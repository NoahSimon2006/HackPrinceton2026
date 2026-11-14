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
    """Remove lanes on the approach chain edges (SUMO drops the curb-side lanes and rebuilds connections)."""
    approach = study.mapping.get(layout.approach)
    if approach is None:
        raise ValueError(f"The {layout.approach.upper()} approach does not exist at this intersection.")
    rows, remaining = [], layout.length_m
    for edge in reversed(approach["chain"]):
        if remaining <= 0:
            break
        lanes = edge.getLaneNumber() - layout.lanes_removed
        if lanes < 1:
            raise ValueError("A layout must leave at least one general traffic lane.")
        rows.append(f'  <edge id="{edge.getID()}" numLanes="{lanes}"/>')
        remaining -= edge.getLength()
    return "<edges>\n" + "\n".join(rows) + "\n</edges>\n"


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
            if line.length > remaining:
                from shapely.ops import substring
                line = substring(line, line.length - remaining, line.length)
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
    if outlines is not None:
        parcels, buildings = [], []
        for feature in outlines:
            try:
                geometry = utm(feature["geometry"])
            except ValueError:
                continue
            target = parcels if feature["properties"].get("label") == "Parcel boundary" else buildings
            target.append((feature["properties"].get("evidenceId"), geometry))
        result["parcel_overlap_m2"] = round(sum(design.intersection(g).area for _, g in parcels), 2)
        result["building_overlap_m2"] = round(sum(design.intersection(g).area for _, g in buildings), 2)
        result["parcel_evidence"] = [i for i, g in parcels + buildings if design.intersection(g).area > .05 and i]
    if frontages is not None:
        conflicts = []
        for frontage in frontages:
            if not frontage.get("curbCuts"):
                continue
            try:
                line = utm(frontage["geometry"])
            except ValueError:
                continue
            if design.distance(line) <= 3.0:
                conflicts.append(frontage.get("evidenceId"))
        result["access_conflicts"] = len(conflicts)
        result["access_evidence"] = [c for c in conflicts if c]
    return result


def rank(results: dict, checks: dict, keep_clear: list | None = None) -> dict:
    """Eligibility first, then CO2-first weighted score versus baseline. Returns per-layout verdicts."""
    base = results["baseline"]
    verdicts = {}
    for name, metrics in results.items():
        if name == "baseline":
            continue
        reasons = []
        if metrics["completion_share"] is not None and base["completion_share"] and \
                metrics["completion_share"] < MIN_COMPLETION * base["completion_share"]:
            reasons.append(f"completes {metrics['completion_share']:.0%} of demand vs {base['completion_share']:.0%} today (strands traffic)")
        if metrics["unable_to_enter_share"] > max(MAX_UNABLE_TO_ENTER, base["unable_to_enter_share"] + MAX_UNABLE_TO_ENTER):
            reasons.append(f"{metrics['unable_to_enter_share']:.0%} of vehicles cannot enter the study area")
        check = checks.get(name, {})
        if check.get("building_overlap_m2"):
            reasons.append(f"overlaps mapped buildings by {check['building_overlap_m2']} m²")
        if check.get("keep_clear_conflict"):
            reasons.append("crosses a planner keep-clear area")
        def change(key, sub=None):
            before = base[key] if sub is None else max(base[key].values() or [0])
            after = metrics[key] if sub is None else max(metrics[key].values() or [0])
            return (after - before) / before if before else 0.0
        # CO2 per completed vehicle, so a layout is not rewarded for serving fewer trips.
        changes = {"co2": change("co2_g_per_completed_vehicle"), "delay": change("mean_delay_s"), "queue": change("max_queue_m", True)}
        noise_before = [v for v in base["max_noise_db"].values() if v is not None]
        noise_after = [v for v in metrics["max_noise_db"].values() if v is not None]
        changes["noise"] = (max(noise_after) - max(noise_before)) / 10 if noise_before and noise_after else 0.0
        changes["parcel_overlap"] = min(1.0, (check.get("parcel_overlap_m2") or 0) / 50)
        changes["access"] = min(1.0, (check.get("access_conflicts") or 0) / 2)
        score = -sum(WEIGHTS[k] * v for k, v in changes.items())
        tradeoffs = [k for k in ("delay", "queue", "co2") if changes[k] > TRADEOFF]
        verdicts[name] = {"eligible": not reasons, "ineligible_reasons": reasons, "score": round(score, 4),
                          "changes": {k: round(v, 4) for k, v in changes.items()}, "tradeoffs": tradeoffs}
    eligible = [n for n, v in verdicts.items() if v["eligible"]]
    best = max(eligible, key=lambda n: verdicts[n]["score"], default=None)
    recommended = best if best and verdicts[best]["score"] > 0 else None
    return {"verdicts": verdicts, "recommended": recommended,
            "reason": None if recommended else
            ("No tested layout is eligible." if not eligible else
             "No eligible layout scores better than today's layout on the CO2-first ranking.")}


def evaluate(study, layouts: list[Layout], outlines=None, frontages=None, keep_clear=None) -> dict:
    """Simulate baseline plus layouts with paired seeds, measure footprints and checks, rank."""
    if not 1 <= len(layouts) <= 3 or len({l.name for l in layouts}) != len(layouts):
        raise ValueError("Evaluate one to three uniquely named layouts.")
    patches, shapes, checks, descriptions = {}, {}, {}, {}
    zones = []
    for area in keep_clear or []:
        try:
            zones.append(utm(area))
        except ValueError:
            continue
    for layout in layouts:
        patches[layout.name] = edge_patch(layout, study)
        shapes[layout.name] = footprint(layout, study)
        checks[layout.name] = sponsor_checks(shapes[layout.name], outlines, frontages)
        checks[layout.name]["footprint_m2"] = round(shapes[layout.name].area, 1)
        checks[layout.name]["keep_clear_conflict"] = any(shapes[layout.name].intersection(z).area > .05 for z in zones)
        descriptions[layout.name] = describe(layout, study.mapping[layout.approach]["edge"].getLaneNumber())
    comparison = study.compare(patches)
    ranking = rank(comparison["results"], checks)
    comparison.update(layouts={l.name: l.model_dump() for l in layouts}, descriptions=descriptions, checks=checks,
                      ranking=ranking, geometry={n: to_geojson(g, layout=n, role="proposed") for n, g in shapes.items()})
    return comparison
