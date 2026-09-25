"""Standing tracker delivery is bounded, verifiable and safe after lost replies."""
import copy
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import sync_work_items as sync

RECORD = {'id': 'proj-a', 'title': 'Current work', 'created_at': '2026-09-20T00:00:00Z',
          'status': 'in_progress', 'assignee': 'worker', 'priority': 1}


class Delivery(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / 'state.json'
        self.state = {}
        self.calls = []
        self.present = True
        self.control = True
        self.lost = False

    def post(self, endpoint, body):
        self.calls.append((endpoint, copy.deepcopy(body)))
        if endpoint == '/episode':
            # Write-ahead persistence must precede every write, including retry.
            saved = json.loads(self.path.read_text())
            self.assertEqual(body, saved['items'][body['nodes'][0]['name']]['pending']['body'])
            if self.lost:
                raise TimeoutError('lost response')
            return {'outcome': 'unchanged', 'count': 0}
        if 'LIMIT 1' in body['query']:
            return {'rows': [{'s': 'control'}] if self.control else []}
        return {'rows': [{'t': 'WorkItem', 'o': 'Observation'}] if self.present else []}

    def tick(self, records=None, now=1000):
        return sync.tick([RECORD] if records is None else records, self.state, self.path,
                         actor='tracker', source='br:authoritative', now=now, post=self.post)

    def test_one_record_write_plus_two_reads_and_named_plane(self):
        result = self.tick([RECORD, {**RECORD, 'id': 'proj-b'}])
        self.assertEqual(3, result['requests'])
        self.assertEqual(1, result['verified'])
        self.assertEqual(1, result['backlog'])
        self.assertEqual(['/episode', '/query', '/query'], [p for p, _ in self.calls])
        self.assertTrue(all(b['graph'] == sync.planes.plane_for('observed') for _, b in self.calls))
        self.assertEqual('br:authoritative#proj-a', self.calls[0][1]['source'])
        self.assertIn('FILTER(?t =', self.calls[-1][1]['query'])
        self.assertIn('observedValue', self.calls[-1][1]['query'])

    def test_unchanged_success_needs_readback_not_count(self):
        self.assertEqual('OK', self.tick()['status'])
        self.assertNotIn('pending', self.state['items']['proj-a'])

    def test_unchanged_response_with_missing_data_is_not_success(self):
        self.present = False
        self.assertEqual('UNKNOWN', self.tick()['status'])
        self.assertIn('pending', self.state['items']['proj-a'])
        self.assertNotIn('version', self.state['items']['proj-a'])

    def test_failed_control_never_authorizes_retry(self):
        self.control = False
        self.tick()
        for now in (1060, 1120, 1180):
            self.tick(now=now)
        self.assertEqual(1, len([p for p, _ in self.calls if p == '/episode']))
        self.assertEqual(0, self.state['items']['proj-a']['pending']['absent_reads'])

    def test_timeout_landed_reconciles_without_repost(self):
        self.lost = True
        self.assertEqual('UNKNOWN', self.tick()['status'])
        self.lost = False
        self.assertEqual('OK', self.tick(now=1060)['status'])
        self.assertEqual(1, len([p for p, _ in self.calls if p == '/episode']))

    def test_two_absent_reads_then_same_body_retry_despite_tracker_change(self):
        self.lost = True
        self.tick()
        original = self.calls[0][1]
        self.lost = False
        self.present = False
        changed = [{**RECORD, 'title': 'Changed', 'updated_at': '2026-09-21T00:00:00Z'}]
        self.tick(changed, now=1060)
        self.tick(changed, now=1120)
        self.assertEqual(1, len([p for p, _ in self.calls if p == '/episode']))
        self.present = True
        result = self.tick(changed, now=1180)
        self.assertEqual(3, result['requests'])
        writes = [b for p, b in self.calls if p == '/episode']
        self.assertEqual([original, original], writes)
        self.assertEqual(1, result['backlog'])  # new version still needs delivery

    def test_pending_survives_task_close(self):
        self.lost = True
        self.tick()
        self.lost = False
        self.assertEqual(1, self.tick([], now=1060)['verified'])

    def test_poisoned_item_does_not_block_other_item(self):
        self.lost = True
        records = [RECORD, {**RECORD, 'id': 'proj-b'}]
        self.tick(records)
        self.lost = False
        self.present = False
        self.assertEqual('proj-a', self.tick(records, now=1060)['item'])
        self.present = True
        result = self.tick(records, now=1120)
        self.assertEqual('proj-b', result['item'])
        self.assertEqual(1, result['verified'])

    def test_pending_recovery_beats_large_fresh_backlog_without_repost(self):
        self.lost = True
        self.tick()
        self.lost = False
        records = [RECORD] + [{**RECORD, 'id': f'proj-new-{i}'} for i in range(250)]
        result = self.tick(records, now=1060)
        self.assertEqual('proj-a', result['item'])
        self.assertEqual(2, result['requests'])
        self.assertEqual(0, result['writes'])
        self.assertEqual(1, result['verified'])
        self.assertEqual(0, result['indeterminate'])

    def test_recovery_control_failure_does_not_starve_fresh_work(self):
        self.lost = True
        self.tick()
        self.lost = False
        self.control = False
        records = [RECORD, {**RECORD, 'id': 'proj-b'}]
        self.assertEqual('proj-a', self.tick(records, now=1060)['item'])
        self.control = True
        result = self.tick(records, now=1120)
        self.assertEqual('proj-b', result['item'])
        self.assertEqual('DEGRADED', result['status'])

    def test_controlled_retry_does_not_wait_behind_fresh_backlog(self):
        self.lost = True
        self.tick()
        original = self.calls[0][1]
        pending = self.state['items']['proj-a']['pending']
        pending['absent_reads'] = 2
        self.lost = False
        records = [RECORD] + [{**RECORD, 'id': f'proj-new-{i}'} for i in range(250)]
        result = self.tick(records, now=1060)
        self.assertEqual('proj-a', result['item'])
        self.assertEqual(1, result['writes'])
        self.assertEqual(original, self.calls[-3][1])
        self.assertEqual('OK', result['status'])

    def test_backoff_has_no_requests(self):
        self.tick()
        before = len(self.calls)
        self.assertEqual('BACKOFF', self.tick(now=1059)['mode'])
        self.assertEqual(before, len(self.calls))

    def test_indeterminate_receipt_degrades_during_other_success(self):
        self.lost = True
        records = [RECORD, {**RECORD, 'id': 'proj-b'}]
        self.tick(records)
        self.assertEqual('UNKNOWN', self.tick(now=1059)['status'])
        self.lost = False
        self.present = False
        self.assertEqual('UNKNOWN', self.tick(records, now=1060)['status'])
        self.present = True
        result = self.tick(records, now=1120)
        self.assertEqual(1, result['verified'])
        self.assertEqual('DEGRADED', result['status'])
        self.assertEqual(1, result['indeterminate'])

    def test_successful_version_not_reposted_and_recheck_is_read_only(self):
        self.tick()
        self.assertEqual(0, self.tick(now=1060)['requests'])
        self.assertEqual(2, self.tick(now=1000 + sync.RECHECK)['requests'])
        self.assertEqual(1, len([p for p, _ in self.calls if p == '/episode']))

    def test_failed_periodic_control_stays_visible_during_other_success(self):
        self.tick()
        self.control = False
        self.tick(now=1000 + sync.RECHECK)
        self.control = True
        result = self.tick([RECORD, {**RECORD, 'id': 'proj-b'}], now=1060 + sync.RECHECK)
        self.assertEqual(1, result['verified'])
        self.assertEqual('UNKNOWN', result['status'])
        self.assertEqual(1, result['backlog'])

    def test_retraction_does_not_repost_in_same_tick(self):
        self.tick()
        self.present = False
        result = self.tick(now=1000 + sync.RECHECK)
        self.assertEqual(2, result['requests'])
        self.assertEqual(0, result['writes'])
        self.assertEqual('UNKNOWN', result['status'])

    def test_retry_attempt_cap(self):
        self.present = False
        self.tick()
        for now in range(1060, 4000, 60):
            result = self.tick(now=now)
            self.assertLessEqual(result['requests'], 3)
        self.assertEqual(3, len([p for p, _ in self.calls if p == '/episode']))
        self.assertIn('pending', self.state['items']['proj-a'])

    def test_unknown_query_format_is_not_absence(self):
        with patch.object(self, 'post', return_value={}):
            self.assertEqual('UNKNOWN', self.tick()['status'])
        self.assertEqual(0, self.state['items']['proj-a']['pending']['absent_reads'])

    def test_bounds_and_unsafe_ids_before_network(self):
        for record in ({**RECORD, 'id': 'unsafe/>}'}, {**RECORD, 'title': 'x' * sync.MAX_BODY}):
            self.state = {}
            result = self.tick([record])
            self.assertEqual('UNKNOWN', result['status'])
            self.assertEqual(1, result['invalid'])
        self.assertEqual([], self.calls)

    def test_malformed_record_does_not_block_good_record(self):
        result = self.tick([{**RECORD, 'id': 'proj-bad', 'title': ''}, RECORD])
        self.assertEqual(1, result['verified'])
        self.assertEqual(1, result['invalid'])
        self.assertEqual('UNKNOWN', result['status'])

    def test_stale_backlog_fails_even_with_successful_item(self):
        records = [RECORD, {**RECORD, 'id': 'proj-b'}]
        self.tick(records)
        self.assertEqual('OK', self.tick(records, now=2000)['status'])
        # A permanently unresolved item remains visible even during its backoff.
        self.state['items']['proj-a']['pending'] = {
            'body': self.calls[0][1], 'attempts': 3, 'absent_reads': 2}
        self.state['items']['proj-a'].update(due_since=1000, not_before=10000)
        self.assertEqual('UNKNOWN', self.tick(records, now=2060)['status'])


class TrackerFormats(unittest.TestCase):
    def test_old_list_and_complete_envelope(self):
        self.assertEqual([RECORD], sync.records_from([RECORD]))
        self.assertEqual([RECORD], sync.records_from({'issues': [RECORD], 'total': 1,
                                                    'offset': 0, 'has_more': False}))

    def test_truncation_error_and_ambiguous_formats_refused(self):
        for value in ({}, {'issues': [RECORD], 'total': 2, 'offset': 0, 'has_more': False},
                      {'issues': [RECORD], 'total': 1, 'offset': 1, 'has_more': False},
                      {'issues': [RECORD], 'total': 1, 'offset': 0, 'has_more': True},
                      [RECORD, RECORD], None):
            with self.assertRaises((ValueError, KeyError)):
                sync.records_from(value)

    def test_scope_current_assigned_including_blocked_not_closed_or_unassigned(self):
        variants = [RECORD, {**RECORD, 'id': 'proj-open', 'status': 'open'},
                    {**RECORD, 'id': 'proj-blocked', 'status': 'blocked'},
                    {**RECORD, 'id': 'proj-closed', 'status': 'closed'},
                    {**RECORD, 'id': 'proj-unassigned', 'status': 'open', 'assignee': None}]
        self.assertEqual(['proj-a', 'proj-open', 'proj-blocked'],
                         [r['id'] for r in sync.records_from(variants)])

    def test_public_cli_explicit_authority_no_export(self):
        with patch.object(sync.subprocess, 'run') as run:
            run.return_value.stdout = json.dumps([RECORD])
            sync.collect(Path('/tmp/fixture.db'))
        argv = run.call_args.args[0]
        self.assertEqual(['br', '--db', '/tmp/fixture.db', 'list'], argv[:4])
        self.assertIn('--deferred', argv)
        self.assertEqual('0', argv[argv.index('--limit') + 1])


class Transitions(unittest.TestCase):
    """aegis-3b3nrb: closes and blocker changes reach the graph, promptly."""

    def fake_br(self, current, by_id):
        calls = []

        def run(argv, **kw):
            calls.append(argv)
            out = type('R', (), {})()
            if '--id' in argv:
                wanted = [argv[i + 1] for i, a in enumerate(argv) if a == '--id']
                out.stdout = json.dumps([by_id[i] for i in wanted if i in by_id])
            else:
                out.stdout = json.dumps(current)
            return out
        return run, calls

    def test_a_tracked_item_that_closed_is_fetched_as_trailing(self):
        closed = {**RECORD, 'id': 'proj-done', 'status': 'closed', 'closed_at': '2026-09-24T04:16:21Z'}
        run, calls = self.fake_br([RECORD], {'proj-done': closed})
        records = sync.collect(Path('/tmp/f.db'), tracked=['proj-a', 'proj-done'], run=run)
        got = {r['id']: r for r in records}
        self.assertEqual('closed', got['proj-done']['status'])
        self.assertTrue(got['proj-done']['trailing'])
        self.assertNotIn('trailing', got['proj-a'])
        self.assertTrue(any('--all' in c for c in calls), 'closed records need --all')

    def test_an_unassigned_blocker_of_current_work_is_fetched(self):
        blocker = {**RECORD, 'id': 'proj-dep', 'status': 'open', 'assignee': None}
        run, _ = self.fake_br([{**RECORD, 'blocked_on': ['proj-dep']}], {'proj-dep': blocker})
        with patch('ingest_work_items.attach_blocked_on', lambda records, db: []):
            records = sync.collect(Path('/tmp/f.db'), run=run)
        self.assertIn('proj-dep', {r['id'] for r in records})

    def test_a_change_goes_ahead_of_the_recheck_rotation(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        path = Path(temp.name) / 'state.json'
        a, b = {**RECORD, 'id': 'proj-a'}, {**RECORD, 'id': 'proj-b'}
        post = lambda endpoint, body: ({'outcome': 'created'} if endpoint == '/episode'
                                       else {'rows': [{'s': 'c', 't': 'WorkItem', 'o': 'Observation'}]})
        state = {}
        for now in (1000, 1060):  # both written and verified
            sync.tick([a, b], state, path, actor='t', source='br:x', now=now, post=post)
        # b changes; a has the OLDER last_attempt and is due for its recheck
        b2 = {**b, 'status': 'closed', 'updated_at': '2026-09-25T00:00:00Z'}
        later = 1060 + sync.RECHECK + 120
        receipt = sync.tick([a, b2], state, path, actor='t', source='br:x', now=later, post=post)
        self.assertEqual('proj-b', receipt['item'], 'the transition must not wait behind a recheck')

    def test_a_closed_trailing_item_is_final_once_verified(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        path = Path(temp.name) / 'state.json'
        done = {**RECORD, 'id': 'proj-done', 'status': 'closed', 'trailing': True}
        post = lambda endpoint, body: ({'outcome': 'created'} if endpoint == '/episode'
                                       else {'rows': [{'s': 'c', 't': 'WorkItem', 'o': 'Observation'}]})
        state = {}
        sync.tick([done], state, path, actor='t', source='br:x', now=1000, post=post)
        self.assertTrue(state['items']['proj-done'].get('final'))

    def test_dependencies_are_looked_up_only_when_updated_at_moves(self):
        looked = []

        def fake_attach(records, db):
            for r in records:
                looked.append(r['id'])
                r['blocked_on'] = ['proj-dep']
        a = {**RECORD, 'dependency_count': 1, 'updated_at': 't1'}
        cache = {}
        with patch('ingest_work_items.attach_blocked_on', fake_attach):
            sync.attach_deps([dict(a)], None, cache)
            again = dict(a)
            sync.attach_deps([again], None, cache)          # same updated_at: cached
            sync.attach_deps([{**a, 'updated_at': 't2'}], None, cache)  # moved: looked up
        self.assertEqual(['proj-a', 'proj-a'], looked)
        self.assertEqual(['proj-dep'], again['blocked_on'])


if __name__ == '__main__':
    unittest.main()
