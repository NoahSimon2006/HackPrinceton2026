"""Bounded street layouts: SUMO network patches, map geometry and sponsor-evidence checks.

A layout is a small set of parameters the agent may choose. Python turns it into:
- an edge patch for SUMO (so the traffic effect is simulated, not guessed);
- WGS84 GeoJSON drawn from the simulated network's own lane shapes;
- parcel and building overlap areas (Vexcel outlines) and access conflicts (CoStar
  frontages with reported curb cuts), measured in UTM 11N.
Ranking preserves historical strict-v1 weights and uses an ordered environmental-priority policy for new studies; nothing is tuned per run.
"""
from __future__ import annotations

from typing import Literal
import math
import statistics
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
ENVIRONMENTAL_POLICY = "environmental-priority-v1"


class Layout(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, allow_inf_nan=False)
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
        missing_building_coverage = False
        for feature in outlines:
            try:
                label = feature["properties"].get("label")
                if label not in ("Parcel boundary", "Building footprint"):
                    continue
                geometry = utm(feature["geometry"])
                if geometry.geom_type not in ("Polygon", "MultiPolygon"):
                    raise ValueError("Outline must be an area")
            except (ValueError, KeyError, TypeError, AttributeError):
                # A filtered invalid building must not turn into zero overlap.
                parcels, buildings = [], []
                break
            target = parcels if label == "Parcel boundary" else buildings
            target.append((feature["properties"].get("evidenceId"), geometry))
            if label == "Parcel boundary" and feature["properties"].get("buildingCoverage") is False:
                missing_building_coverage |= design.intersection(geometry).area > .05
        if parcels:
            result["parcel_overlap_m2"] = round(design.intersection(unary_union([g for _, g in parcels])).area, 2)
        if buildings:
            overlap = round(design.intersection(unary_union([g for _, g in buildings])).area, 2)
            if overlap or not missing_building_coverage:
                result["building_overlap_m2"] = overlap
        result["parcel_evidence"] = [i for i, g in parcels + buildings if design.intersection(g).area > .05 and i]
    if frontages:
        conflicts, assessed = [], 0
        for frontage in frontages:
            try:
                cuts = frontage.get("curbCuts")
                if type(cuts) is not int or cuts < 0:
                    continue
                line = utm(frontage["geometry"])
                if line.geom_type != "LineString":
                    continue
            except (ValueError, KeyError, TypeError, AttributeError):
                continue
            assessed += 1
            if cuts > 0 and design.distance(line) <= 3.0:
                conflicts.append(frontage.get("evidenceId"))
        if assessed == len(frontages):
            result["access_conflicts"] = len(conflicts)
        result["access_evidence"] = [c for c in conflicts if c]
    return result


def rank(results: dict, checks: dict, keep_clear: list | None = None, *, policy=None) -> dict:
    """User-approved strict gates, followed by CO₂-first ranking among fully assessed layouts."""
    if policy not in (None, "strict", "strict-v1", "strict-total-co2-v1", ENVIRONMENTAL_POLICY):
        raise ValueError("Unknown versioned traffic selection policy.")
    environmental = policy == ENVIRONMENTAL_POLICY
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
            try:
                change = 10 ** ((other - value) / 10) - 1 if energy else relative(value, other)
            except OverflowError:
                return None
            if change is None:
                return None
            changes.append(change)
        return max(changes)

    for name, metrics in results.items():
        if name == "baseline":
            continue
        reasons, check = [], checks.get(name, {})
        completion, base_completion = metrics.get("completion_share"), base.get("completion_share")
        if (not finite(completion) or not finite(base_completion)
                or not 0 <= completion <= 1 or not 0 < base_completion <= 1):
            reasons.append("trip completion is unavailable")
        elif completion < MIN_COMPLETION * base_completion:
            reasons.append("completes less than 98% of baseline completed demand")
        unable, base_unable = metrics.get("unable_to_enter_share"), base.get("unable_to_enter_share")
        if not finite(unable) or not finite(base_unable) or not 0 <= unable <= 1 or not 0 <= base_unable <= 1:
            reasons.append("entry-failure accounting is unavailable")
        elif unable > base_unable + MAX_UNABLE_TO_ENTER + 1e-9:
            reasons.append("entry failures exceed baseline by more than 2 percentage points")
        if metrics.get("teleports", 0) or base.get("teleports", 0):
            reasons.append("teleported vehicles invalidate the comparison")
        for field, label in (("parcel_overlap_m2", "parcel overlap"), ("building_overlap_m2", "building overlap"),
                             ("access_conflicts", "property access")):
            if not finite(check.get(field)) or check[field] < 0:
                reasons.append(f"{label} remains unassessed")
        if environmental and finite(check.get("access_conflicts")) and check["access_conflicts"] > 0:
            reasons.append("conflicts with reported property access; revise the footprint or resolve the access conflict")
        if check.get("building_overlap_m2", 0):
            reasons.append(f"overlaps mapped buildings by {check['building_overlap_m2']} m²")
        if check.get("keep_clear_conflict"):
            reasons.append("crosses a planner keep-clear area")
        if check.get("marked_crossing_conflict"):
            reasons.append("crosses a planner-marked crossing")
        if (check.get("detection_status") not in ("ready", "empty")
                or any(check.get(field) is None for field in ("candidate_crosswalk_overlaps", "candidate_driveway_overlaps"))):
            reasons.append("crossing and driveway candidate checks remain unassessed")
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
                                      if finite(check.get("parcel_overlap_m2")) and check["parcel_overlap_m2"] >= 0 else None)
        changes["access"] = (min(1.0, check["access_conflicts"] / 2)
                             if finite(check.get("access_conflicts")) and check["access_conflicts"] >= 0 else None)
        score = -sum(WEIGHTS[k] * v for k, v in changes.items()) if all(v is not None for v in changes.values()) else None
        missing = [reason for reason in reasons if "unavailable" in reason or "unassessed" in reason]
        if changes["co2"] is None:
            missing.append("CO₂ comparison is unavailable")
        verdicts[name] = {"eligible": not reasons, "ineligible_reasons": reasons,
                          "readiness": {"status": "partial" if missing else "evaluated", "gaps": missing},
                          "score": score,
                          "changes": {k: round(v, 4) if v is not None else None for k, v in changes.items()},
                          "tradeoffs": [k for k in ("delay", "queue", "noise", "co2") if changes[k] is not None and changes[k] > 0]}
    eligible = [n for n, v in verdicts.items() if v["eligible"]]
    if environmental:
        return environmental_selection(results, checks, verdicts, eligible)
    best = max(eligible, key=lambda n: verdicts[n]["score"], default=None)
    recommended = best if best and verdicts[best]["score"] > 0 else None
    return {"verdicts": verdicts, "recommended": recommended, "policy": "strict-v1",
            "noise_rule": "At most 10% increase in sound energy (approximately 0.414 dB), not 10% of a dB reading.",
            "reason": None if recommended else
            ("No tested layout passes the strict rules with complete evidence." if not eligible else
             "No eligible layout scores better than today's layout on the CO₂-first ranking.")}


def environmental_selection(results, checks, verdicts, eligible):
    """Choose CO₂ first; use one paired-seed standard error as a disclosed tie screen.

    The tolerance is a descriptive simulation-variability screen, not a confidence
    interval or a claim that model/input uncertainty has been quantified. Missing
    seed detail never earns a readiness score: only exact means can tie then.
    """
    for verdict in verdicts.values():
        verdict["score"] = None  # The historical weighted total is not this policy.
    best = min(eligible, key=lambda name: (results[name]["co2_kg_per_hour"], name), default=None)
    tied, tolerances, reasons = [], {}, {}

    def paired_values(name):
        rows = results[name].get("paired_co2_kg_per_hour", [])
        if not isinstance(rows, list) or len(rows) < 2:
            return None
        values = {}
        for row in rows:
            if not isinstance(row, dict) or type(row.get("seed")) is not int:
                return None
            value = row.get("value")
            if (not isinstance(value, (int, float)) or isinstance(value, bool)
                    or not math.isfinite(value) or value < 0 or row["seed"] in values):
                return None
            values[row["seed"]] = value
        return values

    if best:
        reference = paired_values(best)
        for name in eligible:
            values = paired_values(name)
            tolerance = 0.0
            if reference is not None and values is not None and values.keys() == reference.keys():
                differences = [values[seed] - reference[seed] for seed in sorted(reference)]
                tolerance = statistics.stdev(differences) / math.sqrt(len(differences))
                reasons[name] = f"One standard error of {len(differences)} paired-seed differences."
            else:
                reasons[name] = "Paired-seed detail unavailable; only exact modeled means tie."
            tolerances[name] = tolerance
            if results[name]["co2_kg_per_hour"] - results[best]["co2_kg_per_hour"] <= tolerance:
                tied.append(name)

    # Apply only common measured fields, so missing optional feasibility evidence
    # cannot masquerade as zero impact or act as a hidden readiness penalty.
    practical = [key for key in ("access_conflicts", "parcel_overlap_m2", "footprint_m2")
                 if tied and all(isinstance(checks[n].get(key), (int, float))
                                 and not isinstance(checks[n][key], bool)
                                 and math.isfinite(checks[n][key]) for n in tied)]
    def disruption(name):
        base, current = results["baseline"], results[name]
        change = lambda before, after: (after-before)/before if before else 0.0
        operational = (max(0.0, change(base["mean_delay_s"], current["mean_delay_s"])),
                       max(0.0, *(change(v, current["max_queue_m"][k]) for k, v in base["max_queue_m"].items())),
                       max(0.0, *(10 ** ((current["max_noise_db"][k]-v)/10)-1 for k, v in base["max_noise_db"].items())))
        return tuple(checks[name][key] for key in practical) + operational + (results[name]["co2_kg_per_hour"], name)
    recommended = min(tied, key=disruption, default=None)
    explanation = ("No tested layout passes the hard validity, source and operational gates. Inspect the rejected footprints and missing evidence."
                   if not recommended else
                   "Lowest modeled total CO₂ among eligible layouts; feasibility and disruption break only ties within the disclosed paired-seed variability screen."
                   if len(tied) == 1 else
                   "Eligible layouts within the paired-seed CO₂ variability screen are compared by mapped access, parcel overlap, footprint area, then delay, queues and noise.")
    return {"verdicts": verdicts, "recommended": recommended, "policy": ENVIRONMENTAL_POLICY,
            "selection_order": ["Hard validity, access, crossing and operational gates", "Same-cohort modeled total CO₂",
                                "Within the disclosed CO₂ tie screen: access conflicts, parcel overlap, footprint area, delay, queues, noise"],
            "selection_reason": explanation,
            "co2_tie_tolerance": {"method": "One standard error of paired-seed CO₂ differences; descriptive variability, not a confidence interval or complete uncertainty estimate.",
                                  "unit": "kg/hour", "relative_to": best, "tolerances": tolerances,
                                  "basis": reasons, "tied_layouts": tied, "practical_fields": practical},
            "noise_rule": "At most 10% increase in sound energy (approximately 0.414 dB), not 10% of a dB reading.",
            "reason": None if recommended else explanation}


def evaluate(study, layouts: list[Layout], outlines=None, frontages=None, keep_clear=None, *, activity=None, policy=None, extra_checks=None) -> dict:
    """Simulate baseline plus layouts with paired seeds, measure footprints and checks, rank."""
    if not 1 <= len(layouts) <= 3 or len({l.name for l in layouts}) != len(layouts) or any(l.name == "baseline" for l in layouts):
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
