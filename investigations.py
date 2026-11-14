"""Bounded, local-only investigation jobs. All state expires with the server."""
import copy
import os
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone

from evidence import build_evidence, fingerprint, GUIDANCE
from planner import Budget, PROMPT_VERSION, RunStopped, answer_followup, investigate

TERMINAL = {"complete", "partial", "failed", "cancelled"}


class JobError(Exception):
    def __init__(self, status, message):
        self.status = status
        super().__init__(message)


class Investigations:
    def __init__(self, image_loader, runner=investigate):
        self.image_loader, self.runner = image_loader, runner
        self.jobs, self.cache = {}, {}
        self.lock = threading.RLock()
        self.pool = ThreadPoolExecutor(max_workers=2, thread_name_prefix="investigation")
        self.slots = threading.BoundedSemaphore(2)

    def _get(self, id_, site_name):
        job = self.jobs.get(id_)
        if job and job["status"] in TERMINAL and not job["followup_running"] and time.monotonic()-job["created_clock"] > 3600:
            self.jobs.pop(id_, None)
            job = None
        if job is None or job["site"]["name"] != site_name:
            raise JobError(404, "This investigation is unavailable. Start a new analysis.")
        return job

    def _prune(self):
        expired = [id_ for id_, j in self.jobs.items()
                   if j["status"] in TERMINAL and not j["followup_running"] and time.monotonic()-j["created_clock"] > 3600]
        for id_ in expired:
            self.jobs.pop(id_, None)
        self.cache = {k: id_ for k, id_ in self.cache.items() if id_ in self.jobs}

    def start(self, site, refresh=False):
        key = os.getenv("GROK_API_KEY", "").strip()
        if not key:
            raise JobError(503, "Add the Grok key to the local .env and restart the server.")
        evidence = build_evidence(site)
        model = os.getenv("GROK_MODEL") or "grok-4.3"
        cache_key = fingerprint([site["name"], evidence["source_version"], model, PROMPT_VERSION, GUIDANCE])
        with self.lock:
            self._prune()
            cached = self.jobs.get(self.cache.get(cache_key))
            if cached and (cached["status"] not in TERMINAL or (not refresh and cached["status"] == "complete")):
                return self.snapshot(cached["id"], site["name"]) | {"cached": cached["status"] == "complete"}
            if len(self.jobs) >= 24:
                oldest = next((id_ for id_, j in self.jobs.items() if j["status"] in TERMINAL and not j["followup_running"]), None)
                if oldest:
                    del self.jobs[oldest]
                else:
                    raise JobError(429, "Investigations are still running. Try again shortly.")
            if not self.slots.acquire(blocking=False):
                raise JobError(429, "Two analyses are already running. Wait or cancel one first.")
            id_ = uuid.uuid4().hex
            job = {"id": id_, "site": dict(site), "evidence": evidence, "model": model,
                   "created_at": datetime.now(timezone.utc).isoformat(), "created_clock": time.monotonic(),
                   "status": "running", "events": [], "artifacts": {}, "report": None,
                   "message": "Gathering crash evidence", "cancelled": threading.Event(),
                   "followups": [], "followup_running": False, "cache_key": cache_key}
            def emit(role, text, kind):
                with self.lock:
                    if job["status"] == "cancelled":
                        return
                    job["events"].append({"role": role, "text": text, "kind": kind,
                                          "seconds": round(time.monotonic()-job["created_clock"], 1)})
                    job["events"] = job["events"][-100:]
                    job["message"] = text
            job["emit"] = emit
            job["budget"] = Budget(job["cancelled"], emit)
            self.jobs[id_] = job
            self.cache[cache_key] = id_
            emit("evidence", "Loaded CHP records; LAPD heat-map totals remain separate", "tool")
            self.pool.submit(self._run, job, key)
            return self.snapshot(id_, site["name"])

    def _run(self, job, key):
        try:
            report = self.runner(key, job["model"], job["evidence"], self.image_loader,
                                 job["budget"], job["emit"], job["artifacts"])
            with self.lock:
                if job["cancelled"].is_set():
                    if job["status"] != "partial":
                        job["status"] = "cancelled"
                    return
                if not report:
                    raise ValueError("No validated report")
                job["report"] = report
                visual_available = "V-aerial" in job["evidence"]["sources"]
                job["status"] = "complete" if visual_available and not job["evidence"]["unavailable"] else "partial"
                job["message"] = "Investigation complete" if job["status"] == "complete" else "Report ready with missing-source limitations"
        except RunStopped as error:
            with self.lock:
                if job["status"] != "partial":
                    job["status"] = "cancelled" if job["cancelled"].is_set() else "partial"
                    job["message"] = str(error)
        except Exception:
            # Never expose provider exceptions, request headers, or raw prompts.
            with self.lock:
                if job["status"] != "partial":
                    job["status"] = "cancelled" if job["cancelled"].is_set() else "partial" if job["artifacts"] else "failed"
                    job["message"] = "Analysis could not finish. Available evidence is below; retry to start a new run."
        finally:
            self.slots.release()

    def latest_report(self, site_name):
        """Most recent accepted report for a site, for the design chat's context."""
        with self.lock:
            for job in reversed(list(self.jobs.values())):
                if job["site"]["name"] == site_name and job["report"]:
                    return copy.deepcopy(job["report"])
        return None

    def snapshot(self, id_, site_name):
        with self.lock:
            job = self._get(id_, site_name)
            elapsed = time.monotonic()-job["created_clock"]
            if job["status"] == "running" and time.monotonic() > job["budget"].deadline:
                job["status"] = "partial"
                job["cancelled"].set()
                job["message"] = "Time limit reached. Available evidence is retained."
            return {"id": id_, "site": job["site"]["name"], "status": job["status"],
                    "created_at": job["created_at"], "message": job["message"], "elapsed": round(elapsed),
                    "events": copy.deepcopy(job["events"]), "artifacts": copy.deepcopy(job["artifacts"].copy()),
                    "report": copy.deepcopy(job["report"]), "usage": job["budget"].usage(),
                    "sources": copy.deepcopy(job["evidence"]["sources"].copy()),
                    "period": job["evidence"]["period"], "retrieved_at": job["evidence"]["retrieved_at"],
                    "followups": copy.deepcopy(job["followups"]), "followup_running": job["followup_running"]}

    def cancel(self, id_, site_name):
        with self.lock:
            job = self._get(id_, site_name)
            if job["status"] not in TERMINAL or job["followup_running"]:
                job["cancelled"].set()
                job["status"] = "cancelled"
                job["message"] = "Cancelled. An already-sent provider request may still finish; no further calls will start."
            return self.snapshot(id_, site_name)

    def followup(self, id_, site_name, question):
        if not isinstance(question, str) or not 1 <= len(question.strip()) <= 1200:
            raise JobError(400, "Enter a question of up to 1200 characters.")
        with self.lock:
            job = self._get(id_, site_name)
            if job["status"] not in {"complete", "partial"} or not job["report"] or job["cancelled"].is_set():
                raise JobError(409, "Finish an investigation before asking a follow-up.")
            if job["followup_running"]:
                raise JobError(409, "A follow-up is already running.")
            if len(job["followups"]) >= 5:
                raise JobError(429, "This investigation supports five follow-up questions. Start a fresh analysis for more.")
            if not self.slots.acquire(blocking=False):
                raise JobError(429, "Two analyses are running. Try again shortly.")
            job["followup_running"] = True
            item = {"question": question.strip(), "status": "running"}
            job["followups"].append(item)
            # Follow-ups each have a single call and a short deadline. They are
            # accounted separately and bounded to five per investigation.
            budget = Budget(job["cancelled"], job["emit"], max_calls=1, seconds=45)
            self.pool.submit(self._followup, job, item, budget)
            return self.snapshot(id_, site_name)

    def _followup(self, job, item, budget):
        try:
            result = answer_followup(os.getenv("GROK_API_KEY", ""), job["model"], job["evidence"],
                                     job["report"], job["followups"][:-1], item["question"], budget)
            with self.lock:
                if job["cancelled"].is_set():
                    item.update(status="cancelled")
                else:
                    item.update(status="complete", **result)
        except Exception:
            with self.lock:
                item.update(status="cancelled" if job["cancelled"].is_set() else "failed",
                            answer="The follow-up could not be completed. No new conclusion was added.")
        finally:
            with self.lock:
                item["usage"] = budget.usage()
                job["followup_running"] = False
            self.slots.release()
