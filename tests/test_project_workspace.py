"""Native graph, durable state, concurrency boundaries and recovery regressions."""
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from agent_activity import Activity, RunCancelled, TransientSourceError
from project_store import ProjectStore, ProjectConflict
from site_agent import analyze_site
from test_site_agent import lead_model, specialist_model, message, call, calls, read


def snapshot(question='Preserve the loading entrance while reducing environmental impacts.'):
    return dict(workflow='street',siteId='workspace-test',lon=-118.25,lat=34.05,propertyId=None,
                question=question,markings=[],rainfallScenario=None,inputRevision=0,proposalRevision=1)


def review():
    return message(call('SiteReview',dict(findings=[],recommendations=[],questions=['Verify the available source coverage?'])))


def run_graph(store, project, *, extra=(), imagery=lambda _: [], property_context=lambda: ({}, []), discovery=None):
    models=[lead_model([*extra,calls('delegate'),review()]),
            specialist_model('site','street',[review()]),specialist_model('domain','street',[review()],discovery=discovery is not None)]
    events=[]
    activity=Activity(events.append)
    store.begin(project['id'],project['version'],activity.id)
    from deepagents import create_deep_agent
    graphs=[]
    def capture(**kwargs):
        graph=create_deep_agent(**kwargs);graphs.append(graph);return graph
    with patch('site_agent.ChatXAI',side_effect=models),patch('site_agent.create_deep_agent',side_effect=capture),store.checkpointer() as saver:
        result=analyze_site('unused','fake',project['snapshot']['question'],'street',[],imagery,property_context,lambda:{},
            lon=-118.25,lat=34.05,project=project,checkpointer=saver,activity=activity,fetch_discovery=discovery,
            persist_artifact=lambda path,content:store.artifact(project['id'],path,content,activity.id))
        checkpoint=graphs[-2 if discovery is not None else -1].get_state({'configurable':{'thread_id':project['threadId']}}).values
    store.finish(project['id'],activity.id,result,'ready' if not result['analysisError'] else 'failed')
    return result, models, checkpoint, events


class WorkspaceTest(unittest.TestCase):
    def test_native_checkpoint_continues_after_a_fresh_python_process(self):
        with tempfile.TemporaryDirectory() as directory:
            store=ProjectStore(directory);project=store.save(snapshot())
            result,_,checkpoint,_=run_graph(store,project)
            self.assertIsNone(result['analysisError'])
            self.assertIn('/project/history/previous-review.json',checkpoint['files'])
            project=store.save({**snapshot('Try a smaller footprint.'),'inputRevision':1,'proposalRevision':2},project['id'],project['version'])
            script='''import json,sys
sys.path.insert(0,"tests")
from test_project_workspace import *
store=ProjectStore(sys.argv[1]);project=store.get(sys.argv[2])
result,models,checkpoint,events=run_graph(store,project,extra=[message(read('/project/history/previous-review.json'))])
assert result['analysisError'] is None,result['analysisError']
assert '/project/history/previous-review.json' in result['artifactsRead']['lead']
sent=str([model.seen for model in models])
assert 'Preserve the loading entrance' in sent
assert 'Try a smaller footprint.' in sent
print(json.dumps({'thread':project['threadId'],'skills':result['skillsUsed'],'read_previous':True}))
'''
            child=subprocess.run([sys.executable,'-c',script,directory,project['id']],cwd=Path(__file__).resolve().parents[1],text=True,capture_output=True,timeout=20)
            self.assertEqual(child.returncode,0,child.stderr)
            self.assertEqual(json.loads(child.stdout)['thread'],project['threadId'])
            reloaded=ProjectStore(directory).get(project['id'])
            self.assertEqual(reloaded['snapshot']['question'],'Try a smaller footprint.')
            self.assertEqual(len(reloaded['instructions']),2)

    def test_stale_run_cannot_publish_or_replace_latest_artifacts(self):
        with tempfile.TemporaryDirectory() as directory:
            store=ProjectStore(directory);first=store.save(snapshot());run='a'*32
            store.begin(first['id'],first['version'],run)
            activity=Activity(current=lambda:store.is_current(first['id'],run))
            updated=store.save({**snapshot(),'inputRevision':1},first['id'],first['version'])
            with self.assertRaises(RunCancelled):activity.check()
            store.begin(first['id'],updated['version'],'b'*32)
            store.artifact(first['id'],'/project/evaluations/traffic.json','latest','b'*32)
            store.artifact(first['id'],'/project/evaluations/traffic.json','stale',run)
            self.assertEqual(store.artifact(first['id'],'/project/evaluations/traffic.json'),'latest')
            self.assertFalse(store.finish(first['id'],run,{'proposal':{'status':'pass'}},'ready'))
            with self.assertRaises(ProjectConflict):store.save(snapshot(),first['id'],first['version'])

    def test_interrupted_run_preserves_inputs_and_activity_on_restart(self):
        with tempfile.TemporaryDirectory() as directory:
            store=ProjectStore(directory);project=store.save(snapshot());run='a'*32
            store.begin(project['id'],project['version'],run)
            store.event(project['id'],{'run_id':run,'sequence':1,'summary':'Read source facts.'})
            restarted=ProjectStore(directory);restarted.recover_interrupted();value=restarted.get(project['id'])
            self.assertEqual(value['status'],'interrupted');self.assertIsNone(value['activeRun'])
            self.assertEqual(value['snapshot'],project['snapshot']);self.assertEqual(len(value['events']),1)

    def test_tools_cannot_rewrite_constraints_skills_or_evaluation(self):
        with tempfile.TemporaryDirectory() as directory:
            store=ProjectStore(directory);project=store.save(snapshot())
            attempts=message(*(call('write_file',{'file_path':path,'content':'FORGED PASS'},path) for path in
                ['/project/constraints.json','/skills/property-association/SKILL.md','/project/evaluations/traffic.json','/Users/Derek/.env']))
            result,models,checkpoint,_=run_graph(store,project,extra=[attempts])
            self.assertIsNone(result['analysisError'])
            files=checkpoint['files']
            self.assertNotIn('/Users/Derek/.env',files)
            self.assertNotIn('/project/evaluations/traffic.json',files)
            self.assertNotIn('FORGED PASS',str(files['/project/constraints.json']))
            self.assertNotIn('FORGED PASS',str(files['/skills/property-association/SKILL.md']))
            self.assertTrue(any('denied' in str(message.content).lower() for group in models[0].seen for message in group))

    def test_transient_source_retry_is_bounded_and_bad_data_is_not_retried(self):
        with tempfile.TemporaryDirectory() as directory:
            store=ProjectStore(directory);project=store.save(snapshot());attempts=[]
            def imagery(group):
                attempts.append(group)
                if group=='outlines':raise TransientSourceError('PRIVATE network detail')
                return []
            count=[]
            def invalid():
                count.append(1);raise ValueError('PRIVATE sponsor payload')
            result,models,checkpoint,events=run_graph(store,project,imagery=imagery,property_context=invalid)
            self.assertIsNone(result['analysisError'])
            self.assertEqual(attempts.count('outlines'),2);self.assertEqual(len(count),1)
            self.assertEqual(result['sourceStatus']['outlines'],'unavailable')
            for value in (result,events,checkpoint,[model.seen for model in models]):
                self.assertNotIn('PRIVATE',str(value))
            self.assertEqual(len([e for e in events if e['status']=='retry' and e['stage']=='outlines']),1)

    def test_live_traffic_is_used_in_memory_but_never_archived(self):
        from site_measurements import fact, source
        live=fact('live-sensitive-marker','Current speed',37.45,'km/h',source('TomTom current traffic'),basis='reported')
        with tempfile.TemporaryDirectory() as directory:
            store=ProjectStore(directory);project=store.save(snapshot())
            result,models,checkpoint,events=run_graph(store,project,discovery=lambda:([live],[]))
            self.assertIsNone(result['analysisError'])
            self.assertIn('live-sensitive-marker',str([model.seen for model in models]))
            self.assertNotIn('live-sensitive-marker',str(checkpoint))
            saved=store.get(project['id'])
            self.assertNotIn('live-sensitive-marker',str(saved))
            self.assertIsNone(saved['result']['report'])
            self.assertTrue(saved['result']['resumeNotice'])
            for item in saved['artifacts']:
                self.assertNotIn('live-sensitive-marker',store.artifact(project['id'],item['path']))

    def test_no_property_or_workflow_switch_within_project(self):
        with tempfile.TemporaryDirectory() as directory:
            store=ProjectStore(directory);project=store.save(snapshot())
            for change in ({'workflow':'water'},{'lon':-118.26},{'siteId':'different'}):
                with self.assertRaises(ValueError):store.save({**snapshot(),**change},project['id'],project['version'])

if __name__=='__main__':unittest.main()
