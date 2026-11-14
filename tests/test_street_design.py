import unittest

from shapely.geometry import box, mapping
from pyproj import Transformer
from shapely import transform

from street_design import Layout, rank, sponsor_checks

TO_GEO = Transformer.from_crs(32611, 4326, always_xy=True)
X, Y = 385_000, 3_768_000


def metrics(completion=0.9, unable=0.05, delay=60.0, queue=80.0, co2_trip=300.0, co2=400.0):
    return {"completion_share": completion, "unable_to_enter_share": unable, "mean_delay_s": delay,
            "max_queue_m": {"nb": queue}, "max_noise_db": {"nb": 72.0}, "co2_kg_per_hour": co2,
            "co2_g_per_completed_vehicle": co2_trip}


def geo(polygon):
    return mapping(transform(polygon, TO_GEO.transform, interleaved=False))


class RankingTest(unittest.TestCase):
    def test_layout_that_strands_demand_cannot_win_even_with_lowest_co2(self):
        results = {"baseline": metrics(), "strander": metrics(completion=0.6, unable=0.3, co2_trip=150, co2=200),
                   "fair": metrics(co2_trip=280)}
        outcome = rank(results, {})
        self.assertFalse(outcome["verdicts"]["strander"]["eligible"])
        self.assertEqual(outcome["recommended"], "fair")

    def test_no_recommendation_when_nothing_beats_today(self):
        outcome = rank({"baseline": metrics(), "worse": metrics(delay=90, co2_trip=330)}, {})
        self.assertIsNone(outcome["recommended"])
        self.assertIn("co2", outcome["verdicts"]["worse"]["changes"])

    def test_building_overlap_and_keep_clear_make_layout_ineligible(self):
        results = {"baseline": metrics(), "a": metrics(co2_trip=250), "b": metrics(co2_trip=260)}
        outcome = rank(results, {"a": {"building_overlap_m2": 3.0}, "b": {"keep_clear_conflict": True}})
        self.assertFalse(outcome["verdicts"]["a"]["eligible"])
        self.assertFalse(outcome["verdicts"]["b"]["eligible"])
        self.assertIsNone(outcome["recommended"])

    def test_sponsor_checks_measure_overlap_and_curb_cut_conflicts(self):
        design = box(X, Y, X + 10, Y + 4)
        outlines = [{"geometry": geo(box(X + 5, Y - 5, X + 30, Y + 20)), "properties": {"label": "Parcel boundary", "evidenceId": "outline-1"}},
                    {"geometry": geo(box(X + 20, Y, X + 30, Y + 10)), "properties": {"label": "Building footprint", "evidenceId": "outline-2"}}]
        frontage = {"geometry": {"type": "LineString", "coordinates": [list(TO_GEO.transform(X, Y + 6)), list(TO_GEO.transform(X + 10, Y + 6))]},
                    "curbCuts": 1, "evidenceId": "frontage-1"}
        result = sponsor_checks(design, outlines, [frontage])
        self.assertAlmostEqual(result["parcel_overlap_m2"], 20.0, places=1)
        self.assertEqual(result["building_overlap_m2"], 0.0)
        self.assertEqual(result["access_conflicts"], 1)
        unassessed = sponsor_checks(design, None, None)
        self.assertIsNone(unassessed["parcel_overlap_m2"])
        self.assertIsNone(unassessed["access_conflicts"])

    def test_layout_parameters_are_bounded(self):
        with self.assertRaises(ValueError):
            Layout(name="x", kind="lane_reallocation", approach="nb", lanes_removed=3, length_m=50, new_use="bike_lane")
        with self.assertRaises(ValueError):
            Layout(name="ok-name", kind="lane_reallocation", approach="nb", lanes_removed=1, length_m=500, new_use="bike_lane")


if __name__ == "__main__":
    unittest.main()
