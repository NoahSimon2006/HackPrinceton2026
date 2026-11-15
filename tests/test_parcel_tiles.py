import json
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import Mock, patch

from shapely.geometry import box, mapping
from parcel_tiles import ParcelTiles, fetch_outlines, tile_bounds, validate_tile, TTL

LA = (-118.67, 33.70, -118.10, 34.35)
TILE = (17, 22484, 52336)
BOUNDS = tile_bounds(*TILE)


def parcel(bounds=BOUNDS, date='2026-07-01', collection='new'):
    west, south, east, north = bounds
    footprint = mapping(box(west + .0001, south + .0001, east - .0001, north - .0001))
    return {'geometry': mapping(box(*bounds)), 'properties': {
        'metadata.ortho-date-estimate': date, 'metadata.collection': collection,
        'structures': [{'footprint.wkt': footprint}]}}


class ParcelTilesTest(unittest.TestCase):
    def test_corners_are_covered_whole_shapes_are_kept_and_neighboring_cells_share_ids(self):
        request = Mock(return_value=json.dumps({'features': [parcel(), parcel((-120, 32, -119, 33))]}))
        features, partial = fetch_outlines(request, 'urban', BOUNDS)
        self.assertFalse(partial)
        self.assertEqual(len(features), 2)
        params = request.call_args.args[1]
        self.assertGreater(params['buffer-meter'], 175)
        self.assertLess(params['buffer-meter'], 200)
        self.assertEqual(params['page-size'], 250)
        self.assertEqual(features[0]['geometry'], json.loads(json.dumps(mapping(box(*BOUNDS).normalize()))))
        neighbor, _ = fetch_outlines(request, 'urban', tile_bounds(17, TILE[1] + 1, TILE[2]))
        self.assertEqual(features[0]['id'], neighbor[0]['id'])

    def test_newest_duplicate_does_not_remove_adjacent_older_collection(self):
        west, south, east, north = BOUNDS
        first = (west, south, (west + east) / 2, north)
        second = ((west + east) / 2, south, east, north)
        request = Mock(return_value=json.dumps({'features': [parcel(first, '2024-01-01', 'old'),
            parcel(first), parcel(second, '2025-01-01', 'other')]}))
        features, _ = fetch_outlines(request, 'urban', BOUNDS)
        parcels = [f for f in features if f['properties']['label'] == 'Parcel boundary']
        self.assertEqual([p['properties']['date'] for p in parcels], ['2026-07-01', '2025-01-01'])

    def test_reversed_boundary_does_not_restore_historical_buildings(self):
        old, new = parcel(date='2024-01-01'), parcel()
        old['geometry'] = mapping(box(*BOUNDS).reverse())
        old['properties']['structures'] = [{'footprint.wkt': mapping(box(*BOUNDS))}]
        request = Mock(return_value=json.dumps({'features': [old, new]}))
        features, _ = fetch_outlines(request, 'urban', BOUNDS)
        self.assertEqual(len(features), 2)
        self.assertTrue(all(f['properties']['date'] == '2026-07-01' for f in features))

    def test_invalid_geometry_does_not_hide_valid_neighbors(self):
        bad = parcel()
        bad['geometry'] = {'type': 'Polygon', 'coordinates': [[[0,0],[1,1],[0,1],[1,0],[0,0]]]}
        request = Mock(return_value=json.dumps({'features': [parcel(), bad]}))
        features, partial = fetch_outlines(request, 'urban', BOUNDS)
        self.assertEqual(len(features), 2)
        self.assertTrue(partial)

    def test_dense_response_subdivides_and_discloses_remaining_cap(self):
        request = Mock(return_value=json.dumps({'features': [parcel()] * 250}))
        _, partial = fetch_outlines(request, 'urban', BOUNDS)
        self.assertEqual(request.call_count, 21)
        self.assertTrue(partial)
        request.reset_mock()
        request.side_effect = [json.dumps({'features': [parcel()] * 250})] + [json.dumps({'features': [parcel()]})] * 4
        _, partial = fetch_outlines(request, 'urban', BOUNDS)
        self.assertEqual(request.call_count, 5)
        self.assertFalse(partial)

    def test_memory_disk_expiry_and_concurrent_requests(self):
        with tempfile.TemporaryDirectory() as folder:
            store = ParcelTiles(folder, LA, 'urban')
            request = Mock(return_value=json.dumps({'features': [parcel()]}))
            with ThreadPoolExecutor(max_workers=4) as pool:
                results = list(pool.map(lambda _: store.get(*TILE, request), range(4)))
            self.assertEqual(request.call_count, 1)
            self.assertTrue(all(data == results[0] for data in results))
            other = ParcelTiles(folder, LA, 'urban')
            self.assertEqual(other.get(*TILE, request), results[0])
            self.assertEqual(request.call_count, 1, 'restart reuses persisted cache')
            with patch('parcel_tiles.time.time', return_value=results[0]['fetchedAt'] + TTL + 1):
                other.get(*TILE, request)
            self.assertEqual(request.call_count, 2)

    def test_failures_are_not_cached_as_empty_coverage(self):
        with tempfile.TemporaryDirectory() as folder:
            store = ParcelTiles(folder, LA, 'urban')
            request = Mock(side_effect=ValueError('Vexcel rejected the key or imagery access.'))
            for _ in range(2):
                with self.assertRaises(ValueError): store.get(*TILE, request)
            self.assertEqual(request.call_count, 2)
            request.side_effect = ValueError('No Vexcel property outlines are available at this point.')
            self.assertEqual(store.get(*TILE, request)['features'], [])
            self.assertEqual(store.get(*TILE, request)['features'], [])
            self.assertEqual(request.call_count, 3)

    def test_bounds_rejected_before_provider_and_endpoint_serves_geojson(self):
        from server import Handler
        for coords in ((16, 22484, 52336), (17, -1, 2), (17, 0, 0), (17, 131072, 0)):
            with self.subTest(coords=coords), self.assertRaises(ValueError): validate_tile(*coords, LA)
        handler = Handler.__new__(Handler)
        handler.send_json = Mock()
        handler.path = '/api/parcels/17/0/0.json'
        with patch('server.PARCEL_TILES.get') as get:
            handler.do_GET()
            self.assertEqual(handler.send_json.call_args.args[0], 400)
            get.assert_not_called()
            handler.path = '/api/parcels/17/22484/52336.json'
            get.return_value = {'type': 'FeatureCollection', 'features': [], 'status': 'ready'}
            handler.do_GET()
            self.assertEqual(handler.send_json.call_args.args, (200, get.return_value))


if __name__ == '__main__': unittest.main()
