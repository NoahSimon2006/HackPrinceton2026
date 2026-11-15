import json
from pathlib import Path
import unittest
from unittest.mock import patch
import numpy as np
from pyproj import Transformer
from shapely import transform
from shapely.geometry import shape
import discovery
from terrain_discovery import d8
from water_discovery import upstream_cells


class WesternWaterTest(unittest.TestCase):
    def test_reverse_contribution_follows_only_real_links_and_is_bounded(self):
        z=np.array([[4.,3.,2.],[3.,2.,1.],[2.,1.,0.]])
        target,area,_,_=d8(z)
        cells=upstream_cells(target,8)
        self.assertEqual(len(cells),area[2,2]);self.assertEqual(set(cells),set(range(9)))
        with self.assertRaises(ValueError):upstream_cells(target,8,limit=4)
        target,_,_,_=d8(np.ones((4,4)))
        self.assertEqual(upstream_cells(target,5),[5],'unresolved flats cannot acquire invented connections')

    @unittest.skipUnless((discovery.DATA/'western-dem.tif').exists(),'Western source raster not downloaded')
    def test_real_outside_legacy_feature_conserves_area_and_gap_returns_no_substitute(self):
        data=discovery.load_discovery('water')
        feature=next(f for f in data['layers'][0]['features'] if f['properties']['center'][1]<34.062)
        p=feature['properties']
        polygon=transform(shape(p['contributing_geometry']),Transformer.from_crs(4326,26911,always_xy=True).transform,interleaved=False)
        self.assertAlmostEqual(polygon.area,p['value'],places=2)
        self.assertFalse(p['scalar_detail']['window_edge_contribution'])
        self.assertIn('western-dem.tif',p['grid_reference']['raster'])
        gap=discovery.query_area('water',[-118.26,34.045,-118.259,34.046],data=data)
        self.assertEqual(gap['coverage'],'outside_pilot')
        self.assertTrue(all(layer['total']==0 for layer in gap['layers']))
        self.assertEqual(data['audit']['pilot_valid_cells'],data['audit']['pilot_cells'])

    @unittest.skipUnless((discovery.DATA/'western-dem.tif').exists(),'Western source raster not downloaded')
    def test_neighborhood_query_preserves_source_units_and_redacts_geometry(self):
        data=discovery.load_discovery('water')
        facts,_=discovery.area_facts('water',-118.300769,34.070315,data=data)
        serialized=json.dumps(facts)
        for forbidden in ['coordinates','contributing_geometry','Normandie','229 S','-118.300769','34.070315']:
            self.assertNotIn(forbidden,serialized)
        providers={f['source']['provider'] for f in facts}
        self.assertIn('CoStar local property kit',providers)
        self.assertIn('Vexcel parcel/building extraction',providers)
        self.assertTrue(any(f['unit']=='inches' for f in facts))
        self.assertTrue(any(f['unit']=='m² of terrain-inferred contribution' for f in facts))
        with self.assertRaises(ValueError):discovery.query_area('water',[-180,-90,180,90],data=data)
        with self.assertRaises(ValueError):discovery.query_area('water',[-118.301,34.06,-118.3,34.07],limit=500,data=data)


if __name__=='__main__':unittest.main()
