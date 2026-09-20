#!/usr/bin/env python3
"""Bounded standing delivery of current authoritative br WorkItems.

One record, at most one write and two reads per tick. The scheduler supplies
an explicit tracker database; this adapter never reads cost attribution.
"""
from __future__ import annotations

import argparse
import fcntl
import json
import os
from pathlib import Path
import subprocess
import time

import camayoc_metrics
from ingest_work_items import BASE_NS, _entity_name, episode_for
import planes

INTERVAL = 60
RECHECK = 6 * 3600
MAX_BODY = 256 * 1024
MAX_ATTEMPTS = 3


def save(path, value):
    temporary = path.with_suffix(path.suffix + '.tmp')
    temporary.write_text(json.dumps(value, sort_keys=True) + '\n')
    temporary.replace(path)


def records_from(payload):
    """Accept both public br list formats, never treat truncation as complete."""
    if isinstance(payload, dict):
        if payload.get('has_more') is not False or payload.get('offset') != 0:
            raise ValueError('tracker list is incomplete')
        records = payload.get('issues')
        if not isinstance(records, list) or payload.get('total') != len(records):
            raise ValueError('tracker list total is unproven')
    else:
        records = payload
    if not isinstance(records, list) or any(not isinstance(r, dict) for r in records):
        raise ValueError('tracker list must contain records')
    if len({r['id'] for r in records}) != len(records):
        raise ValueError('duplicate tracker identifiers')
    return [r for r in records if r.get('status') == 'in_progress' or
            (r.get('status') in ('open', 'blocked') and r.get('assignee'))]


def collect(db):
    result = subprocess.run(['br', '--db', str(db), 'list', '--status', 'open',
                             '--status', 'in_progress', '--status', 'blocked',
                             '--deferred', '--limit', '0', '--json'],
                            check=True, capture_output=True, text=True, timeout=15)
    return records_from(json.loads(result.stdout))


def readback(body, post):
    """A control plus exact direct assertions, always scoped to observed records."""
    graph = body['graph']
    control = post('/query', {'graph': graph, 'query':
        f'SELECT ?s WHERE {{ ?s a ?t . FILTER(?t = <{BASE_NS}WorkItem>) }} LIMIT 1'})
    if not isinstance(control.get('rows'), list) or not control['rows']:
        raise ValueError('WorkItem control unproven')
    item, observation = body['nodes']
    identifier = json.dumps(item['properties']['identifier'])
    value = json.dumps(observation['properties']['observedValue'])
    query = (f'SELECT ?t ?o WHERE {{ <{BASE_NS}{item["name"]}> a ?t ; '
             f'<{BASE_NS}identifier> {identifier} ; <{BASE_NS}sourceKind> "observed" ; '
             f'<{BASE_NS}observes> <{BASE_NS}{observation["name"]}> . '
             f'<{BASE_NS}{observation["name"]}> a ?o ; <{BASE_NS}observedValue> {value} . '
             f'FILTER(?t = <{BASE_NS}WorkItem> && ?o = <{BASE_NS}Observation>) }}')
    found = post('/query', {'graph': graph, 'query': query})
    if not isinstance(found.get('rows'), list) or found.get('truncated'):
        raise ValueError('WorkItem readback unproven')
    return bool(found['rows'])


def tick(records, state, path, *, actor, source, now, post):
    if now < state.get('next_tick', 0):
        return {**state.get('receipt', {'status': 'UNKNOWN'}), 'mode': 'BACKOFF',
                'requests': 0, 'writes': 0, 'verified': 0}
    state['next_tick'] = now + INTERVAL
    entries = state.setdefault('items', {})
    # Preserve pending bodies even when a task closes or its tracker fields change.
    # They are immutable retry evidence, not a cache that can be overwritten.
    current = {}
    invalid = []
    for record in records:
        try:
            item = _entity_name(record['id'])
            body = episode_for(record, actor=actor, source=f'{source}#{item}')
            if len(json.dumps(body, sort_keys=True).encode()) > MAX_BODY:
                raise ValueError('tracker episode exceeds byte cap')
        except (ValueError, TypeError, KeyError, AttributeError) as exc:
            invalid.append({'id': str(record.get('id', 'UNKNOWN'))[:120],
                            'error': type(exc).__name__})
            continue
        current[item] = body
        entry = entries.setdefault(item, {'first_seen': now, 'last_attempt': 0})
        if entry.get('version') != body['name'] and 'due_since' not in entry:
            entry['due_since'] = now
        entry['priority'] = record.get('priority', 4)
        entry['active'] = record.get('status') == 'in_progress'
        entry['created_at'] = record['created_at']
    candidates = []
    for item, entry in entries.items():
        if item not in current and not entry.get('pending'):
            continue
        due = (entry.get('pending') or entry.get('version') != current[item]['name']
               or now - entry.get('verified_at', 0) >= RECHECK)
        if due:
            entry.setdefault('due_since', now)
            if now >= entry.get('not_before', 0):
                candidates.append(item)
    receipt = {'status': 'OK', 'requests': 0, 'writes': 0, 'verified': 0,
               'current': len(current), 'invalid': len(invalid), 'parked': invalid[:20]}
    def request(endpoint, body):
        receipt['requests'] += 1
        if receipt['requests'] > 3:
            raise ValueError('ingress request budget exhausted')
        return post(endpoint, body)
    # Fairness: never-attempted work first, then least recently attempted. A
    # poisoned item cannot occupy the front forever. Current claims win ties.
    candidates.sort(key=lambda i: entries[i].get('created_at', ''), reverse=True)
    candidates.sort(key=lambda i: (entries[i]['last_attempt'],
                                   not entries[i].get('active'),
                                   entries[i].get('priority', 4)))
    if candidates:
        item = candidates[0]
        entry = entries[item]
        receipt['item'] = item
        entry['last_attempt'] = now
        pending = entry.get('pending')
        try:
            if pending:
                # No repeat write until two separately scheduled, controlled
                # absent reads. Never replace this body with a fresher record.
                if pending.get('absent_reads', 0) >= 2 and pending['attempts'] < MAX_ATTEMPTS:
                    pending['attempts'] += 1
                    pending['absent_reads'] = 0
                    save(path, state)
                    receipt['writes'] = 1
                    response = request('/episode', pending['body'])
                    entry['write_receipt'] = {k: response.get(k) for k in ('outcome', 'tx_id', 'count')}
                    if response.get('outcome') not in ('created', 'updated', 'unchanged'):
                        raise ValueError('episode outcome unproven')
                if not readback(pending['body'], request):
                    pending['absent_reads'] = pending.get('absent_reads', 0) + 1
                    raise ValueError('pending tracker episode not readable')
            else:
                body = current[item]
                # An unchanged version needs only a read, including recovery
                # after legitimate retraction. Re-emission uses the same body.
                if entry.get('version') == body['name'] and readback(body, request):
                    entry['verified_at'] = now
                    entry.pop('due_since', None)
                    receipt['verified'] = 1
                else:
                    pending = {'body': body, 'attempts': 0, 'absent_reads': 0}
                    entry['pending'] = pending
                    # A failed periodic recheck used two requests: leave the
                    # exact pending body for later, without a same-tick write.
                    if receipt['requests'] == 0:
                        pending['attempts'] = 1
                        save(path, state)
                        receipt['writes'] = 1
                        response = request('/episode', body)
                        entry['write_receipt'] = {k: response.get(k) for k in ('outcome', 'tx_id', 'count')}
                        if response.get('outcome') not in ('created', 'updated', 'unchanged'):
                            raise ValueError('episode outcome unproven')
                        if not readback(body, request):
                            raise ValueError('tracker episode not readable after write')
                    else:
                        raise ValueError('previously verified tracker episode no longer readable')
            if pending:
                entry['version'] = pending['body']['name']
                entry['verified_at'] = now
                entry.pop('pending', None)
                entry.pop('due_since', None)
                receipt['verified'] = 1
            entry.pop('error', None)
            entry.pop('not_before', None)
        except Exception as exc:
            # Do not print transport response bodies or credential-bearing URLs.
            entry['error'] = type(exc).__name__
            entry['not_before'] = now + (900 if entry.get('pending', {}).get('attempts', 0) >= MAX_ATTEMPTS else INTERVAL)
            receipt.update(status='UNKNOWN', error=type(exc).__name__)
    outstanding = [e for i, e in entries.items() if e.get('pending') or
                   (i in current and e.get('version') != current[i]['name'])]
    receipt['backlog'] = len(outstanding)
    receipt['oldest_seconds'] = max((now - e.get('due_since', now) for e in outstanding), default=0)
    if (invalid or any(e.get('error') for e in outstanding)
            or receipt['oldest_seconds'] > max(900, len(current) * INTERVAL * 2)):
        receipt['status'] = 'UNKNOWN'
    # Retain all indeterminate writes; prune inactive confirmed entries only.
    state['items'] = {i: e for i, e in entries.items() if i in current or e.get('pending')
                      or now - e.get('verified_at', 0) < RECHECK}
    state['receipt'] = receipt
    save(path, state)
    return receipt


def main():
    os.umask(0o077)
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--db', required=True, type=Path)
    parser.add_argument('--state', required=True, type=Path)
    parser.add_argument('--actor', required=True)
    parser.add_argument('--source', required=True, help='stable authoritative tracker provenance URI')
    parser.add_argument('--publish-status', action='store_true')
    args = parser.parse_args()
    args.state.parent.mkdir(parents=True, exist_ok=True)
    with args.state.with_suffix('.lock').open('a') as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            print(json.dumps({'status': 'BUSY', 'requests': 0}))
            return 0
        started = time.time()
        receipt = {'status': 'UNKNOWN'}
        try:
            state = json.loads(args.state.read_text()) if args.state.exists() else {}
            receipt = tick(collect(args.db), state, args.state, actor=args.actor,
                           source=args.source, now=started,
                           post=lambda endpoint, body: planes._post(endpoint, body, client='camayoc-ingress'))
        except Exception as exc:
            receipt['error'] = type(exc).__name__
        save(args.state.with_suffix('.receipt.json'), {'attempted_at': started, **receipt})
        print(json.dumps(receipt, sort_keys=True))
        code = 2 if receipt['status'] == 'UNKNOWN' else 0
        if args.publish_status:
            samples = [
                ('camayoc_workitem_ingress_timestamp_seconds', {}, started),
                ('camayoc_workitem_ingress_exit_status', {}, code),
                ('camayoc_workitem_ingress_backlog', {}, receipt.get('backlog', -1)),
                ('camayoc_workitem_ingress_oldest_seconds', {}, receipt.get('oldest_seconds', -1)),
            ]
            ok, why = camayoc_metrics.push('camayoc_workitem_ingress',
                camayoc_metrics.exposition(samples), grouping={'producer': args.actor})
            if not ok:
                print(why)
                code = 2
        return code


if __name__ == '__main__':
    raise SystemExit(main())
