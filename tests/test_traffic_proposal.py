import copy
import unittest

from pydantic import ValidationError

from proposal import Design, Proposal, from_traffic_comparison


def result(delay, co2_trip, queue=90.0, noise=72.0):
    return {"seeds": [11, 23, 37], "completion_share": .9, "unable_to_enter_share": .03, "mean_delay_s": delay,
            "co2_g_per_completed_vehicle": co2_trip, "co2_kg_per_hour": 300.0, "max_queue_m": {"nb": queue, "eb": 40.0},
            "max_noise_db": {"nb": noise, "eb": None}}


def comparison(parcel=None, curb_cuts=None, recommended="eb-curb"):
    square = [[-118.2435, 34.0521], [-118.2433, 34.0521], [-118.2433, 34.0522], [-118.2435, 34.0522], [-118.2435, 34.0521]]
    return {"sheet_url": "https://navigatela.lacity.org/dot/traffic_data/manual_counts/MAIN.1ST.111108-MAN.pdf",
            "period": "pm", "assumptions": ["Signal control is generated."],
            "results": {"baseline": result(80, 300), "eb-curb": result(70, 280)},
            "layouts": {"eb-curb": {"name": "eb-curb", "kind": "lane_reallocation", "approach": "eb", "lanes_removed": 1,
                                    "length_m": 60, "new_use": "curb_extension"}},
            "descriptions": {"eb-curb": "Convert 1 of 3 EB approach lanes to planted curb extension for the last 60 m before the stop line."},
            "checks": {"eb-curb": {"parcel_overlap_m2": parcel, "building_overlap_m2": 0.0 if parcel is not None else None,
                                   "access_conflicts": curb_cuts, "footprint_m2": 192.0, "keep_clear_conflict": False}},
            "ranking": {"recommended": recommended, "reason": None if recommended else "No eligible layout scores better than today's layout.",
                        "verdicts": {"eb-curb": {"eligible": True, "ineligible_reasons": []}}},
            "geometry": {"eb-curb": {"type": "Feature", "geometry": {"type": "Polygon", "coordinates": [square]}, "properties": {}}}}


class TrafficProposalTest(unittest.TestCase):
    def test_metrics_come_from_the_simulated_comparison(self):
        p = from_traffic_comparison(comparison(), "eb-curb", site_id="turning-x", revision=2, input_revision=3)
        self.assertFalse(p.development_fixture)
        delay = next(m for m in p.metrics if m.id == "mean_delay")
        self.assertEqual((delay.baseline, delay.proposed), (80, 70))
        self.assertTrue(all(m.revision == 2 and m.input_hash == p.input_hash for m in p.metrics))
        self.assertIn("Recommended", p.recommendation)

    def test_missing_sponsor_evidence_stays_unassessed(self):
        p = from_traffic_comparison(comparison(), "eb-curb", site_id="s", revision=1, input_revision=0)
        self.assertEqual(p.overlap.status, "unassessed")
        self.assertEqual(p.access.status, "unassessed")
        checked = from_traffic_comparison(comparison(parcel=12.5, curb_cuts=1), "eb-curb", site_id="s", revision=1, input_revision=0)
        self.assertEqual(checked.overlap.status, "checked")
        self.assertIn("12.5", checked.overlap.text)
        self.assertEqual(checked.access.status, "checked")

    def test_not_recommended_layout_says_why(self):
        p = from_traffic_comparison(comparison(recommended=None), "eb-curb", site_id="s", revision=1, input_revision=0)
        self.assertIn("Not recommended", p.recommendation)

    def test_unsimulated_layout_and_changed_metrics_are_rejected(self):
        with self.assertRaises(ValueError):
            from_traffic_comparison(comparison(), "never-run", site_id="s", revision=1, input_revision=0)
        dumped = from_traffic_comparison(comparison(), "eb-curb", site_id="s", revision=1, input_revision=0).model_dump(mode="json")
        stale = copy.deepcopy(dumped); stale["metrics"][0]["input_hash"] = "old"
        with self.assertRaises(ValidationError):
            Proposal.model_validate(stale)

    def test_design_kinds_keep_their_own_fields(self):
        with self.assertRaises(ValidationError):
            Design(kind="lane_reallocation", length_m=60, width_m=3.2)
        with self.assertRaises(ValidationError):
            Design(kind="test_island", length_m=12, width_m=2, approach="nb")


if __name__ == "__main__":
    unittest.main()
