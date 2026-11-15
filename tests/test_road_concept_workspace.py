"""Road concepts publish independently of simulations and retain exact revisions."""
import copy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

from project_store import ProjectStore
from road_concept import build_road_concept
from street_context import prepare_street_context
from test_project_workspace import snapshot
from test_project_api import handler
from traffic_retention import archive_artifact


def context(lon=-118.25, lat=34.05):
    raw = f'''<osm version="0.6">
      <node id="1" lon="{lon-.0015}" lat="{lat}"/>
      <node id="2" lon="{lon+.0015}" lat="{lat}"/>
      <way id="1"><nd ref="1"/><nd ref="2"/>
        <tag k="highway" v="residential"/><tag k="width" v="12"/>
      </way></osm>'''.encode()
    return prepare_street_context(lon, lat, network_path=Path('/nonexistent-road-concept-test-network'),
        osm_path=Path('/nonexistent-road-concept-test-osm'), fetch_osm=lambda bbox: raw)


def concept(revision=1, input_revision=0, site_id='workspace-test', lon=-118.25, evidence=None):
    c = context(lon)
    return build_road_concept(c, [{'id': 'bike-east', 'kind': 'bike_lane',
        'anchor_id': c['anchors'][0]['id'], 'side': 'right',
        'offset_m': 60, 'length_m': 25, 'width_m': 1.8}],
        identity={'site_id': site_id, 'revision': revision, 'input_revision': input_revision}, evidence=evidence)


class RoadConceptWorkspaceTest(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.store = ProjectStore(self.directory.name)
        self.project = self.store.save(snapshot('Improve the intersection for cycling.'))

    def publish(self, c, run='a' * 32):
        self.store.begin(self.project['id'], self.project['version'], run)
        self.assertTrue(self.store.finish(self.project['id'], run,
            {'concept': c, 'analysisError': None, 'comparison': {'status': 'unavailable'}}, 'ready'))
        self.project = self.store.get(self.project['id'])
        return self.project

    def test_concept_without_counts_is_saved_and_reload_is_exact(self):
        c = concept()
        saved = self.publish(c)
        self.assertEqual(saved['result']['concept'], c)
        self.assertEqual(saved['result']['comparison']['status'], 'unavailable')
        self.assertEqual(saved['trafficDesignHistory'], [])
        self.assertEqual(saved['conceptHistory'][0]['concept'], c)
        timestamp = saved['result']['conceptSavedAt']
        self.assertNotIn('savedAt', saved['result'], 'A concept timestamp must not imply publication of an unrelated traffic evaluation.')
        restarted = ProjectStore(self.directory.name).get(saved['id'])
        self.assertEqual(restarted['result']['conceptSavedAt'], timestamp)
        self.assertEqual(restarted['conceptHistory'][0]['concept']['context'], c['context'])

    def test_revision_and_failed_continuation_preserve_previous_geometry(self):
        first = concept()
        self.publish(first)
        first_time = self.project['result']['conceptSavedAt']
        changed = {**self.project['snapshot'], 'question': 'Make the cycle lane shorter.',
                   'inputRevision': 1, 'proposalRevision': 2}
        self.project = self.store.save(changed, self.project['id'], self.project['version'])
        second = concept(2, 1)
        self.publish(second, 'b' * 32)
        self.assertEqual([v['concept']['revision'] for v in self.project['conceptHistory']], [1, 2])
        self.assertEqual(self.project['conceptHistory'][0]['savedAt'], first_time)
        self.store.begin(self.project['id'], self.project['version'], 'c' * 32)
        self.store.finish(self.project['id'], 'c' * 32, None, 'canceled')
        stopped = self.store.get(self.project['id'])
        self.assertEqual(stopped['status'], 'canceled')
        self.assertEqual(stopped['conceptHistory'][-1]['concept'], second)

    def test_foreign_revision_tampering_and_origin_cannot_publish(self):
        original = concept()
        altered = copy.deepcopy(original)
        altered['geometry'][0]['geometry']['coordinates'][0][0][0] += .0001
        for index, c in enumerate((concept(site_id='other-site'), concept(revision=2), concept(lon=-118.251), altered)):
            with self.subTest(site=c['site_id'], revision=c['revision']):
                run = f'{index + 1:032x}'
                self.store.begin(self.project['id'], self.project['version'], run)
                with self.assertRaises(ValueError):
                    self.store.finish(self.project['id'], run, {'concept': c}, 'ready')
                self.store.finish(self.project['id'], run, None, 'failed')
                self.assertEqual(self.store.get(self.project['id'])['conceptHistory'], [])

    def test_stale_and_canceled_runs_cannot_archive_a_concept(self):
        self.store.begin(self.project['id'], self.project['version'], 'a' * 32)
        self.project = self.store.save({**self.project['snapshot'], 'inputRevision': 1},
                                      self.project['id'], self.project['version'])
        self.assertFalse(self.store.finish(self.project['id'], 'a' * 32, {'concept': concept()}, 'ready'))
        self.store.begin(self.project['id'], self.project['version'], 'b' * 32)
        self.store.finish(self.project['id'], 'b' * 32, {'concept': concept()}, 'canceled')
        saved = self.store.get(self.project['id'])
        self.assertIsNone(saved['result']['concept'])
        self.assertEqual(saved['conceptHistory'], [])

    def test_canonical_artifact_survives_retention_but_notes_do_not(self):
        c = concept()
        payload = archive_artifact('/project/designs/road-concept.json', json.dumps(c))
        self.assertEqual(json.loads(payload), c)
        self.assertIsNone(archive_artifact('/project/notes/lead/reason.md', 'Live traffic prose'))
        c['input_hash'] = '0' * 64
        with self.assertRaises(ValueError):
            archive_artifact('/project/designs/road-concept.json', json.dumps(c))

    def test_detailed_source_context_can_be_archived_without_enlarging_agent_notes(self):
        from shapely.geometry import Point
        from street_context import _geographic
        from site_measurements import PROJECT
        east, north = PROJECT.transform(-118.25, 34.05)
        detailed = _geographic(Point(east, north + 35).buffer(5, quad_segs=1600))
        c = concept(evidence={'outlines': [{'geometry': detailed, 'properties': {'label': 'Building footprint'}}]})
        content = json.dumps(c)
        self.assertGreater(len(content), 200_000)
        self.store.artifact(self.project['id'], '/project/designs/road-concept.json', content)
        self.assertEqual(json.loads(self.store.artifact(self.project['id'], '/project/designs/road-concept.json')), c)
        # Ordinary workspace artifacts retain their existing bounded budget.
        with self.assertRaises(ValueError):
            self.store.artifact(self.project['id'], '/project/brief.json', 'x' * 200_001)

    def test_http_analysis_publishes_concept_and_read_only_project_restores_it(self):
        c = concept()
        h = handler('/api/site-analysis', {**self.project['snapshot'],
            'projectId': self.project['id'], 'projectVersion': self.project['version']})
        with patch.dict('os.environ', {'GROK_API_KEY': 'test-only'}), \
             patch('server.project_store', return_value=self.store), \
             patch('server.traffic_context_at_site', return_value=None), \
             patch('site_agent.analyze_site', return_value={'concept': c, 'analysisError': None}) as analyze:
            h.do_POST()
        self.assertEqual(h.send_json.call_args.args[0], 200)
        returned = h.send_json.call_args.args[1]
        self.assertEqual(returned['concept']['input_hash'], c['input_hash'])
        self.assertTrue(returned['conceptSavedAt'])
        self.assertEqual(len(returned['conceptHistory']), 1)
        self.assertTrue(callable(analyze.call_args.kwargs['fetch_street_context']))
        get = handler('/api/projects?id=' + self.project['id'], {})
        with patch('server.project_store', return_value=self.store):
            get.do_GET()
        self.assertEqual(get.send_json.call_args.args[0], 200)
        self.assertEqual(get.send_json.call_args.args[1]['result']['concept'], c)


if __name__ == '__main__':
    unittest.main()
