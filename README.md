# 🔥 HABIB BLACKFORGE — Enterprise Email Validation Engine

> Built under pressure. Proven by evidence.
> **Evidence > Assumption. Accuracy > Speed. Honest confidence > False certainty.**

Full-stack bulk email validation bot: **Flask backend + React dashboard + SQLite + live streaming + checkpoint/resume.**

## ✨ কী কী আছে

- Bulk paste / TXT / CSV / drag-drop (২ লাখ/জব পর্যন্ত, crash ছাড়াই)
- Pipeline: syntax → normalize → dedupe → DNS → MX → provider (Google Workspace / Microsoft 365...) → optional SMTP → catch-all → confidence
- সৎ স্ট্যাটাস: **LIVE** (SMTP প্রমাণ) / **LIKELY DELIVERABLE** (MX-ok, mailbox অজানা) / **INVALID** / **UNKNOWN** — ভুয়া "100% live" নয়
- Live SSE stream, counters, progress, ETA, result panels + table (search/filter/sort/pagination)
- Copy + TXT/CSV/JSON export
- Cookie-file **structural** check (শুধু গঠন — replay/auth কখনোই নয়)
- Emergency STOP (আসল backend stop + checkpoint) ও RESUME JOB
- Rate limits, size limits, secure headers, no raw-input logging
- 🎓 EDU / G / M365 / ALL ফিল্টার

## 🖥️ Windows-এ চালানো (২টা ফাইল!)

**১. Python ইনস্টল** (একবার): https://www.python.org/downloads/ → 3.10+ → ⚠️ **"Add python.exe to PATH" টিক দিতেই হবে**

**২. `setup.ps1`** → Right-click → **Run with PowerShell** (একবার, ২-৩ মিনিট)
> যদি script blocked বলে: PowerShell-এ (Admin নয়) চালান: `Set-ExecutionPolicy -Scope CurrentUser RemoteSigned`

**৩. `run.ps1`** → Right-click → **Run with PowerShell** → ব্রাউজারে http://127.0.0.1:5000 খুলবে 🎉

**বন্ধ করতে:** PowerShell window-তে `Ctrl+C`

## 📋 ব্যবহার

1. ইমেইল Paste (বা ফাইল drop) → **LOAD + COUNT**
2. Speed + Mode বেছে নিন (SMTP চাইলে টিক + authorization টিক দিন)
3. **START VALIDATION** → লাইভ stream দেখুন
4. **Copy / TXT / CSV / JSON** দিয়ে রেজাল্ট নিন
5. মাঝপথে থামাতে: **EMERGENCY STOP** → পরে **RESUME JOB**

## 🧪 টেস্ট

```powershell
.venv\Scripts\python test_api.py
```

(সার্ভার চালু থাকতে হবে — `run.ps1` আগে চালান। সব PASS আসা উচিত।)

ম্যানুয়াল চেকলিস্ট: preview counts → start → stream আসে → stop → resume → table search/filter → txt/csv/json ডাউনলোড → cookie tab → history delete।

## 🛠️ সমস্যা হলে

| সমস্যা | সমাধান |
|---|---|
| `python not found` | PATH টিক দিয়ে Python আবার ইনস্টল + PC রিস্টার্ট |
| script cannot run | `Set-ExecutionPolicy -Scope CurrentUser RemoteSigned` |
| pip install fail | ইন্টারনেট চেক; antivirus pause করে আবার |
| পোর্ট busy (5000) | আগের run window বন্ধ করুন |
| SMTP-তে সব UNKNOWN | WiFi port 25 block করেছে → MX-mode-ই ব্যবহার করুন |
| Google-এ UNKNOWN বেশি | Throttle হয়েছে — LOW speed + ছোট batch + পরে retry |

## 📁 গঠন

```
blackforge-bot/
├── backend/        Flask API (app.py), engine (worker.py), pipeline (validator.py),
│                   database (db.py), cookies (cookieval.py), static/ = built UI
├── frontend/       React+Vite source (build → backend/static)
├── setup.ps1 / run.ps1 / requirements.txt / README.md / test_api.py
```

Frontend আবার build করতে (Node.js লাগে): `cd frontend && npm install && npm run build`

## ⚠️ SMTP সেফটি

SMTP probe শুধু তখনই চালান যখন ডোমেইন **আপনার** বা **স্পষ্ট অনুমতি** আছে। Allowlist দিয়ে স্কোপ সীমাবদ্ধ করুন। Rate-limit/throttle সম্মান করুন — UNKNOWN মানে "অজানা", DEAD নয়।
