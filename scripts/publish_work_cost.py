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


def publish(result, actor, state_path):
    state = json.loads(state_path.read_text()) if state_path.exists() else {}
    transactions = []
    pending = []
    for body, records in snapshots(result, actor):
        encoded = json.dumps(body, sort_keys=True)
        digest = hashlib.sha256(encoded.encode()).hexdigest()
        if state.get(body['snapshot']) == digest:
            continue
        items = sorted({r['bead'] for r in records if r['attribution'] == 'attributed'})
        if (len(items) > MAX_WORK_ITEMS or len(records) > MAX_RECORDS
                or len(encoded.encode()) > MAX_BODY_BYTES):
            raise ValueError('cost snapshot exceeds reviewed item/record/byte budget; narrow sources')
        pending.append((body, records, digest, items))
    if len(pending) > MAX_SNAPSHOTS:
        raise ValueError('cost run exceeds reviewed snapshot budget; narrow sources')
    # Preflight the complete invocation BEFORE any network access. Backfills
    # must be explicitly partitioned; no N-session query burst or partial run.
    last_request = None

    def post(endpoint, body):
        nonlocal last_request
        if last_request is not None:
            time.sleep(max(0, 1 - (time.monotonic() - last_request)))
        last_request = time.monotonic()
        return planes._post(endpoint, body, client='camayoc-cost')

    for body, records, digest, items in pending:
        key = body['snapshot']
        marker = state_path.with_suffix('.pending.json')
        if marker.exists():
            raise ValueError('previous graph write indeterminate; reconcile pending snapshot before retry')
        if items:
            # One anchored, bounded conjunction. Every item must be DIRECTLY
            # typed: constant-type patterns infer and would weaken this gate.
            patterns = ' '.join(f'<{ONTOLOGY}{item}> a ?t{i} . '
                                f'FILTER(?t{i} = <{ONTOLOGY}WorkItem>)'
                                for i, item in enumerate(items))
            check = post('/query', {'query': 'ASK { ' + patterns + ' }'})
            if check.get('result') is not True:
                raise ValueError('canonical WorkItem unavailable; run tracker ingress first')
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
        items_seen = {row['item'] for row in rows if row.get('item')}
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
    args = ap.parse_args()
    try:
        method = json.loads(args.method.read_text())
        if method.get('system') != 'session_usage' or method.get('query') != 'work_cost':
            raise ValueError('expected session_usage/work_cost method')
        result = retrieve(method['params'])
        answer = publish(result, args.actor, args.state) if args.post else [b for b, _ in snapshots(result, args.actor)]
        print(json.dumps(answer, sort_keys=True))
        return 0
    except (OSError, ValueError, planes.PlaneError) as exc:
        print(f'cost publication UNKNOWN: {exc}', file=sys.stderr)
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
