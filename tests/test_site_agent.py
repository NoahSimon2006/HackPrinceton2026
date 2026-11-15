import re
import unittest
from unittest.mock import Mock, patch
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


def call(name, args=None, identifier=None):
    return {"name":name, "args":args or {}, "id":identifier or name}


def message(*tools):
    return AIMessage(content="", tool_calls=list(tools))


def read(path):
    return call("read_file", {"file_path":path, "limit":1000}, path)


def calls(*names):
    if names == ("delegate",):
        return message(call("task", {"subagent_type":"site-evidence", "description":"Read /project/brief.json, use sponsor source tools and property skill, save /project/reports/site-evidence.json."}, "site-task"),
                       call("task", {"subagent_type":"domain-analysis", "description":"Read /project/brief.json, inspect domain inputs with the domain skill, save /project/reports/domain-analysis.json."}, "domain-task"))
    return message(*(call(name) for name in names))


def lead_model(responses):
    program = [message(read("/skills/proposal-publication/SKILL.md"), read("/project/brief.json"),
                       call("write_file", {"file_path":"/project/plan.md", "content":"Inspect sponsor and domain evidence concurrently, then evaluate a supported design."}))]
    for response in responses:
        program.append(response)
        if isinstance(response, AIMessage) and any(c["name"] == "task" for c in response.tool_calls):
            program.append(message(read("/project/reports/site-evidence.json"), read("/project/reports/domain-analysis.json")))
    return ScriptedModel(responses=program)


def specialist_model(name, workflow, responses, discovery=False):
    skill = "property-association" if name == "site" else "stormwater-concept" if workflow == "water" else "traffic-evaluation"
    tools = ["find_parcel_and_buildings", "detect_site_features", "read_costar_property"] if name == "site" else ["read_rainfall_and_watershed" if workflow == "water" else "read_traffic_inputs"]
    if discovery and name != "site":
        tools.append("query_neighborhood_discovery")
    return ScriptedModel(responses=[message(read(f"/skills/{skill}/SKILL.md"),read("/project/brief.json")), calls(*tools), *responses])


def complete():
    return AIMessage(content="", tool_calls=[{"name": "SiteReview", "id": "review", "args": {
        "findings": [{"text": "The source parcel area is 10,000.00 m².", "fact_ids": ["parcel-area"]}],
        "recommendations": [{"text": "Check the parcel's available surfaces before locating a treatment area.", "fact_ids": ["parcel-area"]}],
        "questions": ["Which paved surface drains toward the proposed treatment location?"]}}])


class AgentTest(unittest.TestCase):
    def setUp(self):
        # Scripted models use no provider capacity; pacing has dedicated fake-clock tests.
        from unittest.mock import patch
        pacing = patch('xai_runtime.MIN_INTERVAL_SECONDS', 0)
        pacing.start()
        self.addCleanup(pacing.stop)

    def test_numeric_validation_suggests_available_facts_without_accepting_missing_citations(self):
        facts = {'water-footprint_area': fact('water-footprint_area', 'Footprint area', 20, 'm²', source('Local geometry')),
                 'water-captured_volume': fact('water-captured_volume', 'Temporary runoff storage', 1.984, 'm³', source('Local geometry'), precision=3)}
        schema = review_schema(facts, set(), set())
        payload = {'findings': [{'text': 'The footprint is 20 m².', 'fact_ids': ['water-captured_volume']}],
                   'recommendations': [], 'questions': ['Verify access?']}
        with self.assertRaisesRegex(ValidationError, 'Available exact-value facts to check: water-footprint_area'):
            schema.model_validate(payload)
        payload['findings'][0]['fact_ids'] = ['water-footprint_area']
        self.assertEqual(schema.model_validate(payload).findings[0].fact_ids, ['water-footprint_area'])

    def test_failed_or_invalid_candidate_source_is_distinct_from_successful_empty(self):
        for state in ("failed", "invalid", "empty"):
            with self.subTest(state=state):
                review = AIMessage(content="", tool_calls=[{"name": "SiteReview", "id": "summary", "args": {
                    "findings": [], "recommendations": [], "questions": ["Verify site evidence?"]}}])
                evaluation = AIMessage(content="", tool_calls=[{"name": "evaluate_designs", "id": "evaluate", "args": {"layouts": LAYOUTS}}])
                lead = lead_model([calls("delegate"), evaluation, review])
                def imagery(group):
                    if group != "detections" or state == "empty":
                        return []
                    if state == "failed":
                        raise ValueError("private source failure")
                    return [{"geometry": {"type": "Polygon", "coordinates": []}, "properties": {"label": "Crosswalk"}}]
                with patch("site_agent.ChatXAI", side_effect=[lead, specialist_model("site", "street", [review]), specialist_model("domain", "street", [review])]), \
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
        lead = lead_model([calls("delegate"), evaluation("schema-error", bad_schema),
                                       evaluation("duplicate-error", duplicates), evaluation("valid", LAYOUTS), review])
        events = []
        with patch("site_agent.ChatXAI", side_effect=[lead, specialist_model("site", "street", [review]), specialist_model("domain", "street", [review])]), \
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
        self.assertIn("SiteReview", lead.tool_sets[-1])

    def test_traffic_lead_must_evaluate_then_cites_local_metrics_without_sending_geometry(self):
        def review():
            return AIMessage(content="", tool_calls=[{"name": "SiteReview", "id": "review", "args": {
                "findings": [{"text": "Historical counted movements anchor this comparison.", "fact_ids": ["traffic-count-total"]}],
                "recommendations": [{"text": "Evaluate the selected north-curb layout with the field team.", "fact_ids": ["traffic-north-curb-verdict"]}],
                "questions": ["Can the field team verify access and the generated signal timing?"]}}])
        empty_review = AIMessage(content="", tool_calls=[{"name": "SiteReview", "id": "summary", "args": {
            "findings": [], "recommendations": [], "questions": ["Verify the source evidence on site?"]}}])
        evaluation = AIMessage(content="", tool_calls=[{"name": "evaluate_designs", "id": "evaluate", "args": {"layouts": LAYOUTS}}])
        lead = lead_model([calls("delegate"), review(), evaluation, review()])
        site = specialist_model("site", "street", [empty_review])
        domain = specialist_model("domain", "street", [empty_review])
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
        self.assertIn("task", lead.tool_names)
        self.assertIn("read_file", lead.tool_names)
        self.assertNotIn("execute", lead.tool_names)
        self.assertIn("search_aerial_imagery", site.tool_names)
        self.assertLessEqual(len([e for e in events if e["stage"] == "model-request" and e["status"] == "started"]), 36)
        self.assertEqual(len([e for e in events if e["stage"] == "model-request" and e["status"] == "completed"]), len([e for e in events if e["stage"] == "model-request" and e["status"] == "started"]))

    def test_real_agent_graph_collects_facts_validates_references_and_redacts_geometry(self):
        model = lead_model([complete(), calls("delegate"), calls("draft_rain_garden"), complete()])
        site_model = specialist_model("site", "water", [complete()])
        domain_model = specialist_model("domain", "water", [AIMessage(content="", tool_calls=[{"name":"SiteReview","id":"domain","args":{"findings":[],"recommendations":[],"questions":["Verify drainage connections?"]}}])], discovery=True)
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
                analysis_identity=IDENTITY,
                fetch_discovery=lambda: ([fact("area-terrain-test", "Nearby terrain contribution", 900, "m²", source("USGS"), basis="estimated", note="Not verified drainage.")], []))
        self.assertIsNone(result["analysisError"])
        self.assertIn("query_neighborhood_discovery", domain_model.tool_names)
        self.assertTrue(any(f["id"] == "area-terrain-test" for f in result["facts"]))
        self.assertIsNotNone(result["report"])
        self.assertEqual(result["proposal"]["status"], "conditional")
        self.assertEqual(result["proposal"]["design"]["kind"], "bioretention")
        self.assertGreaterEqual(len(result["alternatives"]), 2)
        self.assertTrue(result["waterPlan"]["decisions"])
        self.assertEqual(next(f["value"] for f in result["facts"] if f["id"] == "parcel-area"), 10000)
        self.assertTrue(result["evidence"]["outlines"][0]["geometry"])
        starts = [i for i,e in enumerate(events) if e["stage"] == "investigation" and e["status"] == "started"]
        finishes = [i for i,e in enumerate(events) if e["stage"] == "investigation" and e["status"] == "completed"]
        self.assertEqual(len(starts),2)
        self.assertLess(max(starts),min(finishes))
        self.assertIn("/project/reports/site-evidence.json", result["virtualFiles"])
        self.assertIn("/project/reports/domain-analysis.json", result["artifactsRead"]["lead"])
        self.assertIn("/skills/property-association/SKILL.md", result["skillsUsed"]["site-evidence"])
        sent = " ".join(str(message.content) for m in (model,site_model,domain_model) for group in m.seen for message in group) + str(events)
        sent = re.sub(r"\d{4}-\d{2}-\d{2}T[0-9:.+Z-]+", "<timestamp>", sent)
        self.assertIsNone(result["comparison"])
        self.assertNotIn("compare_water", model.tool_names)
        for forbidden in ["PRIVATE PROPERTY", "PRIVATE ADDRESS", "PRIVATE KEY", "vacancyPercent", '"coordinates"', str(LON), str(LAT)]:
            self.assertNotIn(forbidden, sent)
        self.assertIn('"value": 194', sent)
        self.assertIn('"value": 1.01', sent)
        self.assertIn('"value": 2040', sent)
        self.assertIn('D8 unfilled terrain routing', sent)
        self.assertIn("water-storage_volume", sent)
        self.assertIn("Read the required source tools first", sent)
        self.assertNotIn("execute", model.tool_names)
        self.assertIn("task", model.tool_names)
        self.assertIn("SiteReview", model.tool_names)
        self.assertIn("SiteReview", model.tool_sets[-1])

    def test_model_failure_preserves_measurements_and_source_failure_is_not_zero(self):
        model = lead_model([calls("delegate"), RuntimeError("provider failed")])
        with patch("site_agent.ChatXAI", side_effect=[model,specialist_model("site", "street", [RuntimeError("failed")]),specialist_model("domain", "street", [RuntimeError("failed")])]):
            result = analyze_site("unused", "fake", "Review", "street", [],
                lambda group: [feature(polygon(-10, -10, 100, 100), "Parcel boundary")],
                lambda: (_ for _ in ()).throw(ValueError("private upstream error")), lambda: {}, lon=LON, lat=LAT)
        self.assertIsNone(result["report"])
        self.assertTrue(result["analysisError"])
        self.assertEqual(next(f["value"] for f in result["facts"] if f["id"] == "parcel-area"), 10000)
        self.assertEqual(result["sourceStatus"]["property"], "unavailable")
        self.assertNotIn("private upstream error", str(result))

    def test_unstructured_specialist_completion_saves_partial_report_and_unblocks_lead(self):
        final = message(call('SiteReview', {'findings':[], 'recommendations':[], 'questions':['Verify source coverage?']}))
        lead=lead_model([calls('delegate'), final])
        specialists=[specialist_model('site','street',[AIMessage(content='Inputs inspected.'), AIMessage(content='Still plain text.')]),
                     specialist_model('domain','street',[AIMessage(content='Inputs inspected.'), AIMessage(content='Still plain text.')])]
        with patch('site_agent.ChatXAI',side_effect=[lead,*specialists]):
            result=analyze_site('unused','fake','Review','street',[],lambda _:[],lambda:({},[]),lambda:{},lon=LON,lat=LAT)
        self.assertIsNone(result['analysisError'])
        self.assertEqual(result['specialists'],{'site-evidence':False,'domain-analysis':False})
        self.assertEqual(len([path for path in result['artifactsRead']['lead'] if '/reports/' in path]),2)

    def test_specialist_plain_completion_gets_one_cited_correction_without_source_replay(self):
        final = message(call('SiteReview', {'findings':[], 'recommendations':[], 'questions':['Verify source coverage?']}))
        corrected = message(call('SiteReview', {'findings':[{'text':'Traffic comparison inputs remain unavailable.',
            'fact_ids':['traffic-comparison-status']}], 'recommendations':[], 'questions':['Which supported counted site should be investigated?']}))
        lead = lead_model([calls('delegate'), final])
        site = specialist_model('site','street',[final])
        domain = specialist_model('domain','street',[AIMessage(content='Inputs inspected.'), corrected])
        imagery = Mock(return_value=[]); property_source = Mock(return_value=({},[])); events=[]
        with patch('site_agent.ChatXAI',side_effect=[lead,site,domain]):
            result=analyze_site('unused','fake','Review','street',[],imagery,property_source,lambda:{},lon=LON,lat=LAT,activity=Activity(events.append))
        self.assertIsNone(result['analysisError'])
        self.assertEqual(result['specialists'],{'site-evidence':True,'domain-analysis':True})
        self.assertEqual(domain.tool_sets[-1],{'SiteReview'})
        self.assertEqual(len(domain.seen),4)
        self.assertEqual(len([e for e in events if e['stage']=='structured-review']),1)
        self.assertEqual(imagery.call_count,2)
        property_source.assert_called_once()
        self.assertIn('/project/reports/domain-analysis.json',result['artifactsRead']['lead'])
        self.assertTrue(any(f['id']=='traffic-comparison-status' for f in result['facts']))

    def test_failed_specialist_correction_stays_bounded_and_preserves_validated_evidence(self):
        final = message(call('SiteReview', {'findings':[], 'recommendations':[], 'questions':['Verify source coverage?']}))
        bad_number = message(call('SiteReview', {'findings':[{'text':'Traffic comparison inputs show 999 vehicles.',
            'fact_ids':['traffic-comparison-status']}], 'recommendations':[], 'questions':['Verify demand?']}))
        for correction in (AIMessage(content='Still plain text.'), bad_number, calls('read_traffic_inputs')):
            with self.subTest(correction=correction):
                lead=lead_model([calls('delegate'),final]); site=specialist_model('site','street',[final])
                domain=specialist_model('domain','street',[AIMessage(content='Inputs inspected.'),correction,final])
                events=[]; imagery=Mock(return_value=[]); property_source=Mock(return_value=({},[]))
                with patch('site_agent.ChatXAI',side_effect=[lead,site,domain]):
                    result=analyze_site('unused','fake','Review','street',[],imagery,property_source,lambda:{},lon=LON,lat=LAT,activity=Activity(events.append))
                self.assertIsNone(result['analysisError'])
                self.assertEqual(result['specialists'],{'site-evidence':True,'domain-analysis':False})
                self.assertEqual(len(domain.seen),4)
                self.assertEqual(len(domain.responses),1,'no second corrective request may consume the remaining response')
                self.assertEqual(domain.tool_sets[-1],{'SiteReview'})
                self.assertEqual(len([e for e in events if e['stage']=='structured-review']),1)
                self.assertEqual(imagery.call_count,2); property_source.assert_called_once()
                self.assertIn('/project/reports/domain-analysis.json',result['artifactsRead']['lead'])
                self.assertNotIn('999',str(result['report']))
                self.assertTrue(any(f['id']=='traffic-comparison-status' for f in result['facts']))

    def test_specialist_correction_cannot_exceed_existing_model_call_limit(self):
        final=message(call('SiteReview',{'findings':[],'recommendations':[],'questions':['Verify source coverage?']}))
        domain=specialist_model('domain','street',[
            *[message(read('/project/source-brief.json')) for _ in range(9)], AIMessage(content='Inputs inspected.'), final])
        lead=lead_model([calls('delegate'),final]); site=specialist_model('site','street',[final])
        with patch('site_agent.ChatXAI',side_effect=[lead,site,domain]):
            result=analyze_site('unused','fake','Review','street',[],lambda _:[],lambda:({},[]),lambda:{},lon=LON,lat=LAT)
        self.assertIsNone(result['analysisError'])
        self.assertEqual(len(domain.seen),12)
        self.assertEqual(len(domain.responses),1)
        self.assertFalse(result['specialists']['domain-analysis'])

    def test_mixed_report_write_and_invalid_review_gets_one_bounded_schema_only_correction(self):
        final=message(call('SiteReview',{'findings':[],'recommendations':[],'questions':['Verify drainage connectivity?']}))
        bad={'findings':[{'text':'The rainfall estimate is 999 in.','fact_ids':['county-rainfall']}],
             'recommendations':[],'questions':['Verify drainage connectivity?']}
        mixed=message(call('write_file',{'file_path':'/project/reports/domain-analysis.json','content':'FORGED REPORT'}),
                      call('SiteReview',bad))
        for correction in (final, message(call('SiteReview',bad)), calls('read_rainfall_and_watershed')):
            with self.subTest(correction=correction):
                lead=lead_model([calls('delegate'),final]); site=specialist_model('site','water',[final])
                domain=specialist_model('domain','water',[mixed,correction,final])
                imagery=Mock(return_value=[]); property_source=Mock(return_value=({},[]))
                hydrology=Mock(return_value={'estimate':{'inches':1.01,'depth_range':[1,1.1],'method':'interpolated'}})
                events=[]; saved={}
                with patch('site_agent.ChatXAI',side_effect=[lead,site,domain]):
                    result=analyze_site('unused','fake','Review','water',[],imagery,property_source,hydrology,
                        lon=LON,lat=LAT,activity=Activity(events.append),
                        persist_artifact=lambda path,content:saved.__setitem__(path,content))
                self.assertIsNone(result['analysisError'])
                self.assertEqual(result['specialists']['domain-analysis'],correction is final)
                self.assertEqual(len(domain.seen),4)
                self.assertEqual(len(domain.responses),1,'mixed-call failure shares the single correction budget')
                self.assertEqual(domain.tool_sets[-1],{'SiteReview'})
                self.assertEqual(len([e for e in events if e['stage']=='structured-review']),1)
                self.assertIn('numbers not present',str(domain.seen[-1]),'the corrective request sees the actual validation error')
                self.assertIn('write_file',str(domain.seen[-1]),'the native ordinary-tool result is complete before correction')
                self.assertNotIn('FORGED REPORT',str(saved))
                self.assertEqual(imagery.call_count,2); property_source.assert_called_once(); hydrology.assert_called_once()
                self.assertTrue(any(f['id']=='county-rainfall' for f in result['facts']))
                self.assertIn('/project/reports/domain-analysis.json',result['artifactsRead']['lead'])

    def test_cancellation_before_specialist_correction_prevents_another_model_request(self):
        final=message(call('SiteReview',{'findings':[],'recommendations':[],'questions':['Verify source coverage?']}))
        domain=specialist_model('domain','street',[AIMessage(content='Inputs inspected.'),final])
        lead=lead_model([calls('delegate'),final]); site=specialist_model('site','street',[final])
        def emit(event):
            if event['stage']=='structured-review': activity.cancelled.set()
        activity=Activity(emit)
        with patch('site_agent.ChatXAI',side_effect=[lead,site,domain]):
            result=analyze_site('unused','fake','Review','street',[],lambda _:[],lambda:({},[]),lambda:{},lon=LON,lat=LAT,activity=activity)
        self.assertIn('canceled',result['analysisError'])
        self.assertEqual(len(domain.seen),3)
        self.assertEqual(len(domain.responses),1)

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
