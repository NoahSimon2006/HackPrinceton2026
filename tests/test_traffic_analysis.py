"""Deterministic adapter tests; simulation outputs below are test doubles only."""
import json
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

from shapely.geometry import box, LineString

from agent_activity import Activity, RunCancelled
from traffic_analysis import TrafficAnalysis, comparison_facts, crossing_checks, validate_layouts
from traffic_counts import parse_manual
from test_traffic_counts import MANUAL
from test_street_design import geo, X, Y
from test_street_design import checked, metrics
from street_design import rank


IDENTITY = {"site_id": "street:test-site", "revision": 2, "input_revision": 1}
LAYOUTS = [dict(name="north-curb", kind="lane_reallocation", approach="nb", lanes_removed=1, length_m=40, new_use="curb_extension"),
           dict(name="east-bike", kind="lane_reallocation", approach="eb", lanes_removed=1, length_m=60, new_use="bike_lane")]


def context():
    sheet = parse_manual(MANUAL)
    sheet.update(url="https://navigatela.lacity.org/dot/traffic_data/manual_counts/PRIVATE.STREET.pdf", sha256="a" * 64,
                 filename="PRIVATE.STREET.pdf")
    return {"sheet": sheet, "period": "pm", "node_id": "PRIVATE-NODE", "lon": -118.24, "lat": 34.05}


def study():
    edge = Mock()
    edge.getLaneNumber.return_value = 3
    edge.getLength.return_value = 100
    return SimpleNamespace(mapping={"nb": {"chain": [edge], "edge": edge}, "eb": {"chain": [edge], "edge": edge}})


def comparison(recommended="north-curb"):
    baseline = {"seeds": [11, 23, 37], "co2_kg_per_hour": 400, "nox_g_per_hour": 100, "mean_delay_s": 60,
                "completed_per_hour": 4500, "completion_share": .9, "unable_to_enter_share": .01,
                "co2_g_per_completed_vehicle": 90, "max_queue_m": {"nb": 80}, "max_noise_db": {"nb": 72}}
    result = {"period": "pm", "peak_hour": "5-6", "count_date": "2011-11-08", "sheet_url": context()["sheet"]["url"],
              "assumptions": ["Generated signal timing; historical counted demand, not current conditions."],
              "results": {"baseline": baseline, "north-curb": {**baseline, "co2_kg_per_hour": 380},
                          "east-bike": {**baseline, "co2_kg_per_hour": 410}},
              "layouts": {value["name"]: value for value in LAYOUTS},
              "descriptions": {"north-curb": "Convert 1 NB lane for 40 m.", "east-bike": "Convert 1 EB lane for 60 m."},
              "checks": {}, "geometry": {}, "ranking": {"recommended": recommended,
                "reason": None if recommended else "No tested layout is eligible.",
                "verdicts": {"north-curb": {"eligible": bool(recommended), "ineligible_reasons": [] if recommended else ["Mapped access unassessed"], "tradeoffs": [], "score": .03},
                             "east-bike": {"eligible": False, "ineligible_reasons": ["Total CO₂ does not improve"], "tradeoffs": [], "score": -.01}}}}
    for name in ("north-curb", "east-bike"):
        result["checks"][name] = {"footprint_m2": 128, "parcel_overlap_m2": 8, "building_overlap_m2": 0,
            "access_conflicts": 0, "keep_clear_conflict": False, "parcel_evidence": ["outline-1"], "access_evidence": [],
            "candidate_crosswalk_overlaps": 0, "candidate_driveway_overlaps": 0, "marked_crossing_conflict": False}
        result["geometry"][name] = {"type": "Feature", "geometry": geo(box(X, Y, X + 40, Y + 3.2)), "properties": {"role": "proposed"}}
    return result


class TrafficAdapterTest(unittest.TestCase):
    def test_plan_keeps_source_gaps_separate_and_omits_private_inputs(self):
        adapter = TrafficAnalysis(context(), IDENTITY, Activity(), allow_generated_timing=True, policy="environmental-priority-v1")
        adapter.comparison = comparison(None)
        adapter.comparison["status"] = "completed"
        adapter.comparison["ranking"]["verdicts"]["north-curb"]["readiness"] = {"status":"partial", "gaps":["property access remains unassessed"]}
        adapter.comparison["checks"]["north-curb"]["access_conflicts"] = None
        plan = adapter.plan()
        self.assertEqual(plan["readiness"]["missing"], ["property access remains unassessed"])
        self.assertEqual(plan["policy"], "environmental-priority-v1")
        self.assertTrue(any("unassessed" in row["decision"] for row in plan["sourceDecisions"]))
        for forbidden in ("PRIVATE", "coordinates", "node_id", "north_south", "east_west"):
            self.assertNotIn(forbidden, json.dumps(plan))

    def test_input_gate_retains_verified_counts_and_never_runs_assumed_signal_simulation(self):
        with patch("traffic_analysis.Study") as builder, patch("traffic_analysis.evaluate") as evaluate:
            adapter = TrafficAnalysis(context(), IDENTITY, Activity())
            facts, warnings = adapter.prepare()
            outcome = adapter.run(LAYOUTS)
        builder.assert_not_called()
        evaluate.assert_not_called()
        self.assertEqual(outcome["status"], "unavailable")
        self.assertEqual(next(f["value"] for f in facts if f["id"] == "traffic-count-nb-through"), 2614)
        self.assertIn("2011-11-08", json.dumps(facts))
        self.assertNotIn("PRIVATE", json.dumps(facts))
        self.assertEqual(adapter.comparison["input_revision"], 1)
        self.assertTrue(adapter.comparison["input_hash"])
        self.assertFalse(warnings)

    def test_one_comparison_only_and_only_recommended_eligible_proposal_is_published(self):
        events = []
        with patch("traffic_analysis.Study", return_value=study()), patch("traffic_analysis.evaluate", return_value=comparison()) as evaluate:
            adapter = TrafficAnalysis(context(), IDENTITY, Activity(events.append), allow_generated_timing=True)
            outcome = adapter.run(LAYOUTS, keep_clear=[])
            again = adapter.run(LAYOUTS)
        evaluate.assert_called_once()
        self.assertEqual(outcome["status"], "completed")
        self.assertEqual(again["status"], "already_evaluated")
        self.assertEqual(adapter.proposal["design"]["approach"], "nb")
        self.assertEqual(adapter.proposal["input_hash"], adapter.comparison["input_hash"])
        sent = json.dumps(outcome) + json.dumps(events)
        for forbidden in ("PRIVATE", "coordinates", "node_id", "north_south", "east_west", str(context()["lon"]), str(context()["lat"])):
            self.assertNotIn(forbidden, sent)
        self.assertIn("traffic-north-curb-co2", sent)

    def test_no_forced_winner_and_changed_constraint_changes_input_hash(self):
        outputs = []
        with patch("traffic_analysis.Study", return_value=study()), patch("traffic_analysis.evaluate", side_effect=lambda *a, **k: comparison(None)):
            for keep_clear in ([], [geo(box(X + 100, Y, X + 110, Y + 10))]):
                adapter = TrafficAnalysis(context(), IDENTITY, Activity(), allow_generated_timing=True)
                self.assertEqual(adapter.run(LAYOUTS, keep_clear=keep_clear)["status"], "completed")
                self.assertIsNone(adapter.proposal)
                self.assertEqual(set(adapter.alternatives), {"east-bike", "north-curb"})
                for alternative in adapter.alternatives.values():
                    self.assertEqual(alternative["status"], "rejected")
                    self.assertEqual(alternative["input_hash"], adapter.comparison["input_hash"])
                outputs.append(adapter.comparison)
        self.assertNotEqual(outputs[0]["input_hash"], outputs[1]["input_hash"])

    def test_network_failure_preserves_counts_and_sanitizes_errors(self):
        with patch("traffic_analysis.Study", side_effect=RuntimeError("PRIVATE source path")):
            adapter = TrafficAnalysis(context(), IDENTITY, Activity(), allow_generated_timing=True)
            facts, _ = adapter.prepare()
        self.assertFalse(adapter.ready)
        self.assertTrue(any(f["id"] == "traffic-count-total" for f in facts))
        self.assertNotIn("PRIVATE", json.dumps(facts))

    def test_simulation_failure_is_explicit_and_cancellation_propagates(self):
        with patch("traffic_analysis.Study", return_value=study()), patch("traffic_analysis.evaluate", side_effect=RuntimeError("PRIVATE process path")):
            adapter = TrafficAnalysis(context(), IDENTITY, Activity(), allow_generated_timing=True)
            self.assertEqual(adapter.run(LAYOUTS)["status"], "unavailable")
            self.assertIsNone(adapter.proposal)
            self.assertEqual(adapter.comparison["results"], {})
        with patch("traffic_analysis.Study", return_value=study()), patch("traffic_analysis.evaluate", side_effect=RunCancelled()):
            adapter = TrafficAnalysis(context(), IDENTITY, Activity(), allow_generated_timing=True)
            with self.assertRaises(RunCancelled):
                adapter.run(LAYOUTS)
        self.assertTrue(adapter.facts)

    def test_failed_proposal_validation_cannot_leave_a_text_only_winner(self):
        with patch("traffic_analysis.Study", return_value=study()), patch("traffic_analysis.evaluate", return_value=comparison()), \
             patch("proposal.from_traffic_comparison", side_effect=ValueError("Invalid proposal geometry")):
            adapter = TrafficAnalysis(context(), IDENTITY, Activity(), allow_generated_timing=True)
            outcome = adapter.run(LAYOUTS)
        self.assertEqual(outcome["status"], "unavailable")
        self.assertEqual(adapter.comparison["status"], "unavailable")
        self.assertIsNone(adapter.comparison["ranking"]["recommended"])
        self.assertIsNone(adapter.proposal)
        self.assertTrue(any(f["id"] == "traffic-count-total" for f in adapter.facts))
        self.assertFalse(any(f["id"] == "traffic-north-curb-verdict" for f in adapter.facts))

    def test_renamed_or_cosmetically_changed_layouts_are_not_distinct(self):
        duplicate = {**LAYOUTS[0], "name": "north-bike", "new_use": "bike_lane"}
        with self.assertRaises(ValueError):
            validate_layouts([LAYOUTS[0], duplicate])
        with self.assertRaises(ValueError):
            validate_layouts([LAYOUTS[0]])
        self.assertEqual(len(validate_layouts(LAYOUTS)), 2)

    def test_candidates_remain_unverified_and_crossing_constraints_are_spatial(self):
        design = box(X, Y, X + 40, Y + 4)
        detections = [{"geometry": geo(box(X + 10, Y, X + 12, Y + 4)),
                       "properties": {"label": "Crosswalk", "evidenceId": "candidate-1"}},
                      {"geometry": geo(box(X + 100, Y, X + 102, Y + 4)),
                       "properties": {"label": "Driveway", "evidenceId": "candidate-2"}}]
        checks = crossing_checks(design, detections, [geo(LineString([(X + 15, Y - 5), (X + 15, Y + 5)]))])
        self.assertEqual(checks["candidate_crosswalk_overlaps"], 1)
        self.assertEqual(checks["candidate_driveway_overlaps"], 0)
        self.assertTrue(checks["marked_crossing_conflict"])
        self.assertEqual(checks["candidate_evidence"], ["candidate-1"])

    def test_failed_or_malformed_detections_block_an_otherwise_eligible_layout(self):
        design = box(X, Y, X + 40, Y + 4)
        results = {"baseline": metrics(), "candidate": metrics(co2=350)}
        for detections in (None, [{"geometry": {"type": "Polygon", "coordinates": []},
                                   "properties": {"label": "Crosswalk"}}], ["invalid feature"]):
            with self.subTest(detections=detections):
                checks = crossing_checks(design, detections, [])
                self.assertEqual(checks["detection_status"], "unavailable")
                self.assertIsNone(checks["candidate_crosswalk_overlaps"])
                self.assertIsNone(checks["candidate_driveway_overlaps"])
                ranked = rank(results, {"candidate": {**checked(), **checks}})
                self.assertIsNone(ranked["recommended"])
                self.assertIn("crossing and driveway candidate checks remain unassessed",
                              ranked["verdicts"]["candidate"]["ineligible_reasons"])
        empty = crossing_checks(design, [], [])
        self.assertEqual(empty["detection_status"], "empty")
        self.assertEqual(empty["candidate_crosswalk_overlaps"], 0)
        self.assertEqual(rank(results, {"candidate": {**checked(), **empty}})["recommended"], "candidate")

    def test_missing_candidate_facts_report_unassessed_not_zero(self):
        result = comparison(None)
        result["checks"]["north-curb"].update(crossing_checks(box(X, Y, X + 40, Y + 4), None, []))
        facts = comparison_facts(result)
        missing = next(item for item in facts if item["id"] == "traffic-north-curb-candidate_crosswalk_overlaps")
        self.assertEqual(missing["basis"], "availability")
        self.assertIn("Unassessed", missing["value"])


if __name__ == "__main__":
    unittest.main()
