"""The published shortlist always has guidance based on its final evidence."""
import os
import time
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import opportunity_scout
import test_opportunity_scout as fixtures
from project_store import ProjectStore
from scout_store import ScoutStore
from server import start_scout
from agent_activity import RunCancelled
from test_opportunity_scout import BOUNDS, feature


class ScoutFeedbackApiTests(unittest.TestCase):
    def setUp(self):
        self.directory = TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.store = ScoutStore(ProjectStore(self.directory.name))

    def start(self, workflow, goal):
        with patch('server.scout_store', return_value=self.store), \
             patch('server.Thread', side_effect=lambda **kwargs: SimpleNamespace(start=kwargs['target'])):
            return start_scout({'workflow': workflow, 'goal': goal, 'bounds': BOUNDS})

    def test_no_model_key_still_publishes_useful_source_guidance(self):
        bundle = fixtures.OpportunityTests().research([feature('collection', -118.30, 1200)])
        with patch.dict(os.environ, {'GROK_API_KEY': ''}), \
             patch.object(opportunity_scout, 'research_candidates', return_value=bundle), \
             patch('scout_agent.ChatXAI') as model:
            result = self.start('water', 'Intercept runoff while keeping entrances clear')
        self.assertEqual(result['status'], 'ready')
        model.assert_not_called()
        batch = result['batches'][0]
        self.assertEqual(batch['feedbackGoal'], result['goal'])
        self.assertEqual(batch['agentStatus'], 'partial')
        feedback = batch['candidates'][0]['feedback']
        self.assertIn('1,200', feedback['observation'])
        self.assertTrue(feedback['nextStep'])
        self.assertTrue(feedback['relevance'])

    def test_saved_search_keeps_the_review_with_its_original_evidence(self):
        source = feature('slow', -118.30, 18)
        bundle = fixtures.OpportunityTests().research([source], 'street')
        bundle.update(review={'findings': [{'candidate_id': bundle['candidates'][0]['id'],
            'text': 'Check loading access along this observed slow approach.', 'fact_ids': [bundle['candidates'][0]['evidence'][0]['id']]}]},
            agentStatus='complete')
        bundle['expiresAt'] = bundle['candidates'][0]['expiresAt'] = time.time() - 1
        with patch.dict(os.environ, {'GROK_API_KEY': 'test-unused'}), \
             patch('scout_agent.review_scout', return_value=bundle), \
             patch.object(opportunity_scout, 'map_discovery') as refresh:
            result = self.start('street', 'Reduce emissions and preserve access')
        self.assertEqual(result['status'], 'ready')
        batch = result['batches'][0]
        refresh.assert_not_called()
        self.assertEqual(batch['evidenceFreshness'], 'snapshot')
        self.assertEqual(batch['review'], bundle['review'])
        feedback = batch['candidates'][0]['feedback']
        self.assertIn('18%', feedback['observation'])
        self.assertIn('search time', feedback['observation'])
        self.assertEqual(batch['feedbackGoal'], result['goal'])
        with self.store.projects.connect() as db:
            persisted = db.execute('SELECT payload FROM scouts').fetchone()[0]
        self.assertIn('18%', persisted)
        self.assertIn('feedback', persisted)
        self.assertNotIn('modelContext', persisted)
        self.assertEqual(ScoutStore(self.store.projects).get(result['id'])['batches'][0]['review'], bundle['review'])

    def test_model_deadline_preserves_research_but_user_cancellation_does_not_publish(self):
        bundle = fixtures.OpportunityTests().research([feature('collection', -118.30, 1200)])
        for cancelled in (False, True):
            def stop(*args):
                args[4]()
                if cancelled:
                    args[5].cancelled.set()
                else:
                    args[5].deadline = 0
                raise RunCancelled()
            with self.subTest(cancelled=cancelled), patch('scout_agent.review_scout', side_effect=stop), \
                 patch.object(opportunity_scout, 'research_candidates', return_value=bundle):
                result = self.start('water', 'Preserve access and intercept runoff')
            if cancelled:
                self.assertEqual(result['status'], 'canceled')
                self.assertEqual(result['batches'], [])
            else:
                self.assertEqual(result['status'], 'ready')
                self.assertTrue(result['batches'][0]['candidates'][0]['feedback']['nextStep'])

    def test_empty_search_gives_an_action_without_inventing_a_location(self):
        for workflow in ('water', 'street'):
            with self.subTest(workflow=workflow), patch.dict(os.environ, {'GROK_API_KEY': ''}), \
                 patch.object(opportunity_scout, 'research_candidates', return_value={'candidates': [], 'warnings': [], 'exhausted': True}), \
                 patch.object(opportunity_scout, 'refresh_traffic_candidates', side_effect=lambda bundle, *args, **kwargs: bundle):
                result = self.start(workflow, 'Keep entrances clear')
            batch = result['batches'][0]
            self.assertEqual(batch['candidates'], [])
            self.assertIn('map', batch['summary'])
            self.assertNotIn('expired', batch['summary'])
            self.assertNotIn('resumeNotice', batch)
            self.assertEqual(result['goal'], 'Keep entrances clear')


if __name__ == '__main__':
    unittest.main()
