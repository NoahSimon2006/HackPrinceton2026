"""Rebuild the archived road-emissions estimate with explicitly opted-in volume assumptions.

Every road edge gets a weekday daily volume, chosen in this order and labeled with
its basis:
  1. counted      - a LADOT automated 24-hour count on this street and direction at
                    an adjacent intersection (the sheets are titled "24 Hours
                    Traffic Volume").
  2. same_street  - inverse-distance average of counts on the same street and
                    direction within 1.2 km.
  3. class_median - median counted volume of roads in the same OpenStreetMap class
                    (needs at least 10 counted roads of that class)
                    within the pilot.
  4. assumed      - the earlier class default, used only when no road of that class
                    was counted.
Hourly volume uses the share of daily traffic observed in each period on official
LADOT 24-hour count sheets (median across the downloaded sheets). Emissions are
vehicles x segment length x CARB EMFAC2025 2026 Los Angeles running-exhaust rates.
No random-trip simulation is used.

Not live planning evidence. Usage: python scripts/build_emissions.py --allow-volume-assumptions
"""
from __future__ import annotations

import json
import argparse
import math
import statistics
import xml.etree.ElementTree as ET
import sys
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from traffic_counts import SheetError, find_sheet  # noqa: E402
from traffic_sim import fleet_rates, file_hash, FLEET_SOURCE  # noqa: E402
from street_names import street_key  # noqa: E402

DATA = ROOT / "private" / "discovery"
OUT = ROOT / "public" / "data" / "emissions.json"
BBOX = [-118.268, 34.034, -118.219, 34.070]
PERIODS = {"midday": {"label": "Weekday midday", "hours": [11, 12, 13]},
           "pm_peak": {"label": "Weekday PM peak", "hours": [16, 17, 18]}}
ROAD_TYPES = {"motorway", "motorway_link", "trunk", "trunk_link", "primary", "primary_link", "secondary",
              "secondary_link", "tertiary", "tertiary_link", "residential", "unclassified", "living_street"}
CLASS_DEFAULT = {"motorway": 70000, "motorway_link": 21000, "trunk": 32000, "trunk_link": 12000, "primary": 22000,
                 "primary_link": 9500, "secondary": 14000, "secondary_link": 7000, "tertiary": 8500,
                 "tertiary_link": 4500, "residential": 2500, "unclassified": 3000, "living_street": 1200}
WEEKDAYS = {"MON", "TUE", "WED", "THU", "FRI"}
SHEET_SAMPLE = 16


# SUMO edge-output helpers kept from the earlier simulation exporter (tested in test_discovery).
def edge_data(path):
    tree = ET.parse(path)
    if len(tree.findall(".//interval")) != 1:
        raise ValueError("Expected one measurement interval; aggregate explicitly before exporting.")
    return {element.get("id"): {key: float(value) for key, value in element.attrib.items()
                                  if key != "id"}
            for element in tree.findall(".//interval/edge")}


def delay_metrics(traffic, begin, end):
    """Vehicle-time shares, never an unsupported per-vehicle delay estimate.

    Export preparation only: the archived assumed-demand run is not live data.
    See SUMO's Lane-_or_Edge-based_Traffic_Measures output documentation.
    """
    if not all(math.isfinite(v) for v in (begin, end)) or end <= begin:
        raise ValueError("Invalid SUMO measurement interval.")
    def value(key):
        v = traffic.get(key)
        return v if isinstance(v, (int, float)) and math.isfinite(v) and v >= 0 else None
    sampled, stopped, lost = (value(k) for k in ("sampledSeconds", "waitingTime", "timeLoss"))
    def percent(numerator):
        if not sampled or numerator is None or numerator > sampled + .02:return None
        return round(100 * min(numerator, sampled) / sampled, 3)
    return {"sampled_vehicle_seconds":sampled, "stopped_vehicle_seconds":stopped,
            "time_loss_vehicle_seconds":lost, "stopped_time_percent":percent(stopped),
            "time_loss_percent":percent(lost), "simulated_entered":value("entered"),
            "simulated_left":value("left"), "simulated_departed":value("departed"),
            "simulated_arrived":value("arrived"), "simulated_flow_vehicles_h":value("flow"),
            "interval_begin_s":begin, "interval_end_s":end, "interval_seconds":end-begin,
            "halting_speed_threshold_m_s":.1,
            "basis":"Archived assumed-demand SUMO scenario; unavailable in live discovery."}


def bearing_field(edge):
    shape = edge.getShape()
    dx, dy = shape[-1][0] - shape[0][0], shape[-1][1] - shape[0][1]
    return ("e_b" if dx > 0 else "w_b") if abs(dx) > abs(dy) else ("n_b" if dy > 0 else "s_b")


def hourly_profile(records):
    """Median share of daily traffic per period from official 24-hour sheets."""
    automated = sorted((r for r in records if r.get("type", "").strip().upper() in ("AUTO", "AUT")
                        and r.get("day") in WEEKDAYS and r.get("dir", "").strip().upper() == "AT" and r.get("count_date")),
                       key=lambda r: r["count_date"], reverse=True)
    shares = {p: [] for p in PERIODS}
    used = []
    for row in automated:
        if len(used) >= SHEET_SAMPLE:
            break
        try:
            sheet = find_sheet(row["primary_street"], row["cross_street"], row["count_date"], "AUTO", DATA / "sheets")
        except SheetError:
            continue
        if sheet["url"] in {u["url"] for u in used}:
            continue
        for direction, values in sheet["hourly"].items():
            day = sum(values)
            if day < 500:
                continue
            for period, spec in PERIODS.items():
                shares[period].append(statistics.fmean(values[h] for h in spec["hours"]) / day)
        used.append({"url": sheet["url"], "date": sheet["date"], "location": sheet["location"]})
    if not used or any(not values for values in shares.values()):
        raise SystemExit("No official 24-hour sheets could be read; refusing to assume hourly shares.")
    return {p: round(statistics.median(v), 5) for p, v in shares.items()}, used


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--allow-volume-assumptions", action="store_true", help="Explicitly reproduce the archived extrapolated layer; not live planning evidence.")
    if not parser.parse_args().allow_volume_assumptions:
        parser.error("Archived extrapolated volumes require --allow-volume-assumptions. Live discovery uses source-only counts.")
    import sumolib
    carb = fleet_rates()
    net = sumolib.net.readNet(str(ROOT / "sim" / "dtla.net.xml"))
    records = json.loads((DATA / "ladot-records.json").read_text())
    edges, by_street, node_streets = [], defaultdict(list), defaultdict(set)
    for edge in net.getEdges():
        if edge.isSpecial() or not edge.allows("passenger"):
            continue
        kind = edge.getType().split("|")[-1].replace("highway.", "")
        if kind not in ROAD_TYPES or edge.getLength() < 15:
            continue
        coords = [net.convertXY2LonLat(*p) for p in edge.getShape()]
        mid = coords[len(coords) // 2]
        if not (BBOX[0] <= mid[0] <= BBOX[2] and BBOX[1] <= mid[1] <= BBOX[3]):
            continue
        x, y = net.convertLonLat2XY(*mid)
        item = {"edge": edge, "id": edge.getID(), "name": edge.getName() or kind.replace("_", " ").title(), "kind": kind,
                "length_m": edge.getLength(), "xy": (x, y), "field": bearing_field(edge),
                "coordinates": [[round(lon, 6), round(lat, 6)] for lon, lat in coords]}
        edges.append(item)
        if edge.getName():
            key = street_key(edge.getName())
            item["street"] = key
            by_street[key].append(item)
            node_streets[edge.getFromNode().getID()].add(key)
            node_streets[edge.getToNode().getID()].add(key)

    anchors = {}
    for record in records:
        if record.get("type", "").strip().upper() not in ("AUTO", "AUT") or record.get("day") not in WEEKDAYS or not record.get("count_date"):
            continue
        if record.get("dir", "").strip().upper() != "AT":
            continue
        primary, cross = street_key(record.get("primary_street", "")), street_key(record.get("cross_street", ""))
        for item in by_street.get(primary, []):
            edge = item["edge"]
            if not any(cross in node_streets[n.getID()] for n in (edge.getFromNode(), edge.getToNode())):
                continue
            try:
                daily = float(record.get(item["field"]) or 0)
            except (TypeError, ValueError):
                continue
            if daily <= 0:
                continue  # never split a total into an unreported direction
            previous = anchors.get(item["id"])
            if previous is None or record["count_date"] > previous["date"]:
                anchors[item["id"]] = {"daily": daily, "date": record["count_date"][:10], "street": record["primary_street"],
                                       "cross": record["cross_street"], "direction": item["field"]}

    counted = [e for e in edges if e["id"] in anchors]
    class_values = defaultdict(list)
    for e in counted:
        class_values[e["kind"]].append(anchors[e["id"]]["daily"])
    shares, sheets = hourly_profile(records)
    bases = defaultdict(int)
    output = []
    for item in edges:
        anchor = anchors.get(item["id"])
        detail = None
        if anchor:
            daily, basis, detail = anchor["daily"], "counted", anchor
        else:
            nearby = [(math.dist(item["xy"], c["xy"]), anchors[c["id"]]) for c in by_street.get(item.get("street"), [])
                      if c["id"] in anchors and c["field"] == item["field"]]
            nearby = [(d, a) for d, a in nearby if d <= 1200]
            if nearby:
                weights = [(1 / max(d, 25), a) for d, a in nearby]
                daily = sum(w * a["daily"] for w, a in weights) / sum(w for w, _ in weights)
                basis = "same_street"
                detail = {"sources": len(nearby), "nearest_m": round(min(d for d, _ in nearby)),
                          "dates": sorted({a["date"] for _, a in nearby})}
            elif len(class_values.get(item["kind"], [])) >= 10:
                daily, basis = statistics.median(class_values[item["kind"]]), "class_median"
                detail = {"counted_roads": len(class_values[item["kind"]])}
            else:
                daily, basis = CLASS_DEFAULT[item["kind"]] / 2, "assumed"
        bases[basis] += 1
        miles = item["length_m"] / 1609.344
        periods = {}
        for period in PERIODS:
            volume = daily * shares[period]
            periods[period] = {"vehicles_h": round(volume), "speed_kmh": round(item["edge"].getSpeed() * 3.6, 1),
                               "co2_kg_h": round(volume * miles * carb["CO2"] / 1000, 2),
                               "nox_g_h": round(volume * miles * carb["NOx"], 2)}
        output.append({"id": item["id"], "name": item["name"], "class": item["kind"], "length_m": round(item["length_m"]),
                       "coordinates": item["coordinates"], "basis": basis, "count": anchor,
                       "basis_detail": detail if basis != "counted" else None, "daily_vehicles": round(daily),
                       "periods": periods})

    summary = {p: {k: round(sum(r["periods"][p][k] for r in output), 1) for k in ("co2_kg_h", "nox_g_h")} for p in PERIODS}
    data = {"schema": 2, "title": "Downtown Los Angeles road emissions from counted traffic", "bbox": BBOX,
            "built_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "periods": {p: {"label": s["label"], "share_of_daily": shares[p]} for p, s in PERIODS.items()},
            "fleet_rates_g_per_mile": carb, "fleet_source_sha256": file_hash(FLEET_SOURCE),
            "archived_assumption_based": True, "summary": summary, "roads": output,
            "quality": {"road_edges": len(output), "historical_anchor_edges": bases["counted"], "basis_counts": dict(bases),
                        "hourly_profile_sheets": len(sheets), "simulation_teleports": 0},
            "hourly_profile_sheets": sheets,
            "method": {
                "headline": "Tailpipe running-exhaust estimate built from counted LADOT traffic (2011–2016) and CARB 2026 Los Angeles fleet rates.",
                "traffic": f"Counted roads: {bases['counted']}. Same street, inverse-distance from counts within 1.2 km: {bases['same_street']}. Median counted volume of the same road class: {bases['class_median']}. Assumed class default: {bases['assumed']}.",
                "volume": f"Daily volumes are LADOT automated 24-hour counts by direction. Hourly shares come from {len(sheets)} official LADOT 24-hour count sheets: midday (11 AM–2 PM) {shares['midday']*100:.2f}% and PM peak (4–7 PM) {shares['pm_peak']*100:.2f}% of daily traffic per hour.",
                "emissions": "Vehicles × segment length × CARB EMFAC2025 v2.1.1 2026 Los Angeles (SC) VMT-weighted running-exhaust rates. Excludes starts, idling surcharges, non-tailpipe and upstream emissions; congestion is not modeled on this layer.",
                "uncertainty": "Counts are 2011–2016 weekday counts; current traffic may differ. Roads without their own count carry the basis shown when selected.",
                "signal": "Signal timing does not enter this layer."},
            "sources": [
                {"label": "CARB EMFAC2025 v2.1.1, Los Angeles (SC), 2026", "url": "https://emfac.arb.ca.gov/emissions-inventory/3b6469b056eb7e5a47b65c0c96415b33d5e20812"},
                {"label": "LADOT Traffic Counts Summary, 2011–2016", "url": "https://data.lacity.org/Transportation/LADOT-Traffic-Counts-Summary/94wu-3ps3"},
                {"label": "LADOT 24-hour count sheets (NavigateLA)", "url": sheets[0]["url"]},
                {"label": "OpenStreetMap contributors, road geometry", "url": "https://www.openstreetmap.org/copyright"}]}
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(data, separators=(",", ":")))
    print("Roads:", len(output), "bases:", dict(bases), "shares:", shares, "sheets:", len(sheets))
    print("Summary:", summary)


if __name__ == "__main__":
    main()
