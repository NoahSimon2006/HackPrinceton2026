import json
import tempfile
import time
import unittest
from unittest.mock import patch

from project_store import ProjectConflict, ProjectStore
from scout_store import REFRESH_NOTICE, ScoutStore, validate_search
from test_project_api import handler


def request(workflow='water'):
    return {'workflow': workflow, 'goal': 'Find useful environmental improvements.', 'bounds': [-118.307, 34.055, -118.294, 34.073]}


def candidate(number=1):
    return {'id': 'candidate-' + str(number), 'label': 'Local candidate', 'center': [-118.30, 34.06],
            'geometry': {'type': 'Point', 'coordinates': [-118.30, 34.06]}, 'propertyId': None,
            'environmental': {'summary': 'A supported screening signal, not measured benefit.'},
            'feasibility': 'Check access.', 'disruption': 'Check parking.', 'direction': 'Investigate planting.',
            'readiness': {'summary': 'Ready for conceptual study.', 'missing': ['Drainage connection']},
            'evidence': [], 'provenance': {'featureId': 'source-1'}, 'modelContext': {'curated': True}}


class ScoutStoreTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.projects = ProjectStore(self.temp.name)
        self.store = ScoutStore(self.projects)

    def tearDown(self):
        self.temp.cleanup()

    def complete(self, inputs=None, item=None):
        search = self.store.begin(inputs or request(), 'a' * 32)
        self.store.finish(search['id'], 'a' * 32, {'candidates': [item or candidate()], 'exhausted': False})
        return self.store.get(search['id'])

    def test_show_more_and_choice_survive_restart_without_creating_a_design(self):
        first = self.complete()
        second = self.store.begin({**request(), 'searchId': first['id']}, 'b' * 32)
        self.assertEqual(len(second['batches']), 1)
        self.store.finish(first['id'], 'b' * 32, {'candidates': [candidate(2)], 'exhausted': True})
        choice = self.store.select(first['id'], candidate()['id'])
        project = choice['project']
        self.assertIsNone(project['result'])
        self.assertIsNone(project['activeRun'])
        self.assertEqual(project['snapshot']['question'], request()['goal'])
        artifact = json.loads(self.projects.artifact(project['id'], '/project/scouting-selection.json'))
        self.assertEqual(artifact['candidateId'], candidate()['id'])
        self.assertNotIn('geometry', artifact)
        self.assertNotIn('center', artifact)
        self.assertEqual(ScoutStore(self.projects).get(first['id'])['selected']['projectId'], project['id'])
        self.assertEqual(len(self.store.get(first['id'])['batches']), 2)
        self.assertEqual(self.store.select(first['id'], candidate()['id'])['project']['id'], project['id'])
        changed = self.projects.save({**project['snapshot'], 'question': 'Keep the entrance clear.'}, project['id'], project['version'])
        other = self.store.select(first['id'], candidate(2)['id'])
        self.assertNotEqual(other['project']['id'], project['id'])
        resumed = self.store.select(first['id'], candidate()['id'])['project']
        self.assertEqual(resumed['id'], project['id'])
        self.assertEqual(resumed['version'], changed['version'])
        self.assertEqual(resumed['snapshot']['question'], 'Keep the entrance clear.')

    def test_changed_area_and_canceled_run_cannot_publish(self):
        search = self.store.begin(request(), 'a' * 32)
        with self.assertRaises(ProjectConflict):
            self.store.begin({**request(), 'searchId': search['id'], 'bounds': [-118.31, 34.05, -118.29, 34.07]}, 'b' * 32)
        self.store.cancel(search['id'])
        self.assertFalse(self.store.finish(search['id'], 'a' * 32, {'candidates': [candidate()]}))
        self.store.artifact(search['id'], 'a' * 32, '/project/stale.json', 'stale')
        self.assertEqual(self.store.get(search['id'])['batches'], [])
        self.assertEqual(self.store.get(search['id'])['artifacts'], {})
        renewed = self.store.begin({**request(), 'searchId': search['id']}, 'b' * 32)
        self.assertFalse(self.store.finish(search['id'], 'a' * 32, {'candidates': [candidate()]}))
        self.assertEqual(renewed['runId'], 'b' * 32)
        self.assertIsNone(self.store.cancel(search['id'], 'a' * 32))
        self.assertTrue(self.store.is_current(search['id'], 'b' * 32))

    def test_traffic_answer_survives_expiry_and_restart_and_can_still_be_selected(self):
        observed = '2026-11-15T12:32:31+00:00'
        item = {**candidate(), 'expiresAt': time.time() + 30, 'label': 'Maple Avenue',
                'feedback': {'observation': 'At search time, speed was 5 km/h.',
                             'nextStep': 'Compare the loading entrance with the queue before changing curb space.'},
                'evidence': [{'id': 'speed', 'value': 5,
                             'source': {'provider': 'TomTom', 'retrieved_at': observed}}]}
        search = self.store.begin(request('street'), 'a' * 32)
        review = {'findings': [{'candidate_id': item['id'], 'text': 'Check the loading entrance.', 'fact_ids': ['speed']}]}
        self.store.finish(search['id'], 'a' * 32, {'candidates': [item], 'review': review, 'summary': 'Three locations to compare.'})
        current = self.store.get(search['id'])['batches'][0]
        self.assertEqual(current['evidenceFreshness'], 'current')
        self.assertEqual(current['snapshotAt'], observed)
        with self.projects.connect() as db:
            stored = json.loads(db.execute('SELECT payload FROM scouts').fetchone()[0])
        self.assertEqual(stored['batches'][0]['review'], review)
        self.assertEqual(stored['batches'][0]['candidates'][0]['feedback'], item['feedback'])
        self.assertEqual(stored['batches'][0]['candidates'][0]['geometry'], item['geometry'])
        self.assertNotIn('modelContext', json.dumps(stored))
        with patch('scout_store.time.time', return_value=time.time() + 60):
            restarted = ScoutStore(self.projects)
            saved = restarted.get(search['id'])['batches'][0]
            self.assertEqual(saved['evidenceFreshness'], 'snapshot')
            self.assertEqual(saved['snapshotAt'], observed)
            self.assertEqual(saved['review'], review)
            self.assertEqual(saved['summary'], current['summary'])
            saved_candidate = saved['candidates'][0]
            self.assertEqual(saved_candidate['evidenceFreshness'], 'snapshot')
            for key in ('feedback', 'evidence', 'geometry', 'center', 'label'):
                self.assertEqual(saved_candidate[key], item[key])
            self.assertTrue(saved_candidate.get('available', True))
            selected = restarted.select(search['id'], item['id'])
            self.assertEqual(selected['project']['snapshot']['lon'], item['center'][0])
            self.assertEqual(selected['project']['snapshot']['question'], request('street')['goal'])
            # The saved choice is a location and brief. Site analysis must fetch
            # its own current evidence, never treat these old speeds as live.
            origin = json.loads(self.projects.artifact(selected['project']['id'], '/project/scouting-selection.json'))
            self.assertNotIn('evidence', origin)
            self.assertNotIn('feedback', origin)

    def test_source_already_expired_before_publication_keeps_the_answer(self):
        for expiry in (time.time() - 30, None):
            with self.subTest(expiry=expiry):
                item = {**candidate(), 'expiresAt': expiry, 'feedback': {'nextStep': 'Inspect the entrance nearest this queue.'}}
                search = self.complete(request('street'), item)
                saved = ScoutStore(self.projects).get(search['id'])['batches'][0]
                self.assertEqual(saved['evidenceFreshness'], 'snapshot')
                self.assertEqual(saved['candidates'][0]['feedback'], item['feedback'])
                self.assertEqual(self.store.select(search['id'], item['id'])['candidate']['id'], item['id'])

    def test_cancelled_more_search_preserves_the_previous_saved_answer(self):
        item = {**candidate(), 'expiresAt': time.time() - 30, 'feedback': {'nextStep': 'Check the first location.'}}
        first = self.complete(request('street'), item)
        self.store.begin({**request('street'), 'searchId': first['id']}, 'b' * 32)
        self.store.cancel(first['id'], 'b' * 32)
        self.assertFalse(self.store.finish(first['id'], 'b' * 32, {'candidates': [candidate(2)], 'review': {'findings': ['LATE REVIEW']}}))
        saved = ScoutStore(self.projects).get(first['id'])
        self.assertEqual(len(saved['batches']), 1)
        self.assertEqual(saved['batches'][0]['candidates'][0]['feedback'], item['feedback'])
        self.assertNotIn('LATE REVIEW', json.dumps(saved))
        self.assertEqual(self.store.select(first['id'], item['id'])['candidate']['id'], item['id'])

    def test_legacy_unavailable_record_is_not_recreated_as_a_selectable_location(self):
        old = {'id': 'candidate-1', 'label': 'Previous traffic opportunity', 'available': False,
               'resumeNotice': 'The original version did not retain this location.'}
        search = self.complete(request('street'), old)
        saved = ScoutStore(self.projects).get(search['id'])['batches'][0]['candidates'][0]
        self.assertFalse(saved['available'])
        self.assertNotIn('center', saved)
        with self.assertRaises(ProjectConflict):
            self.store.select(search['id'], old['id'])

    def test_legacy_copy_explains_missing_old_details_and_preserves_selected_project(self):
        first = self.complete(request('street'), candidate())
        selected = self.store.select(first['id'], candidate()['id'])
        old_notice = 'Live traffic evidence expired and is not archived. Run a new search to refresh this area; earlier choices remain in history.'
        with self.projects.connect() as db:
            stored = json.loads(db.execute('SELECT payload FROM scouts WHERE id=?', (first['id'],)).fetchone()[0])
            stored['batches'] = [{'id': 'a' * 32, 'created': stored['updated'], 'summary': old_notice,
                                 'resumeNotice': old_notice,
                                 'candidates': [{'id': candidate()['id'], 'label': 'Previous traffic opportunity',
                                                 'available': False, 'resumeNotice': old_notice}]}]
            db.execute('UPDATE scouts SET payload=? WHERE id=?', (json.dumps(stored), first['id']))
        restored = ScoutStore(self.projects).get(first['id'])
        batch = restored['batches'][0]
        self.assertEqual(batch['summary'], REFRESH_NOTICE)
        self.assertEqual(batch['resumeNotice'], REFRESH_NOTICE)
        self.assertEqual(batch['candidates'][0]['resumeNotice'], REFRESH_NOTICE)
        self.assertIn('new searches keep their answers', batch['summary'])
        self.assertFalse(batch['candidates'][0]['available'])
        self.assertNotIn('center', batch['candidates'][0])
        self.assertEqual(restored['selected']['projectId'], selected['project']['id'])
        self.assertEqual(self.projects.get(restored['selected']['projectId'])['id'], selected['project']['id'])
        # The compatibility copy is a read-time adaptation, not a rewrite of
        # saved research or an attempt to reconstruct lost locations.
        with self.projects.connect() as db:
            unchanged = db.execute('SELECT payload FROM scouts WHERE id=?', (first['id'],)).fetchone()[0]
        self.assertIn(old_notice, unchanged)

    def test_new_saved_answer_is_not_changed_by_legacy_copy_migration(self):
        item = {**candidate(), 'expiresAt': time.time() - 30, 'feedback': {'nextStep': 'Check this loading entrance.'}}
        first = self.complete(request('street'), item)
        restored = ScoutStore(self.projects).get(first['id'])
        self.assertEqual(restored['batches'], first['batches'])
        self.assertEqual(restored['batches'][0]['candidates'][0]['feedback'], item['feedback'])
        self.assertNotIn('resumeNotice', restored['batches'][0])

    def test_empty_traffic_search_preserves_useful_recovery_guidance(self):
        search = self.store.begin(request('street'), 'a' * 32)
        summary = 'No additional locations here. Try a smaller area or pick a spot directly.'
        self.store.finish(search['id'], 'a' * 32, {'candidates': [], 'summary': summary, 'feedbackGoal': request()['goal']})
        saved = ScoutStore(self.projects).get(search['id'])['batches'][0]
        self.assertEqual(saved['candidates'], [])
        self.assertEqual(saved['summary'], summary)
        self.assertNotIn('resumeNotice', saved)

    def test_interruption_and_empty_history(self):
        search = self.store.begin(request(), 'a' * 32)
        restarted = ScoutStore(self.projects)
        self.assertEqual(restarted.get(search['id'])['status'], 'interrupted')
        restarted.begin({**request(), 'searchId': search['id']}, 'b' * 32)
        restarted.finish(search['id'], 'b' * 32, {'candidates': [], 'exhausted': True})
        self.assertEqual(restarted.get(search['id'])['batches'][0]['candidates'], [])

    def test_api_select_only_accepts_own_candidate_and_cross_site_writes_fail(self):
        search = self.complete()
        h = handler('/api/scouts/select', {'id': search['id'], 'candidateId': 'unknown'})
        with patch('server.scout_store', return_value=self.store):
            h.do_POST()
        self.assertEqual(h.send_json.call_args.args[0], 400)
        self.assertEqual(self.projects.list(), [])
        h = handler('/api/scouts', request())
        h.headers['Sec-Fetch-Site'] = 'cross-site'
        h.do_POST()
        self.assertEqual(h.send_json.call_args.args[0], 400)

    def test_bounds_and_goal_budget(self):
        for bounds in ([False, 34.05, -118.2, 34.06], [-118.6, 34, -118.1, 34.1], [float('nan'), 34, -118.2, 34.1]):
            with self.assertRaises(ValueError):
                validate_search({**request(), 'bounds': bounds})
        with self.assertRaises(ValueError):
            validate_search({**request(), 'goal': ' '})


if __name__ == '__main__':
    unittest.main()
