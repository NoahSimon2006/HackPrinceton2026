"""Real native graph orchestration with deterministic models and local-only sources."""
import json
from threading import Barrier
import unittest
from unittest.mock import Mock, patch
from pydantic import Field
from agent_activity import Activity, RunCancelled
from scout_agent import review_scout
from test_site_agent import ScriptedModel, message, call, read


FACT = {"id":"terrain-signal","label":"Terrain accumulation screen","value":901.0,"display":"901.00 m²",
        "unit":"m²","method":"Bare-earth local window","note":"Not a drainage area or measured capture.",
        "source":{"provider":"USGS","url":"https://www.usgs.gov/3d-elevation-program"}}


def bundle():
    return {"coverage":"inside_pilot","methodology":"Environmental screen first; readiness separate.","exhausted":False,"warnings":[],
        "candidates":[{"id":"candidate-a","label":"PRIVATE STREET ADDRESS","center":[-118.25,34.05],
            "geometry":{"type":"Point","coordinates":[-118.25,34.05]},"propertyId":"PRIVATE_PROPERTY",
            "environmental":{"summary":"Terrain screening signal"},"feasibility":"Check access.",
            "disruption":"Unknown driveway connection.","readiness":{"summary":"Needs verification","missing":["drainage"]},
            "direction":"Investigate interception","reason":"Source-supported screen","evidence":[FACT],"provenance":{},
            "modelContext":{"environmental":"A terrain screening signal; capture unassessed.","evidence":[FACT]}}]}


def review(text="The terrain signal is 901.00 m²; investigate drainage connectivity.", ids=None):
    return message(call("ScoutReview",{"findings":[{"candidate_id":"candidate-a","text":text,"fact_ids":ids or ["terrain-signal"]}]}))


class ParallelModel(ScriptedModel):
    rendezvous: object = Field(exclude=True)
    def _generate(self, messages, **kwargs):
        if not self.seen:
            self.rendezvous.wait(timeout=10)
        return super()._generate(messages,**kwargs)


def specialist(responses=None, rendezvous=None):
    responses = [message(read("/skills/opportunity-scouting/SKILL.md"),read("/project/brief.json")),
                 message(call("read_candidate_evidence")),*(responses if responses is not None else [review()])]
    return ParallelModel(responses=responses,rendezvous=rendezvous) if rendezvous else ScriptedModel(responses=responses)


def lead(extra=(), final=None):
    return ScriptedModel(responses=[
        message(read("/skills/opportunity-scouting/SKILL.md"),read("/project/brief.json"),
                call("write_file",{"file_path":"/project/plan.md","content":"Research the area, assess environment and feasibility in parallel, then wait for selection."}),
                call("query_area_opportunities")),
        *extra,
        message(call("task",{"subagent_type":"site-evidence","description":"Assess feasibility and readiness; save your report."},"site"),
                call("task",{"subagent_type":"domain-analysis","description":"Assess environmental screening; save your report."},"domain")),
        message(read("/project/reports/site-evidence.json"),read("/project/reports/domain-analysis.json")),
        *(final or [review()])])


class ScoutAgentTest(unittest.TestCase):
    def run_graph(self, models=None, research=None, activity=None):
        research = research or Mock(side_effect=bundle)
        models = models or [specialist(),specialist(),lead()]
        saved, events = {}, []
        with patch("scout_agent.ChatXAI",side_effect=models):
            result = review_scout("unused","fake","Find runoff interception opportunities","water",research,
                activity=activity or Activity(events.append),persist_artifact=lambda path,content:saved.__setitem__(path,content))
        return result,models,research,saved,events

    def test_native_parallel_delegation_reads_skills_and_saved_reports_without_raw_geometry(self):
        rendezvous = Barrier(2)
        result,models,research,saved,events = self.run_graph([specialist(rendezvous=rendezvous),specialist(rendezvous=rendezvous),lead()])
        self.assertEqual(result["agentStatus"],"complete")
        research.assert_called_once()
        self.assertEqual(result["candidates"][0]["center"],[-118.25,34.05])
        self.assertEqual(result["specialists"],{"site-evidence":"complete","domain-analysis":"complete"})
        for name in ("lead","site-evidence","domain-analysis"):
            self.assertIn("/skills/opportunity-scouting/SKILL.md",result["skillsUsed"][name])
        for name in ("site-evidence","domain-analysis"):
            self.assertIn(f"/project/reports/{name}.json",result["artifactsRead"]["lead"])
            self.assertEqual(json.loads(saved[f"/project/reports/{name}.json"])["status"],"complete")
        sent = str([model.seen for model in models])+str(saved)+str(events)
        for restricted in ("PRIVATE STREET ADDRESS","PRIVATE_PROPERTY","coordinates","-118.25","34.05"):
            self.assertNotIn(restricted,sent)
        self.assertIn("901.00",sent)
        for forbidden in ("draft_rain_garden","evaluate_designs","execute"):
            self.assertNotIn(forbidden,[name for model in models for name in model.tool_names])

    def test_citation_and_numeric_validation_retry_without_adding_invented_benefit(self):
        models=[specialist(),specialist(),lead(final=[review("Capture 9999 m².",["invented"]),review("Capture 9999 m²."),review()])]
        result,models,_,_,_=self.run_graph(models)
        self.assertEqual(result["agentStatus"],"complete")
        sent=str(models[-1].seen)
        self.assertIn("Cite only returned fact IDs",sent)
        self.assertIn("Use only exact numbers",sent)
        self.assertNotIn("9999",str(result["review"]))

    def test_model_failure_preserves_real_candidates_and_sanitizes_failure(self):
        models=[specialist(),specialist(),ScriptedModel(responses=[RuntimeError("PRIVATE TOKEN ERROR")])]
        result,_,research,_,_=self.run_graph(models)
        research.assert_called_once()
        self.assertEqual(result["agentStatus"],"partial")
        self.assertEqual(result["candidates"],bundle()["candidates"])
        self.assertIsNone(result["review"])
        self.assertNotIn("PRIVATE TOKEN ERROR",str(result))

    def test_plain_text_specialist_saves_partial_and_lead_can_still_cite_facts(self):
        from langchain_core.messages import AIMessage
        result,_,_,saved,_=self.run_graph([specialist([AIMessage(content="I cannot finish the schema.")]),specialist(),lead()])
        self.assertEqual(result["agentStatus"],"partial")
        self.assertIsNotNone(result["review"])
        self.assertEqual(json.loads(saved["/project/reports/site-evidence.json"])["status"],"partial")

    def test_cancellation_never_returns_fallback_candidates(self):
        activity=Activity()
        def cancel():
            activity.cancelled.set()
            return bundle()
        with self.assertRaises(RunCancelled):
            self.run_graph(research=Mock(side_effect=cancel),activity=activity)

    def test_readiness_never_reorders_candidates_and_no_design_is_created(self):
        value=bundle(); second=json.loads(json.dumps(value["candidates"][0])); second["id"]="candidate-b"
        second["readiness"]={"summary":"Ready to draft","missing":[]}; value["candidates"].append(second)
        result,_,_,_,_=self.run_graph(research=Mock(return_value=value))
        self.assertEqual([c["id"] for c in result["candidates"]],["candidate-a","candidate-b"])
        self.assertNotIn("proposal",result)
        self.assertNotIn("selectedCandidate",result)

    def test_canonical_files_and_host_paths_remain_read_only_to_model(self):
        attempts=message(*(call("write_file",{"file_path":path,"content":"FORGED"},path) for path in
            ("/project/brief.json","/skills/opportunity-scouting/SKILL.md","/Users/Derek/.env")))
        result,_,_,saved,_=self.run_graph([specialist(),specialist(),lead(extra=[attempts])])
        self.assertEqual(result["agentStatus"],"complete")
        self.assertNotIn("FORGED",str(saved))

    def test_source_absence_can_return_no_candidates_without_fabrication(self):
        value=bundle(); value["candidates"]=[]; value["coverage"]="outside_pilot"
        result,_,_,_,_=self.run_graph([specialist(),specialist(),ScriptedModel(responses=[RuntimeError("model unavailable")])],
                                    research=Mock(return_value=value))
        self.assertEqual(result["candidates"],[])
        self.assertIn("No supported locations",result["summary"])


if __name__=="__main__": unittest.main()
