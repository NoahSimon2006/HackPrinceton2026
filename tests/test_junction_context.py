"""Deterministic source topology fixtures shared by compiler/agent acceptance tests."""
import json
import copy
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from shapely.affinity import rotate, translate
from shapely.geometry import LineString, Point, Polygon, shape

from site_measurements import PROJECT, projected
from street_context import TO_GEO, canonical_hash, prepare_street_context

LON, LAT = -118.25, 34.05
X, Y = PROJECT.transform(LON, LAT)


def osm_junction_fixture(*, walking=True, legs=4, angle=0, shared=True, service_leg=False):
    """Four sourced radial streets with optional parallel sidewalk centerlines."""
    nodes, ways, index = [], [], 1
    def point(x, y):
        nonlocal index
        p = translate(rotate(Point(x, y), angle, origin=(0, 0)), X, Y)
        lon, lat = TO_GEO.transform(p.x, p.y)
        identifier = str(index); index += 1
        nodes.append(f'<node id="{identifier}" lon="{lon}" lat="{lat}"/>')
        return identifier
    center = point(0, 0)
    vectors = ((1, 0), (0, 1), (-1, 0), (0, -1))[:legs]
    for i, (dx, dy) in enumerate(vectors):
        start = center if shared else point(0, 0)
        end = point(dx * 90, dy * 90)
        kind = 'service' if service_leg and i == legs - 1 else 'residential'
        ways.append(f'<way id="{100 + i}" timestamp="2026-11-01T00:00:00Z"><nd ref="{start}"/><nd ref="{end}"/>'
                    f'<tag k="highway" v="{kind}"/><tag k="width" v="12"/><tag k="name" v="PRIVATE JUNCTION STREET {i}"/></way>')
        if walking:
            for side in (-1, 1):
                a = point(-dy * side * 9, dx * side * 9)
                b = point(dx * 90 - dy * side * 9, dy * 90 + dx * side * 9)
                ways.append(f'<way id="{200 + i * 2 + (side == 1)}"><nd ref="{a}"/><nd ref="{b}"/>'
                            '<tag k="highway" v="footway"/><tag k="footway" v="sidewalk"/></way>')
    return ('<osm version="0.6">' + ''.join(nodes + ways) + '</osm>').encode()


def junction_context(*, walking=True, legs=4, angle=0, selected_offset=24, shared=True, service_leg=False):
    """Production ``prepare_street_context`` from source XML, no ignored data/network."""
    selected = translate(rotate(Point(selected_offset, 0), angle, origin=(0, 0)), X, Y)
    lon, lat = TO_GEO.transform(selected.x, selected.y)
    raw = osm_junction_fixture(walking=walking, legs=legs, angle=angle, shared=shared, service_leg=service_leg)
    return prepare_street_context(lon, lat, network_path='/missing/test-network.xml', osm_path='/missing/test-roads.osm',
                                  fetch_osm=lambda bbox: raw)


def sumo_junction_fixture(*, walking=True, minor_node=False):
    """One genuine four-leg junction; optional offset-node short north segment."""
    offset = (1000 - X, 1000 - Y)
    def xy(x, y):
        return f'{1000 + x},{1000 + y}'
    nodes = ['<junction id="center" type="priority" x="1000" y="1000" shape="992,992 1008,992 1008,1008 992,1008"/>']
    edges = []
    for i, (dx, dy) in enumerate(((1, 0), (0, 1), (-1, 0), (0, -1))):
        endpoint = f'end-{i}'
        nodes.append(f'<junction id="{endpoint}" type="dead_end" x="{1000 + dx * 90}" y="{1000 + dy * 90}"/>')
        segments = [('center', endpoint, 8, 90)]
        if minor_node and i == 1:
            nodes.append('<junction id="minor" type="priority" x="1004" y="1020" shape="996,1014 1008,1014 1008,1026 996,1026"/>')
            segments = [('center', 'minor', 8, 15), ('minor', endpoint, 25, 90)]
        for j, (start, end, a, b) in enumerate(segments):
            for reverse in (False, True):
                sign = -1 if reverse else 1
                first, last = (b, a) if reverse else (a, b)
                coords = [xy(dx * t + dy * sign * 1.6, dy * t - dx * sign * 1.6) for t in (first, last)]
                identifier = ('-' if reverse else '') + f'road-{i}-{j}'
                frm, to = (end, start) if reverse else (start, end)
                edges.append(f'<edge id="{identifier}" from="{frm}" to="{to}" type="highway.residential" name="PRIVATE SOURCE ROAD {i}">'
                             f'<lane id="{identifier}_0" width="3.2" shape="{" ".join(coords)}"/></edge>')
        if walking:
            for side in (-1, 1):
                coords = [xy(dx * t - dy * side * 9, dy * t + dx * side * 9) for t in (0, 90)]
                edges.append(f'<edge id="walk-{i}-{side}" type="highway.footway"><lane id="walk-{i}-{side}_0" width="2" shape="{" ".join(coords)}"/></edge>')
    if minor_node:
        nodes.append('<junction id="drive-end" type="dead_end" x="1030" y="1020"/>')
        edges.extend([
            '<edge id="drive" from="minor" to="drive-end" type="highway.service"><lane id="drive_0" width="3.2" shape="1008,1018.4 1030,1018.4"/></edge>',
            '<edge id="-drive" from="drive-end" to="minor" type="highway.service"><lane id="-drive_0" width="3.2" shape="1030,1021.6 1008,1021.6"/></edge>',
        ])
    return (f'<net><location netOffset="{offset[0]},{offset[1]}" projParameter="+proj=utm +zone=11 +datum=WGS84 +units=m +no_defs"/>'
            + ''.join(nodes + edges) + '</net>').encode()


def sumo_context(*, walking=True, minor_node=False):
    with tempfile.TemporaryDirectory() as directory:
        path = Path(directory) / 'network.xml'; path.write_bytes(sumo_junction_fixture(walking=walking, minor_node=minor_node))
        lon, lat = TO_GEO.transform(X + 24, Y)
        return prepare_street_context(lon, lat, network_path=path, osm_path='/missing/test-roads.osm', allow_public_fetch=False)


class JunctionContextTests(unittest.TestCase):
    def test_midblock_selection_resolves_actual_shared_junction_and_all_legs(self):
        context = junction_context()
        self.assertEqual(context['model_context']['design_mode'], 'junction')
        junction = context['junctions'][0]
        self.assertAlmostEqual(junction['distance_m'], 24, places=2)
        self.assertEqual(junction['approach_count'], 4)
        self.assertEqual(context['model_context']['selected_junction_id'], junction['id'])
        anchor_ids = {anchor['id'] for anchor in context['anchors']}
        for approach in junction['approaches']:
            self.assertIn(approach['anchor_id'], anchor_ids)
            self.assertEqual(approach['junction_offset_m'], 0.)
            self.assertEqual(approach['outward_sign'], 1)
            self.assertLess(approach['crossing_offset_m'], 5)
            self.assertGreater(approach['available_length_m'], 20)
        model = json.dumps(context['model_context'])
        for forbidden in ('PRIVATE JUNCTION', 'coordinates', 'node_refs', str(LON), 'easting'):
            self.assertNotIn(forbidden, model)

    def test_geometric_crossing_without_shared_source_node_is_not_a_junction(self):
        context = junction_context(shared=False)
        self.assertEqual(context['junctions'], [])
        self.assertEqual(context['model_context']['design_mode'], 'needs_placement')

    def test_driveway_does_not_promote_midblock_to_major_intersection(self):
        self.assertEqual(junction_context(legs=3, service_leg=True)['junctions'], [])
        self.assertEqual(junction_context(legs=3)['junctions'][0]['approach_count'], 3)

    def test_sidewalk_connections_widen_context_beyond_modeled_traffic_lanes(self):
        context = sumo_context()
        junction = context['junctions'][0]
        self.assertEqual(junction['walking_connection_status'], 'mapped')
        plan = projected(junction['plan_area'])
        for approach in junction['approaches']:
            self.assertAlmostEqual(approach['width_m'], 6.4, places=2)
            self.assertAlmostEqual(approach['crossing_span_m'], 18, places=2)
            self.assertEqual(approach['walking_connection_status'], 'mapped')
            crossing = projected(approach['crossing_geometry'], ('LineString',))
            self.assertLess(crossing.difference(plan.buffer(.01)).length, .01)
            self.assertTrue(all(item['source_ref'].startswith('walk-') for item in approach['walking_landings']))

    def test_missing_sidewalks_are_proposed_landings_not_observations(self):
        context = junction_context(walking=False)
        self.assertEqual(context['model_context']['design_mode'], 'junction')
        for approach in context['junctions'][0]['approaches']:
            self.assertEqual(approach['walking_connection_status'], 'proposed')
            self.assertTrue(all(item['status'] == 'proposed' and item['source_ref'] is None for item in approach['walking_landings']))
            self.assertTrue(all('unverified' in item['basis'] for item in approach['walking_landings']))

    def test_minor_offset_node_does_not_bend_a_straight_approach(self):
        context = sumo_context(minor_node=True)
        north = next(a for a in context['junctions'][0]['approaches'] if a['direction'] == 'north')
        line = projected(north['geometry'], ('LineString',))
        self.assertGreater(line.length, 40)
        self.assertLess(line.bounds[2] - line.bounds[0], .01)
        self.assertEqual(len(north['source_anchor_ids']), 2)
        self.assertTrue(north['access_openings'])
        self.assertTrue(all(projected(item['geometry']).is_valid for item in north['access_openings']))

    def test_rotated_junction_preserves_source_alignment_and_source_hash(self):
        context = junction_context(angle=31)
        junction = context['junctions'][0]
        self.assertEqual(junction['source_hash'], context['sources'][0]['source_hash'])
        self.assertEqual({row['direction'] for row in junction['approaches']}, {'northeast', 'northwest', 'southeast', 'southwest'})
        for approach in junction['approaches']:
            self.assertTrue(projected(approach['road_geometry']).is_valid)

    def test_production_source_context_compiles_a_connected_package_and_roundtrips(self):
        from road_concept import build_road_concept, validate_road_concept
        for context in (junction_context(), junction_context(walking=False), sumo_context(minor_node=True), junction_context(legs=3)):
            with self.subTest(source=context['sources'][0]['provider'], legs=context['junctions'][0]['approach_count']):
                junction = context['junctions'][0]
                concept = build_road_concept(context, [{'id': 'whole-junction', 'kind': 'intersection_redesign',
                    'junction_id': junction['id'], 'anchor_id': junction['approaches'][0]['anchor_id']}],
                    identity={'site_id': 'junction-test', 'revision': 1, 'input_revision': 0})
                self.assertEqual(validate_road_concept(json.loads(json.dumps(concept))), concept)
                surfaces = {item['properties'].get('surface') for item in concept['geometry']}
                self.assertTrue({'roadway', 'sidewalk', 'curb', 'crosswalk', 'stop_line'} <= surfaces)
                self.assertEqual(concept['evaluation']['status'], 'unassessed')
                self.assertTrue(concept['checks'][0]['pedestrian_connected'])
                self.assertTrue(junction['pedestrian_connections'])

    def test_normalized_source_corner_gap_is_explicit_bounded_pedestrian_infill(self):
        from junction_context import _source_data
        def source_with_corner_hole(*args):
            nodes, walking = _source_data(*args)
            # A normalized SUMO outline can retain an enclosed triangular gap
            # adjacent to a mapped walking-corner envelope. Coordinates are
            # local fixture offsets, not a copied geographic site.
            hole = [(9, 9), (10, 11), (8, 11), (9, 9)]
            nodes['center']['area'] = translate(Polygon([(-14,-14),(14,-14),(14,14),(-14,14)], [hole]), X, Y)
            nodes['center']['area_normalized'] = True
            return nodes, walking
        with patch('junction_context._source_data', side_effect=source_with_corner_hole):
            context = sumo_context()
        junction = context['junctions'][0]
        self.assertIn('normalized', junction['basis'])
        infills = [feature for feature in junction['pedestrian_connections'] if '-infill-' in feature['id']]
        self.assertTrue(infills)
        self.assertEqual(len(projected(junction['plan_area']).interiors), 0)
        for feature in infills:
            self.assertIn('Proposed pedestrian infill', feature['properties']['basis'])
            geometry = projected(feature['geometry'])
            self.assertLessEqual(geometry.area, 30)
            self.assertTrue(projected(junction['area']).envelope.buffer(.01).covers(geometry))

    def test_narrow_lane_only_source_and_one_way_preflight_need_placement(self):
        from junction_context import model_junction_context
        context = sumo_context(walking=False)
        self.assertEqual(context['model_context']['design_mode'], 'needs_placement')
        self.assertIn('width', context['model_context']['question'])
        context = junction_context()
        context['junctions'][0]['approaches'][0]['traffic_direction'] = 'outbound'
        summary = model_junction_context(context['junctions'], context['anchors'])
        self.assertEqual(summary['design_mode'], 'needs_placement')
        self.assertIn('one-way', summary['question'])
        self.assertEqual(summary['approach_count'], 4)

    def test_explicit_crossing_is_usable_beside_an_unsupported_junction(self):
        from junction_context import model_junction_context
        context = junction_context()
        anchors = [*context['anchors'], {'id': 'marked-crossing-test', 'kind': 'marked_crossing'}]
        self.assertEqual(model_junction_context(context['junctions'], anchors)['design_mode'], 'junction')
        context['junctions'][0]['approaches'][0]['traffic_direction'] = 'outbound'
        summary = model_junction_context(context['junctions'], anchors)
        self.assertEqual(summary['design_mode'], 'marked_crossing')
        self.assertEqual(summary['design_instruction'], 'Use the explicit user-marked crossing alignment.')
        self.assertNotIn('question', summary)
        self.assertEqual(summary['selected_junction_id'], context['junctions'][0]['id'])
        self.assertEqual(summary['approach_count'], 4)

    def test_legacy_context_without_junction_fields_still_replays(self):
        from road_concept import build_road_concept, validate_road_concept
        from test_road_concept import road_context, identity, component
        context = copy.deepcopy(road_context())
        context.pop('junctions', None)
        context['compiler_version'] = 'road-context-v1'
        for anchor in context['anchors']:
            anchor.pop('topology', None)
        stable = {key: value for key, value in context.items() if key not in ('context_hash', 'model_context')}
        stable['sources'] = [{key: value for key, value in item.items() if key != 'retrieved_at'} for item in context['sources']]
        context['context_hash'] = canonical_hash(stable)
        value = build_road_concept(context, [component(context)], identity=identity())
        self.assertEqual(validate_road_concept(json.loads(json.dumps(value))), value)


if __name__ == '__main__':
    unittest.main()
