import json
import unittest
from street_context import prepare_street_context
from road_concept import build_road_concept,validate_road_concept,canonical_hash
from tests.test_junction_context import osm_junction_fixture,LON,LAT
from tests.test_junction_design import package,identity

class OneWayTests(unittest.TestCase):
    def context(self):
        import xml.etree.ElementTree as ET
        root=ET.fromstring(osm_junction_fixture(legs=3))
        roads=[w for w in root.findall('way') if w.get('id') in ('100','102')]
        self.assertEqual(len(roads),2)
        for way,direction in zip(roads,('yes','-1')):
            ET.SubElement(way,'tag',k='oneway',v=direction)
            ET.SubElement(way,'tag',k='lanes',v='4')
        return prepare_street_context(LON,LAT,network_path='/missing/net',osm_path='/missing/osm',fetch_osm=lambda _:ET.tostring(root))
    def test_oneway_direction_lane_counts_paint_and_replay(self):
        c=self.context();self.assertEqual(c['model_context']['design_mode'],'junction')
        d=build_road_concept(c,[package(c)],identity=identity())
        self.assertEqual(validate_road_concept(json.loads(json.dumps(d))),d)
        self.assertEqual(d['checks'][0]['one_way_approach_count'],2)
        self.assertNotIn('through_lanes_per_direction',d['checks'][0])
        for index,a in enumerate(c['junctions'][0]['approaches']):
            if a['traffic_direction']!='one_way':continue
            features=[f for f in d['geometry'] if f['id'].startswith('intersection-approach-'+str(index+1)+'-')]
            surfaces=[f['properties']['surface'] for f in features]
            self.assertNotIn('centerline',surfaces)
            self.assertIn('lane_separator',surfaces)
            self.assertEqual(surfaces.count('stop_line'),int(a['traffic_flow']=='inbound'))
            movement=d['checks'][0]['approach_movements'][index]
            self.assertEqual(movement[a['traffic_flow']+'_lanes'],4)
            self.assertEqual(surfaces.count('lane_arrow'),4)
    def test_service_access_does_not_replace_anonymous_anchor_ids(self):
        from tests.test_junction_context import sumo_context
        c=sumo_context(minor_node=True)
        ids={a['id'] for a in c['anchors']}
        for a in c['junctions'][0]['approaches']:
            self.assertIn(a['anchor_id'],ids)
            self.assertRegex(a['anchor_id'],r'^road-[a-f0-9]{12}$')
