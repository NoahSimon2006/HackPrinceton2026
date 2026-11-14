"""Build the Central LA SUMO road network from OpenStreetMap.

Downloads an OSM extract covering the catalogued intersections, converts it with
netconvert, and writes a report of what was built. Output goes to the Git-ignored
sim/ directory. Re-run with --refresh to download OSM again.
"""
import argparse
import hashlib
import json
import os
import subprocess
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlencode
from urllib.request import Request, urlopen

import sumo
import sumolib

ROOT = Path(__file__).resolve().parents[1]
SIM = ROOT / "sim"
PATCHES = ROOT / "scripts/network_patch"   # optional hand fixes: *.nod.xml, *.edg.xml, *.con.xml, *.tll.xml
OVERPASS = ("https://overpass-api.de/api/map", "https://overpass.kumi.systems/api/map",
            "https://overpass.private.coffee/api/map")   # public mirrors, tried in order
PAD_DEG = 0.004   # roughly four blocks, so boundary roads have somewhere to send traffic
ARTERIALS = ("Figueroa", "7th", "Olympic", "Main", "Broadway", "Flower", "Hope", "Spring", "Hill", "Grand")


def bounding_box():
    sites = json.loads((ROOT / "public/data/la.json").read_text())["sites"]
    lats, lons = [s["lat"] for s in sites], [s["lon"] for s in sites]
    return (round(min(lons) - PAD_DEG, 4), round(min(lats) - PAD_DEG, 4),
            round(max(lons) + PAD_DEG, 4), round(max(lats) + PAD_DEG, 4))


def download_osm(box, target):
    data = b""
    for base in OVERPASS:
        request = Request(f"{base}?{urlencode({'bbox': ','.join(map(str, box))})}",
                          headers={"User-Agent": "crossing-lab-network-build"})
        try:
            with urlopen(request, timeout=180) as response:
                data = response.read()
        except OSError as error:
            print(f"  {base} failed ({error}); trying the next mirror")
            continue
        if b"<osm" in data[:2000]:
            break
    else:
        raise SystemExit("No Overpass server returned an OSM extract. Nothing was replaced.")
    temporary = target.with_suffix(".tmp")
    temporary.write_bytes(data)
    temporary.replace(target)


def convert(osm, net):
    home = Path(sumo.SUMO_HOME)
    command = [
        str(home / "bin/netconvert"), "--osm-files", str(osm), "--output-file", str(net),
        "--type-files", str(home / "data/typemap/osmNetconvert.typ.xml"),
        "--keep-edges.by-vclass", "passenger",
        "--remove-edges.by-type", "highway.service,highway.track,highway.services,highway.unsurfaced,highway.living_street",
        "--remove-edges.isolated", "--geometry.remove", "--roundabouts.guess", "--ramps.guess",
        "--junctions.join", "--junctions.corner-detail", "5",
        "--tls.guess-signals", "--tls.discard-simple", "--tls.join", "--tls.default-type", "actuated",
        "--output.street-names", "--output.original-names", "--proj.utm",
        "--no-turnarounds.except-deadend",
    ]
    for option, pattern in (("--node-files", "*.nod.xml"), ("--edge-files", "*.edg.xml"),
                            ("--connection-files", "*.con.xml"), ("--tllogic-files", "*.tll.xml")):
        files = sorted(PATCHES.glob(pattern)) if PATCHES.is_dir() else []
        if files:
            command += [option, ",".join(map(str, files))]
    result = subprocess.run(command, capture_output=True, text=True, env={**os.environ, "SUMO_HOME": str(home)})
    (SIM / "netconvert.log").write_text(result.stdout + result.stderr)
    if result.returncode or not net.exists():
        raise SystemExit("netconvert failed; see sim/netconvert.log")
    return Counter(line.split(":")[0] for line in result.stderr.splitlines() if line.startswith("Warning"))["Warning"]


def largest_connected_share(net, edges):
    """Share of edges in the largest strongly connected component (iterative Tarjan)."""
    index, low, on_stack, stack, counter, best = {}, {}, set(), [], 0, 0
    for root in edges:
        if root in index:
            continue
        work = [(root, iter(root.getOutgoing()))]
        index[root] = low[root] = counter; counter += 1
        stack.append(root); on_stack.add(root)
        while work:
            edge, successors = work[-1]
            for nxt in successors:
                if nxt not in index:
                    index[nxt] = low[nxt] = counter; counter += 1
                    stack.append(nxt); on_stack.add(nxt)
                    work.append((nxt, iter(nxt.getOutgoing())))
                    break
                if nxt in on_stack:
                    low[edge] = min(low[edge], index[nxt])
            else:
                work.pop()
                if work:
                    low[work[-1][0]] = min(low[work[-1][0]], low[edge])
                if low[edge] == index[edge]:
                    size = 0
                    while True:
                        member = stack.pop(); on_stack.discard(member); size += 1
                        if member is edge:
                            break
                    best = max(best, size)
    return best / len(edges) if edges else 0


def report(net_path, box, warnings, osm):
    net = sumolib.net.readNet(str(net_path))
    edges = [e for e in net.getEdges() if e.allows("passenger")]
    nodes = net.getNodes()
    arterials = {}
    for name in ARTERIALS:
        matched = [e for e in edges if name.lower() in (e.getName() or "").lower()]
        arterials[name] = {
            "edges": len(matched), "km": round(sum(e.getLength() for e in matched) / 1000, 2),
            "lanes_per_direction": dict(sorted(Counter(e.getLaneNumber() for e in matched).items())),
            "signalised_ends": sum(e.getToNode().getType().startswith("traffic_light") for e in matched),
        }
    summary = {
        "built_at": datetime.now(timezone.utc).isoformat(), "sumo_version": sumolib.version.gitDescribe() if hasattr(sumolib, "version") else "unknown",
        "bounding_box_wsen": box, "osm_sha256": hashlib.sha256(osm.read_bytes()).hexdigest(),
        "osm_source": "OpenStreetMap via Overpass API; © OpenStreetMap contributors (ODbL)",
        "edges": len(edges), "lane_km": round(sum(e.getLength() * e.getLaneNumber() for e in edges) / 1000, 1),
        "junctions": len(nodes), "junction_types": dict(Counter(n.getType() for n in nodes).most_common()),
        "traffic_light_programs": len(net.getTrafficLights()),
        "named_edge_share": round(sum(bool(e.getName()) for e in edges) / len(edges), 3),
        "largest_connected_share": round(largest_connected_share(net, edges), 3),
        "netconvert_warnings": warnings, "arterials": arterials,
        "hand_patches": sorted(p.name for p in PATCHES.glob("*.xml")) if PATCHES.is_dir() else [],
        "signal_timing": "Generated by netconvert (actuated). Not LADOT's real signal plans.",
    }
    (SIM / "network_report.json").write_text(json.dumps(summary, indent=2))
    return summary


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--refresh", action="store_true", help="download the OSM extract again")
    args = parser.parse_args()
    SIM.mkdir(exist_ok=True)
    box, osm, net = bounding_box(), SIM / "central_la.osm.xml", SIM / "central_la.net.xml"
    if args.refresh or not osm.exists():
        print("Downloading OpenStreetMap extract for", box)
        download_osm(box, osm)
    print("Converting with netconvert")
    warnings = convert(osm, net)
    summary = report(net, box, warnings, osm)
    print(json.dumps(summary, indent=2))
    if summary["largest_connected_share"] < 0.9:
        print("WARNING: less than 90% of edges are mutually reachable; inspect the network.", file=sys.stderr)


if __name__ == "__main__":
    main()
