"""Summarise SUMO runs into public/data/sim.json for the map and the Grok chat.

Per road segment and period: idling, share of time stopped, emissions, speed and flow,
averaged over the available seeds, plus deterministic cause indicators computed here
(never by the language model). Segments are also rolled up to the app's street-pair sites.
"""
import json
import math
import statistics
import sys
import xml.etree.ElementTree as ET
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

import sumolib

sys.path.insert(0, str(Path(__file__).resolve().parent))
from build_demand import PERIODS, edge_heading, key_of, road_class  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
SIM = ROOT / "sim"
MIN_FLOW = 30            # vehicles in the measured hour; quieter segments are too noisy to report
OFFSET_M = 3.5           # draw each direction slightly to its right so both are visible
COMPASS = ("northbound", "eastbound", "southbound", "westbound")


def read_edges(path):
    for _, element in ET.iterparse(path):
        if element.tag == "edge":
            yield element.attrib["id"], {k: float(v) for k, v in element.attrib.items() if k != "id"}
            element.clear()


def load_period(period):
    """Mean of each raw measure across seeds, per edge."""
    seeds = sorted((SIM / "runs" / period).glob("seed*"))
    totals, idle_by_seed = defaultdict(lambda: defaultdict(float)), defaultdict(list)
    for seed in seeds:
        seen = {}
        for name in ("traffic.xml", "emissions.xml"):
            for edge_id, values in read_edges(seed / name):
                seen.setdefault(edge_id, {}).update(values)
        for edge_id, values in seen.items():
            for key, value in values.items():
                totals[edge_id][key] += value / len(seeds)
            vehicles = max(values.get("entered", 0), values.get("left", 0), 1)
            idle_by_seed[edge_id].append(values.get("waitingTime", 0) / vehicles)
    return totals, idle_by_seed, len(seeds)


def offset_shape(net, edge):
    shape = edge.getShape()
    if len(shape) > 7:   # thin long shapes; keep the ends
        step = (len(shape) - 1) / 6
        shape = [shape[round(i * step)] for i in range(7)]
    points = []
    for i, (x, y) in enumerate(shape):
        a, b = shape[max(i - 1, 0)], shape[min(i + 1, len(shape) - 1)]
        dx, dy = b[0] - a[0], b[1] - a[1]
        length = math.hypot(dx, dy) or 1
        lon, lat = net.convertXY2LonLat(x + dy / length * OFFSET_M, y - dx / length * OFFSET_M)
        points.append([round(lat, 5), round(lon, 5)])
    return points


def causes_for(edge, m, target, upstream_signal):
    """Why vehicles idle here. Thresholds are screening rules, not calibrated engineering criteria."""
    found = []
    signal = edge.getToNode().getType().startswith("traffic_light")
    per_lane = m["flow"] / edge.getLaneNumber()
    if m["occupancy"] >= 45:
        found.append(("spillback", "The queue fills most of this block, so it can back up into the junction behind it."))
    # Only counted roads: assumed targets are not a real demand to fall short of.
    if target and target["basis"] == "counted" and m["flow"] < 0.8 * target["hourly"] and m["stopped_share"] >= 0.3:
        found.append(("over_capacity", f"Only {round(m['flow'])} of the {target['hourly']} counted vehicles an hour got through: demand exceeds what the junction ahead passes."))
    if signal and m["stopped_share"] >= 0.35 and per_lane < 400 and not any(c == "spillback" for c, _ in found):
        found.append(("signal_delay", "Vehicles spend a large share of their time stopped at the signal although the lanes are not heavily loaded, which points to signal timing or poor progression between signals."))
    if signal and upstream_signal and edge.getLength() < 120 and m["stopped_share"] >= 0.25:
        found.append(("close_signals", f"Signals at both ends of a {round(edge.getLength())} m block force repeated stops."))
    if not signal and m["stopped_share"] >= 0.3:
        found.append(("yield_delay", "Vehicles wait here to enter or cross a busier road without a signal."))
    if m["speed_ratio"] < 0.35 and not found:
        found.append(("slow", "Traffic moves at well under free-flow speed along the whole segment."))
    return [{"code": code, "text": text} for code, text in found]


def main():
    net_path = SIM / "central_la.net.xml"
    if not (SIM / "runs/manifest.json").exists():
        raise SystemExit("Run scripts/run_sim.py first.")
    net = sumolib.net.readNet(str(net_path))
    manifest = json.loads((SIM / "runs/manifest.json").read_text())
    demand = json.loads((SIM / "demand/demand_report.json").read_text())
    names_at = defaultdict(set)
    for edge in net.getEdges():
        if edge.getName():
            for node in (edge.getFromNode(), edge.getToNode()):
                names_at[node.getID()].add(edge.getName())
    geometry, periods, per_period = {}, {}, {}
    for period, settings in PERIODS.items():
        if not (SIM / "runs" / period).is_dir():
            continue
        raw, idle_by_seed, seeds = load_period(period)
        targets = json.loads((SIM / "demand" / f"{period}.targets.json").read_text())
        segments = {}
        for edge_id, r in raw.items():
            if not net.hasEdge(edge_id):
                continue
            edge = net.getEdge(edge_id)
            flow = max(r.get("entered", 0), r.get("left", 0))
            vehicle_km = r.get("sampledSeconds", 0) * r.get("speed", 0) / 1000
            if flow < MIN_FLOW or vehicle_km <= 0 or not edge.allows("passenger"):
                continue
            km = edge.getLength() / 1000
            m = {"flow": round(flow), "idle_s": round(r.get("waitingTime", 0) / flow, 1),
                 "stopped_share": round(r.get("waitingTime", 0) / max(r.get("sampledSeconds", 1), 1), 3),
                 "delay_s": round(r.get("timeLoss", 0) / flow, 1), "speed_ratio": round(r.get("speedRelative", 0), 2),
                 "speed_kmh": round(r.get("speed", 0) * 3.6, 1), "occupancy": round(r.get("occupancy", 0), 1),
                 "idle_veh_h": round(r.get("waitingTime", 0) / 3600, 1),
                 "co2_kg_km": round(r.get("CO2_abs", 0) / 1e6 / km, 1),            # kg per km of road in the hour
                 "co2_g_vkm": round(r.get("CO2_abs", 0) / 1e3 / vehicle_km),      # g per vehicle-km
                 "nox_g_km": round(r.get("NOx_abs", 0) / 1e3 / km, 1),
                 "pm_g_km": round(r.get("PMx_abs", 0) / 1e3 / km, 2),
                 "fuel_l_km": round(r.get("fuel_abs", 0) / 1e3 / 745 / km, 1)}   # petrol at about 745 g per litre
            target = targets.get(edge_id)
            m["basis"] = target["basis"] if target else "unconstrained"
            spread = idle_by_seed.get(edge_id, [])
            if len(spread) > 1 and statistics.mean(spread) > 0:
                m["idle_spread"] = round(statistics.pstdev(spread) / statistics.mean(spread), 2)
            m["causes"] = causes_for(edge, m, target, edge.getFromNode().getType().startswith("traffic_light"))
            segments[edge_id] = m
            if edge_id not in geometry:
                cross = sorted(names_at[edge.getToNode().getID()] - {edge.getName()})
                geometry[edge_id] = {"name": edge.getName() or "Unnamed ramp or link", "toward": cross[0] if cross else None,
                                     "dir": COMPASS[round(edge_heading(edge) / 90) % 4], "class": road_class(edge),
                                     "lanes": edge.getLaneNumber(), "length_m": round(edge.getLength()),
                                     "signal": edge.getToNode().getType().startswith("traffic_light"),
                                     "shape": offset_shape(net, edge)}
        per_period[period] = segments
        periods[period] = {"label": settings["label"], "seeds": seeds, "segments": len(segments),
                           "runs": manifest["periods"].get(period, {}).get("runs", [])}

    # Roll up to the app's street-pair sites: the approaches into the matching junction.
    by_pair = defaultdict(list)
    for node in net.getNodes():
        keys = {key_of(e.getName()) for e in list(node.getIncoming()) + list(node.getOutgoing()) if e.getName()}
        for a in keys:
            for b in keys:
                if a < b:
                    by_pair[(a, b)].append(node)
    sites = {}
    for site in json.loads((ROOT / "public/data/la.json").read_text())["sites"]:
        parts = site["name"].split(" & ")
        if len(parts) != 2:
            continue
        pair = tuple(sorted(key_of(p) for p in parts))
        nodes = by_pair.get(pair)
        if not nodes:
            continue
        x, y = net.convertLonLat2XY(site["lon"], site["lat"])
        nodes = [n for n in nodes if math.hypot(n.getCoord()[0] - x, n.getCoord()[1] - y) < 250]
        approaches = sorted({e.getID() for n in nodes for e in n.getIncoming() if key_of(e.getName()) in pair})
        if approaches:
            sites[site["name"]] = approaches

    used = sorted({e for segments in per_period.values() for e in segments})
    output = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "method": {
            "engine": "SUMO " + manifest["sumo_version"], "emission_model": manifest["emission_model"],
            "demand": f"LADOT counts ({', '.join(demand['count_years'][:1] + demand['count_years'][-1:])}) on {demand['edges_with_count']} segments; other arterials assumed at {demand['assumed_factor']:.0%} of the counted per-lane median",
            "signals": "Signal timing generated by SUMO, not LADOT's real plans",
            "caveat": "Simulated and uncalibrated. Use for ranking and comparison, not as measured idling or emissions.",
        },
        "periods": periods,
        "segments": {e: {**geometry[e], "data": {p: per_period[p][e] for p in per_period if e in per_period[p]}} for e in used},
        "sites": sites,
    }
    target = ROOT / "public/data/sim.json"
    target.write_text(json.dumps(output, separators=(",", ":")))
    print(f"Wrote {target.relative_to(ROOT)}: {len(used)} segments, {len(sites)} sites, {target.stat().st_size / 1e6:.1f} MB")
    for period, segments in per_period.items():
        worst = sorted((s for e, s in segments.items() if geometry[e]["class"] != "motorway"), key=lambda s: -s["idle_veh_h"])[:1]
        print(period, "segments:", len(segments), "| causes:", dict(sorted(
            ((c, sum(any(x["code"] == c for x in s["causes"]) for s in segments.values()))
             for c in ("spillback", "over_capacity", "signal_delay", "close_signals", "yield_delay", "slow")))))


if __name__ == "__main__":
    main()
