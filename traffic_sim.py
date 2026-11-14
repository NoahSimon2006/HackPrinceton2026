"""Simulate one intersection with counted LADOT turning movements as demand.

Demand comes only from an official manual count sheet: every approach and movement
(left / through / right) is a SUMO flow at its counted hourly rate, split into cars,
dual-wheeled trucks and buses using that sheet's own vehicle-class counts.

One input is an assumption, and it is reported with every result: signal control is
SUMO's generated actuated program, identical in the baseline and every layout, because
LADOT signal timing plans are not published.

Baseline and layouts run on the same cut-out network, the same demand and the same
random seeds, so differences are the layout's effect inside the study area.
"""
from __future__ import annotations

import json
import math
import re
import statistics
import xml.etree.ElementTree as ET
from hashlib import sha256
from pathlib import Path

import sumo_tools

ROOT = Path(__file__).resolve().parent
SIM = ROOT / "sim"
NETWORK = SIM / "dtla.net.xml"
WARMUP_S, MEASURE_S = 600, 3600
SEEDS = (11, 23, 37)
RADIUS_M = 320
CHAIN_M = 220
CARB_G_PER_MILE = {"CO2": 387.1437, "NOx": 0.1308}  # EMFAC2025 v2.1.1, LA (SC) 2026 running exhaust, VMT-weighted
TURNS = {"left": ("l", "L"), "through": ("s",), "right": ("r", "R")}
ASSUMPTIONS = [
    "Signal control is SUMO's generated actuated program; LADOT timing plans are not published. It is identical in every layout.",
    "Vehicles enter at the counted hourly rate for the sheet's peak hour, after a 10-minute warm-up at the same rate.",
    "Lane counts and turn permissions come from OpenStreetMap unless an explicit override is listed.",
    "Absolute CO2 is scaled to CARB's 2026 Los Angeles fleet rate; differences between layouts come from the simulation.",
]


class SimulationError(RuntimeError):
    pass


def street_key(name: str) -> str:
    text = (name or "").upper()
    text = re.sub(r"\b(\d+)\s*(ST|ND|RD|TH)\b", r"\1", text)
    for pattern, replacement in [(r"\b(NORTH|SOUTH|EAST|WEST|N|S|E|W)\b", ""), (r"\b(AVENUE|AVE|AV)\b", "AV"),
                                 (r"\b(STREET|STR|ST)\b", "ST"), (r"\b(BOULEVARD|BLVD|BL)\b", "BL"),
                                 (r"\b(PLACE|PL)\b", "PL"), (r"\b(DRIVE|DR)\b", "DR"), (r"\b(ROAD|RD)\b", "RD")]:
        text = re.sub(pattern, replacement, text)
    return " ".join(re.findall(r"[A-Z0-9]+", text))


def heading(edge, end=True):
    shape = edge.getShape()
    (x1, y1), (x2, y2) = (shape[-2], shape[-1]) if end else (shape[0], shape[1])
    return math.degrees(math.atan2(x2 - x1, y2 - y1)) % 360


def _site_folder(node_id: str, sheet: dict) -> Path:
    digest = sha256(f"{node_id}|{sheet['sha256']}|{NETWORK.stat().st_size}".encode()).hexdigest()[:12]
    return SIM / "scenarios" / digest


def cut_network(node_id: str, lon: float, lat: float, folder: Path) -> Path:
    folder.mkdir(parents=True, exist_ok=True)
    out = folder / "cut.net.xml"
    if out.exists():
        return out
    dlat = RADIUS_M / 111_195
    dlon = dlat / math.cos(math.radians(lat))
    sumo_tools.run([sumo_tools.binary("netconvert"), "-s", NETWORK, "--keep-edges.in-geo-boundary",
                    f"{lon - dlon},{lat - dlat},{lon + dlon},{lat + dlat}", "--keep-edges.by-vclass", "passenger",
                    "--remove-edges.isolated", "--tls.rebuild", "--tls.default-type", "actuated",
                    "--no-turnarounds", "-o", out.name], cwd=folder, log="cut.log")
    return out


def approaches(net, node_id: str, sheet: dict) -> dict:
    """Map each counted approach and movement to network edges: {nb: {edge, chain, moves{left: out_edge}}}."""
    node = net.getNode(node_id)
    streets = {"ns": street_key(sheet["north_south"]), "ew": street_key(sheet["east_west"])}
    result = {}
    for name, axis, sign in (("nb", "ns", 1), ("sb", "ns", -1), ("eb", "ew", 1), ("wb", "ew", -1)):
        counted = sum(sum(sheet["approaches"][name][h].values()) for h in sheet["hours"])
        options = []
        for edge in node.getIncoming():
            if street_key(edge.getName()) != streets[axis] or not edge.allows("passenger"):
                continue
            angle = math.radians(heading(edge))
            component = math.cos(angle) if axis == "ns" else math.sin(angle)
            if component * sign > 0.3:
                options.append(edge)
        if not options:
            if counted:
                raise SimulationError(f"Counted {name.upper()} approach has no matching network edge.")
            continue
        edge = max(options, key=lambda e: e.getLaneNumber())
        moves = {}
        for move, letters in TURNS.items():
            targets = [c.getTo() for c in edge.getOutgoing() for c in edge.getConnections(c)
                       if c.getDirection() in letters and c.getTo().allows("passenger")]
            if targets:
                moves[move] = max(targets, key=lambda e: (bool(e.getName()), e.getLaneNumber()))
        result[name] = {"edge": edge, "chain": upstream(edge), "moves": moves}
    return result


def upstream(edge, length=CHAIN_M):
    chain, total, current = [edge], edge.getLength(), edge
    key = street_key(edge.getName())
    while total < length:
        options = [e for e in current.getIncoming() if street_key(e.getName()) == key and e not in chain
                   and e.allows("passenger") and abs((heading(e) - heading(current, end=False) + 180) % 360 - 180) < 40]
        if not options:
            break
        current = max(options, key=lambda e: e.getLaneNumber())
        chain.insert(0, current)
        total += current.getLength()
    return chain


def downstream(edge, length=CHAIN_M):
    chain, total, current = [edge], edge.getLength(), edge
    key = street_key(edge.getName())
    while total < length:
        options = [e for e in current.getOutgoing() if street_key(e.getName()) == key and e not in chain
                   and e.allows("passenger") and abs((heading(e, end=False) - heading(current) + 180) % 360 - 180) < 40]
        if not options:
            break
        current = max(options, key=lambda e: e.getLaneNumber())
        chain.append(current)
        total += current.getLength()
    return chain


def demand(sheet: dict, period: str, mapping: dict) -> tuple[list[dict], dict]:
    """Flows from the sheet's peak hour; returns flows and the counted totals they reproduce."""
    from traffic_counts import peak_hour
    hour = peak_hour(sheet, period)
    flows, counted = [], {}
    for name, approach in mapping.items():
        values = sheet["approaches"][name]
        six_hours = sum(sum(values[h].values()) for h in sheet["hours"]) or 1
        heavy = sheet.get("heavy_vehicles", {})
        truck = min(.5, heavy.get("dual_wheeled", {}).get(name, 0) / six_hours)
        bus = min(.3, heavy.get("buses", {}).get(name, 0) / six_hours)
        for move, vehicles in values[hour].items():
            if not vehicles:
                continue
            out = approach["moves"].get(move)
            if out is None:
                raise SimulationError(f"{name.upper()} {move} is counted ({vehicles}) but the network has no such movement.")
            counted[f"{name}_{move}"] = vehicles
            for vtype, share in (("car", 1 - truck - bus), ("truck", truck), ("bus", bus)):
                rate = vehicles * share
                if rate > 0:
                    flows.append({"id": f"{name}_{move}_{vtype}", "type": vtype, "rate": rate,
                                  "from": approach["chain"][0].getID(), "via": [approach["edge"].getID(), out.getID()],
                                  "to": downstream(out)[-1].getID()})
    return flows, {"hour": hour, "movements": counted, "total": sum(counted.values())}


def write_routes(flows, path: Path):
    end = WARMUP_S + MEASURE_S
    lines = ['<routes>',
             '  <vType id="car" vClass="passenger"/>',
             '  <vType id="truck" vClass="truck"/>',
             '  <vType id="bus" vClass="bus"/>']
    for f in flows:
        lines.append(f'  <flow id="{f["id"]}" type="{f["type"]}" begin="0" end="{end}" vehsPerHour="{f["rate"]:.3f}" '
                     f'from="{f["from"]}" to="{f["to"]}" via="{" ".join(f["via"])}" departLane="best" departSpeed="max"/>')
    path.write_text("\n".join(lines + ["</routes>"]) + "\n", encoding="utf-8")


def _xml_rows(path: Path, tag: str):
    for _, element in ET.iterparse(path):
        if element.tag == tag:
            yield element.attrib
            element.clear()


def run_once(net_path: Path, routes: Path, folder: Path, seed: int, watched: dict) -> dict:
    folder.mkdir(parents=True, exist_ok=True)
    end = WARMUP_S + MEASURE_S
    (folder / "out.add.xml").write_text(
        f'<additional><edgeData id="t" file="traffic.xml" begin="{WARMUP_S}" end="{end}" excludeEmpty="true"/>'
        f'<edgeData id="e" type="emissions" file="emissions.xml" begin="{WARMUP_S}" end="{end}" excludeEmpty="true"/>'
        f'<edgeData id="n" type="harmonoise" file="noise.xml" begin="{WARMUP_S}" end="{end}" excludeEmpty="true"/></additional>')
    sumo_tools.run([sumo_tools.binary("sumo"), "-n", net_path, "-r", routes, "-a", "out.add.xml", "--begin", "0",
                    "--end", str(end + 900), "--seed", str(seed), "--time-to-teleport", "300", "--no-step-log", "true",
                    "--tripinfo-output", "tripinfo.xml", "--queue-output", "queue.xml",
                    "--statistic-output", "statistics.xml", "--duration-log.disable", "true", "--no-warnings", "true"],
                   cwd=folder, log="sumo.log", timeout=900)
    trips = [t for t in _xml_rows(folder / "tripinfo.xml", "tripinfo")
             if WARMUP_S <= float(t["depart"]) - float(t.get("departDelay", 0)) < end]
    stats = ET.parse(folder / "statistics.xml").getroot()
    vehicles = stats.find("vehicles").attrib
    loaded_window = round(sum(1 for _ in trips))
    emissions = {k: 0.0 for k in ("CO2_abs", "NOx_abs")}
    for edge in _xml_rows(folder / "emissions.xml", "edge"):
        for key in emissions:
            emissions[key] += float(edge.get(key, 0))
    distance = sum(float(e.get("sampledSeconds", 0)) * float(e.get("speed", 0)) for e in _xml_rows(folder / "traffic.xml", "edge"))
    queues = {name: 0.0 for name in watched}
    lane_owner = {f"{edge}_{i}": name for name, edges in watched.items() for edge, lanes in edges for i in range(lanes)}
    for _, element in ET.iterparse(folder / "queue.xml"):
        if element.tag == "data":
            time = float(element.get("timestep", 0))
            if WARMUP_S <= time < end:
                for lane in element.iter("lane"):
                    owner = lane_owner.get(lane.get("id"))
                    if owner:
                        queues[owner] = max(queues[owner], float(lane.get("queueing_length", 0)))
            element.clear()
    noise = {}
    noise_rows = {e["id"]: float(e.get("noise", 0)) for e in _xml_rows(folder / "noise.xml", "edge")}
    for name, edges in watched.items():
        levels = [noise_rows[e] for e, _ in edges if noise_rows.get(e)]
        noise[name] = round(max(levels), 1) if levels else None
    delays = [float(t["timeLoss"]) + float(t.get("departDelay", 0)) for t in trips]
    return {"seed": seed, "completed": loaded_window,
            "inserted_total": int(vehicles["inserted"]), "loaded_total": int(vehicles["loaded"]),
            "not_inserted_total": int(vehicles["loaded"]) - int(vehicles["inserted"]),
            "teleports": int(stats.find("teleports").get("total")),
            "mean_delay_s": round(statistics.fmean(delays), 1) if delays else None,
            "co2_sumo_g": emissions["CO2_abs"] / 1000, "nox_sumo_g": emissions["NOx_abs"] / 1000,
            "vehicle_miles": distance / 1609.344, "max_queue_m": {k: round(v, 1) for k, v in queues.items()},
            "max_noise_db": noise}


def summarise(runs: list[dict], demand_total: int, carb_factor: dict) -> dict:
    mean = lambda key: statistics.fmean(r[key] for r in runs)
    completed = mean("completed")
    expected = demand_total * MEASURE_S / 3600
    names = runs[0]["max_queue_m"].keys()
    return {
        "seeds": [r["seed"] for r in runs],
        "demand_vehicles_per_hour": demand_total,
        "completed_per_hour": round(completed * 3600 / MEASURE_S),
        "completion_share": round(completed / expected, 4) if expected else None,
        "unable_to_enter_share": round(mean("not_inserted_total") / max(mean("loaded_total"), 1), 4),
        "mean_delay_s": round(mean("mean_delay_s"), 1),
        "max_queue_m": {n: round(max(r["max_queue_m"][n] for r in runs), 1) for n in names},
        "max_noise_db": {n: max((r["max_noise_db"][n] for r in runs if r["max_noise_db"][n] is not None), default=None) for n in names},
        "co2_kg_per_hour": round(mean("co2_sumo_g") * carb_factor["CO2"] / 1000 * 3600 / MEASURE_S, 1),
        "nox_g_per_hour": round(mean("nox_sumo_g") * carb_factor["NOx"] * 3600 / MEASURE_S, 1),
        "vehicle_miles_per_hour": round(mean("vehicle_miles") * 3600 / MEASURE_S, 1),
        "teleports": max(r["teleports"] for r in runs),
        "spread": {"mean_delay_s": [min(r["mean_delay_s"] for r in runs), max(r["mean_delay_s"] for r in runs)],
                   "co2_sumo_kg": [round(min(r["co2_sumo_g"] for r in runs) / 1000, 1), round(max(r["co2_sumo_g"] for r in runs) / 1000, 1)]},
    }


class Study:
    """Prepared cut-out network, mapped approaches and counted demand for one site and period."""

    def __init__(self, node_id: str, lon: float, lat: float, sheet: dict, period: str = "pm"):
        import sumolib
        if not NETWORK.exists():
            raise SimulationError("Road network missing. Run scripts/fetch_osm.py and netconvert (see README).")
        self.node_id, self.sheet, self.period = node_id, sheet, period
        self.folder = _site_folder(node_id, sheet)
        self.net_path = cut_network(node_id, lon, lat, self.folder)
        self.net = sumolib.net.readNet(str(self.net_path))
        self.mapping = approaches(self.net, node_id, sheet)
        self.flows, self.counted = demand(sheet, period, self.mapping)
        self.watched = {name: [(e.getID(), e.getLaneNumber()) for e in a["chain"]] for name, a in self.mapping.items()}

    def layout_network(self, name: str, edge_patch: str | None) -> Path:
        if not edge_patch:
            return self.net_path
        folder = self.folder / f"layout-{name}"
        folder.mkdir(parents=True, exist_ok=True)
        (folder / "patch.edg.xml").write_text(edge_patch, encoding="utf-8")
        sumo_tools.run([sumo_tools.binary("netconvert"), "-s", self.net_path, "--edge-files", "patch.edg.xml",
                        "--tls.rebuild", "--tls.default-type", "actuated", "-o", "layout.net.xml"], cwd=folder, log="netconvert.log")
        return folder / "layout.net.xml"

    def simulate(self, name: str, net_path: Path, watched=None) -> list[dict]:
        folder = self.folder / f"{self.period}-{name}"
        folder.mkdir(parents=True, exist_ok=True)
        routes = folder / "demand.rou.xml"
        write_routes(self.flows, routes)
        return [run_once(net_path, routes, folder / f"seed{s}", s, watched or self.watched) for s in SEEDS]

    def compare(self, layouts: dict[str, str | None]) -> dict:
        """Run baseline plus layouts ({name: edge patch xml}); identical demand and seeds for each."""
        base_runs = self.simulate("baseline", self.net_path)
        sumo_rate = statistics.fmean(r["co2_sumo_g"] / max(r["vehicle_miles"], 1e-9) for r in base_runs)
        nox_rate = statistics.fmean(r["nox_sumo_g"] / max(r["vehicle_miles"], 1e-9) for r in base_runs)
        factor = {"CO2": CARB_G_PER_MILE["CO2"] / sumo_rate, "NOx": CARB_G_PER_MILE["NOx"] / max(nox_rate, 1e-9)}
        results = {"baseline": summarise(base_runs, self.counted["total"], factor)}
        for name, patch in layouts.items():
            runs = self.simulate(name, self.layout_network(name, patch))
            results[name] = summarise(runs, self.counted["total"], factor)
        return {"period": self.period, "peak_hour": self.counted["hour"], "counted_movements": self.counted["movements"],
                "count_date": self.sheet["date"], "sheet_url": self.sheet["url"], "results": results,
                "assumptions": ASSUMPTIONS, "study_radius_m": RADIUS_M,
                "lanes": {n: a["edge"].getLaneNumber() for n, a in self.mapping.items()}}


def find_node(sheet: dict) -> tuple[str, float, float]:
    """Network junction where the sheet's two named streets meet."""
    import sumolib
    net = sumolib.net.readNet(str(NETWORK))
    wanted = {street_key(sheet["north_south"]), street_key(sheet["east_west"])}
    for node in net.getNodes():
        names = {street_key(e.getName()) for e in node.getIncoming() + node.getOutgoing() if e.getName()}
        if wanted <= names:
            lon, lat = net.convertXY2LonLat(*node.getCoord())
            return node.getID(), lon, lat
    raise SimulationError("The counted intersection was not found in the road network.")


if __name__ == "__main__":
    import sys
    from traffic_counts import load_sheet
    sheet = load_sheet(sys.argv[1] if len(sys.argv) > 1 else "MAIN.1ST.111108-MAN.pdf", ROOT / "private" / "discovery" / "sheets")
    node, lon, lat = find_node(sheet)
    study = Study(node, lon, lat, sheet, "pm")
    print(json.dumps(study.compare({}), indent=1))
