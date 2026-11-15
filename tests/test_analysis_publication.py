"""Accepted cancellation and final concept publication have one ordered outcome."""
import copy
import tempfile
from threading import Event, Lock, Thread
import unittest
from unittest.mock import patch

from agent_activity import Activity
from project_store import ProjectStore
import server
from test_project_api import handler
from test_project_workspace import snapshot
from test_road_concept_workspace import concept


class AnalysisPublicationTest(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.store = ProjectStore(self.directory.name)
        self.project = self.store.save(snapshot('Improve the intersection for walking.'))
        self.concept = concept()

    def request(self):
        return handler('/api/site-analysis', {**self.project['snapshot'],
            'projectId': self.project['id'], 'projectVersion': self.project['version']})

    def test_cancel_accepted_before_publication_cannot_archive_returned_concept(self):
        entered, release = Event(), Event()
        captured = {}
        def analyze(*args, **kwargs):
            captured['activity'] = kwargs['activity']
            entered.set()
            self.assertTrue(release.wait(3))
            # Even a producer returning geometry after cancellation cannot publish it.
            return {'concept': copy.deepcopy(self.concept), 'analysisError': None}
        h = self.request()
        with patch.dict('os.environ', {'GROK_API_KEY': 'test-only'}), \
             patch('server.project_store', return_value=self.store), \
             patch('server.traffic_context_at_site', return_value=None), \
             patch('site_agent.analyze_site', side_effect=analyze):
            thread = Thread(target=h.do_POST)
            thread.start()
            try:
                self.assertTrue(entered.wait(3))
                cancel = handler('/api/site-analysis/cancel', {'runId': captured['activity'].id})
                cancel.do_POST()
                self.assertEqual(cancel.send_json.call_args.args, (202, {'canceled': True}))
            finally:
                release.set()
                thread.join(3)
        self.assertFalse(thread.is_alive())
        saved = self.store.get(self.project['id'])
        self.assertEqual(saved['status'], 'canceled')
        self.assertEqual(saved['conceptHistory'], [])
        self.assertIsNone(saved['result']['concept'])

    def test_cancel_during_final_validation_reports_already_finished_without_blocking_other_runs(self):
        publishing, release, cancel_entered = Event(), Event(), Event()
        captured = {}
        original_finish = self.store.finish
        def finish(*args, **kwargs):
            if args[3] == 'ready':
                publishing.set()
                self.assertTrue(release.wait(3))
            return original_finish(*args, **kwargs)
        def analyze(*args, **kwargs):
            captured['activity'] = kwargs['activity']
            return {'concept': copy.deepcopy(self.concept), 'analysisError': None}
        original_cancel = server.cancel_site_analysis
        def cancel_request(run_id):
            cancel_entered.set()
            return original_cancel(run_id)
        h = self.request()
        other = Activity()
        other.publication_lock, other.publication_finished = Lock(), False
        with patch.dict('os.environ', {'GROK_API_KEY': 'test-only'}), \
             patch('server.project_store', return_value=self.store), \
             patch('server.traffic_context_at_site', return_value=None), \
             patch('site_agent.analyze_site', side_effect=analyze), \
             patch.object(self.store, 'finish', side_effect=finish), \
             patch('server.cancel_site_analysis', side_effect=cancel_request):
            thread = Thread(target=h.do_POST)
            cancel_thread = None
            thread.start()
            try:
                self.assertTrue(publishing.wait(3))
                cancel = handler('/api/site-analysis/cancel', {'runId': captured['activity'].id})
                cancel_thread = Thread(target=cancel.do_POST)
                cancel_thread.start()
                self.assertTrue(cancel_entered.wait(3))
                with server.ANALYSIS_LOCK:
                    server.ACTIVE_ANALYSES[other.id] = other
                self.assertTrue(original_cancel(other.id), 'An unrelated run must remain cancellable.')
            finally:
                release.set()
                thread.join(3)
                if cancel_thread:
                    cancel_thread.join(3)
                with server.ANALYSIS_LOCK:
                    server.ACTIVE_ANALYSES.pop(other.id, None)
        self.assertFalse(thread.is_alive())
        self.assertFalse(cancel_thread.is_alive())
        self.assertEqual(cancel.send_json.call_args.args, (202, {'canceled': False}))
        self.assertFalse(captured['activity'].cancelled.is_set())
        saved = self.store.get(self.project['id'])
        self.assertEqual(saved['status'], 'ready')
        self.assertEqual(saved['result']['concept'], self.concept)
        self.assertEqual(len(saved['conceptHistory']), 1)


if __name__ == '__main__':
    unittest.main()
