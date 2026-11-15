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
        self.assertIn('small reversible trial', ' '.join(crossing['goalChecks']))
        self.assertNotIn('small reversible trial', crossing['candidates'][0]['feedback']['nextStep'])
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

    def test_equal_speed_different_extent_and_nearby_uses_change_the_decision_guidance(self):
        housing = candidate('housing', 18, speed_kmh=5, free_flow_kmh=27.8, length_m=165.2, time_penalty_s=97.5)
        shops = candidate('shops', 18, speed_kmh=5, free_flow_kmh=27.8, length_m=45.6, time_penalty_s=26.9)
        for item, use in ((housing, 'Multifamily'), (shops, 'Retail')):
            item['evidence'].append({'id': item['id'] + '-costar-nearby-use-1',
                                     'label': 'Nearby CoStar records by property type: ' + use, 'value': 1})
        result = enrich_feedback({'candidates': [housing, shops]}, 'street',
                                 'Keep loading access clear, improve pedestrian crossings and use low-cost changes')
        first, second = [item['feedback'] for item in result['candidates']]
        self.assertIn('165.2 m', first['observation'])
        self.assertIn('97.5 seconds', first['observation'])
        self.assertIn('longest mapped slow stretch', first['relevance'])
        self.assertIn('shortest mapped slow stretch', second['relevance'])
        self.assertIn('housing entrances', first['nextStep'])
        self.assertIn('deliveries or pickups', second['nextStep'])
        self.assertIn('resident driveways', first['tradeoff'])
        self.assertIn('shop entrances', second['tradeoff'])
        self.assertNotEqual(first['nextStep'], second['nextStep'])
        self.assertNotEqual(first['tradeoff'], second['tradeoff'])
        self.assertTrue(first['observation'].startswith('At search time'))
        self.assertIn('do not establish ownership', first['tradeoff'])
        self.assertEqual(len(result['goalChecks']), 3)
        self.assertEqual([c['id'] for c in result['candidates']], ['housing', 'shops'])
        for item in result['candidates']:
            self.assertTrue(set(item['feedback']['factIds']) <= {f['id'] for f in item['evidence']})

    def test_extent_alone_supports_different_inspection_scopes_without_inventing_causes(self):
        result = enrich_feedback({'candidates': [candidate('long', 18, length_m=165.2),
                                                 candidate('short', 18, length_m=45.6)]}, 'street', 'Reduce emissions')
        first, second = [item['feedback'] for item in result['candidates']]
        self.assertIn('in sections', first['nextStep'])
        self.assertIn('first stopping point', second['nextStep'])
        self.assertIn('165.2 m', first['tradeoff'])
        self.assertIn('45.6 m', second['tradeoff'])
        self.assertNotIn('caused by', str(result))

    def test_same_nearby_use_does_not_hide_different_inspection_scopes(self):
        choices = [candidate('long', 18, length_m=209), candidate('short', 18, length_m=118)]
        for item in choices:
            item['evidence'].append({'id': item['id'] + '-costar-nearby-use-1',
                                     'label': 'Nearby CoStar records by property type: Multifamily', 'value': 1})
        result = enrich_feedback({'candidates': choices}, 'street', 'Improve crossings')
        first, second = [item['feedback']['nextStep'] for item in result['candidates']]
        self.assertIn('209.0 m in sections', first)
        self.assertIn('downstream stopping point', second)
        self.assertNotEqual(first, second)

    def test_unmeasured_extent_does_not_receive_a_comparative_rank(self):
        result = enrich_feedback({'candidates': [candidate('long', 18, length_m=165.2),
                                                 candidate('short', 18, length_m=45.6),
                                                 candidate('unknown', 20)]}, 'street', 'Reduce emissions')
        self.assertNotIn('longest', result['candidates'][0]['feedback']['relevance'])
        self.assertNotIn('shortest', result['candidates'][1]['feedback']['relevance'])

    def test_missing_signal_still_offers_concrete_observation_task(self):
        result = enrich_feedback({'candidates': [{'id': 'sparse', 'evidence': []}]}, 'street', 'Improve access')
        feedback = result['candidates'][0]['feedback']
        self.assertIn('observe where vehicles stop', feedback['observation'])
        self.assertIn('driveways and loading entrances', feedback['nextStep'])
        self.assertEqual(feedback['factIds'], [])

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

    def test_compact_feedback_has_one_intuitive_metric_and_retains_details(self):
        item = candidate('one', 53, speed_kmh=21.2, free_flow_kmh=40,
                         length_m=165.2, time_penalty_s=97.5)
        result = enrich_feedback({'candidates': [item]}, 'street', 'Improve pedestrian crossings')
        feedback = result['candidates'][0]['feedback']
        brief = feedback['brief']
        self.assertEqual(set(brief), {'headline', 'metric', 'action'})
        self.assertEqual(brief['metric'], 'Traffic was 47% slower than uncongested speed.')
        self.assertIn('pedestrian routes', brief['action'])
        self.assertNotIn('165.2', str(brief))
        self.assertNotIn('97.5', str(brief))
        self.assertLessEqual(len(' '.join(brief.values()).split()), 60)
        self.assertIn('165.2 m', feedback['observation'])
        self.assertIn('97.5 seconds', feedback['observation'])

    def test_compact_actions_keep_equal_speed_locations_distinct(self):
        choices = [candidate('long', 18, length_m=209), candidate('short', 18, length_m=118)]
        for item in choices:
            item['evidence'].append({'id': item['id'] + '-costar-nearby-use-1',
                                     'label': 'Nearby CoStar records by property type: Multifamily', 'value': 1})
        result = enrich_feedback({'candidates': choices}, 'street', 'Improve crossings')
        first, second = [item['feedback']['brief'] for item in result['candidates']]
        self.assertIn('Longest', first['headline'])
        self.assertIn('Shortest', second['headline'])
        self.assertIn('full stretch', first['action'])
        self.assertIn('downstream queue', second['action'])
        self.assertNotEqual(first['action'], second['action'])

    def test_compact_feedback_budget_holds_with_all_goal_topics_and_sparse_sources(self):
        for workflow in ('street', 'water'):
            for facts in (candidate('full', 900 if workflow == 'water' else 18,
                                    length_m=200, path_length_m=50, drop_m=3,
                                    **{'historical-demand-date': '2015-02-03', 'costar-reportedLoadingDocks': 20}),
                          {'id': 'empty', 'evidence': []}):
                with self.subTest(workflow=workflow, candidate=facts['id']):
                    brief = enrich_feedback({'candidates': [facts]}, workflow,
                        'Improve safe crossings, preserve loading access, add shade trees and prefer low-cost changes')['candidates'][0]['feedback']['brief']
                    self.assertTrue(brief['action'])
                    self.assertLessEqual(len(' '.join(brief.values()).split()), 60)
                    self.assertNotIn('unassessed', str(brief))
                    if facts['id'] == 'empty':
                        self.assertEqual(brief['metric'], '')

    def test_compact_goal_changes_action_without_claiming_benefit(self):
        bundle = {'candidates': [candidate('one', 53)]}
        access = enrich_feedback(bundle, 'street', 'Preserve loading access')['candidates'][0]['feedback']['brief']
        walking = enrich_feedback(bundle, 'street', 'Safer pedestrian crossings')['candidates'][0]['feedback']['brief']
        self.assertIn('loading entrances', access['action'])
        self.assertIn('pedestrian routes', walking['action'])
        self.assertNotEqual(access['action'], walking['action'])
        self.assertNotIn('emissions', access['metric'])


if __name__ == '__main__':
    unittest.main()
