import json
import tempfile
import unittest

from project_store import ProjectStore
from site_measurements import measure_outlines
from stormwater_design import draft_rain_garden
from stormwater_settings import DEFAULTS, effective_settings, validate_settings
from test_site_measurements import LON, LAT, feature, polygon


def snapshot(revision=1, settings=None):
    return {'workflow': 'water', 'siteId': 'water-loop', 'lon': LON, 'lat': LAT,
            'propertyId': None, 'question': 'Develop this stormwater opportunity.', 'markings': [],
            'rainfallScenario': None, 'inputRevision': revision - 1, 'proposalRevision': revision,
            'stormwaterSettings': settings}


def design(revision=1):
    outlines = [feature(polygon(-30, -20, 60, 40), 'Parcel boundary'),
                feature(polygon(-10, -5, 20, 10), 'Building footprint')]
    measure_outlines(outlines, LON, LAT)
    return draft_rain_garden(lon=LON, lat=LAT, evidence={'outlines': outlines, 'detections': [], 'frontages': []},
        markings=[], rainfall={'inches': 1}, scenario=None, storage_depth_m=.15,
        runoff_coefficient=None, protect_driveway=False,
        identity={'site_id': 'water-loop', 'input_revision': revision - 1, 'revision': revision})[0].model_dump()


class StormwaterWorkspaceTest(unittest.TestCase):
    def setUp(self):
        # Scripted models use no provider capacity; pacing has dedicated fake-clock tests.
        from unittest.mock import patch
        pacing = patch('xai_runtime.MIN_INTERVAL_SECONDS', 0)
        pacing.start()
        self.addCleanup(pacing.stop)

    def test_narrative_failure_keeps_valid_design_but_deadline_cannot_publish_it(self):
        from unittest.mock import patch
        from agent_activity import Activity
        from site_agent import analyze_site
        from test_site_agent import ScriptedModel, lead_model, specialist_model, calls, message, call
        for expires in (False, True):
            with self.subTest(expires=expires):
                review = message(call('SiteReview', {'findings': [], 'recommendations': [], 'questions': ['Verify drainage connections?']}))
                lead = lead_model([calls('delegate'), calls('draft_rain_garden'), RuntimeError('transport failure')])
                models = [lead, specialist_model('site', 'water', [review]), specialist_model('domain', 'water', [review])]
                activity = Activity()
                original = ScriptedModel._generate
                def generate(model, *args, **kwargs):
                    if expires and model.responses and isinstance(model.responses[0], RuntimeError):
                        activity.deadline = 0
                    return original(model, *args, **kwargs)
                outlines = [feature(polygon(-30, -20, 60, 40), 'Parcel boundary'), feature(polygon(-10, -5, 20, 10), 'Building footprint')]
                with patch('site_agent.ChatXAI', side_effect=models), patch.object(ScriptedModel, '_generate', generate):
                    result = analyze_site('unused', 'fake', 'Develop a concept.', 'water', [],
                        lambda group: outlines if group == 'outlines' else [], lambda: ({'propertyType': 'Multifamily'}, []),
                        lambda: {'estimate': {'inches': 1, 'depth_range': [1, 1], 'method': 'contour'}}, lon=LON, lat=LAT,
                        analysis_identity={'site_id': 'water-loop', 'input_revision': 0, 'revision': 1}, activity=activity)
                if expires:
                    self.assertTrue(activity.cancelled.is_set())
                    self.assertIsNone(result['proposal'])
                    self.assertIsNone(result['waterPlan'])
                    self.assertEqual(result['alternatives'], {})
                else:
                    self.assertIsNone(result['analysisError'])
                    self.assertTrue(result['synthesisWarning'])
                    self.assertIsNotNone(result['proposal'])

    def test_explicit_settings_override_agent_and_cannot_become_connected_drainage(self):
        settings = effective_settings({'targetAreaM2': 18, 'storageDepthM': .12, 'layout': 'linear', 'protectAccess': True},
            {'targetAreaM2': 100, 'storageDepthM': .3, 'layout': 'compact', 'runoffCoefficient': .9, 'protectAccess': False})
        self.assertEqual(settings['targetAreaM2'], 18)
        self.assertEqual(settings['storageDepthM'], .12)
        self.assertEqual(settings['layout'], 'linear')
        self.assertTrue(settings['protectAccess'])
        self.assertIsNone(settings['runoffCoefficient'])
        self.assertEqual(settings['drainageAssumption'], 'unknown')
        previous = {**DEFAULTS, 'targetAreaM2': 80, 'storageDepthM': .2, 'layout': 'linear'}
        self.assertEqual(effective_settings(None, {'targetAreaM2': 30}, previous)['targetAreaM2'], 30)
        self.assertTrue(effective_settings(None, {}, {'protectAccess': True})['protectAccess'])
        self.assertFalse(effective_settings(None, {'protectAccess': False}, {'protectAccess': True})['protectAccess'])
        self.assertFalse(effective_settings({'protectAccess': False}, {}, {'protectAccess': True}, {'protectAccess': True})['protectAccess'])

    def test_partial_what_if_can_save_but_cannot_run_without_user_inputs(self):
        value = {'drainageAssumption': 'marked_connected'}
        self.assertEqual(validate_settings(value)['drainageAssumption'], 'marked_connected')
        with self.assertRaises(ValueError):
            validate_settings(value, for_analysis=True, markings=[])
        value['runoffCoefficient'] = 0
        with self.assertRaises(ValueError):
            validate_settings(value, for_analysis=True, markings=[])
        self.assertEqual(validate_settings(value, for_analysis=True, markings=[{'kind': 'drainage'}])['runoffCoefficient'], 0)
        for invalid in (True, float('nan'), -1, 1.1):
            with self.assertRaises(ValueError):
                validate_settings({'runoffCoefficient': invalid})
        with self.assertRaises(ValueError):
            validate_settings({'targetAreaM2': 10}, 'street')
        with self.assertRaises(ValueError):
            effective_settings(None, {'targetAreaM2': 0})

    def test_successful_revisions_survive_restart_and_stale_run_cannot_archive(self):
        with tempfile.TemporaryDirectory() as directory:
            store = ProjectStore(directory)
            project = store.save(snapshot())
            store.begin(project['id'], project['version'], 'a' * 32)
            first = {'proposal': design(), 'waterPlan': {'settings': effective_settings(None)}, 'alternatives': {}}
            self.assertTrue(store.finish(project['id'], 'a' * 32, first, 'ready'))
            self.assertEqual(first['designHistory'], [])
            project = store.save(snapshot(2, {'targetAreaM2': 20}), project['id'], project['version'])
            store.begin(project['id'], project['version'], 'b' * 32)
            self.assertFalse(store.finish(project['id'], 'a' * 32, first, 'ready'))
            second = {'proposal': design(2), 'waterPlan': {'settings': effective_settings({'targetAreaM2': 20})}, 'alternatives': {}}
            store.finish(project['id'], 'b' * 32, second, 'ready')
            restored = ProjectStore(directory).get(project['id'])
            self.assertEqual([item['revision'] for item in restored['designHistory']], [1, 2])
            self.assertEqual(restored['snapshot']['stormwaterSettings']['targetAreaM2'], 20)
            self.assertEqual(second['designHistory'][0]['proposal'], json.loads(json.dumps(first['proposal'])))
            self.assertEqual(restored['result']['proposal']['input_revision'], 1)

    def test_foreign_geometry_revision_and_failed_reports_do_not_archive(self):
        with tempfile.TemporaryDirectory() as directory:
            store = ProjectStore(directory)
            project = store.save(snapshot())
            store.begin(project['id'], project['version'], 'a' * 32)
            with self.assertRaises(ValueError):
                store.finish(project['id'], 'a' * 32, {'proposal': design(2)}, 'ready')
            self.assertEqual(store.get(project['id'])['designHistory'], [])
            store.finish(project['id'], 'a' * 32, {'proposal': design(), 'analysisError': 'failed'}, 'failed')
            self.assertEqual(store.get(project['id'])['designHistory'], [])


if __name__ == '__main__':
    unittest.main()
