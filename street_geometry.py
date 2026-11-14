"""Build measurable street concepts in local meters and publish GeoJSON for both views."""
import math

from shapely.geometry import Point, Polygon, mapping
from shapely.ops import unary_union

METERS_PER_DEGREE = 111_195
FEATURED_SITE = {
    "name": "OLYMPIC BL & WALL ST",
    "lat": 34.037603,
    "lon": -118.253109,
    "years": {},
    "featured": True,
}
# City of LA street centerlines establish the angles. Widths are interpreted
# from the Vexcel aerial view and remain concept-level inputs.
FEATURED_BEARINGS = {"first": 129.8, "second": 42.3, "basis": "LA street centerlines"}
FEATURED_WIDTHS_M = (17.0, 13.4)
RENDERED_TYPES = {
    "curb_extension", "planted_curb_extension", "median_refuge", "roundabout",
    "protected_bike_lane", "lane_reduction", "high_visibility_crosswalk",
    "raised_crossing", "speed_cushion", "hardened_centerline", "daylighting",
    "lighting", "chicane",
}


def lon_scale(site):
    return METERS_PER_DEGREE * math.cos(math.radians(site["lat"]))


def to_local(site, lon, lat):
    return (lon - site["lon"]) * lon_scale(site), (lat - site["lat"]) * METERS_PER_DEGREE


def to_geo(site, east, north):
    return [round(site["lon"] + east / lon_scale(site), 8), round(site["lat"] + north / METERS_PER_DEGREE, 8)]


def at(bearing, along, lateral):
    sine, cosine = math.sin(math.radians(bearing)), math.cos(math.radians(bearing))
    return along * sine + lateral * cosine, along * cosine - lateral * sine


def bounding_ring(west, south, east, north):
    return [(west, south), (east, south), (east, north), (west, north), (west, south)]


def local_constraint(site, bounds):
    west, south = to_local(site, bounds[0], bounds[1])
    east, north = to_local(site, bounds[2], bounds[3])
    return Polygon(bounding_ring(west, south, east, north))


def build_geometry(site, bearings, design, constraints):
    """Compute shared map/3D features and test ground footprints against marked areas."""
    keys = ("first", "second")
    widths = FEATURED_WIDTHS_M if site.get("featured") else tuple(
        design[f"{key}_street_lanes_before"] * 3.3 + 4 for key in keys
    )
    halves = dict(zip(keys, (width / 2 for width in widths)))
    features, replaced, conflicts = [], [], []
    excluded = [local_constraint(site, area) for area in constraints]
    crossing_edges = {}

    def add(shape, kind, element, number, height=0, *, convert=False, clearance=False):
        if shape.is_empty or shape.area < 0.02:
            return
        if convert:
            replaced.append(shape)
        if clearance:
            for index, area in enumerate(excluded, start=1):
                if shape.intersection(area).area > 0.05:
                    conflict = {"element": element["label"], "area": index}
                    if conflict not in conflicts:
                        conflicts.append(conflict)
        ring = [to_geo(site, x, y) for x, y in mapping(shape)["coordinates"][0]]
        features.append({"type": "Feature", "geometry": {"type": "Polygon", "coordinates": [ring]},
                         "properties": {"kind": kind, "label": element["label"], "number": number, "height_m": height}})

    def add_tree(position, element, number):
        tree_base = Point(*position).buffer(0.3)
        for index, area in enumerate(excluded, start=1):
            if tree_base.intersection(area).area > 0.02:
                conflict = {"element": element["label"], "area": index}
                if conflict not in conflicts:
                    conflicts.append(conflict)
        features.append({"type": "Feature", "geometry": {"type": "Point", "coordinates": to_geo(site, *position)},
                         "properties": {"kind": "tree", "label": element["label"], "number": number}})

    for number, element in enumerate(design["elements"], start=1):
        kind = element["type"]
        if kind == "roundabout":
            radius = min(widths) * 0.31
            ring = [(math.cos(i * math.tau / 24) * radius, math.sin(i * math.tau / 24) * radius) for i in range(24)]
            add(Polygon(ring), "planted", element, number, 0.2, convert=True, clearance=True)
            continue
        if kind not in RENDERED_TYPES:
            continue
        streets = keys if element["street"] == "both" else (element["street"],)
        approaches = {"positive": (1,), "negative": (-1,), "both": (-1, 1)}[element.get("approach", "both")]
        sides = {"left": (-1,), "right": (1,), "both": (-1, 1)}[element.get("side", "both")]
        for street in streets:
            half = halves[street]
            across = halves["second" if street == "first" else "first"]
            bearing = bearings[street]
            setback = element.get("setback_m", 0)
            length = element.get("length_m", 10)
            depth = min(element.get("extension_m", 2.4), half - 1.4)
            for direction in approaches:
                def point(along, lateral):
                    return at(bearing, along * direction, lateral)

                def shape(points):
                    return Polygon([point(along, lateral) for along, lateral in points])

                def box(start, end, left, right):
                    return shape(bounding_ring(start, left, end, right))

                start = across + 1.5 + setback
                if kind in ("curb_extension", "planted_curb_extension"):
                    for side in sides:
                        outer, inner = side * half, side * (half - depth)
                        footprint = shape([(start, outer), (start + length, outer),
                                           (start + length - 1.6, inner), (start + 1.6, inner)])
                        material = "planted" if kind == "planted_curb_extension" else "concrete"
                        add(footprint, material, element, number, 0.18, convert=True, clearance=True)
                        if setback <= 2.5:
                            edge = (street, direction, side)
                            crossing_edges[edge] = max(crossing_edges.get(edge, 0), depth)
                        if material == "planted":
                            add_tree(point(start + length * 0.63, (outer + inner) / 2), element, number)
                elif kind in ("median_refuge", "hardened_centerline", "speed_cushion"):
                    if kind == "median_refuge":
                        add(box(start + 5, start + length + 5, -0.9, 0.9), "planted", element, number, 0.18, convert=True, clearance=True)
                    elif kind == "hardened_centerline":
                        add(box(start, start + length, -0.16, 0.16), "amber", element, number, 0.12, clearance=True)
                    else:
                        add(box(start + 25, start + 28, -half + 2, half - 2), "amber", element, number, 0.08, clearance=True)
                elif kind in ("high_visibility_crosswalk", "raised_crossing"):
                    if kind == "raised_crossing":
                        add(box(start, start + 3.2, -half, half), "concrete", element, number, 0.12, clearance=True)
                    for index in range(math.floor((2 * half - 0.6) / 1.3)):
                        lateral = -half + 0.55 + index * 1.3
                        add(box(start, start + 3.2, lateral, lateral + 0.56), "marking", element, number)
                elif kind in ("protected_bike_lane", "lane_reduction", "daylighting"):
                    for side in sides:
                        if kind == "lane_reduction":
                            lanes_before, lanes_after = (design[f"{street}_street_lanes_{stage}"] for stage in ("before", "after"))
                            lane_space = (lanes_before - lanes_after) * 1.65
                            if lane_space > 0:
                                add(box(start + 5, start + 36, side * max(0.8, half - lane_space), side * half),
                                    "reallocated", element, number, clearance=True)
                        else:
                            width = 1.8 if kind == "protected_bike_lane" else 0.18
                            add(box(start + 5, start + 36, side * (half - width), side * (half - 0.04)),
                                "bike" if kind == "protected_bike_lane" else "amber", element, number)
                elif kind == "lighting":
                    for side in sides:
                        east, north = point(start + 3, side * (half + 0.6))
                        features.append({"type": "Feature", "geometry": {"type": "Point", "coordinates": to_geo(site, east, north)},
                                         "properties": {"kind": "lamp", "label": element["label"], "number": number}})
                elif kind == "chicane":
                    for side in sides:
                        edge = side * half
                        position = start + (14 if side < 0 else 30)
                        add(shape([(position, edge), (position + 11, edge), (position + 6, edge - side * depth)]),
                            "concrete", element, number, 0.18, convert=True, clearance=True)

    crossings = []
    for street in keys:
        for direction, approach in ((1, "positive"), (-1, "negative")):
            saved = sum(crossing_edges.get((street, direction, side), 0) for side in (-1, 1))
            if saved:
                crossings.append({"street": street, "approach": approach, "before_m": round(halves[street] * 2, 1),
                                  "after_m": round(halves[street] * 2 - saved, 1)})
    converted = unary_union(replaced).area if replaced else 0
    shadow_polygons, shadow_area = proposal_shadow(site, features)
    tree_count = sum(f["properties"]["kind"] == "tree" for f in features)
    features.extend({"type": "Feature", "geometry": {"type": "Polygon", "coordinates": rings},
                     "properties": {"kind": "shade", "label": "Modeled tree shade · July 15, 4 p.m. PDT", "height_m": 0}}
                    for rings in shadow_polygons)
    return {"type": "FeatureCollection", "features": features,
            "metrics": {"converted_m2": round(converted, 1), "crossings": crossings,
                        "trees": tree_count, "modeled_tree_shade_m2": shadow_area},
            "conflicts": conflicts}


def street_stops(site, bearings):
    return [{"position": to_geo(site, *at(bearings["first"], along, 0)),
             "heading": bearings["first"], "label": label}
            for along, label in [(-53, "Far approach"), (-34, "Approach"), (-17, "Before the crossing"),
                                 (0, "Intersection"), (17, "Beyond the crossing"), (34, "Departure"),
                                 (53, "Far departure")]]


def proposal_shadow(site, features):
    """Project 1.6 m crowns centered 3.6 m high before existing shade overlap."""
    trees = [to_local(site, *feature["geometry"]["coordinates"]) for feature in features
             if feature["properties"]["kind"] == "tree"]
    if not trees:
        return [], 0
    # 23:00 UTC / 16:00 PDT on July 15, 2026. Approximate apparent solar position.
    declination = math.radians(21.45)
    hour_angle = math.radians((23 - 12) * 15 + site["lon"] - 1.48)
    latitude = math.radians(site["lat"])
    east = -math.cos(declination) * math.sin(hour_angle)
    north = math.cos(latitude) * math.sin(declination) - math.sin(latitude) * math.cos(declination) * math.cos(hour_angle)
    up = math.sin(latitude) * math.sin(declination) + math.cos(latitude) * math.cos(declination) * math.cos(hour_angle)
    radius, center_height = 1.6, 3.6
    direction = math.atan2(north, east)
    footprints = []
    for x, y in trees:
        points = []
        for i in range(32):
            angle = i * math.tau / 32
            along, across = radius / up * math.cos(angle), radius * math.sin(angle)
            points.append((x - center_height * east / up + along * math.cos(direction) - across * math.sin(direction),
                           y - center_height * north / up + along * math.sin(direction) + across * math.cos(direction)))
        footprints.append(Polygon(points))
    merged = unary_union(footprints)
    shapes = [merged] if merged.geom_type == "Polygon" else merged.geoms
    rings = [[[to_geo(site, x, y) for x, y in ring.coords]
              for ring in (polygon.exterior, *polygon.interiors)] for polygon in shapes]
    return rings, round(merged.area, 1)
