import unittest

from site_evidence import detection_features, parcel_features


class DetectionParsingTest(unittest.TestCase):
    def test_source_features_are_not_truncated_before_conflict_checks(self):
        polygon = {'type':'Polygon','coordinates':[[[-118.25,34.05],[-118.2499,34.05],[-118.2499,34.0501],[-118.25,34.05]]]}
        structures = [{'footprint.wkt':polygon} for _ in range(15)]
        payload = {'features':[{'geometry':polygon,'properties':{'request-information.inside-parcel':True,'structures':structures}}]}
        evidence={'outlines':[]}
        parcel_features(payload,evidence)
        self.assertEqual(len(evidence['outlines']),16)
        structures[-1]['footprint.wkt']='malformed'
        with self.assertRaises(ValueError):parcel_features(payload,{'outlines':[]})
        evidence={'detections':[]}
        candidates=[{'bbox':polygon,'confidence':1-i/20} for i in range(15)]
        detection_features({'features':[{'properties':{'label':'zebra crosswalk','detections':candidates}}]},evidence,('zebra crosswalk',))
        self.assertEqual(len(evidence['detections']),15)
        self.assertAlmostEqual(evidence['detections'][-1]['properties']['score'],.3)

    def test_invalid_detection_confidence_is_unavailable_not_a_ui_type_error(self):
        polygon={'type':'Polygon','coordinates':[]}
        for value in (True,'0.7',float('nan'),float('inf'),-1,1.1):
            with self.subTest(value=value), self.assertRaises(ValueError):
                detection_features({'features':[{'properties':{'label':'zebra crosswalk','detections':[{'bbox':polygon,'confidence':value}]}}]},
                                   {'detections':[]},('zebra crosswalk',))

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
