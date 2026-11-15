"""Collect geographically bounded imagery evidence for a selected site."""

import json
import math
import re

SEARCH_TEXT = {
    "street": "marked pedestrian crosswalks and driveway entrances connecting to a street",
    "water": "paved parking lots, building rooftops, and landscaped strips next to pavement",
}
DETECTION_LABELS = {
    "street": ("zebra crosswalk", "driveway entrance"),
    "water": ("parking lot", "landscaped strip"),
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


def parcel_features(payload, evidence):
    parcels = [
        item for item in payload.get("features", [])
        if item["properties"].get("request-information.inside-parcel") and polygon_geometry(item.get("geometry"))
    ]
    if not parcels:
        return
    parcel = max(parcels, key=lambda item: item["properties"].get("metadata.ortho-date-estimate") or "")
    props = parcel["properties"]
    metadata = {
        "collection": props.get("metadata.collection"),
        "date": (props.get("metadata.ortho-date-estimate") or "")[:10],
    }
    evidence["outlines"].append(feature(polygon_geometry(parcel["geometry"]), "Parcel boundary", **metadata))
    for structure in props.get("structures", [])[:12]:
        geometry = polygon_geometry(structure.get("footprint.wkt"))
        if geometry:
            evidence["outlines"].append(feature(geometry, "Building footprint", **metadata))


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
            evidence["detections"].append(feature(geometry, label.capitalize(), score=candidate.get("confidence")))
    evidence["detections"].sort(key=lambda item: item["properties"]["score"] or 0, reverse=True)
    del evidence["detections"][12:]


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
            "latest": "true", "include": "precomputed,footprint-wkt",
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
    payload = json.loads(request(path, params, "application/json", 5_000_000, post=post, timeout=25))
    evidence = {group: []}
    if group == "outlines":
        parcel_features(payload, evidence)
    elif group == "detections":
        detection_features(payload, evidence, labels)
    else:
        for item in payload.get("features", [])[:3]:
            geometry = polygon_geometry(item.get("geometry"))
            if geometry:
                evidence["search"].append(feature(geometry, "Imagery search match"))
    return evidence[group]
