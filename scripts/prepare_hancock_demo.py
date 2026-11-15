"""Prepare private Hancock demo evidence; no model or simulation calls.

Run: .venv/bin/python scripts/prepare_hancock_demo.py [--refresh]
Valid snapshots are reused without network requests. --refresh replaces them
only after a bounded Vexcel response and the local CoStar association validate.
Sponsor data is written only under ignored private/demo-hancock/.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
import math
import os
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from pyproj import Transformer
from shapely.geometry import Point, mapping, shape
from shapely.ops import transform

import server
from site_evidence import parcel_features, recent_parcel_collections
from site_view import site_view_descriptor

DATA = ROOT / "private" / "demo-hancock"
PROPERTY_ID = "4497305"
MODEL_ID = "SU76BQEbevu"
LON, LAT = -118.3100104, 34.0641972
FILES = ("context-local.geojson", "costar-design-context.json", "fetch-metadata.json")


def validate_snapshot(scene, context, metadata):
    origin = scene["origin"]
    expected = Transformer.from_crs(4326, 32611, always_xy=True).transform(LON, LAT)
    if (scene.get("type") != "FeatureCollection" or origin["crs"] != "EPSG:32611"
            or (origin["lon"], origin["lat"]) != (LON, LAT)
            or not all(math.isclose(origin[key], value, abs_tol=.001, rel_tol=0)
                       for key, value in zip(("easting", "northing"), expected))):
        raise ValueError("The cached geometry has the wrong site or coordinate origin.")
    if (context["propertyId"] != PROPERTY_ID or context["tour"]["modelId"] != MODEL_ID
            or context["coordinates"] != [LON, LAT]):
        raise ValueError("The cached CoStar evidence has the wrong property or exterior tour.")
    fields = context["sourceFields"]
    if fields.get("numStoriesAboveGrade") != 3 or fields.get("totalNumUnits") != 28:
        raise ValueError("The CoStar unit/story counts differ from this curated demo; review the scene.")
    datetime.fromisoformat(metadata["retrievedAt"])
    features = scene["features"]
    if not isinstance(features, list) or not 1 <= len(features) < 500:
        raise ValueError("The snapshot has no usable bounded source features.")
    containing = set()
    for feature in features:
        geom = shape(feature["geometry"])
        label = feature["properties"]["label"]
        if (geom.geom_type not in ("Polygon", "MultiPolygon") or geom.is_empty
                or not geom.is_valid or not all(math.isfinite(v) for v in geom.bounds)
                or max(abs(v) for v in geom.bounds) > 500):
            raise ValueError("A source outline is malformed or outside the bounded scene.")
        if label in ("Parcel boundary", "Building footprint") and geom.covers(Point(0, 0)):
            containing.add(label)
    if containing != {"Parcel boundary", "Building footprint"}:
        raise ValueError("The source snapshot does not locate the selected building and parcel.")


def costar_context():
    directory = os.getenv("COSTAR_KIT_DIR", "").strip()
    if not directory:
        raise ValueError("Set COSTAR_KIT_DIR in the local .env to the supplied CoStar kit.")
    root = Path(directory).expanduser()
    if not (root / "data/commercial-property.jsonl").is_file():
        raise ValueError("COSTAR_KIT_DIR is missing data/commercial-property.jsonl.")
    catalog = server.property_catalog()[0]
    descriptor = site_view_descriptor(root, catalog, PROPERTY_ID)
    tours = [item for item in descriptor["scans"]
             if item["modelId"] == MODEL_ID and item["exteriorHint"]]
    if len(tours) != 1:
        raise ValueError("The expected Hancock exterior tour association could not be confirmed.")
    records = []
    with (root / "data/commercial-property.jsonl").open(encoding="utf-8") as file:
        for line in file:
            record = json.loads(line)
            if str(record.get("id")) == PROPERTY_ID:
                records.append(record)
    if len(records) != 1:
        raise ValueError("The Hancock CoStar property is missing or duplicated.")
    record = records[0]
    address = record["primaryAddress"]
    if (address["longitude"], address["latitude"]) != (LON, LAT):
        raise ValueError("The CoStar location changed; review the demo before preparing it.")
    fields = {key: record.get(key) for key in (
        "numStoriesAboveGrade", "grossBuildingAreaSquareFeet", "lotSize",
        "lotSizeMeasurementType", "zoningDescription")}
    fields["parking"] = [{key: item[key] for key in ("parkingType", "totalSpaces") if key in item}
                         for item in (record.get("parking") or [])]
    fields["totalNumUnits"] = (record.get("propertyApartment") or {}).get("totalNumUnits")
    tour = tours[0]
    return {
        "propertyId": PROPERTY_ID, "name": descriptor["property"]["name"],
        "address": descriptor["property"]["address"] + ", Los Angeles, CA",
        "coordinates": [LON, LAT], "source": "Local CoStar commercial-property.jsonl",
        "sourceFields": fields,
        "tour": {"modelId": MODEL_ID, "title": tour["title"], "attachmentDate": tour["attachmentDate"]},
        "designImplications": [
            "Multifamily use informs preserving resident entry, accessible circulation and service access.",
            "Parking counts may be unknown; the design does not claim verified spaces retained or removed.",
            "Reported stories inform massing; floor-to-floor heights remain assumed.",
            "Property records and parcel outlines do not establish land control or public-frontage permissions.",
        ],
        "unverified": ["Existing drainage connections", "Infiltration rate", "Utilities",
                       "Drainage slope and low points", "Construction permission", "Surveyed clearances"],
    }


def prepare(refresh=False):
    if not refresh and all((DATA / name).is_file() for name in FILES):
        snapshot = [json.loads((DATA / name).read_text()) for name in FILES]
        try:
            validate_snapshot(*snapshot)
        except (KeyError, TypeError, ValueError) as error:
            raise ValueError("Cached demo evidence failed validation; inspect it, then use --refresh.") from error
        return snapshot[0], True
    context = costar_context()
    if not os.getenv("VEXCEL_API_KEY", "").strip():
        raise ValueError("Set VEXCEL_API_KEY in the local .env to prepare missing Vexcel evidence.")
    params = {"wkt": f"POINT({LON} {LAT})", "srid": 4326, "layer": server.LAYERS,
              "latest": "true", "include": "footprint-wkt,capture-date,collection,gsd",
              "buffer-meter": 90, "page-size": 250}
    raw = json.loads(server.vexcel_request("/property/extract", params, "application/json",
                                         5_000_000, timeout=25))
    if not isinstance(raw.get("features"), list) or len(raw["features"]) >= 250:
        raise ValueError("The bounded Vexcel parcel response is invalid or incomplete.")
    evidence = {"outlines": []}
    parcel_features(recent_parcel_collections(raw), evidence, nearby=True)
    projection = Transformer.from_crs(4326, 32611, always_xy=True)
    x0, y0 = projection.transform(LON, LAT)

    def local(x, y, z=None):
        x, y = projection.transform(x, y)
        return x - x0, y - y0

    features = []
    for index, feature in enumerate(evidence["outlines"]):
        geom = transform(local, shape(feature["geometry"]))
        features.append({"type": "Feature", "id": index, "geometry": mapping(geom),
                         "properties": {**feature["properties"], "areaM2": round(geom.area, 3)}})
    origin = {"lon": LON, "lat": LAT, "easting": x0, "northing": y0, "crs": "EPSG:32611"}
    scene = {"type": "FeatureCollection", "origin": origin, "features": features}
    metadata = {"retrievedAt": datetime.now(timezone.utc).isoformat(), "params": params,
                "endpoint": "/property/extract", "files": list(FILES), "origin": origin,
                "note": "One bounded Vexcel request; CoStar attachment dates are not capture dates."}
    validate_snapshot(scene, context, metadata)
    DATA.mkdir(parents=True, exist_ok=True)
    for name, value in zip(FILES, (scene, context, metadata)):
        temporary = DATA / (name + ".tmp")
        temporary.write_text(json.dumps(value, indent=2, allow_nan=False))
        temporary.replace(DATA / name)
    return scene, False


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--refresh", action="store_true", help="Refetch bounded Vexcel evidence and recheck CoStar.")
    args = parser.parse_args()
    try:
        scene, cached = prepare(args.refresh)
    except Exception as error:
        # Provider errors are already sanitized; avoid dumping source records,
        # request headers, credentials or tracebacks from malformed local data.
        message = str(error) if isinstance(error, ValueError) else "Check local CoStar files and Vexcel connectivity."
        print(f"Hancock demo preparation failed: {message}", file=sys.stderr)
        return 1
    dates = sorted({f["properties"].get("date") for f in scene["features"] if f["properties"].get("date")})
    print(f"{'Reused' if cached else 'Prepared'} {len(scene['features'])} source outlines; capture dates: {', '.join(dates) or 'not supplied'}.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
