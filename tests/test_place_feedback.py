import unittest
from copy import deepcopy

from place_feedback import enrich_feedback


def candidate(identifier, value, **extra):
    values = {'signal': value, **extra}
    return {'id': identifier, 'evidence': [{'id': identifier + '-' + key, 'value': number}
                                          for key, number in values.items()]}


class PlaceFeedbackTests(unittest.TestCase):
    def test_distinct_traffic_feedback_uses_current_facts_and_relative_comparison(self):
        bundle = {'candidates': [candidate('first', 18, speed_kmh=9, free_flow_kmh=50), candidate('second', 45)]}
        result = enrich_feedback(bundle, 'street', 'Reduce emissions while preserving access.')
        first, second = [item['feedback'] for item in result['candidates']]
        self.assertIn('18%', first['observation'])
        self.assertIn('9 km/h', first['observation'])
        self.assertIn('Strongest slowdown among these choices', first['headline'])
        self.assertNotEqual(first['headline'], second['headline'])
        self.assertNotIn('feedback', bundle['candidates'][0])
        for item in result['candidates']:
            self.assertTrue(set(item['feedback']['factIds']) <= {f['id'] for f in item['evidence']})
        self.assertEqual(result['feedbackGoal'], 'Reduce emissions while preserving access.')
        self.assertIn('selected map area', result['summary'])

    def test_user_goal_changes_the_next_action_without_reordering(self):
        bundle = {'candidates': [candidate('first', 18), candidate('second', 45)]}
        access = enrich_feedback(bundle, 'street', 'Keep entrances clear for deliveries')
        crossing = enrich_feedback(bundle, 'street', 'Make pedestrian crossings safer with low-cost changes')
        self.assertIn('driveways and loading entrances', access['candidates'][0]['feedback']['nextStep'])
        self.assertIn('crossing routes and sight lines', crossing['candidates'][0]['feedback']['nextStep'])
        self.assertIn('small reversible trial', crossing['candidates'][0]['feedback']['nextStep'])
        self.assertNotEqual(access['candidates'][0]['feedback']['nextStep'], crossing['candidates'][0]['feedback']['nextStep'])
        self.assertEqual([c['id'] for c in access['candidates']], [c['id'] for c in crossing['candidates']])

    def test_unknown_goal_is_preserved_without_inventing_a_fit(self):
        goal = 'Prioritize routes serving the night shift'
        result = enrich_feedback({'candidates': [candidate('one', 18)]}, 'street', goal)
        self.assertEqual(result['feedbackGoal'], goal)
        feedback = result['candidates'][0]['feedback']
        self.assertNotIn('night shift', str(feedback))
        self.assertIn('signal timing', feedback['nextStep'])
        self.assertNotIn('Strongest', feedback['headline'])

    def test_ties_are_not_given_a_false_winner(self):
        result = enrich_feedback({'candidates': [candidate('a', 18), candidate('b', 18)]}, 'street', 'Emissions')
        self.assertTrue(all(c['feedback']['headline'].startswith('Joint strongest') for c in result['candidates']))

    def test_water_actions_use_terrain_and_actual_property_constraints(self):
        site = candidate('water', 1000, path_length_m=25, drop_m=2.5,
                         **{'costar-reportedLoadingDocks': 2, 'parcel-outside-footprints': 300})
        result = enrich_feedback({'candidates': [site]}, 'water', 'Add shade trees and reduce runoff')
        feedback = result['candidates'][0]['feedback']
        self.assertIn('1,000 m²', feedback['observation'])
        self.assertIn('25 m', feedback['observation'])
        self.assertIn('2.5 m', feedback['observation'])
        self.assertIn('actual inlet', feedback['nextStep'])
        self.assertIn('soil space and utilities', feedback['nextStep'])
        self.assertIn('2 loading docks', feedback['tradeoff'])
        self.assertIn('water-costar-reportedLoadingDocks', feedback['factIds'])
        self.assertNotIn('capture 1,000', str(feedback))

    def test_missing_optional_sources_still_give_an_action_and_cite_only_known_facts(self):
        for workflow in ('street', 'water'):
            with self.subTest(workflow=workflow):
                result = enrich_feedback({'candidates': [candidate('one', 18)], 'agentStatus': 'partial'}, workflow, 'Improve this area')
                feedback = result['candidates'][0]['feedback']
                self.assertTrue(all(feedback[key] for key in ('observation', 'relevance', 'nextStep', 'tradeoff')))
                self.assertEqual(feedback['factIds'], ['one-signal'])
                self.assertNotIn('impact unassessed', str(feedback))
                self.assertEqual(result['agentStatus'], 'partial')

    def test_rebuild_after_refresh_replaces_stale_feedback_and_comparison(self):
        first = enrich_feedback({'candidates': [candidate('a', 18), candidate('b', 45)]}, 'street', 'Preserve access')
        refreshed = deepcopy(first)
        refreshed['candidates'][0]['evidence'][0]['value'] = 55
        refreshed['reviewStale'] = True
        current = enrich_feedback(refreshed, 'street', first['feedbackGoal'])
        self.assertIn('55%', current['candidates'][0]['feedback']['observation'])
        self.assertNotIn('18%', str(current['candidates'][0]['feedback']))
        self.assertTrue(current['candidates'][1]['feedback']['headline'].startswith('Strongest'))

    def test_empty_or_expired_results_offer_a_recovery_action_without_recreating_live_facts(self):
        for candidates in ([], [{'id': 'old', 'available': False, 'resumeNotice': 'Expired'}]):
            result = enrich_feedback({'candidates': candidates}, 'street', 'Reduce emissions')
            self.assertIn('search again', result['summary'])
            self.assertTrue(all('feedback' not in item for item in result['candidates']))


if __name__ == '__main__':
    unittest.main()
