import sys
from pathlib import Path
from unittest.mock import patch
import unittest
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from publish_work_cost import snapshots, publish
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
             patch('publish_work_cost.planes._post', return_value={'result': False}) as post:
            state = Path(directory) / 'state.json'
            with self.assertRaisesRegex(ValueError, 'canonical WorkItem unavailable'):
                publish({}, 'worker', state)
            self.assertEqual(post.call_count, 1)
            self.assertEqual(post.call_args.args[0], '/query')
            self.assertFalse(state.exists())
            self.assertFalse(state.with_suffix('.pending.json').exists())
