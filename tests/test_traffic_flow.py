import json
import time
import unittest
from unittest.mock import patch
import mapbox_vector_tile
import openlr
from pyproj import Transformer
from shapely.geometry import LineString, shape
from shapely.ops import transform
import traffic_flow as flow
import discovery


X,Y=flow.tiles_for((-118.246,34.049,-118.239,34.056))[0]
CHAIN=[[1024,1024],[2048,1024],[3072,1024]]


def feature(chain=CHAIN, speed=36., ratio=.5, code=None, **extra):
    coordinates=[flow.tile_coordinate(X,Y,*xy,4096) for xy in chain]
    if code is None:
        bearing=90 if chain[0][0]<chain[-1][0] else 270
        a,b=coordinates[0],coordinates[-1]
        points=[openlr.LocationReferencePoint(*a,openlr.FRC.FRC4,openlr.FOW.SINGLE_CARRIAGEWAY,bearing,openlr.FRC.FRC4,600),
                openlr.LocationReferencePoint(*b,openlr.FRC.FRC4,openlr.FOW.SINGLE_CARRIAGEWAY,(bearing+180)%360,openlr.FRC.FRC7,0)]
        code=openlr.binary_encode(openlr.LineLocationReference(points,0,0))
    return {'geometry':{'type':'LineString','coordinates':chain},'properties':{'absolute_speed':speed,'relative_speed':ratio,'openlr':code,'road_category':'street','part_of_two_way_road':True,**extra}}


def response(features):
    return {'tile':(X,Y),'body':mapbox_vector_tile.encode({'name':'Traffic flow','features':features},default_options={'y_coord_down':True}),
            'received':time.time(),'ttl':60,'http_date':'Sun, 15 Nov 2026 05:00:00 GMT','data_ids':'opaque#123'}


class FlowTest(unittest.TestCase):
    def setUp(self):
        self.names=patch('traffic_flow.named_roads',return_value=([],None,None));self.names.start();self.addCleanup(self.names.stop)

    def test_tile_decode_units_direction_and_duplicate_conservation(self):
        r=response([feature()]);features,audit=flow.decode_tiles([r,r])
        self.assertEqual(len(features),1)
        p=features[0]['properties'];d=p['scalar_detail']
        self.assertEqual(p['value'],50)
        self.assertEqual(d['speed_kmh'],36)
        self.assertEqual(d['free_flow_kmh'],72)
        self.assertEqual(d['direction'],'E')
        self.assertTrue(d['direction_verified'])
        self.assertIsNone(d['confidence']);self.assertIsNone(d['observation_time'])
        self.assertAlmostEqual(d['travel_time_s'],d['length_m']/10,delta=.1)
        self.assertAlmostEqual(d['time_penalty_s'],d['length_m']/20,delta=.1)
        first=features[0]['geometry']['coordinates'][0]
        expected=flow.tile_coordinate(X,Y,*CHAIN[0],4096)
        self.assertAlmostEqual(first[0],expected[0],places=7)
        self.assertAlmostEqual(first[1],expected[1],places=7)

    def test_opposite_directions_remain_separate_and_zero_is_not_a_freeflow_estimate(self):
        features,_=flow.decode_tiles([response([feature(),feature(list(reversed(CHAIN)),speed=0,ratio=0)])])
        self.assertEqual(len(features),2)
        self.assertEqual({f['properties']['scalar_detail']['direction'] for f in features},{'E','W'})
        stopped=next(f['properties']['scalar_detail'] for f in features if f['properties']['value']==0)
        self.assertIsNone(stopped['free_flow_kmh']);self.assertIsNone(stopped['time_penalty_s'])

    def test_conflicting_source_values_and_malformed_payload_do_not_invent_a_winner(self):
        a=feature();b=feature(speed=18,ratio=.25,code=a['properties']['openlr'])
        result,audit=flow.decode_tiles([response([a,b])])
        self.assertEqual(result,[]);self.assertEqual(audit['conflicting_flow_references'],1)
        with self.assertRaises(ValueError):flow.decode_tiles([{'tile':(X,Y),'body':b'not a tile'}])
        invalid=feature();invalid['properties']['relative_speed']=1.5
        self.assertEqual(flow.decode_tiles([response([invalid])])[0],[])

    def test_openlr_mismatch_does_not_assign_direction(self):
        mismatch=feature([[100,100],[200,100]])['properties']['openlr']
        features,_=flow.decode_tiles([response([feature(code=mismatch)])])
        self.assertFalse(features[0]['properties']['scalar_detail']['direction_verified'])
        self.assertIsNone(features[0]['properties']['scalar_detail']['direction'])

    def test_live_cache_is_short_lived_bounded_and_never_falls_back_to_expired_data(self):
        r=response([feature()])
        with patch.dict('os.environ',{'TOMTOM_API_KEY':'test-secret'}),patch.multiple(flow,_snapshot=None,_attempted_at=0.,_requests=0), \
             patch('traffic_flow.tiles_for',return_value=[(X,Y)]),patch('traffic_flow.fetch_tile',return_value=r) as fetch:
            first=flow.get_snapshot();second=flow.get_snapshot()
            self.assertEqual(first['version'],second['version']);self.assertEqual(fetch.call_count,1)
            self.assertNotIn('test-secret',json.dumps(first))
            first['layers'][0]['features'].clear()
            self.assertTrue(flow.resolve_snapshot(second['version'])['layers'][0]['features'],'callers receive separate copies')
            with patch('traffic_flow.time.time',return_value=r['received']+61):
                with self.assertRaisesRegex(ValueError,'expired'):flow.resolve_snapshot(second['version'])
                fetch.side_effect=ValueError('Provider unavailable')
                failed=flow.get_snapshot()
                self.assertEqual(failed['layers'][0]['status'],'unavailable')
                self.assertEqual(failed['layers'][0]['features'],[])
        with patch.dict('os.environ',{'TOMTOM_API_KEY':'test-secret'}),patch.multiple(flow,_snapshot=None,_attempted_at=0.,_requests=256),patch('traffic_flow.fetch_tile') as fetch:
            self.assertEqual(flow.get_snapshot()['layers'][0]['status'],'unavailable');fetch.assert_not_called()

    def test_map_reference_uses_its_own_version_and_rejects_relocation(self):
        features,_=flow.decode_tiles([response([feature()])]);p=features[0]['properties']
        data={'version':'flow-abc','sources':{'tomtom':{'label':'TomTom','url':flow.DOC,'retrieved_at':'2026-11-15T00:00:00Z','observed_at':None}},
              'layers':[{'id':'flow','status':'partial','source':'tomtom','features':features,'classification':'estimated','unit':'% of free-flow speed','period':'Retrieved today','method':'Decoded tiles','limitations':flow.LIMITS}]}
        ref={'version':'flow-abc','layer':'flow','feature':features[0]['id']}
        with patch('traffic_flow.resolve_snapshot',return_value=data):
            context=discovery.discovery_context('street',ref,*p['center'])
            self.assertIsNone(context['source']['observed_at'],'retrieval is not observation')
            self.assertNotIn('coordinates',json.dumps(context));self.assertNotIn('center',json.dumps(context))
            with self.assertRaises(ValueError):discovery.discovery_context('street',ref,p['center'][0]+.01,p['center'][1])

    def test_connected_approach_does_not_merge_an_opposing_queue(self):
        from copy import deepcopy
        a=flow.decode_tiles([response([feature()])])[0][0]
        a['properties']['scalar_detail']['road_name']='Test Street'
        b=deepcopy(a);b['id']='next'
        acoords=a['geometry']['coordinates'];dx=acoords[-1][0]-acoords[0][0]
        b['geometry']['coordinates']=[[x+dx,y] for x,y in acoords]
        c=deepcopy(b);c['id']='opposite';c['properties']['scalar_detail']['direction']='W'
        grouped=flow.group_approaches([a,b,c])
        self.assertEqual(len(grouped),1)
        self.assertEqual(set(grouped[0]['properties']['member_ids']),{a['id'],'next'})
        self.assertEqual(grouped[0]['properties']['scalar_detail']['member_count'],2)


if __name__=='__main__':unittest.main()
