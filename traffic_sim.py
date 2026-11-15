"""Simulate one intersection with counted LADOT turning movements as demand.

Demand comes only from an official manual count sheet: every approach and movement
(left / through / right) is a SUMO flow at its counted hourly rate, split into cars,
dual-wheeled trucks and buses using that sheet's own vehicle-class counts.

Signal control is SUMO-generated, rather than a measured LADOT timing plan. The
comparison also discloses network geometry, vehicle-class allocation, warm-up and
study-boundary modeling choices in ASSUMPTIONS; observed counts are never replaced
with road-class demand defaults.

Baseline and layouts run on the same cut-out network, the same demand and the same
random seeds. Results describe each layout with its regenerated signal connections
under that controlled model, not observed traffic or a validated operational forecast.
"""
from __future__ import annotations

import json
import csv
import math
import statistics
import subprocess
import time
import xml.etree.ElementTree as ET
from concurrent.futures import ThreadPoolExecutor, as_completed
from hashlib import sha256
from pathlib import Path
from threading import Event

import sumo_tools
from street_names import street_key

ROOT = Path(__file__).resolve().parent
SIM = ROOT / "sim"
NETWORK = SIM / "dtla.net.xml"
WARMUP_S, MEASURE_S = 600, 3600
SEEDS = (11, 23, 37)
RADIUS_M = 200
CHAIN_M = 150
CUT_VERSION = "5-verified-restrictions"
SIM_VERSION = "8-verified-restrictions"
MAX_WORKERS = 3
FLEET_SOURCE = SIM / "sources" / "emfac2025-la-2026.csv"
FLEET_URL = "https://emfac.arb.ca.gov/emissions-inventory/3b6469b056eb7e5a47b65c0c96415b33d5e20812"
TURNS = {"left": ("l", "L"), "through": ("s",), "right": ("r", "R")}
ASSUMPTIONS = [
    "Signal control is SUMO-generated actuated timing, not a measured LADOT signal plan. The same generation settings are used for every layout; movement links are rebuilt for each geometry.",
    "Vehicles enter at the counted hourly rate for the sheet's peak hour, after a 10-minute warm-up at the same rate.",
    "Lane counts use the OSM-derived network and are not field-verified. Represented static single-node OSM turn restrictions are checked for cars, trucks and buses after conversion and layout changes. Unresolved conditional or via-way restrictions in a study block simulation. OSM completeness and historical applicability are not field-verified.",
    "Other junctions inside the 200 m study area use generated priority rules, not measured signal control, to isolate the counted intersection.",
    "Vehicle-class proportions use the count sheet's full observation period; the sheet does not report a class split for each peak-hour movement.",
    "Demand is held at the historical peak-hour rate during warm-up. Completion includes a 15-minute clearance period; unfinished trips and vehicles still waiting to enter remain in the denominator.",
    "Absolute CO2 is scaled to CARB's 2026 Los Angeles fleet rate; differences between layouts come from the simulation.",
]


class SimulationError(RuntimeError):
    pass


def _check(activity=None):
    if activity is not None:
        activity.check()


class _RunControl:
    def __init__(self, activity=None):
        self.activity = activity
        self.cancelled = Event()

    def check(self):
        if self.cancelled.is_set():
            from agent_activity import RunCancelled
            raise RunCancelled("Traffic comparison canceled.")
        _check(self.activity)


def _run(command, *, cwd, log, activity=None, timeout=600):
    """Cancellable subprocess: never leave a SUMO process behind after a disconnect."""
    _check(activity)
    started = time.monotonic()
    with Path(cwd, log).open("w", encoding="utf-8") as output:
        process = subprocess.Popen([str(c) for c in command], cwd=cwd, env=sumo_tools.environment(),
                                   stdout=output, stderr=subprocess.STDOUT, text=True)
        try:
            while process.poll() is None:
                _check(activity)
                if time.monotonic() - started > timeout:
                    raise SimulationError("Traffic calculation exceeded its time budget.")
                time.sleep(.1)
            _check(activity)
            if process.returncode:
                raise SimulationError(f"{Path(str(command[0])).name} could not complete; inspect its local run log.")
        except BaseException:
            if process.poll() is None:
                process.terminate()
                try:
                    process.wait(timeout=2)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait()
            raise


def file_hash(path):
    digest = sha256()
    with Path(path).open("rb") as source:
        for block in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def verify_restrictions(network_path):
    """Do not simulate a cutout whose represented source restrictions are unresolved."""
    from scripts.verify_turn_restrictions import audit
    osm = SIM / "sources" / "dtla-roads.osm"
    if not osm.is_file():
        raise SimulationError("OSM turn-restriction source is missing. Rebuild the road network.")
    result = audit(osm, network_path)
    unresolved = [r for r in result["relations"] if r["status"] == "failed" or r["status"].startswith("unverified_")]
    if unresolved:
        raise SimulationError("This study contains unresolved OSM turn restrictions (including conditional, complex or invalid rules). Traffic comparison is unavailable until they are resolved; counts are not altered to bypass them.")
    return {"osm_sha256": result["osm_sha256"], "network_sha256": result["network_sha256"],
            "counts": result["counts"], "scope": result["scope"]}


def validate_network_sources():
    manifest = SIM / "network-build.json"
    try:
        data = json.loads(manifest.read_text())
        valid = (data["network_sha256"] == file_hash(NETWORK)
                 and data["osm_sha256"] == file_hash(SIM / "sources" / "dtla-roads.osm"))
    except (OSError, ValueError, KeyError, TypeError):
        valid = False
    if not valid:
        raise SimulationError("Road network source verification is missing or stale. Run scripts/build_road_network.py and rebuild discovery.")


def fleet_rates(path=None):
    """Recompute calibration from the retrieved official CSV, never a silent default factor."""
    path = Path(path or FLEET_SOURCE)
    if not path.exists():
        raise SimulationError("Official CARB fleet-rate CSV is missing; emissions comparison is unavailable.")
    lines = path.read_text(encoding="utf-8-sig").splitlines()
    start = next((i for i, line in enumerate(lines) if line.startswith("Region,")), None)
    if start is None:
        raise SimulationError("CARB fleet-rate CSV has no recognized header.")
    rows = list(csv.DictReader(lines[start:]))
    if not rows or any(r.get("Region") != "Los Angeles (SC)" or r.get("Calendar Year") != "2026" for r in rows):
        raise SimulationError("CARB fleet-rate CSV does not match the disclosed region and year.")
    try:
        values = [{key: float(r[key]) for key in ("Total VMT", "CO2_RUNEX", "NOx_RUNEX")} for r in rows]
    except (ValueError, TypeError, KeyError):
        raise SimulationError("CARB fleet-rate CSV contains missing or invalid numeric values.") from None
    if any(not math.isfinite(v) or v < 0 for row in values for v in row.values()):
        raise SimulationError("CARB fleet-rate CSV requires finite, nonnegative VMT and running-exhaust rates.")
    distance = sum(r["Total VMT"] for r in values)
    if not math.isfinite(distance) or distance <= 0:
        raise SimulationError("CARB fleet-rate CSV has no positive VMT.")
    rates = {key: sum(r["Total VMT"] * r[key + "_RUNEX"] for r in values) / distance
             for key in ("CO2", "NOx")}
    if any(not math.isfinite(value) or value <= 0 for value in rates.values()):
        raise SimulationError("CARB fleet-rate calibration requires finite positive rates.")
    return rates


def heading(edge, end=True):
    shape = edge.getShape()
    (x1, y1), (x2, y2) = (shape[-2], shape[-1]) if end else (shape[0], shape[1])
    return math.degrees(math.atan2(x2 - x1, y2 - y1)) % 360


def _site_folder(node_id: str, sheet: dict) -> Path:
    converter = file_hash(sumo_tools.binary("netconvert"))
    digest = sha256(f"{node_id}|{sheet['sha256']}|{file_hash(NETWORK)}|{converter}|{CUT_VERSION}|{RADIUS_M}|{CHAIN_M}".encode()).hexdigest()[:20]
    return SIM / "scenarios" / digest


def cut_network(node_id: str, lon: float, lat: float, folder: Path, *, activity=None) -> Path:
    folder.mkdir(parents=True, exist_ok=True)
    out = folder / "cut.net.xml"
    if out.exists():
        return out
    dlat = RADIUS_M / 111_195
    dlon = dlat / math.cos(math.radians(lat))
    _run([sumo_tools.binary("netconvert"), "-s", NETWORK, "--keep-edges.in-geo-boundary",
                    f"{lon - dlon},{lat - dlat},{lon + dlon},{lat + dlat}", "--keep-edges.by-vclass", "passenger",
                    "--remove-edges.isolated", "--tls.rebuild", "--tls.default-type", "actuated",
                    "--no-turnarounds", "-o", "raw.net.xml"], cwd=folder, log="cut.log", activity=activity)
    import sumolib
    raw = sumolib.net.readNet(str(folder / "raw.net.xml"))
    nodes = [f'  <node id="{n.getID()}" x="{n.getCoord()[0]}" y="{n.getCoord()[1]}" type="priority"/>'
             for n in raw.getNodes() if n.getID() != node_id and n.getType() not in ("priority", "dead_end")]
    (folder / "isolate.nod.xml").write_text("<nodes>\n" + "\n".join(nodes) + "\n</nodes>\n", encoding="utf-8")
    _run([sumo_tools.binary("netconvert"), "-s", "raw.net.xml", "--node-files", "isolate.nod.xml",
          "--tls.rebuild", "--tls.default-type", "actuated", "-o", "cut.pending.net.xml"],
         cwd=folder, log="isolate.log", activity=activity)
    (folder / "cut.pending.net.xml").replace(out)
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
                       if c.getDirection() in letters and c.allows("passenger")
                       and c.getFromLane().allows("passenger") and c.getToLane().allows("passenger")]
            if targets:
                moves[move] = max(targets, key=lambda e: (bool(e.getName()), e.getLaneNumber()))
        result[name] = {"edge": edge, "chain": upstream(edge), "moves": moves}
    return result


def upstream(edge, length=CHAIN_M):
    chain, total, current = [edge], edge.getLength(), edge
    key = street_key(edge.getName())
    while total < length:
        options = [e for e in current.getIncoming() if street_key(e.getName()) == key and e not in chain
                   and e.allows("passenger") and any(c.allows("passenger") for c in e.getConnections(current))
                   and abs((heading(e) - heading(current, end=False) + 180) % 360 - 180) < 40]
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
                   and e.allows("passenger") and any(c.allows("passenger") for c in current.getConnections(e))
                   and abs((heading(e, end=False) - heading(current) + 180) % 360 - 180) < 40]
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
        classes = [heavy.get(kind, {}).get(name) for kind in ("dual_wheeled", "buses")]
        if any(type(value) is not int or value < 0 for value in classes):
            raise SimulationError("Counted truck/bus composition is missing or invalid; no all-car fleet is substituted.")
        truck, bus = [value / six_hours for value in classes]
        if min(truck, bus) < 0 or truck + bus > 1:
            raise SimulationError("Counted vehicle classes exceed the reported approach total.")
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
                    vclass = "passenger" if vtype == "car" else vtype
                    if not any(c.allows(vclass) and c.getFromLane().allows(vclass) and c.getToLane().allows(vclass)
                               for c in approach["edge"].getConnections(out)):
                        raise SimulationError(f"Counted {name.upper()} {move} demand conflicts with the network's {vtype} turn permissions.")
                    flows.append({"id": f"{name}_{move}_{vtype}", "type": vtype, "rate": rate,
                                  "from": approach["chain"][0].getID(), "via": [approach["edge"].getID(), out.getID()],
                                  "to": downstream(out)[-1].getID()})
    return flows, {"hour": hour, "movements": counted, "total": sum(counted.values())}


def write_routes(flows, path: Path):
    """Explicit departures make the offered measurement cohort auditable, even when it cannot enter."""
    root = ET.Element("routes")
    for kind, vclass in (("car", "passenger"), ("truck", "truck"), ("bus", "bus")):
        ET.SubElement(root, "vType", id=kind, vClass=vclass)
    trips = []
    groups = {}
    for flow in flows:
        groups.setdefault(flow["id"].rsplit("_", 1)[0], []).append(flow)
    for begin, duration, cohort in ((0, WARMUP_S, "warmup"), (WARMUP_S, MEASURE_S, "measured")):
        for members in groups.values():
            desired = [f["rate"] * duration / 3600 for f in members]
            allocated = [math.floor(value) for value in desired]
            remaining = round(sum(desired)) - sum(allocated)
            order = sorted(range(len(members)), key=lambda i: (desired[i] - allocated[i], members[i]["id"]), reverse=True)
            for i in order[:remaining]:
                allocated[i] += 1
            for f, count in zip(members, allocated):
                for number in range(count):
                    depart = begin + (number + .5) * duration / count
                    trips.append((depart, {"id": f'{f["id"]}.{cohort}.{number}', "type": f["type"], "depart": f"{depart:.6f}",
                                   "from": f["from"], "to": f["to"], "via": " ".join(dict.fromkeys(f["via"])),
                                   "departLane": "best", "departSpeed": "max"}))
    for _, attributes in sorted(trips, key=lambda item: (item[0], item[1]["id"])):
        ET.SubElement(root, "trip", attributes)
    ET.ElementTree(root).write(path, encoding="utf-8", xml_declaration=True)


def cohort_stats(rows, departures: dict, *, end: float) -> dict:
    """Use intended departure IDs, not only successful arrivals, as the accounting boundary."""
    rows = {row["id"]: row for row in rows}
    completed, inserted, delays = 0, 0, []
    for ident, intended in departures.items():
        row = rows.get(ident)
        if row is None or float(row.get("depart", -1)) < 0:
            delays.append(end - intended)
            continue
        inserted += 1
        arrived = float(row.get("arrival", -1)) >= 0 and not row.get("vaporized")
        completed += int(arrived)
        delays.append(float(row.get("timeLoss", 0)) + float(row.get("departDelay", 0)))
    return {"offered": len(departures), "completed": completed, "inserted": inserted,
            "not_inserted": len(departures) - inserted, "unfinished": inserted - completed,
            "mean_delay_s": statistics.fmean(delays) if delays else None}


def _xml_rows(path: Path, tag: str):
    for _, element in ET.iterparse(path):
        if element.tag == tag:
            row = dict(element.attrib)
            if tag == "tripinfo":
                emission = element.find("emissions")
                if emission is not None:
                    row.update(emission.attrib)
            yield row
            element.clear()


def queue_maxima(path: Path, watched: dict, *, begin: float, end: float) -> dict:
    """Peak physical queue across each fixed approach chain, invariant to edge splitting.

    At each timestamp, take the longest lane queue within each edge, then add those
    edge lengths along the approach. Summing lane queues would double-count parallel
    lanes; taking a single edge maximum would reward a layout merely for splitting it.
    """
    queues = {name: 0.0 for name in watched}
    lane_owner = {f"{edge}_{i}": (name, edge)
                  for name, edges in watched.items() for edge, lanes in edges for i in range(lanes)}
    samples = 0
    for _, element in ET.iterparse(path):
        if element.tag != "data":
            continue
        if begin <= float(element.get("timestep", 0)) < end:
            samples += 1
            edge_queues = {}
            for lane in element.iter("lane"):
                owner = lane_owner.get(lane.get("id"))
                if owner:
                    length = float(lane.get("queueing_length", "nan"))
                    if not math.isfinite(length) or length < 0:
                        raise SimulationError("Queue output contains an invalid measured length.")
                    edge_queues[owner] = max(edge_queues.get(owner, 0.0), length)
            totals = {name: 0.0 for name in watched}
            for (name, _), length in edge_queues.items():
                totals[name] += length
            for name, length in totals.items():
                queues[name] = max(queues[name], length)
        element.clear()
    if not samples:
        raise SimulationError("Queue output has no samples in the measurement interval.")
    return queues


def run_once(net_path: Path, routes: Path, folder: Path, seed: int, watched: dict, *, activity=None) -> dict:
    folder.mkdir(parents=True, exist_ok=True)
    end = WARMUP_S + MEASURE_S
    fingerprint = sha256(json.dumps(dict(network=file_hash(net_path), routes=file_hash(routes), seed=seed,
                                        watched=watched, version=SIM_VERSION, warmup=WARMUP_S, measure=MEASURE_S,
                                        binary=file_hash(sumo_tools.binary("sumo"))), sort_keys=True).encode()).hexdigest()
    cache = folder / "result.json"
    _check(activity)
    if cache.exists():
        saved = json.loads(cache.read_text())
        if saved.get("fingerprint") == fingerprint:
            return saved["result"]
    (folder / "out.add.xml").write_text(
        f'<additional><edgeData id="t" file="traffic.xml" begin="{WARMUP_S}" end="{end}" excludeEmpty="true"/>'
        f'<edgeData id="e" type="emissions" file="emissions.xml" begin="{WARMUP_S}" end="{end}" excludeEmpty="true"/>'
        f'<edgeData id="n" type="harmonoise" file="noise.xml" begin="{WARMUP_S}" end="{end}" excludeEmpty="true"/></additional>')
    _run([sumo_tools.binary("sumo"), "-n", net_path, "-r", routes, "-a", "out.add.xml", "--begin", "0",
                    "--end", str(end + 900), "--seed", str(seed), "--time-to-teleport", "-1", "--no-step-log", "true",
                    "--tripinfo-output", "tripinfo.xml", "--queue-output", "queue.xml",
                    "--device.emissions.probability", "1",
                    "--tripinfo-output.write-unfinished", "true", "--tripinfo-output.write-undeparted", "true",
                    "--statistic-output", "statistics.xml", "--duration-log.disable", "true", "--no-warnings", "true"],
                   cwd=folder, log="sumo.log", timeout=900, activity=activity)
    departures = {t["id"]: float(t["depart"]) for t in _xml_rows(routes, "trip") if WARMUP_S <= float(t["depart"]) < end}
    trip_rows = list(_xml_rows(folder / "tripinfo.xml", "tripinfo"))
    cohort = cohort_stats(trip_rows, departures, end=end + 900)
    stats = ET.parse(folder / "statistics.xml").getroot()
    vehicles = stats.find("vehicles").attrib
    measured_trips = [row for row in trip_rows if row["id"] in departures and float(row.get("depart", -1)) >= 0]
    try:
        values = [{key: float(row[key]) for key in ("CO2_abs", "NOx_abs", "routeLength")} for row in measured_trips]
        if any(not math.isfinite(value) or value < 0 for row in values for value in row.values()):
            raise ValueError("Invalid trip output")
    except (KeyError, ValueError, TypeError):
        raise SimulationError("Measured trip emissions or distance are missing or invalid; no zero values were substituted.") from None
    emissions = {key: sum(row[key] for row in values) for key in ("CO2_abs", "NOx_abs")}
    distance = sum(row["routeLength"] for row in values)
    queues = queue_maxima(folder / "queue.xml", watched, begin=WARMUP_S, end=end)
    noise = {}
    noise_rows = {e["id"]: float(e.get("noise", 0)) for e in _xml_rows(folder / "noise.xml", "edge")}
    for name, edges in watched.items():
        levels = [noise_rows[e] for e, _ in edges if noise_rows.get(e)]
        # Each edgeData value is an hourly average. The maximum is across spatial
        # edges (and later seeds), never a temporal peak. Keep output precision for
        # the strict sound-energy gate rather than rounding to a tenth of a dB.
        noise[name] = max(levels) if levels else None
    result = {"seed": seed, **cohort,
            "inserted_total": int(vehicles["inserted"]), "loaded_total": int(vehicles["loaded"]),
            "not_inserted_total": int(vehicles["loaded"]) - int(vehicles["inserted"]),
            "teleports": int(stats.find("teleports").get("total", 0)),
            "co2_sumo_g": emissions["CO2_abs"] / 1000, "nox_sumo_g": emissions["NOx_abs"] / 1000,
            "vehicle_miles": distance / 1609.344, "max_queue_m": queues,
            "max_noise_db": noise}
    _check(activity)
    pending = cache.with_suffix(".pending.json")
    pending.write_text(json.dumps({"fingerprint": fingerprint, "result": result}), encoding="utf-8")
    pending.replace(cache)
    return result


def summarise(runs: list[dict], demand_total: int, carb_factor: dict) -> dict:
    mean = lambda key: statistics.fmean(r[key] for r in runs)
    completed = mean("completed")
    expected = mean("offered")
    names = runs[0]["max_queue_m"].keys()
    return {
        "seeds": [r["seed"] for r in runs],
        "demand_vehicles_per_hour": demand_total,
        "completed_per_hour": round(completed * 3600 / MEASURE_S),
        "offered_vehicles": round(expected),
        "unfinished_vehicles": round(mean("unfinished")),
        "unable_to_enter_vehicles": round(mean("not_inserted")),
        "completion_share": completed / expected if expected else None,
        "unable_to_enter_share": mean("not_inserted") / expected if expected else None,
        "mean_delay_s": mean("mean_delay_s"),
        "max_queue_m": {n: max(r["max_queue_m"][n] for r in runs) for n in names},
        "max_noise_db": {n: max(r["max_noise_db"][n] for r in runs)
                         if all(r["max_noise_db"].get(n) is not None for r in runs) else None for n in names},
        "co2_kg_per_hour": mean("co2_sumo_g") * carb_factor["CO2"] / 1000 * 3600 / MEASURE_S,
        "nox_g_per_hour": mean("nox_sumo_g") * carb_factor["NOx"] * 3600 / MEASURE_S,
        "vehicle_miles_per_hour": round(mean("vehicle_miles") * 3600 / MEASURE_S, 1),
        "co2_g_per_completed_vehicle": round(mean("co2_sumo_g") * carb_factor["CO2"] / completed, 1) if completed else None,
        "teleports": max(r["teleports"] for r in runs),
        "spread": {"mean_delay_s": [min(r["mean_delay_s"] for r in runs), max(r["mean_delay_s"] for r in runs)],
                   "co2_sumo_kg": [round(min(r["co2_sumo_g"] for r in runs) / 1000, 1), round(max(r["co2_sumo_g"] for r in runs) / 1000, 1)]},
    }


class Study:
    """Prepared cut-out network, mapped approaches and counted demand for one site and period."""

    def __init__(self, node_id: str, lon: float, lat: float, sheet: dict, period: str = "pm", *, activity=None):
        import sumolib
        if not NETWORK.exists():
            raise SimulationError("Road network missing. Run scripts/fetch_osm.py and scripts/build_road_network.py (see README).")
        validate_network_sources()
        self.node_id, self.sheet, self.period = node_id, sheet, period
        self.folder = _site_folder(node_id, sheet)
        self.net_path = cut_network(node_id, lon, lat, self.folder, activity=activity)
        self.restriction_checks = {"baseline": verify_restrictions(self.net_path)}
        self.net = sumolib.net.readNet(str(self.net_path))
        self.mapping = approaches(self.net, node_id, sheet)
        self.flows, self.counted = demand(sheet, period, self.mapping)
        self.watched = {name: [(e.getID(), e.getLaneNumber()) for e in a["chain"]] for name, a in self.mapping.items()}

    def layout_network(self, name: str, edge_patch: str | None, *, activity=None) -> Path:
        if not edge_patch:
            self.restriction_checks[name] = self.restriction_checks["baseline"]
            return self.net_path
        identity = sha256((file_hash(self.net_path) + edge_patch + CUT_VERSION).encode()).hexdigest()[:20]
        folder = self.folder / f"layout-{identity}"
        folder.mkdir(parents=True, exist_ok=True)
        if (folder / "layout.net.xml").exists():
            self.restriction_checks[name] = verify_restrictions(folder / "layout.net.xml")
            return folder / "layout.net.xml"
        (folder / "patch.edg.xml").write_text(edge_patch, encoding="utf-8")
        _run([sumo_tools.binary("netconvert"), "-s", self.net_path, "--edge-files", "patch.edg.xml",
              "--tls.rebuild", "--tls.default-type", "actuated", "-o", "layout.pending.net.xml"],
             cwd=folder, log="netconvert.log", activity=activity)
        self.restriction_checks[name] = verify_restrictions(folder / "layout.pending.net.xml")
        (folder / "layout.pending.net.xml").replace(folder / "layout.net.xml")
        return folder / "layout.net.xml"

    def _run_inputs(self, net_path, patch=None):
        """Keep the original approach ID after a split; route departures start on its new upstream piece."""
        import sumolib
        changed = sumolib.net.readNet(str(net_path))
        starts = {}
        if patch:
            for edge in ET.fromstring(patch).findall("edge"):
                for split in edge.findall("split"):
                    if float(split.get("pos", 0)) != 0:
                        starts[edge.get("id")] = split.get("idBefore")
        flows = [{**f, "from": starts.get(f["from"], f["from"])} for f in self.flows]
        watched = {}
        for name, approach in self.mapping.items():
            ids = [ident for edge in approach["chain"]
                   for ident in ([starts[edge.getID()], edge.getID()] if edge.getID() in starts else [edge.getID()])]
            watched[name] = [(ident, changed.getEdge(ident).getLaneNumber()) for ident in ids]
        return flows, watched

    def _prepare_run(self, name, net_path, patch=None):
        identity = sha256((file_hash(net_path) + json.dumps(self.flows, sort_keys=True) + SIM_VERSION).encode()).hexdigest()[:20]
        folder = self.folder / f"{self.period}-{identity}"
        folder.mkdir(parents=True, exist_ok=True)
        routes = folder / "demand.rou.xml"
        flows, watched = self._run_inputs(net_path, patch)
        write_routes(flows, routes)
        return folder, routes, watched

    def simulate(self, name: str, net_path: Path, watched=None, *, activity=None, patch=None) -> list[dict]:
        folder, routes, inferred = self._prepare_run(name, net_path, patch)
        with ThreadPoolExecutor(max_workers=MAX_WORKERS) as pool:
            futures = [pool.submit(run_once, net_path, routes, folder / f"seed{s}", s, watched or inferred, activity=activity)
                       for s in SEEDS]
            return [future.result() for future in futures]

    def compare(self, layouts: dict[str, str | None], *, activity=None) -> dict:
        """Run baseline plus layouts ({name: edge patch xml}); identical demand and seeds for each."""
        _check(activity)
        if "baseline" in layouts:
            raise ValueError("The baseline is reserved for the unchanged source network.")
        rates = fleet_rates()
        prepared = {"baseline": (self.net_path, None)}
        prepared.update({name: (self.layout_network(name, patch, activity=activity), patch) for name, patch in layouts.items()})
        all_runs = {name: [] for name in prepared}
        control = _RunControl(activity)
        with ThreadPoolExecutor(max_workers=MAX_WORKERS) as pool:
            futures = {}
            for name, (network, patch) in prepared.items():
                folder, routes, watched = self._prepare_run(name, network, patch)
                for seed in SEEDS:
                    future = pool.submit(run_once, network, routes, folder / f"seed{seed}", seed, watched, activity=control)
                    futures[future] = name
            try:
                for future in as_completed(futures):
                    _check(activity)
                    name = futures[future]
                    all_runs[name].append(future.result())
                    if activity is not None:
                        activity.event("traffic", "simulation", "running", "Completed a paired traffic run.")
            except BaseException:
                control.cancelled.set()
                for future in futures:
                    future.cancel()
                raise
        for runs in all_runs.values():
            runs.sort(key=lambda r: r["seed"])
        base_runs = all_runs["baseline"]
        sumo_rate = statistics.fmean(r["co2_sumo_g"] / max(r["vehicle_miles"], 1e-9) for r in base_runs)
        nox_rate = statistics.fmean(r["nox_sumo_g"] / max(r["vehicle_miles"], 1e-9) for r in base_runs)
        if sumo_rate <= 0 or nox_rate <= 0:
            raise SimulationError("Baseline produced no positive emissions calibration rate.")
        factor = {"CO2": rates["CO2"] / sumo_rate, "NOx": rates["NOx"] / nox_rate}
        results = {"baseline": summarise(base_runs, self.counted["total"], factor)}
        for name in layouts:
            runs = all_runs[name]
            results[name] = summarise(runs, self.counted["total"], factor)
        return {"period": self.period, "peak_hour": self.counted["hour"], "counted_movements": self.counted["movements"],
                "count_date": self.sheet["date"], "sheet_url": self.sheet["url"], "results": results,
                "assumptions": ASSUMPTIONS + ["Emissions and completion use the same explicit trip cohort scheduled in the measured hour, including unfinished trips through the 15-minute clearance. Delay includes vehicles waiting to enter; unfinished-trip delay is a lower bound.",
                                               "Queue length is the sum of the longest lane queue on each edge of the fixed approach chain at a timestamp, then the maximum over the measured hour and seeds. Splitting an edge does not shorten the measured approach.",
                                               "Roadway noise is the maximum approach hourly source level: maximum of SUMO Harmonoise hourly mean edge levels across approach edges and seeds. It is not a temporal noise peak or building exposure."],
                "study_radius_m": RADIUS_M, "simulation_version": SIM_VERSION,
                "turn_restriction_checks": self.restriction_checks,
                "fleet_source": {"url": FLEET_URL, "sha256": file_hash(FLEET_SOURCE), "rates_g_per_mile": rates,
                                 "method": "VMT-weighted EMFAC2025 v2.1.1 LA (SC) 2026 running-exhaust rates, derived from 133-row official CSV; baseline normalization reused for all layouts."},
                "input_hash": sha256(json.dumps({"network": file_hash(self.net_path), "sheet": self.sheet["sha256"],
                    "fleet": file_hash(FLEET_SOURCE), "flows": self.flows, "layouts": layouts, "seeds": SEEDS, "version": SIM_VERSION}, sort_keys=True).encode()).hexdigest(),
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
