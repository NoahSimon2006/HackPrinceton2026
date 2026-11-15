import copy
import unittest

from pyproj import Transformer
from shapely import transform
from shapely.geometry import MultiPolygon, Polygon, box, mapping, shape

from concept_scene import SceneUnavailable, build_scene, parse_scene_query
from site_measurements import PROJECT


LON, LAT = -118.302, 34.0596
EAST, NORTH = PROJECT.transform(LON, LAT)
INVERSE = Transformer.from_crs("EPSG:32611", "EPSG:4326", always_xy=True)


def geographic(local):
    from shapely.affinity import translate
    return mapping(transform(translate(local, xoff=EAST, yoff=NORTH), INVERSE.transform, interleaved=False))


def proposal(local=None, *, revision=1, digest="a" * 64, geometry_id="bed", workflow="water", status=None):
    local = local if local is not None else box(0, 0, 10, 2)
    return {"schema_version": 1, "site_id": "scene-site", "workflow": workflow, "revision": revision,
        "input_revision": revision - 1, "input_hash": digest, "development_fixture": False,
        "status": status or ("conditional" if workflow == "water" else "rejected"), "evidence": [],
        "design": {"kind": "bioretention", "storage_depth_m": .15} if workflow == "water" else
            {"kind": "lane_reallocation", "length_m": 10, "width_m": 2, "approach": "wb", "lanes_removed": 1, "new_use": "bike_lane"},
        "geometry": [{"type": "Feature", "id": geometry_id, "geometry": geographic(local), "properties": {"role": "proposed", "revision": revision}}],
        "existing_geometry_ids": [], "proposed_geometry_ids": [geometry_id],
        "metrics": [{"id": "footprint_area", "unit": "m²", "baseline": None, "proposed": round(local.area, 3 if workflow == "water" else 1),
                     "status": "calculated", "revision": revision, "input_hash": digest, "method": "Exact test footprint area."}],
        "assumptions": ["Explicit test scenario."], "access": {"status": "unassessed", "text": "Unknown", "evidence_ids": []},
        "overlap": {"status": "unassessed", "text": "Unknown", "evidence_ids": []}, "recommendation": "Inspect the saved concept."}


def project(p=None, outlines=None):
    p = p or proposal()
    return {"id": "1" * 32, "status": "ready", "snapshot": {"siteId": "scene-site", "workflow": p["workflow"],
        "lon": LON, "lat": LAT, "proposalRevision": p["revision"], "inputRevision": p["input_revision"]},
        "result": {"proposal": p, "alternatives": {}, "savedAt": "2026-11-15T10:00:00+00:00",
                   "evidence": {"outlines": outlines or []}}, "designHistory": [], "trafficDesignHistory": []}


def scene(p):
    q = p["result"]["proposal"]
    return build_scene(p, q["revision"], q["input_hash"], q["proposed_geometry_ids"][0])


class ConceptSceneTest(unittest.TestCase):
    def test_holes_and_authoritative_metrics_use_exact_utm_meters(self):
        polygon = Polygon([(0, 0), (10, 0), (10, 10), (0, 10)], holes=[[(2, 2), (6, 2), (6, 6), (2, 6)]])
        saved = project(proposal(polygon))
        value = scene(saved)
        footprint = shape(value["features"][0]["geometry"])
        self.assertEqual(len(footprint.interiors), 1)
        self.assertAlmostEqual(footprint.area, 84, places=6)
        self.assertEqual(value["metrics"], saved["result"]["proposal"]["metrics"])
        self.assertEqual(value["areaM2"], 84)
        self.assertEqual(value["origin"]["crs"], "EPSG:32611")
        self.assertAlmostEqual(value["origin"]["easting"], EAST, places=6)
        self.assertEqual(value["features"][0]["heightM"], .15)
        self.assertIn("Assumed", value["features"][0]["heightBasis"])

    def test_multipolygon_and_stable_origin_across_revisions(self):
        first = scene(project(proposal(MultiPolygon([box(-10, -2, -5, 0), box(5, 0, 10, 2)]))))
        second = scene(project(proposal(box(0, 0, 10, 2), revision=2, digest="b" * 64)))
        self.assertEqual(first["features"][0]["geometry"]["type"], "MultiPolygon")
        self.assertAlmostEqual(first["geometryAreaM2"], 20, places=6)
        self.assertEqual(first["origin"], second["origin"])
        self.assertAlmostEqual(first["focusBounds"][0], -10, places=6)

    def test_full_identity_and_query_validation(self):
        saved = project()
        for revision, digest, identifier in [(2, "a" * 64, "bed"), (1, "b" * 64, "bed"), (1, "a" * 64, "other"), (True, "a" * 64, "bed")]:
            with self.subTest(reference=(revision, digest, identifier)), self.assertRaises(SceneUnavailable):
                build_scene(saved, revision, digest, identifier)
        query = {"projectId": ["1" * 32], "revision": ["1"], "inputHash": ["a" * 64], "geometryId": ["bed"]}
        self.assertEqual(parse_scene_query(query)["revision"], 1)
        for malformed in ({**query, "revision": ["1", "2"]}, {**query, "revision": ["0"]}, {**query, "extra": ["x"]}, {**query, "projectId": ["../x"]}):
            with self.assertRaises(SceneUnavailable):
                parse_scene_query(malformed)
        for key, value in (("site_id", "foreign"), ("development_fixture", True)):
            wrong = copy.deepcopy(saved); wrong["result"]["proposal"][key] = value
            with self.assertRaises(SceneUnavailable):
                scene(wrong)

    def test_current_context_is_clipped_and_has_explicit_assumed_height(self):
        metadata = {"collection": "test-collection", "date": "2026-07-03"}
        outlines = [{"geometry": geographic(box(-100, -100, 100, 100)), "properties": {"label": "Building footprint", "private": "not returned", **metadata}},
                    {"geometry": geographic(box(-2, -2, 12, 4)), "properties": {"label": "Parcel boundary", **metadata}},
                    {"geometry": geographic(box(500, 500, 510, 510)), "properties": {"label": "Parcel boundary", "collection": "excluded-collection", "date": "2020-01-01"}}]
        value = scene(project(outlines=outlines))
        self.assertEqual(value["context"]["status"], "matched")
        self.assertEqual(len(value["features"]), 3)
        self.assertEqual(value["context"]["sources"], [{"provider": "Vexcel", **metadata}])
        building = value["features"][1]
        self.assertEqual(building["heightM"], 6)
        self.assertIn("Illustrative", building["heightBasis"])
        self.assertNotIn("private", str(value))
        self.assertLessEqual(value["bounds"][2], 45.000001)

    def test_old_history_does_not_borrow_latest_context(self):
        saved = project(proposal(revision=2, digest="b" * 64), outlines=[
            {"geometry": geographic(box(-5, -5, 5, 5)), "properties": {"label": "Building footprint"}}])
        saved["designHistory"] = [{"proposal": proposal(), "savedAt": "2026-11-14T00:00:00+00:00"}]
        value = build_scene(saved, 1, "a" * 64, "bed")
        self.assertEqual(value["context"]["status"], "unavailable")
        self.assertEqual(len(value["features"]), 1)
        self.assertEqual(value["savedAt"], "2026-11-14T00:00:00+00:00")

    def test_failed_result_context_is_not_attached_to_retained_history(self):
        saved = project(outlines=[{"geometry": geographic(box(-5, -5, 5, 5)), "properties": {"label": "Building footprint"}}])
        saved["designHistory"] = [{"proposal": copy.deepcopy(saved["result"]["proposal"]), "savedAt": "2026-11-14T00:00:00+00:00"}]
        saved["result"]["analysisError"] = "Stopped"
        saved["status"] = "failed"
        value = scene(saved)
        self.assertEqual(value["context"]["status"], "unavailable")
        self.assertEqual(value["savedAt"], "2026-11-14T00:00:00+00:00")

    def test_rejected_traffic_alternatives_use_geometry_identity(self):
        first = proposal(workflow="street", geometry_id="west")
        second = proposal(box(20, 0, 30, 2), workflow="street", geometry_id="east")
        saved = project(first)
        saved["result"].update(proposal=None, alternatives={"west": first, "east": second})
        value = build_scene(saved, 1, "a" * 64, "east")
        self.assertEqual(value["status"], "rejected")
        self.assertAlmostEqual(value["focusBounds"][0], 20, places=6)
        self.assertEqual(value["features"][0]["heightM"], .15)
        self.assertEqual(value["identity"]["geometryId"], "east")

    def test_water_alternative_preserves_rejection_from_study(self):
        saved = project()
        saved["result"]["waterPlan"] = {"comparison": {"results": [
            {"id": "bed", "inputHash": "a" * 64, "revision": 1, "status": "rejected"}]}}
        self.assertEqual(scene(saved)["status"], "rejected")

    def test_metrics_geometry_revision_and_far_geometry_fail_closed(self):
        for mutate in (lambda p: p["metrics"][0].update(proposed=500),
                       lambda p: p["metrics"][0].update(input_hash="b" * 64),
                       lambda p: p["geometry"][0]["properties"].update(revision=2),
                       lambda p: p["geometry"][0].update(geometry=geographic(box(1500, 0, 1510, 2)))):
            saved = project(); mutate(saved["result"]["proposal"])
            with self.assertRaises(SceneUnavailable):
                scene(saved)


if __name__ == "__main__":
    unittest.main()
