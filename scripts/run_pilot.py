"""Rebuild the two deterministic downtown simulation periods and map artifact."""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SIM = ROOT / "sim"
SUMO_HOME = Path(sys.prefix) / "lib" / f"python{sys.version_info.major}.{sys.version_info.minor}" / "site-packages" / "sumo"
BIN = SUMO_HOME / "bin"
TOOLS = SUMO_HOME / "tools"


def run(label, command):
    print(label, flush=True)
    env = {**os.environ, "SUMO_HOME": str(SUMO_HOME)}
    result = subprocess.run(command, cwd=ROOT, env=env, text=True, capture_output=True)
    (SIM / f"{label}.log").write_text(result.stdout + result.stderr)
    if result.returncode:
        raise RuntimeError(f"{label} failed; inspect sim/{label}.log")


def main():
    if not (SIM / "sources" / "dtla-roads.osm").exists():
        raise FileNotFoundError("Run scripts/fetch_osm.py first to obtain the OSM extract")
    for source in ("ladot-traffic-counts.json", "emfac2025-la-2026.csv"):
        if not (SIM / "sources" / source).exists():
            raise FileNotFoundError(f"Missing sim/sources/{source}; see README")
    run("network", [str(BIN / "netconvert"), "--osm-files", "sim/sources/dtla-roads.osm",
                    "--output-file", "sim/dtla.net.xml", "--geometry.remove", "--ramps.guess",
                    "--junctions.join", "--tls.guess-signals", "--tls.discard-simple",
                    "--remove-edges.isolated", "--no-turnarounds", "--output.street-names", "true"])
    for period, interval, seed in (("midday", ".9", "26"), ("pm_peak", ".6", "27")):
        run(f"{period}-routes", [sys.executable, str(TOOLS / "randomTrips.py"),
            "-n", "sim/dtla.net.xml", "-o", f"sim/{period}.trips.xml",
            "-r", f"sim/{period}.rou.xml", "-b", "0", "-e", "3600", "-p", interval,
            "--vehicle-class", "passenger", "--fringe-factor", "5", "--min-distance", "500",
            "--validate", "--seed", seed, "--trip-attributes",
            'departLane="best" departSpeed="max"', "--error-log", f"sim/{period}.route-errors.txt"])
        (SIM / f"{period}.add.xml").write_text(
            f'<additional><edgeData id="traffic" file="{period}.traffic.xml" begin="600" end="3600" period="3000" excludeEmpty="true" speedThreshold="0.1"/>'
            f'<edgeData id="emissions" type="emissions" file="{period}.emissions.xml" begin="600" end="3600" period="3000" excludeEmpty="true"/></additional>')
        run(f"{period}-sim", [str(BIN / "sumo"), "-n", "sim/dtla.net.xml", "-r",
            f"sim/{period}.rou.xml", "-a", f"sim/{period}.add.xml", "--begin", "0",
            "--end", "3600", "--step-length", "1", "--time-to-teleport", "300",
            "--no-step-log", "true", "--summary-output", f"sim/{period}.summary.xml",
            "--statistic-output", f"sim/{period}.statistics.xml", "--seed", seed])
    run("artifact", [sys.executable, "scripts/build_emissions.py"])
    print("Built public/data/emissions.json")


if __name__ == "__main__":
    main()
