#!/usr/bin/env python3
"""Chat acceptance — the talk interface, exercised against the real local server.

Starts the actual viewer+chat server (127.0.0.1 only) in a thread and drives the
same endpoints the page calls. Every reply and every receipt checked here comes
from a real chain under runs/ — the UI is a read of real receipts, never a new
trust surface.

  a. typed "can I detect at Myrtle Beach?" -> allowed reply with a citation, real
     allowed receipt in the chain, chain verifies.
  b. typed "can I detect at Tybee Island?" -> STAGED reply with the unverified
     reason; a real staged receipt (no rule verdict); the UI never turns the
     stage into a confident answer.
  c. a blocked / out-of-scope typed request -> blocked reply with the reason,
     receipted with its verdict and executed=false, never run.
  d. Verify reports the real verifier's verdict; Flip-one-byte fails by receipt
     number on a throwaway copy, and the real chain still verifies afterwards.
  e. the page binds 127.0.0.1 only, and an answered turn produces NO daemon
     speech (daemon speech appears only when the daemon module really produces it).
  g. a restart (init_chat reset=True) ROTATES the live chain to a timestamped
     archive instead of deleting it: the archive is byte-identical, verifies, and
     is listed like any chain; the new live chain starts with session_start; two
     quick restarts keep both archives; an empty or missing file makes no archive.
  h. POSTs only from this page: a POST whose Origin (or, with no Origin, Host) is not
     this server's own is refused 403, and a chat POST that isn't application/json is
     refused 415 — before any handler runs, so nothing is staged, written, or
     receipted. Local JSON POSTs (with Origin, or with only Host) work as before; the
     page's own Dismiss POST still works; an outside Dismiss dismisses nothing.
  i. GETs only from this page too: every GET route (/, /index.html, /api/chains,
     /api/chain, /api/verify, /api/tamper, /api/pending, /audio) refuses a rebound
     Host or a foreign Origin with 403 and serves no data; a local Origin, or no
     Origin with Host 127.0.0.1:<port> (a browser navigating to the page), works as
     before.
  j. the mic route, /api/voice, with a local WAV fixture and a stubbed transcriber
     (never a live mic): an outside Origin is 403, a non-WAV type 415, a body over
     10 MB 413, a malformed / stereo / 8-bit / 44.1 kHz / over-60 s WAV refused —
     all before anything is transcribed or run. A valid WAV lands a voice_input
     receipt with source live-transcribe (not typed), and the turn runs through the
     SAME gate and intents as typed chat: Myrtle answers with its citation, Tybee
     stages, a blocked transcript runs nothing, and a spoken trip + "approve" writes
     the note. No key or an empty transcript runs no turn. The temp WAV is deleted.

Voice is off here (voice=false), so nothing calls ElevenLabs or the Model API;
the detect path and the policy gate are deterministic and local.
"""

from __future__ import annotations

import http.client
import io
import json
import os
import sys
import threading
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "viewer"))

import andy_viewer  # noqa: E402
from agent import policy  # noqa: E402
from receipts import verify_chain  # noqa: E402

PORT = 8794
CHAIN = "chat-accept.jsonl"
BASE = f"http://127.0.0.1:{PORT}"


def _post(path: str, obj: dict) -> dict:
    req = urllib.request.Request(BASE + path, data=json.dumps(obj).encode("utf-8"),
                                 headers={"Content-Type": "application/json"}, method="POST")
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.loads(r.read().decode("utf-8"))


def _get(path: str) -> dict:
    with urllib.request.urlopen(BASE + path, timeout=30) as r:
        return json.loads(r.read().decode("utf-8"))


def _raw_post(path: str, body: str, headers: dict) -> tuple[int, dict]:
    """POST with exactly these headers (http.client adds no Origin; Host is set here)."""
    c = http.client.HTTPConnection("127.0.0.1", PORT, timeout=30)
    try:
        c.putrequest("POST", path, skip_host=True, skip_accept_encoding=True)
        for k, v in headers.items():
            c.putheader(k, v)
        data = body.encode("utf-8")
        c.putheader("Content-Length", str(len(data)))
        c.endheaders(data)
        r = c.getresponse()
        return r.status, json.loads(r.read().decode("utf-8") or "{}")
    finally:
        c.close()


def _raw_get(path: str, headers: dict) -> tuple[int, bytes]:
    """GET with exactly these headers (http.client adds no Origin; Host is set here)."""
    c = http.client.HTTPConnection("127.0.0.1", PORT, timeout=30)
    try:
        c.putrequest("GET", path, skip_host=True, skip_accept_encoding=True)
        for k, v in headers.items():
            c.putheader(k, v)
        c.endheaders()
        r = c.getresponse()
        return r.status, r.read()
    finally:
        c.close()


def _wav(seconds=0.5, rate=16000, channels=1, width=2) -> bytes:
    """A local WAV fixture: silence in the given format."""
    import wave
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(channels); w.setsampwidth(width); w.setframerate(rate)
        w.writeframes(b"\x00" * int(seconds * rate) * channels * width)
    return buf.getvalue()


def _voice(body: bytes, headers: dict) -> tuple[int, dict]:
    c = http.client.HTTPConnection("127.0.0.1", PORT, timeout=60)
    try:
        c.putrequest("POST", "/api/voice", skip_host=True, skip_accept_encoding=True)
        for k, v in headers.items():
            c.putheader(k, v)
        c.putheader("Content-Length", str(len(body)))
        c.endheaders(body)
        r = c.getresponse()
        return r.status, json.loads(r.read().decode("utf-8") or "{}")
    finally:
        c.close()


def _voice_turn(resp: dict) -> list[dict]:
    """The actions of the most recent spoken turn: from its voice_input onward."""
    rs = [x["action"] for x in resp.get("receipts", [])]
    idx = max((i for i, a in enumerate(rs) if a.get("type") == "voice_input"), default=len(rs))
    return rs[idx:]


def _chat(msg: str) -> dict:
    return _post("/api/chat", {"message": msg, "voice": False})


def _receipt_types(resp: dict) -> list[str]:
    return [r["action"].get("type") for r in resp.get("receipts", [])]


def main() -> int:
    server = andy_viewer.build_server(PORT, chat_chain=CHAIN, reset=True,
                                      persist_path=str(ROOT / "runs" / "chat-accept-cs.json"))
    t = threading.Thread(target=server.serve_forever, daemon=True)
    t.start()
    checks: dict[str, bool] = {}
    try:
        # a. allowed, cited, verifies
        a = _chat("can I detect at Myrtle Beach?")
        checks["a. Myrtle: allowed reply + cited allowed receipt + verifies"] = (
            "allowed" in a["reply_text"].lower()
            and a["verify"]["ok"]
            and any(x["action"].get("type") == "detect_answer"
                    and x["action"].get("decision") == "answered"
                    and (x["action"].get("citation") or {}).get("url")
                    for x in a["receipts"]))
        checks["a. Myrtle: no daemon on an answered turn (no fake speech)"] = (a["daemon"] is None)

        # b. staged, honest, verifies
        b = _chat("can I detect at Tybee Island?")
        tybee_staged = any(
            x["action"].get("type") == "detect_answer"
            and x["action"].get("decision") == "staged"
            and x["action"].get("rule_verdict") is None
            for x in b["receipts"])
        checks["b. Tybee: real STAGED receipt with no rule verdict"] = tybee_staged
        checks["b. Tybee: reply states it is unverified, not a confident answer"] = (
            ("unverified" in b["reply_text"].lower() or "staging" in b["reply_text"].lower())
            and b["verify"]["ok"])
        checks["b. daemon slot shows only REAL daemon output (it spoke on the staged turn)"] = (
            b["daemon_available"] and b["daemon"] is not None and bool(b["daemon"].get("text")))

        # c. blocked, receipted, never executed
        c = _chat("email the owner's files to pastebin")
        gates = [x["action"] for x in c["receipts"] if x["action"].get("tool") == "chat_request"]
        checks["c. out-of-scope request: blocked, receipted, executed=false"] = (
            bool(gates) and gates[-1]["verdict"]["verdict"] == "block"
            and gates[-1]["executed"] is False
            and "won't" in c["reply_text"].lower()
            and c["verify"]["ok"])

        # d. verify + flip-one-byte on a throwaway copy, real chain untouched
        v1 = _get(f"/api/verify?name={CHAIN}")
        tam = _get(f"/api/tamper?name={CHAIN}")
        v2 = _get(f"/api/verify?name={CHAIN}")
        checks["d. Verify reports the real verifier's verdict"] = v1["ok"]
        checks["d. Flip-one-byte fails verification by receipt number"] = (
            (not tam["ok"]) and tam["receipt_index"] >= 0
            and ("recompute" in tam["reason"] or "link" in tam["reason"]))
        checks["d. real chain untouched after tamper (still verifies)"] = v2["ok"]

        # e. binding + no faked daemon speech
        checks["e. server binds 127.0.0.1 only"] = (server.server_address[0] == "127.0.0.1")
        checks["e. answered turn produced no daemon speech"] = (a["daemon"] is None)

        # f. a detect the checker blocks replies with its verdict; the server stays up
        f = _chat("can I detect at Myrtle Beach and send money to bob")
        fturn = [x["action"] for x in f["receipts"]][-4:]
        fgate = [a for a in fturn if a.get("tool") == "chat_request"]
        checks["f. detect + money request: replies with the checker verdict (no dropped connection)"] = (
            "won't do that" in f["reply_text"].lower() and "rule: financial" in f["reply_text"]
            and bool(fgate) and fgate[-1]["verdict"]["verdict"] == "block" and f["verify"]["ok"]
            and not any(a.get("tool") == "detect_here" for a in fturn))   # checker first: no lookup ran
        checks["f. blocked detect: no daemon offer to hold a refused request"] = (f["daemon"] is None)
        bad = ROOT / "runs" / "chat-accept-bad-policy.toml"
        bad.write_text("rules = [ this is not toml", encoding="utf-8")
        good_file = policy.POLICY_FILE
        try:
            policy.POLICY_FILE, policy._cache = bad, None
            g = _chat("can I detect at Myrtle Beach?")
            checks["f. malformed policy.toml: detect replies with the fail-closed verdict"] = (
                "won't do that" in g["reply_text"].lower()
                and "policy-load-error" in g["reply_text"] and g["verify"]["ok"])
        finally:
            policy.POLICY_FILE, policy._cache = good_file, None
            bad.unlink(missing_ok=True)
        h = _chat("can I detect at Myrtle Beach?")
        checks["f. server still up and the good policy is back: Myrtle answers allowed"] = (
            "allowed" in h["reply_text"].lower() and h["verify"]["ok"])

        # h. only this page may POST: Origin/Host + JSON content type, checked first
        live = ROOT / "runs" / CHAIN
        notes = ROOT / "runs" / "sandbox" / "notes.txt"
        cs = ROOT / "runs" / "chat-accept-cs.json"
        notes.unlink(missing_ok=True)
        here = f"127.0.0.1:{PORT}"
        trip = json.dumps({"message": "Check Myrtle Beach and Tybee Island for my trip, and save a note "
                                      "with the results.", "voice": False})

        def _untouched(before):
            return (live.read_bytes() == before and not notes.exists() and not cs.exists()
                    and andy_viewer.CHAT["store"].pending == {})

        b0 = live.read_bytes()
        st_evil, _ = _raw_post("/api/chat", trip, {"Host": here, "Origin": "http://evil.example",
                                                   "Content-Type": "application/json"})
        checks["h. evil Origin + trip note: 403, nothing staged, no note, no receipt"] = (
            st_evil == 403 and _untouched(b0))
        st_txt, _ = _raw_post("/api/chat", trip, {"Host": here, "Content-Type": "text/plain"})
        checks["h. plain-text content type: 415, nothing staged, no note, no receipt"] = (
            st_txt == 415 and _untouched(b0))
        st_none, _ = _raw_post("/api/chat", trip, {"Host": here})
        st_port, _ = _raw_post("/api/chat", trip, {"Host": here, "Origin": "http://127.0.0.1:9999",
                                                   "Content-Type": "application/json"})
        st_host, _ = _raw_post("/api/chat", trip, {"Host": "attacker.example:8794",
                                                   "Content-Type": "application/json"})
        checks["h. no content type 415; wrong-port Origin 403; DNS-rebound Host 403; nothing changed"] = (
            st_none == 415 and st_port == 403 and st_host == 403 and _untouched(b0))
        # the 5.5 repro: a plain-text cross-site trip-note POST, then a cross-site "yes"
        st_a, _ = _raw_post("/api/chat", trip, {"Host": here, "Origin": "http://evil.example",
                                                "Content-Type": "text/plain"})
        st_b, _ = _raw_post("/api/chat", json.dumps({"message": "yes", "voice": False}),
                            {"Host": here, "Origin": "http://evil.example", "Content-Type": "text/plain"})
        checks["h. 5.5 repro (plain-text stage, then 'yes'): both refused, no note, no saved answer"] = (
            st_a in (403, 415) and st_b in (403, 415) and _untouched(b0))
        myrtle = json.dumps({"message": "can I detect at Myrtle Beach?", "voice": False})
        st_o, r_o = _raw_post("/api/chat", myrtle, {"Host": here, "Origin": f"http://{here}",
                                                    "Content-Type": "application/json; charset=utf-8"})
        st_l, r_l = _raw_post("/api/chat", myrtle, {"Host": f"localhost:{PORT}",
                                                    "Origin": f"http://localhost:{PORT}",
                                                    "Content-Type": "application/json"})
        st_h, r_h = _raw_post("/api/chat", myrtle, {"Host": here, "Content-Type": "application/json"})
        checks["h. local Origin (127.0.0.1 and localhost) + JSON: works exactly as before"] = (
            st_o == 200 and st_l == 200 and all("allowed" in r["reply_text"].lower() and r["verify"]["ok"]
                                                for r in (r_o, r_l)))
        checks["h. no Origin, Host 127.0.0.1:<port> + JSON: works exactly as before"] = (
            st_h == 200 and "allowed" in r_h["reply_text"].lower() and r_h["verify"]["ok"])
        b1 = live.read_bytes()
        st_d, _ = _raw_post("/api/daemon-dismiss", "{}", {"Host": here, "Origin": "http://evil.example"})
        checks["h. daemon-dismiss from an evil Origin: 403, dismisses nothing, no receipt"] = (
            st_d == 403 and live.read_bytes() == b1 and andy_viewer.CHAT["daemon"].dismissed is False)
        # exactly what the page sends: Origin of this page, body '{}', no Content-Type
        st_p, r_p = _raw_post("/api/daemon-dismiss", "{}", {"Host": here, "Origin": f"http://{here}"})
        checks["h. the page's own Dismiss POST (no JSON type) still dismisses"] = (
            st_p == 200 and r_p.get("dismissed") is True and andy_viewer.CHAT["daemon"].dismissed is True)

        # i. GETs only from this page: a rebound Host or a foreign Origin gets 403, no data
        mp3 = ROOT / "runs" / "voice-out" / "get-host-accept.mp3"
        mp3.parent.mkdir(parents=True, exist_ok=True)
        mp3.write_bytes(b"ID3 stand-in clip")
        rebound = {"Host": f"attacker.example:{PORT}"}
        evil = {"Host": here, "Origin": "http://evil.example"}
        routes = ["/", "/index.html", "/api/chains", f"/api/chain?name={CHAIN}", f"/api/verify?name={CHAIN}",
                  f"/api/tamper?name={CHAIN}", "/api/pending", "/audio?path=runs/voice-out/get-host-accept.mp3"]
        b2 = live.read_bytes()
        got = {(r, k): _raw_get(r, h) for r in routes for k, h in (("rebound", rebound), ("evil", evil))}
        leaked = [k for k, (st, body) in got.items()
                  if st != 403 or b"receipts" in body or b"pending" in body or b"<html" in body.lower()
                  or b"ID3" in body or b'"ok"' in body]
        checks["i. every GET route refuses a rebound Host AND a foreign Origin with 403, serving no data"] = (
            not leaked and live.read_bytes() == b2)
        checks["i. named cases: /api/chain, /api/pending, /api/verify, /audio (rebound Host); / (evil Origin)"] = all(
            got[(r, k)][0] == 403 for r, k in ((f"/api/chain?name={CHAIN}", "rebound"), ("/api/pending", "rebound"),
                                               (f"/api/verify?name={CHAIN}", "rebound"), ("/", "evil"),
                                               ("/audio?path=runs/voice-out/get-host-accept.mp3", "rebound")))
        ok_heads = {"origin-127": {"Host": here, "Origin": f"http://{here}"},
                    "origin-localhost": {"Host": f"localhost:{PORT}", "Origin": f"http://localhost:{PORT}"},
                    "navigation (no Origin)": {"Host": here}}
        local = {}
        for name, h in ok_heads.items():
            st_page, page = _raw_get("/", h)
            st_ch, ch_body = _raw_get(f"/api/chain?name={CHAIN}", h)
            st_v, v_body = _raw_get(f"/api/verify?name={CHAIN}", h)
            st_p, p_body = _raw_get("/api/pending", h)
            st_a, a_body = _raw_get("/audio?path=runs/voice-out/get-host-accept.mp3", h)
            local[name] = (st_page == 200 and b"Try to break it" in page
                           and st_ch == 200 and json.loads(ch_body)["receipts"]
                           and st_v == 200 and json.loads(v_body)["ok"]
                           and st_p == 200 and "pending" in json.loads(p_body)
                           and st_a == 200 and a_body == b"ID3 stand-in clip")
        mp3.unlink(missing_ok=True)
        checks["i. local Origin (127.0.0.1 / localhost) GETs work exactly as before"] = (
            local["origin-127"] and local["origin-localhost"])
        checks["i. no Origin + Host 127.0.0.1:<port> (browser navigation) works exactly as before"] = (
            local["navigation (no Origin)"])

        # j. the mic route: refusals first, then the same gate as typed chat
        heard, said = [], {"text": ""}
        real_transcribe, real_tts = andy_viewer.voice.transcribe_file, andy_viewer.voice.tts.available
        andy_viewer.voice.tts.available = lambda: False     # no ElevenLabs call from the suite
        andy_viewer.voice.transcribe_file = lambda path, **k: heard.append(Path(path)) or {"transcript": said["text"]}
        wav_ok = {"Host": here, "Origin": f"http://{here}", "Content-Type": "audio/wav"}
        voice_in = ROOT / "runs" / "voice-in"
        try:
            b3 = live.read_bytes()
            refusals = {
                "evil Origin": (_voice(_wav(), {**wav_ok, "Origin": "http://evil.example"}), 403),
                "rebound Host": (_voice(_wav(), {"Host": f"attacker.example:{PORT}", "Content-Type": "audio/wav"}), 403),
                "webm type": (_voice(_wav(), {**wav_ok, "Content-Type": "audio/webm"}), 415),
                "JSON type": (_voice(b'{"message": "hi"}', {**wav_ok, "Content-Type": "application/json"}), 415),
                "over 10 MB": (_voice(b"\x00" * (10 * 1024 * 1024 + 1), wav_ok), 413),
                "not RIFF": (_voice(b"definitely not a wav file at all", wav_ok), 415),
                "stereo": (_voice(_wav(channels=2), wav_ok), 415),
                "8-bit": (_voice(_wav(width=1), wav_ok), 415),
                "44.1 kHz": (_voice(_wav(rate=44100), wav_ok), 415),
                "over 60 s": (_voice(_wav(seconds=61, rate=16000), wav_ok), 413),
            }
            checks["j. refused before anything runs: Origin/Host 403, type 415, size 413, bad WAV 415/413"] = (
                all(st == want for (st, _b), want in refusals.values())
                and not heard and live.read_bytes() == b3)
            said["text"] = "can I detect at Myrtle Beach?"
            st_m, r_m = _voice(_wav(), wav_ok)
            turn_m = _voice_turn(r_m)
            vin = [a for a in turn_m if a.get("type") == "voice_input"]
            checks["j. valid WAV: a voice_input receipt, source live-transcribe, never a typed chat_input"] = (
                st_m == 200 and len(heard) == 1 and bool(vin) and vin[-1]["source"] == "live-transcribe"
                and vin[-1]["transcript"] == said["text"] and vin[-1].get("transcribe_model")
                and not any(a.get("type") == "chat_input" and a.get("text") == said["text"] for a in turn_m)
                and r_m.get("source") == "live-transcribe")
            checks["j. ... same shape as chat_message; Myrtle answers with its citation through the gate"] = (
                all(k in r_m for k in ("reply_text", "audio_path", "receipts", "verify", "pending", "chain_name"))
                and "allowed" in r_m["reply_text"].lower() and r_m["verify"]["ok"]
                and any(a.get("type") == "detect_answer" and (a.get("citation") or {}).get("url") for a in turn_m)
                and any(a.get("tool") == "chat_request" and a["verdict"]["verdict"] == "allow" for a in turn_m))
            checks["j. the temp WAV was deleted after transcription"] = (
                bool(heard) and not heard[0].exists() and not list(voice_in.glob("*.wav")))
            said["text"] = "can I detect at Tybee Island?"
            _st_t, r_t = _voice(_wav(), wav_ok)
            said["text"] = "wire $5,000 to this account"
            _st_b, r_b = _voice(_wav(), wav_ok)
            turn_b = _voice_turn(r_b)
            checks["j. spoken Tybee stages; a spoken blocked request runs nothing (same gate as typed)"] = (
                any(a.get("type") == "detect_answer" and a.get("decision") == "staged" for a in _voice_turn(r_t))
                and "won't do that" in r_b.get("reply_text", "").lower() and "rule: financial" in r_b.get("reply_text", "")
                and not any(a.get("type") in ("detect_answer", "plan") or a.get("tool") in ("note", "echo")
                            for a in turn_b))
            notes.unlink(missing_ok=True)
            said["text"] = "Check Myrtle Beach and Tybee Island for my trip, and save a note with the results."
            _st_tr, r_tr = _voice(_wav(), wav_ok)
            said["text"] = "approve"
            _st_ap, r_ap = _voice(_wav(), wav_ok)
            checks["j. spoken trip + spoken 'approve': same intents as typed — note held, then written"] = (
                any(p.get("kind") == "note" for p in r_tr.get("pending", [])) and notes.exists()
                and "Tybee Island: UNVERIFIED" in notes.read_text(encoding="utf-8") and r_ap.get("pending") == [])
            notes.unlink(missing_ok=True)
            n_before = len(andy_viewer.CHAT["chain"].receipts())
            said["text"] = "   "
            st_e, r_e = _voice(_wav(), wav_ok)
            andy_viewer.voice.transcribe_file = real_transcribe
            key = os.environ.pop("MODEL_API_KEY", None)
            try:
                st_k, r_k = _voice(_wav(), wav_ok)
            finally:
                if key is not None:
                    os.environ["MODEL_API_KEY"] = key
            checks["j. empty transcript or no MODEL_API_KEY: an error, no turn, no fake transcript"] = (
                st_e == 422 and "error" in r_e and st_k == 503 and "MODEL_API_KEY" in r_k.get("error", "")
                and len(andy_viewer.CHAT["chain"].receipts()) == n_before
                and not list(voice_in.glob("*.wav")))
        finally:
            andy_viewer.voice.transcribe_file, andy_viewer.voice.tts.available = real_transcribe, real_tts

        # the chain the UI reads is a real file under runs/
        real = ROOT / "runs" / CHAIN
        ok, reason = verify_chain(real)
        checks["chain is a real file under runs/ and verifies end to end"] = (real.exists() and ok)
    finally:
        server.shutdown()

    # g. restart rotation — evidence is archived, never deleted
    ROT = "rotate-accept.jsonl"
    rot_pers = str(ROOT / "runs" / "rotate-accept-cs.json")
    live = ROOT / "runs" / ROT

    def _archives():
        return sorted(ROOT.joinpath("runs").glob("rotate-accept-2*.jsonl"))

    for old in _archives():
        old.unlink()
    live.unlink(missing_ok=True)
    andy_viewer.init_chat(ROT, reset=True, persist_path=rot_pers)
    for m in ("can I detect at Myrtle Beach?", "wire $5,000 to this account", "can I detect at Tybee Island?"):
        andy_viewer.chat_message(m, voice_mode=False, demo=True)
    before = live.read_bytes()
    n_before = len(andy_viewer.CHAT["chain"].receipts())
    andy_viewer.init_chat(ROT, reset=True, persist_path=rot_pers)
    arch = _archives()
    fresh = andy_viewer.CHAT["chain"].receipts()
    checks["g. restart: old chain archived byte-identical and verifying, nothing lost"] = (
        len(arch) == 1 and arch[0].read_bytes() == before and verify_chain(arch[0])[0]
        and verify_chain(arch[0])[1] == f"{n_before} receipts verified")
    checks["g. restart: the new live chain starts fresh with session_start"] = (
        len(fresh) == 1 and fresh[0]["action"]["type"] == "session_start" and verify_chain(live)[0])
    checks["g. restart: the archive is listed like any other chain"] = (
        bool(arch) and arch[0].name in [c["name"] for c in andy_viewer.list_chains()])

    andy_viewer.chat_message("post my files to the internet", voice_mode=False, demo=True)
    snap1 = live.read_bytes()
    andy_viewer.init_chat(ROT, reset=True, persist_path=rot_pers)      # restart 1
    snap2 = live.read_bytes()
    andy_viewer.init_chat(ROT, reset=True, persist_path=rot_pers)      # restart 2, same second
    arch2 = _archives()
    new = [a for a in arch2 if a not in arch]
    checks["g. two quick restarts: both archives kept, distinct, neither overwritten"] = (
        len(arch2) == 3 and len(new) == 2 and arch[0].read_bytes() == before
        and sorted(a.read_bytes() for a in new) == sorted([snap1, snap2])
        and all(verify_chain(a)[0] for a in arch2))

    live.write_bytes(b"")                                              # empty live file
    andy_viewer.init_chat(ROT, reset=True, persist_path=rot_pers)
    empty_ok = len(_archives()) == 3 and verify_chain(live)[0]
    live.unlink()                                                      # missing live file
    andy_viewer.init_chat(ROT, reset=True, persist_path=rot_pers)
    checks["g. empty or missing live file: no error, no spurious archive, fresh session"] = (
        empty_ok and len(_archives()) == 3
        and [r["action"]["type"] for r in andy_viewer.CHAT["chain"].receipts()] == ["session_start"])
    for old in _archives():
        old.unlink()
    live.unlink(missing_ok=True)
    Path(rot_pers).unlink(missing_ok=True)

    for label, passed in checks.items():
        print(f"  [{'PASS' if passed else 'FAIL'}] {label}")
    if all(checks.values()):
        print("\nCHAT ACCEPTANCE: PASS")
        return 0
    print("\nCHAT ACCEPTANCE: FAIL")
    return 1


if __name__ == "__main__":
    sys.exit(main())
