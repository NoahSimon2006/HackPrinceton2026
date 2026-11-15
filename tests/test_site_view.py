import csv
from copy import deepcopy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

from server import Handler, STATIC
from site_view import ADDRESS, MODEL_ID, PROPERTY_ID, TITLE, UNAVAILABLE, SiteViewUnavailable, site_view_descriptor


PROPERTY = {"id": PROPERTY_ID, "lat": 34.037124, "lon": -118.253067,
            "name": "Wall Street Garment Center", "address": ADDRESS, "type": "GeneralRetail"}


class SiteViewTest(unittest.TestCase):
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
        return site_view_descriptor(self.root, catalog if catalog is not None else [PROPERTY])

    def request(self, path="/api/site-view"):
        handler = Handler.__new__(Handler)
        handler.path = path
        handler.send_json = Mock()
        with patch.dict("os.environ", {"COSTAR_KIT_DIR": str(self.root)}), \
             patch("server.property_catalog", return_value=([PROPERTY], {}, {})), \
             patch("urllib.request.urlopen", side_effect=AssertionError("No external requests are allowed.")):
            handler.do_GET()
        return handler.send_json.call_args.args

    def test_fixed_join_and_caption_produce_allowlisted_descriptor_without_external_call(self):
        self.rows.append({**self.rows[0], "MatterportModelId": "2wKwkYGbkPc"})
        self.write()
        status, result = self.request()
        self.assertEqual(status, 200)
        self.assertEqual(result["property"], PROPERTY)
        self.assertEqual(result["status"], "linked")
        self.assertEqual(result["scan"], {"modelId": MODEL_ID, "title": TITLE,
                                         "url": "https://my.matterport.com/show/?m=35LT5s1GSfA"})
        self.assertIn("visual inspection", " ".join(result["limitations"]))
        self.assertIn("proposed-design view is unavailable", " ".join(result["limitations"]))
        self.assertEqual(result["source"]["attachmentDate"], "2024-12-05T19:40:31.783-05:00")
        serialized = json.dumps(result)
        self.assertNotIn(str(self.root), serialized)
        self.assertNotIn("PRIVATE", serialized)
        self.assertNotIn("untrusted.invalid", serialized)
        self.assertEqual(STATIC["/site-view.js"], "site-view.js")

    def test_catalog_extras_and_query_urls_cannot_change_the_fixed_viewer(self):
        result = self.descriptor([{**PROPERTY, "sdkKey": "PRIVATE-KEY", "contacts": "PRIVATE-CONTACT",
                                   "url": "javascript:PRIVATE-URL"}])
        self.assertEqual(set(result["property"]), {"id", "lat", "lon", "name", "address", "type"})
        self.assertNotIn("PRIVATE", json.dumps(result))
        status, result = self.request("/api/site-view?model=OTHER&url=https://untrusted.invalid")
        self.assertEqual(status, 200)
        self.assertEqual(result["scan"]["modelId"], MODEL_ID)

    def test_wrong_csv_model_property_or_address_is_unavailable(self):
        original = deepcopy(self.rows)
        for key, value in (("MatterportModelId", "2wKwkYGbkPc"), ("PropertyId", "4483806"),
                           ("Address", "PRIVATE OTHER ADDRESS"), ("City", "Other"), ("State", "NY")):
            with self.subTest(field=key):
                self.rows = [{**original[0], key: value}]
                self.write()
                with self.assertRaisesRegex(SiteViewUnavailable, "local source association"):
                    self.descriptor()
        self.rows = original + [{**original[0], "PropertyId": "4483806"}]
        self.write()
        with self.assertRaises(SiteViewUnavailable):
            self.descriptor()

    def test_attachment_must_confirm_exact_exterior_model_membership(self):
        original = deepcopy(self.record["attachments"][0])
        for key, value in (("videoKey", "2wKwkYGbkPc"), ("caption", "Interior suite tour"),
                           ("videoExternalReferenceType", 0), ("caption", None), ("videoKey", None)):
            with self.subTest(field=key):
                self.record["attachments"] = [{**original, key: value}]
                self.write()
                with self.assertRaises(SiteViewUnavailable):
                    self.descriptor()
        self.record["attachments"] = [{**original, "videoExternalReferenceType": 234}]
        self.write()
        self.assertEqual(self.descriptor()["scan"]["modelId"], MODEL_ID)
        self.record["attachments"].append(original)
        self.write()
        with self.assertRaises(SiteViewUnavailable):
            self.descriptor()

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
        self.assertEqual(self.request(), (503, {"error": UNAVAILABLE}))

    def test_catalog_failures_do_not_expose_local_paths(self):
        handler = Handler.__new__(Handler)
        handler.path = "/api/site-view"
        handler.send_json = Mock()
        with patch("server.property_catalog", side_effect=FileNotFoundError("PRIVATE LOCAL KIT PATH")):
            handler.do_GET()
        self.assertEqual(handler.send_json.call_args.args, (503, {"error": UNAVAILABLE}))


if __name__ == "__main__":
    unittest.main()
