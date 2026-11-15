import io
import json
import unittest
from unittest.mock import Mock, patch
from email.message import Message
from agent_activity import Activity, RunCancelled
from test_site_agent import ScriptedModel, calls, lead_model, specialist_model
from test_site_measurements import LAT, LON
from site_agent import analyze_site
from server import Handler, ACTIVE_ANALYSES

class ActivityTest(unittest.TestCase):
    def test_disconnect_cancels_before_more_source_or_model_work(self):
        activity=Activity()
        def emit(event):
            if event['stage']=='outlines' and event['status']=='started':
                raise BrokenPipeError('client gone')
        activity.emit=emit
        model=lead_model([calls('delegate')])
        fetch=Mock(side_effect=lambda *args: self.assertFalse(activity.cancelled.is_set()) or [])
        with patch('site_agent.ChatXAI',side_effect=[model,specialist_model("site","street",[]),specialist_model("domain","street",[])]):
            result=analyze_site('key','test','Review','street',[],fetch,fetch,fetch,lon=LON,lat=LAT,activity=activity)
        self.assertTrue(activity.cancelled.is_set())
        self.assertIsNone(result['report'])
        self.assertTrue(all(call.args != ("outlines",) for call in fetch.call_args_list))
        self.assertNotIn('client gone',str(result))

    def test_transport_streams_sanitized_events_then_matching_result(self):
        payload={'lat':LAT,'lon':LON,'workflow':'street','question':'Review',
                 'siteId':'stream-test-site','inputRevision':0,'proposalRevision':1}
        raw=json.dumps(payload).encode(); h=Handler.__new__(Handler)
        h.path='/api/site-analysis';h.headers=Message()
        h.headers['Content-Type']='application/json';h.headers['Accept']='application/x-ndjson';h.headers['Content-Length']=str(len(raw))
        h.rfile=io.BytesIO(raw);h.wfile=io.BytesIO()
        for name in ('send_response','send_header','end_headers','log_error'):setattr(h,name,Mock())
        def run(*args,activity,**kw):
            activity.event('lead','planning','started','Preparing review.')
            return {'runId':activity.id,'facts':[],'report':None}
        with patch.dict('os.environ',{'GROK_API_KEY':'private-key'}),patch('site_agent.analyze_site',side_effect=run):h.do_POST()
        events=[json.loads(line) for line in h.wfile.getvalue().splitlines()]
        self.assertEqual([e['type'] for e in events],['activity','result'])
        self.assertEqual(events[0]['run_id'],events[1]['result']['runId'])
        self.assertNotIn('private-key',h.wfile.getvalue().decode())

    def test_expired_run_stops(self):
        with self.assertRaises(RunCancelled):Activity(seconds=-1).check()

    def test_cancel_endpoint_signals_only_matching_run(self):
        activity=Activity();ACTIVE_ANALYSES[activity.id]=activity
        try:
            raw=json.dumps({"runId":activity.id}).encode()
            h=Handler.__new__(Handler);h.path="/api/site-analysis/cancel";h.headers=Message()
            h.headers["Content-Type"]="application/json";h.headers["Content-Length"]=str(len(raw))
            h.rfile=io.BytesIO(raw);h.send_json=Mock()
            h.do_POST()
            self.assertTrue(activity.cancelled.is_set())
            self.assertEqual(h.send_json.call_args.args,(202,{"canceled":True}))
        finally:ACTIVE_ANALYSES.pop(activity.id,None)
