"""Build SUMO traffic demand for Central LA from LADOT counts plus labelled assumptions.

1. Fetch LADOT's public traffic count summary (daily totals by direction, 2011-2016).
2. Match each count to a network edge by street names and direction of travel.
3. Convert daily totals to hourly volumes with assumed time-of-day factors.
4. Give uncounted arterial edges a default volume per lane taken from the counted
   edges of the same road class. Local streets and freeways are left unconstrained.
5. Sample routes with SUMO's routeSampler so simulated flows reproduce those volumes.

Every edge target records whether it was counted or assumed. Output: sim/demand/.
"""
import argparse
import json
import math
import os
import re
import statistics
import subprocess
import sys
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlencode
from urllib.request import Request, urlopen

import sumo
import sumolib

sys.path.insert(0, str(Path(__file__).resolve().parent))
from import_ccrs import street_key  # noqa: E402  (same street-name normalisation as the crash import)

ROOT = Path(__file__).resolve().parents[1]
SIM, OUT = ROOT / "sim", ROOT / "sim/demand"
DATASET = "94wu-3ps3"
COUNTS_URL = f"https://data.lacity.org/resource/{DATASET}.json"
# Assumed share of a weekday's traffic in one hour. LADOT publishes daily totals only.
PERIODS = {"pm_peak": {"label": "Weekday afternoon peak hour", "hour_share": 0.085},
           "midday": {"label": "Weekday midday hour", "hour_share": 0.060}}
WARMUP, MEASURE = 900, 3600          # seconds; demand covers both so the network is loaded before measuring
ASSUMED_CLASSES = ("primary", "secondary", "tertiary")
FALLBACK_PER_LANE = {"primary": 380, "secondary": 300, "tertiary": 180}   # peak veh/h per lane if too few counts
CARDINALS = {"n_b": 0, "e_b": 90, "s_b": 180, "w_b": 270}
SIDES = {"N/O": 0, "E/O": 90, "S/O": 180, "W/O": 270}


def key_of(name):
    name = re.sub(r"\b(\d+)\s+(ST|ND|RD|TH)\b", r"\1\2", (name or "").upper())
    return street_key(name)[0]


def fetch_counts(refresh):
    cache = OUT / "ladot_counts.json"
    if cache.exists() and not refresh:
        return json.loads(cache.read_text())
    rows, offset = [], 0
    while True:
        query = urlencode({"$limit": 5000, "$offset": offset, "$order": ":id"})
        with urlopen(Request(f"{COUNTS_URL}?{query}", headers={"User-Agent": "crossing-lab-demand-build"}), timeout=60) as response:
            page = json.load(response)
        rows += page
        if len(page) < 5000:
            break
        offset += 5000
    data = {"dataset": DATASET, "source": "LADOT Traffic Counts Summary, LA Open Data (public domain)",
            "retrieved_at": datetime.now(timezone.utc).isoformat(), "rows": rows}
    cache.write_text(json.dumps(data))
    return data


def bearing(a, b):
    return math.degrees(math.atan2(b[0] - a[0], b[1] - a[1])) % 360


def closeness(angle, target):
    return math.cos(math.radians(angle - target))


def edge_heading(edge):
    shape = edge.getShape()
    return bearing(shape[0], shape[-1])


def match_counts(net, rows):
    """Return {edge_id: best count record}; one record per edge, the most recent count wins."""
    edges = [e for e in net.getEdges() if e.allows("passenger") and e.getName()]
    names = {e.getID(): key_of(e.getName()) for e in edges}
    at_node = defaultdict(set)
    for edge in edges:
        for node in (edge.getFromNode(), edge.getToNode()):
            at_node[node.getID()].add(names[edge.getID()])
    by_pair = defaultdict(list)
    for node_id, keys in at_node.items():
        for a in keys:
            for b in keys:
                if a != b:
                    by_pair[(a, b)].append(net.getNode(node_id))
    matched, stats = {}, defaultdict(int)
    for row in rows:
        stats["rows"] += 1
        primary, cross = key_of(row.get("primary_street")), key_of(row.get("cross_street"))
        date = (row.get("count_date") or "")[:10]
        if not primary or not cross or not re.match(r"20\d\d-", date):
            stats["unusable"] += 1
            continue
        nodes = by_pair.get((primary, cross))
        if not nodes:
            stats["outside_network_or_unmatched"] += 1
            continue
        side = SIDES.get((row.get("dir") or "").strip().upper())
        used = False
        for field, cardinal in CARDINALS.items():
            try:
                daily = float(row.get(field) or 0)
            except ValueError:
                continue
            if daily <= 0:
                continue
            best = None
            for node in nodes:
                position = node.getCoord()
                for edge in list(node.getIncoming()) + list(node.getOutgoing()):
                    if names.get(edge.getID()) != primary:
                        continue
                    heading = closeness(edge_heading(edge), cardinal)
                    if heading < 0.5:      # LA's downtown grid is rotated about 38 degrees; allow 60
                        continue
                    incoming = edge.getToNode() is node
                    far = edge.getFromNode().getCoord() if incoming else edge.getToNode().getCoord()
                    if side is None:
                        if not incoming:   # "AT": use the approach into the junction
                            continue
                    elif closeness(bearing(position, far), side) < 0.5:
                        continue
                    score = heading + (0.1 if incoming else 0)
                    if best is None or score > best[0]:
                        best = (score, edge)
            if best is None:
                stats["direction_unmatched"] += 1
                continue
            used = True
            edge_id = best[1].getID()
            record = {"daily": daily, "date": date, "type": (row.get("type") or "").strip(),
                      "location": f"{row.get('primary_street')} {row.get('dir')} {row.get('cross_street')}".strip(),
                      "direction": field}
            if edge_id not in matched or date > matched[edge_id]["date"]:
                matched[edge_id] = record
        stats["rows_matched"] += used
    return matched, dict(stats)


def road_class(edge):
    kind = (edge.getType() or "").replace("highway.", "")
    return kind.replace("_link", "")


def build_targets(net, matched, share, assumed_factor):
    """Hourly target per edge: counted where available, class default per lane elsewhere on arterials."""
    per_lane = defaultdict(list)
    for edge_id, record in matched.items():
        edge = net.getEdge(edge_id)
        per_lane[road_class(edge)].append(record["daily"] * share / edge.getLaneNumber())
    defaults = {}
    for kind in ASSUMED_CLASSES:
        values = per_lane.get(kind, [])
        scaled_fallback = FALLBACK_PER_LANE[kind] * share / PERIODS["pm_peak"]["hour_share"]
        defaults[kind] = {"per_lane": round(statistics.median(values) if len(values) >= 5 else scaled_fallback, 1),
                          "basis": f"median of {len(values)} counted {kind} edges" if len(values) >= 5 else "fixed fallback (too few counts)"}
    targets = {}
    for edge in net.getEdges():
        if not edge.allows("passenger"):
            continue
        edge_id, kind = edge.getID(), road_class(edge)
        if edge_id in matched:
            record = matched[edge_id]
            targets[edge_id] = {"hourly": round(record["daily"] * share), "basis": "counted", "class": kind,
                                "count_date": record["date"], "count_location": record["location"], "daily": record["daily"]}
        elif kind in defaults and not (edge.getType() or "").endswith("_link"):
            targets[edge_id] = {"hourly": round(defaults[kind]["per_lane"] * assumed_factor * edge.getLaneNumber()),
                                "basis": "assumed", "class": kind}
    return targets, defaults


def run(command, log):
    result = subprocess.run(command, capture_output=True, text=True, cwd=OUT,
                            env={**os.environ, "SUMO_HOME": str(sumo.SUMO_HOME)})
    (OUT / log).write_text(result.stdout + result.stderr)
    if result.returncode:
        raise SystemExit(f"{Path(command[1]).name if command[0] == sys.executable else Path(command[0]).name} failed; see sim/demand/{log}")
    return result


def candidate_routes(net_path, count, seed):
    """A large pool of plausible routes; routeSampler picks from it. Relative paths keep SUMO's XML headers valid."""
    tools = Path(sumo.SUMO_HOME) / "tools"
    run([sys.executable, str(tools / "randomTrips.py"), "-n", os.path.relpath(net_path, OUT),
         "-o", "candidates.trips.xml", "-r", "candidates.rou.xml", "-b", "0", "-e", str(count), "-p", "1",
         "--fringe-factor", "8", "--min-distance", "400", "-L", "--seed", str(seed), "--validate"], "randomTrips.log")


def fit(net, targets, period):
    tools = Path(sumo.SUMO_HOME) / "tools"
    horizon = WARMUP + MEASURE
    scale = horizon / 3600
    with (OUT / f"{period}.counts.xml").open("w") as out:
        out.write(f'<data>\n  <interval id="{period}" begin="0" end="{horizon}">\n')
        for edge_id, target in targets.items():
            out.write(f'    <edge id="{edge_id}" entered="{round(target["hourly"] * scale)}"/>\n')
        out.write("  </interval>\n</data>\n")
    run([sys.executable, str(tools / "routeSampler.py"), "-r", "candidates.rou.xml",
         "--edgedata-files", f"{period}.counts.xml", "-o", f"{period}.rou.xml",
         "--mismatch-output", f"{period}.mismatch.xml", "--begin", "0", "--end", str(horizon),
         "--attributes", 'departLane="best" departSpeed="max" departPos="random_free"',
         "--seed", "42", "--optimize", "full", "--minimize-vehicles", "1"], f"{period}.routeSampler.log")
    # Fit quality on counted edges only: GEH < 5 is the usual "acceptable" threshold for hourly flows.
    fitted = {}
    for interval in sumolib.xml.parse(str(OUT / f"{period}.mismatch.xml"), "interval"):
        for edge in interval.edge or []:
            fitted[edge.id] = float(edge.measuredCount) / scale
    counted = [(t["hourly"], fitted.get(e, 0.0)) for e, t in targets.items() if t["basis"] == "counted"]
    geh = [math.sqrt(2 * (m - c) ** 2 / (m + c)) if m + c else 0 for c, m in counted]
    vehicles = sum(1 for _ in sumolib.xml.parse(str(OUT / f"{period}.rou.xml"), "vehicle"))
    return {"vehicles": vehicles, "counted_edges": len(counted),
            "counted_target_total": round(sum(c for c, _ in counted)), "counted_fitted_total": round(sum(m for _, m in counted)),
            "geh_under_5_share": round(sum(g < 5 for g in geh) / len(geh), 3) if geh else None,
            "median_geh": round(statistics.median(geh), 2) if geh else None}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--refresh", action="store_true", help="download the LADOT counts again")
    parser.add_argument("--assumed-factor", type=float, default=0.6,
                        help="uncounted arterials get this share of the counted per-lane median; counts are taken on busier roads")
    parser.add_argument("--refresh-routes", action="store_true", help="regenerate the candidate route pool")
    parser.add_argument("--candidates", type=int, default=30000, help="size of the candidate route pool")
    args = parser.parse_args()
    net_path = SIM / "central_la.net.xml"
    if not net_path.exists():
        raise SystemExit("Run scripts/build_network.py first.")
    OUT.mkdir(parents=True, exist_ok=True)
    counts = fetch_counts(args.refresh)
    net = sumolib.net.readNet(str(net_path))
    matched, match_stats = match_counts(net, counts["rows"])
    print("Count matching:", match_stats, "edges with a count:", len(matched))
    if args.refresh_routes or not (OUT / "candidates.rou.xml").exists():
        print("Generating candidate routes")
        candidate_routes(net_path, args.candidates, 7)
    report = {"built_at": datetime.now(timezone.utc).isoformat(), "counts_source": counts["source"], "counts_dataset": DATASET,
              "counts_retrieved_at": counts["retrieved_at"], "count_years": sorted({r["date"][:4] for r in matched.values()}),
              "matching": match_stats, "edges_with_count": len(matched), "assumed_factor": args.assumed_factor, "warmup_s": WARMUP, "measure_s": MEASURE,
              "assumptions": ["Daily counts converted to hourly with the hour_share factor of each period.",
                              "Counts date from 2011-2016 and are not adjusted to today.",
                              f"Uncounted primary, secondary and tertiary roads use {args.assumed_factor:.0%} of the per-lane median of counted roads of that class; "
                              "the factor was lowered until the network stopped gridlocking, so it is a tuning choice, not a measurement.",
                              "Local streets, freeways and ramps have no target; traffic uses them only as routes require."],
              "periods": {}}
    for period, settings in PERIODS.items():
        targets, defaults = build_targets(net, matched, settings["hour_share"], args.assumed_factor)
        (OUT / f"{period}.targets.json").write_text(json.dumps(targets))
        print(f"Fitting routes for {period}")
        report["periods"][period] = {**settings, "class_defaults_per_lane": defaults,
                                     "targets": {"counted": sum(t["basis"] == "counted" for t in targets.values()),
                                                 "assumed": sum(t["basis"] == "assumed" for t in targets.values())},
                                     "fit": fit(net, targets, period)}
    (OUT / "demand_report.json").write_text(json.dumps(report, indent=2))
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
