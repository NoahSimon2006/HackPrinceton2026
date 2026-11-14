import unittest

from designer import ChatError, validated_constraints
from street_geometry import FEATURED_BEARINGS, FEATURED_SITE, build_geometry, street_stops
from vexcel_scene import local_uri, provider_url
from sponsor_data import SponsorError


class StreetGeometryTest(unittest.TestCase):
    def test_planting_and_access_overlap_use_the_rendered_footprint(self):
        design = {"elements": [{"type": "planted_curb_extension", "label": "Plant a corner", "street": "first",
                                "approach": "positive", "side": "left"}]}
        geometry = build_geometry(FEATURED_SITE, FEATURED_BEARINGS, design, [])
        self.assertEqual([feature["properties"]["kind"] for feature in geometry["features"]], ["planted", "tree", "shade"])
        self.assertAlmostEqual(geometry["metrics"]["converted_m2"], 20.2, places=1)
        self.assertEqual(geometry["metrics"]["crossings"][0]["after_m"], 14.6)
        self.assertGreater(geometry["metrics"]["modeled_tree_shade_m2"], 0)
        ring = geometry["features"][0]["geometry"]["coordinates"][0]
        longitude, latitude = zip(*ring)
        bounds = [[min(longitude), min(latitude), max(longitude), max(latitude)]]
        self.assertEqual(validated_constraints(FEATURED_SITE, bounds), bounds)
        blocked = build_geometry(FEATURED_SITE, FEATURED_BEARINGS, design, bounds)
        self.assertEqual(blocked["conflicts"], [{"element": "Plant a corner", "area": 1}])
        design["elements"][0]["approach"] = "negative"
        changed = build_geometry(FEATURED_SITE, FEATURED_BEARINGS, design, bounds)
        self.assertEqual(changed["conflicts"], [])
        self.assertNotEqual(changed["features"][0], geometry["features"][0])

    def test_stops_and_constraint_validation(self):
        stops = street_stops(FEATURED_SITE, FEATURED_BEARINGS)
        self.assertEqual(stops[3]["position"], [FEATURED_SITE["lon"], FEATURED_SITE["lat"]])
        for bounds in ([[-2, -1, 1, 2]], [[1, False, 2, 8]], [[float("nan"), 1, 2, 9]]):
            with self.subTest(bounds=bounds), self.assertRaises(ChatError):
                validated_constraints(FEATURED_SITE, bounds)


class StreetResourceTest(unittest.TestCase):
    def test_tileset_urls_stay_on_the_local_credential_free_route(self):
        base = "https://api.vexcelgroup.com/v2/3d/tileset"
        result = local_uri("tile?zoom=19&tile-x=1&tile-y=2&api_key=secret", base)
        self.assertEqual(result, "/api/vexcel/scene/tile?zoom=19&tile-x=1&tile-y=2")
        with self.assertRaises(SponsorError):
            local_uri("https://example.com/v2/3d/tile", base)
        with self.assertRaises(SponsorError):
            provider_url("tileset", "collection=other")
