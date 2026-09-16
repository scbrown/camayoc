#!/usr/bin/env python3
"""Publish parser-owned request facts into Camayoc's observed plane.

Reads the SAME result used by retrieve_metric.py, never st-supplied counts.
A per-session snapshot replaces only this producer's facts, so a corrected
focus assignment cannot leave two work items charged for the same request.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import sys
import time
from urllib.parse import quote

from ingest_session_usage import BASE, ONTOLOGY, READERS, emit
import planes
from work_cost import retrieve

MAX_SNAPSHOTS = 1
MAX_WORK_ITEMS = 8
MAX_RECORDS = 1000
MAX_BODY_BYTES = 4 * 1024 * 1024

PROPERTIES = {'input_uncached': 'inputTokensUncached', 'cache_read_input': 'cacheReadInputTokens',
              'cache_write_input': 'cacheWriteInputTokens', 'output': 'outputTokens'}


def snapshots(result, actor):
    if result['errors']:
        raise ValueError('cannot replace graph snapshot with incomplete source reads')
    sessions = {}
    for record in result['records']:
        key = (record['harness'], record['session'], record['agent'])
        sessions.setdefault(key, []).append(record)
    for (fmt, session_id, principal), records in sorted(sessions.items()):
        out = ['@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .']
        emit(session_id, principal, READERS[fmt][1], fmt, records, out)
        session_iri = f'{BASE}session/{quote(session_id, safe="")}'
        items = set()
        for record in records:
            iri = f'{session_iri}/usage/{quote(record["id"], safe="")}'
            out.append(f'<{iri}> <{ONTOLOGY}usageHarness> {json.dumps(fmt)} .')
            if record['model']:
                out.append(f'<{iri}> <{ONTOLOGY}usageModel> {json.dumps(record["model"])} .')
                out.append(f'<{iri}> <{ONTOLOGY}usageModelSource> {json.dumps(record["model_source"])} .')
            for kind, value in record['counts'].items():
                if value is not None:
                    out.append(f'<{iri}> <{ONTOLOGY}{PROPERTIES[kind]}> {value} .')
            if record['attribution'] == 'attributed':
                item = record['bead']
                # Canonical tracker mapper uses the exact stable item ID.
                if not item or any(c not in 'abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-_.' for c in item):
                    raise ValueError('unsafe tracker identifier')
                out.append(f'<{iri}> <{ONTOLOGY}attributedTo> <{ONTOLOGY}{item}> .')
                items.add(item)
        # WorkItem types come from ingest_work_items.py in this SAME observed
        # plane. Never copy them into a replaceable cost snapshot: retracting
        # that snapshot must not disturb canonical tracker identity facts.
        turtle = '\n'.join(out)
        yield {'turtle': turtle, 'actor': actor, 'source': f'camayoc-session-usage:{fmt}:{session_id}',
               'graph': planes.plane_for('observed'), 'replace_snapshot': True,
               'snapshot': f'camayoc-session-usage:{fmt}:{session_id}',
               'shapes': (Path(__file__).resolve().parents[1] / 'shapes/usage-breakdown.shapes.ttl').read_text()}, records


def expand_item(value):
    # The query endpoint compacts this registered namespace on the wire.
    # Normalize only the namespace we own; unknown prefixes stay mismatches.
    return ONTOLOGY + value[len('aegis:'):] if value.startswith('aegis:') else value


class OperatorAction(ValueError):
    """A reviewed budget requires narrower operator-selected sources."""


def _atomic(path, text):
    temporary = path.with_suffix(path.suffix + '.tmp')
    temporary.write_text(text)
    temporary.replace(path)


def publish(result, actor, state_path, *, push_status=False):
    """Every attempt leaves a receipt and status metrics, including failures."""
    receipt_path = state_path.with_suffix('.receipt.json')
    receipt = {'attempted_at': time.time(), 'status': 'UNKNOWN', 'requests': 0,
               'request_seconds': 0, 'items_per_snapshot': [], 'records_per_snapshot': [],
               'body_bytes_per_snapshot': [], 'readback': 'sampled-last-record'}
    try:
        previous = json.loads(receipt_path.read_text()) if receipt_path.exists() else {}
        if previous.get('next_request_after', 0) > time.time():
            receipt['next_request_after'] = previous['next_request_after']
            for field in ('items_per_snapshot', 'records_per_snapshot', 'body_bytes_per_snapshot'):
                receipt[field] = previous.get(field, [])
            receipt['dimensions_source'] = 'previous_attempt'
            raise OperatorAction('BACKOFF: previous request budget cooldown has not elapsed')
        answer = _publish(result, actor, state_path, receipt)
        receipt['status'] = 'OK'
        return answer
    except OperatorAction as exc:
        receipt.update(status='STALLED' if state_path.with_suffix('.pending.json').exists() else 'OPERATOR_ACTION',
                       detail=str(exc))
        raise
    except (OSError, ValueError, planes.PlaneError) as exc:
        receipt.update(status='STALLED' if state_path.with_suffix('.pending.json').exists() else 'UNKNOWN',
                       detail=str(exc))
        raise
    finally:
        receipt['finished_at'] = time.time()
        if receipt['requests']:
            slow = receipt.get('knot_seconds', 0) > 10 or receipt['request_seconds'] > 15
            receipt['next_request_after'] = receipt['finished_at'] + 900 if slow else receipt['first_request_at'] + 60
            receipt['backoff_seconds'] = 900 if slow else 60
        reason = ('pending' if receipt['status'] == 'STALLED' else
                  'backoff' if receipt.get('detail', '').startswith('BACKOFF:') else
                  'budget' if receipt['status'] == 'OPERATOR_ACTION' else
                  'error' if receipt['status'] == 'UNKNOWN' else 'none')
        receipt['reason'] = reason
        if receipt['records_per_snapshot']:
            history_path = state_path.with_suffix('.budget.json')
            history = json.loads(history_path.read_text()) if history_path.exists() else {'runs': 0}
            history['runs'] += int(bool(receipt.get('preflight_reached')))
            for key in ('items', 'records', 'body_bytes'):
                field = key + '_per_snapshot'
                history['max_' + key] = max(history.get('max_' + key, 0), *receipt[field], 0)
            # Retain measured runs for the later min/median/max review. Older
            # histories may have only maxima: never invent their missing samples.
            samples = history.setdefault('samples', [])
            if receipt.get('preflight_reached') and len(samples) < 20:
                samples.append({
                    'run': history['runs'],
                    'attempted_at': receipt['attempted_at'],
                    **{key: max(receipt[key + '_per_snapshot'], default=0)
                       for key in ('items', 'records', 'body_bytes')},
                })
            history['review_due'] = history['runs'] >= 20
            _atomic(history_path, json.dumps(history, sort_keys=True))
            receipt['budget_history'] = history
        _atomic(receipt_path, json.dumps(receipt, sort_keys=True))
        history_path = state_path.with_suffix('.budget.json')
        history = json.loads(history_path.read_text()) if history_path.exists() else {'runs': 0}
        metrics = '\n'.join([
            '# TYPE camayoc_cost_projection_stalled gauge',
            f'camayoc_cost_projection_stalled{{reason="{reason}"}} {int(reason in {"pending", "budget", "error"})}', 
            '# TYPE camayoc_cost_preflight_runs gauge',
            f"camayoc_cost_preflight_runs {history['runs']}",
            '# TYPE camayoc_cost_budget_review_due gauge',
            f"camayoc_cost_budget_review_due {int(history['runs'] >= 20)}",
            '# TYPE camayoc_cost_projection_ok gauge',
            f"camayoc_cost_projection_ok {int(receipt['status'] == 'OK')}",
            '# TYPE camayoc_cost_projection_last_attempt_timestamp_seconds gauge',
            f"camayoc_cost_projection_last_attempt_timestamp_seconds {receipt['attempted_at']}", ''])
        _atomic(state_path.with_suffix('.prom'), metrics)
        print('cost publication receipt: ' + json.dumps(receipt, sort_keys=True), file=sys.stderr)
        if push_status:
            from camayoc_metrics import push
            ok, why = push('camayoc_cost_projection', metrics, grouping={'producer': actor})
            print('cost status metrics: ' + why, file=sys.stderr)
            if not ok:
                raise RuntimeError('cost status metrics were not delivered: ' + why)


def _publish(result, actor, state_path, receipt):
    if state_path.with_suffix('.pending.json').exists():
        raise ValueError('previous graph write indeterminate; reconcile pending snapshot before retry')
    state = json.loads(state_path.read_text()) if state_path.exists() else {}
    transactions = []
    pending = []
    for body, records in snapshots(result, actor):
        encoded = json.dumps(body, sort_keys=True)
        digest = hashlib.sha256(encoded.encode()).hexdigest()
        items = sorted({r['bead'] for r in records if r['attribution'] == 'attributed'})
        receipt['items_per_snapshot'].append(len(items))
        receipt['records_per_snapshot'].append(len(records))
        receipt['body_bytes_per_snapshot'].append(len(encoded.encode()))
        if state.get(body['snapshot']) == digest:
            continue
        if (len(items) > MAX_WORK_ITEMS or len(records) > MAX_RECORDS
                or len(encoded.encode()) > MAX_BODY_BYTES):
            raise OperatorAction('cost snapshot exceeds reviewed item/record/byte budget; narrow sources')
        pending.append((body, records, digest, items))
    if len(pending) > MAX_SNAPSHOTS:
        raise OperatorAction('cost run exceeds reviewed snapshot budget; narrow sources')
    # Preflight the complete invocation BEFORE any network access. Backfills
    # must be explicitly partitioned; no N-session query burst or partial run.
    last_request = None

    def post(endpoint, body):
        nonlocal last_request
        if endpoint == '/query':
            # WorkItem ingress and usage snapshots share this named plane.
            # An omitted graph queries ROOT and falsely reports them absent.
            body = {**body, 'graph': planes.plane_for('observed')}
        if last_request is not None:
            time.sleep(max(0, 1 - (time.monotonic() - last_request)))
        last_request = time.monotonic()
        if receipt['requests'] >= 3:
            raise OperatorAction('cost request budget exhausted')
        receipt.setdefault('first_request_at', time.time())
        receipt['requests'] += 1
        started = time.monotonic()
        try:
            return planes._post(endpoint, body, client='camayoc-cost')
        finally:
            elapsed = time.monotonic() - started
            receipt['request_seconds'] += elapsed
            if endpoint == '/knot':
                receipt['knot_seconds'] = elapsed

    for body, records, digest, items in pending:
        key = body['snapshot']
        marker = state_path.with_suffix('.pending.json')
        if marker.exists():
            raise ValueError('previous graph write indeterminate; reconcile pending snapshot before retry')
        if items:
            receipt['preflight_reached'] = True
            # Named rows preserve which item is missing; FILTER proves direct
            # typing without inference. No conjunction across distinct items.
            values = ' '.join(f'<{ONTOLOGY}{item}>' for item in items)
            check = post('/query', {'query': f'SELECT ?item WHERE {{ VALUES ?item {{ {values} }} '
                          f'?item a ?t . FILTER(?t = <{ONTOLOGY}WorkItem>) }}'})
            if not isinstance(check.get('rows'), list):
                raise ValueError('INDETERMINATE: canonical preflight returned no rows field')
            found = {expand_item(row['item']) for row in check['rows'] if row.get('item')}
            expected = {ONTOLOGY + item for item in items}
            if not found:
                control = post('/query', {'query': f'SELECT ?t WHERE {{ <{ONTOLOGY}{items[0]}> a ?t . '
                                         f'FILTER(?t = <{ONTOLOGY}WorkItem>) }}'})
                # Even two zeros cannot establish absence with an unproven
                # control. Never prescribe re-ingestion on this arm.
                raise ValueError('INDETERMINATE: zero-of-N canonical preflight; single-item control '
                                 + ('present' if control.get('rows') else 'unproven'))
            if found != expected:
                missing = sorted(item.removeprefix(ONTOLOGY) for item in expected - found)
                raise ValueError('canonical WorkItem unavailable: ' + ', '.join(missing))
        # Store an indeterminate marker BEFORE sending. A failed write is not
        # retried automatically; the exact snapshot and read-back must be
        # reconciled by the operator before clearing this marker.
        marker = state_path.with_suffix('.pending.json')
        if marker.exists():
            raise ValueError('previous graph write indeterminate; reconcile pending snapshot before retry')
        marker.write_text(json.dumps(body, sort_keys=True))
        response = post('/knot', body)
        if response.get('conforms') is False or not response.get('tx_id'):
            raise ValueError('graph refused cost snapshot')
        # A response proves acceptance; separately check one exact request's
        # total before advancing the cursor. No blind retry on failure.
        record = records[-1]
        iri = f'{BASE}session/{quote(record["session"], safe="")}/usage/{quote(record["id"], safe="")}'
        check = post('/query', {'query': f'SELECT ?n ?item WHERE {{ <{iri}> <{ONTOLOGY}tokensConsumed> ?n . OPTIONAL {{ <{iri}> <{ONTOLOGY}attributedTo> ?item }} }}'})
        rows = check.get('rows', [])
        if not any(str(row.get('n')) == str(record['tokens']) for row in rows):
            raise ValueError('cost snapshot accepted but read-back unproven')
        items_seen = {expand_item(row['item']) for row in rows if row.get('item')}
        expected = {ONTOLOGY + record['bead']} if record['attribution'] == 'attributed' else set()
        if items_seen != expected:
            raise ValueError('cost snapshot attribution read-back differs; reconcile pending snapshot')
        state[key] = digest
        temporary = state_path.with_suffix('.tmp')
        temporary.write_text(json.dumps(state, sort_keys=True))
        temporary.replace(state_path)
        marker.unlink()
        transactions.append(response['tx_id'])
    return transactions


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('method', type=Path)
    ap.add_argument('--actor', required=True)
    ap.add_argument('--state', type=Path, required=True)
    ap.add_argument('--post', action='store_true')
    ap.add_argument('--publish-status', action='store_true', help='push attempt status, including stalled attempts')
    args = ap.parse_args()
    try:
        method = json.loads(args.method.read_text())
        if method.get('system') != 'session_usage' or method.get('query') != 'work_cost':
            raise ValueError('expected session_usage/work_cost method')
        result = retrieve(method['params'])
        answer = publish(result, args.actor, args.state, push_status=args.publish_status) if args.post else [b for b, _ in snapshots(result, args.actor)]
        print(json.dumps(answer, sort_keys=True))
        return 0
    except (OSError, ValueError, RuntimeError) as exc:
        print(f'cost publication UNKNOWN: {exc}', file=sys.stderr)
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
