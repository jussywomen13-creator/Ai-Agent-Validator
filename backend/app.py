"""HABIB BLACKFORGE - Flask API: jobs, streaming, exports, cookie checks.
Rate limits, size limits, bounded concurrency, safe files, no raw-input logging."""
import csv
import io
import json
import time
from collections import defaultdict, deque
from functools import wraps

from flask import Flask, Response, jsonify, request, send_from_directory, stream_with_context

import db
from cookieval import validate_cookie_file
from validator import check_syntax, is_institutional, parse_input
from worker import engine

app = Flask(__name__, static_folder="static", static_url_path="")
app.config["MAX_CONTENT_LENGTH"] = 12 * 1024 * 1024  # 12 MB uploads max
app.config["JSON_SORT_KEYS"] = False

MAX_EMAILS_PER_JOB = 200000
STATUSES = {"ALL", "LIVE", "LIKELY", "INVALID", "UNKNOWN", "PENDING"}
PROVIDERS = {"ALL", "GOOGLE_WORKSPACE", "MICROSOFT_365", "YAHOO", "ZOHO", "PROTON",
             "ICLOUD", "YANDEX", "FASTMAIL", "CUSTOM_PRIVATE", "DISPOSABLE", ""}

# ---------------- rate limiting (in-memory) ----------------
_hits = defaultdict(deque)
_hits_lock = __import__("threading").Lock()


def rate_limit(per_min):
    def deco(fn):
        @wraps(fn)
        def wrapper(*a, **kw):
            ip = (request.headers.get("X-Forwarded-For", "") or request.remote_addr or "?").split(",")[0].strip()
            now = time.time()
            with _hits_lock:
                dq = _hits[(fn.__name__, ip)]
                while dq and now - dq[0] > 60:
                    dq.popleft()
                if len(dq) >= per_min:
                    return jsonify({"error": "rate-limited, slow down"}), 429
                dq.append(now)
            return fn(*a, **kw)
        return wrapper
    return deco


@app.after_request
def secure_headers(resp):
    resp.headers["X-Content-Type-Options"] = "nosniff"
    resp.headers["X-Frame-Options"] = "DENY"
    resp.headers["Referrer-Policy"] = "no-referrer"
    resp.headers["Content-Security-Policy"] = "default-src 'self'; style-src 'self' 'unsafe-inline'"
    return resp


@app.errorhandler(413)
def too_large(_e):
    return jsonify({"error": "upload too large (max 12 MB)"}), 413


# ---------------- frontend ----------------
@app.get("/")
def index():
    try:
        return send_from_directory(app.static_folder, "index.html")
    except Exception:
        return jsonify({"app": "HABIB BLACKFORGE API", "status": "ok",
                        "hint": "Build the frontend (frontend/) into backend/static/"})


@app.get("/<path:fname>")
def static_files(fname):
    if ".." in fname or fname.startswith("/"):
        return jsonify({"error": "bad path"}), 400
    try:
        return send_from_directory(app.static_folder, fname)
    except Exception:
        try:
            return send_from_directory(app.static_folder, "index.html")
        except Exception:
            return jsonify({"error": "not found"}), 404


@app.get("/api/health")
def health():
    return jsonify({"ok": True, "ts": int(time.time())})


# ---------------- parse preview (counts only) ----------------
@app.post("/api/parse-preview")
@rate_limit(120)
def parse_preview():
    data = request.get_json(silent=True) or {}
    text = data.get("text", "")
    if len(text) > 11 * 1024 * 1024:
        return jsonify({"error": "text too large"}), 413
    parsed = parse_input(text, MAX_EMAILS_PER_JOB)
    bad = 0
    for u in parsed["unique"][:20000]:
        if not check_syntax(u["normalized"])["valid"]:
            bad += 1
    # counts only - never log or echo the addresses
    app.logger.info("parse-preview unique=%d dupes=%d", len(parsed["unique"]), parsed["dupes"])
    return jsonify({"input": len(parsed["unique"]) + parsed["dupes"],
                    "unique": len(parsed["unique"]), "dupes": parsed["dupes"],
                    "invalid_syntax_sample": bad, "truncated": parsed["truncated"]})


# ---------------- jobs ----------------
def _read_input_text():
    """Accept JSON {text} or multipart file. Returns (text, source)."""
    if request.content_type and "multipart/form-data" in request.content_type:
        f = request.files.get("file")
        if not f:
            return "", "none"
        data = f.read(11 * 1024 * 1024 + 1)
        if len(data) > 11 * 1024 * 1024:
            raise ValueError("file too large (max ~11 MB)")
        return data.decode("utf-8", "replace"), "file"
    data = request.get_json(silent=True) or {}
    text = data.get("text", "")
    if len(text) > 11 * 1024 * 1024:
        raise ValueError("text too large")
    return text, "text"


@app.post("/api/jobs")
@rate_limit(20)
def create_job():
    try:
        if request.content_type and "multipart/form-data" in request.content_type:
            form = request.form
            text, _ = _read_input_text()
            payload = {"name": form.get("name", ""), "mode": form.get("mode", "STANDARD"),
                       "speed": form.get("speed", "MEDIUM"),
                       "custom_threads": form.get("custom_threads", "6"),
                       "focus": form.get("focus", "ALL"),
                       "smtp": form.get("smtp", "false") == "true",
                       "allowlist": form.get("allowlist", "")}
        else:
            payload = request.get_json(silent=True) or {}
            text = payload.get("text", "")
        mode = str(payload.get("mode", "STANDARD"))[:32]
        speed = str(payload.get("speed", "MEDIUM"))[:16].upper()
        if speed not in ("LOW", "MEDIUM", "HIGH", "CUSTOM"):
            speed = "MEDIUM"
        try:
            custom_threads = max(1, min(int(payload.get("custom_threads", 6)), 32))
        except (ValueError, TypeError):
            custom_threads = 6
        focus = str(payload.get("focus", "ALL"))[:16].upper()
        if focus not in ("ALL", "GOOGLE", "MICROSOFT", "EDU"):
            focus = "ALL"
        smtp = bool(payload.get("smtp"))
        allowlist = str(payload.get("allowlist", ""))[:2000]
        name = str(payload.get("name", ""))[:80]

        parsed = parse_input(text, MAX_EMAILS_PER_JOB)
        unique = parsed["unique"]
        filtered_out = 0
        if focus == "EDU":
            # Institutional-pattern pre-filter actually narrows the queue.
            kept = []
            for u in unique:
                syn = check_syntax(u["normalized"])
                if syn["valid"] and is_institutional(syn["domain"]):
                    kept.append(u)
                else:
                    filtered_out += 1
            unique = kept
        if not unique:
            return jsonify({"error": "no emails to queue (empty input or EDU filter removed all)"}), 400

        job_id = db.create_job(name, mode, speed,
                               {"focus": focus, "custom_threads": custom_threads},
                               smtp, allowlist, len(unique), parsed["dupes"])
        for i in range(0, len(unique), 1000):
            chunk = [(u["original"][:254], u["normalized"][:254])
                     for u in unique[i:i + 1000]]
            db.insert_emails(job_id, chunk)
        app.logger.info("job=%d created total=%d dupes=%d filtered=%d smtp=%s",
                        job_id, len(unique), parsed["dupes"], filtered_out, smtp)
        return jsonify({"job_id": job_id, "total": len(unique),
                        "dupes": parsed["dupes"], "filtered_out": filtered_out,
                        "truncated": parsed["truncated"]})
    except ValueError as e:
        return jsonify({"error": str(e)}), 413
    except Exception as e:
        app.logger.exception("create-job failed")
        return jsonify({"error": f"create failed: {str(e)[:120]}"}), 500


@app.get("/api/jobs")
@rate_limit(120)
def jobs_list():
    jobs = db.list_jobs()
    for j in jobs:
        j["running"] = engine.is_running(j["id"])
    return jsonify({"jobs": jobs})


@app.get("/api/jobs/<int:job_id>")
@rate_limit(200)
def job_detail(job_id):
    job = db.get_job(job_id)
    if not job:
        return jsonify({"error": "job not found"}), 404
    job["running"] = engine.is_running(job_id)
    job["counts"] = db.count_by_status(job_id)
    return jsonify({"job": job})


@app.post("/api/jobs/<int:job_id>/start")
@rate_limit(60)
def job_start(job_id):
    if not db.get_job(job_id):
        return jsonify({"error": "job not found"}), 404
    if db.count_pending(job_id) == 0:
        return jsonify({"error": "nothing pending (job already complete?)"}), 400
    if not engine.start(job_id):
        return jsonify({"error": "job already running"}), 409
    return jsonify({"started": True})


@app.post("/api/jobs/<int:job_id>/stop")
@rate_limit(60)
def job_stop(job_id):
    if not engine.stop(job_id):
        return jsonify({"error": "job not running"}), 409
    return jsonify({"stopped": True})


@app.post("/api/jobs/<int:job_id>/resume")
@rate_limit(60)
def job_resume(job_id):
    job = db.get_job(job_id)
    if not job:
        return jsonify({"error": "job not found"}), 404
    if job["status"] not in ("STOPPED", "CREATED", "DONE"):
        return jsonify({"error": f"cannot resume from {job['status']}"}), 400
    if db.count_pending(job_id) == 0:
        return jsonify({"error": "nothing pending to resume"}), 400
    if not engine.start(job_id):
        return jsonify({"error": "job already running"}), 409
    return jsonify({"resumed": True})


@app.delete("/api/jobs/<int:job_id>")
@rate_limit(60)
def job_delete(job_id):
    if engine.is_running(job_id):
        return jsonify({"error": "stop the job first"}), 409
    db.delete_job(job_id)
    return jsonify({"deleted": True})


@app.get("/api/jobs/<int:job_id>/results")
@rate_limit(200)
def job_results(job_id):
    status = (request.args.get("status") or "ALL").upper()
    provider = (request.args.get("provider") or "ALL").upper()
    if status not in STATUSES or provider not in PROVIDERS:
        return jsonify({"error": "bad filter"}), 400
    try:
        page = max(1, int(request.args.get("page", 1)))
        per = max(1, min(int(request.args.get("per", 50)), 200))
    except ValueError:
        return jsonify({"error": "bad pagination"}), 400
    rows, total = db.get_results(job_id, None if status == "ALL" else status,
                                 None if provider == "ALL" else provider,
                                 (request.args.get("q") or "")[:80] or None,
                                 page, per, request.args.get("sort", "id"),
                                 request.args.get("dir", "asc"))
    return jsonify({"rows": rows, "total": total, "page": page, "per": per})


@app.get("/api/jobs/<int:job_id>/export")
@rate_limit(30)
def job_export(job_id):
    fmt = (request.args.get("format") or "csv").lower()
    status = (request.args.get("status") or "ALL").upper()
    if fmt not in ("txt", "csv", "json") or status not in STATUSES:
        return jsonify({"error": "bad export params"}), 400
    if not db.get_job(job_id):
        return jsonify({"error": "job not found"}), 404
    fname = f"blackforge_job{job_id}_{status.lower()}.{fmt}"

    def gen_txt():
        for r in db.iter_export(job_id, None if status == "ALL" else status):
            yield r["normalized"] + "\n"

    def gen_csv():
        buf = io.StringIO()
        w = csv.writer(buf)
        w.writerow(["email", "domain", "syntax", "dns", "has_mx", "provider",
                    "institution", "confidence", "status", "reason", "updated"])
        yield buf.getvalue()
        for r in db.iter_export(job_id, None if status == "ALL" else status):
            buf = io.StringIO()
            w = csv.writer(buf)
            w.writerow([r["normalized"], r["domain"], r["syntax"], r["dns"], r["has_mx"],
                        r["provider"], r["institution"], r["confidence"], r["status"],
                        r["reason"], r["updated"]])
            yield buf.getvalue()

    def gen_json():
        yield "["
        first = True
        for r in db.iter_export(job_id, None if status == "ALL" else status):
            if not first:
                yield ","
            first = False
            yield json.dumps({"email": r["normalized"], "domain": r["domain"],
                              "syntax": r["syntax"], "dns": r["dns"],
                              "has_mx": bool(r["has_mx"]),
                              "mx_hosts": json.loads(r["mx_hosts"] or "[]"),
                              "provider": r["provider"], "institution": r["institution"],
                              "confidence": r["confidence"], "status": r["status"],
                              "reason": r["reason"], "updated": r["updated"]})
        yield "]"

    gen = {"txt": gen_txt, "csv": gen_csv, "json": gen_json}[fmt]
    mime = {"txt": "text/plain", "csv": "text/csv", "json": "application/json"}[fmt]
    return Response(stream_with_context(gen()), mimetype=mime,
                    headers={"Content-Disposition": f"attachment; filename={fname}"})


@app.get("/api/jobs/<int:job_id>/stream")
@rate_limit(60)
def job_stream(job_id):
    job = db.get_job(job_id)
    if not job:
        return jsonify({"error": "job not found"}), 404

    def gen():
        import queue as _q
        q = engine.subscribe(job_id)
        try:
            snap = db.get_job(job_id)
            yield "data: " + json.dumps({"t": "snapshot", "job": snap,
                                         "counts": db.count_by_status(job_id)}) + "\n\n"
            while True:
                try:
                    ev = q.get(timeout=15)
                except _q.Empty:
                    yield ":ping\n\n"
                    continue
                yield "data: " + json.dumps(ev) + "\n\n"
                if ev.get("t") in ("done", "stopped"):
                    break
        finally:
            engine.unsubscribe(job_id, q)

    return Response(stream_with_context(gen()), mimetype="text/event-stream",
                    headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


# ---------------- cookie validation ----------------
@app.post("/api/cookie")
@rate_limit(60)
def cookie_check():
    if request.content_type and "text/plain" in request.content_type:
        text = request.get_data(as_text=True)
    else:
        data = request.get_json(silent=True) or {}
        text = data.get("text", "")
    if len(text) > 2 * 1024 * 1024:
        return jsonify({"error": "cookie file too large (max 2 MB)"}), 413
    if not text.strip():
        return jsonify({"error": "empty input"}), 400
    return jsonify(validate_cookie_file(text))


if __name__ == "__main__":
    import os
    db.init_db()
    # Cloud hosts (Render/Koyeb) assign a dynamic PORT and need 0.0.0.0.
    port = int(os.environ.get("PORT", "5000"))
    host = os.environ.get("HOST", "127.0.0.1")
    app.run(host=host, port=port, threaded=True)
