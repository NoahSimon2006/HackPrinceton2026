import io
import json
import unittest
from email.message import Message
from unittest.mock import Mock, patch

from server import Handler
from test_site_measurements import LAT, LON, polygon


def request(payload):
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
    def test_geometry_and_scenario_reach_local_measurement_call(self):
        markings = [{"kind": "drainage", "geometry": polygon()}]
        scenario = {"inches": 1.5, "source": "Sensitivity test"}
        with patch.dict("os.environ", {"GROK_API_KEY": "test-only"}), patch("site_agent.analyze_site", return_value={"report": None}) as analyze:
            status, _ = request({"lat": LAT, "lon": LON, "workflow": "water", "question": "Review", "markings": markings, "rainfallScenario": scenario})
        self.assertEqual(status, 200)
        self.assertEqual(analyze.call_args.args[4], markings)
        self.assertEqual(analyze.call_args.kwargs["scenario"], scenario)
        self.assertEqual(analyze.call_args.kwargs["lon"], LON)

    def test_invalid_inputs_do_not_reach_model(self):
        with patch("site_agent.analyze_site") as analyze:
            status, _ = request({"lat": LAT, "lon": LON, "workflow": "water", "question": "Review", "markings": ["drainage"]})
            self.assertEqual(status, 400)
            status, _ = request({"lat": LAT, "lon": LON, "workflow": "street", "question": "Review", "rainfallScenario": {"inches": 1, "source": "Test"}})
            self.assertEqual(status, 400)
            analyze.assert_not_called()


if __name__ == "__main__":
    unittest.main()
