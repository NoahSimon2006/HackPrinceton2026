import unittest

from site_measurements import measure_candidates, measure_outlines, projected, validate_inputs
from stormwater_design import draft_rain_garden
from test_site_measurements import LAT, LON, feature, polygon


class StormwaterDesignTest(unittest.TestCase):
    def setUp(self):
        self.outlines = [feature(polygon(-30, -20, 60, 40), "Parcel boundary"),
                         feature(polygon(-10, -5, 20, 10), "Building footprint")]
        self.detections = [feature(polygon(16, -5, 10, 10), "Landscaped strip")]
        measure_outlines(self.outlines, LON, LAT)
        measure_candidates(self.detections, LON, LAT)

    def draft(self, markings=(), *, coefficient=None, protect=False, revision=1):
        markings, _ = validate_inputs(list(markings), None, "water", LON, LAT)
        return draft_rain_garden(lon=LON, lat=LAT, evidence={"outlines":self.outlines,
            "detections":self.detections, "frontages":[]}, markings=markings, rainfall={"inches":1},
            scenario=None, storage_depth_m=.15, runoff_coefficient=coefficient, protect_driveway=protect,
            identity={"site_id":"site", "input_revision":revision - 1, "revision":revision})

    def test_default_draft_depends_on_evidence_and_leaves_capture_unknown(self):
        draft, question, _ = self.draft()
        self.assertIsNone(question)
        self.assertEqual(draft.status, "draft")
        bed = projected(draft.geometry[0].geometry)
        self.assertTrue(projected(self.detections[0]["geometry"]).covers(bed))
        self.assertTrue(bed.disjoint(projected(self.outlines[1]["geometry"])))
        values = {metric.id:metric for metric in draft.metrics}
        self.assertGreater(values["storage_volume"].proposed, 0)
        for key in ("runoff_volume", "captured_volume", "overflow_volume"):
            self.assertEqual(values[key].status, "unassessed")
            self.assertIsNone(values[key].proposed)

    def test_keep_clear_revision_moves_geometry_and_recalculates_scenario(self):
        first, _, _ = self.draft()
        access = polygon(15, -7, 14, 14)
        markings = [{"kind":"access", "geometry":access},
                    {"kind":"drainage", "geometry":self.outlines[1]["geometry"]},
                    {"kind":"drainage", "geometry":self.outlines[1]["geometry"]}]
        second, question, _ = self.draft(markings, coefficient=.8, protect=True, revision=2)
        self.assertIsNone(question)
        self.assertTrue(projected(second.geometry[0].geometry).disjoint(projected(access)))
        self.assertNotEqual(first.input_hash, second.input_hash)
        values = {metric.id:metric.proposed for metric in second.metrics}
        self.assertEqual(values["runoff_volume"], 4.064)  # Overlapping markings count once.
        self.assertAlmostEqual(values["captured_volume"], values["storage_volume"] - values["direct_rain_volume"], places=3)
        self.assertAlmostEqual(values["runoff_volume"], values["captured_volume"] + values["overflow_volume"], places=3)
        self.assertIn("marking-1", second.access.evidence_ids)

    def test_unknown_requested_access_returns_one_location_question(self):
        draft, question, facts = self.draft(protect=True)
        self.assertIsNone(draft)
        self.assertIn("driveway", question)
        self.assertEqual(facts, [])
