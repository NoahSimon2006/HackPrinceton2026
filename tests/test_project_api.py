import io
import json
from email.message import Message
import tempfile
import unittest
from unittest.mock import Mock, patch

from discovery import map_discovery, traffic_context_at_site
from project_store import ProjectStore
from server import Handler
from test_project_workspace import snapshot


def handler(path, value):
    h=Handler.__new__(Handler);h.path=path;h.headers=Message()
    payload=json.dumps(value).encode();h.rfile=io.BytesIO(payload);h.wfile=io.BytesIO()
    h.headers['Content-Type']='application/json';h.headers['Content-Length']=str(len(payload))
    h.send_json=Mock();h.log_error=Mock()
    return h


class ProjectApiTest(unittest.TestCase):
    def test_saved_revision_is_required_before_an_agent_can_run(self):
        with tempfile.TemporaryDirectory() as directory:
            store=ProjectStore(directory);project=store.save(snapshot())
            payload={**snapshot('Changed without saving'),'projectId':project['id'],'projectVersion':project['version']}
            h=handler('/api/site-analysis',payload)
            with patch('server.project_store',return_value=store),patch('server.traffic_context_at_site',return_value=None),patch('site_agent.analyze_site') as analyze:
                h.do_POST()
            self.assertEqual(h.send_json.call_args.args[0],409);analyze.assert_not_called()

    def test_project_endpoint_rejects_cross_site_writes(self):
        h=handler('/api/projects',{'snapshot':snapshot()});h.headers['Sec-Fetch-Site']='cross-site'
        h.do_POST();self.assertEqual(h.send_json.call_args.args[0],400)

    def test_map_exposes_only_current_traffic_layers(self):
        historical={'layers':[{'id':'counts'},{'id':'turning'}], 'sources':{'historical':{}},'version':'old'}
        live={'layers':[{'id':'flow'},{'id':'approaches'}],'sources':{'tomtom':{}},'audit':{}}
        with patch('discovery.load_discovery',return_value=historical),patch('traffic_flow.get_snapshot',return_value=live):
            data=map_discovery('street')
        self.assertEqual([layer['id'] for layer in data['layers']],['flow','approaches'])
        self.assertEqual(set(data['sources']),{'tomtom'})

    def test_internal_count_association_requires_one_close_intersection(self):
        feature={'id':'verified','properties':{'center':[-118.25,34.05]}}
        data={'version':'version','layers':[{'id':'turning','features':[feature]}]}
        with patch('discovery.load_discovery',return_value=data),patch('discovery.traffic_context',return_value={}) as resolve:
            result=traffic_context_at_site(-118.25,34.0501)
            self.assertLessEqual(result['association_distance_m'],25)
            self.assertEqual(resolve.call_args.args[0],{'version':'version','layer':'turning','feature':'verified'})
            resolve.reset_mock()
            self.assertIsNone(traffic_context_at_site(-118.26,34.05));resolve.assert_not_called()
            data['layers'][0]['features'].append({'id':'ambiguous','properties':{'center':[-118.25001,34.05]}})
            self.assertIsNone(traffic_context_at_site(-118.25,34.05));resolve.assert_not_called()

if __name__=='__main__':unittest.main()
