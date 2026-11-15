"""Local, source-bound bare-earth terrain screening; never a drainage model."""
from hashlib import sha256
import json
from pathlib import Path

DEM_URL = "https://prd-tnm.s3.amazonaws.com/StagedProducts/Elevation/1m/Projects/CA_LosAngeles_B23/TIFF/USGS_1M_11_x37y378_CA_LosAngeles_B23.tif"
DATA = Path(__file__).resolve().parent / "private/discovery"
LIMITS = [
    "Bare-earth DEM gradients do not measure roof slopes, curbs, pipes or inlet connections.",
    "Relief is the sampled elevation range, not a surveyed longitudinal grade or a verified overflow path.",
    "Small elevation differences may be within DEM error. Acquisition date is unverified; publication date is not acquisition date.",
]


def terrain_screen(geometry, path=None):
    """Sample a polygon and its valid gradient neighborhood from the cached 1 m DEM.

    Source sidecars and the raster digest must agree. No downloads, filling of
    missing pixels, invented flow paths or fallback slopes are performed.
    The optional path supports isolated local datasets/tests, never a URL.
    """
    result = dict(status="unavailable", min_elevation_m=None, max_elevation_m=None,
                  relief_m=None, median_slope_percent=None, max_slope_percent=None,
                  sampled_cells=0, source=None, limitations=LIMITS.copy())
    try:
        import numpy as np
        import rasterio
        from rasterio.features import geometry_mask
        from rasterio.windows import Window, from_bounds
        from pyproj import Transformer
        from shapely import transform
        from shapely.geometry import box, mapping, shape
        from site_measurements import projected

        directory = Path(path).parent if path is not None else DATA
        origin = json.loads((directory / "water.json").read_text())["sources"]["dem"]
        expanded = origin.get('raster_file') == 'western-dem.tif'
        path = Path(path) if path is not None else directory / ('western-dem.tif' if expanded else 'kipling-dem.tif')
        metadata_path = directory / ('western-terrain-source.json' if expanded else 'terrain-source.json')
        meta = json.loads(metadata_path.read_text())
        digest = sha256(path.read_bytes()).hexdigest()
        if expanded:
            from water_discovery import DEM_URLS, DEM_PAGE, WESTERN, BUFFER_M
            if (meta.get('urls') != DEM_URLS or origin.get('url') != DEM_PAGE
                    or origin.get('urls') != DEM_URLS or meta.get('pilot_bbox') != list(WESTERN)
                    or meta.get('buffer_m') != BUFFER_M or meta.get('input_sha256') != digest
                    or sha256(metadata_path.read_bytes()).hexdigest() != origin.get('metadata_sha256')):
                raise ValueError('Expanded source metadata mismatch')
        elif meta.get('url') != DEM_URL or origin.get('url') != DEM_URL:
            raise ValueError('Source metadata mismatch')
        if (meta.get("publication_date") != origin.get("published_at")
                or meta.get("publication_date") != "2025-08-11"
                or meta.get("crs") != "EPSG:26911" or meta.get("resolution_m") != [1., 1.]
                or origin.get("vertical_datum") != "NAVD88, meters"
                or origin.get("input_sha256") != digest):
            raise ValueError("Source metadata mismatch")
        projected(geometry, ("Polygon", "MultiPolygon"))
        local = transform(shape(geometry), Transformer.from_crs(4326, 26911, always_xy=True).transform, interleaved=False)
        with rasterio.open(path) as src:
            if (src.crs.to_epsg() != 26911 or src.res != (1., 1.) or src.count != 1
                    or src.transform.b != 0 or src.transform.d != 0
                    or not np.allclose(list(src.bounds), meta["bounds"], rtol=0, atol=1e-6)
                    or not box(*src.bounds).covers(local.buffer(2))):
                raise ValueError("Terrain grid or coverage mismatch")
            raw = from_bounds(*local.buffer(2).bounds, src.transform)
            left, top = int(np.floor(raw.col_off)), int(np.floor(raw.row_off))
            right, bottom = int(np.ceil(raw.col_off + raw.width)), int(np.ceil(raw.row_off + raw.height))
            window = Window(left, top, right-left, bottom-top)
            values = src.read(1, window=window, masked=True)
            transform_ = src.window_transform(window)
            touched = geometry_mask([mapping(local)], values.shape, transform_, invert=True, all_touched=True)
            selected = geometry_mask([mapping(local)], values.shape, transform_, invert=True, all_touched=False)
            valid = ~np.ma.getmaskarray(values) & np.isfinite(values.data)
            neighborhood = touched.copy()
            for dy, dx in ((-1,0),(1,0),(0,-1),(0,1)):
                neighborhood |= np.roll(touched, (dy,dx), axis=(0,1))
            if not selected.any() or not valid[neighborhood].all():
                raise ValueError("Terrain pixels incomplete")
            z = np.where(valid, values.data, np.nan).astype(float)
            dy, dx = np.gradient(z, 1., 1.)
            slopes = np.hypot(dx, dy)[selected] * 100
            heights = z[selected]
            if not np.isfinite(slopes).all():
                raise ValueError("Terrain gradient unavailable")
        result.update(status="ready", min_elevation_m=round(float(heights.min()), 3),
                      max_elevation_m=round(float(heights.max()), 3),
                      relief_m=round(float(heights.max()-heights.min()), 3),
                      median_slope_percent=round(float(np.median(slopes)), 2),
                      max_slope_percent=round(float(slopes.max()), 2), sampled_cells=int(selected.sum()),
                      source={"provider":"USGS 3DEP 1 m bare-earth DEM", "url":origin['url'],
                              "urls":origin.get('urls',[DEM_URL]),
                              "publication_date":meta["publication_date"], "observed_at":None,
                              "retrieved_at":origin.get("retrieved_at"), "resolution_m":1,
                              "vertical_datum":"NAVD88, meters", "input_sha256":digest},
                      method="Pixel-center elevations and central-difference gradients on the native 1 m bare-earth grid; complete polygon and neighboring pixel coverage required.")
    except (ImportError, OSError, ValueError, KeyError, TypeError, AttributeError, IndexError):
        result["reason"] = "Complete, source-validated local terrain coverage is unavailable for this footprint."
    return result
