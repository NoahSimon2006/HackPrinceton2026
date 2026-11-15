"""Resolve local CoStar context without assigning the nearest property to a point."""
from math import hypot, cos, radians

from shapely.geometry import Point

from site_measurements import PROJECT, projected


def resolve_site(items, lon, lat, outlines, *, property_id=None, radius=200):
    point = Point(*PROJECT.transform(lon, lat))
    nearby = sorted(items, key=lambda p: hypot((p["lon"] - lon) * cos(radians(lat)), p["lat"] - lat))
    nearby = [p for p in nearby if hypot((p["lon"] - lon) * cos(radians(lat)), p["lat"] - lat) * 111_320 <= radius]
    result = {"status": "unmatched", "property": None, "candidates": nearby[:5],
              "message": "No unique property match. Nearby properties are choices, not an association to this point."}
    if property_id is not None:
        matches = [p for p in items if p["id"] == property_id]
        if len(matches) != 1:
            raise ValueError("The selected property is not in the local catalog.")
        prop = matches[0]
        if point.distance(Point(*PROJECT.transform(prop["lon"], prop["lat"]))) <= 1.5:
            return {**result, "status": "selected", "property": prop, "candidates": [],
                    "message": "Selected CoStar property. Ownership and access rights are not verified."}
    parcels = {}
    for item in outlines:
        if item.get("properties", {}).get("label") != "Parcel boundary":
            continue
        polygon = projected(item["geometry"], ("Polygon", "MultiPolygon"))
        if not point.buffer(5000).covers(polygon):
            raise ValueError("Parcel geometry is outside the site scope.")
        if polygon.covers(point):
            parcels[polygon.normalize().wkb] = polygon
    matches = [p for p in items if any(g.covers(Point(*PROJECT.transform(p["lon"], p["lat"]))) for g in parcels.values())]
    if len(parcels) == 1 and len(matches) == 1:
        if property_id is not None and matches[0]["id"] != property_id:
            raise ValueError("The property reference does not match this location.")
        return {**result, "status": "matched", "property": matches[0], "candidates": [],
                "message": "One CoStar location shares the mapped parcel with this point. This spatial match does not establish ownership or access."}
    if property_id is not None:
        raise ValueError("The property reference cannot be associated uniquely with this location.")
    if len(parcels) > 1 or len(matches) > 1:
        return {**result, "status": "ambiguous", "candidates": (matches or nearby)[:5],
                "message": "Multiple parcel or property matches. Choose a property to use its location, or investigate the map point without assigning one."}
    if parcels:
        result["message"] = "A mapped parcel contains this point, but no CoStar location matches it. Nearby properties remain separate choices."
    return result
