"""Spatial regressions for coordinated, source-anchored intersection plans."""
import copy
import json
import unittest

from shapely import unary_union
from shapely.affinity import rotate, translate
from shapely.geometry import LineString, Point, box

from road_concept import ConceptPlacementError, build_road_concept, validate_road_concept
from site_measurements import projected
from street_context import _geographic, canonical_hash
from tests.test_road_concept import X, Y, identity, road_context


def rehash_context(context):
    stable = {k: v for k, v in context.items() if k not in ("context_hash", "model_context")}
    stable["sources"] = [{k: v for k, v in s.items() if k != "retrieved_at"} for s in stable["sources"]]
    context["context_hash"] = canonical_hash(stable)
    return context


def junction_context(angle=23, width=12):
    context = road_context()
    def place(geometry):
        return translate(rotate(geometry, angle, origin=(0, 0)), X, Y)
    core = place(box(-8.1, -8.1, 8.1, 8.1))
    approaches, anchors, roads = [], [], []
    for index, (start, end) in enumerate((((8, 0), (68, 0)), ((0, 8), (0, 68)), ((-8, 0), (-68, 0)), ((0, -8), (0, -68)))):
        line = place(LineString([start, end]))
        surface = line.buffer(width/2, cap_style="flat")
        identifier = "road-" + f"{index+1:012x}"
        anchor = {"id": identifier, "kind": "road", "geometry": _geographic(line), "surface": _geographic(surface),
                  "width_m": width, "length_m": line.length, "width_basis": "fixture mapped envelope",
                  "selection_offset_m": 0., "supported_kinds": ["intersection_redesign", "crossing", "curb_extension"],
                  "traffic_direction": "two_way"}
        anchors.append(anchor); roads.append(surface)
        approaches.append({"id": f"approach-{index+1}", "anchor_id": identifier, "geometry": _geographic(line),
                           "road_geometry": _geographic(surface), "mouth": _geographic(Point(line.coords[0])),
                           "bearing_deg": index*90., "direction": "two_way", "width_m": width,
                           "junction_offset_m": 0., "outward_sign": 1, "crossing_offset_m": 4.,
                           "available_length_m": line.length, "crossing_span_m": width, "walking_landings": []})
    junction = {"id": "junction-000000000001", "center": _geographic(Point(X, Y)), "area": _geographic(core),
                "plan_area": _geographic(unary_union([core, *roads])), "distance_m": 0.,
                "basis": "sourced_fixture_junction", "source_hash": "a"*64, "approaches": approaches}
    context["anchors"] = anchors; context["junctions"] = [junction]
    return rehash_context(context)


def package(context, **kwargs):
    junction = context["junctions"][0]
    return {"id": "intersection", "kind": "intersection_redesign", "anchor_id": junction["approaches"][0]["anchor_id"],
            "junction_id": junction["id"], **kwargs}


class JunctionDesignTests(unittest.TestCase):
    def test_whole_plan_is_source_anchored_connected_and_masks_old_paint(self):
        context = junction_context()
        value = build_road_concept(context, [package(context)], identity=identity())
        self.assertEqual(value["compiler_version"], "road-concept-v2")
        self.assertEqual(validate_road_concept(json.loads(json.dumps(value))), value)
        self.assertEqual(value["checks"][0]["crossing_count"], 4)
        self.assertEqual(value["checks"][0]["approach_count"], 4)
        self.assertTrue(value["checks"][0]["connected"])
        influence = projected(value["geometry"][0]["geometry"])
        self.assertEqual(influence.geom_type, "Polygon")
        self.assertEqual(value["geometry"][0]["properties"]["surface"], "roadway")
        source = projected(context["junctions"][0]["plan_area"])
        self.assertLess(influence.difference(source.buffer(.01)).area, .01)
        self.assertGreater(influence.area, 1000)
        surfaces = {f["properties"]["surface"] for f in value["geometry"]}
        self.assertEqual(surfaces, {"roadway", "sidewalk", "curb", "centerline", "crosswalk", "stop_line", "lane_arrow"})
        for feature in value["geometry"]:
            with self.subTest(feature=feature["id"]):
                geometry = projected(feature["geometry"])
                self.assertTrue(geometry.is_valid)
                self.assertLess(geometry.difference(influence.buffer(.01)).area, .01)
        checks = value["checks"][0]
        self.assertAlmostEqual(checks["roadway_area_m2"]+checks["sidewalk_area_m2"], checks["area_m2"], places=2)

    def test_crossings_follow_every_mouth_and_touch_pedestrian_landings(self):
        context = junction_context(angle=37)
        concept = build_road_concept(context, [package(context)], identity=identity())
        sidewalks = unary_union([projected(f["geometry"]) for f in concept["geometry"] if f["properties"]["surface"] == "sidewalk"])
        crosses = [projected(f["geometry"]) for f in concept["geometry"] if f["properties"]["surface"] == "crosswalk"]
        for approach, stripes in zip(context["junctions"][0]["approaches"], crosses):
            line = projected(approach["geometry"], ("LineString",))
            self.assertAlmostEqual(line.project(stripes.centroid), 5.5, places=1)
            self.assertLess(stripes.distance(sidewalks), .6)
            self.assertLess(stripes.area, 30)

    def test_disconnected_midblock_crossing_rejected_but_marked_crossing_works(self):
        context = road_context()
        # Current contexts explicitly say no sourced junction was found.
        context["junctions"] = []; rehash_context(context)
        with self.assertRaisesRegex(ConceptPlacementError, "sourced junction mouth"):
            build_road_concept(context, [{"id": "cross", "kind": "crossing", "anchor_id": context["anchors"][0]["id"]}], identity=identity())

    def test_constraints_and_untrusted_footprint_fail_closed(self):
        context = junction_context(angle=0)
        building = {"geometry": _geographic(box(X-1, Y-1, X+1, Y+1)), "properties": {"label": "Building footprint"}}
        with self.assertRaisesRegex(ConceptPlacementError, "mapped building"):
            build_road_concept(context, [package(context)], identity=identity(), evidence={"outlines": [building]})
        marking = {"kind": "access", "geometry": _geographic(box(X+10, Y+4, X+16, Y+6))}
        with self.assertRaisesRegex(ConceptPlacementError, "keep-clear"):
            build_road_concept(context, [package(context)], identity=identity(), markings=[marking])
        bad = copy.deepcopy(context)
        bad["junctions"][0]["approaches"][0]["mouth"] = _geographic(Point(X+30, Y+30))
        rehash_context(bad)
        with self.assertRaisesRegex(ConceptPlacementError, "detached"):
            build_road_concept(bad, [package(bad)], identity=identity())

    def test_revision_preserves_unspecified_choices_and_revalidates_source(self):
        context = junction_context()
        original = build_road_concept(context, [package(context, approach_length_m=35., crossing_width_m=4.)], identity=identity())
        revised = build_road_concept(context, changes=[{"id": "intersection", "op": "update", "curb_extension_m": 1.8}], previous=original, identity=identity(2, 1))
        self.assertEqual(revised["components"][0]["approach_length_m"], 35.)
        self.assertEqual(revised["components"][0]["crossing_width_m"], 4.)
        self.assertNotEqual(original["geometry"], revised["geometry"])
        self.assertEqual(validate_road_concept(revised), revised)
        changed = copy.deepcopy(context); changed["junctions"][0]["source_hash"] = "b"*64; rehash_context(changed)
        with self.assertRaisesRegex(ConceptPlacementError, "sourced junction changed"):
            build_road_concept(changed, changes=[{"id": "intersection", "op": "update", "curb_extension_m": 1.8}], previous=original, identity=identity(2, 1))

    def test_rehashed_geometry_edit_cannot_publish_and_roundabout_is_not_guessed(self):
        context = junction_context()
        concept = build_road_concept(context, [package(context)], identity=identity())
        changed = copy.deepcopy(concept)
        changed["geometry"][0]["properties"]["surface"] = "sidewalk"
        changed["input_hash"] = canonical_hash({k:v for k,v in changed.items() if k != "input_hash"})
        with self.assertRaises(ConceptPlacementError):
            validate_road_concept(changed)
        with self.assertRaisesRegex(ConceptPlacementError, "turn paths"):
            build_road_concept(context, [package(context, layout="roundabout")], identity=identity())

    def test_production_source_contexts_compile_without_fabricated_junctions(self):
        from tests.test_junction_context import junction_context as sourced, sumo_context
        for context in (sourced(), sourced(walking=False), sourced(legs=3), sumo_context(), sumo_context(minor_node=True)):
            with self.subTest(context=context["junctions"][0]["basis"]):
                value = build_road_concept(context, [package(context)], identity=identity())
                self.assertEqual(validate_road_concept(value), value)
                self.assertEqual(value["checks"][0]["crossing_count"], len(context["junctions"][0]["approaches"]))

    def test_one_way_junction_rejected_and_T_arm_has_no_false_straight_arrow(self):
        from tests.test_junction_context import junction_context as sourced
        context = sourced(legs=3)
        value = build_road_concept(context, [package(context)], identity=identity())
        approaches = context["junctions"][0]["approaches"]
        for index, approach in enumerate(approaches):
            if approach["direction"] == "north":
                self.assertFalse(any(f["id"].startswith(f"intersection-approach-{index+1}-arrow") for f in value["geometry"]))
        context["junctions"][0]["approaches"][0]["traffic_direction"] = "one_way"
        rehash_context(context)
        with self.assertRaisesRegex(ConceptPlacementError, "one-way or unverified"):
            build_road_concept(context, [package(context)], identity=identity())

    def test_service_access_opening_remains_drivable_without_a_curb_barrier(self):
        context = junction_context(angle=0)
        opening = box(X+20, Y+1, X+24, Y+6)
        context["junctions"][0]["approaches"][0]["access_openings"] = [{"geometry": _geographic(opening)}]
        rehash_context(context)
        value = build_road_concept(context, [package(context)], identity=identity())
        self.assertEqual(value["checks"][0]["access_openings_preserved"], 1)
        physical = unary_union([projected(f["geometry"]) for f in value["geometry"] if f["properties"]["surface"] in ("curb", "sidewalk")])
        self.assertLess(physical.intersection(opening).area, .02)

    def test_access_outside_shorter_plan_is_not_counted_and_duplicates_count_once(self):
        context = junction_context(angle=0)
        approach = context["junctions"][0]["approaches"][0]
        inside = {"id": "service-in", "geometry": _geographic(box(X+18, Y+1, X+21, Y+6))}
        outside = {"id": "service-out", "geometry": _geographic(box(X+50, Y+1, X+54, Y+6))}
        approach["access_openings"] = [inside, copy.deepcopy(inside), outside]
        rehash_context(context)
        value = build_road_concept(context, [package(context, approach_length_m=20.)], identity=identity())
        self.assertEqual(value["checks"][0]["access_openings_preserved"], 1)

    def test_narrow_lane_only_envelope_does_not_create_token_sidewalks(self):
        context = junction_context(width=6.4)
        with self.assertRaisesRegex(ConceptPlacementError, "too narrow"):
            build_road_concept(context, [package(context)], identity=identity())

    def test_source_corner_repair_connects_the_full_walking_network(self):
        from tests.test_junction_context import junction_context as sourced
        context = sourced()
        value = build_road_concept(context, [package(context)], identity=identity())
        self.assertTrue(value["checks"][0]["pedestrian_connected"])
        influence = projected(value["geometry"][0]["geometry"])
        walk = [projected(f["geometry"]) for f in value["geometry"] if f["properties"]["surface"] == "sidewalk"]
        params = value["components"][0]
        for approach in context["junctions"][0]["approaches"]:
            line = projected(approach["geometry"], ("LineString",))
            position = params["crossing_setback_m"]+params["crossing_width_m"]/2
            center = line.interpolate(position)
            a, b = line.interpolate(position-.1), line.interpolate(position+.1)
            nx, ny = -(b.y-a.y)/a.distance(b), (b.x-a.x)/a.distance(b)
            span = approach["plan_width_m"]/2
            band = LineString([(center.x+nx*span, center.y+ny*span), (center.x-nx*span, center.y-ny*span)]).buffer(params["crossing_width_m"]/2, cap_style="flat")
            walk.append(band.intersection(influence))
        network = unary_union(walk).buffer(.03)
        self.assertEqual(network.geom_type, "Polygon")
        # Merely asserting a connected carriageway would miss these old gaps.
        broken = copy.deepcopy(context)
        broken["junctions"][0]["pedestrian_connections"] = []
        # Retain the drivable six-metre corridor while severing the pedestrian
        # edges of one approach beyond its crossing.
        arm = broken["junctions"][0]["approaches"][0]
        line = projected(arm["geometry"], ("LineString",))
        from shapely.ops import substring
        first = substring(line, 12., 14.)
        road = projected(arm["road_geometry"])
        arm["road_geometry"] = _geographic(unary_union([road.difference(first.buffer(30, cap_style="flat")), first.buffer(3, cap_style="flat")]))
        rehash_context(broken)
        with self.assertRaisesRegex(ConceptPlacementError, "pedestrian network has a gap"):
            build_road_concept(broken, [package(broken)], identity=identity())

    def test_old_v1_concept_replays_without_new_junction_gate(self):
        context = road_context()
        context.pop("junctions", None); rehash_context(context)
        component = {"id": "cross", "kind": "crossing", "anchor_id": context["anchors"][0]["id"]}
        value = build_road_concept(context, [component], identity=identity())
        value["compiler_version"] = "road-concept-v1"
        value["input_hash"] = canonical_hash({k:v for k,v in value.items() if k != "input_hash"})
        self.assertEqual(validate_road_concept(json.loads(json.dumps(value))), value)
        self.assertNotIn("junction_id", value["components"][0])


if __name__ == "__main__":
    unittest.main()
