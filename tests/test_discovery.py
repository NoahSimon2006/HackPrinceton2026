import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import numpy as np
import discovery
from scripts import build_discovery as builder
from scripts.build_emissions import delay_metrics, edge_data
from terrain_discovery import d8, path_from


class TerrainTest(unittest.TestCase):
    def test_diagonal_nodata_marks_d8_contribution_incomplete(self):
        z=np.full((7,7),10.)
        z[2,2]=np.nan
        z[3,3]=1.
        _,_,edge,_=d8(z)
        self.assertTrue(edge[3,3], 'D8 includes diagonal neighbors, so diagonal NoData is an incomplete boundary')
    def test_downhill_diagonal_routes_conserve_area_and_stop_at_flats(self):
        z = np.array([[4,3,2],[3,2,1],[2,1,0]], dtype=float)
        target, area, edge, _ = d8(z, 2)
        self.assertEqual(target[1,1], 8)
        self.assertEqual(path_from(0, target), [0,4,8])
        self.assertEqual(area[2,2], 36)
        self.assertTrue(edge[2,2])
        self.assertEqual(area[target < 0].sum(), z.size * 4)
        flat_target, flat_area, _, _ = d8(np.ones((4,4)))
        self.assertTrue((flat_target == -1).all())
        self.assertTrue((flat_area == 1).all(), 'flats must not acquire fabricated gradients')

    def test_nodata_and_pits_are_not_bridged_or_filled(self):
        z = np.array([[4,4,4],[4,0,4],[4,4,np.nan]])
        target, area, edge, _ = d8(z)
        self.assertEqual(target[1,1], -1)
        self.assertEqual(area[1,1], 8)
        self.assertEqual(area[2,2], 0)
        self.assertTrue(edge[1,1])
        self.assertFalse((target == 8).any())
        with self.assertRaises(ValueError):d8(z, 0)
        self.assertEqual(builder.longest_inside_path([0,1,2,3,4,5], lambda i:i != 2), [3,4,5])


class TrafficTest(unittest.TestCase):
    def test_reported_counts_keep_dates_units_and_directions_without_scaling(self):
        row = {'type':'AUTO','dir':'AT','primary_street':'1 st ST','cross_street':'ALAMEDA ST',
               'total':'18102','count_date':'2014-01-16T00:00:00','w_b':'6433','e_b':'11669'}
        records = [row, {**row,'count_date':'2013-01-16'}, {**row,'type':'MAN','total':'99999'},
                   {**row,'dir':'E/O'}, {**row,'type':'MIO'}, {**row,'total':'nan'}]
        points = {('1 ST','ALAMEDA ST'):[(10,20,-118.238,34.049,'node')]}
        features, skipped = builder.count_records(records, points)
        self.assertEqual(len(features), 1)
        p = features[0]['properties']
        self.assertEqual(p['value'], 18102)
        self.assertEqual(p['period'], '2014-01-16')
        self.assertEqual(p['scalar_detail']['directional_reported_counts'], {'w_b':6433,'e_b':11669})
        self.assertEqual(p['source_record'], row)
        self.assertEqual(skipped['manual_or_unverified_type'], 2)
        self.assertEqual(skipped['offset_location'], 1)
        self.assertEqual(skipped['invalid_count'], 1)
        points[('1 ST','ALAMEDA ST')].append((200,20,-118.24,34.049,'other'))
        self.assertEqual(builder.count_records([row], points)[0], [])
        self.assertEqual(builder.street_key('East 1st Street'), '1 ST')

    def test_delay_export_has_vehicle_time_denominator_and_missing_samples(self):
        result = delay_metrics({'sampledSeconds':1000,'waitingTime':250,'timeLoss':400,
                                'entered':50,'left':45,'flow':54}, 600, 3600)
        self.assertEqual(result['stopped_time_percent'], 25)
        self.assertEqual(result['time_loss_percent'], 40)
        self.assertEqual(result['sampled_vehicle_seconds'], 1000)
        self.assertEqual(result['simulated_entered'], 50)
        self.assertEqual(result['interval_seconds'], 3000)
        self.assertIsNone(delay_metrics({}, 0, 10)['stopped_time_percent'])
        self.assertIsNone(delay_metrics({'sampledSeconds':0,'waitingTime':0}, 0, 10)['stopped_time_percent'])
        self.assertIsNone(delay_metrics({'sampledSeconds':1,'waitingTime':10}, 0, 10)['stopped_time_percent'])
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'traffic.xml'
            path.write_text('<meandata><interval/><interval/></meandata>')
            with self.assertRaises(ValueError):edge_data(path)


def snapshot():
    return {'schema':1,'workflow':'street','version':'real-source-hash',
            'sources':{'ladot':{'label':'LADOT','url':builder.LADOT_PAGE,'retrieved_at':'2026-11-14'}},
            'layers':[{'id':'counts','status':'ready','source':'ladot','classification':'reported',
                       'unit':'vehicles reported','period':'2011–2016','method':'No scaling',
                       'limitations':'Historical only','features':[{'id':'count-one','geometry':{'coordinates':[-118.25,34.05]},
                       'properties':{'label':'PRIVATE SITE NAME','center':[-118.25,34.05], 'value':18102,
                                     'period':'2014-01-16','source_record':{'address':'PRIVATE ADDRESS'},
                                     'scalar_detail':{'count_type':'AUTO'}}}]}]}


class DiscoveryTest(unittest.TestCase):
    def test_cached_snapshot_changes_require_a_new_content_version(self):
        from hashlib import sha256
        data=snapshot();data.pop('version')
        data['version']=sha256(json.dumps(data,sort_keys=True).encode()).hexdigest()[:16]
        with tempfile.TemporaryDirectory() as folder, patch('discovery.DATA',Path(folder)):
            path=Path(folder)/'street.json';path.write_text(json.dumps(data))
            self.assertEqual(discovery.load_discovery('street')['version'],data['version'])
            data['layers'][0]['features'][0]['properties']['value']=999999
            path.write_text(json.dumps(data))
            with self.assertRaisesRegex(ValueError,'content changed'):discovery.load_discovery('street')
            path.write_text('[]')
            with self.assertRaises(ValueError):discovery.load_discovery('street')

    def test_reference_is_resolved_locally_and_rejects_stale_or_different_sites(self):
        data=snapshot(); reference={'version':data['version'],'layer':'counts','feature':'count-one'}
        with patch('discovery.load_discovery',return_value=data):
            result=discovery.discovery_context('street',reference,-118.25,34.05)
            self.assertEqual(result['source']['observed_at'],'2014-01-16')
            for forbidden in ('PRIVATE','coordinates','center','-118.25','source_record'):
                self.assertNotIn(forbidden,json.dumps(result))
            for ref in ({**reference,'version':'old'},{**reference,'feature':'invented'},
                        {**reference,'value':999}, 'untrusted'):
                with self.assertRaises(ValueError):discovery.discovery_context('street',ref,-118.25,34.05)
            with self.assertRaises(ValueError):discovery.discovery_context('street',reference,-118.26,34.05)
            data['layers'][0]['status']='unavailable'
            with self.assertRaises(ValueError):discovery.discovery_context('street',reference)

    def test_turning_context_rejects_changed_pdf_and_parsed_data(self):
        from hashlib import sha256
        data = snapshot(); layer = data['layers'][0]; feature = layer['features'][0]
        layer['id'] = 'turning'; p = feature['properties']
        blob = b'%PDF test source'
        sheet = {'filename':'MAIN.1ST.111108-MAN.pdf','sha256':sha256(blob).hexdigest(),
                 'url':'https://navigatela.lacity.org/test.pdf','date':'2014-01-16','approaches':{'nb':123}}
        p.update(sheet_url=sheet['url'],sheet_sha256=sheet['sha256'],network_node='node')
        ref = {'version':data['version'],'layer':'turning','feature':feature['id']}
        with tempfile.TemporaryDirectory() as folder, patch('discovery.DATA',Path(folder)), \
             patch('discovery.load_discovery',return_value=data), patch('traffic_counts.load_sheet',return_value=sheet):
            network=Path(folder)/'network.xml'; network.write_bytes(b'<net/>')
            data['sources']['osm']={'input_sha256':sha256(network.read_bytes()).hexdigest()}
            network_patch=patch('discovery.NETWORK',network);network_patch.start();self.addCleanup(network_patch.stop)
            cache = Path(folder)/'sheets'; cache.mkdir(); pdf=cache/sheet['filename']; pdf.write_bytes(blob)
            parsed = Path(folder)/'turning-sheets.json'; parsed.write_text(json.dumps({feature['id']:sheet}))
            result = discovery.traffic_context(ref,-118.25,34.05)
            self.assertEqual(result['sheet'],sheet)
            self.assertEqual(result['node_id'],'node')
            nearby=discovery.traffic_context(ref,-118.24999,34.05001)
            self.assertEqual((nearby['lon'],nearby['lat']),(-118.25,34.05), 'Use the canonical matched node center for deterministic network cuts')
            network.write_bytes(b'<net changed="true"/>')
            with self.assertRaisesRegex(ValueError,'Road network changed'):discovery.traffic_context(ref,-118.25,34.05)
            network.write_bytes(b'<net/>')
            pdf.write_bytes(b'%PDF changed')
            with self.assertRaises(ValueError):discovery.traffic_context(ref,-118.25,34.05)
            pdf.write_bytes(blob)
            parsed.write_text(json.dumps({feature['id']:{**sheet,'approaches':{'nb':999}}}))
            with self.assertRaises(ValueError):discovery.traffic_context(ref,-118.25,34.05)

    def test_missing_snapshot_never_uses_fixture_and_partial_sources_survive(self):
        with tempfile.TemporaryDirectory() as folder, patch('discovery.DATA',Path(folder)):
            with self.assertRaises(FileNotFoundError):discovery.load_discovery('water')
            with self.assertRaises(ValueError):discovery.load_discovery('../private')
        with tempfile.TemporaryDirectory() as folder, patch.object(builder,'DATA',Path(folder)):
            def cached(directory,name,fetch,refresh):
                if name=='western-catchments.json':raise OSError('County unavailable')
                return [], {'retrieved_at':'2026-11-15','input_sha256':'test'}
            with patch('water_discovery.cached',side_effect=cached), \
                 patch('water_discovery.download_mosaic',side_effect=OSError('DEM unavailable')), \
                 patch('server.property_catalog',side_effect=OSError('Kit unavailable')), \
                 patch('hydrology.rainfall_at',return_value={'inches':1.01,'method':'test interpolation','depth_range':[1,1.1]}):
                data=builder.build_water()
            layers={layer['id']:layer for layer in data['layers']}
            self.assertEqual(layers['terrain']['status'],'unavailable')
            self.assertEqual(layers['terrain']['features'],[])
            self.assertEqual(layers['catchments']['status'],'unavailable')
            self.assertEqual(layers['rainfall']['status'],'ready')
            self.assertGreater(len(layers['rainfall']['features']),64)



class LocalSourceSpotCheck(unittest.TestCase):
    @unittest.skipUnless((builder.DATA/'street.json').exists(),'Local source snapshot not built')
    def test_traffic_feature_matches_downloaded_source_record(self):
        data=discovery.load_discovery('street')
        records=json.loads((builder.DATA/'ladot-records.json').read_text())
        feature=data['layers'][0]['features'][0]
        p=feature['properties']; row=p['source_record']
        self.assertIn(row,records)
        self.assertEqual(p['value'],int(row['total']))
        self.assertEqual(p['period'],row['count_date'][:10])
        self.assertIn(row['type'],('AUTO','AUT'))
        self.assertEqual(row['dir'],'AT')

    @unittest.skipUnless((builder.DATA/'western-dem.tif').exists(),'Western DEM not downloaded')
    def test_exported_flow_follows_real_dem_cells_and_accumulation(self):
        import rasterio
        from pyproj import Transformer
        data=discovery.load_discovery('water')
        feature=next(f for f in data['layers'][0]['features'] if f['properties']['kind']=='flow')
        with rasterio.open(builder.DATA/'western-dem.tif') as src:
            z=src.read(1).astype(float)
            inverse=~src.transform
        project=Transformer.from_crs(4326,26911,always_xy=True)
        cells=[]
        for coordinate in feature['geometry']['coordinates']:
            c,r=inverse @ project.transform(*coordinate)
            cells.append((int(r),int(c)))
        target,area,_,_=d8(z)
        for (r,c),(rr,cc) in zip(cells,cells[1:]):
            self.assertEqual(target[r,c],rr*z.shape[1]+cc)
            self.assertLess(z[rr,cc],z[r,c])
        self.assertEqual(feature['properties']['value'],area[cells[-1]])
        self.assertAlmostEqual(feature['properties']['scalar_detail']['drop_m'],z[cells[0]]-z[cells[-1]],places=3)


if __name__=='__main__':unittest.main()
