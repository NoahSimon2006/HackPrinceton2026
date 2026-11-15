"""Site screening data from LA County Public Works."""

import json
import math
from functools import lru_cache
from urllib.parse import urlencode
from urllib.request import urlopen

COUNTY_GIS = "https://dpw.gis.lacounty.gov/dpw/rest/services"
RAINFALL = f"{COUNTY_GIS}/hydrologygis/MapServer/3"
WATERSHEDS = f"{COUNTY_GIS}/PW_Open_Data/MapServer/36"


def county_features(layer, geometry, geometry_type, fields):
    query = urlencode({
        "f": "geojson", "geometry": geometry, "geometryType": geometry_type,
        "inSR": 4326, "outSR": 4326, "spatialRel": "esriSpatialRelIntersects",
        "outFields": fields, "returnGeometry": "true",
    })
    with urlopen(f"{layer}/query?{query}", timeout=12) as response:
        raw = response.read(5_000_001)
        if len(raw) > 5_000_000:
            raise ValueError("LA County hydrology response exceeded its size limit.")
        payload = json.loads(raw)
    if (not isinstance(payload, dict) or payload.get("type") != "FeatureCollection"
            or payload.get("exceededTransferLimit") or not isinstance(payload.get("features"), list)):
        raise ValueError("LA County returned incomplete hydrology data.")
    return payload["features"]


@lru_cache(maxsize=1)
def rainfall_contours(bounds):
    west, south, east, north = bounds
    envelope = f"{west - .1},{south - .1},{east + .1},{north + .1}"
    return county_features(RAINFALL, envelope, "esriGeometryEnvelope", "CONTOUR")


def closest_point(lon, lat, line):
    """Return the closest offset to a contour in a local metric plane."""
    if not isinstance(line, (list, tuple)) or len(line) < 2:
        raise ValueError("A rainfall contour needs at least two coordinate pairs.")
    for coordinate in line:
        if (not isinstance(coordinate, (list, tuple)) or len(coordinate) != 2
                or any(isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v) for v in coordinate)
                or not -180 <= coordinate[0] <= 180 or not -90 <= coordinate[1] <= 90):
            raise ValueError("Rainfall contour coordinates are invalid.")
    x_scale = 111_320 * math.cos(math.radians(lat))
    points = [((x - lon) * x_scale, (y - lat) * 111_320) for x, y in line]
    best = (math.inf, 0, 0)
    for (x, y), (end_x, end_y) in zip(points, points[1:]):
        dx, dy = end_x - x, end_y - y
        length_squared = dx * dx + dy * dy
        fraction = max(0, min(1, -(x * dx + y * dy) / length_squared)) if length_squared else 0
        offset_x, offset_y = x + fraction * dx, y + fraction * dy
        best = min(best, (math.hypot(offset_x, offset_y), offset_x, offset_y))
    return best


def rainfall_at(lon, lat, features):
    if (isinstance(lon, bool) or isinstance(lat, bool) or not isinstance(lon, (int, float))
            or not isinstance(lat, (int, float)) or not math.isfinite(lon) or not math.isfinite(lat)
            or not -180 <= lon <= 180 or not -90 <= lat <= 90 or not isinstance(features, list)):
        raise ValueError("Invalid rainfall lookup inputs.")
    nearest = {}
    for feature in features:
        if not isinstance(feature, dict) or not isinstance(feature.get("properties"), dict):
            raise ValueError("Rainfall source contains an invalid feature.")
        geometry = feature["geometry"]
        if not geometry or geometry["type"] not in ("LineString", "MultiLineString"):
            continue
        raw_depth = feature["properties"].get("CONTOUR")
        try:
            depth = float(raw_depth)
        except (TypeError, ValueError):
            raise ValueError("Rainfall contour depth is invalid.") from None
        if isinstance(raw_depth, bool) or not math.isfinite(depth) or not 0 <= depth <= 100:
            raise ValueError("Rainfall contour depth is invalid.")
        lines = [geometry["coordinates"]] if geometry["type"] == "LineString" else geometry["coordinates"]
        if not isinstance(lines, (list, tuple)) or not lines:
            raise ValueError("Rainfall contour geometry is empty.")
        for line in lines:
            point = closest_point(lon, lat, line)
            nearest[depth] = min(point, nearest.get(depth, point))

    if not nearest:
        return None
    depth = min(nearest, key=lambda value: nearest[value][0])
    distance, x, y = nearest[depth]
    if distance <= 1:
        return {"inches": depth, "method": "on_contour", "depth_range": [depth, depth]}

    # Only interpolate between adjacent depth levels with nearby contours on
    # opposite sides of the point. Else let the planner enter a sourced depth.
    candidates = []
    levels = sorted(nearest)
    for first, second in zip(levels, levels[1:]):
        if depth not in (first, second) or second - first > 0.101:
            continue
        other = second if depth == first else first
        other_distance, other_x, other_y = nearest[other]
        if other_distance <= 10_000 and x * other_x + y * other_y <= -.5 * distance * other_distance:
            candidates.append((other_distance, other))
    if not candidates:
        return None
    other_distance, other = min(candidates)
    estimate = depth + (other - depth) * distance / (distance + other_distance)
    return {"inches": round(estimate, 2), "method": "interpolated",
            "depth_range": sorted((depth, other))}


def watershed_at(lon, lat):
    return county_features(WATERSHEDS, f"{lon},{lat}", "esriGeometryPoint",
                           "NAME,WATERSHED")
