"""Exercise the real Deep Agents graph using a scripted offline model."""
import json
import threading
import unittest
from typing import Any
from unittest.mock import patch

from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage, ToolMessage
from langchain_core.outputs import ChatGeneration, ChatResult
from langchain_core.runnables import RunnableLambda
from pydantic import Field

from evidence import build_evidence
from planner import Budget, VisualNotes, investigate
from test_investigations import SITE, example_report


class ScriptedModel(BaseChatModel):
    bound_tools: list[Any] = Field(default_factory=list, exclude=True)

    @property
    def _llm_type(self):return 'offline-scripted-test'

    def bind_tools(self,tools,**kwargs):return self.model_copy(update={'bound_tools':list(tools)})

    def with_structured_output(self,*args,**kwargs):
        return RunnableLambda(lambda messages:{'raw':AIMessage(content='offline visual fixture'),
            'parsed':VisualNotes(observations=['Marked crossings are visible in the test fixture.'],uncertainties=['Test fixture only.'])})

    def _generate(self,messages,stop=None,run_manager=None,**kwargs):
        available={t.name for t in self.bound_tools}
        used={m.name for m in messages if isinstance(m,ToolMessage)}
        calls=[]
        def call(name,args):calls.append({'name':name,'args':args,'id':f'call-{name}-{len(messages)}-{len(calls)}','type':'tool_call'})
        if 'submit_report' in available:
            if 'task' not in used:
                call('write_todos',{'todos':[{'content':'Investigate evidence with specialists','status':'in_progress'}]})
                for role in ['crash-analyst','site-analyst','guidance-researcher']:
                    call('task',{'subagent_type':role,'description':'Read the assigned evidence tools, write your notes file, and publish.'})
            elif 'read_specialist_notes' not in used:call('read_specialist_notes',{})
            elif 'submit_report' not in used:call('submit_report',example_report())
        else:
            role='site-analyst' if 'inspect_aerial' in available else 'guidance-researcher' if 'read_guidance' in available else 'crash-analyst'
            needed={'site-analyst':['inspect_aerial'],'guidance-researcher':['get_crash_evidence','read_guidance'],'crash-analyst':['get_crash_evidence']}[role]
            for name in needed:
                if name not in used:call(name,{})
            if not calls and 'write_file' not in used:
                call('write_file',{'file_path':f'/notes/{role}.md','content':'Evidence: E-location. Verify crash locations before selecting treatments.'})
            elif not calls and 'publish_notes' not in used:
                call('publish_notes',{'file_path':f'/notes/{role}.md'})
        message=AIMessage(content='' if calls else 'Specialist notes published.',tool_calls=calls,
                          usage_metadata={'input_tokens':20,'output_tokens':10,'total_tokens':30})
        return ChatResult(generations=[ChatGeneration(message=message)])


class WorkflowTest(unittest.TestCase):
    @patch('planner.model_for',return_value=ScriptedModel())
    def test_real_delegation_files_and_final_report_without_external_calls(self,model):
        evidence=build_evidence(SITE)
        events=[]; artifacts={}
        emit=lambda role,text,kind:events.append((role,text,kind))
        budget=Budget(threading.Event(),emit,seconds=20)
        result=investigate('dummy','offline',evidence,lambda site:b'fake-image',budget,emit,artifacts)
        self.assertEqual(result['summary'],example_report()['summary'])
        self.assertEqual(set(artifacts),{'crash-analyst','site-analyst','guidance-researcher'})
        self.assertTrue(all('Evidence: E-location' in x['text'] for x in artifacts.values()))
        self.assertTrue(any(kind=='planning' for _,_,kind in events))
        self.assertEqual(sum(kind=='delegation' for _,_,kind in events),3)
        self.assertIn('V-aerial',evidence['sources'])
        self.assertLessEqual(budget.calls,24)


if __name__=='__main__':unittest.main()
