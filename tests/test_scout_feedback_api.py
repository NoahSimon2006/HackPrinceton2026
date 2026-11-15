"""The published shortlist always has guidance based on its final evidence."""
from copy import deepcopy
import os
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import opportunity_scout
import test_opportunity_scout as fixtures
from project_store import ProjectStore
from scout_store import ScoutStore
from server import start_scout
from test_opportunity_scout import BOUNDS, data, feature


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

    def test_refresh_replaces_agent_prose_with_guidance_from_new_values(self):
        source = feature('slow', -118.30, 18)
        bundle = fixtures.OpportunityTests().research([source], 'street')
        bundle.update(review={'findings': [{'candidate_id': bundle['candidates'][0]['id'],
            'text': 'OLD AGENT COMMENTARY', 'fact_ids': [bundle['candidates'][0]['evidence'][0]['id']]}]},
            agentStatus='complete', summary='OLD AGENT SUMMARY')
        current = deepcopy(source)
        current['properties']['value'] = 45
        with patch.dict(os.environ, {'GROK_API_KEY': 'test-unused'}), \
             patch('scout_agent.review_scout', return_value=bundle), \
             patch.object(opportunity_scout, 'map_discovery', return_value=data([current], 'street', version='v2')):
            result = self.start('street', 'Reduce emissions and preserve access')
        self.assertEqual(result['status'], 'ready')
        batch = result['batches'][0]
        self.assertTrue(batch['reviewStale'])
        self.assertNotIn('review', batch)
        self.assertNotIn('OLD AGENT', str(batch))
        feedback = batch['candidates'][0]['feedback']
        self.assertIn('45%', feedback['observation'])
        self.assertNotIn('18%', feedback['observation'])
        self.assertEqual(batch['feedbackGoal'], result['goal'])
        with self.store.projects.connect() as db:
            persisted = db.execute('SELECT payload FROM scouts').fetchone()[0]
        self.assertNotIn('45%', persisted)
        self.assertNotIn('feedback', persisted)

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
