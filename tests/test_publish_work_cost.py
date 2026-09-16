import sys
from pathlib import Path
from unittest.mock import patch
import unittest
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from publish_work_cost import snapshots, publish, ONTOLOGY
from tempfile import TemporaryDirectory


class ProjectionTests(unittest.TestCase):
    def test_projection_keeps_request_identity_and_existing_item(self):
        record = {'id': 'response/1', 'session': 'session/1', 'harness': 'codex',
                  'agent': 'worker', 'at': '2026-09-14T01:00:00Z', 'tokens': 12,
                  'model': 'example-model', 'model_source': 'declared',
                  'counts': {'input_uncached': 3, 'cache_read_input': 7,
                             'cache_write_input': 0, 'output': 2},
                  'bead': 'project-1', 'attribution': 'attributed'}
        with patch('publish_work_cost.planes.plane_for', return_value='https://example.org/observed'):
            body, _ = next(snapshots({'errors': [], 'records': [record]}, 'worker'))
        self.assertIn('/session/session%2F1/usage/response%2F1>', body['turtle'])
        self.assertIn('attributedTo> <http://aegis.gastown.local/ontology/project-1>', body['turtle'])
        self.assertNotIn('a <http://aegis.gastown.local/ontology/WorkItem>', body['turtle'])
        self.assertIn('usageModel> "example-model"', body['turtle'])
        self.assertTrue(body['replace_snapshot'])
        self.assertIn('usage-breakdown', str(Path(__file__).resolve().parents[1] / 'shapes/usage-breakdown.shapes.ttl'))

    def test_incomplete_read_cannot_replace_previous_good_graph(self):
        with self.assertRaises(ValueError):
            list(snapshots({'errors': ['source unavailable'], 'records': []}, 'worker'))

    def test_missing_canonical_item_blocks_write(self):
        body = {'snapshot': 'session:s'}
        records = [{'bead': 'project-1', 'attribution': 'attributed'}]
        with TemporaryDirectory() as directory, \
             patch('publish_work_cost.snapshots', return_value=[(body, records)]), \
             patch('publish_work_cost.planes._post', return_value={'rows': []}) as post:
            state = Path(directory) / 'state.json'
            with self.assertRaisesRegex(ValueError, 'INDETERMINATE'):
                publish({}, 'worker', state)
            self.assertEqual(post.call_count, 2)
            self.assertEqual(post.call_args.args[0], '/query')
            self.assertFalse(state.exists())
            self.assertFalse(state.with_suffix('.pending.json').exists())

    def test_over_budget_does_not_issue_any_request(self):
        rows = [{'bead': f'p-{i}', 'attribution': 'attributed'} for i in range(9)]
        with TemporaryDirectory() as directory, \
             patch('publish_work_cost.snapshots', return_value=[({'snapshot': 's'}, rows)]), \
             patch('publish_work_cost.planes._post') as post:
            with self.assertRaisesRegex(ValueError, 'budget'):
                publish({}, 'worker', Path(directory)/'state.json')
            post.assert_not_called()

    def test_one_asserted_preflight_for_multiple_items(self):
        rows = [{'bead': f'p-{i}', 'attribution': 'attributed'} for i in range(8)]
        with TemporaryDirectory() as directory, \
             patch('publish_work_cost.snapshots', return_value=[({'snapshot': 's'}, rows)]), \
             patch('publish_work_cost.planes._post', return_value={'rows': []}) as post:
            with self.assertRaisesRegex(ValueError, 'INDETERMINATE'):
                publish({}, 'worker', Path(directory)/'state.json')
            self.assertEqual(post.call_count, 2)
            self.assertIn('VALUES ?item', post.call_args_list[0].args[1]['query'])
            self.assertEqual(post.call_args_list[0].args[1]['query'].count('FILTER('), 1)
            self.assertEqual(post.call_args.kwargs['client'], 'camayoc-cost')

    def test_transport_sends_stable_client_header(self):
        import io
        from planes import _post
        with patch('planes.urllib.request.urlopen', return_value=io.BytesIO(b'{}')) as request:
            _post('/query', {}, client='camayoc-cost')
            self.assertEqual(dict(request.call_args.args[0].header_items())['X-quipu-client'], 'camayoc-cost')

    def test_stale_attribution_edge_refuses_readback(self):
        record = {'bead': 'p-new', 'attribution': 'attributed', 'session': 's', 'id': 'r', 'tokens': 10}
        body = {'snapshot': 's', 'turtle': 'fixture'}
        from publish_work_cost import ONTOLOGY
        with TemporaryDirectory() as directory, \
             patch('publish_work_cost.snapshots', return_value=[(body, [record])]), \
             patch('publish_work_cost.time.sleep'), \
             patch('publish_work_cost.planes._post', side_effect=[
                 {'rows': [{'item': ONTOLOGY+'p-new'}]}, {'tx_id': 1},
                 {'rows': [{'n': '10', 'item': ONTOLOGY+'p-new'}, {'n': '10', 'item': ONTOLOGY+'p-old'}]}]):
            path = Path(directory)/'state.json'
            with self.assertRaisesRegex(ValueError, 'attribution read-back differs'):
                publish({}, 'worker', path)
            self.assertTrue(path.with_suffix('.pending.json').exists())
            self.assertFalse(path.exists())


class ResilienceTests(unittest.TestCase):
    def run_failure(self, replies, expected, rows=None):
        rows = rows or [{'bead': 'p-one', 'attribution': 'attributed'}]
        with TemporaryDirectory() as directory, \
             patch('publish_work_cost.snapshots', return_value=[({'snapshot': 's'}, rows)]), \
             patch('publish_work_cost.time.sleep'), \
             patch('publish_work_cost.planes._post', side_effect=replies) as post:
            path = Path(directory)/'state.json'
            with self.assertRaisesRegex((ValueError, OSError, RuntimeError), expected):
                publish({}, 'worker', path)
            self.assertTrue(all(call.args[0] == '/query' for call in post.call_args_list))
            self.assertFalse(path.with_suffix('.pending.json').exists())
            return post.call_count

    def test_partial_rows_name_the_missing_item(self):
        self.assertEqual(self.run_failure([{'rows': [{'item': ONTOLOGY+'p-one'}]}], 'p-two',
            [{'bead': b, 'attribution': 'attributed'} for b in ['p-one','p-two']]), 1)

    def test_zero_batch_with_visible_single_item_is_indeterminate(self):
        self.assertEqual(self.run_failure([{'rows': []}, {'rows': [{'t': ONTOLOGY+'WorkItem'}]}],
                                         'INDETERMINATE.*present'), 2)

    def test_408_and_timeout_never_reach_knot(self):
        import planes
        for error in [planes.PlaneError('/query failed: HTTP 408'), TimeoutError('read timed out')]:
            with self.subTest(error=error):
                self.assertEqual(self.run_failure([error], '408|timed out'), 1)

    def test_pending_marker_is_visible_and_preserved(self):
        import json
        with TemporaryDirectory() as directory, \
             patch('publish_work_cost.snapshots', return_value=[({'snapshot': 's'}, [])]), \
             patch('publish_work_cost.planes._post') as post:
            path = Path(directory)/'state.json'
            marker=path.with_suffix('.pending.json')
            marker.write_text('{"snapshot":"s","turtle":"original bytes"}')
            before=marker.read_bytes()
            with self.assertRaisesRegex(ValueError, 'indeterminate'):
                publish({}, 'worker', path)
            post.assert_not_called()
            self.assertEqual(marker.read_bytes(), before)
            self.assertEqual(json.loads(path.with_suffix('.receipt.json').read_text())['status'], 'STALLED')
            self.assertIn('camayoc_cost_projection_stalled 1', path.with_suffix('.prom').read_text())

    def test_slow_indeterminate_write_backs_off_fifteen_minutes(self):
        import json
        with TemporaryDirectory() as directory, \
             patch('publish_work_cost.snapshots', return_value=[({'snapshot': 's'}, [])]), \
             patch('publish_work_cost.time.monotonic', side_effect=[0,0,16]), \
             patch('publish_work_cost.planes._post', side_effect=TimeoutError('write response lost')) as post:
            path=Path(directory)/'state.json'
            with self.assertRaises(TimeoutError):
                publish({}, 'worker', path)
            receipt=json.loads(path.with_suffix('.receipt.json').read_text())
            self.assertEqual(receipt['backoff_seconds'], 900)
            self.assertEqual(receipt['status'], 'STALLED')
            self.assertEqual(post.call_count, 1)

    def test_transport_has_no_default_caller(self):
        import planes
        with self.assertRaises(TypeError):
            planes._post('/query', {})
