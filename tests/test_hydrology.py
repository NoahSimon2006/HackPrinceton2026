import io
import unittest
from unittest.mock import patch

from hydrology import rainfall_at, county_features


def contour(depth, x):
    return {'type':'Feature','geometry':{'type':'LineString','coordinates':[[x,34.04],[x,34.06]]},'properties':{'CONTOUR':depth}}


class HydrologyTest(unittest.TestCase):
    def test_adjacent_opposite_contours_interpolate_without_extrapolation(self):
        features=[contour(1,-118.251),contour(1.1,-118.249)]
        self.assertEqual(rainfall_at(-118.25,34.05,features)['inches'],1.05)
        self.assertEqual(rainfall_at(-118.251,34.05,features)['method'],'on_contour')
        self.assertIsNone(rainfall_at(-118.26,34.05,features))
        self.assertIsNone(rainfall_at(-118.25,34.05,[contour(1,-118.251),contour(1.3,-118.249)]))

    def test_nonfinite_or_malformed_contours_fail_closed(self):
        for depth in (float('nan'),float('inf'),True,-1,101,None):
            with self.subTest(depth=depth), self.assertRaises(ValueError):
                rainfall_at(-118.25,34.05,[contour(depth,-118.25)])
        for line in ([],[[-118.25,34.05]],[[float('nan'),34.05],[-118.25,34.06]],[[True,34.05],[-118.25,34.06]]):
            bad=contour(1,-118.25);bad['geometry']['coordinates']=line
            with self.subTest(line=line), self.assertRaises(ValueError):rainfall_at(-118.25,34.05,[bad])

    def test_incomplete_county_collection_cannot_be_used(self):
        for body in (b'[]',b'{"type":"FeatureCollection"}',b'{"type":"FeatureCollection","features":[],"exceededTransferLimit":true}'):
            with patch('hydrology.urlopen',return_value=io.BytesIO(body)), self.assertRaises(ValueError):
                county_features('https://example.invalid','point','esriGeometryPoint','CONTOUR')


if __name__=='__main__':unittest.main()
