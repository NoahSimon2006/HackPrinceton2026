import unittest
from unittest.mock import patch

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
    return AIMessage(content="", tool_calls=[{"name": name, "args": {}, "id": name} for name in names])


def complete():
    return AIMessage(content="", tool_calls=[{"name": "SiteReview", "id": "review", "args": {
        "findings": [{"text": "The source parcel area is 10,000.00 m².", "fact_ids": ["parcel-area"]}],
        "recommendations": [{"text": "Check the parcel's available surfaces before locating a treatment area.", "fact_ids": ["parcel-area"]}],
        "questions": ["Which paved surface drains toward the proposed treatment location?"]}}])


class AgentTest(unittest.TestCase):
    def test_real_agent_graph_collects_facts_validates_references_and_redacts_geometry(self):
        model = ScriptedModel(responses=[
            complete(),  # Must be rejected until required evidence tools are attempted.
            calls("find_parcel_and_buildings", "detect_site_features", "read_costar_property", "read_rainfall_and_watershed"),
            complete(),
        ])
        outlines = [feature(polygon(-10, -10, 100, 100), "Parcel boundary")]
        details = {"propertyType": "Multifamily", "units": 194, "reportedParkingSpaces": 25,
                   "name": "PRIVATE PROPERTY", "address": "PRIVATE ADDRESS", "lat": LAT, "lon": LON}
        with patch("site_agent.ChatXAI", return_value=model):
            result = analyze_site("unused", "fake", "Review this site", "water", [],
                lambda group: outlines if group == "outlines" else [], lambda: (details, []),
                lambda: {"estimate": {"inches": 1.01, "depth_range": [1, 1.1], "method": "interpolated"}}, lon=LON, lat=LAT)
        self.assertIsNone(result["analysisError"])
        self.assertIsNotNone(result["report"])
        self.assertEqual(next(f["value"] for f in result["facts"] if f["id"] == "parcel-area"), 10000)
        self.assertTrue(result["evidence"]["outlines"][0]["geometry"])
        sent = " ".join(str(message.content) for group in model.seen for message in group)
        for forbidden in ["PRIVATE PROPERTY", "PRIVATE ADDRESS", '"coordinates"', str(LON), str(LAT)]:
            self.assertNotIn(forbidden, sent)
        self.assertIn('"value": 194', sent)
        self.assertIn('"value": 1.01', sent)
        self.assertIn("Read the required source tools first", sent)
        self.assertNotIn("execute", model.tool_names)
        self.assertNotIn("task", model.tool_names)
        self.assertIn("SiteReview", model.tool_names)

    def test_model_failure_preserves_measurements_and_source_failure_is_not_zero(self):
        model = ScriptedModel(responses=[calls("find_parcel_and_buildings", "read_costar_property"), RuntimeError("provider failed")])
        with patch("site_agent.ChatXAI", return_value=model):
            result = analyze_site("unused", "fake", "Review", "street", [],
                lambda group: [feature(polygon(-10, -10, 100, 100), "Parcel boundary")],
                lambda: (_ for _ in ()).throw(ValueError("private upstream error")), lambda: {}, lon=LON, lat=LAT)
        self.assertIsNone(result["report"])
        self.assertTrue(result["analysisError"])
        self.assertEqual(result["facts"][0]["value"], 10000)
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
