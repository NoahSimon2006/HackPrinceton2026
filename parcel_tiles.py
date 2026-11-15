"""On-demand reference outlines, cached by fixed map cell rather than by site.

Only existing Vexcel property/extract data is requested. This never generates
properties, runs site analysis, or treats browsing geometry as analyzed evidence.
"""
import hashlib
import json
import math
import time
from collections import OrderedDict
from pathlib import Path
from threading import BoundedSemaphore, Lock

from shapely.errors import ShapelyError
from shapely.geometry import box, mapping, shape

from site_evidence import parcel_features

TILE_ZOOM = 17
TTL = 7 * 24 * 3600
PARTIAL_TTL = 300
PAGE_SIZE = 250


def tile_bounds(z, x, y):
    n = 2 ** z
    latitude = lambda row: math.degrees(math.atan(math.sinh(math.pi * (1 - 2 * row / n))))
    return x / n * 360 - 180, latitude(y + 1), (x + 1) / n * 360 - 180, latitude(y)


def validate_tile(z, x, y, bounds):
    if z != TILE_ZOOM or not (0 <= x < 2 ** z and 0 <= y < 2 ** z):
        raise ValueError("Invalid parcel tile coordinates.")
    west, south, east, north = tile_bounds(z, x, y)
    if east <= bounds[0] or west >= bounds[2] or north <= bounds[1] or south >= bounds[3]:
        raise ValueError("Parcel tile is outside the Los Angeles map.")
    return max(west, bounds[0]), max(south, bounds[1]), min(east, bounds[2]), min(north, bounds[3])


def fetch_outlines(request, layers, bounds, depth=0):
    west, south, east, north = bounds
    lon, lat = (west + east) / 2, (south + north) / 2
    # The provider already supports point + buffer searches. Circumscribe the
    # cell so its corners are covered, then filter whole features to the cell.
    radius = math.ceil(1.01 * 111_320 * math.hypot((east - west) / 2 * math.cos(math.radians(lat)), (north - south) / 2))
    try:
        payload = json.loads(request("/property/extract", {
            "wkt": f"POINT({lon} {lat})", "srid": 4326, "layer": layers,
            "latest": "true", "include": "footprint-wkt,capture-date,collection,gsd",
            "buffer-meter": radius, "page-size": PAGE_SIZE,
        }, "application/json", 5_000_000, timeout=25))
    except ValueError as error:
        if str(error) != "No Vexcel property outlines are available at this point.":
            raise
        payload = {"features": []}
    if not isinstance(payload, dict) or not isinstance(payload.get("features"), list):
        raise ValueError("Vexcel returned no valid parcel collection.")
    capped = len(payload["features"]) >= PAGE_SIZE
    if capped and depth < 2:
        # Dense blocks can hit the provider cap. Subdivide instead of silently
        # treating a truncated page as complete. Bound recursion to 21 calls.
        parts = [fetch_outlines(request, layers, cell, depth + 1) for cell in (
            (west, south, lon, lat), (lon, south, east, lat),
            (west, lat, lon, north), (lon, lat, east, north))]
        return [f for features, _ in parts for f in features], any(partial for _, partial in parts)
    partial = capped
    evidence = {"outlines": []}
    # Keep the newest copy of each boundary, without discarding neighboring
    # parcels from older collections. Malformed source features leave disclosed
    # gaps; they must not hide all valid outlines in the same map cell.
    parcels = []
    for item in payload["features"]:
        try:
            boundary = shape(item["geometry"])
            if boundary.is_empty or not boundary.is_valid or not isinstance(item.get("properties"), dict):
                raise ValueError("Invalid parcel boundary geometry.")
            # Ring direction/start vertices can differ across capture years.
            item["geometry"] = json.loads(json.dumps(mapping(boundary.normalize())))
            parcels.append(item)
        except (ShapelyError, ValueError, KeyError, TypeError, AttributeError):
            partial = True
    parcels.sort(key=lambda item: str(item["properties"].get("metadata.ortho-date-estimate") or ""), reverse=True)
    seen = set()
    for item in parcels:
        signature = json.dumps(item["geometry"], sort_keys=True)
        if signature in seen:
            continue
        seen.add(signature)
        try:
            parcel_features({"features": [item]}, evidence, nearby=True)
        except (ValueError, KeyError, TypeError, AttributeError):
            partial = True

    cell = box(*bounds)
    features = []
    for feature in evidence["outlines"]:
        try:
            geometry = shape(feature["geometry"])
        except (ShapelyError, ValueError, KeyError, TypeError, AttributeError):
            partial = True
            continue
        if geometry.is_empty or not geometry.is_valid:
            partial = True
            continue
        if not geometry.intersects(cell):
            continue
        identity = feature["properties"]["label"].encode() + geometry.normalize().wkb
        feature["id"] = hashlib.sha256(identity).hexdigest()[:24]
        features.append(feature)
    return features, partial


class ParcelTiles:
    def __init__(self, directory, bounds, layers):
        # Separate caches when the source layer configuration changes.
        self.directory = Path(directory) / hashlib.sha256(layers.encode()).hexdigest()[:12]
        self.bounds, self.layers = bounds, layers
        self.memory = OrderedDict()
        self.lock = Lock()
        self.tile_locks = [Lock() for _ in range(32)]
        self.slots = BoundedSemaphore(2)

    def get(self, z, x, y, request):
        bounds = validate_tile(z, x, y, self.bounds)
        key = f"{z}-{x}-{y}"
        path = self.directory / f"{key}.json"
        with self.tile_locks[hash(key) % len(self.tile_locks)]:
            with self.lock:
                cached = self.memory.get(key)
            if cached is None:
                try:
                    cached = json.loads(path.read_text())
                except (OSError, ValueError):
                    pass
            valid_cache = (isinstance(cached, dict) and isinstance(cached.get("expires"), (float, int))
                           and cached["expires"] > time.time() and isinstance(cached.get("data"), dict)
                           and cached["data"].get("type") == "FeatureCollection"
                           and isinstance(cached["data"].get("features"), list))
            if not valid_cache:
                with self.slots:
                    features, partial = fetch_outlines(request, self.layers, bounds)
                unique = {}
                for feature in sorted(features, key=lambda f: f["properties"].get("date") or ""):
                    unique[feature["id"]] = feature
                data = {"type": "FeatureCollection", "features": list(unique.values()),
                        "status": "partial" if partial else "ready", "source": "Vexcel",
                        "fetchedAt": time.time()}
                cached = {"expires": time.time() + (PARTIAL_TTL if partial else TTL), "data": data}
                # Cache failures must not prevent displaying a successful fetch.
                try:
                    self.directory.mkdir(parents=True, exist_ok=True)
                    temporary = path.with_suffix(".tmp")
                    temporary.write_text(json.dumps(cached, separators=(",", ":")))
                    temporary.replace(path)
                except OSError:
                    pass
            with self.lock:
                self.memory[key] = cached
                self.memory.move_to_end(key)
                while len(self.memory) > 256:
                    self.memory.popitem(last=False)
            return cached["data"]
