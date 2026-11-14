"""Bounded street layouts: SUMO network patches, map geometry and sponsor-evidence checks.

A layout is a small set of parameters the agent may choose. Python turns it into:
- an edge patch for SUMO (so the traffic effect is simulated, not guessed);
- WGS84 GeoJSON drawn from the simulated network's own lane shapes;
- parcel and building overlap areas (Vexcel outlines) and access conflicts (CoStar
  frontages with reported curb cuts), measured in UTM 11N.
Ranking applies fixed eligibility rules and CO2-first weights; nothing is tuned per run.
"""
from __future__ import annotations

from typing import Literal
import math
import xml.etree.ElementTree as ET

from pydantic import BaseModel, ConfigDict, Field
from pyproj import Transformer
from shapely import transform, unary_union
from shapely.geometry import LineString, mapping, shape

TO_UTM = Transformer.from_crs(4326, 32611, always_xy=True)
TO_GEO = Transformer.from_crs(32611, 4326, always_xy=True)
LANE_WIDTH_M = 3.2
USES = {"curb_extension": "Planted curb extension", "bike_lane": "Protected bike lane", "bus_lane": "Bus-only lane",
        "pedestrian_space": "Widened sidewalk"}
WEIGHTS = {"co2": .50, "delay": .20, "queue": .10, "parcel_overlap": .10, "noise": .05, "access": .05}
MIN_COMPLETION = .98
MAX_UNABLE_TO_ENTER = .02
TRADEOFF = .10


class Layout(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str = Field(pattern=r"^[a-z0-9-]{2,32}$")
    kind: Literal["lane_reallocation"]
    approach: Literal["nb", "sb", "eb", "wb"]
    lanes_removed: int = Field(ge=1, le=2)
    length_m: float = Field(ge=20, le=200, description="Length of approach converted, measured back from the stop line.")
    new_use: Literal["curb_extension", "bike_lane", "bus_lane", "pedestrian_space"]


def describe(layout: Layout, lanes_before: int) -> str:
    return (f"Convert {layout.lanes_removed} of {lanes_before} {layout.approach.upper()} approach lane"
            f"{'s' if lanes_before != 1 else ''} to {USES[layout.new_use].lower()} for the last {layout.length_m:.0f} m before the stop line.")


def edge_patch(layout: Layout, study) -> str:
    """Reallocate exactly the displayed length and explicitly remove the curb-side lane indices."""
    approach = study.mapping.get(layout.approach)
    if approach is None:
        raise ValueError(f"The {layout.approach.upper()} approach does not exist at this intersection.")
    if layout.new_use == "bus_lane":
        raise ValueError("Bus-only operation is not implemented; select a nonmotorized space reallocation.")
    if sum(edge.getLength() for edge in approach["chain"]) + .01 < layout.length_m:
        raise ValueError("The requested length extends beyond the measured approach chain.")
    root, remaining = ET.Element("edges"), layout.length_m
    for edge in reversed(approach["chain"]):
        if remaining <= 0:
            break
        lanes = edge.getLaneNumber() - layout.lanes_removed
        if lanes < 1:
            raise ValueError("A layout must leave at least one general traffic lane.")
        row = ET.SubElement(root, "edge", id=edge.getID())
        attributes = {"pos": "0" if remaining >= edge.getLength() - .01 else f"{-remaining:.6f}",
                      "lanes": " ".join(str(i) for i in range(layout.lanes_removed, edge.getLaneNumber()))}
        if attributes["pos"] != "0":
            attributes.update(idBefore=f"{edge.getID()}.cp4-before", idAfter=edge.getID(), type="priority")
        ET.SubElement(row, "split", attributes)
        remaining -= edge.getLength()
    return ET.tostring(root, encoding="unicode")


def footprint(layout: Layout, study):
    """Polygon (UTM 11N) covering the curb-side lanes removed, from the network's lane shapes."""
    net = study.net
    approach = study.mapping[layout.approach]
    pieces, remaining = [], layout.length_m
    for edge in reversed(approach["chain"]):
        if remaining <= 0:
            break
        for lane in edge.getLanes()[:layout.lanes_removed]:  # index 0 is the curb-side lane in SUMO
            coords = [TO_UTM.transform(*net.convertXY2LonLat(x, y)) for x, y in lane.getShape()]
            line = LineString(coords)
            # SUMO's position uses edge length; preserve that fraction on the projected lane shape.
            selected_length = line.length * min(1.0, remaining / edge.getLength())
            if selected_length < line.length:
                from shapely.ops import substring
                line = substring(line, line.length - selected_length, line.length)
            pieces.append(line.buffer(lane.getWidth() / 2 or LANE_WIDTH_M / 2, cap_style="flat"))
        remaining -= edge.getLength()
    return unary_union(pieces)


def to_geojson(geometry, **properties):
    return {"type": "Feature", "geometry": mapping(transform(geometry, TO_GEO.transform, interleaved=False)),
            "properties": properties}


def utm(geometry: dict):
    from site_measurements import projected
    return projected(geometry, kinds=("Polygon", "MultiPolygon", "LineString"))


def sponsor_checks(design, outlines: list | None, frontages: list | None) -> dict:
    """Measure overlap with Vexcel parcels/buildings and conflicts with CoStar curb cuts. None = unassessed."""
    result = {"parcel_overlap_m2": None, "building_overlap_m2": None, "access_conflicts": None,
              "parcel_evidence": [], "access_evidence": []}
    if outlines:
        parcels, buildings = [], []
        for feature in outlines:
            try:
                geometry = utm(feature["geometry"])
            except (ValueError, KeyError, TypeError):
                continue
            label = feature.get("properties", {}).get("label")
            if label not in ("Parcel boundary", "Building footprint"):
                continue
            target = parcels if label == "Parcel boundary" else buildings
            target.append((feature["properties"].get("evidenceId"), geometry))
        if parcels:
            result["parcel_overlap_m2"] = round(design.intersection(unary_union([g for _, g in parcels])).area, 2)
        if buildings:
            result["building_overlap_m2"] = round(design.intersection(unary_union([g for _, g in buildings])).area, 2)
        result["parcel_evidence"] = [i for i, g in parcels + buildings if design.intersection(g).area > .05 and i]
    if frontages:
        conflicts, assessed = [], 0
        for frontage in frontages:
            if frontage.get("curbCuts") is None:
                continue
            try:
                line = utm(frontage["geometry"])
            except (ValueError, KeyError, TypeError):
                continue
            assessed += 1
            if frontage["curbCuts"] > 0 and design.distance(line) <= 3.0:
                conflicts.append(frontage.get("evidenceId"))
        if assessed == len(frontages):
            result["access_conflicts"] = len(conflicts)
        result["access_evidence"] = [c for c in conflicts if c]
    return result


def rank(results: dict, checks: dict, keep_clear: list | None = None, *, policy=None) -> dict:
    """User-approved strict gates, followed by CO₂-first ranking among fully assessed layouts."""
    if policy not in (None, "strict", "strict-v1", "strict-total-co2-v1"):
        raise ValueError("Only the user-approved strict traffic policy is supported.")
    base = results["baseline"]
    verdicts = {}

    def finite(value):
        return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)

    def relative(before, after):
        if not finite(before) or not finite(after) or before < 0 or after < 0:
            return None
        return (after - before) / before if before else (0.0 if after == 0 else None)

    def worst_approach(before, after, *, energy=False):
        if not before or before.keys() != after.keys():
            return None
        changes = []
        for name, value in before.items():
            other = after[name]
            if not finite(value) or not finite(other):
                return None
            change = 10 ** ((other - value) / 10) - 1 if energy else relative(value, other)
            if change is None:
                return None
            changes.append(change)
        return max(changes)

    for name, metrics in results.items():
        if name == "baseline":
            continue
        reasons, check = [], checks.get(name, {})
        completion, base_completion = metrics.get("completion_share"), base.get("completion_share")
        if not finite(completion) or not finite(base_completion) or base_completion <= 0:
            reasons.append("trip completion is unavailable")
        elif completion < MIN_COMPLETION * base_completion:
            reasons.append("completes less than 98% of baseline completed demand")
        unable, base_unable = metrics.get("unable_to_enter_share"), base.get("unable_to_enter_share")
        if not finite(unable) or not finite(base_unable):
            reasons.append("entry-failure accounting is unavailable")
        elif unable > base_unable + MAX_UNABLE_TO_ENTER + 1e-9:
            reasons.append("entry failures exceed baseline by more than 2 percentage points")
        if metrics.get("teleports", 0) or base.get("teleports", 0):
            reasons.append("teleported vehicles invalidate the comparison")
        for field, label in (("parcel_overlap_m2", "parcel overlap"), ("building_overlap_m2", "building overlap"),
                             ("access_conflicts", "property access")):
            if check.get(field) is None:
                reasons.append(f"{label} remains unassessed")
        if check.get("building_overlap_m2", 0):
            reasons.append(f"overlaps mapped buildings by {check['building_overlap_m2']} m²")
        if check.get("keep_clear_conflict"):
            reasons.append("crosses a planner keep-clear area")
        if check.get("marked_crossing_conflict"):
            reasons.append("crosses a planner-marked crossing")
        for field, label in (("candidate_crosswalk_overlaps", "crosswalk"), ("candidate_driveway_overlaps", "driveway")):
            if check.get(field):
                reasons.append(f"overlaps an unverified {label} candidate; verify its location and access before recommending")
        changes = {
            "co2": relative(base.get("co2_kg_per_hour"), metrics.get("co2_kg_per_hour")),
            "delay": relative(base.get("mean_delay_s"), metrics.get("mean_delay_s")),
            "queue": worst_approach(base.get("max_queue_m", {}), metrics.get("max_queue_m", {})),
        }
        changes["noise"] = worst_approach(base.get("max_noise_db", {}), metrics.get("max_noise_db", {}), energy=True)
        if changes["co2"] is None or changes["co2"] >= 0:
            reasons.append("total CO₂ does not improve on the same offered-trip cohort")
        for key in ("delay", "queue", "noise"):
            if changes[key] is None:
                reasons.append(f"{key} comparison is unavailable")
            elif changes[key] > TRADEOFF + 1e-9:
                unit = " sound energy" if key == "noise" else ""
                reasons.append(f"{key}{unit} worsens by more than 10%")
        changes["parcel_overlap"] = (min(1.0, check["parcel_overlap_m2"] / 50)
                                      if check.get("parcel_overlap_m2") is not None else None)
        changes["access"] = (min(1.0, check["access_conflicts"] / 2)
                             if check.get("access_conflicts") is not None else None)
        score = -sum(WEIGHTS[k] * v for k, v in changes.items()) if all(v is not None for v in changes.values()) else None
        verdicts[name] = {"eligible": not reasons, "ineligible_reasons": reasons,
                          "score": round(score, 4) if score is not None else None,
                          "changes": {k: round(v, 4) if v is not None else None for k, v in changes.items()},
                          "tradeoffs": [k for k in ("delay", "queue", "noise", "co2") if changes[k] is not None and changes[k] > 0]}
    eligible = [n for n, v in verdicts.items() if v["eligible"]]
    best = max(eligible, key=lambda n: verdicts[n]["score"], default=None)
    recommended = best if best and verdicts[best]["score"] > 0 else None
    return {"verdicts": verdicts, "recommended": recommended, "policy": "strict-v1",
            "noise_rule": "At most 10% increase in sound energy (approximately 0.414 dB), not 10% of a dB reading.",
            "reason": None if recommended else
            ("No tested layout passes the strict rules with complete evidence." if not eligible else
             "No eligible layout scores better than today's layout on the CO₂-first ranking.")}


def evaluate(study, layouts: list[Layout], outlines=None, frontages=None, keep_clear=None, *, activity=None, policy=None, extra_checks=None) -> dict:
    """Simulate baseline plus layouts with paired seeds, measure footprints and checks, rank."""
    if not 1 <= len(layouts) <= 3 or len({l.name for l in layouts}) != len(layouts):
        raise ValueError("Evaluate one to three uniquely named layouts.")
    patches, shapes, checks, descriptions = {}, {}, {}, {}
    zones = []
    for area in keep_clear or []:
        try:
            zones.append(utm(area))
        except ValueError as error:
            raise ValueError("A planner keep-clear area is invalid; correct it before comparison.") from error
    for layout in layouts:
        if activity is not None:
            activity.check()
        patches[layout.name] = edge_patch(layout, study)
        shapes[layout.name] = footprint(layout, study)
        checks[layout.name] = sponsor_checks(shapes[layout.name], outlines, frontages)
        checks[layout.name]["footprint_m2"] = round(shapes[layout.name].area, 1)
        checks[layout.name]["keep_clear_conflict"] = any(shapes[layout.name].intersection(z).area > .05 for z in zones)
        if extra_checks is not None:
            checks[layout.name].update(extra_checks(shapes[layout.name]))
        descriptions[layout.name] = describe(layout, study.mapping[layout.approach]["edge"].getLaneNumber())
    comparison = study.compare(patches, activity=activity)
    ranking = rank(comparison["results"], checks, policy=policy)
    comparison.update(layouts={l.name: l.model_dump() for l in layouts}, descriptions=descriptions, checks=checks,
                      ranking=ranking, geometry={n: to_geojson(g, layout=n, role="proposed") for n, g in shapes.items()})
    return comparison
