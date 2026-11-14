import unittest
from unittest.mock import patch
from threading import Barrier
from agent_activity import Activity

from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage
from langchain_core.outputs import ChatGeneration, ChatResult
from pydantic import Field, ValidationError

from site_agent import analyze_site, review_schema
from site_measurements import fact, source
from test_site_measurements import LON, LAT, feature, polygon


class ScriptedModel(BaseChatModel):
    responses: list = Field(default_factory=list)
    seen: list = Field(default_factory=list)
    tool_names: list = Field(default_factory=list)

    @property
    def _llm_type(self):
        return "site-agent-test"

    def bind_tools(self, tools, **kwargs):
        self.tool_names.extend(tool.name if hasattr(tool, "name") else tool.get("function", {}).get("name") for tool in tools)
        return self

    def _generate(self, messages, stop=None, run_manager=None, **kwargs):
        self.seen.append(messages)
        response = self.responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return ChatResult(generations=[ChatGeneration(message=response)])


def calls(*names):
    return AIMessage(content="", tool_calls=[{"name": name, "args": {"plan":["Read site evidence and domain sources concurrently.", "Check citations and report data gaps."]} if name == "investigate_site" else {}, "id": name} for name in names])


def complete():
    return AIMessage(content="", tool_calls=[{"name": "SiteReview", "id": "review", "args": {
        "findings": [{"text": "The source parcel area is 10,000.00 m².", "fact_ids": ["parcel-area"]}],
        "recommendations": [{"text": "Check the parcel's available surfaces before locating a treatment area.", "fact_ids": ["parcel-area"]}],
        "questions": ["Which paved surface drains toward the proposed treatment location?"]}}])


class AgentTest(unittest.TestCase):
    def test_real_agent_graph_collects_facts_validates_references_and_redacts_geometry(self):
        model = ScriptedModel(responses=[complete(), calls("investigate_site"), complete()])
        site_model = ScriptedModel(responses=[complete()])
        domain_model = ScriptedModel(responses=[AIMessage(content="", tool_calls=[{"name":"SiteReview","id":"domain","args":{"findings":[],"recommendations":[],"questions":["Verify drainage connections?"]}}])])
        barrier = Barrier(2)
        events = []
        def imagery(group):
            if group == "outlines": barrier.wait(timeout=3)
            return outlines if group == "outlines" else []
        def hydrology():
            barrier.wait(timeout=3)
            return {"estimate":{"inches":1.01,"depth_range":[1,1.1],"method":"interpolated"}}
        outlines = [feature(polygon(-10, -10, 100, 100), "Parcel boundary")]
        details = {"propertyType": "Multifamily", "units": 194, "reportedParkingSpaces": 25,
                   "vacancyPercent":43, "privateKey":"PRIVATE KEY", "name": "PRIVATE PROPERTY", "address": "PRIVATE ADDRESS", "lat": LAT, "lon": LON}
        selected = {"value":2040,"unit":"m² of raster area","classification":"derived",
                    "source":{"label":"USGS","url":"https://www.usgs.gov/3d-elevation-program","retrieved_at":"2026-11-14"},
                    "method":"D8 unfilled terrain routing","period":"Publication 2025-08-11",
                    "limitations":"Window-limited raster area; not a verified catchment or flood depth."}
        with patch("site_agent.ChatXAI", side_effect=[model,site_model,domain_model]):
            result = analyze_site("unused", "fake", "Review this site", "water", [],
                imagery, lambda: (details, []), hydrology, lon=LON, lat=LAT, activity=Activity(events.append), discovery=selected)
        self.assertIsNone(result["analysisError"])
        self.assertIsNotNone(result["report"])
        self.assertEqual(next(f["value"] for f in result["facts"] if f["id"] == "parcel-area"), 10000)
        self.assertTrue(result["evidence"]["outlines"][0]["geometry"])
        starts = [i for i,e in enumerate(events) if e["stage"] == "investigation" and e["status"] == "started"]
        finishes = [i for i,e in enumerate(events) if e["stage"] == "investigation" and e["status"] == "completed"]
        self.assertEqual(len(starts),2)
        self.assertLess(max(starts),min(finishes))
        self.assertIn("/project/specialists.json", result["virtualFiles"])
        sent = " ".join(str(message.content) for m in (model,site_model,domain_model) for group in m.seen for message in group) + str(events)
        for forbidden in ["PRIVATE PROPERTY", "PRIVATE ADDRESS", "PRIVATE KEY", "vacancyPercent", '"coordinates"', str(LON), str(LAT)]:
            self.assertNotIn(forbidden, sent)
        self.assertIn('"value": 194', sent)
        self.assertIn('"value": 1.01', sent)
        self.assertIn('"value": 2040', sent)
        self.assertIn('D8 unfilled terrain routing', sent)
        self.assertIn("Read the required source tools first", sent)
        self.assertNotIn("execute", model.tool_names)
        self.assertNotIn("task", model.tool_names)
        self.assertIn("SiteReview", model.tool_names)

    def test_model_failure_preserves_measurements_and_source_failure_is_not_zero(self):
        model = ScriptedModel(responses=[calls("investigate_site"), RuntimeError("provider failed")])
        with patch("site_agent.ChatXAI", side_effect=[model,ScriptedModel(responses=[RuntimeError("failed")]),ScriptedModel(responses=[RuntimeError("failed")])]):
            result = analyze_site("unused", "fake", "Review", "street", [],
                lambda group: [feature(polygon(-10, -10, 100, 100), "Parcel boundary")],
                lambda: (_ for _ in ()).throw(ValueError("private upstream error")), lambda: {}, lon=LON, lat=LAT)
        self.assertIsNone(result["report"])
        self.assertTrue(result["analysisError"])
        self.assertEqual(next(f["value"] for f in result["facts"] if f["id"] == "parcel-area"), 10000)
        self.assertEqual(result["sourceStatus"]["property"], "unavailable")
        self.assertNotIn("private upstream error", str(result))

    def test_unknown_citations_and_unsupported_measurements_are_rejected(self):
        item = fact("crossing", "Marked crossing", 25, "m", source("Planner"))
        schema = review_schema({"crossing": item}, set(), set())
        def report(text, refs):
            return {"findings": [{"text": text, "fact_ids": refs}], "recommendations": [], "questions": ["Verify endpoints?"]}
        schema.model_validate(report("The marked crossing is 25.00 m / 82.0 ft.", ["crossing"]))
        with self.assertRaises(ValidationError):
            schema.model_validate(report("The crossing is 99 m.", ["crossing"]))
        with self.assertRaises(ValidationError):
            schema.model_validate(report("The crossing is 25 m.", ["invented-source"]))


if __name__ == "__main__":
    unittest.main()
