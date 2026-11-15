import json
from hashlib import sha256
from pathlib import Path
import tempfile
import unittest

from pyproj import Transformer
from shapely import transform
from shapely.geometry import box, mapping

from stormwater_terrain import DEM_URL, terrain_screen, DATA

try:
    import numpy as np
    import rasterio
    from rasterio.transform import from_origin
except ImportError:
    rasterio = None


@unittest.skipIf(rasterio is None, "Install requirements-discovery.txt for terrain tests")
class TerrainScreenTest(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        self.path = self.root / "kipling-dem.tif"
        self.grid = from_origin(379700, 3770700, 1, 1)
        self.values = np.tile(np.arange(20, dtype=np.float32) * .1, (20,1)) + 70
        self.geo = lambda x1,y1,x2,y2: mapping(transform(box(x1,y1,x2,y2), Transformer.from_crs(26911,4326,always_xy=True).transform, interleaved=False))
        self.polygon = self.geo(379705,3770685,379715,3770695)
        self.write()

    def write(self):
        with rasterio.open(self.path, "w", driver="GTiff", height=20,width=20,count=1,
                           dtype="float32",crs="EPSG:26911",transform=self.grid,nodata=-9999) as src:
            src.write(self.values,1)
        (self.root/"terrain-source.json").write_text(json.dumps(dict(url=DEM_URL,crs="EPSG:26911",
            resolution_m=[1,1],bounds=[379700,3770680,379720,3770700],publication_date="2025-08-11")))
        (self.root/"water.json").write_text(json.dumps({"sources":{"dem":dict(url=DEM_URL,
            published_at="2025-08-11",vertical_datum="NAVD88, meters",input_sha256=sha256(self.path.read_bytes()).hexdigest())}}))

    def test_native_gradient_and_relief_are_separate_from_drainage(self):
        result = terrain_screen(self.polygon,self.path)
        self.assertEqual(result["status"],"ready")
        self.assertAlmostEqual(result["median_slope_percent"],10,places=2)
        self.assertAlmostEqual(result["max_slope_percent"],10,places=2)
        self.assertEqual(result["sampled_cells"],100)
        self.assertAlmostEqual(result["relief_m"],.9,places=2)
        self.assertNotIn("flow_path",result)

    def test_missing_pixels_metadata_and_boundaries_fail_closed(self):
        outside = self.geo(379699,3770685,379705,3770695)
        self.assertEqual(terrain_screen(outside,self.path)["status"],"unavailable")
        self.values[10,10]=-9999
        self.write()
        result=terrain_screen(self.polygon,self.path)
        self.assertEqual(result["status"],"unavailable")
        self.assertIsNone(result["median_slope_percent"])
        self.values[10,10]=71
        self.write()
        metadata=json.loads((self.root/"water.json").read_text())
        metadata["sources"]["dem"]["input_sha256"]="0"*64
        (self.root/"water.json").write_text(json.dumps(metadata))
        self.assertEqual(terrain_screen(self.polygon,self.path)["status"],"unavailable")
        (self.root/"water.json").write_text("{}")
        self.assertEqual(terrain_screen(self.polygon,self.path)["status"],"unavailable")
        self.assertEqual(terrain_screen({"type":"Point","coordinates":[-118.3,34.07]},self.path)["status"],"unavailable")

    def test_real_cached_source_when_available(self):
        if not (DATA/"kipling-dem.tif").exists():
            self.skipTest("Real cached USGS data unavailable")
        result = terrain_screen(self.polygon)
        self.assertEqual(result["status"],"ready")
        self.assertIn(DEM_URL,result["source"]["urls"])
        self.assertGreaterEqual(result["max_slope_percent"],0)
        self.assertLess(result["max_elevation_m"],100)


if __name__ == "__main__":
    unittest.main()
