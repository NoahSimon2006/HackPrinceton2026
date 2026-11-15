import json
import math
import unittest
from copy import deepcopy
from shapely.geometry import Point
from site_measurements import PROJECT, measure_candidates, measure_outlines, projected
from stormwater_planning import plan_stormwater
from test_site_measurements import LON, LAT, INVERSE, X, Y, feature, polygon


def raw_point(x,y):
    lon,lat=INVERSE.transform(X+x,Y+y)
    return {'lon':lon,'lat':lat}


class StormwaterPlanningTest(unittest.TestCase):
    def setUp(self):
        self.outlines=[feature(polygon(-30,-20,60,40),'Parcel boundary'),feature(polygon(-10,-5,20,10),'Building footprint')]
        self.outlines[0]['properties']['buildingCoverage']=True
        self.detections=[feature(polygon(14,-18,12,14),'Landscaped strip')]
        measure_outlines(self.outlines,LON,LAT,nearby=True);measure_candidates(self.detections,LON,LAT)
        self.evidence={'outlines':self.outlines,'detections':self.detections,'frontages':[]}
        self.identity={'site_id':'unchanged-selected-opportunity','revision':1,'input_revision':0}

    def plan(self,*,settings=None,markings=(),rainfall=None,scenario=None,previous=None,property_context=None,identity=None,evidence=None):
        return plan_stormwater(lon=LON,lat=LAT,evidence=evidence or self.evidence,markings=list(markings),rainfall={'inches':1} if rainfall is None else rainfall,
            scenario=scenario,settings=settings or {},identity=identity or self.identity,previous=previous,property_context=property_context)

    @staticmethod
    def metrics(proposal):return {m.id:m.proposed for m in proposal.metrics}

    def test_real_polygons_alternatives_and_unknown_capture(self):
        result=self.plan();proposal=result['proposal']
        self.assertIsNone(result['question']);self.assertEqual(proposal.design.kind,'bioretention')
        self.assertGreaterEqual(len(result['alternatives']),2);self.assertEqual(result['comparison']['selected'],'water-option-1')
        for item in result['alternatives'].values():
            bed=projected(item['geometry'][0]['geometry']);self.assertTrue(projected(self.outlines[0]['geometry']).covers(bed))
            self.assertTrue(bed.disjoint(projected(self.outlines[1]['geometry'])))
            self.assertTrue(all(m['revision']==1 and m['input_hash']==item['input_hash'] for m in item['metrics']))
        values=self.metrics(proposal)
        for key in ('runoff_volume','captured_volume','overflow_volume'):self.assertIsNone(values[key])
        self.assertAlmostEqual(values['storage_volume'],values['footprint_area']*.15,places=3)
        self.assertEqual(len({json.dumps(v['geometry']) for v in result['alternatives'].values()}),len(result['alternatives']))

    def test_keep_clear_revision_changes_geometry_and_hash(self):
        first=self.plan()['proposal'];previous=first.model_dump()
        bed=first.geometry[0].geometry
        changed=self.plan(markings=[{'kind':'access','geometry':bed}],previous=previous,identity={**self.identity,'revision':2,'input_revision':1})
        second=changed['proposal'];self.assertIsNotNone(second)
        self.assertTrue(projected(second.geometry[0].geometry).intersection(projected(bed)).area<1e-6)
        self.assertNotEqual(first.input_hash,second.input_hash);self.assertEqual(second.revision,2)
        self.assertIn('marking-1',second.access.evidence_ids)

    def test_union_what_if_reserves_direct_rain_and_conserves(self):
        area=polygon(-10,-5,20,10)
        result=self.plan(markings=[{'kind':'drainage','geometry':area}]*2,settings={'drainageAssumption':'marked_connected','runoffCoefficient':.8,'targetAreaM2':10},scenario={'inches':1,'source':'Explicit test storm'})
        values=self.metrics(result['proposal'])
        self.assertEqual(values['contributing_area'],200)
        self.assertEqual(values['runoff_volume'],4.064)
        self.assertAlmostEqual(values['captured_volume'],values['storage_volume']-values['direct_rain_volume'],places=3)
        self.assertAlmostEqual(values['captured_volume']+values['overflow_volume'],values['runoff_volume'],places=3)
        self.assertEqual(result['comparison']['scenario']['name'],'Explicit test storm')
        self.assertTrue(any('Explicit what-if' in item for item in result['proposal'].assumptions))

    def test_roof_or_coefficient_alone_does_not_establish_connected_drainage(self):
        area=self.outlines[1]['geometry']
        for settings,markings in [({'runoffCoefficient':.8},[{'kind':'drainage','geometry':area}]),({'runoffCoefficient':.8,'drainageAssumption':'marked_connected'},[])]:
            result=self.plan(settings=settings,markings=markings)
            self.assertIsNone(self.metrics(result['proposal'])['captured_volume'])

    def test_zero_coefficient_and_zero_rain_are_valid_explicit_scenarios(self):
        marked=[{'kind':'drainage','geometry':self.outlines[1]['geometry']}]
        for coefficient,inches in [(0,1),(.8,0)]:
            result=self.plan(markings=marked,settings={'drainageAssumption':'marked_connected','runoffCoefficient':coefficient},scenario={'inches':inches,'source':'Zero sensitivity'})
            values=self.metrics(result['proposal']);self.assertEqual(values['runoff_volume'],0);self.assertEqual(values['captured_volume'],0)

    def test_direct_rain_over_capacity_does_not_capture_external_runoff(self):
        result=self.plan(markings=[{'kind':'drainage','geometry':self.outlines[1]['geometry']}],settings={'drainageAssumption':'marked_connected','runoffCoefficient':1,'storageDepthM':.05},scenario={'inches':10,'source':'Extreme what-if'})
        values=self.metrics(result['proposal']);self.assertEqual(values['captured_volume'],0);self.assertGreater(values['direct_overflow_volume'],0)
        self.assertEqual(values['overflow_volume'],values['runoff_volume'])

    def test_no_event_preserves_unknown_values(self):
        result=self.plan(rainfall={},settings={'drainageAssumption':'marked_connected','runoffCoefficient':.8},markings=[{'kind':'drainage','geometry':self.outlines[1]['geometry']}])
        values=self.metrics(result['proposal']);self.assertIsNone(values['captured_volume']);self.assertIsNone(values['direct_rain_volume'])
        self.assertGreater(values['storage_volume'],0)

    def test_rainfall_revision_preserves_shape_but_changes_hash_and_volumes(self):
        first=self.plan()['proposal']
        second=self.plan(scenario={'inches':2,'source':'Larger scenario'},identity={**self.identity,'revision':2,'input_revision':1})['proposal']
        self.assertEqual(first.geometry[0].geometry,second.geometry[0].geometry)
        self.assertNotEqual(first.input_hash,second.input_hash)
        self.assertAlmostEqual(self.metrics(second)['direct_rain_volume'],2*self.metrics(first)['direct_rain_volume'],delta=.001)

    def test_target_area_layout_and_placement_revisions(self):
        first=self.plan()['proposal']
        smaller=self.plan(settings={'targetAreaM2':10})['proposal']
        linear=self.plan(settings={'layout':'linear'})['proposal']
        moved=self.plan(settings={'placement':'away_from_previous'},previous=first.model_dump())['proposal']
        self.assertLess(self.metrics(smaller)['footprint_area'],self.metrics(first)['footprint_area'])
        self.assertNotEqual(first.geometry[0].geometry,linear.geometry[0].geometry)
        self.assertGreater(projected(moved.geometry[0].geometry).distance(projected(first.geometry[0].geometry)),1)

    def test_multifamily_context_changes_circulation_geometry_with_cited_assumption(self):
        baseline=self.plan()['proposal']
        context={'hostProperties':[{**raw_point(0,0),'type':'Multifamily','details':{'propertyType':'Multifamily','units':194}}]}
        result=self.plan(property_context=context);proposal=result['proposal']
        self.assertNotEqual(baseline.geometry[0].geometry,proposal.geometry[0].geometry)
        self.assertGreaterEqual(projected(proposal.geometry[0].geometry).distance(projected(self.outlines[1]['geometry'])),1.999)
        decision=next(d for d in result['decisions'] if d['source']=='CoStar local property kit')
        self.assertIn('proposed 2 m',decision['decision']);self.assertIn('water-siting-',decision['fact_id'])
        self.assertTrue(decision['evidence_ids']);self.assertNotIn('194',str(result['facts']))

    def test_ambiguous_host_records_do_not_supply_one_parking_count(self):
        context={'hostProperties':[{**raw_point(0,0),'type':'Multifamily','details':{'reportedParkingSpaces':204}},
                                   {**raw_point(1,1),'type':'Multifamily','details':{'reportedParkingSpaces':999}}]}
        result=self.plan(property_context=context);text=json.dumps(result['facts'])
        self.assertNotIn('204',text);self.assertNotIn('999',text);self.assertIn('2 record(s)',text)
        self.assertTrue(any('CoStar' in r.source for r in result['proposal'].evidence))

    def test_frontage_constraint_preserves_rejected_exact_footprint(self):
        line={'type':'LineString','coordinates':[list(INVERSE.transform(X-30,Y+8)),list(INVERSE.transform(X+30,Y+8))]}
        self.evidence['frontages']=[{'geometry':line,'curbCuts':1,'evidenceId':'frontage-1'}]
        result=self.plan();bed=projected(result['proposal'].geometry[0].geometry)
        self.assertLess(bed.intersection(projected(line).buffer(3)).area,1e-6)
        rejects=[row for row in result['comparison']['results'] if row['status']=='rejected']
        self.assertTrue(rejects)
        for row in rejects:
            rejected=result['alternatives'][row['id']]
            self.assertGreater(projected(rejected['geometry'][0]['geometry']).intersection(projected(line).buffer(3)).area,0)
            self.assertFalse(rejected['geometry'][0]['properties']['eligible'])
            self.assertNotEqual(row['id'],result['comparison']['selected'])

    def test_nearby_host_is_provisional_and_does_not_change_site_identity(self):
        self.evidence['outlines']=[feature(polygon(25,-20,50,40),'Parcel boundary'),feature(polygon(35,-5,20,10),'Building footprint')]
        self.evidence['outlines'][0]['properties']['buildingCoverage']=True
        result=self.plan();proposal=result['proposal']
        self.assertEqual(proposal.site_id,self.identity['site_id']);self.assertTrue(result['comparison']['results'][0]['provisionalHost'])
        self.assertTrue(any('Provisional nearby host parcel' in a for a in proposal.assumptions))
        self.assertGreater(projected(proposal.geometry[0].geometry).distance(Point(X,Y)),20)

    def test_complete_coverage_and_protect_access_gaps_are_specific(self):
        self.evidence['outlines'][0]['properties']['buildingCoverage']=False
        self.assertIsNone(self.plan()['proposal'])
        self.evidence['outlines'][0]['properties']['buildingCoverage']=True
        result=self.plan(settings={'protectAccess':True})
        self.assertIsNone(result['proposal']);self.assertIn('outline the driveway',result['question'])

    def test_nearly_coincident_parcels_use_conservative_intersection(self):
        duplicate=feature(polygon(-29.9,-20,59.9,40),'Parcel boundary');duplicate['properties']['buildingCoverage']=True
        self.evidence['outlines'].append(duplicate)
        result=self.plan();self.assertIsNotNone(result['proposal'])
        self.assertTrue(any('reconciled' in a for a in result['proposal'].assumptions))
        self.assertTrue(projected(duplicate['geometry']).covers(projected(result['proposal'].geometry[0].geometry)))
        self.evidence['outlines'].append(feature(polygon(-15,-10,40,30),'Parcel boundary'))
        self.assertIsNone(self.plan()['proposal'])

    def test_model_facts_and_decisions_do_not_contain_raw_geometry_or_addresses(self):
        context={'hostProperties':[{**raw_point(0,0),'name':'PRIVATE-NAME','address':'PRIVATE-ADDRESS','type':'Multifamily','details':{'propertyType':'Multifamily'}}]}
        result=self.plan(property_context=context);safe=json.dumps({'facts':result['facts'],'decisions':result['decisions'],'comparison':result['comparison']})
        for forbidden in ('coordinates','PRIVATE-NAME','PRIVATE-ADDRESS',str(LON),str(LAT)):self.assertNotIn(forbidden,safe)

    def test_access_protection_is_checked_per_host_not_borrowed_from_another(self):
        left=feature(polygon(-34,-8,14,16),'Parcel boundary')
        right=feature(polygon(20,-20,50,40),'Parcel boundary')
        for parcel in (left,right):parcel['properties']['buildingCoverage']=True
        outlines=[left,feature(polygon(-32,-4,9,8),'Building footprint'),right,feature(polygon(35,-5,20,10),'Building footprint')]
        measure_outlines(outlines,LON,LAT,nearby=True)
        driveway=feature(polygon(-22.5,5,2,2),'Driveway entrance')
        measure_candidates([driveway],LON,LAT)
        evidence={'outlines':outlines,'detections':[driveway],'frontages':[]}
        first=self.plan(evidence=evidence)['proposal']
        self.assertTrue(projected(right['geometry']).covers(projected(first.geometry[0].geometry)), 'Unconstrained larger host should otherwise win on target fit.')
        protected=self.plan(evidence=evidence,settings={'protectAccess':True})
        self.assertIsNotNone(protected['proposal'])
        self.assertTrue(projected(left['geometry']).covers(projected(protected['proposal'].geometry[0].geometry)))
        self.assertEqual(len(protected['comparison']['unavailableHosts']),1)
        for item in protected['alternatives'].values():
            self.assertTrue(projected(left['geometry']).covers(projected(item['geometry'][0]['geometry'])))
        # A planner marking on the left host cannot satisfy the right host either.
        evidence['detections']=[]
        marked=self.plan(evidence=evidence,settings={'protectAccess':True},markings=[{'kind':'access','geometry':driveway['geometry']}])
        self.assertTrue(projected(left['geometry']).covers(projected(marked['proposal'].geometry[0].geometry)))
        self.assertEqual(len(marked['comparison']['unavailableHosts']),1)

    def test_unrelated_access_mark_does_not_satisfy_selected_host(self):
        result=self.plan(settings={'protectAccess':True},markings=[{'kind':'access','geometry':polygon(80,80,5,5)}])
        self.assertIsNone(result['proposal'])
        self.assertIn('outline the driveway',result['question'])
        self.assertEqual(len(result['comparison']['unavailableHosts']),1)

    def test_thin_clipped_fragment_is_not_a_usable_footprint(self):
        result=self.plan(markings=[{'kind':'treatment','geometry':polygon(15,-10,.4,10)}])
        self.assertIsNone(result['proposal'])

    def test_source_change_changes_hash_even_if_footprint_is_same(self):
        first=self.plan()['proposal']
        self.outlines[0]['properties']['date']='2025-01-01'
        second=self.plan()['proposal']
        self.assertEqual(first.geometry[0].geometry,second.geometry[0].geometry)
        self.assertNotEqual(first.input_hash,second.input_hash)

    def test_selected_parameters_have_citable_facts_and_unknown_coefficient_does_not(self):
        result=self.plan(settings={'storageDepthM':.17,'runoffCoefficient':.8,'layout':'linear','placement':'landscape_first'})
        facts={item['id']:item for item in result['facts']}
        self.assertEqual(facts['water-storage-depth']['value'],.17)
        self.assertEqual(facts['water-storage-depth']['basis'],'assumption')
        self.assertEqual(facts['water-host-distance']['value'],0)
        self.assertEqual(facts['water-layout-placement']['value'],'linear; landscape_first')
        self.assertNotIn('water-runoff-coefficient',facts)
        self.evidence['outlines']=[feature(polygon(25.14,-20,50,40),'Parcel boundary'),feature(polygon(35,-5,20,10),'Building footprint')]
        self.evidence['outlines'][0]['properties']['buildingCoverage']=True
        explicit=self.plan(settings={'drainageAssumption':'marked_connected','runoffCoefficient':0},markings=[{'kind':'drainage','geometry':self.evidence['outlines'][1]['geometry']}])
        facts={item['id']:item for item in explicit['facts']}
        self.assertEqual(facts['water-runoff-coefficient']['value'],0)
        self.assertEqual(facts['water-runoff-coefficient']['basis'],'assumption')
        self.assertEqual(facts['water-host-distance']['value'],25.1)
        self.assertTrue(any('25.1 m' in text for text in explicit['proposal'].assumptions))

    def test_parameter_limits_and_minimum_area(self):
        for settings in ({'targetAreaM2':501},{'targetAreaM2':True},{'storageDepthM':.01},{'runoffCoefficient':math.nan},{'layout':'invented'}):
            with self.assertRaises(ValueError):self.plan(settings=settings)
        self.assertIsNotNone(self.plan(settings={'targetAreaM2':2})['proposal'])

if __name__=='__main__':unittest.main()
