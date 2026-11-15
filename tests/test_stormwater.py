"""Development-only synthetic polygons test accounting and publication gates."""
from copy import deepcopy
import json
import unittest
from unittest.mock import patch

from pyproj import Transformer
from shapely import transform
from shapely.geometry import box, mapping, LineString

from proposal import Proposal, Design, from_water_comparison
from stormwater import compare_water, validate_water_design
from site_measurements import PROJECT

LON, LAT = -118.3021, 34.06925
X, Y = PROJECT.transform(LON, LAT)
INVERSE = Transformer.from_crs(32611, 4326, always_xy=True)


def rectangle(x,y,w,h):
    return mapping(transform(box(X+x,Y+y,X+x+w,Y+y+h),INVERSE.transform,interleaved=False))


def setup():
    return dict(lon=LON,lat=LAT,
        markings=[{'kind':'drainage','geometry':rectangle(0,0,10,10)},
                  {'kind':'drainage','geometry':rectangle(5,0,10,10)},
                  {'kind':'treatment','geometry':rectangle(20,0,10,5)},
                  {'kind':'treatment','geometry':rectangle(20,10,10,10)}],
        design=dict(storage_depth_m=.1,runoff_coefficient=.8,surface_confirmed=True,connections_confirmed=True,
                    access_confirmed=True,overflow_confirmed=True,confirmation_note='PRIVATE-CONFIRMATION source notes'),
        hydrology={'estimate':{'inches':1.,'method':'on_contour','depth_range':[1.,1.]},'unavailable':[]},scenario=None,
        outlines=[{'type':'Feature','geometry':rectangle(-10,-10,100,100),'properties':{'label':'Parcel boundary','date':'2026-07-03','collection':'test-source','evidenceId':'outline-1'}},
                  {'type':'Feature','geometry':rectangle(40,40,10,10),'properties':{'label':'Building footprint','date':'2026-07-03','collection':'test-source','evidenceId':'outline-2'}}],
        property_details={'propertyType':'Multifamily','reportedParkingSpaces':25,'private':'PRIVATE-RECORD'},frontages=[],
        source_status={'outlines':'ready','property':'ready','hydrology':'ready'},identity={'site_id':'property:test','revision':1,'input_revision':0})


class StormwaterTest(unittest.TestCase):
    def test_small_design_inputs_are_not_changed_to_zero_in_agent_facts(self):
        args=setup();args['design'].update(storage_depth_m=.001,runoff_coefficient=.00000001)
        result=self.compare(args);facts={f['id']:f for f in result['facts']}
        self.assertEqual(facts['water-depth']['value'],.001)
        self.assertEqual(facts['water-depth']['display'],'0.001 m')
        self.assertEqual(facts['water-coefficient']['value'],.00000001)
        self.assertEqual(facts['water-coefficient']['display'],'0.00000001')

    def setUp(self):
        self.terrain=patch('stormwater.terrain_screen',return_value={'status':'ready','median_slope_percent':1.,'source':{'provider':'Test DEM'}})
        self.terrain.start();self.addCleanup(self.terrain.stop)

    def compare(self,args=None): return compare_water(**(args or setup()))

    def test_storage_conservation_direct_rain_and_union(self):
        result=self.compare();c=result['comparison'];p=result['proposal']
        self.assertEqual(c['status'],'ready');self.assertAlmostEqual(c['contributing_area_m2'],150.,places=5)
        for name, r in c['results'].items():
            self.assertAlmostEqual(r['runoff_m3'],.0254*150*.8,places=6)
            self.assertAlmostEqual(r['captured_m3']+r['excess_m3'],r['runoff_m3'])
            self.assertLessEqual(r['captured_m3'],r['runoff_m3'])
            self.assertLessEqual(r['captured_m3'],max(r['capacity_m3']-r['direct_rain_m3'],0))
            self.assertGreaterEqual(r['excess_m3'],0)
        self.assertEqual(c['ranking']['recommended'],'treatment-1') # Both capture all; smaller footprint wins.
        self.assertEqual(p['design']['kind'],'bioretention');self.assertIsNone(p['design']['length_m'])
        self.assertEqual({g['properties']['role'] for g in p['geometry']},{'proposed','contributing'})
        self.assertEqual(p['input_hash'],c['input_hash']);Proposal.model_validate(p)
        self.assertIn('water-treatment-1-verdict',{f['id'] for f in result['facts']})
        for f in result['facts']:self.assertIsInstance(f['source']['retrieved_at'],str)

    def test_direct_rain_consumes_capacity_and_never_negative(self):
        args=setup();args['design']['storage_depth_m']=.01
        c=self.compare(args)['comparison']
        self.assertIsNone(c['ranking']['recommended'])
        for name in ('treatment-1','treatment-2'):
            r=c['results'][name];self.assertEqual(r['captured_m3'],0)
            self.assertAlmostEqual(r['direct_excess_m3'],r['direct_rain_m3']-r['capacity_m3'])
            self.assertAlmostEqual(r['excess_m3'],r['runoff_m3'])

    def test_missing_inputs_preserve_unassessed_not_zero(self):
        mutations=[lambda a:a.update(design=None),lambda a:a['design'].update(surface_confirmed=False),
                   lambda a:a.update(outlines=[]),lambda a:a.update(property_details=None),
                   lambda a:a['source_status'].update(outlines='unavailable'),lambda a:a.update(hydrology={}),
                   lambda a:a.update(markings=a['markings'][:-1])]
        for mutate in mutations:
            with self.subTest(mutate=mutate):
                args=setup();mutate(args);r=self.compare(args)
                self.assertEqual(r['comparison']['status'],'unavailable');self.assertIsNone(r['proposal'])
                self.assertTrue(r['comparison']['missing_inputs'])
                for result in r['comparison']['results'].values():self.assertTrue(all(v is None for v in result.values()))

    def test_validation_rejects_coercion_unknown_missing_and_wrong_workflow(self):
        good=setup()['design'];self.assertEqual(validate_water_design(good,'water'),good)
        self.assertIsNone(validate_water_design(None,'street'))
        for key in ('storage_depth_m','runoff_coefficient'):
            for value in (True,False,None,'0.2',0,-1,1.1,float('nan'),float('inf')):
                with self.subTest(key=key,value=value),self.assertRaises(ValueError):validate_water_design({**good,key:value},'water')
        for change in ({'surface_confirmed':1},{'confirmation_note':''},{'confirmation_note':'x'*601},{'unknown':True}):
            with self.assertRaises(ValueError):validate_water_design({**good,**change},'water')
        partial=good.copy();del partial['overflow_confirmed']
        with self.assertRaises(ValueError):validate_water_design(partial,'water')
        with self.assertRaises(ValueError):validate_water_design(good,'street')

    def test_geometry_conflicts_reject_only_affected_candidate(self):
        for geometry in (rectangle(40,40,10,10),rectangle(0,0,10,10),rectangle(85,0,10,10)):
            args=setup();args['markings'][2]['geometry']=geometry
            r=self.compare(args);self.assertFalse(r['comparison']['ranking']['verdicts']['treatment-1']['eligible'])
            self.assertEqual(r['comparison']['ranking']['recommended'],'treatment-2')
            self.assertTrue(all(v is None for v in r['comparison']['results']['treatment-1'].values()))
        args=setup();args['markings'].append({'kind':'access','geometry':rectangle(20,0,2,2)})
        self.assertEqual(self.compare(args)['comparison']['ranking']['recommended'],'treatment-2')
        args=setup();args['markings'][3]['geometry']=args['markings'][2]['geometry']
        self.assertEqual(self.compare(args)['comparison']['status'],'unavailable')

    def test_terrain_failure_preserves_balance_but_blocks_recommendation(self):
        with patch('stormwater.terrain_screen',return_value={'status':'unavailable'}):
            r=self.compare();self.assertEqual(r['comparison']['status'],'ready');self.assertIsNone(r['proposal'])
            self.assertGreater(r['comparison']['results']['treatment-1']['captured_m3'],0)
            self.assertFalse(r['comparison']['ranking']['verdicts']['treatment-1']['eligible'])

    def test_revision_provenance_and_private_values(self):
        original=self.compare();initial=original['comparison']['input_hash']
        for mutate in (lambda a:a['identity'].update(revision=2),lambda a:a['identity'].update(input_revision=1),
                       lambda a:a['design'].update(confirmation_note='new source'),lambda a:a['outlines'][0]['properties'].update(date='2025-01-01'),
                       lambda a:a['design'].update(runoff_coefficient=.7),lambda a:a['property_details'].update(reportedParkingSpaces=26)):
            args=setup();mutate(args);self.assertNotEqual(self.compare(args)['comparison']['input_hash'],initial)
        self.assertEqual(self.compare()['comparison']['input_hash'],initial)
        serialized=json.dumps(original['facts']);self.assertNotIn('PRIVATE',serialized);self.assertNotIn(str(LON),serialized)
        self.assertNotIn('PRIVATE-RECORD',json.dumps(original['comparison']))
        self.assertTrue(any(s.get('observed_at')=='2026-07-03' for s in original['comparison']['sources']))
        tampered=deepcopy(original['proposal']);tampered['geometry'][0]['properties']['revision']=2
        with self.assertRaises(ValueError):Proposal.model_validate(tampered)
        with self.assertRaises(ValueError):from_water_comparison(original['comparison'],'treatment-2',site_id='site',revision=1,input_revision=0)

    def test_frontage_conflict_missing_and_malformed_are_distinct(self):
        args=setup();missing=self.compare(args)
        self.assertEqual(missing['comparison']['checks']['treatment-1']['frontage_status'],'unassessed')
        self.assertIsNone(missing['comparison']['checks']['treatment-1']['frontage_conflicts'])
        line=mapping(transform(LineString([(X+21,Y-1),(X+21,Y+6)]),INVERSE.transform,interleaved=False))
        args['frontages']=[{'geometry':line,'curbCuts':1,'selectedProperty':True}]
        conflict=self.compare(args)
        self.assertEqual(conflict['comparison']['checks']['treatment-1']['frontage_conflicts'],1)
        self.assertEqual(conflict['comparison']['ranking']['recommended'],'treatment-2')
        self.assertTrue(any(f['id']=='water-costar-reportedParkingSpaces' and f['value']==25 for f in conflict['facts']))
        self.assertTrue(any(f['id']=='water-treatment-1-frontage-conflicts' and f['value']==1 for f in conflict['facts']))
        for cuts in (None,True,-1,1.5,'1'):
            args['frontages'][0]['curbCuts']=cuts
            bad=self.compare(args)
            self.assertEqual(bad['comparison']['checks']['treatment-1']['frontage_status'],'unavailable')
            self.assertIsNone(bad['proposal']);self.assertIsNone(bad['comparison']['checks']['treatment-1']['frontage_conflicts'])
        args['frontages']=[{'geometry':{'type':'LineString','coordinates':[]},'curbCuts':1}]
        self.assertEqual(self.compare(args)['comparison']['status'],'unavailable')

    def test_rainfall_scenario_remains_explicit_and_rain_changes_metrics(self):
        args=setup();original=self.compare(args)
        args['scenario']={'inches':2,'source':'Planner documented event'}
        updated=self.compare(args);self.assertEqual(updated['comparison']['rainfall']['basis'],'user_provided')
        self.assertAlmostEqual(updated['comparison']['results']['baseline']['runoff_m3'],2*original['comparison']['results']['baseline']['runoff_m3'])
        self.assertNotEqual(updated['comparison']['input_hash'],original['comparison']['input_hash'])
        self.assertEqual(updated['proposal']['evidence'][-1]['classification'],'user_provided')

if __name__=='__main__':unittest.main()
