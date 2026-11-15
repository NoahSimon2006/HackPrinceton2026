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
from test_traffic_analysis import context as traffic_context, study as traffic_study, comparison as traffic_comparison, LAYOUTS, IDENTITY


class ScriptedModel(BaseChatModel):
    responses: list = Field(default_factory=list)
    seen: list = Field(default_factory=list)
    tool_names: list = Field(default_factory=list)
    tool_sets: list = Field(default_factory=list)

    @property
    def _llm_type(self):
        return "site-agent-test"

    def bind_tools(self, tools, **kwargs):
        names = [tool.name if hasattr(tool, "name") else tool.get("function", {}).get("name") for tool in tools]
        self.tool_names.extend(names)
        self.tool_sets.append(set(names))
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
    def test_failed_or_invalid_candidate_source_is_distinct_from_successful_empty(self):
        for state in ("failed", "invalid", "empty"):
            with self.subTest(state=state):
                review = AIMessage(content="", tool_calls=[{"name": "SiteReview", "id": "summary", "args": {
                    "findings": [], "recommendations": [], "questions": ["Verify site evidence?"]}}])
                evaluation = AIMessage(content="", tool_calls=[{"name": "evaluate_designs", "id": "evaluate", "args": {"layouts": LAYOUTS}}])
                lead = ScriptedModel(responses=[calls("investigate_site"), evaluation, review])
                def imagery(group):
                    if group != "detections" or state == "empty":
                        return []
                    if state == "failed":
                        raise ValueError("private source failure")
                    return [{"geometry": {"type": "Polygon", "coordinates": []}, "properties": {"label": "Crosswalk"}}]
                with patch("site_agent.ChatXAI", side_effect=[lead, ScriptedModel(responses=[review]), ScriptedModel(responses=[review])]), \
                     patch("traffic_analysis.Study", return_value=traffic_study()), \
                     patch("traffic_analysis.evaluate", return_value=traffic_comparison(None)) as evaluate:
                    result = analyze_site("unused", "fake", "Compare layouts", "street", [], imagery, lambda: ({}, []), lambda: {},
                        lon=LON, lat=LAT, traffic_context=traffic_context(), analysis_identity=IDENTITY, allow_generated_timing=True)
                self.assertIsNone(result["analysisError"])
                checks = evaluate.call_args.kwargs["extra_checks"]
                from shapely.geometry import box
                outcome = checks(box(385000, 3768000, 385010, 3768010))
                self.assertEqual(result["sourceStatus"]["detections"], "empty" if state == "empty" else "unavailable")
                self.assertEqual(outcome["detection_status"], "empty" if state == "empty" else "unavailable")
                self.assertNotIn("private source failure", str(result))

    def test_invalid_design_arguments_emit_sanitized_activity_before_one_comparison(self):
        review = AIMessage(content="", tool_calls=[{"name": "SiteReview", "id": "review", "args": {
            "findings": [], "recommendations": [], "questions": ["Verify missing source coverage?"]}}])
        def evaluation(identifier, layouts):
            return AIMessage(content="", tool_calls=[{"name": "evaluate_designs", "id": identifier, "args": {"layouts": layouts}}])
        bad_schema = [{**LAYOUTS[0], "name": "private-argument", "length_m": 999}, LAYOUTS[1]]
        duplicates = [LAYOUTS[0], {**LAYOUTS[0], "name": "duplicate"}]
        lead = ScriptedModel(responses=[calls("investigate_site"), evaluation("schema-error", bad_schema),
                                       evaluation("duplicate-error", duplicates), evaluation("valid", LAYOUTS), review])
        events = []
        with patch("site_agent.ChatXAI", side_effect=[lead, ScriptedModel(responses=[review]), ScriptedModel(responses=[review])]), \
             patch("traffic_analysis.Study", return_value=traffic_study()), \
             patch("traffic_analysis.evaluate", return_value=traffic_comparison(None)) as evaluate:
            result = analyze_site("unused", "fake", "Compare layouts", "street", [], lambda _: [], lambda: ({}, []), lambda: {},
                lon=LON, lat=LAT, traffic_context=traffic_context(), analysis_identity=IDENTITY,
                allow_generated_timing=True, activity=Activity(events.append))
        self.assertIsNone(result["analysisError"])
        evaluate.assert_called_once()
        retries = [e["summary"] for e in events if e["stage"] == "validation"]
        self.assertIn("Correcting bounded design parameters before simulation.", retries)
        self.assertIn("Choosing distinct valid alternatives before simulation.", retries)
        public_content = str([{key: event[key] for key in ("summary", "facts") if key in event} for event in events])
        self.assertNotIn("private-argument", public_content)
        self.assertNotIn("999", public_content)
        self.assertEqual(lead.tool_sets[-1], {"SiteReview"})

    def test_traffic_lead_must_evaluate_then_cites_local_metrics_without_sending_geometry(self):
        def review():
            return AIMessage(content="", tool_calls=[{"name": "SiteReview", "id": "review", "args": {
                "findings": [{"text": "Historical counted movements anchor this comparison.", "fact_ids": ["traffic-count-total"]}],
                "recommendations": [{"text": "Evaluate the selected north-curb layout with the field team.", "fact_ids": ["traffic-north-curb-verdict"]}],
                "questions": ["Can the field team verify access and the generated signal timing?"]}}])
        empty_review = AIMessage(content="", tool_calls=[{"name": "SiteReview", "id": "summary", "args": {
            "findings": [], "recommendations": [], "questions": ["Verify the source evidence on site?"]}}])
        evaluation = AIMessage(content="", tool_calls=[{"name": "evaluate_designs", "id": "evaluate", "args": {"layouts": LAYOUTS}}])
        lead = ScriptedModel(responses=[calls("investigate_site"), review(), evaluation, review()])
        site = ScriptedModel(responses=[empty_review])
        domain = ScriptedModel(responses=[empty_review])
        events = []
        with patch("site_agent.ChatXAI", side_effect=[lead, site, domain]), \
             patch("traffic_analysis.Study", return_value=traffic_study()), \
             patch("traffic_analysis.evaluate", return_value=traffic_comparison()) as evaluate:
            result = analyze_site("unused", "fake", "Compare lower-emission layouts", "street", [],
                lambda _: [], lambda: ({"propertyType": "Office"}, []), lambda: {},
                lon=LON, lat=LAT, traffic_context=traffic_context(), analysis_identity=IDENTITY,
                allow_generated_timing=True, ranking_policy="strict-v1", activity=Activity(events.append))
        self.assertIsNone(result["analysisError"])
        self.assertTrue(result["report"])
        self.assertTrue(result["proposal"])
        self.assertEqual(result["comparison"]["input_hash"], result["proposal"]["input_hash"])
        evaluate.assert_called_once()
        sent = " ".join(str(message.content) for model in (lead, site, domain) for group in model.seen for message in group) + str(events)
        for forbidden in ["PRIVATE", "coordinates", "node_id", str(LON), str(LAT), str(traffic_context()["lon"]), str(traffic_context()["lat"])]:
            self.assertNotIn(forbidden, sent)
        self.assertIn("Read the required source tools first: comparison", sent)
        self.assertIn("evaluate_designs", lead.tool_names)
        self.assertNotIn("evaluate_designs", site.tool_names + domain.tool_names)
        self.assertIn("/project/comparison.json", result["virtualFiles"])
        self.assertEqual(lead.tool_sets, [{"investigate_site", "SiteReview"}, {"evaluate_designs", "SiteReview"},
                                          {"evaluate_designs", "SiteReview"}, {"SiteReview"}])
        self.assertIn("search_aerial_imagery", site.tool_names)
        self.assertEqual(len([e for e in events if e["stage"] == "model-request" and e["status"] == "started"]), 6)
        self.assertEqual(len([e for e in events if e["stage"] == "model-request" and e["status"] == "completed"]), 6)

    def test_real_agent_graph_collects_facts_validates_references_and_redacts_geometry(self):
        model = ScriptedModel(responses=[complete(), calls("investigate_site"), calls("draft_rain_garden"), complete()])
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
        outlines = [feature(polygon(-10, -10, 100, 100), "Parcel boundary"),
                    feature(polygon(0, 0, 20, 20), "Building footprint")]
        details = {"propertyType": "Multifamily", "units": 194, "reportedParkingSpaces": 25,
                   "vacancyPercent":43, "privateKey":"PRIVATE KEY", "name": "PRIVATE PROPERTY", "address": "PRIVATE ADDRESS", "lat": LAT, "lon": LON}
        selected = {"value":2040,"unit":"m² of raster area","classification":"derived",
                    "source":{"label":"USGS","url":"https://www.usgs.gov/3d-elevation-program","retrieved_at":"2026-11-14"},
                    "method":"D8 unfilled terrain routing","period":"Publication 2025-08-11",
                    "limitations":"Window-limited raster area; not a verified catchment or flood depth."}
        with patch("site_agent.ChatXAI", side_effect=[model,site_model,domain_model]):
            result = analyze_site("unused", "fake", "Review this site", "water", [],
                imagery, lambda: (details, []), hydrology, lon=LON, lat=LAT, activity=Activity(events.append), discovery=selected,
                analysis_identity=IDENTITY)
        self.assertIsNone(result["analysisError"])
        self.assertIsNotNone(result["report"])
        self.assertEqual(result["proposal"]["status"], "draft")
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
        self.assertIn("water-storage_volume", sent)
        self.assertIn("Read the required source tools first", sent)
        self.assertNotIn("execute", model.tool_names)
        self.assertNotIn("task", model.tool_names)
        self.assertIn("SiteReview", model.tool_names)
        self.assertEqual(model.tool_sets[-1], {"SiteReview"})

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
        with self.assertRaises(ValidationError) as rejection:
            schema.model_validate(report("The crossing is 99 m.", ["crossing"]))
        self.assertIn("numbers not present in its cited facts: 99", str(rejection.exception))
        self.assertIn("crossing: 25.00 m / 82.0 ft", str(rejection.exception))
        with self.assertRaises(ValidationError):
            schema.model_validate(report("The crossing is 25 m.", ["invented-source"]))


if __name__ == "__main__":
    unittest.main()
