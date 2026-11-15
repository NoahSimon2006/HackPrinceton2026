import copy
import json
import tempfile
import unittest
from unittest.mock import patch

from agent_activity import Activity
from project_store import ProjectStore
from proposal import comparison_fingerprint, from_traffic_comparison
from traffic_workspace import evaluation_record, prior_context, revised_layouts
from test_traffic_analysis import comparison


def snapshot(revision=1):
    return {'workflow':'street','siteId':'street-loop','lon':-118.2434,'lat':34.0522,
            'propertyId':None,'question':'Revise the selected street layout.','markings':[],
            'rainfallScenario':None,'inputRevision':revision-1,'proposalRevision':revision}


def publication(revision=1):
    c=comparison(None); c['status']='completed'
    identity={'site_id':'street-loop','revision':revision,'input_revision':revision-1}
    c.update(identity,workflow='street'); c['input_hash']=comparison_fingerprint(c,**identity)
    return {'comparison':c,'proposal':None,'alternatives':{n:from_traffic_comparison(c,n,**identity).model_dump() for n in c['layouts']},
            'trafficPlan':{'settings':{'layouts':list(c['layouts'].values())}},
            'report':{'findings':['Ephemeral live traffic prose']},'facts':[]}


class TrafficWorkspaceTest(unittest.TestCase):
    def setUp(self):
        # Scripted models use no provider capacity; pacing has dedicated fake-clock tests.
        from unittest.mock import patch
        pacing = patch('xai_runtime.MIN_INTERVAL_SECONDS', 0)
        pacing.start()
        self.addCleanup(pacing.stop)

    def test_named_revision_preserves_other_layouts_and_context_is_curated(self):
        record=publication()
        revised=revised_layouts(record,[{'name':'north-curb','length_m':20}])
        self.assertEqual(revised[0].length_m,20)
        self.assertEqual(revised[1].model_dump(),record['comparison']['layouts']['east-bike'])
        for changes in ([{'name':'unknown','length_m':30}],[{'name':'north-curb','coordinates':[]}],[{'name':'north-curb','length_m':40}]):
            with self.assertRaises(ValueError): revised_layouts(record,changes)
        safe=json.dumps(prior_context(record))
        for text in ('PRIVATE','coordinates','sheet_url','Ephemeral','node_id'):
            self.assertNotIn(text,safe)
        self.assertIn('previous-traffic-north-curb-co2',safe)

    def test_rejected_evaluations_archive_without_live_prose_and_match_exact_inputs(self):
        with tempfile.TemporaryDirectory() as directory:
            store=ProjectStore(directory);p=store.save(snapshot()); first=publication()
            store.begin(p['id'],p['version'],'a'*32);self.assertTrue(store.finish(p['id'],'a'*32,first,'ready'))
            p=store.save(snapshot(2),p['id'],p['version']);store.begin(p['id'],p['version'],'b'*32)
            self.assertFalse(store.finish(p['id'],'a'*32,first,'ready'))
            store.finish(p['id'],'b'*32,publication(2),'ready')
            restored=ProjectStore(directory).get(p['id'])
            self.assertEqual([h['revision'] for h in restored['trafficDesignHistory']],[1,2])
            self.assertIsNone(restored['result']['report'])
            self.assertNotIn('Ephemeral',json.dumps(restored['trafficDesignHistory']))
            self.assertTrue(all(p['status']=='rejected' for p in restored['trafficDesignHistory'][0]['alternatives'].values()))
        for mutate in (lambda r:r['comparison'].update(revision=99),lambda r:r['comparison']['results']['baseline'].update(co2_kg_per_hour=1),lambda r:r['alternatives']['north-curb']['metrics'][0].update(proposed=99)):
            bad=publication();mutate(bad)
            with self.assertRaises(ValueError): evaluation_record(bad,snapshot())

    def test_valid_traffic_evaluation_survives_narrative_failure_but_not_deadline(self):
        from site_agent import analyze_site
        from test_site_agent import ScriptedModel,lead_model,specialist_model,calls,message,call
        from test_traffic_analysis import study,context,LAYOUTS
        for expires in (False,True):
            review=message(call('SiteReview',{'findings':[],'recommendations':[],'questions':[]}))
            lead=lead_model([calls('delegate'),message(call('evaluate_designs',{'changes':[{'name':'north-curb','length_m':20}]})),RuntimeError('transport failure')])
            models=[lead,specialist_model('site','street',[review]),specialist_model('domain','street',[review])]
            activity=Activity();original=ScriptedModel._generate
            def generate(model,*args,**kwargs):
                if expires and model.responses and isinstance(model.responses[0],RuntimeError): activity.deadline=0
                return original(model,*args,**kwargs)
            with patch('site_agent.ChatXAI',side_effect=models),patch.object(ScriptedModel,'_generate',generate),patch('traffic_analysis.Study',return_value=study()),patch('traffic_analysis.evaluate',return_value=comparison(None)) as evaluator:
                result=analyze_site('unused','fake','Evaluate layouts.','street',[],lambda group:[],lambda:(None,[],[]),lambda:{},lon=-118.2434,lat=34.0522,
                    traffic_context=context(),analysis_identity={'site_id':'street-loop','revision':1,'input_revision':0},allow_generated_timing=True,activity=activity,
                    project={'id':'native-revision','threadId':'native-revision-thread','trafficDesignHistory':[publication()]})
            evaluated=evaluator.call_args.args[1]
            self.assertEqual(evaluated[0].length_m,20)
            self.assertEqual(evaluated[1].model_dump(),LAYOUTS[1])
            if expires:
                self.assertTrue(result['analysisError']);self.assertEqual(result['alternatives'],{});self.assertIsNone(result['trafficPlan'])
            else:
                self.assertIsNone(result['analysisError']);self.assertTrue(result['synthesisWarning']);self.assertEqual(result['comparison']['status'],'completed');self.assertEqual(len(result['alternatives']),2)
