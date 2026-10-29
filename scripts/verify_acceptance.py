#!/usr/bin/env python3
"""Verify-on-demand acceptance (hardened) — the self-growing loop, kept honest.

Extraction is exercised across real page SHAPES, not just the demo page, and the
fetch path is restricted to the site index Andy already holds. Every case the
hardening pass must pass, by name:

  a. standard location page -> verdict, verbatim quote, named source, date extract
  b. multiple verdict words  -> the verdict anchored to "Last verified" wins
  c. missing "Last verified" -> fail closed, missing field named, never guessed
  d. missing named source    -> fail closed, never guessed
  e. a law/club/guide page   -> fail closed, never promoted
  f. a fetch failure         -> staged with the fetch error, never promoted
  g. out-of-index URL        -> refused WITHOUT a fetch ("URL not in site index")
  h. confirmed-secondary caveat present in BOTH the reply and the receipt
  i. fetch() records every redirect (requested url, each hop, final url) against a
     LOCAL redirecting server, and never requests a hop that leaves the allowed site
  j. propose(): a redirect off wheretodetect.org, or to a wheretodetect url that is
     not in the index, is refused — no extraction, no proposal — and the receipt
     records the requested url, the final url, and the chain; a redirect between two
     indexed pages is allowed, and the receipt and the proposal name the final url
  k. name matching: a query under 3 characters or a bare substring (not a whole word)
     has no candidate and fetches nothing; a word matching several pages stages with
     the list and fetches nothing until the owner names one; an exact label still
     verifies; the D5+N1 partial-name approval ("Cocoa") still loads after a restart

Core runs hermetically: a real index URL with fetch() monkeypatched to return a
fixture, so the fetch restriction passes while the page content stays fixed. One
live fetch of a real page is reported at the end.
"""

from __future__ import annotations

import hashlib
import http.server
import sys
import threading
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from agent import detect, tier2, verify_source as vs, voice  # noqa: E402
from agent.verify_source import KnowledgeStore  # noqa: E402
from receipts import ReceiptChain, verify_chain  # noqa: E402

RUNS = ROOT / "runs"
CHAIN = RUNS / "verify-receipts.jsonl"
PERS = RUNS / "verify-accept-cs.json"  # temp persist file (gitignored) — not the tracked one
# A real location URL that IS in the index, so the fetch restriction passes.
INDEX_URL = "https://wheretodetect.org/metal-detecting/florida/daytona-beach/"

STANDARD = """<html><body>
<h1>Can You Metal Detect at Testville Beach? Yes</h1>
<div>Testville County &middot; Central &middot; City beach ✅ Allowed Last verified: 2026-09-15</div>
<h2>The rules</h2>
<p>The Testville Beach Code says nothing about metal detecting and permits it on the public beach.</p>
<div>Permit: Not required</div>
<p>More spots near Testville 🔴 Prohibited Testville National Seashore — federal land.</p>
<p>Source: Testville County Code of Ordinances, Ch. 20, Sec. 20-6. Verify against the county.</p>
<p>Not legal advice.</p></body></html>"""

MULTI_VERDICT = """<html><body>
<h1>Can You Metal Detect at Multi Beach?</h1>
<p>Nearby parks are Prohibited and some areas are Restricted, but this beach is different.</p>
<div>Multi County ✅ Allowed Last verified: 2026-08-01</div>
<h2>The rules</h2><p>The Multi County code allows detecting on the public beach.</p>
<div>Permit: Not required</div>
<p>More spots near Multi 🔴 Prohibited Somewhere NPS.</p>
<p>Source: Multi County Code, Ch. 5. Verify against the county.</p></body></html>"""

NO_DATE = """<html><body><div>✅ Allowed</div>
<h2>The rules</h2><p>Detecting is allowed on the public beach.</p><div>Permit: Not required</div>
<p>Source: County Code, Ch. 20.</p></body></html>"""

NO_SOURCE = """<html><body><div>✅ Allowed Last verified: 2026-09-15</div>
<h2>The rules</h2><p>Detecting is allowed on the public beach.</p><div>Permit: Not required</div></body></html>"""

LAW_PAGE = """<html><body>
<h1>Florida Metal Detecting Laws</h1>
<p>Florida state parks generally prohibit metal detecting except in designated swim
areas. County and city rules vary. Always confirm with the managing authority.</p>
<h2>State parks</h2><p>Detecting requires a permit in many parks.</p>
<p>Federal land is governed by ARPA.</p></body></html>"""


def _ok_fetch(html):
    return lambda url, timeout=30.0: {"ok": True, "html": html,
                                      "sha256": hashlib.sha256(html.encode()).hexdigest(),
                                      "bytes": len(html.encode())}


def _fail_fetch(url, timeout=30.0):
    return {"ok": False, "error": "URLError: unreachable (timed out)"}


def main() -> int:
    RUNS.mkdir(exist_ok=True)
    CHAIN.unlink(missing_ok=True)
    PERS.unlink(missing_ok=True)
    chain = ReceiptChain(CHAIN)
    checks = {}
    saved = vs.fetch

    # ---- extraction across page shapes (hermetic, no network) ----
    a = vs.extract(STANDARD)
    ta = vs._text(STANDARD)
    checks["a. standard page: verdict + verbatim quote + named source + date"] = (
        a["ok"] and a["verdict"] == "Allowed" and a["verified_date"] == "2026-09-15"
        and a["quote"] in ta and a["source"] in ta and "Testville Beach Code" in a["quote"])

    b = vs.extract(MULTI_VERDICT)
    checks["b. multiple verdict words: the one at 'Last verified' wins (Allowed)"] = (
        b["ok"] and b["verdict"] == "Allowed")

    c = vs.extract(NO_DATE)
    checks["c. missing 'Last verified': fails closed, names the missing field"] = (
        (not c["ok"]) and "last-verified date" in c["error"])

    d = vs.extract(NO_SOURCE)
    checks["d. missing named source: fails closed"] = (
        (not d["ok"]) and "named source" in d["error"])

    e = vs.extract(LAW_PAGE)
    checks["e. a law/guide page (not a location): fails closed"] = (not e["ok"])

    # ---- f. fetch failure stages, never promotes ----
    store_f = KnowledgeStore(persist_path=str(PERS))
    vs.fetch = _fail_fetch
    try:
        rf = store_f.propose(chain, "Daytona Beach", INDEX_URL)
    finally:
        vs.fetch = saved
    fetch_rcpt = [r["action"] for r in chain.receipts()
                  if r["action"]["type"] == "verify_fetch" and r["action"].get("place") == "Daytona Beach"]
    checks["f. fetch failure: staged with the fetch error, never promoted"] = (
        (not rf["ok"]) and store_f.get("Daytona Beach") is None
        and bool(fetch_rcpt) and fetch_rcpt[-1]["fetched_ok"] is False and fetch_rcpt[-1].get("reason"))

    # ---- g. out-of-index URL refused WITHOUT a fetch ----
    called = {"fetch": False}

    def _tripwire(url, timeout=30.0):
        called["fetch"] = True
        return {"ok": True, "html": STANDARD, "sha256": "x", "bytes": 1}

    store_g = KnowledgeStore(persist_path=str(PERS))
    vs.fetch = _tripwire
    try:
        rg = store_g.propose(chain, "Evil Place", "https://evil.example/x")
    finally:
        vs.fetch = saved
    g_rcpt = [r["action"] for r in chain.receipts()
              if r["action"]["type"] == "verify_fetch" and r["action"].get("place") == "Evil Place"]
    checks["g. out-of-index URL refused WITHOUT a fetch (URL not in site index)"] = (
        (not rg["ok"]) and ("not in site index" in rg["error"])
        and (called["fetch"] is False)
        and bool(g_rcpt) and g_rcpt[-1]["reason"] == "URL not in site index")

    # ---- h. confirmed-secondary caveat in BOTH the reply and the receipt ----
    store_h = KnowledgeStore(persist_path=str(PERS))
    vs.fetch = _ok_fetch(STANDARD)
    try:
        store_h.propose(chain, "Testville Beach", INDEX_URL)
    finally:
        vs.fetch = saved
    before = detect.answer(chain, "Testville Beach", store=store_h)["outcome"]
    store_h.confirm(chain, "Testville Beach")
    after = detect.answer(chain, "Testville Beach", store=store_h)
    o = after["outcome"]
    reply = voice._detect_reply(o)
    rcpt = after["answer_receipt"]["action"]
    caveat = (o.get("caveat") or "").lower()
    needed = ("read the site", "ordinance", "approved", "confirm the primary")
    checks["h. before approval the place is STAGED (not answered)"] = (before["decision"] == detect.STAGED)
    checks["h. after approval: confirmed secondary (answered_with_caveat)"] = (
        o["decision"] == detect.ANSWERED_WITH_CAVEAT and o["evidence_tier"] == vs.CONFIRMED_SECONDARY)
    checks["h. caveat present in the reply (not a bare 'allowed')"] = all(w in reply.lower() for w in needed)
    checks["h. caveat present in the receipt, never Tier 1"] = (
        all(w in (rcpt.get("caveat") or "").lower() for w in needed)
        and rcpt.get("evidence_tier") == vs.CONFIRMED_SECONDARY and rcpt.get("evidence_tier") != "primary")

    # ---- i. fetch() against a LOCAL redirecting server (never the live site) ----
    hits = {"site": [], "away": []}

    def _server(tag, routes):
        class H(http.server.BaseHTTPRequestHandler):
            def do_GET(self):
                hits[tag].append(self.path)
                kind, val = routes.get(self.path, ("page", b"<p>nothing here</p>"))
                if kind == "redirect":
                    self.send_response(302)
                    self.send_header("Location", val)
                    self.end_headers()
                else:
                    self.send_response(200)
                    self.send_header("Content-Type", "text/html")
                    self.end_headers()
                    self.wfile.write(val)

            def log_message(self, *a):
                pass
        srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), H)
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        return srv

    away = _server("away", {})                         # stands in for an off-site host
    a_base = f"http://127.0.0.1:{away.server_address[1]}"
    routes = {}                                        # filled once the port is known
    site = _server("site", routes)
    s_base = f"http://127.0.0.1:{site.server_address[1]}"
    page_c = STANDARD.encode()
    routes.update({"/a": ("redirect", f"{s_base}/b"), "/b": ("redirect", "/c"), "/c": ("page", page_c),
                   "/off": ("redirect", f"{a_base}/x")})
    try:
        fi = vs.fetch(f"{s_base}/a", allowed_prefix=f"{s_base}/")
        hits["away"].clear()
        fo = vs.fetch(f"{s_base}/off", allowed_prefix=f"{s_base}/")
        fd = vs.fetch(f"{s_base}/off")                 # default: only https://wheretodetect.org/ hops
    finally:
        site.shutdown(); away.shutdown()
    checks["i. fetch(): a two-hop same-site redirect records requested -> hop -> final, sha of the final page"] = (
        fi["ok"] and fi["redirect_chain"] == [f"{s_base}/a", f"{s_base}/b", f"{s_base}/c"]
        and fi["final_url"] == f"{s_base}/c" and fi["sha256"] == hashlib.sha256(page_c).hexdigest())
    checks["i. fetch(): a hop off the allowed site is recorded and NOT requested"] = (
        not fo["ok"] and fo.get("left_site") and fo["redirect_chain"] == [f"{s_base}/off", f"{a_base}/x"]
        and fo["final_url"] == f"{a_base}/x" and hits["away"] == []
        and not fd["ok"] and fd.get("left_site"))

    # ---- j. propose(): judged on the FINAL url and the whole chain ----
    COCOA = "https://wheretodetect.org/metal-detecting/florida/cocoa-beach/"
    UNINDEXED = "https://wheretodetect.org/metal-detecting/florida/nowhere-beach/"
    OFFSITE = "https://evil.example/daytona-beach/"
    sha = hashlib.sha256(STANDARD.encode()).hexdigest()

    def _redirected(final, ok=True, extra=None):
        hops = [INDEX_URL] + (extra or []) + [final]
        if not ok:
            return lambda url, timeout=30.0: {"ok": False, "error": f"redirect leaves {vs.SITE} (to {final}) — not followed",
                                              "final_url": final, "redirect_chain": hops, "left_site": True}
        return lambda url, timeout=30.0: {"ok": True, "html": STANDARD, "sha256": sha, "bytes": len(STANDARD),
                                          "final_url": final, "redirect_chain": hops}

    def _try(fetcher, place):
        store = KnowledgeStore(persist_path=str(PERS))
        n0 = len(chain.receipts())
        vs.fetch = fetcher
        try:
            res = store.propose(chain, place, INDEX_URL)
        finally:
            vs.fetch = saved
        new = [r["action"] for r in chain.receipts()[n0:]]
        vf = next((a for a in new if a["type"] == "verify_fetch"), {})
        return res, store, vf, [a for a in new if a["type"] == "verify_extract"]

    r_off, st_off, vf_off, ex_off = _try(_redirected(OFFSITE, ok=False), "Daytona Beach")
    checks["j. indexed url -> off-site redirect: refused, no extraction, no proposal"] = (
        not r_off["ok"] and not ex_off and st_off.pending == {})
    checks["j. ... and the receipt records the requested url, the off-site final url, and the chain"] = (
        vf_off.get("requested_url") == INDEX_URL and vf_off.get("final_url") == OFFSITE
        and vf_off.get("redirect_chain") == [INDEX_URL, OFFSITE] and vf_off.get("fetched_ok") is False)
    r_bounce, st_bounce, vf_bounce, ex_bounce = _try(
        _redirected(COCOA, extra=["https://evil.example/hop"]), "Daytona Beach")
    checks["j. a chain that leaves the site mid-way is refused even if it lands back on an indexed page"] = (
        not r_bounce["ok"] and not ex_bounce and st_bounce.pending == {}
        and "left wheretodetect.org" in (vf_bounce.get("reason") or ""))
    r_un, st_un, vf_un, ex_un = _try(_redirected(UNINDEXED), "Daytona Beach")
    checks["j. indexed url -> unindexed wheretodetect url: refused, no extraction, no proposal"] = (
        not r_un["ok"] and not ex_un and st_un.pending == {} and vf_un.get("final_url") == UNINDEXED
        and "not in the site index" in (vf_un.get("reason") or ""))
    r_ok, st_ok, vf_ok, ex_ok = _try(_redirected(COCOA), "Daytona Beach")
    prop = (r_ok.get("proposal") or {})
    checks["j. indexed url -> another indexed url: allowed; receipt + proposal name the final url and chain"] = (
        r_ok["ok"] and prop.get("url") == COCOA and prop.get("requested_url") == INDEX_URL
        and prop.get("redirect_chain") == [INDEX_URL, COCOA] and vf_ok.get("final_url") == COCOA
        and vf_ok.get("redirect_chain") == [INDEX_URL, COCOA] and vf_ok.get("page_sha256") == sha
        and ex_ok and ex_ok[0].get("url") == COCOA)

    # ---- k. name matching ----
    fetched = []

    def _counting(url, timeout=30.0):
        fetched.append(url)
        return {"ok": True, "html": STANDARD, "sha256": sha, "bytes": len(STANDARD),
                "final_url": url, "redirect_chain": [url]}

    vs.fetch = _counting
    try:
        store_k = KnowledgeStore(persist_path=str(PERS))
        short = [voice.chat_turn(chain, m, store=store_k, voice=False, demo=True) for m in ("verify a", "verify ab")]
        checks["k. a query under 3 characters has no candidate and fetches nothing"] = (
            tier2.candidates("a") == [] and tier2.candidates("ab") == [] and fetched == []
            and all(not r["result"]["ok"] for r in short))
        bare = voice.chat_turn(chain, "verify ona", store=store_k, voice=False, demo=True)
        checks["k. a bare substring that is not a whole word ('ona', 'cocoa bea') has no candidate"] = (
            tier2.candidates("ona") == [] and tier2.candidates("cocoa bea") == []
            and not bare["result"]["ok"] and fetched == [])
        many = detect.answer(chain, "Clearwater", store=store_k)["outcome"]
        it = store_k.propose(chain)                       # "verify it" on the last staged candidate
        checks["k. a word matching several pages stages with the list and fetches nothing"] = (
            many["decision"] == detect.STAGED and len(many["tier2_candidates"]) == 2
            and not it["ok"] and "several site pages match" in it["error"] and fetched == []
            and store_k.pending == {})
        picked = voice.chat_turn(chain, "verify Clearwater Beach", store=store_k, voice=False, demo=True)
        checks["k. ... once the owner names one, that page (and only it) is fetched"] = (
            picked["result"]["ok"] and len(fetched) == 1 and fetched[0].endswith("/clearwater-beach/"))
        fetched.clear()
        detect.answer(chain, "Daytona Beach", store=store_k)
        ex = store_k.propose(chain)
        checks["k. an exact label match still verifies as before"] = (
            ex["ok"] and fetched == [INDEX_URL] and ex["proposal"]["url"] == INDEX_URL)
        cs_pn = RUNS / "verify-accept-pn-cs.json"
        cs_pn.unlink(missing_ok=True)
        s_pn = KnowledgeStore(persist_path=str(cs_pn))
        detect.answer(chain, "Cocoa", store=s_pn)
        s_pn.propose(chain); s_pn.confirm(chain)
        o_pn = detect.answer(chain, "Cocoa", store=KnowledgeStore(persist_path=str(cs_pn)))["outcome"]
        checks["k. D5+N1 loose rule unchanged: 'Cocoa' (one page) still verifies and loads after restart"] = (
            o_pn["decision"] == detect.ANSWERED_WITH_CAVEAT and o_pn["evidence_tier"] == vs.CONFIRMED_SECONDARY)
        cs_pn.unlink(missing_ok=True)
    finally:
        vs.fetch = saved

    # ---- receipts + chain ----
    ok, reason = verify_chain(CHAIN)
    checks["chain verifies end to end"] = ok

    for label, passed in checks.items():
        print(f"  [{'PASS' if passed else 'FAIL'}] {label}")

    live = vs.fetch("https://wheretodetect.org/metal-detecting/florida/daytona-beach/")
    if live["ok"]:
        lex = vs.extract(live["html"])
        print(f"\n  live check: Daytona Beach -> extract ok={lex['ok']} verdict={lex.get('verdict')} "
              f"(quote verbatim={lex.get('quote', '') in vs._text(live['html'])})")
    else:
        print(f"\n  live check skipped (no network): {live['error']}")

    if all(checks.values()):
        print("\nVERIFY-ON-DEMAND (HARDENED) ACCEPTANCE: PASS")
        return 0
    print("\nVERIFY-ON-DEMAND (HARDENED) ACCEPTANCE: FAIL")
    return 1


if __name__ == "__main__":
    sys.exit(main())
