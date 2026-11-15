"""Deterministic intersection plans inside a sourced street envelope.

The model selects bounded design parameters. Every surface and paint marking is
compiled here in metres; the browser never invents the missing road geometry.
These drawings are screening concepts, not surveyed curb lines or traffic plans.
"""
from __future__ import annotations

import math
import re

from shapely import set_precision, unary_union
from shapely.geometry import LineString, Point, Polygon
from shapely.ops import nearest_points, substring

from site_measurements import PROJECT, projected
from street_context import _geographic

SURFACES = frozenset({"roadway", "sidewalk", "curb", "planting", "centerline", "crosswalk", "stop_line", "lane_arrow"})
PARAMETERS = {
    "approach_length_m": (28., 15., 60.),
    "curb_extension_m": (1.2, .6, 3.),
    "crossing_setback_m": (4., 2., 10.),
    "crossing_width_m": (3., 2., 5.),
}


def _point(value):
    if not isinstance(value, dict) or value.get("type") != "Point":
        raise ValueError("The junction needs sourced mouth and center points.")
    pair = value.get("coordinates")
    if not isinstance(pair, (list, tuple)) or len(pair) != 2 or any(type(v) not in (float, int) or not math.isfinite(v) for v in pair):
        raise ValueError("The junction point coordinates are invalid.")
    if not -119 < pair[0] < -117 or not 33 < pair[1] < 35:
        raise ValueError("The junction is outside the supported source area.")
    return Point(*PROJECT.transform(*pair))


def _polygons(value):
    if value.is_empty:
        return Polygon()
    if value.geom_type == "Polygon":
        return value
    if value.geom_type == "MultiPolygon":
        parts = [part for part in value.geoms if part.area >= .001]
        return parts[0] if len(parts) == 1 else unary_union(parts)
    return unary_union([g for g in value.geoms if g.geom_type in ("Polygon", "MultiPolygon")])


def _frame(line, offset):
    offset = max(0., min(line.length, offset))
    at = line.interpolate(offset)
    before = line.interpolate(max(0., offset - .2))
    after = line.interpolate(min(line.length, offset + .2))
    length = before.distance(after)
    if length < .05:
        raise ValueError("A sourced intersection approach is too short to align the plan.")
    dx, dy = (after.x - before.x) / length, (after.y - before.y) / length
    return at, (dx, dy), (-dy, dx)


def _rectangle(at, along, length, width, start=0., lateral=0.):
    dx, dy = along
    nx, ny = -dy, dx
    return Polygon([(at.x + dx*x + nx*y, at.y + dy*x + ny*y)
                    for x, y in ((start, lateral), (start+length, lateral), (start+length, lateral+width), (start, lateral+width))])


def _ribbon(line, stops):
    """A width profile along the actual mouth-outward source centreline."""
    positions = {0., line.length, *(min(line.length, max(0., x)) for x, _ in stops)}
    distance = 0.
    for a, b in zip(line.coords, list(line.coords)[1:]):
        distance += math.dist(a, b)
        positions.add(min(line.length, distance))
    # Sample bends as well as width transitions, avoiding a straight chord across
    # a curved approach or a sharp, oversized miter at a source vertex.
    positions.update(float(x) for x in range(2, int(line.length), 2))
    def width_at(x):
        for (start, left), (end, right) in zip(stops, stops[1:]):
            if start <= x <= end:
                return left + (right-left)*(x-start)/max(.001, end-start)
        return stops[-1][1]
    left, right = [], []
    positions = {min(line.length, round(position, 5)) for position in positions}
    for position in sorted(positions):
        p, _, normal = _frame(line, position)
        half = width_at(position) / 2
        left.append((p.x + normal[0]*half, p.y + normal[1]*half))
        right.append((p.x - normal[0]*half, p.y - normal[1]*half))
    result = Polygon([*left, *reversed(right)])
    if not result.is_valid:
        raise ValueError("This approach bends too sharply for the requested intersection plan. Shorten its extent.")
    return result


def resolve_junction(context, component):
    identifier = component.get("junction_id")
    if not isinstance(identifier, str) or not re.fullmatch(r"junction-[a-f0-9]{12}", identifier):
        raise ValueError("An intersection redesign needs a sourced junction_id from the road context.")
    junction = next((j for j in context.get("junctions", []) if j.get("id") == identifier), None)
    if not junction or not 3 <= len(junction.get("approaches", [])) <= 8:
        raise ValueError("Choose a sourced junction with at least three connected road approaches.")
    if component.get("anchor_id") not in {a.get("anchor_id") for a in junction["approaches"]}:
        raise ValueError("The selected road anchor must belong to this junction.")
    return junction


def normalize_intersection(context, component):
    junction = resolve_junction(context, component)
    if component.get("layout") not in (None, "compact", "roundabout"):
        raise ValueError("Choose the compact intersection layout.")
    if component.get("layout") == "roundabout":
        # A circle that happens to fit in a bounding box is not evidence of a
        # feasible roundabout. Swept paths and an adopted entry design are not
        # available in the current source context; do not render a false fit.
        raise ValueError("A roundabout needs verified entry widths and vehicle turn paths that this source does not provide. Use layout compact for a connected, source-aligned intersection plan.")
    if any(component.get(k) is not None for k in ("side", "offset_m", "length_m", "width_m")):
        raise ValueError("An intersection package uses approach_length_m, curb_extension_m, crossing_setback_m and crossing_width_m, not individual-strip dimensions.")
    result = {key: component[key] for key in ("id", "kind", "anchor_id", "junction_id")}
    result["layout"] = "compact"
    for key, (default, low, high) in PARAMETERS.items():
        value = component.get(key)
        if value is None and key == "crossing_setback_m":
            # Source readers locate landings beside each junction mouth. Use
            # their bounded common starting offset unless the user explicitly
            # requests a different setback, which still must pass every check.
            candidates = [a.get("crossing_offset_m", default) for a in junction["approaches"]]
            value = max(low, min(default, *candidates))
        value = default if value is None else value
        if type(value) not in (float, int) or not math.isfinite(value) or not low <= value <= high:
            raise ValueError(f"Use {key} between {low:g} and {high:g} metres.")
        result[key] = float(value)
    if result["crossing_setback_m"] + result["crossing_width_m"] + 6 > result["approach_length_m"]:
        raise ValueError("Keep at least 6 m of the approach beyond each crossing for a stop line and approach markings.")
    result["label"] = "Intersection redesign"
    return result


def compile_intersection(context, component, constraints, revision):
    """Return exact ordered features and measurable spatial checks for one plan."""
    junction = resolve_junction(context, component)
    center = _point(junction["center"])
    source_core = projected(junction["area"], ("Polygon", "MultiPolygon"))
    source_plan = projected(junction["plan_area"], ("Polygon", "MultiPolygon"))
    origin = Point(*PROJECT.transform(context["origin"]["lon"], context["origin"]["lat"]))
    if not origin.buffer(1000).covers(source_plan) or source_core.difference(source_plan.buffer(.05)).area > .1:
        raise ValueError("The sourced junction envelope is inconsistent; refresh its road geometry.")
    if center.distance(source_core) > 3 or source_core.area < 5:
        raise ValueError("The sourced junction does not contain a usable intersection center.")
    approaches, influence_parts, road_parts = [], [source_core.buffer(.003).intersection(source_plan)], []
    end_openings = []
    source_access = []
    access_shapes = {}
    crossing_width = component["crossing_width_m"]
    for approach in junction["approaches"]:
        line = projected(approach["geometry"], ("LineString",))
        source_road = projected(approach["road_geometry"], ("Polygon", "MultiPolygon"))
        mouth = _point(approach["mouth"])
        if line.interpolate(0).distance(mouth) > .1 or mouth.distance(source_core) > 2:
            raise ValueError("An approach is detached from its sourced junction mouth; refresh the source geometry.")
        if source_road.difference(source_plan.buffer(.05)).area > .1:
            raise ValueError("An approach extends beyond the sourced street envelope.")
        length = min(component["approach_length_m"], line.length, approach["available_length_m"])
        cross_start = component["crossing_setback_m"]
        if length < cross_start + crossing_width + 6:
            raise ValueError("A sourced approach is too short for connected crossings and stop lines. Reduce the crossing setback or choose another junction.")
        line = substring(line, 0., length)
        traffic_direction = approach.get("traffic_direction", "two_way")
        if traffic_direction != "two_way":
            raise ValueError("This junction includes a one-way or unverified traffic direction. A coordinated plan needs verified approach movements before lane arrows or stop lines can be drawn.")
        modeled_width = float(approach["width_m"])
        envelope_width = float(approach.get("plan_width_m", approach.get("street_width_m", approach.get("crossing_span_m", modeled_width))))
        if not 3 <= modeled_width <= 40 or not 3 <= envelope_width <= 45 or envelope_width < modeled_width-.2:
            raise ValueError("The sourced approach widths cannot support a bounded intersection plan.")
        # Sidewalks and buildouts occupy the sourced street envelope only. A
        # lane-only source never licenses inventing extra pavement to either side.
        minimum_road = min(modeled_width, 6.)
        available_side = max(0., (envelope_width-minimum_road)/2)
        # Compact means one 3–3.6 m through lane in each direction. Any
        # former parking/extra-width allocation is shown explicitly as proposed
        # pedestrian space; lane capacity and turn feasibility are unassessed.
        base_walk = max(0., (envelope_width-7.2)/2)
        base_walk = max(base_walk, min(1.8, available_side * .55))
        extension = min(component["curb_extension_m"], max(0., available_side-base_walk))
        if base_walk < 1.2:
            raise ValueError("The sourced street envelope is too narrow for two through lanes and a meaningful pedestrian path on each side. A wider verified street or walking envelope is needed; do not draw token-width sidewalks.")
        road_mouth = envelope_width-2*(base_walk+extension)
        road_far = envelope_width-2*base_walk
        taper_start = cross_start + crossing_width + 1.5
        taper_end = min(length-1., taper_start+6.)
        stops = [(0., road_mouth), (taper_start, road_mouth), (taper_end, road_far), (length, road_far)]
        corridor = _polygons(line.buffer(max(envelope_width/2+3., 25.), cap_style="flat", join_style="round").intersection(source_road))
        if corridor.area < 10 or corridor.distance(source_core) > .1:
            raise ValueError("The sourced approach corridor is disconnected from the intersection.")
        influence_parts.append(corridor)
        nearest = nearest_points(source_core, mouth)[0]
        if nearest.distance(mouth) > .00001:
            influence_parts.append(LineString([mouth, nearest]).buffer(envelope_width/2, cap_style="square").intersection(source_plan))
        for opening in approach.get("access_openings", []):
            opened = projected(opening["geometry"]).intersection(corridor)
            key = opening.get("id") or opened.wkb_hex
            if not opened.is_empty and opened.area > .01:
                access_shapes[key] = unary_union([access_shapes.get(key, Polygon()), opened])
        paved = _ribbon(line, stops).intersection(corridor)
        # The connecting segment reaches into the sourced junction, maintaining
        # every approach instead of drawing independent, floating road strips.
        bridge = LineString([center, mouth]).buffer(road_mouth/2, cap_style="round")
        road_parts.extend([paved, bridge.intersection(source_plan)])
        end, tangent, _ = _frame(line, length)
        end_openings.append(_rectangle(end, tangent, 2., envelope_width+2, -1., -(envelope_width+2)/2))
        approaches.append({"source": approach, "line": line, "length": length, "road_width": road_mouth,
                           "far_width": road_far, "envelope_width": envelope_width,
                           "extension": extension, "cross_start": cross_start})
    source_access = list(access_shapes.values())
    original_influence = _polygons(unary_union(influence_parts).intersection(source_plan))
    pedestrian_extensions = Polygon()
    if "pedestrian_connections" in junction:
        connections = []
        for connection in junction["pedestrian_connections"]:
            geometry = projected(connection["geometry"], ("Polygon", "MultiPolygon"))
            if geometry.difference(source_plan.buffer(.02)).area > .05:
                raise ValueError("A pedestrian corner connection extends beyond its sourced planning envelope.")
            connections.append(geometry)
        pedestrian_extensions = _polygons(unary_union(connections).difference(original_influence))
        influence_parts.extend(connections)
    influence = _polygons(unary_union(influence_parts).intersection(source_plan))
    if influence.geom_type != "Polygon" or not influence.is_valid:
        raise ValueError("The source street envelope is not a continuous intersection. Refresh the junction context.")
    # Round the inside corners of the carriageway, producing continuous curb
    # returns. All expansion is clipped back to the known source envelope.
    core_road = source_core.buffer(-min(2.5, max(.25, min(a["envelope_width"]-a["road_width"] for a in approaches)/2)))
    road_parts.append(core_road)
    roadway = _polygons(set_precision(unary_union(road_parts).buffer(1.4, join_style="round").buffer(-1.4, join_style="round").intersection(influence), .001))
    if not pedestrian_extensions.is_empty:
        roadway = _polygons(roadway.difference(pedestrian_extensions))
    if roadway.geom_type != "Polygon" or roadway.area < 20:
        raise ValueError("The proposed carriageway is disconnected. Use smaller curb extensions or another sourced junction.")
    access = _polygons(unary_union(source_access).intersection(influence))
    if not access.is_empty:
        roadway = _polygons(unary_union([roadway, access]))
    sidewalks = _polygons(influence.difference(roadway))
    # Existing walking paths are source context, not invented curb locations.
    # Connect each crossing end to its matched landing within the known envelope.
    landing_parts = []
    crossing_rows = []
    for row in approaches:
        line, width = row["line"], row["road_width"]
        position = row["cross_start"] + crossing_width/2
        at, tangent, normal = _frame(line, position)
        band = _rectangle(at, tangent, crossing_width, row["envelope_width"], -crossing_width/2, -row["envelope_width"]/2)
        cross_road = _polygons(band.intersection(roadway))
        if cross_road.is_empty or cross_road.area < crossing_width*2:
            raise ValueError("A crossing cannot span this approach's proposed carriageway.")
        # Landings are the two continuous sidewalk areas touching the crossing;
        # they remain present even where footway mapping has no precise width.
        for sign in (-1, 1):
            endpoint = Point(at.x + normal[0]*sign*(width/2), at.y + normal[1]*sign*(width/2))
            landing_test = _rectangle(at, tangent, crossing_width, 1.2, -crossing_width/2,
                                      width/2 if sign == 1 else -width/2-1.2)
            landing = landing_test.intersection(sidewalks)
            if landing.area < landing_test.area-.12:
                raise ValueError("A crossing needs a connected pedestrian landing with at least 1.2 m of conceptual clear depth on both sides. Choose a wider verified street envelope or move the crossing setback.")
            landing_parts.append(landing)
        crossing_rows.append((row, at, tangent, cross_road))
    # Curbs are thin geometry, interrupted across open road ends and crossing
    # landings; their visible width is 18 cm rather than a map-zoom stroke.
    curb = _polygons(roadway.boundary.buffer(.09).intersection(influence).difference(unary_union(end_openings)))
    crossing_clear = unary_union([cross.buffer(.3) for _, _, _, cross in crossing_rows])
    curb = _polygons(curb.difference(crossing_clear).difference(access.buffer(.2)))
    clear = unary_union([projected(f["geometry"]) for f in constraints["keep_clear"]])
    buildings = unary_union([projected(f["geometry"]) for f in constraints["buildings"]])
    # A keep-clear road passage may remain asphalt; physical pedestrian buildouts
    # must not occupy it. Source building conflicts invalidate the entire plan.
    if not clear.is_empty and sidewalks.intersection(clear).area > .05:
        raise ValueError("The intersection buildout overlaps a marked keep-clear area. Reduce curb extensions or revise the marked access area.")
    if not buildings.is_empty and influence.intersection(buildings).area > .1:
        raise ValueError("The sourced intersection plan overlaps a mapped building. Refresh its street envelope before designing here.")
    features = []
    def emit(geometry, surface, suffix, role="proposed"):
        geometry = _polygons(set_precision(geometry, .001))
        if geometry.is_empty or geometry.area < .005:
            return
        if not geometry.is_valid or geometry.geom_type not in ("Polygon", "MultiPolygon"):
            raise ValueError("The intersection produced invalid surface geometry.")
        if geometry.difference(influence.buffer(.03)).area > .05:
            raise ValueError("The proposed intersection extends beyond the sourced street envelope.")
        features.append({"type": "Feature", "id": f"{component['id']}-{suffix}", "geometry": _geographic(geometry),
                         "properties": {"component_id": component["id"], "kind": "intersection_redesign", "label": "Intersection redesign",
                                        "role": role, "surface": surface, "revision": revision}})
    # Full, opaque underlay is essential: satellite paint and removed lanes must
    # not remain visible underneath the new design.
    emit(influence, "roadway", "road-surface")
    emit(sidewalks, "sidewalk", "sidewalks")
    emit(curb, "curb", "curbs")
    for index, (row, at, tangent, cross_road) in enumerate(crossing_rows):
        line, width = row["line"], row["road_width"]
        prefix = f"approach-{index+1}"
        # Zebra bars run in the vehicle direction and repeat across the road.
        bars = []
        lateral = -row["envelope_width"]/2+.2
        while lateral < row["envelope_width"]/2-.2:
            bars.append(_rectangle(at, tangent, crossing_width, .55, -crossing_width/2, lateral).intersection(cross_road))
            lateral += 1.1
        emit(unary_union(bars), "crosswalk", prefix+"-crosswalk", "marking")
        stop_position = row["cross_start"]+crossing_width+1.5
        stop, stop_tangent, _ = _frame(line, stop_position)
        # With mouth→outward centreline, the inbound lane is on its left in
        # right-hand traffic. Stop bars never block the outbound lane.
        emit(_rectangle(stop, stop_tangent, .4, width/2-.3, -.2, .15).intersection(roadway),
             "stop_line", prefix+"-stop", "marking")
        center_start = stop_position+.8
        for mark_index, position in enumerate(_steps(center_start, row["length"]-.2, 6.)):
            dash = substring(line, position, min(row["length"], position+3.))
            emit(dash.buffer(.075, cap_style="flat").intersection(roadway), "centerline", f"{prefix}-center-{mark_index+1}", "marking")
        arrow_position = min(row["length"]-3., stop_position+6.)
        direction = _frame(line, 0.)[1]
        has_opposite = any(direction[0]*_frame(other["line"], 0.)[1][0] + direction[1]*_frame(other["line"], 0.)[1][1] < -.85
                           for other in approaches if other is not row)
        if arrow_position > stop_position+2 and has_opposite:
            arrow_at, outward, normal = _frame(line, arrow_position)
            for sign in (-1, 1):
                # Left half is inbound; right half is outbound.
                forward = (-outward[0], -outward[1]) if sign == 1 else outward
                center_arrow = Point(arrow_at.x+normal[0]*sign*width/4, arrow_at.y+normal[1]*sign*width/4)
                dx, dy = forward; nx, ny = -dy, dx
                arrow = Polygon([(center_arrow.x+dx*x+nx*y, center_arrow.y+dy*x+ny*y) for x, y in
                                 ((-1.5,-.12),(.3,-.12),(.3,-.55),(1.5,0.),(.3,.55),(.3,.12),(-1.5,.12))])
                emit(arrow.intersection(roadway), "lane_arrow", f"{prefix}-arrow-{'in' if sign == 1 else 'out'}", "marking")
    walking_connected = None
    if "pedestrian_connections" in junction:
        walking_network = _polygons(unary_union([sidewalks, *[cross for _, _, _, cross in crossing_rows], access]).buffer(.03))
        walking_connected = walking_network.geom_type == "Polygon"
        if not walking_connected:
            raise ValueError("The proposed pedestrian network has a gap between intersection corners. Refresh the mapped walking connections before publishing this plan.")
    checks = {"component_id": component["id"], "area_m2": round(influence.area, 3),
              "roadway_area_m2": round(roadway.area, 3), "sidewalk_area_m2": round(sidewalks.area, 3),
              "approach_count": len(approaches), "crossing_count": len(crossing_rows),
              "connected": True, "through_lanes_per_direction": 1, "effective_curb_extension_min_m": round(min(a["extension"] for a in approaches), 3),
              "effective_curb_extension_max_m": round(max(a["extension"] for a in approaches), 3),
              "access_openings_preserved": len(source_access), "placement_basis": str(junction.get("basis", "sourced_junction")),
              "road_fit": "checked", "keep_clear": "checked" if constraints["keep_clear"] else "no_markings",
              "building_overlap": "checked" if constraints["building_source_status"] == "available" else "unassessed"}
    if walking_connected is not None:
        checks["pedestrian_connected"] = walking_connected
        checks["pedestrian_connection_basis"] = "Source-bounded pedestrian corners and proposed full crossing bands; source service openings preserve pedestrian passage."
    return features, checks


def _steps(start, stop, step):
    while start < stop:
        yield start
        start += step
