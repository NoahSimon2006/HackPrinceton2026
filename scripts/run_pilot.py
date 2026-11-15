"""Reproduce the archived illustrative random-demand runs; never publish live data."""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SIM = ROOT / "sim"
ARCHIVE = SIM / "archived-pilot"
sys.path.insert(0, str(ROOT))
import sumo_tools


def run(label, command):
    print(label, flush=True)
    return sumo_tools.run(command, cwd=ARCHIVE, log=f"{label}.log")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--allow-illustrative", action="store_true", help="Explicitly reproduce archived assumed-demand runs; not current planning evidence.")
    if not parser.parse_args().allow_illustrative:
        parser.error("Archived random-demand simulation requires --allow-illustrative. It is not used by live planning.")
    if not (SIM / "sources" / "dtla-roads.osm").exists():
        raise FileNotFoundError("Run scripts/fetch_osm.py first to obtain the OSM extract")
    ARCHIVE.mkdir(parents=True, exist_ok=True)
    run("network", [sumo_tools.binary("netconvert"), "--osm-files", str(SIM / "sources/dtla-roads.osm"),
                    "--output-file", "dtla.net.xml", "--geometry.remove", "--ramps.guess",
                    "--junctions.join", "--tls.guess-signals", "--tls.discard-simple",
                    "--remove-edges.isolated", "--no-turnarounds", "--output.street-names", "true"])
    for period, interval, seed in (("midday", ".9", "26"), ("pm_peak", ".6", "27")):
        run(f"{period}-routes", [sys.executable, sumo_tools.tool("randomTrips.py"),
            "-n", "dtla.net.xml", "-o", f"{period}.trips.xml",
            "-r", f"{period}.rou.xml", "-b", "0", "-e", "3600", "-p", interval,
            "--vehicle-class", "passenger", "--fringe-factor", "5", "--min-distance", "500",
            "--validate", "--seed", seed, "--trip-attributes",
            'departLane="best" departSpeed="max"', "--error-log", f"{period}.route-errors.txt"])
        (ARCHIVE / f"{period}.add.xml").write_text(
            f'<additional><edgeData id="traffic" file="{period}.traffic.xml" begin="600" end="3600" period="3000" excludeEmpty="true" speedThreshold="0.1"/>'
            f'<edgeData id="emissions" type="emissions" file="{period}.emissions.xml" begin="600" end="3600" period="3000" excludeEmpty="true"/></additional>')
        run(f"{period}-sim", [sumo_tools.binary("sumo"), "-n", "dtla.net.xml", "-r",
            f"{period}.rou.xml", "-a", f"{period}.add.xml", "--begin", "0",
            "--end", "3600", "--step-length", "1", "--time-to-teleport", "300",
            "--no-step-log", "true", "--summary-output", f"{period}.summary.xml",
            "--statistic-output", f"{period}.statistics.xml", "--seed", seed])
    print("Archived illustrative SUMO outputs rebuilt under sim/archived-pilot/. No live map artifact was published.")


if __name__ == "__main__":
    main()
