"""Source rotation must not overwrite another session's cost observations."""
import json
from pathlib import Path
import sys
import unittest
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import publish_cost_metrics as m


def body(session, bead='task-a', count=10, clock=100):
    identity = {'agent': 'worker', 'harness': 'codex', 'session': session}
    return (m.SOURCE_MARKER + json.dumps(identity) + '\n'
            '# TYPE st_bead_tokens_total gauge\n'
            f'st_bead_tokens_total{{bead="{bead}"}} {count}\n'
            '# TYPE st_bead_cost_coverage gauge\n'
            f'st_bead_cost_coverage{{bead="{bead}"}} 1\n'
            f'st_bead_cost_last_success_timestamp_seconds {clock}\n'
            'st_bead_cost_sync_last_run_timestamp_seconds 200\n'
            'st_bead_cost_paused_for_review 0\n')


class PartitionedPublication(unittest.TestCase):
    def setUp(self):
        self.groups = {}
        def put(job, text, grouping):
            self.groups[tuple(sorted(grouping.items()))] = text
            return True, 'pushed'
        patch = mock.patch.object(m, 'push', side_effect=put)
        self.push = patch.start(); self.addCleanup(patch.stop)

    def test_rotation_preserves_two_sources_and_correction_replaces_only_one(self):
        self.assertTrue(m.publish(body('one'), 'project')[0])
        self.assertTrue(m.publish(body('two', 'task-b', 20), 'project')[0])
        sources = [v for key, v in self.groups.items() if ('session', 'one') in key or ('session', 'two') in key]
        self.assertEqual(len(sources), 2)
        self.assertIn('task-a', ''.join(sources)); self.assertIn('task-b', ''.join(sources))
        self.assertTrue(m.publish(body('one', 'task-c', 5), 'project')[0])
        samples = ''.join(v for key, v in self.groups.items() if any(k == 'session' for k, _ in key))
        self.assertNotIn('task-a', samples)
        self.assertIn('task-b', samples); self.assertIn('task-c', samples)
        root = self.groups[(('rig', 'project'),)]
        self.assertNotIn('st_bead_tokens_total', root)
        self.assertIn('st_bead_cost_paused_for_review', root)

    def test_cached_pause_refresh_routes_to_same_source_without_fresh_success(self):
        self.assertTrue(m.publish(body('one'), 'project')[0])
        refresh = body('one').replace('paused_for_review 0', 'paused_for_review 1')
        self.assertTrue(m.publish(refresh, 'project')[0])
        self.assertEqual(len(self.groups), 2)
        root = self.groups[(('rig', 'project'),)]
        self.assertIn('last_success_timestamp_seconds 100', root)
        self.assertIn('paused_for_review 1', root)
        source = self.groups[tuple(sorted({'rig':'project', 'agent':'worker',
                                          'harness':'codex', 'session':'one'}.items()))]
        self.assertIn('st_bead_cost_source_last_success_timestamp_seconds 100', source)

    def test_legacy_single_rig_payload_is_unchanged(self):
        text = 'st_bead_tokens_total{bead="task-a"} 10\n'
        self.assertTrue(m.publish(text, 'project')[0])
        self.push.assert_called_once_with('st_bead_cost', text, grouping={'rig': 'project'})

    def test_malformed_or_ambiguous_identity_refuses_before_any_network(self):
        for value in ['bad-json', '{}', json.dumps({'agent':'a','harness':'h','session':'/private/path'}),
                      json.dumps({'agent':'a','harness':'h','session':42})]:
            with self.subTest(value=value):
                self.assertFalse(m.publish(m.SOURCE_MARKER + value + '\n', 'project')[0])
        self.assertFalse(m.publish(body('one') + m.SOURCE_MARKER + '{}\n', 'project')[0])
        self.push.assert_not_called()

    def test_sample_failure_is_loud_and_does_not_publish_fresh_status(self):
        self.push.side_effect = None; self.push.return_value = False, 'failed'
        self.assertEqual(m.publish(body('one'), 'project'), (False, 'failed'))
        self.push.assert_called_once()

    def test_status_failure_is_not_reported_as_success(self):
        self.push.side_effect = [(True, 'pushed'), (False, 'status failed')]
        self.assertEqual(m.publish(body('one'), 'project'), (False, 'status failed'))
