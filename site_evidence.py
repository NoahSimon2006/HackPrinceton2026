"""Collect geographically bounded imagery evidence for a selected site."""

import json
import math
import re
from datetime import datetime

SEARCH_TEXT = {
    "street": "marked pedestrian crosswalks and driveway entrances connecting to a street",
    "water": "driveway entrances, paved parking lots, and landscaped strips next to pavement",
}
DETECTION_LABELS = {
    "street": ("zebra crosswalk", "driveway entrance"),
    "water": ("driveway entrance", "parking lot", "landscaped strip"),
}


def polygon_geometry(value):
    if isinstance(value, dict):
        return value if value.get("type") in ("Polygon", "MultiPolygon") else None
    if not isinstance(value, str):
        return None
    shape, _, body = value.partition("(")
    kind = {"POLYGON": "Polygon", "MULTIPOLYGON": "MultiPolygon"}.get(shape.strip())
    if not kind:
        return None

    def point(match):
        return "[" + ",".join(match.group().split()) + "]"

    body = "(" + body
    body = re.sub(r"[-+.\deE]+\s+[-+.\deE]+", point, body)
    try:
        coordinates = json.loads(body.replace("(", "[").replace(")", "]"))
    except ValueError:
        return None
    return {"type": kind, "coordinates": coordinates}


def feature(geometry, label, **properties):
    return {"type": "Feature", "geometry": geometry, "properties": {"label": label, **properties}}


def recent_parcel_collections(payload):
    """Do not combine successive imagery versions into overlapping site parcels.

    The provider has returned multiple years even with latest=true. Select the
    newest dated collection at the point (or nearby when the point has no parcel).
    Retain ties, including overlapping parcels, for explicit local ambiguity checks.
    """
    features = payload["features"]
    containing = [f for f in features if f.get("properties", {}).get("request-information.inside-parcel") is True]
    dated = []
    for item in containing or features:
        props = item.get("properties", {})
        date, collection = props.get("metadata.ortho-date-estimate"), props.get("metadata.collection")
        if not isinstance(date, str) or not isinstance(collection, str) or not collection:
            continue
        try:
            # Capture timestamps are compared as calendar dates, not mixed UTC/
            # local datetimes. Collections captured on the same day remain tied.
            day = datetime.fromisoformat(date).date()
        except ValueError:
            continue
        dated.append((day, collection))
    if not dated:
        return payload
    newest = max(day for day, _ in dated)
    collections = {collection for day, collection in dated if day == newest}
    return {**payload, "features": [f for f in features if f.get("properties", {}).get("metadata.collection") in collections],
            "collectionSelection": "Most recent dated collection returned for this point or nearby search; older versions are not combined. Coverage may be incomplete."}


def parcel_features(payload, evidence, *, nearby=False):
    if not isinstance(payload, dict) or not isinstance(payload.get("features"), list):
        raise ValueError("Parcel response has no valid feature collection.")
    parcels = []
    for item in payload["features"]:
        if not isinstance(item, dict) or not isinstance(item.get("properties"), dict):
            raise ValueError("Parcel response contains an invalid feature.")
        if nearby or item["properties"].get("request-information.inside-parcel") is True:
            parcels.append(item)
    parcels.sort(key=lambda item: item["properties"].get("metadata.ortho-date-estimate") or "", reverse=True)
    seen, outlines = set(), []
    for parcel in parcels if nearby else parcels[:1]:
        props = parcel["properties"]
        boundary = polygon_geometry(parcel.get("geometry"))
        structures = props.get("structures")
        if boundary is None or (not isinstance(structures, list) and not (nearby and structures is None)):
            raise ValueError("Parcel response has incomplete boundary or building coverage.")
        signature = json.dumps(boundary, sort_keys=True)
        if signature in seen:
            continue
        seen.add(signature)
        metadata = {
            "collection": props.get("metadata.collection"),
            "date": (props.get("metadata.ortho-date-estimate") or "")[:10],
            "gsd": props.get("metadata.gsd"),
            "collectionSelection": payload.get("collectionSelection"),
        }
        outlines.append(feature(boundary, "Parcel boundary", buildingCoverage=structures is not None, **metadata))
        for structure in structures or []:
            if not isinstance(structure, dict):
                raise ValueError("Parcel response contains an invalid building.")
            footprint = polygon_geometry(structure.get("footprint.wkt"))
            if footprint is None:
                raise ValueError("Parcel response contains an unusable building footprint.")
            outlines.append(feature(footprint, "Building footprint", **metadata))
    evidence["outlines"].extend(outlines)


def detection_features(payload, evidence, labels):
    if not isinstance(payload, dict) or not isinstance(payload.get("features"), list):
        raise ValueError("Detection response has no valid feature collection.")
    for item in payload["features"]:
        if not isinstance(item, dict) or not isinstance(item.get("properties"), dict):
            raise ValueError("Detection response contains an invalid feature.")
        props = item["properties"]
        label = props.get("label")
        if not isinstance(label, str) or not label.strip():
            raise ValueError("Detection response contains an invalid label.")
        if label not in labels:
            continue
        candidates = props.get("detections")
        if not isinstance(candidates, list):
            raise ValueError("Detection response contains an invalid candidate list.")
        for candidate in candidates:
            if not isinstance(candidate, dict):
                raise ValueError("Detection response contains an invalid candidate.")
            geometry = polygon_geometry(candidate.get("bbox"))
            if geometry is None:
                raise ValueError("Detection response contains an unusable candidate box.")
            score = candidate.get("confidence")
            if score is not None and (isinstance(score, bool) or not isinstance(score, (int, float))
                                      or not math.isfinite(score) or not 0 <= score <= 1):
                raise ValueError("Detection response contains an invalid confidence score.")
            evidence["detections"].append(feature(geometry, label.capitalize(), score=score))
    evidence["detections"].sort(key=lambda item: item["properties"]["score"] or 0, reverse=True)



def imagery_evidence(request, layers, lon, lat, workflow, group):
    dy = 75 / 111_320
    dx = dy / math.cos(math.radians(lat))
    west, east, south, north = lon - dx, lon + dx, lat - dy, lat + dy
    area = f"POLYGON(({west} {south},{east} {south},{east} {north},{west} {north},{west} {south}))"
    image = {"wkt": area, "srid": 4326, "layer": layers, "crop": "bounding_box"}
    labels = DETECTION_LABELS[workflow]
    calls = {
        "outlines": ("/property/extract", {
            "wkt": f"POINT({lon} {lat})", "srid": 4326, "layer": layers,
            "latest": "true", "include": "footprint-wkt,capture-date,collection,gsd",
            "buffer-meter": 200 if workflow == "street" else 0, "page-size": 250,
        }, False),
        "search": ("/embedding/extract", {
            "wkt": area, "srid": 4326, "search-text": SEARCH_TEXT[workflow],
            "include": "score,geometry,collection", "total-records": 3, "page-size": 3,
        }, True),
        "detections": ("/elements/detect", {
            "wkt": area, "srid": 4326, "buffer-meter": 0,
            "images": [{"endpoint": "ortho/extract", "request": image}],
            "model-input": {"elements": [
                {"label": label, "model": "sam3", "detection-threshold": 0.5} for label in labels
            ], "include": ["bbox", "confidence"]},
        }, True),
    }

    path, params, post = calls[group]
    def fetch(values):
        try:
            return json.loads(request(path, values, "application/json", 5_000_000, post=post, timeout=25))
        except ValueError as error:
            if group == "outlines" and str(error) == "No Vexcel property outlines are available at this point.":
                return {"features": []}
            raise
    payload = fetch(params)
    evidence = {group: []}
    if group == "outlines":
        if not isinstance(payload.get("features"), list):
            raise ValueError("Vexcel returned no valid parcel collection.")
        if workflow == "water" and not any(item.get("properties", {}).get("request-information.inside-parcel") is True
                                           for item in payload["features"] if isinstance(item, dict)):
            payload = fetch({**params, "buffer-meter": 75})
        if not isinstance(payload.get("features"), list) or len(payload["features"]) >= 250:
            raise ValueError("The bounded parcel search is incomplete; narrow the selected site.")
        # Keep distinct overlapping/nearby parcels so local resolution can disclose
        # ambiguity rather than choosing the first returned property.
        parcel_features(recent_parcel_collections(payload), evidence, nearby=True)
    elif group == "detections":
        detection_features(payload, evidence, labels)
    else:
        for item in payload.get("features", [])[:3]:
            geometry = polygon_geometry(item.get("geometry"))
            if geometry:
                evidence["search"].append(feature(geometry, "Imagery search match"))
    return evidence[group]
