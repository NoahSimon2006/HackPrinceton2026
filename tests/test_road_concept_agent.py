"""The real Deep Agents graph must research and publish a map concept without counts."""
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from langchain_core.messages import AIMessage

from agent_activity import Activity
from site_agent import analyze_site
from street_context import prepare_street_context
from test_site_agent import call, calls, lead_model, message, read, specialist_model


LON, LAT = -118.25, 34.05
IDENTITY = {'site_id': 'road-agent-site', 'revision': 1, 'input_revision': 0}
EMPTY = {'findings': [], 'recommendations': [], 'questions': ['Verify source alignment on site?']}


def review(payload=None):
    return message(call('SiteReview', payload or EMPTY))


def researched_models(lead_responses):
    lead = lead_model([calls('delegate'), message(read('/skills/traffic-concept/SKILL.md')), *lead_responses])
    site = specialist_model('site', 'street', [review()])
    domain = specialist_model('domain', 'street', [
        calls('read_street_design_context', 'read_street_design_guidance'), review()])
    return lead, site, domain


class RoadConceptAgentTest(unittest.TestCase):
    def setUp(self):
        pacing = patch('xai_runtime.MIN_INTERVAL_SECONDS', 0)
        pacing.start()
        self.addCleanup(pacing.stop)
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        raw = f'''<osm version="0.6">
          <node id="1" lon="{LON - .001}" lat="{LAT}"/>
          <node id="2" lon="{LON + .001}" lat="{LAT}"/>
          <way id="10" timestamp="2026-01-01T00:00:00Z"><nd ref="1"/><nd ref="2"/>
          <tag k="highway" v="residential"/><tag k="name" v="PRIVATE ROAD NAME"/>
          <tag k="lanes" v="2"/></way></osm>'''.encode()
        self.raw = raw
        self.context = prepare_street_context(LON, LAT,
            network_path=Path(self.temp.name) / 'missing.net.xml',
            osm_path=Path(self.temp.name) / 'missing.osm', fetch_osm=lambda _: raw)
        self.anchor = self.context['model_context']['anchors'][0]
        self.components = [
            {'id': 'crossing-a', 'kind': 'crossing', 'anchor_id': self.anchor['id'],
             'offset_m': self.anchor['selection_offset_m'], 'length_m': 3.0},
            {'id': 'curb-a', 'kind': 'curb_extension', 'anchor_id': self.anchor['id'],
             'side': 'right', 'offset_m': self.anchor['selection_offset_m'] + 10,
             'length_m': 8.0, 'width_m': 1.2},
        ]
        self.refs = ['road-context-status', 'road-guidance-crossing', 'road-guidance-curb']

    def compile_call(self, *, components=None, changes=None, refs=None):
        args = {'evidence_fact_ids': self.refs if refs is None else refs}
        if changes is not None:
            args['changes'] = changes
        else:
            args['components'] = components or self.components
        return message(call('create_or_revise_road_concept', args))

    def run_graph(self, models, **kwargs):
        with patch('site_agent.ChatXAI', side_effect=models):
            return analyze_site('unused', 'fake', 'Make this crossing easier to see and preserve property access.',
                'street', [], lambda _: [], lambda: ({}, []), lambda: {},
                lon=LON, lat=LAT, analysis_identity=kwargs.pop('analysis_identity', IDENTITY),
                fetch_street_context=kwargs.pop('fetch_street_context', lambda: self.context), **kwargs)

    def test_researched_overlay_without_counts_keeps_raw_geometry_out_of_model(self):
        final = {'findings': [{'text': 'The crossing treatment follows the reviewed visibility guidance.',
                              'fact_ids': ['road-guidance-crossing']}],
                 'recommendations': [{'text': 'Inspect the proposed crossing and curb layout on the map.',
                                      'fact_ids': ['road-concept-status']}],
                 'questions': ['Verify curb alignment and property access on site?']}
        models = researched_models([self.compile_call(), review(final)])
        events, archived = [], {}
        result = self.run_graph(models, activity=Activity(events.append),
                                persist_artifact=lambda path, value: archived.update({path: value}))
        self.assertIsNone(result['analysisError'])
        self.assertEqual(result['concept']['status'], 'conceptual')
        self.assertEqual(len(result['concept']['components']), 2)
        self.assertEqual(result['comparison']['status'], 'unavailable')
        self.assertEqual(result['concept']['evaluation']['status'], 'unassessed')
        self.assertEqual(result['report']['recommendations'], final['recommendations'])
        self.assertEqual({item['id'] for item in result['concept']['sources'] if item.get('id', '').startswith('road-guidance-')},
                         {'road-guidance-crossing', 'road-guidance-curb'})
        self.assertIn('/project/designs/road-concept.json', archived)
        self.assertIn('geometry', json.loads(archived['/project/designs/road-concept.json']))
        self.assertNotIn('/project/designs/road-concept.json', result['virtualFiles'])
        sent = ' '.join(str(item.content) for model in models for messages in model.seen for item in messages)
        for secret in ('PRIVATE ROAD NAME', '"coordinates":', str(LON), str(LAT)):
            self.assertFalse(secret in sent, f'Model payload exposed local data: {secret}')
        self.assertIn('create_or_revise_road_concept', models[0].tool_names)
        self.assertNotIn('create_or_revise_road_concept', models[1].tool_names + models[2].tool_names)
        self.assertIn('read_street_design_guidance', models[2].tool_names)
        self.assertIn('placement', sent)
        width = next(item for item in result['facts'] if item['id'].endswith('-width_m') and item['id'].startswith('road-anchor-'))
        self.assertEqual(width['basis'], 'estimated')

    def test_ready_geometry_requires_concept_before_final_report(self):
        models = researched_models([review(), self.compile_call(), review()])
        result = self.run_graph(models)
        self.assertIsNone(result['analysisError'])
        self.assertIsNotNone(result['concept'])
        sent = ' '.join(str(item.content) for messages in models[0].seen for item in messages)
        self.assertIn('Read the required source tools first: concept', sent)

    def test_mixed_user_marking_and_osm_anchors_keep_their_own_provenance(self):
        marking = {'kind': 'crossing', 'geometry': {'type': 'LineString',
                   'coordinates': [[LON, LAT - .00005], [LON, LAT + .00005]]}}
        context = prepare_street_context(LON, LAT, [marking],
            network_path=Path(self.temp.name) / 'missing.net.xml',
            osm_path=Path(self.temp.name) / 'missing.osm', fetch_osm=lambda _: self.raw)
        self.assertEqual(context['sources'][0]['provider'], 'Planner map markings')
        models = researched_models([self.compile_call(), review()])
        result = self.run_graph(models, fetch_street_context=lambda: context)
        self.assertIsNone(result['analysisError'])
        self.assertIsNotNone(result['concept'])
        facts = {item['id']: item for item in result['facts']}
        mapped = facts[f"road-anchor-{self.anchor['id']}-length_m"]
        self.assertEqual(mapped['source']['provider'], 'OpenStreetMap bounded map extract')
        self.assertEqual(mapped['source']['collection'], context['sources'][1]['source_hash'])
        marked_anchor = next(item for item in context['anchors'] if item['kind'] == 'marked_crossing')
        marked = facts[f"road-anchor-{marked_anchor['id']}-length_m"]
        self.assertEqual(marked['source']['provider'], 'Planner map marking')
        self.assertEqual(marked['basis'], 'user_provided')

    def test_revision_preserves_unspecified_component_and_does_not_inherit_performance(self):
        from road_concept import build_road_concept
        previous = build_road_concept(self.context, self.components, identity=IDENTITY, markings=[], evidence={})
        project = {'id': 'a' * 32, 'threadId': 'concept-test', 'instructions': [],
                   'result': {'concept': previous}, 'conceptHistory': [{'concept': previous}]}
        models = researched_models([self.compile_call(changes=[{'id': 'curb-a', 'op': 'update', 'length_m': 6.0}]), review()])
        result = self.run_graph(models, analysis_identity={**IDENTITY, 'revision': 2, 'input_revision': 1}, project=project)
        self.assertIsNone(result['analysisError'])
        old = {item['id']: item for item in previous['components']}
        new = {item['id']: item for item in result['concept']['components']}
        self.assertEqual(old['crossing-a'], new['crossing-a'])
        self.assertEqual(new['curb-a']['length_m'], 6.0)
        self.assertEqual(result['concept']['evaluation']['status'], 'unassessed')
        self.assertNotEqual(previous['input_hash'], result['concept']['input_hash'])

    def test_missing_geometry_returns_placement_question_and_no_invented_overlay(self):
        context = {'model_context': {'status': 'unavailable', 'anchors': [],
                                    'reason': 'Mark the intended crossing on the map.'}}
        models = researched_models([review()])
        result = self.run_graph(models, fetch_street_context=lambda: context)
        self.assertIsNone(result['analysisError'])
        self.assertIsNone(result['concept'])
        self.assertEqual(result['conceptGap'], context['model_context']['reason'])
        self.assertEqual(result['report']['questions'], [result['conceptGap']])
        self.assertNotIn('create_or_revise_road_concept', models[0].tool_names)

    def test_validated_overlay_survives_incomplete_narrative(self):
        models = researched_models([self.compile_call(), RuntimeError('provider stopped')])
        result = self.run_graph(models)
        self.assertIsNone(result['analysisError'])
        self.assertIsNotNone(result['concept'])
        self.assertIn('layout remains available', result['synthesisWarning'])

    def test_unusable_building_source_is_not_reported_as_checked_empty(self):
        models = researched_models([self.compile_call(), review()])
        def imagery(_):
            raise ValueError('Source unavailable')
        with patch('site_agent.ChatXAI', side_effect=models):
            result = analyze_site('unused', 'fake', 'Improve this crossing.', 'street', [],
                imagery, lambda: ({}, []), lambda: {}, lon=LON, lat=LAT,
                analysis_identity=IDENTITY, fetch_street_context=lambda: self.context)
        self.assertIsNone(result['analysisError'])
        self.assertTrue(result['concept'])
        self.assertTrue(all(item['building_overlap'] == 'unassessed' for item in result['concept']['checks']))

    def test_invalid_placement_gets_bounded_corrections_then_precise_gap(self):
        components = [{**self.components[0], 'width_m': 1000.0}]
        models = researched_models([self.compile_call(components=components),
                                    self.compile_call(components=components),
                                    self.compile_call(components=components), review()])
        result = self.run_graph(models)
        self.assertIsNone(result['analysisError'])
        self.assertIsNone(result['concept'])
        self.assertTrue(result['conceptGap'])
        self.assertEqual(result['report']['questions'], [result['conceptGap']])
        self.assertNotIn('create_or_revise_road_concept', models[0].tool_sets[-1])

    def test_guidance_must_match_chosen_treatments_and_unused_guidance_is_not_saved(self):
        models = researched_models([
            self.compile_call(refs=['road-context-status', 'road-guidance-refuge']),
            self.compile_call(refs=[*self.refs, 'road-guidance-refuge']), review()])
        result = self.run_graph(models)
        self.assertIsNone(result['analysisError'])
        self.assertIsNotNone(result['concept'])
        self.assertNotIn('road-guidance-refuge', {item.get('id') for item in result['concept']['sources']})
        sent = ' '.join(str(item.content) for messages in models[0].seen for item in messages)
        self.assertIn('Cite relevant reviewed guidance for these treatments', sent)

    def test_canceled_run_cannot_publish_compiled_overlay(self):
        models = researched_models([self.compile_call(), review()])
        def emit(event):
            if event['stage'] == 'road-concept' and event['status'] == 'completed':
                activity.cancelled.set()
        activity = Activity(emit)
        result = self.run_graph(models, activity=activity)
        self.assertIsNone(result['concept'])
        self.assertIn('canceled', result['analysisError'])

    def test_archive_or_summary_write_failure_never_half_publishes_a_concept(self):
        from road_concept import build_road_concept
        previous = build_road_concept(self.context, self.components, identity=IDENTITY, markings=[], evidence={})
        history = [{'concept': previous, 'savedAt': '2026-11-15T00:00:00Z'}]
        project = {'id': 'a' * 32, 'threadId': 'publication-test', 'instructions': [],
                   'result': {'concept': previous}, 'conceptHistory': history}
        for path_to_fail in ('/project/designs/road-concept.json', '/project/designs/road-concept-summary.json'):
            with self.subTest(path=path_to_fail):
                models = researched_models([
                    self.compile_call(changes=[{'id': 'curb-a', 'op': 'update', 'length_m': 6.0}]), review()])
                events = []
                def persist(path, _):
                    if path == path_to_fail:
                        raise ValueError('Archive budget exceeded')
                result = self.run_graph(models, project=project,
                    analysis_identity={**IDENTITY, 'revision': 2, 'input_revision': 1},
                    persist_artifact=persist, activity=Activity(events.append))
                self.assertIsNone(result['concept'])
                self.assertIn('could not be saved', result['analysisError'])
                self.assertEqual(result['sourceStatus']['concept'], 'publication_failed')
                self.assertEqual(result['conceptHistory'], history)
                self.assertFalse(any(item['id'].startswith('road-concept-') for item in result['facts']))
                self.assertFalse(any(event['stage'] == 'road-concept' and event['status'] == 'completed' for event in events))


if __name__ == '__main__':
    unittest.main()
