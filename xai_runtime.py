"""Cancellable, bounded xAI model-request pacing and transient retries.

The coordinator is shared by site/scout agents for a credential and model. Only
an individual failed model request is retried; tools and agent graphs are not.
No prompts, credentials, provider error text or raw headers are logged.
"""
from dataclasses import dataclass, field
from datetime import timezone
from email.utils import parsedate_to_datetime
from hashlib import sha256
import json
import logging
import math
import random
import re
from threading import Lock
from time import monotonic, sleep, time

MAX_IN_FLIGHT = 2
MIN_INTERVAL_SECONDS = 0.6
MAX_ATTEMPTS = 3
MAX_WAIT_SECONDS = 60.0
WAIT_SLICE_SECONDS = 0.1
_LOG = logging.getLogger(__name__)
_GATES = {}
_GATES_LOCK = Lock()


class ModelRateLimitWaitError(RuntimeError):
    """Waiting would exceed this model call's bounded capacity-wait budget."""
    def __init__(self):
        super().__init__('Model capacity is temporarily unavailable within this request budget. Retry later; saved work is retained.')
        self.provider_diagnostic = {'category': 'capacity_wait', 'status': None, 'retry_after': None}


def _retry_after(headers):
    value = next((value for key, value in (headers or {}).items()
                  if str(key).lower() == 'retry-after'), None)
    if not isinstance(value, str) or len(value) > 128:
        return None
    try:
        seconds = float(value)
    except ValueError:
        try:
            stamp = parsedate_to_datetime(value)
            if stamp.tzinfo is None:
                stamp = stamp.replace(tzinfo=timezone.utc)
            seconds = stamp.timestamp() - time()
        except (ValueError, TypeError, OverflowError):
            return None
    return max(0.0, seconds) if math.isfinite(seconds) else None


def safe_limit_headers(headers):
    """Numerical rate-limit metadata only, never general response headers."""
    allowed = {f'x-ratelimit-{kind}-{unit}' for kind in ('limit', 'remaining', 'reset')
               for unit in ('requests', 'tokens')}
    values = {}
    for key, raw in (headers or {}).items():
        key = str(key).lower()
        if key not in allowed or not isinstance(raw, str) or len(raw) > 80:
            continue
        try:
            value = float(raw)
        except ValueError:
            if not re.fullmatch(r'(?:\d{1,8}(?:\.\d{1,6})?(?:ms|s|m|h|d))+', raw):
                continue
            value = sum(float(amount) * {'ms': .001, 's': 1, 'm': 60, 'h': 3600, 'd': 86400}[unit]
                        for amount, unit in re.findall(r'(\d+(?:\.\d+)?)(ms|s|m|h|d)', raw))
        if math.isfinite(value) and 0 <= value <= 1e12:
            values[key] = value
    return values


def classify_error(error):
    """Return allowlisted diagnostics; inspect provider text only locally."""
    response = getattr(error, 'response', None)
    status = getattr(error, 'status_code', None) or getattr(response, 'status_code', None)
    status = status if type(status) is int and 100 <= status <= 599 else None
    body = getattr(error, 'body', None)
    if isinstance(body, dict):
        body = body.get('error', body)
    if isinstance(body, dict):
        code = str(body.get('code', '')).lower()
        kind = str(body.get('type', '')).lower()
        message = str(body.get('message', ''))[:4096].lower()
    else:
        code, kind, message = '', '', str(body or '')[:4096].lower()
    fatal_codes = {'insufficient_quota', 'billing_hard_limit_reached',
                   'billing_not_active', 'insufficient_credits', 'credits_exhausted',
                   'spending_limit_reached', 'payment_required'}
    fatal_phrases = ('insufficient credits', 'out of credits', 'no credits', 'credits exhausted',
                     'spending limit', 'spend limit', 'billing limit', 'billing is not active',
                     'monthly budget', 'payment required')
    name = type(error).__name__.lower()
    if status == 402 or code in fatal_codes or kind in fatal_codes or any(value in message for value in fatal_phrases):
        category = 'quota_or_billing'
    elif status == 401 or code in {'invalid_api_key', 'authentication_error'}:
        category = 'authentication'
    elif status == 403:
        category = 'permission'
    elif status == 429 or 'ratelimit' in name:
        category = 'rate_limit'
    elif status is not None and status >= 500:
        category = 'server'
    elif status == 408 or isinstance(error, (ConnectionError, TimeoutError)) or any(
            word in name for word in ('connectionerror', 'timeouterror')):
        category = 'transport'
    else:
        category = 'other'
    return {'category': category, 'status': status,
            'error_code': code if re.fullmatch(r'[a-z_]{1,64}', code) else None,
            'retry_after': _retry_after(getattr(response, 'headers', None)),
            'limits': safe_limit_headers(getattr(response, 'headers', None))}


@dataclass
class _WaitBudget:
    used: float = 0.0

    def wait(self, seconds, activity):
        if seconds > MAX_WAIT_SECONDS - self.used + 1e-9:
            raise ModelRateLimitWaitError()
        remaining = seconds
        while remaining > 1e-9:
            activity.check()
            step = min(WAIT_SLICE_SECONDS, remaining)
            before = monotonic()
            sleep(step)
            # Charge actual elapsed time, including scheduler delay, to the bound.
            elapsed = max(step, monotonic() - before)
            self.used += elapsed
            if self.used > MAX_WAIT_SECONDS + 1e-6:
                raise ModelRateLimitWaitError()
            remaining -= elapsed
        activity.check()


@dataclass
class _Gate:
    lock: Lock = field(default_factory=Lock)
    active: int = 0
    next_start: float = 0.0
    cooldown: float = 0.0

    def acquire(self, activity, specialist, budget):
        announced = False
        while True:
            activity.check()
            with self.lock:
                now = monotonic()
                ready = max(self.next_start, self.cooldown)
                if self.active < MAX_IN_FLIGHT and now + 1e-9 >= ready:
                    self.active += 1
                    self.next_start = now + MIN_INTERVAL_SECONDS
                    return
                delay = max(0.0, ready - now)
                full = self.active >= MAX_IN_FLIGHT
            if not announced:
                activity.event(specialist, 'model-capacity', 'waiting',
                               'Waiting briefly for shared model capacity; the investigation remains active.')
                announced = True
            # Check the full cooldown against the budget rather than waiting a
            # minute for a provider Retry-After that already exceeds our budget.
            if delay > MAX_WAIT_SECONDS - budget.used + 1e-9:
                raise ModelRateLimitWaitError()
            budget.wait(min(WAIT_SLICE_SECONDS, delay) if delay > 0 else WAIT_SLICE_SECONDS if full else 0.001, activity)

    def release(self):
        with self.lock:
            self.active -= 1

    def defer(self, seconds):
        with self.lock:
            self.cooldown = max(self.cooldown, monotonic() + seconds)


def _gate(key, model_name):
    # Raw credentials are never stored in coordination state or diagnostics.
    identity = (sha256(key.encode()).digest(), model_name)
    with _GATES_LOCK:
        return _GATES.setdefault(identity, _Gate())


def _request_counts(request):
    messages = list(getattr(request, 'messages', None) or [])
    system = getattr(request, 'system_message', None)
    if system is not None:
        messages.append(system)
    chars = 0
    for message in messages:
        content = getattr(message, 'content', '')
        chars += len(content) if isinstance(content, str) else len(json.dumps(content, default=str))
    return {'message_count': len(messages), 'request_chars': chars,
            'tool_count': len(getattr(request, 'tools', None) or [])}


def _usage(response):
    values = {}
    for message in getattr(response, 'result', []) or []:
        usage = getattr(message, 'usage_metadata', None) or {}
        for field in ('input_tokens', 'output_tokens', 'total_tokens'):
            value = usage.get(field)
            if type(value) is int and value >= 0:
                values[field] = values.get(field, 0) + value
    for message in getattr(response, 'result', []) or []:
        values['limits'] = safe_limit_headers((getattr(message, 'response_metadata', None) or {}).get('headers', {}))
    return values


def _record(activity, diagnostic):
    # Bounded numeric diagnostics are safe to inspect locally. They are not
    # agent context and contain no model/source prose or provider identifiers.
    lock = getattr(activity, 'lock', None)
    if lock is None:
        return
    with lock:
        rows = getattr(activity, 'model_diagnostics', [])
        rows.append(diagnostic)
        activity.model_diagnostics = rows[-100:]
        aggregate = getattr(activity, 'model_usage', {
            'attempts': 0, 'retries': 0, 'input_tokens': 0, 'output_tokens': 0,
            'total_tokens': 0, 'peak_request_chars': 0, 'last_error': None})
        if 'attempt' in diagnostic:
            aggregate['attempts'] += 1
            aggregate['retries'] += int(diagnostic['attempt'] > 1)
        for field in ('input_tokens', 'output_tokens', 'total_tokens'):
            aggregate[field] += diagnostic.get(field, 0)
        aggregate['peak_request_chars'] = max(aggregate['peak_request_chars'], diagnostic.get('request_chars', 0))
        if diagnostic.get('category'):
            aggregate['last_error'] = {key: diagnostic.get(key) for key in
                                       ('category', 'status', 'error_code', 'retry_after', 'limits')}
        activity.model_usage = aggregate
    log = _LOG.warning if diagnostic.get('category') else _LOG.info
    log('Model request diagnostic %s', json.dumps(diagnostic, sort_keys=True))


def invoke_model(handler, request, *, activity, specialist, model_name, key):
    """Return the handler response after at most three transient-only attempts."""
    gate, budget = _gate(key, model_name), _WaitBudget()
    counts = _request_counts(request)
    for attempt in range(MAX_ATTEMPTS):
        try:
            gate.acquire(activity, specialist, budget)
        except ModelRateLimitWaitError as error:
            _record(activity, {**counts, **error.provider_diagnostic, 'wait_ms': round(budget.used * 1000)})
            raise
        started = monotonic()
        response, failure = None, None
        try:
            activity.check()
            response = handler(request)
            activity.check()
        except Exception as error:
            failure = error
        finally:
            gate.release()
        duration = max(0, round((monotonic() - started) * 1000))
        if failure is None:
            _record(activity, {**counts, 'attempt': attempt + 1, 'status': 'success',
                               'duration_ms': duration, 'wait_ms': round(budget.used * 1000), **_usage(response)})
            # Only the numeric allowlist above may enter durable diagnostics.
            # Do not let response cookies or other raw headers enter graph checkpoints.
            for message in getattr(response, 'result', []) or []:
                metadata = getattr(message, 'response_metadata', None)
                if isinstance(metadata, dict):
                    metadata.pop('headers', None)
            return response
        # Cancellation must never be converted into a retry or provider error.
        activity.check()
        diagnostic = classify_error(failure)
        failure.provider_diagnostic = diagnostic
        _record(activity, {**counts, **diagnostic, 'attempt': attempt + 1,
                           'duration_ms': duration, 'wait_ms': round(budget.used * 1000)})
        transient = diagnostic['category'] in ('rate_limit', 'server', 'transport')
        if not transient:
            raise failure
        delay = max(diagnostic['retry_after'] or 0.0, min(8.0, 2.0 ** (attempt + 1)) + random.uniform(0, 0.4))
        # Shared cooldown covers other specialists and scouting runs too.
        gate.defer(delay)
        if attempt + 1 >= MAX_ATTEMPTS:
            raise failure
        activity.event(specialist, 'model-capacity', 'retrying',
                       f'Model service is temporarily busy. Retrying this request after a short pause (attempt {attempt + 2} of {MAX_ATTEMPTS}).')
    raise AssertionError('Unreachable model retry state.')
