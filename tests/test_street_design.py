import unittest

from shapely.geometry import box, mapping
from pyproj import Transformer
from shapely import transform

from street_design import Layout, rank, sponsor_checks, edge_patch

TO_GEO = Transformer.from_crs(32611, 4326, always_xy=True)
X, Y = 385_000, 3_768_000


def metrics(completion=0.9, unable=0.05, delay=60.0, queue=80.0, co2_trip=300.0, co2=400.0):
    return {"completion_share": completion, "unable_to_enter_share": unable, "mean_delay_s": delay,
            "max_queue_m": {"nb": queue}, "max_noise_db": {"nb": 72.0}, "co2_kg_per_hour": co2,
            "co2_g_per_completed_vehicle": co2_trip}


def geo(polygon):
    return mapping(transform(polygon, TO_GEO.transform, interleaved=False))


def checked():
    return {"parcel_overlap_m2": 0.0, "building_overlap_m2": 0.0, "access_conflicts": 0, "keep_clear_conflict": False,
            "detection_status": "empty", "candidate_crosswalk_overlaps": 0, "candidate_driveway_overlaps": 0}


class RankingTest(unittest.TestCase):
    def test_invalid_partial_sponsor_geometry_and_counts_stay_unassessed(self):
        design=box(X,Y,X+10,Y+4)
        parcel={'geometry':geo(design),'properties':{'label':'Parcel boundary'}}
        good={'geometry':geo(box(X+20,Y,X+30,Y+10)),'properties':{'label':'Building footprint'}}
        bad={'geometry':{'type':'Polygon','coordinates':[]},'properties':{'label':'Building footprint'}}
        self.assertIsNone(sponsor_checks(design,[parcel,good,bad],[])['building_overlap_m2'])
        for cuts in (True, -1, 1.5, '1', None):
            frontage={'geometry':{'type':'LineString','coordinates':[list(TO_GEO.transform(X,Y)),list(TO_GEO.transform(X+10,Y))]},'curbCuts':cuts}
            self.assertIsNone(sponsor_checks(design,[parcel,good],[frontage])['access_conflicts'])

    def test_tiny_positive_score_is_not_rounded_into_no_recommendation(self):
        result=rank({'baseline':metrics(),'candidate':metrics(co2=399.99)},{'candidate':checked()})
        self.assertEqual(result['recommended'],'candidate')
        self.assertGreater(result['verdicts']['candidate']['score'],0)

    def test_invalid_shares_and_overlap_numbers_cannot_be_eligible(self):
        for value in (float('nan'),-1,True):
            result=rank({'baseline':metrics(),'candidate':metrics(co2=350)}, {'candidate':{**checked(),'parcel_overlap_m2':value}})
            self.assertFalse(result['verdicts']['candidate']['eligible'])
        for value in (-.1,1.1):
            result=rank({'baseline':metrics(),'candidate':metrics(co2=350,completion=value)},{'candidate':checked()})
            self.assertFalse(result['verdicts']['candidate']['eligible'])
    def test_layout_that_strands_demand_cannot_win_even_with_lowest_co2(self):
        results = {"baseline": metrics(), "strander": metrics(completion=0.6, unable=0.3, co2_trip=150, co2=200),
                   "fair": metrics(co2_trip=280, co2=380)}
        outcome = rank(results, {"fair": checked(), "strander": checked()})
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
        for value in (True, "1", 1.5):
            with self.assertRaises(ValueError):
                Layout(name="ok-name", kind="lane_reallocation", approach="nb", lanes_removed=value, length_m=50, new_use="bike_lane")

    def test_strict_policy_rejects_total_co2_increase_despite_per_trip_improvement(self):
        outcome = rank({"baseline": metrics(), "candidate": metrics(co2_trip=250, co2=410)}, {"candidate": checked()})
        self.assertFalse(outcome["verdicts"]["candidate"]["eligible"])
        self.assertTrue(any("total CO₂" in reason for reason in outcome["verdicts"]["candidate"]["ineligible_reasons"]))

    def test_strict_regression_gates_and_unknown_evidence(self):
        for key, value in (("mean_delay_s", 66.1), ("max_queue_m", {"nb": 89.0}),
                           ("max_noise_db", {"nb": 72.5}), ("unable_to_enter_share", .071)):
            candidate = {**metrics(co2=350), key: value}
            self.assertFalse(rank({"baseline": metrics(), "candidate": candidate}, {"candidate": checked()})["verdicts"]["candidate"]["eligible"], key)
        candidate = metrics(co2=350)
        self.assertFalse(rank({"baseline": metrics(), "candidate": candidate}, {})["verdicts"]["candidate"]["eligible"])
        candidate["max_noise_db"] = {"nb": 72.4}
        self.assertTrue(rank({"baseline": metrics(), "candidate": candidate}, {"candidate": checked()})["verdicts"]["candidate"]["eligible"])

    def test_adjacent_approach_regression_cannot_hide_behind_a_larger_queue(self):
        base = {**metrics(), "max_queue_m": {"nb": 150, "wb": 60}, "max_noise_db": {"nb": 80, "wb": 65}}
        candidate = {**metrics(co2=350), "max_queue_m": {"nb": 140, "wb": 80}, "max_noise_db": {"nb": 79, "wb": 66}}
        verdict = rank({"baseline": base, "candidate": candidate}, {"candidate": checked()})["verdicts"]["candidate"]
        self.assertFalse(verdict["eligible"])
        self.assertGreater(verdict["changes"]["queue"], .3)
        self.assertGreater(verdict["changes"]["noise"], .1)

    def test_empty_or_partial_sponsor_evidence_is_unassessed_and_overlaps_are_unioned(self):
        design = box(X, Y, X + 10, Y + 4)
        self.assertIsNone(sponsor_checks(design, [], [])['parcel_overlap_m2'])
        self.assertIsNone(sponsor_checks(design, [], [])['access_conflicts'])
        parcel = {"geometry": geo(design), "properties": {"label": "Parcel boundary", "evidenceId": "parcel"}}
        result = sponsor_checks(design, [parcel, parcel], [{"curbCuts": None}])
        self.assertAlmostEqual(result["parcel_overlap_m2"], 40.0)
        self.assertIsNone(result["building_overlap_m2"])
        self.assertIsNone(result["access_conflicts"])

    def test_touched_parcel_with_missing_buildings_cannot_be_cleared_by_another_parcel(self):
        design = box(X, Y, X + 10, Y + 4)
        parcel = {"geometry": geo(design), "properties": {"label": "Parcel boundary", "buildingCoverage": False}}
        building = {"geometry": geo(box(X + 20, Y, X + 30, Y + 5)), "properties": {"label": "Building footprint"}}
        result = sponsor_checks(design, [parcel, building], [])
        self.assertEqual(result["parcel_overlap_m2"], 40)
        self.assertIsNone(result["building_overlap_m2"])

    def test_partial_length_splits_edge_and_removes_curb_lane(self):
        import xml.etree.ElementTree as ET
        from types import SimpleNamespace
        edge = SimpleNamespace(getID=lambda: "approach", getLength=lambda: 100.0, getLaneNumber=lambda: 3)
        study = SimpleNamespace(mapping={"nb": {"edge": edge, "chain": [edge]}})
        layout = Layout(name="nb-curb", kind="lane_reallocation", approach="nb", lanes_removed=1, length_m=60, new_use="curb_extension")
        split = ET.fromstring(edge_patch(layout, study)).find("edge/split")
        self.assertEqual(float(split.attrib["pos"]), -60)
        self.assertEqual(split.attrib["lanes"], "1 2")
        self.assertEqual(split.attrib["idAfter"], "approach")
        with self.assertRaises(ValueError):
            edge_patch(layout.model_copy(update={"length_m": 120}), study)
        with self.assertRaises(ValueError):
            edge_patch(layout.model_copy(update={"new_use": "bus_lane"}), study)


if __name__ == "__main__":
    unittest.main()
