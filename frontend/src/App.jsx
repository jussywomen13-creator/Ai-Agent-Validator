import { useEffect, useRef, useState } from "react";

const MODES = ["12-AGENT STANDARD", "DEEP INSTITUTIONAL", "EVIDENCE-FIRST", "BALANCED"];
const MODE_HINT = {
  "12-AGENT STANDARD": "Balanced pipeline: 6s timeout, no retries. SMTP only if authorized.",
  "DEEP INSTITUTIONAL": "Thorough: 10s timeout, 2 retries, institutional evidence tagging.",
  "EVIDENCE-FIRST": "Slowest, strictest: 10s timeout, 3 retries, capped confidence.",
  "BALANCED": "Middle ground: 8s timeout, 1 retry.",
};
const SPEEDS = ["LOW", "MEDIUM", "HIGH", "CUSTOM"];
const SPEED_THREADS = { LOW: 2, MEDIUM: 6, HIGH: 12 };
const FOCUS = [
  { id: "EDU", label: "🎓 .EDU / INSTITUTIONAL" },
  { id: "GOOGLE", label: "G GOOGLE WORKSPACE" },
  { id: "MICROSOFT", label: "⊞ MICROSOFT 365" },
  { id: "ALL", label: "✓ ALL DOMAINS" },
];
const FOCUS_PROVIDER = { GOOGLE: "GOOGLE_WORKSPACE", MICROSOFT: "MICROSOFT_365" };
const STATUS_LIST = ["ALL", "LIVE", "LIKELY", "INVALID", "UNKNOWN"];
const PROVIDER_LIST = ["ALL", "GOOGLE_WORKSPACE", "MICROSOFT_365", "YAHOO", "ZOHO", "PROTON",
  "ICLOUD", "YANDEX", "FASTMAIL", "CUSTOM_PRIVATE", "DISPOSABLE"];

function Logo() {
  return (
    <svg width="52" height="52" viewBox="0 0 64 64" fill="none" aria-label="BLACKFORGE logo">
      <defs>
        <linearGradient id="mt" x1="0" y1="0" x2="1" y2="1">
          <stop offset="0" stopColor="#8b93a7" />
          <stop offset=".5" stopColor="#3c4356" />
          <stop offset="1" stopColor="#12151d" />
        </linearGradient>
        <linearGradient id="cy" x1="0" y1="0" x2="0" y2="1">
          <stop offset="0" stopColor="#67e8f9" />
          <stop offset="1" stopColor="#0e7490" />
        </linearGradient>
      </defs>
      <path d="M32 3 57 17.5v29L32 61 7 46.5v-29L32 3z" fill="url(#mt)" stroke="#5b6478" strokeWidth="2" />
      <path d="M32 12 49 21.8v20.4L32 52 15 42.2V21.8L32 12z" fill="#0b0e13" stroke="#2b3342" strokeWidth="1.5" />
      <path d="M22 40l6-12 5 8 4-11 5 15" stroke="url(#cy)" strokeWidth="3" strokeLinecap="round" strokeLinejoin="round" />
      <circle cx="32" cy="25" r="2.4" fill="#67e8f9" />
    </svg>
  );
}

function fmtDur(sec) {
  if (!isFinite(sec) || sec < 0) return "--";
  sec = Math.round(sec);
  if (sec < 60) return sec + "s";
  const m = Math.floor(sec / 60), s = sec % 60;
  if (m < 60) return `${m}m ${s}s`;
  return `${Math.floor(m / 60)}h ${m % 60}m`;
}

export default function App() {
  const [tab, setTab] = useState("email");
  const [health, setHealth] = useState("...");
  // input
  const [text, setText] = useState("");
  const [preview, setPreview] = useState(null);
  const [previewBusy, setPreviewBusy] = useState(false);
  const fileRef = useRef(null);
  // config
  const [focus, setFocus] = useState("ALL");
  const [speed, setSpeed] = useState("MEDIUM");
  const [customThreads, setCustomThreads] = useState(6);
  const [mode, setMode] = useState("12-AGENT STANDARD");
  const [smtp, setSmtp] = useState(false);
  const [auth, setAuth] = useState(false);
  const [allowlist, setAllowlist] = useState("");
  // job
  const [jobId, setJobId] = useState(null);
  const [jobStatus, setJobStatus] = useState("IDLE");
  const [running, setRunning] = useState(false);
  const [busy, setBusy] = useState(false);
  const [total, setTotal] = useState(0);
  const [processed, setProcessed] = useState(0);
  const [counts, setCounts] = useState({ LIVE: 0, LIKELY: 0, INVALID: 0, UNKNOWN: 0 });
  const [dupes, setDupes] = useState(0);
  const [errors, setErrors] = useState(0);
  const [tick, setTick] = useState(0);
  const t0Ref = useRef(Date.now());
  const esRef = useRef(null);
  // stream
  const [lines, setLines] = useState([]);
  const [autoScroll, setAutoScroll] = useState(true);
  const streamRef = useRef(null);
  // table
  const [rows, setRows] = useState([]);
  const [tblTotal, setTblTotal] = useState(0);
  const [page, setPage] = useState(1);
  const [per, setPer] = useState(50);
  const [sort, setSort] = useState("id");
  const [dir, setDir] = useState("asc");
  const [q, setQ] = useState("");
  const [statusF, setStatusF] = useState("ALL");
  const [providerF, setProviderF] = useState("ALL");
  // history + cookie + toast
  const [history, setHistory] = useState([]);
  const [cText, setCText] = useState("");
  const [cRes, setCRes] = useState(null);
  const [cBusy, setCBusy] = useState(false);
  const [toasts, setToasts] = useState([]);

  function toast(msg, kind = "") {
    const id = Date.now() + Math.random();
    setToasts((t) => [...t.slice(-4), { id, msg, kind }]);
    setTimeout(() => setToasts((t) => t.filter((x) => x.id !== id)), 4500);
  }

  function pushLine(ts, text, cls = "info") {
    setLines((prev) => {
      const next = [...prev, { ts, text, cls }];
      return next.length > 400 ? next.slice(next.length - 400) : next;
    });
  }

  useEffect(() => {
    fetch("/api/health").then((r) => r.json()).then(() => setHealth("READY")).catch(() => setHealth("OFFLINE"));
    refreshHistory();
  }, []);

  useEffect(() => {
    if (autoScroll && streamRef.current) streamRef.current.scrollTop = streamRef.current.scrollHeight;
  }, [lines, autoScroll]);

  useEffect(() => {
    if (!running) return;
    const iv = setInterval(() => setTick((t) => t + 1), 1000);
    return () => clearInterval(iv);
  }, [running]);

  useEffect(() => {
    if (!running || !jobId) return;
    const iv = setInterval(() => fetchTable(true), 5000);
    return () => clearInterval(iv);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [running, jobId, page, per, sort, dir, q, statusF, providerF]);

  async function refreshHistory() {
    try {
      const r = await fetch("/api/jobs");
      const j = await r.json();
      setHistory(j.jobs || []);
    } catch { /* offline */ }
  }

  // ---------- input ----------
  async function loadPreview() {
    if (!text.trim()) { toast("Paste emails or upload a file first.", "err"); return; }
    setPreviewBusy(true);
    try {
      const r = await fetch("/api/parse-preview", {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ text }),
      });
      const j = await r.json();
      if (!r.ok) { toast(j.error || "Preview failed", "err"); return; }
      setPreview(j);
    } catch { toast("Preview request failed.", "err"); }
    finally { setPreviewBusy(false); }
  }

  function readFile(f) {
    if (!f) return;
    const rd = new FileReader();
    rd.onload = () => {
      setText((prev) => (prev ? prev + "\n" + rd.result : String(rd.result)));
      toast(`Loaded ${f.name}`);
    };
    rd.readAsText(f);
  }

  // ---------- job control ----------
  function closeStream() {
    if (esRef.current) { esRef.current.close(); esRef.current = null; }
  }

  function openStream(id) {
    closeStream();
    t0Ref.current = Date.now();
    const es = new EventSource(`/api/jobs/${id}/stream`);
    esRef.current = es;
    es.onmessage = (ev) => {
      try {
        const m = JSON.parse(ev.data);
        if (m.t === "snapshot") {
          const jb = m.job || {};
          setTotal(jb.total || 0); setProcessed(jb.processed || 0);
          setDupes(jb.dupes || 0); setErrors(jb.errors || 0);
          setCounts({ LIVE: 0, LIKELY: 0, INVALID: 0, UNKNOWN: 0, ...(m.counts || {}) });
          setJobStatus(jb.status || "RUNNING");
        } else if (m.t === "row") {
          const r = m.row;
          setProcessed(m.processed || 0);
          setCounts({ LIVE: 0, LIKELY: 0, INVALID: 0, UNKNOWN: 0, ...(m.counts || {}) });
          setErrors(m.errors || 0);
          const ts = new Date().toTimeString().slice(0, 8);
          pushLine(ts, `${r.email} → ${r.status} ${r.confidence}% • ${r.provider || "-"} • ${r.reason}`, r.status);
        } else if (m.t === "log") {
          pushLine(m.ts || "", m.msg, "info");
        } else if (m.t === "done" || m.t === "stopped") {
          setRunning(false);
          setJobStatus(m.t === "done" ? "DONE" : "STOPPED");
          if (m.counts) setCounts({ LIVE: 0, LIKELY: 0, INVALID: 0, UNKNOWN: 0, ...m.counts });
          pushLine(new Date().toTimeString().slice(0, 8), m.t === "done" ? "JOB COMPLETE." : "JOB STOPPED - checkpoint saved. Resume available.", m.t);
          fetchTable(true); refreshHistory();
          toast(m.t === "done" ? "Validation complete." : "Stopped. Resume any time.", m.t === "done" ? "ok" : "");
          closeStream();
        }
      } catch { /* ignore */ }
    };
    es.onerror = () => { /* browser retries; silent */ };
  }

  async function start() {
    if (running || busy) return;
    if (!text.trim()) { toast("Paste emails or upload a file first.", "err"); return; }
    if (smtp && !auth) { toast("SMTP requires the authorization checkbox.", "err"); return; }
    setBusy(true);
    try {
      const r = await fetch("/api/jobs", {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          text, mode, speed, custom_threads: customThreads, focus,
          smtp, allowlist, name: `job-${new Date().toTimeString().slice(0, 8)}`,
        }),
      });
      const j = await r.json();
      if (!r.ok) { toast(j.error || "Create failed", "err"); return; }
      if (j.filtered_out) toast(`EDU pre-filter removed ${j.filtered_out} non-institutional addresses.`);
      if (j.truncated) toast("Input hit the 200k cap - truncated.", "err");
      const id = j.job_id;
      setJobId(id); setTotal(j.total); setProcessed(0);
      setCounts({ LIVE: 0, LIKELY: 0, INVALID: 0, UNKNOWN: 0 });
      setDupes(j.dupes || 0); setErrors(0); setLines([]); setRows([]); setTblTotal(0); setPage(1);
      const s = await fetch(`/api/jobs/${id}/start`, { method: "POST" });
      const sj = await s.json();
      if (!s.ok) { toast(sj.error || "Start failed", "err"); return; }
      setRunning(true); setJobStatus("RUNNING");
      openStream(id);
    } catch { toast("Start request failed.", "err"); }
    finally { setBusy(false); }
  }

  async function stop() {
    if (!jobId || !running) return;
    await fetch(`/api/jobs/${jobId}/stop`, { method: "POST" });
    toast("Stop signal sent - workers finishing current item...");
  }

  async function reset() {
    if (running && !window.confirm("A job is running. Stop it and reset the console?")) return;
    if (jobId && running) { try { await fetch(`/api/jobs/${jobId}/stop`, { method: "POST" }); } catch {} }
    closeStream();
    setRunning(false); setJobId(null); setJobStatus("IDLE");
    setTotal(0); setProcessed(0); setCounts({ LIVE: 0, LIKELY: 0, INVALID: 0, UNKNOWN: 0 });
    setDupes(0); setErrors(0); setLines([]); setRows([]); setTblTotal(0); setPage(1);
    refreshHistory();
    toast("Console reset. Job history restored below.");
  }

  async function openJob(id, resume = false) {
    closeStream();
    const r = await fetch(`/api/jobs/${id}`);
    const j = await r.json();
    if (!r.ok) { toast("Job not found", "err"); return; }
    const jb = j.job;
    setJobId(id); setJobStatus(jb.status); setTotal(jb.total); setProcessed(jb.processed);
    setDupes(jb.dupes); setErrors(jb.errors);
    setCounts({ LIVE: 0, LIKELY: 0, INVALID: 0, UNKNOWN: 0, ...(j.counts || {}) });
    setLines([]); setPage(1);
    pushLine(new Date().toTimeString().slice(0, 8), `Opened job #${id} (${jb.status}).`, "info");
    if (resume) {
      const rr = await fetch(`/api/jobs/${id}/resume`, { method: "POST" });
      const rj = await rr.json();
      if (!rr.ok) { toast(rj.error || "Resume failed", "err"); return; }
      setRunning(true); setJobStatus("RUNNING");
      openStream(id);
    } else {
      fetchTableFor(id, 1);
    }
  }

  async function deleteJob(id) {
    if (!window.confirm(`Delete job #${id} and all its results?`)) return;
    const r = await fetch(`/api/jobs/${id}`, { method: "DELETE" });
    if (!r.ok) { const j = await r.json(); toast(j.error || "Delete failed", "err"); return; }
    if (id === jobId) reset();
    refreshHistory();
  }

  // ---------- table / copy / export ----------
  async function fetchTableFor(id, p = page) {
    try {
      const u = new URL(`/api/jobs/${id}/results`, window.location.origin);
      u.searchParams.set("page", p); u.searchParams.set("per", per);
      u.searchParams.set("sort", sort); u.searchParams.set("dir", dir);
      if (q) u.searchParams.set("q", q);
      u.searchParams.set("status", statusF); u.searchParams.set("provider", providerF);
      const r = await fetch(u);
      const j = await r.json();
      if (r.ok) { setRows(j.rows || []); setTblTotal(j.total || 0); }
    } catch {}
  }
  function fetchTable(silent) { if (jobId) fetchTableFor(jobId, page); }

  async function copyStatus(status) {
    if (!jobId) { toast("No job loaded.", "err"); return; }
    try {
      const u = new URL(`/api/jobs/${jobId}/results`, window.location.origin);
      u.searchParams.set("status", status); u.searchParams.set("per", 5000);
      u.searchParams.set("provider", providerF);
      const r = await fetch(u);
      const j = await r.json();
      if (!r.ok || !j.rows.length) { toast(`No ${status} rows to copy.`, "err"); return; }
      await navigator.clipboard.writeText(j.rows.map((x) => x.normalized || x.email).join("\n"));
      toast(`Copied ${j.rows.length}${j.total > j.rows.length ? ` of ${j.total} (cap 5000 - use export for full)` : ""} ${status}.`, "ok");
    } catch { toast("Copy failed.", "err"); }
  }

  function toggleSort(col) {
    if (sort === col) setDir((d) => (d === "asc" ? "desc" : "asc"));
    else { setSort(col); setDir("asc"); }
    setPage(1);
  }

  useEffect(() => { if (jobId) fetchTableFor(jobId, 1); setPage(1);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [statusF, providerF, per, sort, dir]);
  useEffect(() => { if (jobId) fetchTableFor(jobId, page);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [page]);

  // ---------- cookie ----------
  async function validateCookie() {
    if (!cText.trim()) { toast("Paste cookie file contents first.", "err"); return; }
    setCBusy(true); setCRes(null);
    try {
      const r = await fetch("/api/cookie", {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ text: cText }),
      });
      const j = await r.json();
      if (!r.ok) { toast(j.error || "Cookie check failed", "err"); return; }
      setCRes(j);
    } catch { toast("Cookie request failed.", "err"); }
    finally { setCBusy(false); }
  }

  // ---------- derived ----------
  const elapsed = Math.max(1, (Date.now() - t0Ref.current) / 1000);
  const speedNow = running && processed > 0 ? (processed / elapsed) : 0;
  const remaining = Math.max(0, total - processed);
  const eta = running && speedNow > 0 ? (remaining / speedNow) : 0;
  const pct = total > 0 ? Math.round((processed / total) * 100) : 0;
  const workers = speed === "CUSTOM" ? customThreads : SPEED_THREADS[speed];
  const pages = Math.max(1, Math.ceil(tblTotal / per));

  function pickFocus(id) {
    setFocus(id);
    if (id === "GOOGLE" || id === "MICROSOFT") setProviderF(FOCUS_PROVIDER[id]);
    else setProviderF("ALL");
  }

  return (
    <div className="wrap">
      {/* ===== BRAND HEADER ===== */}
      <header className="header">
        <Logo />
        <div>
          <h1>HABIB BLACKFORGE</h1>
          <p className="sub">ENTERPRISE EMAIL VALIDATION ENGINE</p>
          <p className="tag">Built under pressure. Proven by evidence.</p>
        </div>
        <div className={`sysstat ${health === "READY" ? "ok" : "bad"}`}>
          <span className="dot" /> SYSTEM {health}
          {jobId && <span className="jobtag">JOB #{jobId} • {jobStatus}</span>}
        </div>
      </header>

      <div className="tabs">
        <button className={`tabbtn ${tab === "email" ? "active" : ""}`} onClick={() => setTab("email")}>Email Validation</button>
        <button className={`tabbtn ${tab === "cookie" ? "active" : ""}`} onClick={() => setTab("cookie")}>Cookie File Check</button>
      </div>

      {tab === "email" && (
        <>
          {/* ===== FILTERS ===== */}
          <div className="panel">
            <h2>VALIDATION FILTERS</h2>
            <div className="filters-row">
              {FOCUS.map((f) => (
                <button key={f.id} className={`fbtn ${focus === f.id ? "active" : ""}`}
                  onClick={() => pickFocus(f.id)} disabled={running}>{f.label}</button>
              ))}
            </div>
            <div className="hint">
              {focus === "EDU" && ".EDU pre-filter narrows the queue to institutional-pattern domains before validation."}
              {focus === "GOOGLE" && "GOOGLE focus filters results/export views to Google Workspace senders (validation still evidences all)."}
              {focus === "MICROSOFT" && "MICROSOFT focus filters results/export views to Microsoft 365 senders (validation still evidences all)."}
              {focus === "ALL" && "ALL DOMAINS: no filtering - full pipeline on everything queued."}
            </div>
          </div>

          <div className="grid2">
            {/* ===== INPUT ===== */}
            <div className="panel">
              <h2>✉️ PASTE EMAILS TO VALIDATE</h2>
              <p className="psub">Auto-loads on START • No crash for lakhs (streamed to DB)</p>
              <div className="drop" onClick={() => fileRef.current?.click()}
                onDragOver={(e) => e.preventDefault()}
                onDrop={(e) => { e.preventDefault(); readFile(e.dataTransfer.files?.[0]); }}>
                Click or drop <b>.txt / .csv</b> here (appends to the box below)
              </div>
              <input ref={fileRef} type="file" accept=".txt,.csv,.tsv" style={{ display: "none" }}
                onChange={(e) => { readFile(e.target.files?.[0]); e.target.value = ""; }} />
              <textarea className="inputbox" value={text} onChange={(e) => setText(e.target.value)}
                disabled={running} placeholder={"one per line (or CSV/TSV, Name <email>)\n\nstudent@university.edu\nname@gmail.com"} />
              <div className="btnrow">
                <button className="btn" onClick={loadPreview} disabled={running || previewBusy}>
                  {previewBusy ? "Counting..." : "LOAD + COUNT"}</button>
                <button className="btn" onClick={() => { setText(""); setPreview(null); }} disabled={running}>CLEAR</button>
              </div>
              {preview && (
                <div className="kv4">
                  <div><small>INPUT</small><b>{preview.input}</b></div>
                  <div><small>UNIQUE</small><b>{preview.unique}</b></div>
                  <div><small>DUPLICATES</small><b>{preview.dupes}</b></div>
                  <div><small>BAD SYNTAX*</small><b>{preview.invalid_syntax_sample}</b></div>
                </div>
              )}
              <div className="hint">*syntax sample over first 20k lines. Cap: 200,000/job, 12 MB upload.</div>
            </div>

            {/* ===== CONTROL PANEL ===== */}
            <div className="panel">
              <h2>CONTROL PANEL</h2>
              <label className="lbl">THREAD SPEED</label>
              <div className="seg">
                {SPEEDS.map((s) => (
                  <button key={s} className={`segbtn ${speed === s ? "active" : ""}`}
                    onClick={() => setSpeed(s)} disabled={running}>{s}</button>
                ))}
              </div>
              {speed === "CUSTOM" && (
                <input className="textin" type="number" min="1" max="32" value={customThreads}
                  onChange={(e) => setCustomThreads(Math.max(1, Math.min(32, Number(e.target.value) || 1)))}
                  disabled={running} />
              )}
              <label className="lbl">VALIDATION MODE</label>
              <select className="textin" value={mode} onChange={(e) => setMode(e.target.value)} disabled={running}>
                {MODES.map((m) => <option key={m} value={m}>{m}</option>)}
              </select>
              <div className="hint">{MODE_HINT[mode]}</div>
              <label className="check">
                <input type="checkbox" checked={smtp} onChange={(e) => setSmtp(e.target.checked)} disabled={running} />
                <span>Enable SMTP reachability probes <small>Off by default. Mailbox-level evidence when authorized.</small></span>
              </label>
              {smtp && (
                <div className="smtpbox">
                  <label className="check">
                    <input type="checkbox" checked={auth} onChange={(e) => setAuth(e.target.checked)} disabled={running} />
                    <span><b>I own or am explicitly authorized to SMTP-test these domains.</b></span>
                  </label>
                  <details>
                    <summary>Domain allowlist (optional - one per line; SMTP only for these)</summary>
                    <textarea className="inputbox small" value={allowlist}
                      onChange={(e) => setAllowlist(e.target.value)} disabled={running}
                      placeholder={"mycompany.com\nmyschool.edu"} />
                  </details>
                </div>
              )}
              <button className="btn-big go" onClick={start} disabled={running || busy}>
                {busy ? "⏳ CREATING JOB..." : "🚀 START VALIDATION"}</button>
              <div className="btnrow2">
                <button className="btn-big stop" onClick={stop} disabled={!running}>⛔ EMERGENCY STOP</button>
                <button className="btn-big ghost" onClick={reset}>🔄 RESET &amp; RESTORE</button>
              </div>
            </div>
          </div>

          {/* ===== COUNTERS ===== */}
          <div className="panel">
            <h2>LIVE COUNTERS {jobId ? `(JOB #${jobId})` : ""}</h2>
            <div className="counters">
              <div className="counter"><small>QUEUE</small><b>{remaining}</b></div>
              <div className="counter live"><small>LIVE</small><b>{counts.LIVE}</b></div>
              <div className="counter likely"><small>LIKELY DELIVERABLE</small><b>{counts.LIKELY}</b></div>
              <div className="counter unknown"><small>UNKNOWN</small><b>{counts.UNKNOWN}</b></div>
              <div className="counter invalid"><small>INVALID</small><b>{counts.INVALID}</b></div>
              <div className="counter"><small>DUPES</small><b>{dupes}</b></div>
              <div className="counter"><small>PROCESSED</small><b>{processed}</b></div>
              <div className="counter"><small>ERRORS</small><b>{errors}</b></div>
              <div className="counter"><small>SPEED</small><b>{speedNow ? speedNow.toFixed(1) + "/s" : "--"}</b></div>
              <div className="counter"><small>ETA</small><b>{running ? fmtDur(eta) : "--"}</b></div>
            </div>
          </div>

          {/* ===== PROGRESS + STREAM ===== */}
          <div className="grid2">
            <div className="panel">
              <h2>PROGRESS</h2>
              <div className="bigpct">{pct}%</div>
              <div className="progbar"><div className="progfill" style={{ width: pct + "%" }} /></div>
              <div className="prow"><span>Processed / Total</span><b>{processed} / {total}</b></div>
              <div className="prow"><span>Current speed</span><b>{speedNow ? speedNow.toFixed(1) + " emails/s" : "--"}</b></div>
              <div className="prow"><span>ETA</span><b>{running ? fmtDur(eta) : "--"}</b></div>
              <div className="prow"><span>Current batch</span><b>{total ? `${Math.floor(processed / 500) + 1} / ${Math.max(1, Math.ceil(total / 500))}` : "--"}</b></div>
              <div className="prow"><span>Active workers</span><b>{running ? workers : 0}</b></div>
            </div>
            <div className="panel">
              <h2>🟢 LIVE VALIDATION STREAM
                <label className="autosc">auto-scroll <input type="checkbox" checked={autoScroll}
                  onChange={(e) => setAutoScroll(e.target.checked)} /></label>
              </h2>
              <div className="stream" ref={streamRef}>
                {lines.length === 0 && <div className="emptystate">Backend events will stream here during validation.</div>}
                {lines.map((l, i) => (
                  <div key={i} className={`sline ${l.cls.toLowerCase()}`}>
                    <span className="ts">[{l.ts}]</span> {l.text}
                  </div>
                ))}
              </div>
            </div>
          </div>

          {/* ===== RESULT PANELS ===== */}
          <div className="panel">
            <h2>RESULT PANELS</h2>
            <div className="pcards">
              {[["LIVE", counts.LIVE, "live", "SMTP-accepted mailbox evidence"],
                ["LIKELY DELIVERABLE", counts.LIKELY, "likely", "Valid MX, mailbox unprobed"],
                ["INVALID / UNDELIVERABLE", counts.INVALID, "invalid", "Syntax / no-MX / SMTP 5xx"],
                ["UNKNOWN", counts.UNKNOWN, "unknown", "Catch-all / deferral / blocked"]].map(([label, n, cls, sub]) => (
                <div key={label} className={`pcard ${cls}`}>
                  <small>{label}</small><b>{n}</b><span>{sub}</span>
                  <button className="btn btn-sm" disabled={!jobId}
                    onClick={() => copyStatus(label.startsWith("LIKELY") ? "LIKELY" : label.split(" ")[0])}>
                    Copy {label.split(" ")[0]}</button>
                </div>
              ))}
            </div>
            <div className="btnrow wrap">
              <span className="lbl-inline">Export job results:</span>
              {jobId ? (<>
                <a className="btn" href={`/api/jobs/${jobId}/export?format=txt&status=${statusF}`}>TXT</a>
                <a className="btn" href={`/api/jobs/${jobId}/export?format=csv&status=${statusF}`}>CSV</a>
                <a className="btn" href={`/api/jobs/${jobId}/export?format=json&status=${statusF}`}>RESULTS.json</a>
                <span className="hint">(respects table status filter: {statusF})</span>
              </>) : <span className="hint">Start a job to enable exports.</span>}
            </div>
          </div>

          {/* ===== TABLE ===== */}
          <div className="panel">
            <h2>RESULT TABLE {tblTotal ? `(${tblTotal} rows)` : ""}</h2>
            <div className="toolbar">
              <input className="textin search" placeholder="Search email / domain..." value={q}
                onChange={(e) => setQ(e.target.value)}
                onKeyDown={(e) => { if (e.key === "Enter") { setPage(1); jobId && fetchTableFor(jobId, 1); } }} />
              <select className="textin" value={statusF} onChange={(e) => setStatusF(e.target.value)}>
                {STATUS_LIST.map((s) => <option key={s} value={s}>{s}</option>)}
              </select>
              <select className="textin" value={providerF} onChange={(e) => setProviderF(e.target.value)}>
                {PROVIDER_LIST.map((s) => <option key={s} value={s}>{s}</option>)}
              </select>
              <select className="textin" value={per} onChange={(e) => setPer(Number(e.target.value))}>
                {[25, 50, 100, 200].map((n) => <option key={n} value={n}>{n}/page</option>)}
              </select>
              <button className="btn" onClick={() => fetchTable()} disabled={!jobId}>Refresh</button>
            </div>
            <div className="table-wrap">
              <table>
                <thead><tr>
                  {[["email", "Email"], ["domain", "Domain"]].map(([c, l]) => (
                    <th key={c} className="sortable" onClick={() => toggleSort(c)}>{l} {sort === c ? (dir === "asc" ? "▲" : "▼") : ""}</th>
                  ))}
                  <th>Syntax</th><th>DNS</th><th>MX</th><th>Provider</th><th>Institution</th>
                  {[["confidence", "Confidence"], ["status", "Final Status"], ["updated", "Updated"]].map(([c, l]) => (
                    <th key={c} className="sortable" onClick={() => toggleSort(c)}>{l} {sort === c ? (dir === "asc" ? "▲" : "▼") : ""}</th>
                  ))}
                </tr></thead>
                <tbody>
                  {rows.map((r) => {
                    let mxn = 0;
                    try { mxn = JSON.parse(r.mx_hosts || "[]").length; } catch {}
                    return (
                      <tr key={r.id}>
                        <td className="mono">{r.normalized || r.email}</td>
                        <td>{r.domain || "-"}</td>
                        <td>{r.syntax === "pass" ? "✓" : r.syntax === "fail" ? "✗" : "-"}</td>
                        <td>{r.dns === "pass" ? "✓" : r.dns ? r.dns : "-"}</td>
                        <td>{r.has_mx ? `✓${mxn ? ` (${mxn})` : ""}` : "✗"}</td>
                        <td className="small">{r.provider || "-"}</td>
                        <td className="small">{r.institution === "INSTITUTIONAL" ? "🎓" : "-"}</td>
                        <td>{r.status === "PENDING" ? "-" : `${r.confidence}%`}</td>
                        <td><span className={`badge ${r.status}`}>{r.status}</span></td>
                        <td className="small">{(r.updated || "").slice(5, 16).replace("T", " ") || "-"}</td>
                      </tr>
                    );
                  })}
                  {rows.length === 0 && (
                    <tr><td colSpan="10" className="emptystate">No rows - START a validation or adjust filters.</td></tr>
                  )}
                </tbody>
              </table>
            </div>
            <div className="pager">
              <button className="btn btn-sm" disabled={page <= 1} onClick={() => setPage((p) => p - 1)}>Prev</button>
              <span>Page {page} / {pages} ({tblTotal} rows)</span>
              <button className="btn btn-sm" disabled={page >= pages} onClick={() => setPage((p) => p + 1)}>Next</button>
            </div>
          </div>

          {/* ===== HISTORY ===== */}
          <div className="panel">
            <h2>JOB HISTORY (CHECKPOINT / RESUME)</h2>
            {history.length === 0 && <div className="emptystate">No jobs yet.</div>}
            {history.map((j) => (
              <div key={j.id} className="hist">
                <b>#{j.id}</b>
                <span className={`badge ${j.status}`}>{j.status}</span>
                <span className="small">{j.processed}/{j.total} • {j.mode} • {j.speed} • SMTP:{j.smtp ? "ON" : "OFF"}</span>
                <span className="spacer" />
                <button className="btn btn-sm" onClick={() => openJob(j.id)}>Open</button>
                {(j.status === "STOPPED" || j.status === "CREATED") && (
                  <button className="btn btn-sm go" onClick={() => openJob(j.id, true)}>RESUME JOB</button>
                )}
                <button className="btn btn-sm danger" onClick={() => deleteJob(j.id)}>Delete</button>
              </div>
            ))}
          </div>

          <div className="foot">
            SMTP RCPT TO checks cannot guarantee a "100% active inbox." Providers use catch-all routing,
            greylisting, tarpits, anti-enumeration responses, and deferred acceptance; port 25 is blocked by
            many networks. BLACKFORGE reports <b>LIVE</b> (mailbox evidence), <b>LIKELY DELIVERABLE</b> (valid MX,
            unprobed), <b>INVALID</b>, and <b>UNKNOWN</b> - never false certainty. SMTP probes run only when you
            explicitly authorize them.
          </div>
        </>
      )}

      {tab === "cookie" && (
        <div className="grid2">
          <div className="panel">
            <h2>COOKIE FILE INPUT (LOCAL ONLY)</h2>
            <textarea className="inputbox" value={cText} onChange={(e) => setCText(e.target.value)}
              placeholder={"Paste Netscape cookie jar or JSON array...\n\n.example.com\tTRUE\t/\tTRUE\t1999999999\tsid\tabc"} />
            <div className="btnrow">
              <button className="btn" onClick={() => {
                const i = document.createElement("input");
                i.type = "file"; i.accept = ".txt,.json,.cookies";
                i.onchange = () => { const f = i.files?.[0]; if (f) { const r = new FileReader(); r.onload = () => setCText(String(r.result)); r.readAsText(f); } };
                i.click();
              }}>Upload</button>
              <button className="btn" onClick={() => { setCText(""); setCRes(null); }}>Clear</button>
              <button className="btn go2" onClick={validateCookie} disabled={cBusy}>
                {cBusy ? "Checking..." : "Validate structure"}</button>
            </div>
            <div className="hint">Structural validation only. Cookies are never replayed, never used to
              authenticate, never sent anywhere.</div>
          </div>
          <div className="panel">
            <h2>STRUCTURE REPORT</h2>
            {!cRes && <div className="emptystate">Run a check to see the report.</div>}
            {cRes && (<>
              <div className="kv4">
                <div><small>FORMAT</small><b>{cRes.format.toUpperCase()}</b></div>
                <div><small>VERDICT</small><b className={cRes.ok ? "ok" : "bad"}>{cRes.ok ? "OK" : "ISSUES"}</b></div>
                <div><small>VALID/TOTAL</small><b>{cRes.validRows}/{cRes.totalRows}</b></div>
                <div><small>DOMAINS</small><b>{cRes.domainCount}</b></div>
              </div>
              {cRes.issues.length > 0 && (
                <div className="table-wrap"><table><thead><tr><th>Line</th><th>Issue</th></tr></thead>
                  <tbody>{cRes.issues.slice(0, 100).map((it, i) => (
                    <tr key={i}><td>{it.line}</td><td>{it.message}</td></tr>))}</tbody>
                </table></div>
              )}
              <div className="hint">{cRes.disclaimer}</div>
            </>)}
          </div>
        </div>
      )}

      <div className="toasts">
        {toasts.map((t) => <div key={t.id} className={`toast ${t.kind}`}>{t.msg}</div>)}
      </div>
    </div>
  );
}
