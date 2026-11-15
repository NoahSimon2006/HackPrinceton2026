import unittest

from site_evidence import detection_features, imagery_evidence, parcel_features


class ParcelQueryTest(unittest.TestCase):
    def test_intersection_queries_neighboring_parcels_without_a_containing_parcel(self):
        from json import dumps
        from test_site_measurements import LAT, LON, polygon

        def request(path, params, *args, **kwargs):
            self.assertEqual(path, "/property/extract")
            self.assertEqual(params["buffer-meter"], 200)
            return dumps({"features":[{"geometry":polygon(10, 10, 30, 30),
                                        "properties":{"structures":None}}]})
        items = imagery_evidence(request, "urban", LON, LAT, "street", "outlines")
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]["properties"]["label"], "Parcel boundary")
        self.assertFalse(items[0]["properties"]["buildingCoverage"])


class DetectionParsingTest(unittest.TestCase):
    def test_mixed_capture_years_do_not_become_overlapping_current_parcels(self):
        from site_evidence import recent_parcel_collections
        features = [{'properties': {'request-information.inside-parcel': True,
                     'metadata.collection': collection, 'metadata.ortho-date-estimate': date}}
                    for collection, date in [('old', '2025-01-01'), ('new', '2026-07-03'), ('tie', '2026-07-03')]]
        result = recent_parcel_collections({'features': features})
        self.assertEqual([f['properties']['metadata.collection'] for f in result['features']], ['new', 'tie'])
        self.assertIn('older versions', result['collectionSelection'])

    def test_point_miss_uses_one_bounded_neighborhood_query_and_metadata(self):
        from json import dumps
        calls = []
        geometry = {'type':'Polygon','coordinates':[[[-118.25,34.05],[-118.2499,34.05],[-118.2499,34.0501],[-118.25,34.05]]]}
        def request(path, params, *args, **kwargs):
            calls.append(params)
            return dumps({'features':[] if len(calls) == 1 else [{'geometry':geometry,'properties':{
                'structures':None,'metadata.ortho-date-estimate':'2026-07-03T18:50:14','metadata.collection':'source','metadata.gsd':.063}}]})
        result = imagery_evidence(request, 'urban', -118.25, 34.05, 'water', 'outlines')
        self.assertEqual([p['buffer-meter'] for p in calls], [0, 75])
        self.assertTrue(all(p['page-size'] == 250 for p in calls))
        self.assertIn('capture-date', calls[0]['include'])
        self.assertEqual(result[0]['properties']['date'], '2026-07-03')
        self.assertFalse(result[0]['properties']['buildingCoverage'])

    def test_provider_failure_is_not_retried_as_an_empty_point(self):
        from unittest.mock import Mock
        request = Mock(side_effect=ValueError('Vexcel rejected the key or imagery access.'))
        with self.assertRaises(ValueError):
            imagery_evidence(request, 'urban', -118.25, 34.05, 'water', 'outlines')
        self.assertEqual(request.call_count, 1)

    def test_capped_parcel_response_cannot_claim_complete_coverage(self):
        from json import dumps
        def request(*args, **kwargs):
            return dumps({'features':[{'properties':{'request-information.inside-parcel':True}}] * 250})
        with self.assertRaisesRegex(ValueError, 'incomplete'):
            imagery_evidence(request, 'urban', -118.25, 34.05, 'water', 'outlines')

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
