import copy
import json
import math
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock

from shapely.affinity import rotate, translate
from shapely.geometry import LineString, box, mapping, shape

from road_concept import ConceptPlacementError, build_road_concept, concept_model_summary, validate_road_concept
from site_measurements import PROJECT, projected
from street_context import TO_GEO, canonical_hash, prepare_street_context, _geographic


LON, LAT = -118.25, 34.05
X, Y = PROJECT.transform(LON, LAT)


def osm_fixture(angle=0, width=12):
    line = translate(rotate(LineString([(-120, 0), (120, 0)]), angle, origin=(0, 0)), X, Y)
    a, b = [TO_GEO.transform(*point) for point in line.coords]
    return (f'<osm version="0.6"><node id="1" lon="{a[0]}" lat="{a[1]}"/>'
            f'<node id="2" lon="{b[0]}" lat="{b[1]}"/><way id="10" timestamp="2026-11-01T00:00:00Z">'
            '<nd ref="1"/><nd ref="2"/><tag k="highway" v="residential"/>'
            f'<tag k="width" v="{width}"/><tag k="name" v="Private source road name"/></way></osm>').encode()


def road_context(angle=0, width=12, markings=None):
    return prepare_street_context(LON, LAT, markings, network_path="/missing/network.net.xml", osm_path="/missing/roads.osm",
                                  fetch_osm=lambda bbox: osm_fixture(angle, width))


def identity(revision=1, input_revision=0):
    return {"site_id": "road-site", "revision": revision, "input_revision": input_revision}


def component(context, kind="curb_extension", identifier="curb", **kwargs):
    return {"id": identifier, "kind": kind, "anchor_id": context["anchors"][0]["id"], **kwargs}


class StreetContextTests(unittest.TestCase):
    def test_public_geometry_independent_of_counts_and_private_model_payload(self):
        fetch = Mock(return_value=osm_fixture())
        context = prepare_street_context(LON, LAT, network_path="/missing/net", osm_path="/missing/osm", fetch_osm=fetch)
        self.assertEqual(context["status"], "ready")
        self.assertEqual(fetch.call_count, 1)
        west, south, east, north = fetch.call_args.args[0]
        self.assertLess(east - west, .006)
        self.assertLess(north - south, .005)
        self.assertEqual(context["sources"][0]["attribution"], "© OpenStreetMap contributors")
        self.assertEqual(context["origin"]["lon"], LON)
        model = json.dumps(context["model_context"])
        for forbidden in (str(LON), str(LAT), "coordinates", "Private source road name", "easting", "northing"):
            self.assertNotIn(forbidden, model)
        self.assertEqual(context["model_context"]["anchors"][0]["direction"], "east")
        self.assertNotIn("traffic", context["source_status"][0]["source"])

    def test_assumed_width_explicit_and_stable_hash_across_retrieval_time(self):
        raw = osm_fixture().replace(b'<tag k="width" v="12"/>', b'<tag k="lanes" v="2"/>')
        kwargs = dict(network_path="/missing/net", osm_path="/missing/osm", fetch_osm=lambda bbox: raw)
        first, second = prepare_street_context(LON, LAT, **kwargs), prepare_street_context(LON, LAT, **kwargs)
        self.assertEqual(first["context_hash"], second["context_hash"])
        self.assertEqual(first["anchors"][0]["width_m"], 6.4)
        self.assertIn("assumed", first["anchors"][0]["width_basis"])

    def test_missing_road_does_not_invent_a_rectangle(self):
        context = prepare_street_context(LON, LAT, network_path="/missing/net", osm_path="/missing/osm", allow_public_fetch=False)
        self.assertEqual(context["status"], "unavailable")
        self.assertEqual(context["roads"], [])
        with self.assertRaisesRegex(ConceptPlacementError, "No usable road"):
            build_road_concept(context, [], identity=identity())

    def test_marked_crossing_usable_without_network_or_source_fetch(self):
        marking = {"kind": "crossing", "geometry": _geographic(LineString([(X, Y - 5), (X, Y + 5)]))}
        context = prepare_street_context(LON, LAT, [marking], network_path="/missing/net", osm_path="/missing/osm", allow_public_fetch=False)
        concept = build_road_concept(context, [component(context, "crossing", "crossing")], identity=identity())
        self.assertEqual(context["anchors"][0]["kind"], "marked_crossing")
        self.assertGreater(len(concept["geometry"]), 3)
        self.assertEqual(concept["checks"][0]["road_fit"], "user_marked_alignment")

    def test_sumo_projection_lane_offset_and_no_source_request(self):
        # Two parallel eastbound lane centers at y-1.6 and y+1.6.
        offset = (-X + 1000, -Y + 1000)
        xml = (f'<net><location netOffset="{offset[0]},{offset[1]}" projParameter="+proj=utm +zone=11 +datum=WGS84 +units=m +no_defs"/>'
               '<edge id="42" type="highway.residential" name="Local road">'
               '<lane id="42_0" width="3.2" shape="880,998.4 1120,998.4"/>'
               '<lane id="42_1" width="3.2" shape="880,1001.6 1120,1001.6"/></edge></net>').encode()
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "net.xml"; path.write_bytes(xml)
            fetch = Mock(side_effect=AssertionError("Network should not run"))
            context = prepare_street_context(LON, LAT, network_path=path, osm_path="/missing/osm", fetch_osm=fetch)
        fetch.assert_not_called()
        anchor = context["anchors"][0]
        self.assertAlmostEqual(anchor["width_m"], 6.4)
        self.assertLess(projected(anchor["geometry"], ("LineString",)).distance(shape({"type": "Point", "coordinates": [X, Y]})), .01)
        self.assertLess(anchor["distance_m"], .01)
        self.assertNotIn("crossing", anchor["supported_kinds"])

    def test_opposing_unequal_sumo_carriageways_make_one_full_road_crossing(self):
        offset = (-X + 1000, -Y + 1000)
        xml = (f'<net><location netOffset="{offset[0]},{offset[1]}" projParameter="+proj=utm +zone=11 +datum=WGS84 +units=m +no_defs"/>'
               '<edge id="42" from="a" to="b" type="highway.residential">'
               '<lane id="42_0" width="3.2" shape="880,993.6 1120,993.6"/>'
               '<lane id="42_1" width="3.2" shape="880,996.8 1120,996.8"/></edge>'
               '<edge id="-42" from="b" to="a" type="highway.residential">'
               '<lane id="-42_0" width="3.2" shape="1120,1006.4 880,1006.4"/>'
               '<lane id="-42_1" width="3.2" shape="1120,1003.2 880,1003.2"/>'
               '<lane id="-42_2" width="3.2" shape="1120,1000 880,1000"/></edge></net>').encode()
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "net.xml"; path.write_bytes(xml)
            context = prepare_street_context(LON, LAT, network_path=path, osm_path="/missing/osm", allow_public_fetch=False)
        self.assertEqual(len(context["anchors"]), 1)
        anchor = context["anchors"][0]
        self.assertEqual(anchor["crossing_basis"], "paired_opposing_carriageways")
        self.assertAlmostEqual(anchor["width_m"], 16.)
        self.assertLess(anchor["distance_m"], .01)
        concept = build_road_concept(context, [component(context, "crossing", "full-crossing")], identity=identity())
        footprint = projected(concept["geometry"][0]["geometry"])
        self.assertAlmostEqual(footprint.bounds[1], Y - 8, places=3)
        self.assertAlmostEqual(footprint.bounds[3], Y + 8, places=3)
        self.assertAlmostEqual(footprint.area, 48, places=3)

    def test_far_source_and_oversized_response_rejected(self):
        raw = osm_fixture().replace(b'lat="34.', b'lat="34.9')
        ctx = prepare_street_context(LON, LAT, network_path="/missing/net", osm_path="/missing/osm", fetch_osm=lambda bbox: raw)
        self.assertEqual(ctx["status"], "unavailable")
        ctx = prepare_street_context(LON, LAT, network_path="/missing/net", osm_path="/missing/osm", fetch_osm=lambda bbox: b" " * 8_000_001)
        self.assertEqual(ctx["status"], "unavailable")


class RoadConceptTests(unittest.TestCase):
    def test_geometry_follows_diagonal_road_and_has_no_performance_claim(self):
        context = road_context(angle=37)
        value = build_road_concept(context, [component(context, offset_m=125, length_m=15, width_m=2)], identity=identity())
        footprint = projected(value["geometry"][0]["geometry"])
        local = rotate(translate(footprint, -X, -Y), -37, origin=(0, 0))
        self.assertAlmostEqual(local.bounds[0], 5, places=2)
        self.assertAlmostEqual(local.bounds[1], -6, places=2)
        self.assertAlmostEqual(local.bounds[2], 20, places=2)
        self.assertAlmostEqual(local.bounds[3], -4, places=2)
        self.assertAlmostEqual(footprint.area, 30, places=3)
        self.assertEqual(value["status"], "conceptual")
        self.assertEqual(value["evaluation"]["status"], "unassessed")
        self.assertIsNone(value["evaluation"]["reference"])
        self.assertEqual(validate_road_concept(json.loads(json.dumps(value)), identity()), value)

    def test_crossing_and_bicycle_markings_are_compiled_geometry(self):
        context = road_context()
        value = build_road_concept(context, [component(context, "crossing", "cross", offset_m=112),
                                            component(context, "bike_lane", "bike", offset_m=130, length_m=35)], identity=identity())
        stripes = [f for f in value["geometry"] if f["properties"]["kind"] == "crossing" and f["properties"]["role"] == "marking"]
        bike = [f for f in value["geometry"] if f["properties"]["kind"] == "bike_lane" and f["properties"]["role"] == "marking"]
        self.assertGreater(len(stripes), 5)
        self.assertGreaterEqual(len(bike), 3)
        self.assertTrue(all(projected(f["geometry"]).area > .005 for f in stripes + bike))

    def test_island_and_markings_compile_to_distinct_shapes(self):
        context = road_context()
        value = build_road_concept(context, [component(context, "pedestrian_island", "island", offset_m=130),
                                            component(context, "lane_marking", "lane", offset_m=145)], identity=identity())
        island = value["geometry"][0]["geometry"]
        dashed = next(f["geometry"] for f in value["geometry"] if f["properties"]["kind"] == "lane_marking")
        self.assertGreater(len(island["coordinates"][0]), 8)
        self.assertEqual(dashed["type"], "MultiPolygon")

    def test_named_revision_preserves_unmentioned_components_and_fields(self):
        context = road_context()
        original = build_road_concept(context, [component(context, offset_m=130, length_m=12, width_m=2),
                                               component(context, "crossing", "cross", offset_m=110)], identity=identity())
        revised = build_road_concept(context, changes=[{"id": "curb", "op": "update", "length_m": 15}],
                                     previous=original, identity=identity(2, 1))
        self.assertEqual(revised["components"][1], original["components"][1])
        self.assertEqual(revised["components"][0]["width_m"], 2)
        self.assertEqual(revised["parent"]["input_hash"], original["input_hash"])
        self.assertNotEqual(revised["input_hash"], original["input_hash"])
        self.assertEqual(validate_road_concept(revised), revised)
        with self.assertRaisesRegex(ConceptPlacementError, "Confirm realigning"):
            build_road_concept(road_context(angle=10), changes=[{"id": "curb", "op": "update", "length_m": 15}],
                               previous=original, identity=identity(2, 1))

    def test_changed_context_constraints_revalidate_without_discarding_components(self):
        context = road_context()
        original = build_road_concept(context, [component(context, offset_m=130, length_m=12, width_m=2)], identity=identity())
        clear = {"kind": "access", "geometry": _geographic(box(X - 60, Y - 7, X - 55, Y - 3))}
        refreshed = road_context(markings=[clear])
        self.assertNotEqual(context["context_hash"], refreshed["context_hash"])
        revised = build_road_concept(refreshed, changes=[{"id": "curb", "op": "update", "length_m": 15}],
                                     previous=original, identity=identity(2, 1))
        self.assertEqual(revised["components"][0]["width_m"], 2)
        blocking = {"kind": "access", "geometry": _geographic(box(X + 12, Y - 7, X + 15, Y - 3))}
        with self.assertRaisesRegex(ConceptPlacementError, "keep-clear"):
            build_road_concept(road_context(markings=[blocking]), changes=[{"id": "curb", "op": "update", "length_m": 15}],
                               previous=original, identity=identity(2, 1))
        changed_alignment = road_context(angle=10)
        reanchored = build_road_concept(changed_alignment,
                                      changes=[{"id": "curb", "op": "update", "anchor_id": changed_alignment["anchors"][0]["id"]}],
                                      previous=original, identity=identity(2, 1))
        self.assertEqual(reanchored["components"][0]["length_m"], 12)

    def test_labels_cannot_archive_arbitrary_model_observations(self):
        context = road_context()
        value = build_road_concept(context, [component(context, label="Live speed 17 mph at personal address")], identity=identity())
        self.assertEqual(value["components"][0]["label"], "Curb extension")
        self.assertNotIn("Live speed", json.dumps(value))

    def test_keep_clear_building_and_existing_crossing_block_physical_component(self):
        context = road_context()
        component_value = component(context, offset_m=125, length_m=10, width_m=2)
        clear = {"kind": "access", "geometry": _geographic(box(X + 8, Y - 7, X + 12, Y - 3))}
        with self.assertRaisesRegex(ConceptPlacementError, "keep-clear"):
            build_road_concept(context, [component_value], identity=identity(), markings=[clear])
        building = {"geometry": clear["geometry"], "properties": {"label": "Building footprint"}}
        with self.assertRaisesRegex(ConceptPlacementError, "mapped building"):
            build_road_concept(context, [component_value], identity=identity(), evidence={"outlines": [building]})
        crossing = {"kind": "crossing", "geometry": _geographic(LineString([(X + 10, Y - 8), (X + 10, Y + 8)]))}
        with self.assertRaisesRegex(ConceptPlacementError, "marked crossing"):
            build_road_concept(context, [component_value], identity=identity(), markings=[crossing])

    def test_invalid_dims_foreign_anchor_and_overlapping_designs_rejected(self):
        context = road_context(width=7)
        for changes in ({"width_m": float("nan")}, {"length_m": 0}, {"offset_m": 239}, {"anchor_id": "road-000000000000"},
                        {"kind": "pedestrian_island"}, {"side": "center"}):
            with self.subTest(changes=changes), self.assertRaises(ConceptPlacementError):
                build_road_concept(context, [component(context, **changes)], identity=identity())
        with self.assertRaisesRegex(ConceptPlacementError, "too little clear road"):
            build_road_concept(context, [component(context, "pedestrian_space", "left", side="left", width_m=2.5),
                                        component(context, "pedestrian_space", "right", side="right", width_m=2.5)], identity=identity())

    def test_tampering_cannot_be_hidden_by_rehashing_and_summary_is_curated(self):
        context = road_context()
        value = build_road_concept(context, [component(context)], identity=identity())
        altered = copy.deepcopy(value)
        altered["geometry"][0]["geometry"]["coordinates"][0][0][0] += .00001
        altered["input_hash"] = canonical_hash({k: v for k, v in altered.items() if k != "input_hash"})
        with self.assertRaises(ConceptPlacementError):
            validate_road_concept(altered)
        with self.assertRaises(ConceptPlacementError):
            validate_road_concept(value, {**identity(), "site_id": "other-site"})
        summary = json.dumps(concept_model_summary(value))
        for forbidden in (str(LON), "coordinates", "Private source road name", "origin", "https://"):
            self.assertNotIn(forbidden, summary)


if __name__ == "__main__":
    unittest.main()
