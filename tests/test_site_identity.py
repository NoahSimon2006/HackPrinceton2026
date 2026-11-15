import unittest
from unittest.mock import patch

import server
from site_identity import resolve_site
from test_site_measurements import LON, LAT, polygon, feature


PROPERTY = {"id": "one", "name": "Site one", "address": "Source address", "type": "Multifamily", "lon": LON, "lat": LAT}


class SiteIdentityTest(unittest.TestCase):
    def test_same_parcel_match_preserves_a_distinct_map_point(self):
        outlines = [feature(polygon(-30, -30, 60, 60), "Parcel boundary")]
        result = resolve_site([PROPERTY], LON + .0001, LAT, outlines)
        self.assertEqual(result["status"], "matched")
        self.assertEqual(result["property"], PROPERTY)
        self.assertIn("spatial match", result["message"])

    def test_nearest_property_is_not_a_match_without_a_containing_parcel(self):
        result = resolve_site([PROPERTY], LON + .0001, LAT, [])
        self.assertEqual(result["status"], "unmatched")
        self.assertIsNone(result["property"])
        self.assertEqual(result["candidates"], [PROPERTY])

    def test_multiple_properties_or_overlapping_parcels_are_explicit(self):
        outlines = [feature(polygon(-30, -30, 60, 60), "Parcel boundary")]
        duplicate = {**PROPERTY, "id": "two"}
        self.assertEqual(resolve_site([PROPERTY, duplicate], LON, LAT, outlines)["status"], "ambiguous")
        outlines.append(feature(polygon(-20, -20, 60, 60), "Parcel boundary"))
        self.assertEqual(resolve_site([PROPERTY], LON, LAT, outlines)["status"], "ambiguous")
        with self.assertRaises(ValueError):
            resolve_site([PROPERTY], LON + .0001, LAT, outlines, property_id="one")

    def test_explicit_search_selection_is_distinct_from_an_inferred_match(self):
        result = resolve_site([PROPERTY], LON, LAT, [], property_id="one")
        self.assertEqual(result["status"], "selected")
        with self.assertRaises(ValueError):
            resolve_site([PROPERTY], LON + .001, LAT, [], property_id="one")

    def test_duplicate_geometry_is_not_a_second_parcel(self):
        outlines = [feature(polygon(-30, -30, 60, 60), "Parcel boundary")]
        self.assertEqual(resolve_site([PROPERTY], LON, LAT, outlines * 2)["status"], "matched")

    def test_outage_keeps_nearby_properties_unassigned(self):
        with patch("server.property_catalog", return_value=([PROPERTY], {}, {})), patch("server.site_outlines", side_effect=ValueError("offline")):
            result = server.site_resolution(LON + .0001, LAT, "water")
        self.assertEqual(result["status"], "unavailable")
        self.assertIsNone(result["property"])

    def test_cached_source_is_shared_without_sharing_measurement_mutations(self):
        server._site_outlines.cache_clear()
        self.addCleanup(server._site_outlines.cache_clear)
        source = [feature(polygon(-30, -30, 60, 60), "Parcel boundary")]
        with patch("server.imagery_evidence", return_value=source) as fetch, patch("server.time.monotonic", return_value=100):
            first = server.site_outlines(LON, LAT, "water")
            first[0]["properties"]["evidenceId"] = "mutated"
            second = server.site_outlines(LON, LAT, "water")
        self.assertNotIn("evidenceId", second[0]["properties"])
        self.assertEqual(fetch.call_count, 1)
