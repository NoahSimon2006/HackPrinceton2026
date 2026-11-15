"""Revision-bound street concepts compiled locally from sourced road anchors.

This is deliberately separate from a simulated Proposal. Model-authored component
parameters become deterministic, checked GeoJSON; no traffic benefit is inferred.
"""
from __future__ import annotations

from copy import deepcopy
import json
import math
import re
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError
from shapely import unary_union
from shapely.geometry import LineString, Point, Polygon, mapping, shape
from shapely.ops import substring

from site_measurements import PROJECT, projected
from street_context import TO_GEO, canonical_hash, _geographic

LEGACY_VERSION = "road-concept-v1"
VERSION = "road-concept-v2"
KINDS = ("curb_extension", "crossing", "pedestrian_island", "bike_lane", "pedestrian_space", "lane_marking", "intersection_redesign")
LABELS = {"curb_extension": "Curb extension", "crossing": "Marked crossing", "pedestrian_island": "Pedestrian refuge island",
          "bike_lane": "Protected bicycle space", "pedestrian_space": "Pedestrian space", "lane_marking": "Lane separator", "intersection_redesign": "Intersection redesign"}
PHYSICAL = {"curb_extension", "pedestrian_island", "pedestrian_space"}


class ConceptPlacementError(ValueError):
    """Actionable placement or revision error safe for a tool response."""


class RoadComponent(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, allow_inf_nan=False)
    id: str = Field(pattern=r"^[a-z][a-z0-9-]{0,47}$")
    kind: Literal["curb_extension", "crossing", "pedestrian_island", "bike_lane", "pedestrian_space", "lane_marking", "intersection_redesign"]
    anchor_id: str = Field(pattern=r"^road-[a-f0-9]{12}$")
    side: Literal["left", "right", "center"] | None = None
    offset_m: float | None = Field(default=None, ge=0, le=400)
    length_m: float | None = Field(default=None, gt=0, le=150)
    width_m: float | None = Field(default=None, gt=0, le=40)
    label: str | None = Field(default=None, min_length=1, max_length=100)
    junction_id: str | None = Field(default=None, pattern=r"^junction-[a-f0-9]{12}$")
    layout: Literal["compact", "roundabout"] | None = None
    approach_length_m: float | None = Field(default=None, ge=15, le=60)
    curb_extension_m: float | None = Field(default=None, ge=.6, le=3)
    crossing_setback_m: float | None = Field(default=None, ge=2, le=10)
    crossing_width_m: float | None = Field(default=None, ge=2, le=5)


def _identity(identity):
    if (not isinstance(identity, dict) or set(identity) != {"site_id", "revision", "input_revision"}
            or not isinstance(identity["site_id"], str) or not 1 <= len(identity["site_id"]) <= 160
            or type(identity["revision"]) is not int or not 1 <= identity["revision"] <= 100
            or type(identity["input_revision"]) is not int or not 0 <= identity["input_revision"] <= 10000):
        raise ConceptPlacementError("The concept needs a valid site and project revision.")
    return dict(identity)


def _context(context):
    if not isinstance(context, dict) or context.get("status") != "ready" or not context.get("anchors"):
        raise ConceptPlacementError((context or {}).get("reason") or "Read a usable road alignment before drafting a concept.")
    try:
        stable = {k: v for k, v in context.items() if k not in ("context_hash", "model_context")}
        stable["sources"] = [{k: v for k, v in source.items() if k != "retrieved_at"} for source in stable["sources"]]
        if canonical_hash(stable) != context["context_hash"]:
            raise ValueError("hash")
        origin = context["origin"]
        lon, lat = origin["lon"], origin["lat"]
        if any(type(v) not in (float, int) or not math.isfinite(v) for v in (lon, lat)) or not (-118.67 <= lon <= -118.10 and 33.70 <= lat <= 34.35):
            raise ValueError("origin")
        point = Point(*PROJECT.transform(lon, lat))
        if not 1 <= len(context["anchors"]) <= 16:
            raise ValueError("anchors")
        seen = set()
        for anchor in context["anchors"]:
            if anchor["id"] in seen or not re.fullmatch(r"road-[a-f0-9]{12}", anchor["id"]):
                raise ValueError("anchor ID")
            seen.add(anchor["id"])
            line = projected(anchor["geometry"], ("LineString",))
            surface = projected(anchor["surface"], ("Polygon", "MultiPolygon"))
            if not point.buffer(1000).covers(line) or not point.buffer(1000).covers(surface):
                raise ValueError("extent")
            if not 1 <= anchor["width_m"] <= 40 or abs(line.length - anchor["length_m"]) > .01:
                raise ValueError("dimensions")
        return context
    except (KeyError, ValueError, TypeError, AttributeError) as error:
        raise ConceptPlacementError("The saved road context changed or is invalid. Refresh the road geometry before drafting.") from error


def _components(context, components, changes, previous, identity, *, legacy=False):
    anchors = {anchor["id"]: anchor for anchor in context["anchors"]}
    if (components is None) == (changes is None):
        raise ConceptPlacementError("Supply either complete components or named changes, never both.")
    if changes is not None:
        if not previous:
            raise ConceptPlacementError("There is no saved road concept to revise. Supply complete components.")
        saved = validate_road_concept(previous)
        if saved["site_id"] != identity["site_id"] or saved["revision"] >= identity["revision"]:
            raise ConceptPlacementError("Revise a prior concept from this same site.")
        if not isinstance(changes, list) or not 1 <= len(changes) <= 16:
            raise ConceptPlacementError("Supply one to sixteen explicit component changes.")
        values = {item["id"]: deepcopy(item) for item in saved["components"]}
        previous_anchors = {item["id"]: item for item in saved["context"]["anchors"]}
        seen, reanchored = set(), set()
        for change in changes:
            if not isinstance(change, dict):
                raise ConceptPlacementError("Each component change needs an id and an operation.")
            identifier, operation = change.get("id"), change.get("op")
            if identifier in seen:
                raise ConceptPlacementError("Change each component ID at most once per revision.")
            seen.add(identifier)
            if operation == "remove":
                if set(change) != {"id", "op"} or identifier not in values:
                    raise ConceptPlacementError("Remove an existing component by its exact ID.")
                del values[identifier]
            elif operation == "update":
                if identifier not in values or len(change) < 3:
                    raise ConceptPlacementError("Update an existing component and at least one parameter.")
                values[identifier].update({k: v for k, v in change.items() if k != "op"})
                if "anchor_id" in change or "junction_id" in change:
                    reanchored.add(identifier)
            elif operation == "add":
                if identifier in values:
                    raise ConceptPlacementError("New components need a new stable ID.")
                values[identifier] = {k: v for k, v in change.items() if k != "op"}
            else:
                raise ConceptPlacementError("Use change operation add, update or remove.")
        for old in saved["components"]:
            if old["id"] not in values or old["id"] in reanchored:
                continue
            before, after = previous_anchors.get(old["anchor_id"]), anchors.get(old["anchor_id"])
            fields = ("geometry", "width_m", "kind", "supported_kinds", "traffic_direction")
            if after is None or canonical_hash({key: before.get(key) for key in fields}) != canonical_hash({key: after.get(key) for key in fields}):
                raise ConceptPlacementError(f"The mapped road for this {LABELS[old['kind']].lower()} changed. Confirm realigning this feature to the updated road, or remove it. Other design choices will be preserved.")
            if old["kind"] == "intersection_redesign":
                old_junction = next((j for j in saved["context"].get("junctions", []) if j["id"] == old["junction_id"]), None)
                new_junction = next((j for j in context.get("junctions", []) if j["id"] == old["junction_id"]), None)
                if canonical_hash(old_junction) != canonical_hash(new_junction):
                    raise ConceptPlacementError("The sourced junction changed. Confirm its junction_id or anchor_id when revising the plan so the full intersection is rechecked.")
        components = list(values.values())
    if not isinstance(components, list) or not 1 <= len(components) <= 16:
        raise ConceptPlacementError("A road concept needs one to sixteen components.")
    normalized, seen = [], set()
    for raw in components:
        try:
            c = RoadComponent.model_validate(raw).model_dump()
        except ValidationError as error:
            first = error.errors()[0]
            raise ConceptPlacementError("Invalid component " + ".".join(map(str, first["loc"])) + ": " + first["msg"]) from error
        if c["id"] in seen:
            raise ConceptPlacementError("Each component must have a unique stable ID.")
        seen.add(c["id"])
        anchor = anchors.get(c["anchor_id"])
        if not anchor or c["kind"] not in anchor["supported_kinds"]:
            raise ConceptPlacementError(f"{c['id']}: choose a current road anchor supporting {c['kind']}.")
        if c["kind"] == "intersection_redesign":
            if legacy:
                raise ConceptPlacementError("Legacy concepts cannot contain intersection packages.")
            from junction_design import normalize_intersection
            try:
                normalized.append(normalize_intersection(context, c))
            except ValueError as error:
                raise ConceptPlacementError(str(error)) from error
            continue
        for key in ("junction_id", "layout", "approach_length_m", "curb_extension_m", "crossing_setback_m", "crossing_width_m"):
            if c.pop(key) is not None:
                raise ConceptPlacementError(f"{c['id']}: {key} is only supported by an intersection_redesign package.")
        marked = anchor["kind"] == "marked_crossing"
        defaults = {"curb_extension": (8., 2., "right"), "crossing": (3., anchor["width_m"], "center"),
                    "pedestrian_island": (6., 1.5, "center"), "bike_lane": (30., 1.8, "right"),
                    "pedestrian_space": (15., 2.5, "right"), "lane_marking": (25., .15, "center")}
        length, width, side = (anchor["length_m"], 3., "center") if marked else defaults[c["kind"]]
        c["length_m"] = float(length if c["length_m"] is None else c["length_m"])
        c["width_m"] = float(width if c["width_m"] is None else c["width_m"])
        c["side"] = c["side"] or side
        default_offset = 0. if marked else min(max(0., anchor["selection_offset_m"] + 5), max(0., anchor["length_m"] - c["length_m"]))
        c["offset_m"] = float(default_offset if c["offset_m"] is None else c["offset_m"])
        # Canonical text is deterministic. Arbitrary model labels could retain
        # live-feed observations despite the archive's scalar-only boundary.
        c["label"] = LABELS[c["kind"]]
        if c["offset_m"] + c["length_m"] > anchor["length_m"] + .01:
            raise ConceptPlacementError(f"{c['id']}: length and offset exceed this road anchor; use a shorter segment.")
        if marked:
            bounds = (2., 100., 1.5, 6.)
        else:
            bounds = {"curb_extension": (3., 30., .6, 4.), "crossing": (1.5, 6., 2., 40.),
                      "pedestrian_island": (2., 20., 1., 3.), "bike_lane": (5., 120., 1.2, 3.),
                      "pedestrian_space": (3., 100., 1., 6.), "lane_marking": (3., 120., .08, .3)}[c["kind"]]
        if not bounds[0] <= c["length_m"] <= bounds[1] or not bounds[2] <= c["width_m"] <= bounds[3]:
            raise ConceptPlacementError(f"{c['id']}: use length {bounds[0]:g}–{bounds[1]:g} m and width {bounds[2]:g}–{bounds[3]:g} m.")
        if c["kind"] in ("crossing", "pedestrian_island") and c["side"] != "center":
            raise ConceptPlacementError(f"{c['id']}: crossings and refuge islands use side center.")
        if c["kind"] in ("curb_extension", "bike_lane", "pedestrian_space") and c["side"] == "center":
            raise ConceptPlacementError(f"{c['id']}: choose the left or right road edge.")
        if c["kind"] == "crossing" and not marked and abs(c["width_m"] - anchor["width_m"]) > .05:
            raise ConceptPlacementError(f"{c['id']}: a crossing must span this {anchor['width_m']:g} m road corridor; omit width_m to use its width.")
        if c["kind"] in ("curb_extension", "bike_lane", "pedestrian_space") and anchor["width_m"] - c["width_m"] < 3:
            raise ConceptPlacementError(f"{c['id']}: retain at least a conceptual 3 m clear road corridor.")
        if c["kind"] == "pedestrian_island" and anchor["width_m"] - c["width_m"] < 6:
            raise ConceptPlacementError(f"{c['id']}: a center island needs room for a conceptual 3 m road corridor on each side.")
        normalized.append(c)
    if any(c["kind"] == "intersection_redesign" for c in normalized) and len(normalized) != 1:
        raise ConceptPlacementError("An intersection redesign is one coordinated package. Revise its parameters rather than stacking separate strips over the same intersection.")
    # Multiple individually valid edge strips must not jointly consume the road.
    for anchor_id in anchors:
        rows = [c for c in normalized if c["anchor_id"] == anchor_id and c["kind"] in ("curb_extension", "bike_lane", "pedestrian_space", "pedestrian_island")]
        breaks = sorted({p for c in rows for p in (c["offset_m"], c["offset_m"] + c["length_m"])})
        for left, right in zip(breaks, breaks[1:]):
            active = [c for c in rows if c["offset_m"] < (left + right) / 2 < c["offset_m"] + c["length_m"]]
            if anchors[anchor_id]["width_m"] - sum(c["width_m"] for c in active) < (6 if any(c["kind"] == "pedestrian_island" for c in active) else 3):
                raise ConceptPlacementError("Overlapping components leave too little clear road space; reduce widths or move a component.")
    return normalized


def _line_piece(anchor, c):
    line = projected(anchor["geometry"], ("LineString",))
    return substring(line, c["offset_m"], min(line.length, c["offset_m"] + c["length_m"]))


def _offset(line, value):
    result = line if abs(value) < .0001 else line.offset_curve(value)
    if result.geom_type != "LineString" or result.length < .5:
        raise ConceptPlacementError("This bend cannot support the requested width. Shorten the component or choose a straighter road anchor.")
    return result


def _rectangle(point, tangent, along, across, start=0., lateral=0.):
    tx, ty = tangent
    nx, ny = -ty, tx
    return Polygon([(point.x + tx * x + nx * y, point.y + ty * x + ny * y)
                    for x, y in ((start, lateral), (start + along, lateral), (start + along, lateral + across), (start, lateral + across))])


def _geometry(anchor, c):
    piece = _line_piece(anchor, c)
    if piece.geom_type != "LineString":
        raise ConceptPlacementError(f"{c['id']}: the selected road segment is too short.")
    kind, width = c["kind"], c["width_m"]
    if anchor["kind"] == "marked_crossing":
        footprint = piece.buffer(width / 2, cap_style="flat")
        stripes = [substring(piece, pos, min(piece.length, pos + .6)).buffer(width / 2, cap_style="flat")
                   for pos in _steps(.15, piece.length - .2, 1.2)]
        return footprint, stripes
    shift = 0.
    if c["side"] != "center":
        shift = (1 if c["side"] == "left" else -1) * (anchor["width_m"] / 2 - width / 2)
        if kind == "lane_marking":
            shift = (1 if c["side"] == "left" else -1) * max(0., anchor["width_m"] / 2 - 3.2)
    path = _offset(piece, shift)
    if kind == "pedestrian_island":
        if piece.length <= width:
            raise ConceptPlacementError(f"{c['id']}: make the island longer than its width.")
        inner = substring(path, width / 2, path.length - width / 2)
        footprint = inner.buffer(width / 2, cap_style="round")
    else:
        footprint = path.buffer(width / 2, cap_style="flat", join_style="round")
    markings = []
    if kind == "crossing":
        middle = piece.interpolate(piece.length / 2)
        a, b = piece.interpolate(0), piece.interpolate(piece.length)
        distance = a.distance(b)
        if distance < .5:
            raise ConceptPlacementError(f"{c['id']}: choose a straighter crossing location.")
        tangent = ((b.x - a.x) / distance, (b.y - a.y) / distance)
        markings = [_rectangle(middle, tangent, piece.length, min(.6, width / 2 - lateral),
                               start=-piece.length / 2, lateral=lateral).intersection(footprint)
                    for lateral in _steps(-width / 2 + .15, width / 2 - .2, 1.2)]
    elif kind == "bike_lane":
        # A solid inside boundary and repeated direction arrows are authored
        # markings in the supplied geometry, never synthesized by the frontend.
        sign = 1 if c["side"] == "left" else -1
        boundary = _offset(piece, shift - sign * (width / 2 - .10))
        markings.append(boundary.buffer(.075, cap_style="flat").intersection(footprint))
        for pos in _steps(min(5., path.length / 2), path.length - 1., 14.):
            center = path.interpolate(pos)
            a, b = path.interpolate(max(0, pos - .5)), path.interpolate(min(path.length, pos + .5))
            distance = a.distance(b)
            if distance < .2:
                continue
            tx, ty = (b.x - a.x) / distance, (b.y - a.y) / distance
            if c["side"] == "left" and anchor.get("traffic_direction") == "two_way":
                tx, ty = -tx, -ty
            nx, ny = -ty, tx
            arrow = Polygon([(center.x + tx * x + nx * y, center.y + ty * x + ny * y) for x, y in
                             ((-1., -.12), (.2, -.12), (.2, -.4), (1., 0.), (.2, .4), (.2, .12), (-1., .12))])
            markings.append(arrow.intersection(footprint))
    elif kind == "lane_marking":
        dashed = [substring(path, pos, min(path.length, pos + 3.)).buffer(width / 2, cap_style="flat")
                  for pos in _steps(0., path.length - .05, 6.)]
        footprint = unary_union(dashed)
    return footprint, markings


def _steps(start, stop, step):
    while start < stop:
        yield start
        start += step


def _constraint_context(context, markings, evidence):
    result = {"keep_clear": deepcopy(context.get("keep_clear", [])), "crossings": deepcopy(context.get("crossings", [])),
              "buildings": [], "building_source_status": "unavailable", "guidance": []}
    if markings:
        for i, item in enumerate(markings):
            if item.get("kind") in ("access", "crossing"):
                collection = "keep_clear" if item["kind"] == "access" else "crossings"
                geometry = projected(item.get("geometry"), ("Polygon",) if collection == "keep_clear" else ("LineString",))
                normalized = _geographic(geometry)
                if not any(old["geometry"] == normalized for old in result[collection]):
                    result[collection].append({"type": "Feature", "id": f"current-{collection}-{i}", "geometry": normalized, "properties": {"kind": item["kind"]}})
    if isinstance(evidence, dict):
        outlines = evidence.get("outlines")
        if isinstance(outlines, list):
            result["building_source_status"] = "available"
            for i, item in enumerate(outlines[:200]):
                if item.get("properties", {}).get("label") != "Building footprint":
                    continue
                try:
                    geometry = projected(item.get("geometry"), ("Polygon", "MultiPolygon"))
                except ValueError:
                    result["building_source_status"] = "partial"
                    continue
                result["buildings"].append({"type": "Feature", "id": f"building-{i}", "geometry": _geographic(geometry),
                                            "properties": {"label": "Mapped building footprint"}})
        for item in (evidence.get("designGuidance") or [])[:12]:
            if isinstance(item, dict):
                result["guidance"].append({k: str(item[k])[:500] for k in ("id", "provider", "url", "title") if item.get(k)})
    return result


def _compile_legacy(context, components, constraints, revision):
    anchors = {anchor["id"]: anchor for anchor in context["anchors"]}
    rows = []
    clear = unary_union([projected(f["geometry"]) for f in constraints["keep_clear"]])
    buildings = unary_union([projected(f["geometry"]) for f in constraints["buildings"]])
    crossings = unary_union([projected(f["geometry"], ("LineString",)).buffer(1.5) for f in constraints["crossings"]])
    origin = Point(*PROJECT.transform(context["origin"]["lon"], context["origin"]["lat"]))
    for c in components:
        anchor = anchors[c["anchor_id"]]
        footprint, markings = _geometry(anchor, c)
        if footprint.is_empty or not footprint.is_valid or footprint.area < .05 or not origin.buffer(1000).covers(footprint):
            raise ConceptPlacementError(f"{c['id']}: this geometry could not be placed within the selected site.")
        if anchor["kind"] == "road":
            surface = projected(anchor["surface"], ("Polygon", "MultiPolygon"))
            if footprint.difference(surface.buffer(.15)).area > .1:
                raise ConceptPlacementError(f"{c['id']}: the component extends beyond the mapped road corridor. Reduce its width or length.")
        if not clear.is_empty and footprint.intersection(clear).area > .01:
            raise ConceptPlacementError(f"{c['id']}: this placement overlaps a marked keep-clear area. Move or shorten it.")
        if not buildings.is_empty and footprint.intersection(buildings).area > .05:
            raise ConceptPlacementError(f"{c['id']}: this placement overlaps a mapped building. Choose another road segment.")
        if c["kind"] in PHYSICAL and not crossings.is_empty and footprint.intersection(crossings).area > .05:
            raise ConceptPlacementError(f"{c['id']}: preserve the marked crossing corridor by moving or shortening this physical component.")
        for other, other_shape, _ in rows:
            if c["kind"] != "crossing" and other["kind"] != "crossing" and c["kind"] != "lane_marking" and other["kind"] != "lane_marking" and footprint.intersection(other_shape).area > .1:
                raise ConceptPlacementError(f"{c['id']}: it overlaps {other['id']}. Separate the components or revise their widths.")
        rows.append((c, footprint, markings))
    physical = unary_union([footprint for c, footprint, _ in rows if c["kind"] in PHYSICAL])
    features, measured = [], []
    for c, footprint, markings in rows:
        if c["kind"] == "crossing" and not physical.is_empty:
            footprint = footprint.difference(physical)
            markings = [mark.difference(physical) for mark in markings]
        if footprint.is_empty or footprint.area < .05:
            raise ConceptPlacementError(f"{c['id']}: no crossing space remains outside the physical design.")
        def feature(geometry, identifier, role):
            if geometry.is_empty or geometry.area < .005:
                return
            if geometry.geom_type not in ("Polygon", "MultiPolygon") or not geometry.is_valid:
                raise ConceptPlacementError(f"{c['id']}: the marking geometry is invalid.")
            features.append({"type": "Feature", "id": identifier, "geometry": _geographic(geometry),
                             "properties": {"component_id": c["id"], "kind": c["kind"], "label": c["label"],
                                            "role": role, "revision": revision}})
        feature(footprint, c["id"] + "-footprint", "proposed")
        for i, mark in enumerate(markings):
            feature(mark, f"{c['id']}-marking-{i + 1}", "marking")
        measured.append({"component_id": c["id"], "area_m2": round(footprint.area, 3),
                         "road_fit": "checked" if anchors[c["anchor_id"]]["kind"] == "road" else "user_marked_alignment",
                         "keep_clear": "checked" if constraints["keep_clear"] else "no_markings",
                         "building_overlap": "checked" if constraints["building_source_status"] == "available" else "unassessed"})
    return features, measured



def _compile(context, components, constraints, revision, *, legacy=False):
    if not legacy and components[0]["kind"] == "intersection_redesign":
        from junction_design import compile_intersection
        try:
            features, checks = compile_intersection(context, components[0], constraints, revision)
        except ValueError as error:
            raise ConceptPlacementError(str(error)) from error
        return features, [checks]
    # All contexts returned by the new source reader include junction metadata.
    # Bare pre-junction contexts remain replayable for archived v1 concepts.
    if not legacy and "junctions" in context:
        for c in components:
            anchor = next(a for a in context["anchors"] if a["id"] == c["anchor_id"])
            if c["kind"] != "crossing" or anchor["kind"] == "marked_crossing":
                continue
            approaches = [a for j in context["junctions"] for a in j["approaches"] if a["anchor_id"] == c["anchor_id"]]
            if not any(abs(c["offset_m"]-a.get("crossing_offset_m", -100)) <= 4 for a in approaches):
                raise ConceptPlacementError("A crossing needs a sourced junction mouth with connected landings or an explicit user-marked crossing. Use intersection_redesign to draw the full intersection.")
    return _compile_legacy(context, components, constraints, revision)


def build_road_concept(context, components=None, *, changes=None, previous=None, identity,
                       markings=None, evidence=None):
    """Compile a full concept or apply explicit stable-ID add/update/remove edits."""
    identity = _identity(identity)
    context = deepcopy(_context(context))
    normalized = _components(context, components, changes, previous, identity)
    constraints = _constraint_context(context, markings, evidence)
    features, checks = _compile(context, normalized, constraints, identity["revision"])
    parent = None
    if previous:
        previous = validate_road_concept(previous)
        if previous["site_id"] != identity["site_id"] or previous["revision"] >= identity["revision"]:
            raise ConceptPlacementError("A concept revision must follow an earlier design from the same site.")
        parent = {"revision": previous["revision"], "input_hash": previous["input_hash"]}
    result = {"schema_version": 1, "compiler_version": VERSION, **identity, "workflow": "street",
              "status": "conceptual", "context_hash": context["context_hash"], "parent": parent,
              "components": normalized, "geometry": features, "context": context, "constraints": constraints,
              "sources": deepcopy(context["sources"]) + deepcopy(constraints["guidance"]),
              "assumptions": [*context["assumptions"], *dict.fromkeys(anchor["width_basis"] for anchor in context["anchors"] if anchor["id"] in {c["anchor_id"] for c in normalized}),
                              "Proposed dimensions and a minimum clear corridor are screening choices, not adopted engineering standards.",
                              "Road-side placement and source widths require field checks; no turn paths, parking demand, utilities or traffic signals are modeled.",
                              "Bicycle arrows illustrate right-hand traffic along the source alignment; verify permitted travel direction before use.",
                              *(["The compact intersection proposes one through lane in each direction; any former parking or extra lane space is shown as proposed pedestrian space. Capacity and parking impacts are unassessed.",
                                 "Curb extension is a requested maximum. Checked effective dimensions may be smaller to preserve the source corridor and two conceptual 3 m through lanes.",
                                 "The conceptual pedestrian path and crossing landing screening minimum is 1.2 m. This design choice is not an accessibility compliance assessment or adopted local standard.",
                                 "Crossings join proposed pedestrian landings within the source street envelope. Mapped walking paths locate the envelope; exact curb positions and accessibility need a field survey."] if any(c["kind"] == "intersection_redesign" for c in normalized) else [])],
              "checks": checks, "evaluation": {"status": "unassessed", "reference": None,
                                                "reason": "Spatial concept only; traffic performance, emissions and safety benefits have not been evaluated."}}
    result = json.loads(json.dumps(result, allow_nan=False))
    result["input_hash"] = canonical_hash(result)
    return result


def validate_road_concept(value, identity=None):
    """Revalidate hash, source context and deterministic geometry before publication."""
    try:
        if not isinstance(value, dict) or set(value) != {"schema_version", "compiler_version", "site_id", "revision", "input_revision", "workflow", "status", "context_hash", "parent", "components", "geometry", "context", "constraints", "sources", "assumptions", "checks", "evaluation", "input_hash"}:
            raise ValueError("fields")
        own = _identity({key: value[key] for key in ("site_id", "revision", "input_revision")})
        if identity is not None and own != _identity(identity):
            raise ConceptPlacementError("The concept does not match this saved project revision.")
        if value["schema_version"] != 1 or value["compiler_version"] not in (VERSION, LEGACY_VERSION) or value["workflow"] != "street" or value["status"] != "conceptual":
            raise ValueError("schema")
        digest = canonical_hash({key: item for key, item in value.items() if key != "input_hash"})
        if digest != value["input_hash"] or not re.fullmatch(r"[a-f0-9]{64}", value["input_hash"]):
            raise ValueError("hash")
        context = _context(value["context"])
        if context["context_hash"] != value["context_hash"]:
            raise ValueError("context")
        legacy = value["compiler_version"] == LEGACY_VERSION
        normalized = _components(context, value["components"], None, None, own, legacy=legacy)
        if normalized != value["components"]:
            raise ValueError("components")
        features, checks = _compile(context, normalized, value["constraints"], own["revision"], legacy=legacy)
        if canonical_hash(features) != canonical_hash(value["geometry"]) or checks != value["checks"]:
            raise ValueError("geometry")
        if value["evaluation"] != {"status": "unassessed", "reference": None, "reason": "Spatial concept only; traffic performance, emissions and safety benefits have not been evaluated."}:
            raise ValueError("evaluation")
        parent = value["parent"]
        if parent is not None and (set(parent) != {"revision", "input_hash"} or type(parent["revision"]) is not int or not 1 <= parent["revision"] < own["revision"] or not re.fullmatch(r"[a-f0-9]{64}", parent["input_hash"])):
            raise ValueError("parent")
        return deepcopy(value)
    except ConceptPlacementError:
        raise
    except (ValueError, TypeError, KeyError, AttributeError) as error:
        raise ConceptPlacementError("The saved road concept is invalid or changed after publication.") from error


def concept_model_summary(concept):
    """Curated tool handback: never include geometry, origin, street names or URLs."""
    return {"status": concept["status"], "revision": concept["revision"], "input_hash": concept["input_hash"],
            "context_hash": concept["context_hash"], "components": [{k: v for k, v in c.items() if k != "label"} for c in concept["components"]],
            "checks": deepcopy(concept["checks"]), "evaluation": deepcopy(concept["evaluation"]),
            "summary": "Saved a geographically aligned conceptual street layout. These are proposed dimensions; no traffic or emissions benefits were calculated."}
