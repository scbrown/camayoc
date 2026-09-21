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


if __name__ == '__main__':
    unittest.main()
