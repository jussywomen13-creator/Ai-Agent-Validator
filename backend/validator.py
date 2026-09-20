"""Validation pipeline: syntax, normalize, dedupe, DNS, MX, provider,
SMTP diagnostics, catch-all analysis, confidence engine. Every module
returns structured evidence. No fabricated certainty."""
import re
import socket
import time

import dns.exception
import dns.resolver

# ---------------- static lists ----------------
DISPOSABLE = set(
    "mailinator.com tempmail.com guerrillamail.com 10minutemail.com throwawaymail.com "
    "fakeinbox.com yopmail.com trashmail.com getnada.com temp-mail.org emailondeck.com "
    "maildrop.cc dispostable.com mailnesia.com mytrashmail.com spamgourmet.com jetable.org "
    "mailexpire.com mintemail.com anonymbox.com burnermail.io duck.com moakt.com tmail.ws "
    "tmpmail.net harakirimail.com deadaddress.com spambox.us tempinbox.com tempmail.net "
    "trashmail.net trashmail.me trashmail.org trashmail.ws trashymail.com yopmail.fr "
    "yopmail.net nospam.ze.tc sofort-mail.de discardmail.com mailforspam.com spamlab.com "
    "binkmail.com devnullmail.com sharklasers.com shitmail.me sneakemail.com spam.la spam.su "
    "spam4.me spamex.com spamhole.com spaminator.de spaml.de temporaryemail.net "
    "temporaryinbox.com trashemail.de trashinbox.com wegwerfemail.de wegwerfmail.de "
    "wegwerfmail.net wegwerfmail.org whyspam.me willselfdestruct.com rmqkr.net rtrtr.com "
    "teleworm.us superrito.com emailtemporario.com.br mailcatch.com mailsac.com mailtrap.io "
    "getairmail.com fake-box.com crownbicycles.net filzmail.com gishpuppy.com creou.dev"
    .split()
)

FREE_PROVIDERS = set(
    "gmail.com googlemail.com yahoo.com yahoo.co.in yahoo.co.uk outlook.com hotmail.com "
    "live.com msn.com icloud.com me.com mac.com protonmail.com proton.me pm.me tutanota.com "
    "tuta.io yandex.com yandex.ru gmx.com gmx.de web.de aol.com zoho.com rediffmail.com "
    "mail.com inbox.com fastmail.com hey.com".split()
)

ROLE_PREFIX = set(
    "admin administrator info support contact help hello sales service services noreply "
    "no-reply donotreply postmaster webmaster hostmaster abuse security privacy legal "
    "billing bounce newsletter marketing careers jobs hr office mail feedback test demo "
    "example press media partnerships affiliates accounts payments orders shipping returns "
    "subscribe unsubscribe notify notifications alerts devops engineering team staff all "
    "everyone users group".split()
)

INSTITUTION_KEYWORDS = (
    "university college institute school campus academy faculty dept polytechnic "
    "schoolboard schooldistrict deped education edu "
)


def is_institutional(domain):
    d = domain.lower()
    if re.search(r"\.(edu|ac\.[a-z]{2}|edu\.[a-z]{2}|sch\.[a-z]{2}|gov\.[a-z]{2})$", d):
        return True
    return any(k in d for k in INSTITUTION_KEYWORDS.split())


PROVIDER_MX = [
    (re.compile(r"google\.com|googlemail\.com", re.I), "GOOGLE_WORKSPACE"),
    (re.compile(r"outlook\.com|hotmail\.com|office365|protection\.outlook|exchange|microsoft", re.I), "MICROSOFT_365"),
    (re.compile(r"yahoo|yahoodns", re.I), "YAHOO"),
    (re.compile(r"zoho", re.I), "ZOHO"),
    (re.compile(r"proton", re.I), "PROTON"),
    (re.compile(r"icloud|apple", re.I), "ICLOUD"),
    (re.compile(r"yandex", re.I), "YANDEX"),
    (re.compile(r"fastmail|messagingengine", re.I), "FASTMAIL"),
]


def detect_provider(mx_hosts):
    j = " ".join(mx_hosts)
    for rx, name in PROVIDER_MX:
        if rx.search(j):
            return name
    return "CUSTOM_PRIVATE"


# ---------------- module 1-3: parse / normalize / dedupe ----------------
ANGLE_RE = re.compile(r"<([^<>\s,;]+@[^<>\s,;]+)>")


def parse_input(text, max_emails=200000):
    """Split bulk text into candidate tokens. Bounded: stops past cap."""
    found = []
    for m in ANGLE_RE.finditer(text or ""):
        found.append(m.group(1).strip())
    rest = ANGLE_RE.sub(" ", text or "")
    for part in re.split(r"[\n,;\t\r]+", rest):
        for tok in part.split():
            tok = tok.strip("\"'<>()[] \t").rstrip(".,;:")
            if tok:
                found.append(tok)
            if len(found) >= max_emails + 5000:
                break
        if len(found) >= max_emails + 5000:
            break
    seen = set()
    unique = []
    dupes = 0
    for raw in found:
        if len(unique) >= max_emails:
            break
        k = raw.lower()
        if k in seen:
            dupes += 1
            continue
        seen.add(k)
        unique.append({"original": raw, "normalized": k})
    return {"unique": unique, "dupes": dupes, "truncated": len(found) > len(unique) + dupes}


# ---------------- module: syntax ----------------
_LOCAL_RE = re.compile(r"^[A-Za-z0-9.!#$%&'*+/=?^_`{|}~-]+$")
_DOMAIN_RE = re.compile(r"^[A-Za-z0-9.-]+\.[A-Za-z]{2,}$")


def check_syntax(email):
    if not email or len(email) > 254:
        return {"valid": False, "reason": "too-long-or-empty"}
    if any(c.isspace() for c in email):
        return {"valid": False, "reason": "whitespace"}
    parts = email.split("@")
    if len(parts) != 2:
        return {"valid": False, "reason": "missing-or-extra-@"}
    local, domain = parts[0], parts[1].lower()
    if not local or len(local) > 64:
        return {"valid": False, "reason": "bad-local-part"}
    if local.startswith(".") or local.endswith(".") or ".." in local:
        return {"valid": False, "reason": "bad-dots-local"}
    if not _LOCAL_RE.match(local):
        return {"valid": False, "reason": "illegal-chars"}
    if not domain or len(domain) > 253 or "." not in domain:
        return {"valid": False, "reason": "bad-domain"}
    if not _DOMAIN_RE.match(domain) or ".." in domain or domain.startswith(("-", ".")):
        return {"valid": False, "reason": "bad-domain-format"}
    return {"valid": True, "local": local, "domain": domain, "reason": ""}


# ---------------- module 4-5: DNS / MX ----------------
_resolver = dns.resolver.Resolver()
_resolver.lifetime = 8.0
_resolver.timeout = 4.0


def mx_lookup(domain):
    """Returns (hosts_sorted, error_code_or_None). NXDOMAIN -> ([], 'NXDOMAIN')."""
    try:
        answers = _resolver.resolve(domain, "MX")
        recs = sorted(((r.preference, str(r.exchange).rstrip(".")) for r in answers),
                      key=lambda x: x[0])
        return [h for _, h in recs if h], None
    except dns.resolver.NXDOMAIN:
        return [], "NXDOMAIN"
    except dns.resolver.NoAnswer:
        return [], "NO_MX"
    except dns.exception.Timeout:
        return [], "DNS_TIMEOUT"
    except Exception:
        return [], "DNS_ERROR"


# ---------------- module 9-10: SMTP diagnostics + catch-all ----------------
def _read_reply(f):
    """Read (possibly multi-line) SMTP reply. Returns (code, text)."""
    lines = []
    while True:
        line = f.readline(2048)
        if not line:
            raise ConnectionError("smtp-eof")
        line = line.decode("utf-8", "replace")
        lines.append(line)
        if len(line) >= 4 and line[:3].isdigit() and line[3] == " ":
            return int(line[:3]), "".join(lines).strip()[:300]
        if len(lines) > 20:
            raise ConnectionError("smtp-reply-too-long")


def smtp_rcpt(mx_host, email, hello="example.com", mail_from="verifier@example.com",
             timeout=8.0):
    """Returns (code, message). Raises on transport failure."""
    sock = socket.create_connection((mx_host, 25), timeout=timeout)
    try:
        sock.settimeout(timeout)
        f = sock.makefile("rwb")
        code, _ = _read_reply(f)
        if code != 220:
            raise ConnectionError(f"bad-greeting-{code}")
        f.write(f"EHLO {hello}\r\n".encode())
        f.flush()
        code, _ = _read_reply(f)
        if code != 250:
            f.write(f"HELO {hello}\r\n".encode())
            f.flush()
            code, _ = _read_reply(f)
        f.write(f"MAIL FROM:<{mail_from}>\r\n".encode())
        f.flush()
        code, msg = _read_reply(f)
        if code != 250:
            raise ConnectionError(f"mail-from-rejected-{code}")
        f.write(f"RCPT TO:<{email}>\r\n".encode())
        f.flush()
        code, msg = _read_reply(f)
        try:
            f.write(b"QUIT\r\n")
            f.flush()
        except Exception:
            pass
        return code, msg
    finally:
        try:
            sock.close()
        except Exception:
            pass


_catchall_cache = {}
_catchall_lock = __import__("threading").Lock()


def check_catchall(domain, mx_host, hello, mail_from, timeout):
    with _catchall_lock:
        if domain in _catchall_cache:
            return _catchall_cache[domain]
    fake = f"cbprobe-{int(time.time()*1000)%100000000}@{domain}"
    try:
        code, _ = smtp_rcpt(mx_host, fake, hello, mail_from, timeout)
        res = "yes" if code in (250, 251) else "no"
    except Exception as e:
        res = f"error:{str(e)[:80]}"
    with _catchall_lock:
        _catchall_cache[domain] = res
    return res


# ---------------- module 11-12: confidence engine + audit ----------------
USER_UNKNOWN_HINTS = ("5.1.1", "user unknown", "no such", "not found",
                      "invalid recipient", "does not exist", "mailbox unavailable")


def validate_email(normalized, opts):
    """Full pipeline for one address. opts: smtp(bool), hello, mail_from,
    timeout, strict(bool). Returns structured result + evidence."""
    t0 = time.time()
    ev = {"stages": {}}
    res = {"email": normalized, "normalized": normalized, "domain": "",
           "syntax": "fail", "dns": "unchecked", "has_mx": False, "mx_hosts": [],
           "provider": "", "institution": "", "confidence": 0,
           "status": "UNKNOWN", "reason": "", "evidence": ev}

    syn = check_syntax(normalized)
    ev["stages"]["syntax"] = syn
    if not syn["valid"]:
        res.update(status="INVALID", confidence=99,
                   reason="syntax: " + syn["reason"])
        ev["elapsed_ms"] = int((time.time() - t0) * 1000)
        return res
    res["syntax"] = "pass"
    domain = syn["domain"]
    local = syn["local"]
    res["domain"] = domain
    res["institution"] = "INSTITUTIONAL" if is_institutional(domain) else ""

    if domain in DISPOSABLE:
        res.update(status="INVALID", confidence=85, provider="DISPOSABLE",
                   reason="disposable-domain (policy)")
        ev["stages"]["disposable"] = True
        ev["elapsed_ms"] = int((time.time() - t0) * 1000)
        return res

    hosts, derr = mx_lookup(domain)
    ev["stages"]["dns"] = {"mx": hosts, "error": derr}
    if derr in ("DNS_TIMEOUT", "DNS_ERROR"):
        res.update(status="UNKNOWN", confidence=50, dns="error",
                   reason=f"dns lookup failed ({derr}) - retry later")
        ev["elapsed_ms"] = int((time.time() - t0) * 1000)
        return res
    if not hosts:
        res.update(status="INVALID", confidence=95, dns="nxdomain",
                   reason="no MX records - domain cannot receive mail")
        ev["elapsed_ms"] = int((time.time() - t0) * 1000)
        return res
    res["dns"] = "pass"
    res["has_mx"] = True
    res["mx_hosts"] = hosts
    provider = detect_provider(hosts)
    res["provider"] = provider
    role = local.lower() in ROLE_PREFIX
    free = domain in FREE_PROVIDERS
    ev["stages"]["role"] = role
    ev["stages"]["free_provider"] = free

    if not opts.get("smtp"):
        major = provider in ("GOOGLE_WORKSPACE", "MICROSOFT_365", "YAHOO", "ZOHO",
                             "ICLOUD", "PROTON")
        conf = 82 if major else 70
        if opts.get("strict"):
            conf = min(conf, 75)
        res.update(status="LIKELY", confidence=conf,
                   reason=f"MX OK ({hosts[0]}) - mailbox not probed (SMTP off)"
                   + (" - role-based" if role else ""))
        ev["elapsed_ms"] = int((time.time() - t0) * 1000)
        return res

    # SMTP path (only reached when explicitly authorized)
    hello = opts.get("hello", "example.com")
    mail_from = opts.get("mail_from", "verifier@example.com")
    timeout = float(opts.get("timeout", 8))
    ca = check_catchall(domain, hosts[0], hello, mail_from, timeout)
    ev["stages"]["catchall"] = ca
    if ca.startswith("error:"):
        res.update(status="UNKNOWN", confidence=45,
                   reason=f"smtp unreachable ({ca[6:]}) - port 25 may be blocked")
        ev["elapsed_ms"] = int((time.time() - t0) * 1000)
        return res
    if ca == "yes":
        res.update(status="UNKNOWN", confidence=55,
                   reason="catch-all domain - accepts everything, inbox unconfirmable")
        ev["elapsed_ms"] = int((time.time() - t0) * 1000)
        return res
    try:
        code, msg = smtp_rcpt(hosts[0], normalized, hello, mail_from, timeout)
    except Exception as e:
        res.update(status="UNKNOWN", confidence=45,
                   reason=f"smtp transport failed ({str(e)[:80]})")
        ev["elapsed_ms"] = int((time.time() - t0) * 1000)
        return res
    ev["stages"]["smtp"] = {"code": code, "message": msg[:120]}
    low = msg.lower()
    if code in (250, 251):
        conf = 90 if not opts.get("strict") else 88
        res.update(status="LIVE", confidence=conf,
                   reason=f"SMTP {code} accepted (mailbox evidence)"
                   + (" - role-based" if role else ""))
    elif 500 <= code < 600:
        conf = 97 if any(h in low for h in USER_UNKNOWN_HINTS) else 90
        res.update(status="INVALID", confidence=conf,
                   reason=f"SMTP {code} rejected ({msg[:90]})")
    else:
        res.update(status="UNKNOWN", confidence=55,
                   reason=f"SMTP {code} deferral/unclear ({msg[:90]})")
    ev["elapsed_ms"] = int((time.time() - t0) * 1000)
    return res
