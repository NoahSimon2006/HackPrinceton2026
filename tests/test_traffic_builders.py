import subprocess
import sys
import unittest
import xml.etree.ElementTree as ET
from pathlib import Path

from scripts.fetch_osm import collect, extract


class TrafficBuilderTest(unittest.TestCase):
    def test_street_names_match_consistently_across_discovery_and_simulation(self):
        from street_names import street_key
        from scripts import build_discovery, build_emissions
        import traffic_sim
        for module in (build_discovery, build_emissions, traffic_sim):
            self.assertIs(module.street_key, street_key)
        for name, expected in [(None, ''), ('', ''), ('East 1st Street', '1 ST'), ('W 1ST ST', '1 ST'),
                               ('South 23rd Avenue', '23 AV'), ('N. Olympic Boulevard', 'OLYMPIC BL'),
                               ('Olympic Bl', 'OLYMPIC BL')]:
            with self.subTest(name=name):
                self.assertEqual(street_key(name), expected)

    def test_osm_restrictions_are_preserved_and_incomplete_topology_rejected(self):
        root=ET.fromstring('''<osm><node id="1"/><node id="2"/><node id="3"/>
          <way id="10"><nd ref="1"/><nd ref="2"/><tag k="highway" v="primary"/></way>
          <way id="11"><nd ref="2"/><nd ref="3"/><tag k="highway" v="primary"/></way>
          <relation id="20"><member type="way" ref="10" role="from"/><member type="node" ref="2" role="via"/>
            <member type="way" ref="11" role="to"/><tag k="type" v="restriction"/><tag k="restriction" v="no_left_turn"/></relation></osm>''')
        nodes,ways,relations={},{},{}
        collect(root,nodes,ways,relations)
        result=extract(nodes,ways,relations)
        self.assertEqual(result.find('relation/tag[@k="restriction"]').get('v'),'no_left_turn')
        with self.assertRaises(ValueError):extract(nodes,{'10':ways['10']},relations)
        del nodes['3']
        with self.assertRaises(ValueError):extract(nodes,ways,relations)

    def test_archived_scripts_require_explicit_opt_in_before_work(self):
        root=Path(__file__).resolve().parents[1]
        for script,flag in [('run_pilot.py','--allow-illustrative'),('build_emissions.py','--allow-volume-assumptions')]:
            run=subprocess.run([sys.executable,str(root/'scripts'/script)],capture_output=True,text=True,cwd=root)
            self.assertEqual(run.returncode,2)
            self.assertIn(flag,run.stderr)


if __name__=='__main__':unittest.main()
