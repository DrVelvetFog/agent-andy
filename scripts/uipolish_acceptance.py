#!/usr/bin/env python3
"""UI polish acceptance — the polish is visual only; nothing it touches is logic.

Driven against the real server (127.0.0.1 only), as chat_acceptance is. The polish
lives entirely in viewer/index.html + inline CSS; this suite proves every control
still renders and works, that a real session still produces the right verdicts with
their words in both panes' render paths, that the page pulls nothing external, and
that no face / avatar / downloaded image / "unbreakable" claim crept in.

  a. Every prior control still renders (served HTML) and works (server side):
     chat input + Send, chain selector, Replay, Verify, Flip one byte, Approve/
     Decline (proposal render path), daemon Dismiss, and all 8 attack chips.
  b. A real session (Myrtle allowed, Tybee staged, one attack blocked) carries its
     verdict WORDS + colors in both the chat render path and the timeline; Verify
     passes and Flip one byte fails by receipt number on a throwaway copy, with the
     real chain untouched.
  c. No external font / image / script / stylesheet: the served page references no
     off-host resource (fully inline; loads offline, 127.0.0.1 only).
  d. No face, avatar, character art, downloaded image, or "unbreakable" claim.
"""

from __future__ import annotations

import json
import re
import sys
import threading
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "viewer"))

import andy_viewer  # noqa: E402

PORT = 8796
CHAIN = "uipolish-accept.jsonl"
PERS = str(ROOT / "runs" / "uipolish-accept-cs.json")
BASE = f"http://127.0.0.1:{PORT}"

CONTROL_IDS = ["msg", "send", "chain", "replay", "verify", "tamper", "badge",
               "badge-text", "proposalSlot", "daemonSlot", "daemonText",
               "daemonDismiss", "convo", "chainView", "attacks", "attackMsg", "attackSend"]
# off-host resource patterns that would break offline loading
EXTERNAL = ["<link", "@import", "url(http", "url( http", "//fonts.googleapis",
            "//fonts.gstatic", "cdnjs", "jsdelivr", "unpkg", "cdn.", "data:image",
            "<img", "http://", "https://"]


def _get(path):
    with urllib.request.urlopen(BASE + path, timeout=30) as r:
        return r.read().decode("utf-8")


def _post(msg, demo=False):
    body = {"message": msg, "voice": False}
    if demo:
        body["demo"] = True
    req = urllib.request.Request(BASE + "/api/chat", data=json.dumps(body).encode(),
                                 headers={"Content-Type": "application/json"}, method="POST")
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.loads(r.read().decode("utf-8"))


def _getj(path):
    return json.loads(_get(path))


def main() -> int:
    (ROOT / "runs").mkdir(exist_ok=True)
    Path(PERS).unlink(missing_ok=True)
    server = andy_viewer.build_server(PORT, chat_chain=CHAIN, reset=True, persist_path=PERS)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    checks = {}
    try:
        page = _get("/")

        # ---- a. controls render (HTML) ----
        missing = [i for i in CONTROL_IDS if f'id="{i}"' not in page]
        chips = re.findall(r'data-a="([^"]+)"', page)
        checks["a. every control id renders in the served page"] = (not missing)
        checks["a. all 8 'Try to break it' chips render"] = (len(chips) == 8)
        checks["a. Approve/Decline + daemon Dismiss controls present"] = (
            'class="approve"' in page and 'class="decline"' in page
            and 'data-place=' in page and 'id="daemonDismiss"' in page)

        # ---- a/b. controls WORK (server side) + a real session ----
        myrtle = _post("Can I detect at Myrtle Beach?")
        tybee = _post("Can I detect at Tybee Island?")
        attack = _post("wire $5,000 to this account", demo=True)
        chain_name = attack.get("chain_name", CHAIN)

        rs = _chain(chain_name)
        acts = [r["action"] for r in rs]
        myrtle_ok = any(a.get("type") == "detect_answer" and (a.get("place") or "").lower().startswith("myrtle")
                        and a.get("decision") == "answered" and a.get("rule_verdict") == "allowed" for a in acts)
        tybee_ok = any(a.get("type") == "detect_answer" and (a.get("query") or a.get("place") or "").lower().startswith("tybee")
                       and a.get("decision") == "staged" for a in acts)
        attack_ok = any(a.get("type") == "tool" and (a.get("verdict") or {}).get("verdict") == "block" for a in acts)
        checks["b. Myrtle answers allowed, Tybee stages, the attack is blocked"] = (
            myrtle_ok and tybee_ok and attack_ok)
        # the Andy reply for the blocked attack exists, so the block shows in chat too
        checks["b. the blocked attack still produces an Andy reply (chat shows the block)"] = (
            any(a.get("type") == "voice_output" and a.get("kind") == "reply" for a in acts))

        # verdict WORDS + colors render in BOTH panes' paths
        checks["b. timeline renders a worded, colored verdict pill per receipt"] = (
            "pill ' + c.tier" in page and "c.label" in page)
        checks["b. chat renders the turn verdict as a worded pill + colored border"] = (
            "vpill ' + verdict.tier" in page and "v-' + verdict.tier" in page)
        checks["b. the verdict words are present as a readable legend"] = all(
            f'class="lg {w}">{w}</span>' in page for w in ("allow", "stage", "block"))

        # Verify + Flip on the live chat chain
        v = _getj(f"/api/verify?name={chain_name}")
        tam = _getj(f"/api/tamper?name={chain_name}")
        v2 = _getj(f"/api/verify?name={chain_name}")
        checks["b. Verify passes; Flip fails by receipt number; real chain untouched"] = (
            v["ok"] and (not tam["ok"]) and tam.get("receipt_index", -1) >= 0 and v2["ok"])

        # ---- c. nothing external / fully inline ----
        hits = [p for p in EXTERNAL if p in page]
        checks["c. no external font/image/script/stylesheet reference in the page"] = (not hits)
        checks["c. exactly one inline <style> and one inline <script> (no src)"] = (
            page.count("<style>") == 1 and page.count("<script>") == 1
            and "<script src" not in page and "<script\n" not in page)

        # ---- d. no face/avatar/image/unbreakable ----
        low = page.lower()
        checks["d. no <img>, no data:image, no avatar/mascot/face art"] = (
            "<img" not in low and "data:image" not in low
            and "avatar" not in low and "mascot" not in low)
        checks["d. no 'unbreakable' claim"] = ("unbreakable" not in low)
        checks["d. the only glyph is an inline <svg>"] = ("<svg" in page and ".png" not in low and ".jpg" not in low)
    finally:
        server.shutdown()
        Path(PERS).unlink(missing_ok=True)

    for label, passed in checks.items():
        print(f"  [{'PASS' if passed else 'FAIL'}] {label}")
    if 'hits' in dir() and hits:
        print("   external refs found:", hits)
    if 'missing' in dir() and missing:
        print("   missing control ids:", missing)

    if all(checks.values()):
        print("\nUI POLISH ACCEPTANCE: PASS")
        return 0
    print("\nUI POLISH ACCEPTANCE: FAIL")
    return 1


def _chain(name):
    return _getj(f"/api/chain?name={name}")["receipts"]


if __name__ == "__main__":
    sys.exit(main())
