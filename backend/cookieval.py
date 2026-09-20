"""Cookie-file STRUCTURAL validation only. Never replays cookies,
never authenticates, never touches accounts, never leaves the machine."""
import json
import time


def validate_cookie_file(text):
    t = (text or "").strip()
    base = {"format": "unknown", "ok": False, "totalRows": 0, "validRows": 0,
            "invalidRows": 0, "issues": [], "sample": [], "secureCount": 0,
            "httpOnlyCount": 0, "domainCount": 0,
            "disclaimer": "Structural check only - cookies are never replayed, "
                          "never used to authenticate, and never sent anywhere."}
    if not t:
        base["issues"].append({"line": 0, "message": "Empty input"})
        return base
    if t.startswith("[") or t.startswith("{"):
        try:
            parsed = json.loads(t)
        except Exception:
            base["issues"].append({"line": 0, "message": "Invalid JSON"})
            return base
        arr = None
        if isinstance(parsed, list):
            arr = parsed
        elif isinstance(parsed, dict) and isinstance(parsed.get("cookies"), list):
            arr = parsed["cookies"]
        if arr is None:
            base["issues"].append({"line": 0, "message": "JSON is not a cookie array"})
            return base
        base["format"] = "json"
        domains = set()
        for i, c in enumerate(arr):
            base["totalRows"] += 1
            row = c if isinstance(c, dict) else {}
            name = str(row.get("name", ""))
            domain = str(row.get("domain", ""))
            if not name or not domain:
                base["invalidRows"] += 1
                base["issues"].append({"line": i + 1, "message": "Missing name/domain"})
                continue
            base["validRows"] += 1
            domains.add(domain)
            if row.get("secure") is True or str(row.get("secure")).upper() == "TRUE":
                base["secureCount"] += 1
            if row.get("httpOnly") is True or row.get("httponly") is True:
                base["httpOnlyCount"] += 1
            if len(base["sample"]) < 5:
                base["sample"].append({"domain": domain, "name": name,
                                       "value": str(row.get("value", ""))[:16] + "..."})
        base["domainCount"] = len(domains)
        base["ok"] = base["validRows"] > 0 and base["invalidRows"] == 0
        return base
    base["format"] = "netscape"
    domains = set()
    now = int(time.time())
    for i, raw in enumerate(t.splitlines()):
        line = raw.strip()
        if not line:
            continue
        http_only = False
        if line.startswith("#HttpOnly_"):
            http_only = True
            line = line[len("#HttpOnly_"):]
        elif line.startswith("#"):
            continue
        base["totalRows"] += 1
        f = line.split("\t")
        if len(f) < 7:
            base["invalidRows"] += 1
            base["issues"].append({"line": i + 1,
                                   "message": f"Expected 7 tab fields, got {len(f)}"})
            continue
        domain, _, path, secure, exp, name = f[0], f[1], f[2], f[3], f[4], f[5]
        if not domain or not name:
            base["invalidRows"] += 1
            base["issues"].append({"line": i + 1, "message": "Missing domain/name"})
            continue
        base["validRows"] += 1
        domains.add(domain)
        if secure.upper() == "TRUE":
            base["secureCount"] += 1
        if http_only:
            base["httpOnlyCount"] += 1
        if exp.isdigit() and int(exp) < now:
            base["issues"].append({"line": i + 1,
                                   "message": f'Cookie "{name}" looks expired'})
        if len(base["sample"]) < 5:
            base["sample"].append({"domain": domain, "path": path, "name": name,
                                   "value": (f[6] if len(f) > 6 else "")[:16] + "...",
                                   "line": i + 1})
    if base["totalRows"] == 0:
        base["format"] = "unknown"
        base["issues"].append({"line": 0, "message": "No cookie rows found"})
        return base
    base["domainCount"] = len(domains)
    base["ok"] = base["validRows"] > 0 and base["invalidRows"] == 0
    return base
