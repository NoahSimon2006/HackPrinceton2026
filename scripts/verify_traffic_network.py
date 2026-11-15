"""Run a real-count Main/1st comparison and verify restrictions and trip accounting.

This smoke check uses the same two bounded lane-reallocation test designs as the
earlier checkpoint review. It does not publish a recommendation, call an agent,
or substitute invented demand for unavailable counts.
"""
import argparse
from collections import Counter
import json
from pathlib import Path
import sys
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from discovery import load_discovery, traffic_context
from street_design import Layout, edge_patch, evaluate
from traffic_sim import Study, SimulationError, SEEDS, WARMUP_S, MEASURE_S


class Progress:
    def check(self):
        pass

    def event(self, *args):
        print(" ".join(args), flush=True)


def verify(output):
    output.mkdir(parents=True, exist_ok=True)
    snapshot = load_discovery("street")
    sites, selected = [], None
    for layer in snapshot["layers"]:
        if layer["id"] != "turning" or layer["status"] != "ready":
            continue
        for feature in layer["features"]:
            props = feature["properties"]
            reference = {"version": snapshot["version"], "layer": "turning", "feature": feature["id"]}
            context = traffic_context(reference, *props["center"])
            try:
                study = Study(**context)
                row = {"site": props["label"], "status": "ready", "checks": study.restriction_checks}
                if context["sheet"]["filename"] == "MAIN.1ST.111108-MAN.pdf":
                    selected = study
            except SimulationError as error:
                row = {"site": props["label"], "status": "unavailable", "reason": str(error)}
            sites.append(row)
            print(row["site"], row["status"], flush=True)
    if selected is None:
        raise RuntimeError("The verified Main/1st source is unavailable; no substitute demand is used.")
    layouts = [Layout(name="eb-curb-60", kind="lane_reallocation", approach="eb", lanes_removed=1,
                      length_m=60., new_use="curb_extension"),
               Layout(name="wb-walk-80", kind="lane_reallocation", approach="wb", lanes_removed=1,
                      length_m=80., new_use="pedestrian_space")]
    comparison = evaluate(selected, layouts, activity=Progress())
    prepared = {"baseline": (selected.net_path, None)}
    for layout in layouts:
        patch = edge_patch(layout, selected)
        prepared[layout.name] = (selected.layout_network(layout.name, patch), patch)
    runs, demands = [], []
    for name, (network, patch) in prepared.items():
        folder, routes, _ = selected._prepare_run(name, network, patch)
        trips = ET.parse(routes).getroot().findall("trip")
        cohort = [t for t in trips if WARMUP_S <= float(t.get("depart")) < WARMUP_S + MEASURE_S]
        movements = Counter()
        for trip in cohort:
            movements["_".join(trip.get("id").split("_")[:2])] += 1
        assert dict(movements) == selected.counted["movements"], "Generated trips differ from the actual count sheet"
        demands.append({"layout": name, "cohort": len(cohort), "movements": dict(movements)})
        for seed in SEEDS:
            result = json.loads((folder / f"seed{seed}" / "result.json").read_text())["result"]
            assert result["offered"] == selected.counted["total"]
            assert result["completed"] + result["unfinished"] + result["not_inserted"] == result["offered"]
            assert result["teleports"] == 0
            assert result["loaded_total"] == len(trips)
            assert result["completed"] > 0 and result["co2_sumo_g"] > 0 and result["nox_sumo_g"] > 0
            runs.append({"layout": name, "folder": str(folder / f"seed{seed}"), **result})
    report = {"discovery_version": snapshot["version"], "sites": sites, "runs": runs, "demand_checks": demands,
              "study_folder": str(selected.folder), "passed_runs": len(runs)}
    (output / "verification.json").write_text(json.dumps(report, indent=2))
    (output / "comparison.json").write_text(json.dumps(comparison, indent=2))
    print(f"Verified {len(runs)} runs, exact counted movements and cohort conservation. Recommendation: {comparison['ranking']['recommended']}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    verify(args.output_dir)
