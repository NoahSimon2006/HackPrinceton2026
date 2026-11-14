"""Re-simulate a proposed design on a cut-out of the SUMO network around one intersection.

The cut-out and its traffic are built once per site and cached under sim/scenarios/.
Baseline and scenario then run on the same cut-out with the same traffic and seed, so
the difference between them is the design's effect inside the cut-out. Traffic that
would reroute outside the cut-out is not captured.
"""
import hashlib
import json
import math
import os
import subprocess
import sys
import threading
import time
import uuid
import xml.etree.ElementTree as ET
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

ROOT = Path(__file__).resolve().parent
SIM = ROOT / "sim"
sys.path.insert(0, str(ROOT / "scripts"))

PERIOD = "pm_peak"
RADIUS_M = 500
SEED, TELEPORT, BLOCKER = 11, 120, 15
# How each design element is represented in the model. Speeds are typical design values, not engineered ones.
SPEED_ELEMENTS = {"chicane": (25, "approach speed limited to about 25 km/h through the curves"),
                  "speed_cushion": (30, "approach speed limited to about 30 km/h over the cushions"),
                  "raised_crossing": (30, "approach speed limited to about 30 km/h at the raised crossing")}
NOT_SIMULATED = {
    "roundabout": "replacing the signal with a roundabout needs a redrawn junction, which this model cannot build automatically",
    "protected_left_turn": "signal phasing changes are not modelled",
    "leading_pedestrian_interval": "signal phasing changes are not modelled",
    "signal_visibility": "no effect on traffic flow in the model",
    "median_refuge": "no effect on traffic flow in the model", "curb_extension": "no effect on traffic flow in the model",
    "high_visibility_crosswalk": "no effect on traffic flow in the model", "lighting": "no effect on traffic flow in the model",
    "daylighting": "no effect on traffic flow in the model", "hardened_centerline": "no effect on traffic flow in the model",
    "protected_bike_lane": "modelled only through any change in lane count", "lane_reduction": None, "other": "not a modelled element",
}


class ScenarioError(Exception):
    def __init__(self, status, message):
        self.status = status
        super().__init__(message)


def _edges(path):
    for _, element in ET.iterparse(path):
        if element.tag == "edge" and "id" in element.attrib:
            yield element.attrib["id"], {k: float(v) for k, v in element.attrib.items() if k != "id"}
            element.clear()


def _measure(folder, approaches):
    """Per-approach and whole-area results for one run."""
    raw = {}
    for name in ("traffic.xml", "emissions.xml"):
        for edge_id, values in _edges(folder / name):
            raw.setdefault(edge_id, {}).update(values)
    def summarise(ids):
        rows = [raw[i] for i in ids if i in raw]
        flow = sum(max(r.get("entered", 0), r.get("left", 0)) for r in rows)
        seconds = sum(r.get("sampledSeconds", 0) for r in rows)
        vehicle_km = sum(r.get("sampledSeconds", 0) * r.get("speed", 0) for r in rows) / 1000
        waiting, co2 = sum(r.get("waitingTime", 0) for r in rows), sum(r.get("CO2_abs", 0) for r in rows)
        return {"flow": round(flow), "idle_s": round(waiting / flow, 1) if flow else 0,
                "stopped_share": round(waiting / seconds, 3) if seconds else 0,
                "speed_kmh": round(vehicle_km * 1000 / seconds * 3.6, 1) if seconds else 0,
                "co2_g_vkm": round(co2 / 1e3 / vehicle_km) if vehicle_km else 0,
                "idle_veh_h": round(waiting / 3600, 1), "co2_kg": round(co2 / 1e6, 1),
                "nox_g": round(sum(r.get("NOx_abs", 0) for r in rows) / 1e3, 1)}
    stats = ET.parse(folder / "statistics.xml").getroot()
    return {"approaches": {i: summarise([i]) for i in approaches}, "area": summarise(list(raw)),
            "teleports": int(stats.find("teleports").get("total")),
            "vehicles": int(stats.find("vehicles").get("inserted"))}


class Scenarios:
    def __init__(self):
        self.jobs, self.lock = {}, threading.RLock()
        self.pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix="scenario")
        self.site_locks = {}

    # ---- public API ----
    def start(self, site, design, on_done=None):
        if not (SIM / "central_la.net.xml").exists() or not (SIM / "demand" / f"{PERIOD}.rou.xml").exists() or not (ROOT / "public/data/sim.json").exists():
            raise ScenarioError(503, "The traffic simulation has not been built. Run the scripts in scripts/ first.")
        sim = json.loads((ROOT / "public/data/sim.json").read_text())
        approaches = sim["sites"].get(site["name"])
        if not approaches:
            raise ScenarioError(404, "This intersection could not be matched to the simulated road network.")
        with self.lock:
            if any(j["status"] == "running" for j in self.jobs.values()):
                raise ScenarioError(429, "A simulation is already running. Wait for it to finish or cancel it.")
            for old in [k for k, j in self.jobs.items() if time.monotonic() - j["clock"] > 3600]:
                del self.jobs[old]
            job = {"id": uuid.uuid4().hex, "site": site["name"], "version": design.get("version"), "status": "running",
                   "message": "Starting", "clock": time.monotonic(), "cancelled": threading.Event(), "process": None, "result": None}
            self.jobs[job["id"]] = job
        self.pool.submit(self._run, job, dict(site), design, approaches, sim, on_done)
        return self.snapshot(job["id"], site["name"])

    def snapshot(self, id_, site_name):
        with self.lock:
            job = self.jobs.get(id_)
            if job is None or job["site"] != site_name:
                raise ScenarioError(404, "This simulation run has expired. Start it again.")
            return {"id": id_, "site": job["site"], "version": job["version"], "status": job["status"], "message": job["message"],
                    "elapsed": round(time.monotonic() - job["clock"]), "result": job["result"]}

    def cancel(self, id_, site_name):
        with self.lock:
            job = self.jobs.get(id_)
            if job and job["site"] == site_name and job["status"] == "running":
                job["cancelled"].set()
                if job["process"]:
                    job["process"].kill()
        return self.snapshot(id_, site_name)

    # ---- internals ----
    def _call(self, job, command, cwd, log):
        import sumo
        if job["cancelled"].is_set():
            raise InterruptedError
        with open(cwd / log, "w") as handle:
            process = subprocess.Popen(command, cwd=cwd, stdout=handle, stderr=subprocess.STDOUT,
                                       env={**os.environ, "SUMO_HOME": str(sumo.SUMO_HOME)})
            with self.lock:
                job["process"] = process
            code = process.wait()
        if job["cancelled"].is_set():
            raise InterruptedError
        if code:
            raise RuntimeError(f"{Path(command[0]).name} failed; see {cwd / log}")

    def _say(self, job, text):
        with self.lock:
            job["message"] = text

    def _simulate(self, job, folder, net_name):
        import sumo
        folder.mkdir(parents=True, exist_ok=True)
        (folder / "outputs.add.xml").write_text(
            '<additional>\n  <edgeData id="traffic" file="traffic.xml" begin="900" end="4500" excludeEmpty="true"/>\n'
            '  <edgeData id="emissions" type="emissions" file="emissions.xml" begin="900" end="4500" excludeEmpty="true"/>\n</additional>\n')
        self._call(job, [str(Path(sumo.SUMO_HOME) / "bin/sumo"), "-n", f"../{net_name}", "-r", "../cut.rou.xml", "-a", "outputs.add.xml",
                         "--begin", "0", "--end", "4500", "--seed", str(SEED), "--time-to-teleport", str(TELEPORT),
                         "--ignore-junction-blocker", str(BLOCKER), "--ignore-route-errors", "--no-step-log", "--no-warnings",
                         "--statistic-output", "statistics.xml"], folder, "sumo.log")

    def _prepare(self, job, site, folder):
        """Cut the network and traffic around the site once, and run the baseline on it."""
        import sumo
        if (folder / "baseline/statistics.xml").exists():
            return
        folder.mkdir(parents=True, exist_ok=True)
        home = Path(sumo.SUMO_HOME)
        dlat = RADIUS_M / 111_195
        dlon = dlat / math.cos(math.radians(site["lat"]))
        box = f"{site['lon'] - dlon},{site['lat'] - dlat},{site['lon'] + dlon},{site['lat'] + dlat}"
        self._say(job, "Cutting out the streets around this intersection")
        self._call(job, [str(home / "bin/netconvert"), "-s", "../../central_la.net.xml", "--keep-edges.in-geo-boundary", box,
                         "--remove-edges.isolated", "-o", "cut.net.xml"], folder, "cut_net.log")
        self._say(job, "Extracting the traffic that passes through this area")
        self._call(job, [sys.executable, str(home / "tools/route/cutRoutes.py"), "cut.net.xml", f"../../demand/{PERIOD}.rou.xml",
                         "--routes-output", "cut.rou.xml", "--orig-net", "../../central_la.net.xml", "--big"], folder, "cut_routes.log")
        self._say(job, "Simulating today's layout")
        self._simulate(job, folder / "baseline", "cut.net.xml")

    def _edits(self, folder, site, design, approaches):
        """Translate the design into edge changes. Returns (patch xml, simulated notes, not-simulated notes)."""
        import sumolib
        from build_demand import key_of
        net = sumolib.net.readNet(str(folder / "cut.net.xml"))
        names = [key_of(part) for part in site["name"].split(" & ")][:2]
        streets = {"first": names[0], "second": names[1] if len(names) > 1 else None}
        incoming = [net.getEdge(i) for i in approaches if net.hasEdge(i)]
        nodes = {e.getToNode() for e in incoming}
        outgoing = [e for n in nodes for e in n.getOutgoing() if key_of(e.getName()) in names]
        changes, simulated, skipped = {}, [], []
        for which, key in streets.items():
            before, after = design[f"{which}_street_lanes_before"], design[f"{which}_street_lanes_after"]
            if key and after != before:
                label = site["name"].split(" & ")[0 if which == "first" else 1]
                for edge in incoming + outgoing:
                    if key_of(edge.getName()) == key:
                        lanes = max(1, round(edge.getLaneNumber() * after / before))
                        if lanes != edge.getLaneNumber():
                            changes.setdefault(edge.getID(), {})["numLanes"] = lanes
                simulated.append(f"{label}: through lanes scaled from {before} to {after} on the blocks next to the junction")
        for element in design["elements"]:
            kind = element["type"]
            if kind in SPEED_ELEMENTS:
                kmh, text = SPEED_ELEMENTS[kind]
                keys = [k for w, k in streets.items() if k and element["street"] in (w, "both")]
                for edge in incoming:
                    if key_of(edge.getName()) in keys:
                        current = changes.get(edge.getID(), {}).get("speed", edge.getSpeed())
                        changes.setdefault(edge.getID(), {})["speed"] = round(min(current, kmh / 3.6), 2)
                simulated.append(f"{element['label']}: {text}")
            elif NOT_SIMULATED.get(kind):
                skipped.append(f"{element['label']}: {NOT_SIMULATED[kind]}")
        patch = "<edges>\n" + "".join(
            f'  <edge id="{edge_id}" ' + " ".join(f'{k}="{v}"' for k, v in attrs.items()) + "/>\n" for edge_id, attrs in changes.items()) + "</edges>\n"
        return patch, simulated, skipped, len(changes)

    def _run(self, job, site, design, approaches, sim, on_done):
        import sumo
        try:
            folder = SIM / "scenarios" / hashlib.sha256(site["name"].encode()).hexdigest()[:12]
            lock = self.site_locks.setdefault(folder.name, threading.Lock())
            with lock:
                self._prepare(job, site, folder)
                patch, simulated, skipped, changed = self._edits(folder, site, design, approaches)
                baseline = _measure(folder / "baseline", approaches)
                result = {"period": sim["periods"][PERIOD]["label"], "radius_m": RADIUS_M, "simulated": simulated, "not_simulated": skipped,
                          "baseline": baseline, "scenario": None, "approach_names": {
                              i: f"{sim['segments'][i]['name']} {sim['segments'][i]['dir']}" for i in approaches if i in sim["segments"]},
                          "caveats": ["Simulated on a cut-out of about " + str(RADIUS_M) + " m around the junction; traffic that would reroute elsewhere is not captured.",
                                      "Signal timing is generated by SUMO and most traffic volumes are assumed.", "One simulation run; small differences may be noise."]}
                if changed:
                    run = folder / f"run_{job['id'][:8]}"
                    run.mkdir()
                    (run / "patch.edg.xml").write_text(patch)
                    self._say(job, "Applying the design to the road network")
                    self._call(job, [str(Path(sumo.SUMO_HOME) / "bin/netconvert"), "-s", "../cut.net.xml", "--edge-files", "patch.edg.xml",
                                     "-o", "scenario.net.xml"], run, "patch.log")
                    self._say(job, "Simulating the proposed layout")
                    self._simulate(job, folder / f"{run.name}_sim", f"{run.name}/scenario.net.xml")
                    result["scenario"] = _measure(folder / f"{run.name}_sim", approaches)
            with self.lock:
                job.update(status="complete", result=result,
                           message="Comparison ready" if changed else "Nothing in this design changes traffic flow in the model")
            if on_done:
                on_done(result)
        except InterruptedError:
            with self.lock:
                job.update(status="cancelled", message="Cancelled.")
        except Exception as error:
            print("Scenario error:", type(error).__name__, error, file=sys.stderr)
            with self.lock:
                job.update(status="failed", message="The simulation could not finish. The design may have produced a network SUMO cannot run.")
