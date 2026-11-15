import json
import threading
import unittest
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import patch

import xai_runtime as runtime
from agent_activity import RunCancelled


class ProviderError(Exception):
    def __init__(self, status=429, code='rate_limit_exceeded', message='Private provider details', headers=None):
        self.status_code = status
        self.body = {'error': {'code': code, 'message': message}}
        self.response = SimpleNamespace(status_code=status, headers=headers or {})


class Activity:
    def __init__(self, cancel_at=None):
        self.lock = threading.Lock()
        self.events = []
        self.cancel_at = cancel_at

    def check(self):
        if self.cancel_at is not None and runtime.monotonic() >= self.cancel_at:
            raise RunCancelled('Canceled')

    def event(self, *args):
        self.check()
        self.events.append(args)


class ModelRuntimeTest(unittest.TestCase):
    def setUp(self):
        runtime._GATES.clear()
        self.now = 0.0
        self.sleeps = []
        self.stack = []
        def advance(seconds):
            self.sleeps.append(seconds)
            self.now += seconds
        for item in (patch.object(runtime, 'monotonic', lambda: self.now),
                     patch.object(runtime, 'sleep', advance),
                     patch.object(runtime.random, 'uniform', return_value=0)):
            item.start(); self.stack.append(item)
        self.request = SimpleNamespace(messages=[SimpleNamespace(content='PRIVATE-PROMPT')],
                                       tools=[SimpleNamespace(name='private-tool')])
        self.response = SimpleNamespace(result=[SimpleNamespace(
            usage_metadata={'input_tokens': 40, 'output_tokens': 3, 'total_tokens': 43},
            response_metadata={'headers': {'x-ratelimit-limit-tokens': '50000000', 'set-cookie': 'PRIVATE-COOKIE'}})])

    def tearDown(self):
        for item in reversed(self.stack): item.stop()

    def invoke(self, handler, activity=None, key='PRIVATE-KEY', model='test-model'):
        return runtime.invoke_model(handler, self.request, activity=activity or Activity(),
                                    specialist='lead', model_name=model, key=key)

    def test_429_retries_same_request_after_header_and_records_only_safe_metadata(self):
        seen = []
        def handler(request):
            seen.append(request)
            if len(seen) == 1:
                raise ProviderError(headers={'Retry-After': '3', 'x-ratelimit-remaining-tokens': '0',
                                             'x-ratelimit-reset-tokens': '1m2s', 'authorization': 'PRIVATE-KEY'})
            return self.response
        activity = Activity()
        self.assertIs(self.invoke(handler, activity), self.response)
        self.assertEqual(seen, [self.request, self.request])
        self.assertGreaterEqual(self.now + 1e-8, 3)
        self.assertTrue(all(step <= .1 for step in self.sleeps))
        metadata = activity.model_diagnostics
        self.assertEqual(metadata[0]['category'], 'rate_limit')
        self.assertEqual(metadata[0]['limits']['x-ratelimit-reset-tokens'], 62)
        self.assertEqual(metadata[1]['total_tokens'], 43)
        self.assertNotIn('PRIVATE', json.dumps(metadata))
        self.assertNotIn('headers', self.response.result[0].response_metadata)
        self.assertEqual(metadata[1]['limits']['x-ratelimit-limit-tokens'], 50000000)
        self.assertEqual(activity.model_usage['attempts'], 2)
        self.assertEqual(activity.model_usage['retries'], 1)
        self.assertEqual(activity.model_usage['input_tokens'], 40)
        self.assertEqual(activity.model_usage['last_error']['category'], 'rate_limit')
        self.assertTrue(any(event[2] == 'retrying' for event in activity.events))

    def test_quota_auth_and_invalid_request_fail_without_retry(self):
        for error in (ProviderError(code='insufficient_quota'), ProviderError(401), ProviderError(400)):
            with self.subTest(error=error.status_code):
                runtime._GATES.clear();calls=[]
                def handler(request):
                    calls.append(request);raise error
                with self.assertRaises(ProviderError): self.invoke(handler)
                self.assertEqual(len(calls), 1)
        self.assertEqual(runtime.classify_error(ProviderError(code='insufficient_quota'))['category'], 'quota_or_billing')
        self.assertEqual(self.sleeps, [])

    def test_transient_retries_are_bounded_and_release_capacity(self):
        calls=[]
        def handler(request):
            calls.append(request)
            if len(calls)==1: raise TimeoutError('PRIVATE transport text')
            raise ProviderError(503)
        with self.assertRaises(ProviderError): self.invoke(handler)
        self.assertEqual(len(calls), 3)
        self.assertEqual(runtime._gate('PRIVATE-KEY', 'test-model').active, 0)
        self.assertLessEqual(self.now, 60)

    def test_large_retry_after_is_honored_without_unbounded_wait_or_cross_scope_blocking(self):
        calls=[]
        def handler(request):
            calls.append(request);raise ProviderError(headers={'Retry-After': '90'})
        with self.assertRaises(runtime.ModelRateLimitWaitError): self.invoke(handler)
        self.assertEqual(len(calls), 1)
        with self.assertRaises(runtime.ModelRateLimitWaitError): self.invoke(lambda request:self.response)
        self.assertIs(self.invoke(lambda request:self.response, key='DIFFERENT-KEY'), self.response)
        self.assertIs(self.invoke(lambda request:self.response, model='different-model'), self.response)
        self.assertEqual(self.now, 0)

    def test_cancel_during_backoff_never_starts_another_request(self):
        calls=[]
        def handler(request):
            calls.append(request);raise ProviderError(headers={'Retry-After': '3'})
        with self.assertRaises(RunCancelled): self.invoke(handler, Activity(cancel_at=.2))
        self.assertEqual(len(calls), 1)
        self.assertLessEqual(self.now, .3)
        self.assertEqual(runtime._gate('PRIVATE-KEY', 'test-model').active, 0)

    def test_shared_admission_spaces_requests_and_caps_inflight(self):
        gate=runtime._gate('PRIVATE-KEY','test-model')
        gate.acquire(Activity(), 'lead', runtime._WaitBudget())
        gate.acquire(Activity(), 'site-evidence', runtime._WaitBudget())
        self.assertEqual(gate.active, 2)
        self.assertAlmostEqual(self.now,.6)
        with self.assertRaises(RunCancelled):
            gate.acquire(Activity(cancel_at=.8), 'domain-analysis', runtime._WaitBudget())
        self.assertEqual(gate.active, 2)
        gate.release();gate.release()
        self.assertEqual(gate.active, 0)

    def test_retry_after_date_and_diagnostic_header_validation(self):
        with patch.object(runtime, 'time', return_value=1000):
            stamp=datetime.fromtimestamp(1005,tz=timezone.utc).strftime('%a, %d %b %Y %H:%M:%S GMT')
            self.assertEqual(runtime.classify_error(ProviderError(headers={'Retry-After':stamp}))['retry_after'], 5)
        diagnostic=runtime.classify_error(ProviderError(code='PRIVATE-KEY-123',headers={
            'x-ratelimit-limit-tokens':'NaN','x-ratelimit-reset-requests':'PRIVATE-HEADER','x-ratelimit-limit-requests':'7200'}))
        self.assertIsNone(diagnostic['error_code'])
        self.assertEqual(diagnostic['limits'],{'x-ratelimit-limit-requests':7200})
