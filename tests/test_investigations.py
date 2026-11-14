import json
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from evidence import build_evidence
from investigations import Investigations, JobError
from planner import Budget, RunStopped, validate_report

SITE = {"name": "TEST ST & EXAMPLE ST", "lat": 34.05, "lon": -118.25}


def example_report():
    return {"summary": "Verify reported locations before choosing a treatment.", "findings": [{
        "title": "Check the reported crash locations", "category": "evidence gap",
        "concern": "Crash locations are uncertain.", "evidence_ids": ["E-location"],
        "strength": "limited", "strength_reason": "Street names alone do not confirm location.",
        "hypothesis": "Not established.", "next_check": "Obtain collision diagrams to locate the reported events.",
        "candidate_option": "Defer treatment selection.", "guidance_ids": [],
        "prerequisites": "Confirmed crash locations."}], "limitations": ["Traffic counts are unavailable."]}


class EvidenceTest(unittest.TestCase):
    def test_ids_deduplicate_without_collapsing_distinct_reports_and_keep_unknown(self):
        row = {"evidence_id": "C-same", "offset_ft": None, "injured": None, "killed": 0, "type": "REAR END"}
        rows = [row, row, dict(row, evidence_id="C-other", offset_ft=500, injured=1)]
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp)/"ccrs.json"
            path.write_text(json.dumps({"sites": {SITE['name']: rows}, "near_ft": 150}))
            evidence = build_evidence(SITE, path)
        self.assertEqual(len(evidence['records']), 2)
        self.assertEqual(evidence['sources']['S-uncertain']['value'], 1)
        self.assertEqual(evidence['sources']['S-nearby']['value'], 1)
        self.assertEqual(evidence['sources']['S-junction']['value'], 0)
        self.assertEqual(evidence['sources']['S-injured-missing']['value'], 1)
        self.assertEqual(evidence['sources']['S-injured']['value'], 1)

    def test_missing_data_not_zero_crashes_claim(self):
        evidence = build_evidence(SITE, Path('/nonexistent/crossing-test.json'))
        self.assertTrue(evidence['unavailable'])
        self.assertEqual(evidence['records'], [])

    def test_validation_rejects_unknown_sources_visual_fabrication_and_numbers(self):
        evidence = build_evidence(SITE, Path('/nonexistent/crossing-test.json'))
        self.assertEqual(validate_report(example_report(), evidence)['findings'][0]['strength'], 'limited')
        for mutation in ({'evidence_ids':['invented']}, {'category':'visual observation'},
                         {'concern':'There were 12 crashes.'}, {'guidance_ids':['E-location']}):
            report = example_report(); report['findings'][0].update(mutation)
            with self.subTest(mutation=mutation), self.assertRaises(ValueError):
                validate_report(report,evidence)


class BudgetTest(unittest.TestCase):
    def test_shared_budget_cancellation_and_no_lock_inversion(self):
        stop=threading.Event(); budget=Budget(stop,lambda *args: None,max_calls=2)
        r=budget.reserve('lead'); budget.finish(r,[])
        r=budget.reserve('specialist'); budget.finish(r,[])
        with self.assertRaises(RunStopped): budget.reserve('vision')
        stop.set()
        with self.assertRaises(RunStopped): budget.check()

    def test_time_limit(self):
        budget=Budget(threading.Event(),lambda *args: None,seconds=-1)
        with self.assertRaises(RunStopped):budget.check()


class JobsTest(unittest.TestCase):
    def setUp(self):
        self.env=patch.dict('os.environ', {'GROK_API_KEY':'test-key'})
        self.env.start();self.addCleanup(self.env.stop)

    def manager(self,runner):
        manager=Investigations(lambda site: b'fake',runner)
        self.addCleanup(manager.pool.shutdown,wait=True)
        return manager

    def wait(self,manager,id_):
        deadline=time.monotonic()+2
        while time.monotonic()<deadline:
            status=manager.snapshot(id_,SITE['name'])
            if status['status']!='running': return status
            time.sleep(.005)
        self.fail('Job did not finish')

    def test_cache_and_cross_site_isolation(self):
        calls=[]
        def runner(key,model,ev,image,budget,emit,artifacts):
            calls.append(1);ev['sources']['V-aerial']={'kind':'visual'};ev['unavailable']=False
            return example_report()
        manager=self.manager(runner)
        run=manager.start(SITE);done=self.wait(manager,run['id'])
        self.assertEqual(done['status'],'complete')
        cached=manager.start(SITE)
        self.assertTrue(cached['cached']);self.assertEqual(len(calls),1)
        with self.assertRaises(JobError): manager.snapshot(run['id'],'OTHER SITE')
        done['report']['summary']='mutated client copy'
        self.assertNotEqual(manager.snapshot(run['id'],SITE['name'])['report']['summary'],'mutated client copy')

    def test_cancel_keeps_result_from_publishing_and_capacity_is_bounded(self):
        entered=threading.Event(); release=threading.Event()
        def runner(*args): entered.set();release.wait(1);return example_report()
        manager=self.manager(runner)
        first=manager.start(SITE);entered.wait(1)
        second_site=dict(SITE,name='OTHER')
        manager.start(second_site)
        with self.assertRaises(JobError) as error:manager.start(dict(SITE,name='THIRD'))
        self.assertEqual(error.exception.status,429)
        manager.cancel(first['id'],SITE['name']);release.set()
        done=self.wait(manager,first['id'])
        self.assertEqual(done['status'],'cancelled');self.assertIsNone(done['report'])

    def test_missing_imagery_returns_partial_and_provider_error_is_sanitized(self):
        manager=self.manager(lambda *args:example_report())
        run=manager.start(SITE);self.assertEqual(self.wait(manager,run['id'])['status'],'partial')
        def failing(*args):raise RuntimeError('SECRET PROVIDER CONTENT')
        other=self.manager(failing);run=other.start(SITE);done=self.wait(other,run['id'])
        self.assertNotIn('SECRET PROVIDER CONTENT',json.dumps(done))
        self.assertEqual(done['status'],'failed')


if __name__ == '__main__':unittest.main()
