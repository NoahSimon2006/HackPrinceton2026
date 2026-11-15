import io
import json
import unittest
from email.message import Message
from unittest.mock import Mock, patch

from server import Handler
from test_site_measurements import LAT, LON, polygon


def request(payload):
    payload = {"siteId":"api-test-site","inputRevision":0,"proposalRevision":1,**payload}
    body = json.dumps(payload).encode()
    handler = Handler.__new__(Handler)
    handler.path = "/api/site-analysis"
    handler.headers = Message()
    handler.headers["Content-Type"] = "application/json"
    handler.headers["Content-Length"] = str(len(body))
    handler.rfile = io.BytesIO(body)
    handler.send_json = Mock()
    handler.log_error = Mock()
    handler.do_POST()
    return handler.send_json.call_args.args


class SiteApiTest(unittest.TestCase):
    def test_retired_comparison_payload_is_rejected_before_model(self):
        for workflow in ("water", "street"):
            with patch("site_agent.analyze_site") as analyze:
                status, result = request({"lat": LAT, "lon": LON, "workflow": workflow,
                                          "question": "Review", "waterDesign": {"storage_depth_m": .15}})
                self.assertEqual(status, 400)
                self.assertIn("retired", result["error"])
                analyze.assert_not_called()
        with patch.dict("os.environ", {"GROK_API_KEY": "test-only"}), patch("site_agent.analyze_site", return_value={}) as analyze:
            self.assertEqual(request({"lat": LAT, "lon": LON, "workflow": "water", "question": "Draft a garden"})[0], 200)
            self.assertNotIn("water_design", analyze.call_args.kwargs)

    def test_discovery_reference_is_validated_before_model_call(self):
        reference={"version":"source-version","layer":"counts","feature":"count-one"}
        selected={"value":18102,"unit":"vehicles reported"}
        with patch.dict("os.environ", {"GROK_API_KEY":"test-only"}), \
             patch("server.discovery_context",return_value=selected) as resolve, \
             patch("server.traffic_context",return_value=None), \
             patch("site_agent.analyze_site",return_value={"report":None}) as analyze:
            status,_=request({"lat":LAT,"lon":LON,"workflow":"street","question":"Review","discoveryReference":reference})
            self.assertEqual(status,200)
            resolve.assert_called_once_with("street",reference,LON,LAT)
            self.assertEqual(analyze.call_args.kwargs["discovery"],selected)
        with patch("server.discovery_context",side_effect=ValueError("Stale source")), patch("site_agent.analyze_site") as analyze:
            status,_=request({"lat":LAT,"lon":LON,"workflow":"street","question":"Review","discoveryReference":reference})
            self.assertEqual(status,400)
            analyze.assert_not_called()

    def test_geometry_and_scenario_reach_local_measurement_call(self):
        markings = [{"kind": "drainage", "geometry": polygon()}]
        scenario = {"inches": 1.5, "source": "Sensitivity test"}
        with patch.dict("os.environ", {"GROK_API_KEY": "test-only"}), patch("site_agent.analyze_site", return_value={"report": None}) as analyze:
            status, _ = request({"lat": LAT, "lon": LON, "workflow": "water", "question": "Review", "markings": markings, "rainfallScenario": scenario})
        self.assertEqual(status, 200)
        self.assertEqual(analyze.call_args.args[4], markings)
        self.assertEqual(analyze.call_args.kwargs["scenario"], scenario)
        self.assertEqual(analyze.call_args.kwargs["lon"], LON)
        self.assertEqual(analyze.call_args.kwargs["analysis_identity"],{"site_id":"api-test-site","revision":1,"input_revision":0})
        self.assertEqual(analyze.call_args.kwargs["ranking_policy"],"strict-v1")

    def test_invalid_inputs_do_not_reach_model(self):
        with patch("site_agent.analyze_site") as analyze:
            status, _ = request({"lat": LAT, "lon": LON, "workflow": "water", "question": "Review", "markings": ["drainage"]})
            self.assertEqual(status, 400)
            status, _ = request({"lat": LAT, "lon": LON, "workflow": "street", "question": "Review", "rainfallScenario": {"inches": 1, "source": "Test"}})
            self.assertEqual(status, 400)
            analyze.assert_not_called()


if __name__ == "__main__":
    unittest.main()
