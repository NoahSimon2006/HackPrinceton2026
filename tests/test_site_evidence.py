import unittest

from site_evidence import detection_features


class DetectionParsingTest(unittest.TestCase):
    def test_successful_empty_detection_collection_remains_empty(self):
        evidence = {"detections": []}
        detection_features({"features": []}, evidence, ("zebra crosswalk",))
        self.assertEqual(evidence["detections"], [])

    def test_malformed_provider_candidates_are_not_silently_dropped(self):
        for candidate in ({"bbox": "malformed"}, {"bbox": {"type": "Point", "coordinates": [-118.24, 34.05]}}, None):
            with self.subTest(candidate=candidate), self.assertRaises(ValueError):
                detection_features({"features": [{"properties": {"label": "zebra crosswalk", "detections": [candidate]}}]},
                                   {"detections": []}, ("zebra crosswalk",))
        with self.assertRaises(ValueError):
            detection_features({}, {"detections": []}, ("zebra crosswalk",))
        for properties in ({}, {"label": "zebra crosswalk"}, {"label": None}, {"label": ""}):
            with self.subTest(properties=properties), self.assertRaises(ValueError):
                detection_features({"features": [{"properties": properties}]}, {"detections": []}, ("zebra crosswalk",))


if __name__ == "__main__":
    unittest.main()
