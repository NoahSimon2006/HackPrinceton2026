import csv
from copy import deepcopy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

from server import Handler, STATIC
from site_view import UNAVAILABLE, SiteViewUnavailable, site_view_descriptor

PROPERTY_ID = "6067080"
MODEL_ID = "35LT5s1GSfA"
ADDRESS = "510 E Olympic Blvd"
TITLE = "3D Tour of the Building Exterior & Loading Docks"


PROPERTY = {"id": PROPERTY_ID, "lat": 34.037124, "lon": -118.253067,
            "name": "Wall Street Garment Center", "address": ADDRESS, "type": "GeneralRetail"}


class SiteViewTest(unittest.TestCase):
    def test_a_different_property_opens_only_its_own_models(self):
        other = {**PROPERTY, "id": "123456", "name": "Another property", "address": "600 E Olympic Blvd", "lat": PROPERTY["lat"] + .001}
        second = deepcopy(self.record)
        second["id"] = int(other["id"])
        second["primaryAddress"].update(streetNumber="600", latitude=other["lat"])
        second["attachments"][0].update(videoKey="abcdefghijk", caption="Courtyard view")
        self.rows.append({**self.rows[0], "PropertyId": other["id"], "Address": other["address"], "MatterportModelId": "abcdefghijk"})
        self.write()
        with (self.root / "data/commercial-property.jsonl").open("a") as file:
            file.write(json.dumps(second) + "\n")
        result = site_view_descriptor(self.root, [PROPERTY, other], other["id"])
        self.assertEqual(result["property"], other)
        self.assertEqual(result["scan"]["modelId"], "abcdefghijk")
        self.assertNotIn(MODEL_ID, json.dumps(result))
        self.assertTrue(result["scan"]["exteriorHint"])

    def test_multiple_tours_are_validated_and_exterior_titles_are_only_hints(self):
        self.rows.append({**self.rows[0], "MatterportModelId": "abcdefghijk"})
        self.record["attachments"].append({**self.record["attachments"][0], "videoKey": "abcdefghijk", "caption": "Courtyard exterior"})
        self.write()
        result = self.descriptor()
        self.assertEqual(len(result["scans"]), 2)
        self.assertEqual(result["scan"]["modelId"], MODEL_ID)
        self.assertIn("visual inspection", " ".join(result["limitations"]))

    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        (self.root / "data").mkdir()
        self.rows = [{"PropertyId": PROPERTY_ID, "MatterportModelId": MODEL_ID, "Address": ADDRESS,
                      "City": "Los Angeles", "State": "CA"}]
        self.record = {"id": int(PROPERTY_ID), "primaryAddress": {
            "streetNumber": "510", "streetDirection": "E", "streetName": "Olympic", "streetType": "Blvd",
            "latitude": PROPERTY["lat"], "longitude": PROPERTY["lon"]},
            "attachments": [{"videoKey": MODEL_ID, "videoExternalReferenceType": 36, "caption": TITLE,
                             "originationDate": "2024-12-05T19:40:31.783-05:00",
                             "attachmentUri": "https://untrusted.invalid/PRIVATE-ATTACHMENT", "sdkKey": "PRIVATE-SDK-KEY"}],
            "contacts": [{"name": "PRIVATE-CONTACT"}], "notes": "PRIVATE-NOTES"}
        self.write()

    def write(self):
        with (self.root / "commercial-properties.csv").open("w", newline="") as file:
            writer = csv.DictWriter(file, fieldnames=["PropertyId", "MatterportModelId", "Address", "City", "State"])
            writer.writeheader()
            writer.writerows(self.rows)
        (self.root / "data/commercial-property.jsonl").write_text(json.dumps(self.record) + "\n")

    def descriptor(self, catalog=None):
        return site_view_descriptor(self.root, catalog if catalog is not None else [PROPERTY], PROPERTY_ID)

    def request(self, path="/api/site-view?propertyId=" + PROPERTY_ID):
        handler = Handler.__new__(Handler)
        handler.path = path
        handler.send_json = Mock()
        with patch.dict("os.environ", {"COSTAR_KIT_DIR": str(self.root)}), \
             patch("server.property_catalog", return_value=([PROPERTY], {}, {})), \
             patch("urllib.request.urlopen", side_effect=AssertionError("No external requests are allowed.")):
            handler.do_GET()
        return handler.send_json.call_args.args

    def test_selected_property_join_and_caption_produce_allowlisted_descriptor_without_external_call(self):
        self.rows.append({**self.rows[0], "MatterportModelId": "2wKwkYGbkPc"})
        self.write()
        status, result = self.request()
        self.assertEqual(status, 200)
        self.assertEqual(result["property"], PROPERTY)
        self.assertEqual(result["status"], "linked")
        self.assertEqual(result["scan"]["modelId"], MODEL_ID)
        self.assertEqual(result["scan"]["url"], "https://my.matterport.com/show/?m=" + MODEL_ID)
        self.assertEqual(result["scans"], [result["scan"]])
        self.assertIn("visual inspection", " ".join(result["limitations"]))
        self.assertIn("proposed-design view is unavailable", " ".join(result["limitations"]))
        self.assertEqual(result["scan"]["attachmentDate"], "2024-12-05T19:40:31.783-05:00")
        serialized = json.dumps(result)
        self.assertNotIn(str(self.root), serialized)
        self.assertNotIn("PRIVATE", serialized)
        self.assertNotIn("untrusted.invalid", serialized)
        self.assertEqual(STATIC["/site-view.js"], "site-view.js")

    def test_catalog_extras_and_query_urls_cannot_redirect_the_viewer(self):
        result = self.descriptor([{**PROPERTY, "sdkKey": "PRIVATE-KEY", "contacts": "PRIVATE-CONTACT",
                                   "url": "javascript:PRIVATE-URL"}])
        self.assertEqual(set(result["property"]), {"id", "lat", "lon", "name", "address", "type"})
        self.assertNotIn("PRIVATE", json.dumps(result))
        status, result = self.request("/api/site-view?model=OTHER&url=https://untrusted.invalid")
        self.assertEqual(status, 400)
        self.assertEqual(self.request("/api/site-view")[0], 400)

    def test_wrong_csv_model_property_or_address_is_unavailable(self):
        original = deepcopy(self.rows)
        for key, value in (("MatterportModelId", "2wKwkYGbkPc"), ("PropertyId", "4483806"),
                           ("Address", "PRIVATE OTHER ADDRESS"), ("City", "Other"), ("State", "NY")):
            with self.subTest(field=key):
                self.rows = [{**original[0], key: value}]
                self.write()
                self.assertEqual(self.descriptor()["status"], "unavailable")
        self.rows = original + [{**original[0], "PropertyId": "4483806"}]
        self.write()
        # A model also listed under another property still opens when this
        # property's own address row and attachment confirm it; the overlap is disclosed.
        shared = self.descriptor()
        self.assertEqual(shared["status"], "linked")
        self.assertTrue(shared["scan"]["sharedWithOtherProperty"])
        self.assertIn("also listed under another property", shared["limitations"][0])

    def test_attachment_confirms_membership_and_interior_tours_are_included(self):
        original = deepcopy(self.record["attachments"][0])
        for key, value in (("videoKey", "2wKwkYGbkPc"),
                           ("videoExternalReferenceType", 0), ("videoKey", None)):
            with self.subTest(field=key):
                self.record["attachments"] = [{**original, key: value}]
                self.write()
                self.assertEqual(self.descriptor()["status"], "unavailable")
        self.record["attachments"] = [{**original, "videoExternalReferenceType": 234}]
        self.write()
        self.assertEqual(self.descriptor()["scan"]["modelId"], MODEL_ID)
        self.record["attachments"] = [{**original, "caption": "Interior suite tour"}]
        self.write()
        self.assertEqual(self.descriptor()["status"], "linked")
        self.assertEqual(self.descriptor()["scan"]["contextLabel"], "Interior")
        self.assertFalse(self.descriptor()["scan"]["exteriorHint"])
        self.record["attachments"].append(original)
        self.write()
        self.assertEqual(self.descriptor()["tourCount"], 1)

    def test_duplicate_model_metadata_is_preserved_without_duplicate_tours(self):
        original = self.record["attachments"][0]
        self.record["attachments"].extend([{**original, "caption": "Fitness Center", "originationDate": "2025-01-01"},
                                           {**original, "caption": "Pool", "originationDate": "bad date"}])
        self.rows.append(dict(self.rows[0]))
        self.write()
        result = self.descriptor()
        self.assertEqual(result["tourCount"], 1)
        self.assertEqual(result["excludedTourCount"], 0)
        self.assertEqual(result["scan"]["titles"], [TITLE, "Fitness Center", "Pool"])
        self.assertEqual(result["scan"]["attachmentDates"], ["2024-12-05T19:40:31.783-05:00", "2025-01-01"])
        self.assertNotIn("PRIVATE", json.dumps(result))

    def test_optional_metadata_and_property_name_whitespace_do_not_block_identity(self):
        self.record["attachments"][0].update(caption=None, originationDate="not a date")
        self.write()
        result = self.descriptor([{**PROPERTY, "name": "Wall Street\r\n Garment Center"}])
        self.assertEqual(result["status"], "linked")
        self.assertEqual(result["property"]["name"], PROPERTY["name"])
        self.assertEqual(result["scan"]["title"], "3D property tour")
        self.assertIsNone(result["scan"]["attachmentDate"])
        self.assertEqual(result["scan"]["contextLabel"], "Unspecified")
        self.record["attachments"][0]["caption"] = "Fitness\r\n Center"
        self.write()
        self.assertEqual(self.descriptor()["scan"]["title"], "Fitness Center")
        self.assertEqual(self.descriptor()["scan"]["contextLabel"], "Amenity")

    def test_canonical_range_and_suffix_address_still_rejects_wrong_identity(self):
        self.record["primaryAddress"].update(streetNumberEndRange="520", streetSuffix="E")
        correct = "510-520 E Olympic Blvd E"
        self.rows[0]["Address"] = correct
        self.write()
        self.assertEqual(self.descriptor([{**PROPERTY, "address": correct}])["status"], "linked")
        with self.assertRaises(SiteViewUnavailable):
            self.descriptor()
        self.rows[0]["Address"] = "510-520 E Olympic Blvd W"
        self.write()
        result = self.descriptor([{**PROPERTY, "address": correct}])
        self.assertEqual(result["status"], "unavailable")
        self.assertEqual(result["exclusions"][0]["reason"], "address_mismatch")

    def test_exclusions_explain_invalid_associations_beside_valid_tours(self):
        self.rows.extend([{**self.rows[0], "MatterportModelId": "bad"},
                          {**self.rows[0], "MatterportModelId": "abcdefghijk"}])
        self.write()
        result = self.descriptor()
        self.assertEqual(result["status"], "linked")
        self.assertEqual(result["tourCount"], 1)
        self.assertEqual(result["excludedTourCount"], 2)
        self.assertEqual({item["reason"] for item in result["exclusions"]}, {"invalid_model_id", "missing_attachment"})
        self.assertNotIn("PRIVATE", json.dumps(result))

    def test_malformed_individual_models_do_not_hide_valid_tours(self):
        original = self.record["attachments"][0]
        self.record["attachments"].extend([{**original, "videoKey": []}, {**original, "videoKey": {}},
                                           {**original, "videoKey": None}, None])
        self.write()
        # A short CSV row creates None for missing columns, unlike an empty cell.
        with (self.root / "commercial-properties.csv").open("a") as file:
            file.write(PROPERTY_ID + "\n")
        result = self.descriptor()
        self.assertEqual(result["status"], "linked")
        self.assertEqual(result["tourCount"], 1)
        self.assertEqual(result["scan"]["modelId"], MODEL_ID)
        self.assertEqual(result["exclusions"], [{"reason": "invalid_model_id", "count": 1,
                          "message": "A listed tour has no valid Matterport model identifier."}])

    def test_malformed_attachment_collection_is_local_to_its_property(self):
        other = deepcopy(self.record)
        other["id"] = 123456
        other["attachments"] = {"videoKey": MODEL_ID, "private": "PRIVATE"}
        self.write()
        with (self.root / "data/commercial-property.jsonl").open("a") as file:
            file.write(json.dumps(other) + "\n")
        self.assertEqual(self.descriptor()["tourCount"], 1)
        self.record["attachments"] = "PRIVATE malformed collection"
        self.write()
        result = self.descriptor()
        self.assertEqual(result["status"], "unavailable")
        self.assertEqual(result["exclusions"][0]["reason"], "invalid_attachment_collection")
        self.assertNotIn("PRIVATE", json.dumps(result))

    def test_missing_or_corrupt_local_sources_return_only_safe_error(self):
        for filename in ("commercial-properties.csv", "data/commercial-property.jsonl"):
            with self.subTest(file=filename):
                self.write()
                (self.root / filename).unlink()
                self.assertEqual(self.request(), (503, {"error": UNAVAILABLE}))
        self.write()
        (self.root / "commercial-properties.csv").write_text("PropertyId,PRIVATE_HEADER\n")
        self.assertEqual(self.request(), (503, {"error": UNAVAILABLE}))
        self.write()
        (self.root / "data/commercial-property.jsonl").write_text("PRIVATE-BROKEN-RECORD")
        self.assertEqual(self.request(), (503, {"error": UNAVAILABLE}))

    def test_property_identity_coordinates_and_attachment_metadata_are_required(self):
        for catalog in ([], [{**PROPERTY, "id": "4483806"}], [PROPERTY, PROPERTY],
                        [{**PROPERTY, "lat": float("nan")}], [{**PROPERTY, "lon": -80}],
                        [{**PROPERTY, "address": "PRIVATE OTHER ADDRESS"}]):
            with self.subTest(catalog=catalog):
                with self.assertRaises(SiteViewUnavailable):
                    self.descriptor(catalog)
        self.record["primaryAddress"]["latitude"] += .01
        self.write()
        with self.assertRaises(SiteViewUnavailable):
            self.descriptor()
        self.record["primaryAddress"]["latitude"] = PROPERTY["lat"]
        self.record["primaryAddress"]["longitude"] = PROPERTY["lon"] + 5e-8
        self.write()
        with self.assertRaises(SiteViewUnavailable):
            self.descriptor()
        self.record["primaryAddress"]["longitude"] = PROPERTY["lon"]
        self.record.pop("attachments")
        self.write()
        self.assertEqual(self.request()[1]["status"], "unavailable")

    def test_catalog_failures_do_not_expose_local_paths(self):
        handler = Handler.__new__(Handler)
        handler.path = "/api/site-view?propertyId=" + PROPERTY_ID
        handler.send_json = Mock()
        with patch("server.property_catalog", side_effect=FileNotFoundError("PRIVATE LOCAL KIT PATH")):
            handler.do_GET()
        self.assertEqual(handler.send_json.call_args.args, (503, {"error": UNAVAILABLE}))


if __name__ == "__main__":
    unittest.main()
