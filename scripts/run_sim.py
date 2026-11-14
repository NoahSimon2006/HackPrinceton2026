"""Run the baseline SUMO simulation for each period and random seed.

Writes per-road traffic measures (speed, waiting time, time loss, flow) and emissions
(CO2, NOx, PMx, fuel) for the measured hour after a discarded warm-up. Output goes to
sim/runs/<period>/seed<N>/ with a manifest of versions, seeds and input hashes.
"""
import argparse
import hashlib
import json
import os
import subprocess
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path

import sumo
import sumolib

ROOT = Path(__file__).resolve().parents[1]
SIM = ROOT / "sim"
SEEDS = (11, 23, 37)


def sha(path):
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def run_one(period, seed, warmup, measure, args):
    teleport = args.teleport
    out = SIM / args.runs_dir / period / f"seed{seed}"
    out.mkdir(parents=True, exist_ok=True)
    end = warmup + measure
    (out / "outputs.add.xml").write_text(
        "<additional>\n"
        f'  <edgeData id="traffic" file="traffic.xml" begin="{warmup}" end="{end}" excludeEmpty="true"/>\n'
        f'  <edgeData id="emissions" type="emissions" file="emissions.xml" begin="{warmup}" end="{end}" excludeEmpty="true"/>\n'
        "</additional>\n")
    # Relative paths: SUMO copies its command line into XML comments, which must not contain "--".
    rel = lambda path: os.path.relpath(path, out)
    command = [str(Path(sumo.SUMO_HOME) / "bin/sumo"), "-n", rel(SIM / "central_la.net.xml"),
               "-r", rel(SIM / "demand" / f"{period}.rou.xml"), "-a", "outputs.add.xml",
               "--begin", "0", "--end", str(end), "--seed", str(seed),
               "--time-to-teleport", str(teleport), "--ignore-route-errors", "--no-step-log", "--no-warnings",
               "--statistic-output", "statistics.xml", "--duration-log.statistics",
               "--scale", str(args.scale), "--ignore-junction-blocker", str(args.junction_blocker)]
    started = time.monotonic()
    result = subprocess.run(command, capture_output=True, text=True, cwd=out,
                            env={**os.environ, "SUMO_HOME": str(sumo.SUMO_HOME)})
    (out / "sumo.log").write_text(result.stdout + result.stderr)
    if result.returncode:
        raise RuntimeError(f"SUMO failed for {period} seed {seed}; see {out / 'sumo.log'}")
    stats = next(iter(sumolib.xml.parse(str(out / "statistics.xml"), "statistics")))
    vehicles, teleports, trips = stats.vehicles[0], stats.teleports[0], stats.vehicleTripStatistics[0]
    return {"seed": seed, "wall_seconds": round(time.monotonic() - started, 1),
            "inserted": int(vehicles.inserted), "still_waiting_to_enter": int(vehicles.waiting),
            "running_at_end": int(vehicles.running), "teleports": int(teleports.total),
            "mean_trip_seconds": float(trips.duration), "mean_waiting_seconds": float(trips.waitingTime),
            "mean_time_loss_seconds": float(trips.timeLoss), "mean_speed_mps": float(trips.speed)}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--periods", nargs="*", help="default: every period in the demand report")
    parser.add_argument("--seeds", nargs="*", type=int, default=list(SEEDS))
    parser.add_argument("--teleport", type=int, default=120, help="seconds a blocked vehicle waits before SUMO moves it on")
    parser.add_argument("--workers", type=int, default=3)
    parser.add_argument("--scale", type=float, default=1.0, help="multiply demand; below 1 thins every route evenly")
    parser.add_argument("--junction-blocker", type=int, default=15,
                        help="seconds after which a vehicle stuck inside a junction stops blocking cross traffic (-1: never)")
    parser.add_argument("--runs-dir", default="runs", help="output folder under sim/")
    args = parser.parse_args()
    report_path = SIM / "demand/demand_report.json"
    if not report_path.exists():
        raise SystemExit("Run scripts/build_demand.py first.")
    demand = json.loads(report_path.read_text())
    periods = args.periods or list(demand["periods"])
    warmup, measure = demand["warmup_s"], demand["measure_s"]
    manifest = {"ran_at": datetime.now(timezone.utc).isoformat(), "sumo_version": sumolib.version.gitDescribe(),
                "emission_model": "SUMO default passenger-car class (HBEFA family, European fleet); not California's EMFAC",
                "warmup_s": warmup, "measure_s": measure, "time_to_teleport_s": args.teleport, "demand_scale": args.scale, "junction_blocker_s": args.junction_blocker,
                "network_sha256": sha(SIM / "central_la.net.xml"), "periods": {}}
    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        for period in periods:
            print(f"Running {period} with seeds {args.seeds}")
            runs = list(pool.map(lambda seed: run_one(period, seed, warmup, measure, args), args.seeds))
            manifest["periods"][period] = {"routes_sha256": sha(SIM / "demand" / f"{period}.rou.xml"),
                                           "planned_vehicles": demand["periods"][period]["fit"]["vehicles"], "runs": runs}
            for run in runs:
                print(" ", run)
    (SIM / args.runs_dir / "manifest.json").write_text(json.dumps(manifest, indent=2))
    print(f"Wrote sim/{args.runs_dir}/manifest.json")


if __name__ == "__main__":
    main()
