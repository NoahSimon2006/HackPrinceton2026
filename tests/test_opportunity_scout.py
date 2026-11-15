import json
import unittest
from copy import deepcopy
from unittest.mock import patch
from shapely.geometry import box, mapping

import opportunity_scout as scout

BOUNDS = [-118.31, 34.05, -118.29, 34.075]


def feature(identifier, x, value, *, workflow='water', y=34.06):
    return {'type': 'Feature', 'id': identifier,
            'geometry': {'type': 'LineString', 'coordinates': [[x-.0001,y],[x,y]]},
            'properties': {'value': value, 'center': [x,y], 'label': 'Private location label',
                           'scalar_detail': {'window_edge_contribution': False, 'direction_verified': True,
                                             'road_closure': False, 'road_name': 'A street', 'direction': 'N',
                                             'speed_kmh': 10, 'free_flow_kmh': 40, 'length_m': 15,
                                             'time_penalty_s': 12}}}


def data(features, workflow='water', *, version='v1'):
    return {'bbox': BOUNDS, 'version': version, 'flow_expires_epoch': 9999999999,
            'sources': {'source': {'label': 'USGS terrain' if workflow == 'water' else 'TomTom Traffic',
                                  'url': 'https://example.test/source', 'retrieved_at': '2026-11-15'}},
            'layers': [{'id': 'terrain' if workflow == 'water' else 'flow', 'status': 'ready', 'source': 'source',
                        'features': features, 'unit': 'm²' if workflow == 'water' else '%', 'method': 'Screening',
                        'limitations': 'Not measured design benefit.', 'period': 'Test observed period', 'version': version}]}


def sponsor(ready=False):
    return {'facts': [], 'warnings': [], 'vexcel': 'available' if ready else 'unavailable',
            'costar': 'matched' if ready else 'nearby_context', 'association': 'matched' if ready else 'unmatched',
            'property': {'id': 'private-id', 'address': 'Private sponsor address'} if ready else None,
            'nearbyUses': ['Retail'], 'nearbyCount': 1}


class OpportunityTests(unittest.TestCase):
    def research(self, features, workflow='water', exclude=(), sponsors=None):
        with patch.object(scout, 'map_discovery', return_value=data(features,workflow)), patch.object(scout, '_research_site', side_effect=sponsors or (lambda *a: sponsor())):
            return scout.research_candidates(workflow, BOUNDS, exclude)

    def test_stronger_environment_screen_does_not_lose_to_readiness(self):
        candidates=self.research([feature('low',-118.30,100),feature('high',-118.305,1000)], sponsors=[sponsor(False),sponsor(True)])['candidates']
        self.assertEqual([c['environmental']['metrics'][0]['value'] for c in candidates],[1000,100])
        self.assertEqual(candidates[0]['readiness']['sponsors']['vexcel'],'unavailable')
        self.assertIsNone(candidates[0]['propertyId'])
        self.assertEqual(candidates[1]['propertyId'],'private-id')

    def test_group_before_history_exclusion_and_fewer_than_three(self):
        features=[feature('first',-118.30,1000),feature('same',-118.3001,900),feature('other',-118.305,800)]
        first=self.research(features)
        self.assertEqual(len(first['candidates']),2)
        self.assertTrue(first['exhausted'])
        second=self.research(features,exclude=[first['candidates'][0]['id']])
        self.assertEqual(len(second['candidates']),1)
        self.assertEqual(second['candidates'][0]['id'],first['candidates'][1]['id'])

    def test_model_context_never_contains_labels_coordinates_or_property_ids(self):
        candidate=self.research([feature('first',-118.30,1000)], sponsors=[sponsor(True)])['candidates'][0]
        context=json.dumps(candidate['modelContext'])
        for forbidden in ('Private sponsor address','Private location label','private-id','-118.3','coordinates'):
            self.assertNotIn(forbidden,context)
        self.assertIn('geometry',candidate)
        self.assertEqual(candidate['provenance']['kind'],'opportunity')

    def test_validate_before_provider_read_and_no_outside_candidates(self):
        with patch.object(scout,'map_discovery') as fetch:
            with self.assertRaises(ValueError):scout.research_candidates('water',[-119,34,-118,35])
            fetch.assert_not_called()
        result=self.research([feature('outside',-118.33,1000)])
        self.assertEqual(result['candidates'],[])
        self.assertTrue(result['warnings'])

    def test_traffic_excludes_non_slow_closed_unverified_and_duplicate_queue(self):
        features=[feature('fast',-118.300,95),feature('closed',-118.302,20),feature('unverified',-118.304,15),
                  feature('slow',-118.306,25),feature('samequeue',-118.3061,30)]
        features[1]['properties']['scalar_detail']['road_closure']=True
        features[2]['properties']['scalar_detail']['direction_verified']=False
        result=self.research(features,'street')
        self.assertEqual(len(result['candidates']),1)
        candidate=result['candidates'][0]
        self.assertEqual(candidate['environmental']['metrics'][0]['value'],25)
        self.assertIn('CO₂ savings',candidate['environmental']['basis'])
        self.assertEqual(candidate['expiresAt'],9999999999)

    def test_show_more_excludes_a_changed_or_dissolved_traffic_group(self):
        a=feature('flow-a',-118.306,20); b=feature('flow-b',-118.3058,25)
        other=feature('flow-other',-118.300,45)
        approach=feature('approach-ab',-118.306,22)
        approach['properties']['member_ids']=['flow-a','flow-b']
        original=data([a,b,other],'street')
        original['layers'].append({**deepcopy(original['layers'][0]),'id':'approaches','features':[approach]})
        with patch.object(scout,'map_discovery',return_value=original),patch.object(scout,'_research_site',return_value=sponsor()):
            prior=scout.research_candidates('street',BOUNDS)['candidates'][0]
        history=prior['provenance']['groupedCandidateIds']
        self.assertEqual(len(history),3)  # Group identity plus both stable portions.
        changed=deepcopy(approach); changed['id']='approach-bc'
        changed['properties']['member_ids']=['flow-b','flow-c']
        for groups in ([changed],[]):
            with self.subTest(regrouped=bool(groups)):
                current=data([b,other],'street')
                current['layers'].append({**deepcopy(current['layers'][0]),'id':'approaches','features':groups})
                with patch.object(scout,'map_discovery',return_value=current),patch.object(scout,'_research_site',return_value=sponsor()):
                    result=scout.research_candidates('street',BOUNDS,history)
                self.assertEqual(len(result['candidates']),1)
                self.assertEqual(result['candidates'][0]['provenance']['featureId'],'flow-other')

    def test_traffic_refresh_removes_missing_and_updates_all_live_facts(self):
        features=[feature('first',-118.30,20),feature('second',-118.305,30)]
        old=self.research(features,'street')
        changed=deepcopy(features[:1]);changed[0]['properties']['value']=45
        with patch.object(scout,'map_discovery',return_value=data(changed,'street',version='v2')):
            result=scout.refresh_traffic_candidates(old,BOUNDS)
        self.assertTrue(result['reviewStale'])
        self.assertEqual(len(result['candidates']),1)
        self.assertEqual(result['candidates'][0]['evidence'][0]['value'],45)
        self.assertEqual(result['candidates'][0]['provenance']['version'],'v2')

    def test_cancellation_propagates(self):
        with patch.object(scout,'map_discovery') as fetch:
            with self.assertRaises(RuntimeError):
                scout.research_candidates('water',BOUNDS,check=lambda: (_ for _ in ()).throw(RuntimeError('cancelled')))
            fetch.assert_not_called()

    def test_source_error_continues_and_nearby_is_not_an_association(self):
        import server
        point=[-118.30,34.06]
        nearby={'id':'neighbor','lon':-118.3002,'lat':34.06,'type':'Retail','name':'Private Neighbor'}
        with patch.object(server,'site_outlines',side_effect=ValueError('private error')), patch.object(server,'property_catalog',return_value=([nearby],{},{})), patch.object(server,'nearby_frontages',return_value=[]):
            result=scout._research_site('water',point,lambda:None)
        self.assertEqual(result['vexcel'],'unavailable')
        self.assertEqual(result['costar'],'nearby_context')
        self.assertIsNone(result['property'])
        self.assertTrue(any('CoStar' in item['source']['provider'] for item in result['facts']))
        self.assertNotIn('private error',json.dumps(result))

    def test_transient_retry_is_bounded_and_configuration_does_not_retry(self):
        import server
        for error, attempts, status in ((scout.TransientSourceError('transport'),2,'unavailable'),
                                        (ValueError('Vexcel key is missing from the local .env file.'),1,'configuration_missing')):
            with patch.object(server,'site_outlines',side_effect=error) as outlines, patch.object(server,'property_catalog',return_value=([],{},{})), patch.object(server,'nearby_frontages',return_value=[]):
                result=scout._research_site('water',[-118.30,34.06],lambda:None)
            self.assertEqual(outlines.call_count,attempts)
            self.assertEqual(result['vexcel'],status)

    def test_unique_same_parcel_association_and_both_sponsor_facts(self):
        import server
        point=[-118.30,34.06]
        record={'id':'onsite','lon':point[0],'lat':point[1],'type':'Retail','address':'Private address'}
        outlines=[{'type':'Feature','properties':{'label':'Parcel boundary'},'geometry':mapping(box(-118.3002,34.0598,-118.2998,34.0602))}]
        with patch.object(server,'site_outlines',return_value=outlines),patch.object(server,'property_catalog',return_value=([record],{'onsite':{'propertyType':'Retail','reportedParkingSpaces':12}},{})),patch.object(server,'nearby_frontages',return_value=[]):
            result=scout._research_site('water',point,lambda:None)
        self.assertEqual(result['association'],'matched')
        providers={f['source']['provider'] for f in result['facts']}
        self.assertIn('CoStar local property kit',providers)
        self.assertIn('Vexcel parcel extraction',providers)
        self.assertEqual(result['property']['id'],'onsite')


if __name__=='__main__':unittest.main()
