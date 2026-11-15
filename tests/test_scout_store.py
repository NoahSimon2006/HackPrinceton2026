import json
import tempfile
import time
import unittest
from unittest.mock import patch

from project_store import ProjectConflict, ProjectStore
from scout_store import ScoutStore, validate_search
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

    def test_traffic_values_and_geometry_never_reach_sqlite_and_expire(self):
        item = {**candidate(), 'expiresAt': time.time() + 30, 'label': 'LIVE-ROAD-SECRET',
                'environmental': {'summary': 'LIVE-SPEED-SECRET'}}
        search = self.complete(request('street'), item)
        self.assertTrue(search['batches'][0]['candidates'][0]['center'])
        with self.projects.connect() as db:
            stored = db.execute('SELECT payload FROM scouts').fetchone()[0]
        self.assertNotIn('LIVE-', stored)
        self.assertNotIn('coordinates', stored)
        self.assertNotIn('modelContext', stored)
        with patch('scout_store.time.time', return_value=time.time() + 60):
            expired = self.store.get(search['id'])['batches'][0]['candidates'][0]
            self.assertFalse(expired['available'])
            with self.assertRaises(ProjectConflict):
                self.store.select(search['id'], item['id'])
            self.assertFalse(self.store.live)

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
