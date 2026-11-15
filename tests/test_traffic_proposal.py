import copy
import unittest

from pydantic import ValidationError

from proposal import Design, Proposal, from_traffic_comparison, comparison_fingerprint


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

    def test_fingerprint_covers_source_geometry_constraints_and_results(self):
        original = comparison()
        identity = dict(site_id="s", revision=1, input_revision=0)
        before = comparison_fingerprint(original, **identity)
        for mutate in (
            lambda c: c["results"]["eb-curb"].update(co2_kg_per_hour=999),
            lambda c: c.update(sheet_sha256="changed-source"),
            lambda c: c["geometry"]["eb-curb"]["geometry"]["coordinates"][0][0].__setitem__(0,-118.24),
            lambda c: c.update(keep_clear_geometry=[{"changed":"constraint"}]),
        ):
            changed = copy.deepcopy(original); mutate(changed)
            self.assertNotEqual(comparison_fingerprint(changed, **identity), before)
        original.update(**identity,input_hash=before,workflow="street")
        self.assertEqual(comparison_fingerprint(original, **identity), before)

    def test_partial_metrics_and_outlines_are_not_reported_as_zero(self):
        c = comparison(parcel=12.5)
        c["checks"]["eb-curb"]["building_overlap_m2"] = None
        c["results"]["eb-curb"]["mean_delay_s"] = None
        c["results"]["baseline"]["max_queue_m"] = {"nb":None}
        p = from_traffic_comparison(c,"eb-curb",site_id="s",revision=1,input_revision=0)
        self.assertEqual(p.overlap.status,"unassessed")
        for key in ("mean_delay","max_queue","nox_per_hour"):
            m = next(x for x in p.metrics if x.id == key)
            self.assertEqual(m.status,"unassessed")
            self.assertIsNone(m.baseline)
            self.assertIsNone(m.proposed)


if __name__ == "__main__":
    unittest.main()
