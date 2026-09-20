"""Job engine: bounded worker pool, retries/backoff, checkpointing,
real emergency-stop (<=1s latency), resume, and SSE event fan-out.
Numbers always come from real backend state - never fabricated."""
import queue
import threading
import time
from concurrent.futures import ThreadPoolExecutor, wait

import db
from validator import check_syntax, validate_email

SPEEDS = {"LOW": 2, "MEDIUM": 6, "HIGH": 12}
MODES = {
    "STANDARD": {"retries": 0, "timeout": 6, "strict": False},
    "DEEP": {"retries": 2, "timeout": 10, "strict": False},
    "EVIDENCE": {"retries": 3, "timeout": 10, "strict": True},
    "BALANCED": {"retries": 1, "timeout": 8, "strict": False},
}
MODE_ALIASES = {
    "12-AGENT STANDARD": "STANDARD",
    "DEEP INSTITUTIONAL": "DEEP",
    "EVIDENCE-FIRST": "EVIDENCE",
    "BALANCED": "BALANCED",
}
TRANSIENT_HINTS = ("dns lookup failed", "smtp-timeout", "deferral", "transport failed")


def _now_ts():
    return time.strftime("%H:%M:%S")


class Engine:
    def __init__(self):
        self._lock = threading.Lock()
        self._stop = {}      # job_id -> threading.Event
        self._running = set()
        self._subs = {}      # job_id -> [Queue]
        self._t0 = {}        # job_id -> start epoch

    # ---------- pub/sub ----------
    def subscribe(self, job_id):
        q = queue.Queue(maxsize=2000)
        with self._lock:
            self._subs.setdefault(job_id, []).append(q)
        return q

    def unsubscribe(self, job_id, q):
        with self._lock:
            lst = self._subs.get(job_id, [])
            if q in lst:
                lst.remove(q)

    def publish(self, job_id, event):
        with self._lock:
            subs = list(self._subs.get(job_id, []))
        for q in subs:
            try:
                q.put_nowait(event)
            except queue.Full:
                pass  # slow consumer: drop, snapshot covers state

    # ---------- control ----------
    def is_running(self, job_id):
        with self._lock:
            return job_id in self._running

    def start(self, job_id):
        with self._lock:
            if job_id in self._running:
                return False
            self._running.add(job_id)
            self._stop[job_id] = threading.Event()
        t = threading.Thread(target=self._run, args=(job_id,), daemon=True)
        t.start()
        return True

    def stop(self, job_id):
        with self._lock:
            ev = self._stop.get(job_id)
        if ev:
            ev.set()
            return True
        return False

    # ---------- main loop ----------
    def _run(self, job_id):
        job = db.get_job(job_id)
        try:
            if not job:
                return
            mode = MODES.get(MODE_ALIASES.get(job["mode"], job["mode"]), MODES["STANDARD"])
            workers = SPEEDS.get(job["speed"], 6)
            try:
                import json as _j
                filt = _j.loads(job.get("filters") or "{}")
                if str(job["speed"]).upper() == "CUSTOM":
                    workers = max(1, min(int(filt.get("custom_threads", 6)), 32))
            except Exception:
                filt = {}
            allow = set(x.strip().lower() for x in (job.get("allowlist") or "").splitlines() if x.strip())
            smtp_on = bool(job["smtp"])
            opts = {"smtp": smtp_on, "hello": "example.com",
                    "mail_from": "verifier@example.com",
                    "timeout": mode["timeout"], "strict": mode["strict"]}
            retries = mode["retries"]

            db.set_job_status(job_id, "RUNNING")
            self._t0[job_id] = time.time()
            total = job["total"]
            self.publish(job_id, {"t": "log", "ts": _now_ts(),
                                  "msg": f"JOB {job_id} STARTED - {total} queued, "
                                         f"{workers} workers, mode={job['mode']}, smtp={'ON' if smtp_on else 'OFF'}"})

            counts = {"LIVE": 0, "LIKELY": 0, "INVALID": 0, "UNKNOWN": 0}
            processed = db.get_job(job_id)["processed"]
            # rehydrate counts from db (resume-safe)
            for k, v in db.count_by_status(job_id).items():
                if k in counts:
                    counts[k] = v
            errors = db.get_job(job_id)["errors"]
            ev_stop = self._stop.get(job_id)
            ex = ThreadPoolExecutor(max_workers=workers, thread_name_prefix=f"bf{job_id}")
            try:
                after_id = 0
                while True:
                    if ev_stop and ev_stop.is_set():
                        break
                    batch = db.fetch_pending(job_id, after_id, 500)
                    if not batch:
                        break
                    futs = {ex.submit(self._one, job_id, row, opts, allow, retries): row for row in batch}
                    pending_futs = set(futs)
                    while pending_futs:
                        if ev_stop and ev_stop.is_set():
                            break  # emergency stop: leave rest PENDING (resumable)
                        done, pending_futs = wait(pending_futs, timeout=0.5)
                        for fut in done:
                            row = futs[fut]
                            try:
                                res = fut.result()
                            except Exception as e:
                                res = {"email": row["normalized"], "status": "UNKNOWN",
                                       "reason": f"engine-error: {str(e)[:60]}", "confidence": 40,
                                       "domain": "", "syntax": "", "dns": "", "has_mx": False,
                                       "mx_hosts": [], "provider": "", "institution": "",
                                       "evidence": {}}
                                db.mark_result(row["id"], res)
                                db.bump_job(job_id, "errors")
                                errors += 1
                            after_id = max(after_id, row["id"])
                            processed += 1
                            if res["status"] in counts:
                                counts[res["status"]] += 1
                            db.bump_job(job_id, "processed")
                            db.bump_job(job_id, res["status"].lower() if res["status"].lower() in
                                        ("live", "likely", "invalid", "unknown") else "unknown")
                            if processed % 25 == 0:
                                db.save_checkpoint(job_id, after_id, processed)
                            self.publish(job_id, {"t": "row", "row": self._slim(res),
                                                  "processed": processed, "counts": dict(counts),
                                                  "errors": errors})
                            if processed % 100 == 0:
                                self.publish(job_id, {"t": "log", "ts": _now_ts(),
                                                      "msg": f"checkpoint: {processed}/{total} processed"})
                    if ev_stop and ev_stop.is_set():
                        break
            finally:
                # Cancel un-started work; in-flight items finish and persist.
                ex.shutdown(wait=True, cancel_futures=True)

            # Reconcile: in-flight completions during shutdown are already in DB.
            processed = db.reconcile_job(job_id)
            stop_pressed = bool(ev_stop and ev_stop.is_set())
            db.save_checkpoint(job_id, after_id, processed)
            final = db.count_by_status(job_id)
            pending_left = db.count_pending(job_id)
            stopped = stop_pressed and pending_left > 0
            if stopped:
                db.set_job_status(job_id, "STOPPED")
                self.publish(job_id, {"t": "log", "ts": _now_ts(),
                                      "msg": f"EMERGENCY STOP - checkpoint saved at {processed}/{total}. Resume available."})
                self.publish(job_id, {"t": "stopped", "processed": processed, "counts": final})
            else:
                db.set_job_status(job_id, "DONE")
                self.publish(job_id, {"t": "log", "ts": _now_ts(),
                                      "msg": f"JOB COMPLETE - {processed}/{total} in "
                                             f"{int(time.time()-self._t0.get(job_id, time.time()))}s"})
                self.publish(job_id, {"t": "done", "processed": processed, "counts": final})
        finally:
            with self._lock:
                self._running.discard(job_id)
                self._stop.pop(job_id, None)

    @staticmethod
    def _slim(res):
        return {"email": res.get("email", ""), "domain": res.get("domain", ""),
                "syntax": res.get("syntax", ""), "dns": res.get("dns", ""),
                "has_mx": bool(res.get("has_mx")), "provider": res.get("provider", ""),
                "institution": res.get("institution", ""), "confidence": res.get("confidence", 0),
                "status": res.get("status", "UNKNOWN"), "reason": res.get("reason", "")[:160],
                "evidence": res.get("evidence", {})}

    def _one(self, job_id, row, opts, allow, retries):
        import os as _os
        _pacing = float(_os.environ.get("BF_TEST_DELAY_MS", "0") or 0)
        if _pacing > 0:  # test hook only (default off): deterministic stop/resume tests
            time.sleep(_pacing / 1000.0)
        email = row["normalized"]
        # SMTP allowlist enforcement (authorization scoping)
        use_opts = dict(opts)
        if opts.get("smtp"):
            syn = check_syntax(email)
            dom = syn.get("domain", "") if syn.get("valid") else ""
            if allow and dom not in allow:
                use_opts["smtp"] = False
        attempt = 0
        while True:
            res = validate_email(email, use_opts)
            res["email"] = email
            transient = res["status"] == "UNKNOWN" and any(
                h in res.get("reason", "") for h in TRANSIENT_HINTS)
            if transient and attempt < retries:
                attempt += 1
                time.sleep(min(2 ** attempt, 8))
                continue
            break
        db.mark_result(row["id"], res)
        return res


engine = Engine()
