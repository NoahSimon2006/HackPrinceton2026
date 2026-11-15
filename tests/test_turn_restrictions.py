import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import xml.etree.ElementTree as ET

from scripts.verify_turn_restrictions import audit, correction_patch
from traffic_sim import SimulationError, validate_network_sources, verify_restrictions


class RestrictionTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.folder = Path(self.temp.name)
        self.osm = self.folder / 'source.osm'
        self.net = self.folder / 'network.xml'

    def fixture(self, rule='no_left_turn', extra='', links=None):
        self.osm.write_text(f'''<osm><relation id="100">
          <member type="way" ref="10" role="from"/><member type="way" ref="20" role="to"/>
          <member type="node" ref="2" role="via"/><tag k="type" v="restriction"/>
          <tag k="restriction" v="{rule}"/>{extra}</relation></osm>''')
        if links is None:
            links = '<connection from="in" to="out" fromLane="0" toLane="0" dir="l" via=":turn_0"/>'
        self.net.write_text(f'''<net>
          <junction id="cluster"><param key="origId" value="2 3"/></junction>
          <edge id="in" from="1" to="cluster"><lane id="in_0"><param key="origId" value="10"/></lane></edge>
          <edge id="out" from="cluster" to="4"><lane id="out_0"><param key="origId" value="20"/></lane></edge>
          <edge id="other" from="cluster" to="5"><lane id="other_0"><param key="origId" value="30"/></lane></edge>
          <edge id=":turn" function="internal"><lane id=":turn_0"/></edge>{links}</net>''')

    def test_joined_junction_illegal_turn_detected_and_patch_keeps_exception(self):
        self.fixture(extra='<tag k="except" v="bus"/>')
        result = audit(self.osm, self.net)
        self.assertEqual(result['counts'], {'failed': 1})
        self.assertEqual(result['relations'][0]['checks']['bus']['status'], 'exempt')
        connection = correction_patch(result, self.net).find('connection')
        self.assertEqual(set(connection.get('disallow').split()), {'passenger', 'truck'})
        self.assertEqual(connection.get('from'), 'in')

    def test_internal_connection_permissions_are_respected(self):
        self.fixture()
        self.net.write_text(self.net.read_text().replace('<lane id=":turn_0"/>', '<lane id=":turn_0" disallow="passenger truck bus"/>'))
        self.assertEqual(audit(self.osm, self.net)['counts'], {'passed': 1})

    def test_only_turn_rejects_other_exit_and_missing_required_is_not_repaired(self):
        self.fixture('only_left_turn', links='<connection from="in" to="other" fromLane="0" toLane="0" dir="s"/>')
        result = audit(self.osm, self.net)
        self.assertEqual(result['counts'], {'failed': 1})
        with self.assertRaisesRegex(ValueError, 'no required permitted connection'):
            correction_patch(result, self.net)

    def test_conditional_rule_never_silently_passes(self):
        self.fixture(extra='<tag k="restriction:conditional" v="no_left_turn @ (Mo-Fr 16:00-19:00)"/>')
        self.assertEqual(audit(self.osm, self.net)['counts'], {'unverified_conditional': 1})
        (self.folder / 'sources').mkdir()
        (self.folder / 'sources' / 'dtla-roads.osm').write_bytes(self.osm.read_bytes())
        with patch('traffic_sim.SIM', self.folder), self.assertRaisesRegex(SimulationError, 'unresolved OSM'):
            verify_restrictions(self.net)

    def test_u_turn_does_not_prohibit_through_on_same_way(self):
        self.fixture('no_u_turn', links='<connection from="in" to="out" fromLane="0" toLane="0" dir="s"/>')
        self.osm.write_text(self.osm.read_text().replace('ref="20"', 'ref="10"'))
        self.net.write_text(self.net.read_text().replace('value="20"', 'value="10"'))
        self.assertEqual(audit(self.osm, self.net)['counts'], {'passed': 1})
        self.net.write_text(self.net.read_text().replace('dir="s"', 'dir="t"'))
        self.assertEqual(audit(self.osm, self.net)['counts'], {'failed': 1})

    def test_missing_members_and_outside_via_way_are_not_passes(self):
        self.fixture()
        root = ET.parse(self.osm).getroot()
        relation = root.find('relation')
        relation.remove(relation.find('member[@role="to"]'))
        ET.ElementTree(root).write(self.osm)
        self.assertEqual(audit(self.osm, self.net)['counts'], {'unverified_members': 1})
        self.fixture()
        self.osm.write_text(self.osm.read_text().replace('type="node" ref="2"', 'type="way" ref="500"').replace('ref="20"', 'ref="999"'))
        self.assertEqual(audit(self.osm, self.net)['counts'], {'movement_not_represented': 1})

    def test_network_manifest_must_match_both_sources(self):
        from traffic_sim import file_hash
        self.fixture()
        (self.folder / 'sources').mkdir()
        source = self.folder / 'sources' / 'dtla-roads.osm'
        source.write_bytes(self.osm.read_bytes())
        manifest = self.folder / 'network-build.json'
        manifest.write_text(json.dumps({'network_sha256': file_hash(self.net), 'osm_sha256': file_hash(source)}))
        with patch('traffic_sim.SIM', self.folder), patch('traffic_sim.NETWORK', self.net):
            validate_network_sources()
            source.write_text(source.read_text() + '\n')
            with self.assertRaisesRegex(SimulationError, 'stale'):
                validate_network_sources()


if __name__ == '__main__':
    unittest.main()
