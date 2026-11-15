"""Local conceptual scenes derived only from canonically saved 2D designs.

This renderer adapter makes no provider requests and does not alter a design,
performance result, source record, or project. Elevations remain illustrative.
"""
from copy import deepcopy
from datetime import date
import math
import re

from shapely.affinity import translate
from shapely.geometry import Point, box, mapping, shape as read_shape
from shapely.ops import unary_union

from proposal import Proposal
from site_measurements import PROJECT, projected


class SceneUnavailable(ValueError):
    pass


def parse_scene_query(query):
    keys = {"projectId", "revision", "inputHash", "geometryId"}
    if set(query) != keys or any(not isinstance(v, list) or len(v) != 1 for v in query.values()):
        raise SceneUnavailable("Choose one saved design before opening its conceptual scene.")
    values = {key: value[0] for key, value in query.items()}
    if (not all(isinstance(value, str) for value in values.values())
            or not re.fullmatch(r"[a-f0-9]{32}", values["projectId"])
            or not re.fullmatch(r"[a-f0-9]{64}", values["inputHash"])
            or not re.fullmatch(r"[1-9][0-9]{0,2}", values["revision"])
            or int(values["revision"]) > 100
            or not 1 <= len(values["geometryId"]) <= 160):
        raise SceneUnavailable("The saved design reference is invalid.")
    return {"project_id": values["projectId"], "revision": int(values["revision"]),
            "input_hash": values["inputHash"], "geometry_id": values["geometryId"]}


def _candidates(record):
    if not isinstance(record, dict):
        return
    if isinstance(record.get("proposal"), dict):
        yield None, record["proposal"]
    alternatives = record.get("alternatives")
    if isinstance(alternatives, dict):
        for name, candidate in alternatives.items():
            if isinstance(candidate, dict):
                yield name, candidate


def _resolve(project, revision, input_hash, geometry_id):
    snapshot = project.get("snapshot") or {}
    current = project.get("result")
    records = []
    if isinstance(current, dict) and not current.get("analysisError"):
        records.append((current, project.get("status") not in ("failed", "canceled", "interrupted")))
    history_key = "designHistory" if snapshot.get("workflow") == "water" else "trafficDesignHistory"
    records.extend((record, False) for record in project.get(history_key, []) if isinstance(record, dict))
    for record, is_current in records:
        for name, candidate in _candidates(record):
            if (candidate.get("revision") != revision or candidate.get("input_hash") != input_hash
                    or not candidate.get("proposed_geometry_ids")
                    or candidate["proposed_geometry_ids"][0] != geometry_id):
                continue
            try:
                proposal = Proposal.model_validate(candidate)
            except ValueError as error:
                raise SceneUnavailable("The stored design could not be validated for a scene.") from error
            if (proposal.development_fixture or proposal.site_id != snapshot.get("siteId")
                    or proposal.workflow != snapshot.get("workflow")
                    or proposal.revision > snapshot.get("proposalRevision", 0)
                    or proposal.input_revision > snapshot.get("inputRevision", -1)):
                raise SceneUnavailable("The stored design does not belong to this planning site.")
            return proposal, record, name, is_current
    raise SceneUnavailable("That saved design is no longer available. Reopen a saved evaluation or analyze the site.")


def _scene_status(proposal, record, alternative_name):
    # Stormwater alternatives retain a valid conditional Proposal even when the
    # study rejects their fit. Keep that canonical study verdict in the scene.
    if proposal.workflow == "water":
        results = ((record.get("waterPlan") or {}).get("comparison") or {}).get("results", [])
        for entry in results:
            if (isinstance(entry, dict) and entry.get("id") in (alternative_name, proposal.proposed_geometry_ids[0])
                    and entry.get("inputHash") == proposal.input_hash and entry.get("revision") == proposal.revision
                    and entry.get("status") == "rejected"):
                return "rejected"
    return proposal.status


def _polygons(geometry):
    if geometry.geom_type in ("Polygon", "MultiPolygon"):
        return geometry
    parts = [g for g in getattr(geometry, "geoms", ()) if g.geom_type in ("Polygon", "MultiPolygon")]
    return unary_union(parts) if parts else None


def _outline_source(properties):
    collection = properties.get("collection")
    if (not isinstance(collection, str) or not 1 <= len(collection) <= 160
            or any(ord(character) < 32 for character in collection)):
        collection = None
    observed = properties.get("date")
    try:
        observed = date.fromisoformat(observed).isoformat() if isinstance(observed, str) else None
    except ValueError:
        observed = None
    return {"provider": "Vexcel", "collection": collection, "date": observed}


def build_scene(project, revision, input_hash, geometry_id):
    """Return a meter-based scene for one exact stored proposal or alternative."""
    if (isinstance(revision, bool) or not isinstance(revision, int) or not 1 <= revision <= 100
            or not isinstance(input_hash, str) or not re.fullmatch(r"[a-f0-9]{64}", input_hash)
            or not isinstance(geometry_id, str) or not 1 <= len(geometry_id) <= 160):
        raise SceneUnavailable("The saved design reference is invalid.")
    proposal, record, alternative, is_current = _resolve(project, revision, input_hash, geometry_id)
    snapshot = project["snapshot"]
    lon, lat = snapshot.get("lon"), snapshot.get("lat")
    if (any(isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v) for v in (lon, lat))
            or not -118.67 <= lon <= -118.10 or not 33.70 <= lat <= 34.35):
        raise SceneUnavailable("The saved site has no valid local scene origin.")
    east, north = PROJECT.transform(lon, lat)
    origin = Point(east, north)
    proposed_ids = set(proposal.proposed_geometry_ids)
    features, intervention = [], []
    for feature in proposal.geometry:
        if feature.id in proposed_ids:
            kind = "intervention"
        elif feature.properties.get("role") == "contributing":
            kind = "contributing"
        else:
            continue
        shape = projected(feature.geometry, kinds=("Polygon", "MultiPolygon"))
        if not origin.buffer(1000).covers(shape):
            raise SceneUnavailable("The saved footprint exceeds the local scene area.")
        if kind == "intervention":
            intervention.append(shape)
        if kind == "contributing":
            height, basis = 0, "Mapped contributing area only; terrain and hydraulic connection are not inferred."
        elif proposal.workflow == "water":
            height = proposal.design.storage_depth_m
            basis = "Assumed effective ponding depth; illustrative section, not surveyed elevation or excavation depth."
        else:
            height, basis = .15, "Illustrative 0.15 m platform, not a measured or engineered curb height."
        features.append({"id": feature.id, "kind": kind,
                         "geometry": mapping(translate(shape, xoff=-east, yoff=-north)),
                         "heightM": height, "heightBasis": basis})
    if not intervention:
        raise SceneUnavailable("This design has no polygon footprint to render.")
    footprint = unary_union(intervention)
    area = next((m for m in proposal.metrics if m.id == "footprint_area"), None)
    # Traffic publications round square meters to tenths; stormwater to .001.
    tolerance = .050001 if proposal.workflow == "street" else .000501
    if (area is None or area.unit != "m²" or area.status != "calculated" or area.proposed is None
            or area.proposed <= 0 or abs(footprint.area - area.proposed) > tolerance):
        raise SceneUnavailable("The saved footprint and its authoritative area do not agree.")
    focus = translate(footprint, xoff=-east, yoff=-north)
    clip = box(*footprint.bounds).buffer(35, join_style=2)
    source_context = record.get("evidence") if is_current else None
    outlines = source_context.get("outlines") if isinstance(source_context, dict) else []
    outlines = outlines if isinstance(outlines, list) else []
    context_features, context_sources = [], {}
    for i, feature in enumerate(outlines[:200]):
        if not isinstance(feature, dict):
            continue
        properties = feature.get("properties")
        label = properties.get("label") if isinstance(properties, dict) else None
        kind = {"Parcel boundary": "parcel", "Building footprint": "building"}.get(label)
        if not kind:
            continue
        try:
            shape = _polygons(projected(feature.get("geometry"), kinds=("Polygon", "MultiPolygon")).intersection(clip))
        except (ValueError, TypeError, KeyError):
            continue
        if shape is None or shape.is_empty or shape.area <= 0:
            continue
        context_features.append({"id": f"context-{kind}-{i}", "kind": kind,
            "geometry": mapping(translate(shape, xoff=-east, yoff=-north)),
            "heightM": 6 if kind == "building" else 0,
            "heightBasis": "Illustrative 6 m height; only the mapped building footprint is sourced." if kind == "building"
                else "Mapped parcel outline; no ownership or terrain elevation inferred."})
        source = _outline_source(properties)
        context_sources[(source["collection"], source["date"])] = source
        if len(context_features) == 80:
            break
    features.extend(context_features)
    matched = bool(context_features)
    context = {"status": "matched" if matched else "unavailable",
        "sources": list(context_sources.values()),
        "message": "Surroundings use this evaluation's mapped outlines, clipped near the design. Building heights are illustrative."
            if matched else "No matching saved surroundings are available for this revision; only its exact design footprint is shown."}
    bounds = list(focus.bounds)
    for feature in context_features:
        # These coordinates are already local meters; use no additional CRS transform.
        b = read_shape(feature["geometry"]).bounds
        bounds = [min(bounds[0], b[0]), min(bounds[1], b[1]), max(bounds[2], b[2]), max(bounds[3], b[3])]
    return {"schemaVersion": 1,
        "identity": {"projectId": project["id"], "siteId": proposal.site_id, "workflow": proposal.workflow,
            "revision": proposal.revision, "inputRevision": proposal.input_revision,
            "inputHash": proposal.input_hash, "geometryId": geometry_id},
        "origin": {"crs": "EPSG:32611", "easting": east, "northing": north, "lon": lon, "lat": lat},
        "units": "m", "design": proposal.design.model_dump(mode="json"),
        "status": _scene_status(proposal, record, alternative), "savedAt": record.get("savedAt"),
        "areaM2": area.proposed, "geometryAreaM2": footprint.area,
        "metrics": [m.model_dump(mode="json") for m in proposal.metrics],
        "bounds": bounds, "focusBounds": list(focus.bounds), "features": features, "context": context,
        "assumptions": ["Conceptual comparison from the same saved 2D footprint; no new performance evaluation is run.",
            "Flat reference ground, illustrative materials and no surveyed terrain or registered Matterport scan.",
            "Full road-surface geometry is not supplied by this saved design; unspecified surroundings are omitted.",
            "Existing and proposed views share one local origin, scale and camera.",
            *deepcopy(proposal.assumptions)]}
