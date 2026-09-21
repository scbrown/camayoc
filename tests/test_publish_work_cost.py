import sys
from pathlib import Path
from unittest.mock import patch
import unittest
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from publish_work_cost import snapshots, publish, record_budget, ONTOLOGY
from tempfile import TemporaryDirectory


class DistinctBudgetTests(unittest.TestCase):
    def measurement(self, records=221, *, reached=True):
        return {'attempted_at': 100, 'preflight_reached': reached,
                'items_per_snapshot': [3], 'records_per_snapshot': [records],
                'body_bytes_per_snapshot': [528011]}

    def test_repeated_shape_does_not_satisfy_review(self):
        history = {}
        for _ in range(100):
            record_budget(history, self.measurement())
        self.assertEqual(history['runs'], 100)
        self.assertEqual(len(history['samples']), 20)
        self.assertEqual(history['distinct_shapes'], 1)
        self.assertFalse(history['review_due'])

    def test_twenty_distinct_shapes_satisfy_review_and_storage_is_bounded(self):
        history = {}
        for records in range(1, 20):
            record_budget(history, self.measurement(records))
        self.assertFalse(history['review_due'])
        record_budget(history, self.measurement(20))
        self.assertTrue(history['review_due'])
        for records in range(21, 101):
            record_budget(history, self.measurement(records))
        self.assertEqual(history['distinct_shapes'], 20)
        self.assertTrue(history['distinct_shapes_saturated'])
        self.assertEqual(history['max_records'], 100)
        self.assertEqual([x['records'] for x in history['distinct_samples']], list(range(1, 21)))

    def test_legacy_samples_migrate_without_inventing_missing_shapes(self):
        import copy
        samples = [{'run': n, 'attempted_at': n, 'items': 3,
                    'records': 221, 'body_bytes': 528011} for n in range(3, 23)]
        history = {'runs': 371, 'samples': copy.deepcopy(samples),
                   'max_records': 999, 'review_due': True}
        empty = {'records_per_snapshot': []}
        record_budget(history, empty)
        self.assertEqual(history['runs'], 371)
        self.assertEqual(history['samples'], samples)
        self.assertEqual(history['max_records'], 999)
        self.assertEqual(history['distinct_shapes'], 1)
        self.assertFalse(history['review_due'])
        before = copy.deepcopy(history)
        record_budget(history, empty)
        self.assertEqual(history, before)
        # An entirely different shape still gets sampled when the old run
        # sample list was already full before migration.
        record_budget(history, self.measurement(222))
        self.assertEqual(history['distinct_shapes'], 2)
        self.assertEqual(history['samples'], samples)

    def test_refusals_preserve_extremes_without_counting_as_preflight(self):
        history = {'runs': 2, 'max_records': 170}
        record_budget(history, self.measurement(1001, reached=False))
        self.assertEqual(history['max_records'], 1001)
        self.assertEqual(history['runs'], 2)
        self.assertEqual(history['distinct_shapes'], 0)
        self.assertFalse(history['review_due'])

    def test_unchanged_tick_migrates_history_and_emits_distinct_gate(self):
        import json
        with TemporaryDirectory() as directory, \
             patch('publish_work_cost.snapshots', return_value=[]), \
             patch('publish_work_cost.planes._post') as post:
            state = Path(directory) / 'state.json'
            state.with_suffix('.budget.json').write_text(json.dumps({
                'runs': 371, 'review_due': True,
                'samples': [{'items': 3, 'records': 221, 'body_bytes': 528011}]*20}))
            self.assertEqual(publish({}, 'st-cost', state), [])
            post.assert_not_called()
            metrics = state.with_suffix('.prom').read_text()
            self.assertIn('camayoc_cost_preflight_runs 371\n', metrics)
            self.assertIn('camayoc_cost_distinct_shapes 1\n', metrics)
            self.assertIn('camayoc_cost_budget_review_due 0\n', metrics)


class ProjectionTests(unittest.TestCase):
    def test_read_authority_refuses_before_any_network_or_cursor_change(self):
        import json
        invalid = [{}, {'another_consumer.py': ['read:crew:records']},
                   {'publish_work_cost.py': ['crew:records']},
                   {'publish_work_cost.py': ['read:crew:inferred']},
                   {'publish_work_cost.py': 'read:crew:records'},
                   {'publish_work_cost.py': ['read:crew:records', None]}, []]
        with TemporaryDirectory() as directory:
            authority = Path(directory) / 'authority.json'
            state = Path(directory) / 'state.json'
            state.write_text('{"existing":"cursor"}')
            for raw in [None, '{invalid', *map(json.dumps, invalid)]:
                with self.subTest(raw=raw):
                    if raw is not None:
                        authority.write_text(raw)
                    with patch.dict('os.environ', {'CAMAYOC_AUTHORITY': str(authority)}), \
                         patch('publish_work_cost.planes._post') as post:
                        with self.assertRaisesRegex(ValueError, 'refusing publication'):
                            publish({'errors': [], 'records': []}, 'st-cost', state)
                        post.assert_not_called()
                        self.assertEqual(state.read_text(), '{"existing":"cursor"}')
                        self.assertFalse(state.with_suffix('.pending.json').exists())
                        receipt = json.loads(state.with_suffix('.receipt.json').read_text())
                        self.assertEqual(receipt['status'], 'UNKNOWN')
                        self.assertEqual(receipt['requests'], 0)

    def test_explicit_consumer_read_grant_allows_publication(self):
        import json
        record = {'bead': 'p-one', 'attribution': 'attributed',
                  'session': 's', 'id': 'r', 'tokens': 10}
        with TemporaryDirectory() as directory:
            authority = Path(directory) / 'authority.json'
            authority.write_text(json.dumps({'publish_work_cost.py': ['read:crew:records']}))
            with patch.dict('os.environ', {'CAMAYOC_AUTHORITY': str(authority)}), \
                 patch('publish_work_cost.snapshots', return_value=[({'snapshot': 's'}, [record])]), \
                 patch('publish_work_cost.time.sleep'), \
                 patch('publish_work_cost.planes._post', side_effect=[
                     {'rows': [{'item': 'aegis:p-one'}]}, {'tx_id': 7},
                     {'rows': [{'n': '10', 'item': 'aegis:p-one'}]}]) as post:
                self.assertEqual(publish({}, 'st-cost', Path(directory)/'state.json'), [7])
                self.assertEqual(post.call_count, 3)
                for call in (post.call_args_list[0], post.call_args_list[2]):
                    self.assertTrue(call.args[1]['graph'].endswith('/crew/records'))

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
            import json
            history=json.loads((Path(directory)/'state.budget.json').read_text())
            self.assertEqual(history['samples'][0]['items'],8)
            self.assertEqual(history['samples'][0]['run'],1)
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
                 {'rows': [{'item': 'aegis:p-new'}]}, {'tx_id': 1},
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
            self.assertTrue(all(call.args[1]['graph'].endswith('/crew/records') for call in post.call_args_list))
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
            self.assertIn('camayoc_cost_projection_stalled{reason="pending"} 1', path.with_suffix('.prom').read_text())

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

    def test_compacted_item_names_pass_preflight_and_sample(self):
        import json
        record = {'bead':'p-new','attribution':'attributed','session':'s','id':'r','tokens':10}
        with TemporaryDirectory() as directory, \
             patch('publish_work_cost.snapshots', return_value=[({'snapshot':'s'}, [record])]), \
             patch('publish_work_cost.time.sleep'), \
             patch('publish_work_cost.planes._post', side_effect=[
                 {'rows':[{'item':'aegis:p-new'}]}, {'tx_id':1},
                 {'rows':[{'n':'10','item':'aegis:p-new'}]}]):
            path=Path(directory)/'state.json'
            self.assertEqual(publish({},'worker',path),[1])
            self.assertFalse(path.with_suffix('.pending.json').exists())
            self.assertEqual(json.loads(path.with_suffix('.receipt.json').read_text())['requests'],3)

    def test_budget_refusal_is_visible_and_records_maximum(self):
        import json
        rows=[{'bead':f'p-{i}','attribution':'attributed'} for i in range(9)]
        with TemporaryDirectory() as directory, \
             patch('publish_work_cost.snapshots', return_value=[({'snapshot':'s'}, rows)]), \
             patch('publish_work_cost.planes._post') as post:
            path=Path(directory)/'state.json'
            with self.assertRaisesRegex(ValueError,'budget'):
                publish({},'worker',path)
            post.assert_not_called()
            receipt=json.loads(path.with_suffix('.receipt.json').read_text())
            self.assertEqual(receipt['items_per_snapshot'],[9])
            self.assertEqual(receipt['records_per_snapshot'],[9])
            self.assertGreater(receipt['body_bytes_per_snapshot'][0],0)
            self.assertIn('camayoc_cost_projection_stalled{reason="budget"} 1', path.with_suffix('.prom').read_text())
            history=json.loads(path.with_suffix('.budget.json').read_text())
            self.assertEqual(history['max_items'],9)
            self.assertEqual(history['runs'],0)
            self.assertEqual(history['samples'],[])


class UnattributedBudgetTests(unittest.TestCase):
    def test_unattributed_snapshot_is_measured_without_inventing_a_work_item(self):
        import json
        record = {'bead': 'unattributed', 'attribution': 'no proven focus',
                  'session': 's', 'id': 'r', 'tokens': 10}
        body = {'snapshot': 's', 'turtle': 'measured requests', 'graph': 'records'}
        with TemporaryDirectory() as directory:
            state = Path(directory) / 'state.json'
            with patch('publish_work_cost.require_read_grant'), \
                 patch('publish_work_cost.snapshots', return_value=[(body, [record])]), \
                 patch('publish_work_cost.time.sleep'), \
                 patch('publish_work_cost.planes._post', side_effect=[
                     {'tx_id': 1}, {'rows': [{'n': 10}]}]) as post:
                self.assertEqual(publish({'errors': []}, 'cost', state), [1])
            receipt = json.loads(state.with_suffix('.receipt.json').read_text())
            self.assertEqual(receipt['budget_history']['distinct_shapes'], 1)
            self.assertEqual(receipt['budget_history']['distinct_samples'][0]['items'], 0)
            self.assertEqual(receipt['requests'], 2)
            self.assertEqual([call.args[0] for call in post.call_args_list], ['/knot', '/query'])


class ReviewStatusTests(unittest.TestCase):
    def test_review_refresh_never_reads_sources_or_calls_graph(self):
        import json
        with TemporaryDirectory() as directory:
            state = Path(directory) / 'state.json'
            history = {'runs': 20, 'review_due': True, 'samples': [],
                       'distinct_samples': [{'run': n, 'attempted_at': n,
                           'items': 0, 'records': n, 'body_bytes': n * 100} for n in range(1, 21)]}
            state.with_suffix('.budget.json').write_text(json.dumps(history))
            state.with_suffix('.receipt.json').write_text(json.dumps({'next_request_after': 10**12}))
            with patch('publish_work_cost.snapshots') as source, \
                 patch('publish_work_cost.planes._post') as graph:
                self.assertEqual(publish(None, 'cost', state, review_only=True), [])
                source.assert_not_called()
                graph.assert_not_called()
            receipt = json.loads(state.with_suffix('.receipt.json').read_text())
            self.assertEqual(receipt['status'], 'OK')
            self.assertEqual(receipt['requests'], 0)
            self.assertEqual(receipt['next_request_after'], 10**12)
            self.assertTrue(receipt['budget_history']['review_due'])
            self.assertEqual(receipt['budget_history']['runs'], 20)
            state.with_suffix('.pending.json').write_text('{}')
            with self.assertRaisesRegex(ValueError, 'indeterminate snapshot'):
                publish(None, 'cost', state, review_only=True)

    def test_premature_review_status_is_not_healthy(self):
        import json
        with TemporaryDirectory() as directory:
            state = Path(directory) / 'state.json'
            state.with_suffix('.budget.json').write_text('{}')
            with self.assertRaisesRegex(ValueError, 'completed bounded population'):
                publish(None, 'cost', state, review_only=True)
            receipt = json.loads(state.with_suffix('.receipt.json').read_text())
            self.assertEqual(receipt['status'], 'UNKNOWN')


class RefusalAccountingTests(unittest.TestCase):
    def test_each_limit_refuses_without_network_and_persists_source(self):
        import json
        from publish_work_cost import MAX_BODY_BYTES
        source = {'agent': 'worker', 'harness': 'codex', 'session': 's',
                  'bead': None, 'attribution': 'unattributed'}
        arms = {
            'items': [({'snapshot': 's'}, [{**source, 'bead': f'p-{n}', 'attribution': 'attributed'} for n in range(9)])],
            'records': [({'snapshot': 's'}, [source] * 1001)],
            'body_bytes': [({'snapshot': 's', 'turtle': 'x' * MAX_BODY_BYTES}, [source])],
            'snapshots': [({'snapshot': name}, [source]) for name in ('s', 's2')],
        }
        for limit, candidates in arms.items():
            with self.subTest(limit=limit), TemporaryDirectory() as directory, \
                 patch('publish_work_cost.snapshots', return_value=candidates), \
                 patch('publish_work_cost.planes._post') as post:
                state = Path(directory)/'state.json'
                for _ in range(2):
                    with self.assertRaisesRegex(ValueError, 'budget'):
                        publish({}, 'worker', state)
                post.assert_not_called()
                self.assertFalse(state.with_suffix('.pending.json').exists())
                history = json.loads(state.with_suffix('.budget.json').read_text())
                accounting = history['refusal_accounting']
                self.assertEqual((accounting['attempts'], accounting['refusals']), (2, 2))
                self.assertEqual(accounting['limits'][limit], 2)
                self.assertEqual(sum(accounting['limits'].values()), 2)
                self.assertEqual(accounting['recent_refusals'][-1]['sources'][0]['session'], 's')
                self.assertEqual(history['distinct_shapes'], 0)
                self.assertEqual(history['runs'], 0)
                metrics = state.with_suffix('.prom').read_text()
                self.assertIn('camayoc_cost_budget_refusals_total 2\n', metrics)
                self.assertIn(f'camayoc_cost_budget_limit_refusals_total{{limit="{limit}"}} 2\n', metrics)
                self.assertIn('camayoc_cost_budget_window_refusals 2\n', metrics)

    def test_multiple_binding_limits_count_once_and_evidence_is_bounded(self):
        import json
        rows = [{'bead': f'p-{n}', 'attribution': 'attributed'} for n in range(1001)]
        with TemporaryDirectory() as directory, \
             patch('publish_work_cost.snapshots', return_value=[({'snapshot': 's'}, rows)]), \
             patch('publish_work_cost.planes._post') as post:
            state = Path(directory)/'state.json'
            for _ in range(23):
                with self.assertRaises(ValueError):
                    publish({}, 'worker', state)
            post.assert_not_called()
            a = json.loads(state.with_suffix('.budget.json').read_text())['refusal_accounting']
            self.assertEqual(a['refusals'], 23)
            self.assertEqual(a['attempts'], 23)
            self.assertEqual(a['limits']['items'], 23)
            self.assertEqual(a['limits']['records'], 23)
            self.assertEqual(len(a['recent_refusals']), 20)

    def test_admission_and_backoff_noop_review_are_separate(self):
        import json
        row = {'attribution': 'unattributed', 'bead': None, 'session': 's', 'id': 'r', 'tokens': 10}
        body = {'snapshot': 's'}
        with TemporaryDirectory() as directory, \
             patch('publish_work_cost.snapshots', return_value=[(body, [row])]), \
             patch('publish_work_cost.time.sleep'), \
             patch('publish_work_cost.planes._post', side_effect=[{'tx_id': 7}, {'rows': [{'n': '10'}]}]) as post:
            state = Path(directory)/'state.json'
            self.assertEqual(publish({}, 'worker', state), [7])
            with self.assertRaisesRegex(ValueError, 'BACKOFF'):
                publish({}, 'worker', state)
            # End only the fixture's cooldown; graph cursor is unchanged.
            receipt = state.with_suffix('.receipt.json')
            saved = json.loads(receipt.read_text()); saved['next_request_after'] = 0
            receipt.write_text(json.dumps(saved))
            self.assertEqual(publish({}, 'worker', state), [])
            self.assertEqual(post.call_count, 2)
            history_path = state.with_suffix('.budget.json')
            history = json.loads(history_path.read_text())
            self.assertEqual(history['refusal_accounting']['attempts'], 1)
            self.assertEqual(history['refusal_accounting']['refusals'], 0)
            self.assertEqual(history['distinct_shapes'], 1)
            history.update(review_due=True, distinct_samples=[
                {'items': 0, 'records': n, 'body_bytes': n} for n in range(20)])
            history_path.write_text(json.dumps(history))
            self.assertEqual(publish(None, 'worker', state, review_only=True), [])
            a = json.loads(history_path.read_text())['refusal_accounting']
            self.assertEqual((a['attempts'], a['refusals']), (1, 0))

    def test_late_install_and_review_reset_do_not_invent_historical_zeros(self):
        from publish_work_cost import record_refusals
        history = {'runs': 200, 'review_window_started_at': 50}
        receipt = {'attempted_at': 100, 'budget_decision': 'admitted'}
        a = record_refusals(history, receipt)
        self.assertEqual(a['since'], 100)
        self.assertEqual(a['window']['started_at'], 50)
        self.assertEqual(a['window']['observed_since'], 100)
        self.assertEqual(a['attempts'], 1)
        history['review_window_started_at'] = 200
        a = record_refusals(history, {**receipt, 'attempted_at': 210})
        self.assertEqual(a['since'], 100)
        self.assertEqual(a['attempts'], 2)
        self.assertEqual(a['window']['baseline_attempts'], 1)
        self.assertEqual(a['window']['observed_since'], 210)

class SchedulerStatusTests(unittest.TestCase):
    def test_unknown_ticks_advance_without_graph_or_budget_work(self):
        import json
        with TemporaryDirectory() as tmp:
            state = Path(tmp) / 'scheduler.json'
            history = {}
            record_budget(history, {'attempted_at': 10, 'preflight_reached': True,
                'items_per_snapshot': [1], 'records_per_snapshot': [2],
                'body_bytes_per_snapshot': [100]})
            state.with_suffix('.budget.json').write_text(json.dumps(history))
            state.with_suffix('.receipt.json').write_text(json.dumps({
                'status': 'OK', 'attempted_at': 10, 'next_request_after': 9999}))
            with patch('publish_work_cost._publish') as graph, \
                 patch('camayoc_metrics.push', return_value=(True, 'fixture')) as push, \
                 patch('publish_work_cost.time.time', return_value=100):
                publish(None, 'st-cost', state, scheduler_only='tick', push_status=True)
                publish(None, 'st-cost', state, scheduler_only='source_selection', push_status=True)
                graph.assert_not_called()
            receipt = json.loads(state.with_suffix('.receipt.json').read_text())
            self.assertEqual(receipt['attempted_at'], 100)
            self.assertEqual(receipt['next_request_after'], 9999)
            self.assertEqual(receipt['status'], 'UNKNOWN')
            self.assertEqual(receipt['requests'], 0)
            self.assertEqual(json.loads(state.with_suffix('.budget.json').read_text()), history)
            self.assertIn('camayoc_cost_projection_ok 0', push.call_args.args[1])
            self.assertIn('camayoc_cost_projection_unknown{reason="source_selection"} 1', push.call_args.args[1])
            with patch('publish_work_cost.time.time', return_value=160):
                publish(None, 'st-cost', state, scheduler_only='tick')
            later = json.loads(state.with_suffix('.receipt.json').read_text())
            self.assertEqual(later['attempted_at'], 160)
            self.assertEqual(later['status'], 'UNKNOWN')  # heartbeat never invents success
            pending = state.with_suffix('.pending.json')
            pending.write_text('{"body":"preserve exactly"}')
            publish(None, 'st-cost', state, scheduler_only='tick')
            self.assertEqual(pending.read_text(), '{"body":"preserve exactly"}')
            self.assertEqual(json.loads(state.with_suffix('.receipt.json').read_text())['status'], 'STALLED')
