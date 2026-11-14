import math
import unittest

from pyproj import Transformer

from site_measurements import (PROJECT, hydrology_facts, measure_candidates, measure_markings,
                               measure_outlines, projected, property_facts, validate_inputs)

LON, LAT = -118.25, 34.05
X, Y = PROJECT.transform(LON, LAT)
INVERSE = Transformer.from_crs(32611, 4326, always_xy=True)


def ring(x, y, width, height):
    return [list(INVERSE.transform(X + a, Y + b)) for a, b in
            [(x, y), (x + width, y), (x + width, y + height), (x, y + height), (x, y)]]


def polygon(x=0, y=0, width=10, height=10):
    return {"type": "Polygon", "coordinates": [ring(x, y, width, height)]}


def feature(geometry, label):
    return {"type": "Feature", "geometry": geometry,
            "properties": {"label": label, "date": "2024-04-12", "collection": "test-collection"}}


class MeasurementsTest(unittest.TestCase):
    def test_holes_multipolygons_and_line_length(self):
        geometry = polygon(-20, -20, 40, 40)
        geometry["coordinates"].append(ring(-5, -5, 10, 10))
        self.assertAlmostEqual(projected(geometry).area, 1500, places=3)
        multi = {"type": "MultiPolygon", "coordinates": [polygon()["coordinates"], polygon(20, 20)["coordinates"]]}
        self.assertAlmostEqual(projected(multi).area, 200, places=3)
        points = [list(INVERSE.transform(X, Y)), list(INVERSE.transform(X + 30, Y + 40))]
        self.assertAlmostEqual(projected({"type": "LineString", "coordinates": points}).length, 50, places=3)

    def test_union_clipping_and_missing_are_not_zero(self):
        features = [feature(polygon(-10, -10, 100, 100), "Parcel boundary"),
                    feature(polygon(0, 0, 20, 20), "Building footprint"),
                    feature(polygon(10, 0, 20, 20), "Building footprint"),
                    feature(polygon(80, 0, 20, 20), "Building footprint")]
        facts, _ = measure_outlines(features, LON, LAT)
        values = {f["id"]: f["value"] for f in facts}
        self.assertEqual(values["parcel-area"], 10000)
        self.assertEqual(values["footprint-area"], 800)
        self.assertEqual(values["footprint-coverage"], 8)
        self.assertEqual(values["parcel-outside-footprints"], 9200)
        facts, warnings = measure_outlines(features[:1], LON, LAT)
        self.assertEqual(len(facts), 1)
        self.assertTrue(warnings)
        self.assertEqual(measure_outlines(features, LON + .1, LAT)[0], [])

    def test_invalid_and_remote_markings_rejected(self):
        invalid = polygon()
        points = invalid["coordinates"][0]
        points[1], points[2] = points[2], points[1]
        for geometry in [invalid, {"type": "Polygon", "coordinates": [[[math.nan, LAT], [LON, LAT], [LON, LAT + .1]]]}, polygon(2000, 2000)]:
            with self.assertRaises(ValueError):
                validate_inputs([{"kind": "drainage", "geometry": geometry}], None, "water", LON, LAT)
        with self.assertRaises(ValueError):
            validate_inputs([{"kind": "drainage", "geometry": polygon()}], None, "street", LON, LAT)
        for depth in [True, math.nan, math.inf, -1, 101]:
            with self.assertRaises(ValueError):
                validate_inputs([], {"inches": depth, "source": "Test"}, "water", LON, LAT)

    def test_candidate_box_is_never_an_area_or_crossing_length(self):
        data = [feature(polygon(10, 0, 20, 20), "Zebra crosswalk")]
        facts, warnings = measure_candidates(data, LON, LAT)
        self.assertEqual(warnings, [])
        self.assertEqual(len(facts), 1)
        self.assertEqual(facts[0]["value"], 10)
        self.assertEqual(facts[0]["basis"], "candidate")
        self.assertIn("distance", facts[0]["label"])
        self.assertNotIn("area", facts[0])

    def test_markings_and_rainfall_are_distinct_sourced_facts(self):
        markings, scenario = validate_inputs([{"kind": "treatment", "geometry": polygon()}],
            {"inches": 1.5, "source": "Planner sensitivity scenario"}, "water", LON, LAT)
        facts = measure_markings(markings, scenario)
        self.assertEqual(facts[0]["value"], 100)
        self.assertEqual(facts[0]["basis"], "user_marked")
        self.assertEqual(facts[1]["basis"], "assumption")
        county = hydrology_facts({"estimate": {"inches": 1.01, "depth_range": [1, 1.1], "method": "interpolated"}})
        self.assertEqual(county[0]["id"], "county-rainfall")
        self.assertEqual(county[0]["value"], 1.01)

    def test_costar_allowlist_and_frontage_association(self):
        details = {"propertyType": "Multifamily", "units": 194, "vacancyPercent": 43,
                   "name": "PRIVATE NAME", "address": "PRIVATE ADDRESS", "geometry": polygon(),
                   "reportedParkingSpaces": 25, "buildingAreaSqFt": 60088}
        line = {"type": "LineString", "coordinates": ring(0, 0, 10, 10)[:2]}
        facts, _ = property_facts(details, [{"geometry": line, "selectedProperty": False}])
        values = str(facts)
        for secret in ["PRIVATE NAME", "PRIVATE ADDRESS", "vacancyPercent", "coordinates"]:
            self.assertNotIn(secret, values)
        self.assertEqual(facts[-1]["value"], 10)
        self.assertEqual(facts[-1]["label"], "Nearby-property frontage")


if __name__ == "__main__":
    unittest.main()
