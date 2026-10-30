#!/usr/bin/env python3
"""Mac app launcher acceptance — the parts a script can prove headlessly.

The real double-click lifecycle (open the .app, the page loads, chat / Verify /
Flip one byte work; quitting frees the port; a second launch works) is verified
BY HAND on the Mac and reported separately, because it needs LaunchServices and a
browser. This suite proves, with no browser and no repeated real-server starts,
the launcher's contract:

  a. the build produced AgentAndy.app with the right layout, the launcher is +x,
     the bundle is gitignored, and nothing under it is tracked.
  d. with a server already on 8799, the launcher detects it, reports it, and does
     NOT start a second server (exit 0, no andy_viewer process spawned).
  e. moved out of the repo, the launcher fails plainly, names the missing
     start-andy.sh, and starts nothing.
  no-download: the launcher reaches only 127.0.0.1 — no external URL, no wget,
     no curl to any other host.
  hygiene: Info.plist asks for no camera / microphone / location / files access
     and no entitlements; the bundle is unsigned with no signing artifacts; no
     image or icon asset is committed (the README's screenshots in docs/img/ are
     the one exception, and never an icon); and the README makes no signing /
     notarization / distribution claim (and does state it is unsigned and not an
     installer).
"""

from __future__ import annotations

import http.server
import os
import plistlib
import shutil
import socket
import subprocess
import sys
import tempfile
import threading
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
APP = ROOT / "AgentAndy.app"
LAUNCHER = APP / "Contents" / "MacOS" / "AgentAndy"
PLIST = APP / "Contents" / "Info.plist"
PORT = 8799
NONINT = {**os.environ, "ANDY_APP_NONINTERACTIVE": "1"}


def _git(*args):
    return subprocess.run(["git", "-C", str(ROOT), *args],
                          capture_output=True, text=True)


def _andy_viewer_pids():
    r = subprocess.run(["pgrep", "-f", "andy_viewer.py"], capture_output=True, text=True)
    return [p for p in r.stdout.split() if p]


def _port_busy():
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.settimeout(0.5)
    try:
        return s.connect_ex(("127.0.0.1", PORT)) == 0
    finally:
        s.close()


class _Quiet(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"ok")

    def log_message(self, *a):
        pass


def _run(launcher: Path, timeout=20):
    return subprocess.run([str(launcher)], env=NONINT, capture_output=True,
                          text=True, timeout=timeout)


def main() -> int:
    # Prerequisite: the bundle must exist. A missing .app is a FAIL with its reason —
    # never a crash, and never a pass for an app that was never built.
    if not (APP.is_dir() and LAUNCHER.is_file() and PLIST.is_file()):
        print(f"  [FAIL] AgentAndy.app not built — {APP.relative_to(ROOT)} is missing or incomplete; "
              "run `bash scripts/build_mac_app.sh` first. No launcher check ran.")
        print("\nMAC APP LAUNCHER (headless) ACCEPTANCE: FAIL (.app not built)")
        return 1

    # Clean slate: no stray viewer, port free.
    subprocess.run(["pkill", "-f", "andy_viewer.py"], capture_output=True)
    checks = {}

    # ---- a. build output + layout + gitignore ----
    layout_ok = (APP.is_dir() and PLIST.is_file() and LAUNCHER.is_file()
                 and (APP / "Contents" / "Resources").is_dir())
    checks["a. AgentAndy.app built with Contents/{Info.plist,MacOS/AgentAndy,Resources}"] = layout_ok
    checks["a. the launcher is executable"] = (LAUNCHER.is_file() and os.access(LAUNCHER, os.X_OK))
    checks["a. the bundle is gitignored"] = (_git("check-ignore", "AgentAndy.app").returncode == 0)
    checks["a. nothing under the bundle is tracked"] = (_git("ls-files", "AgentAndy.app").stdout.strip() == "")

    # ---- d. already running -> no second server ----
    if _port_busy():
        checks["d. (precondition) port 8799 free before the test"] = False
    else:
        srv = http.server.ThreadingHTTPServer(("127.0.0.1", PORT), _Quiet)
        t = threading.Thread(target=srv.serve_forever, daemon=True)
        t.start()
        try:
            before = _andy_viewer_pids()
            r = _run(LAUNCHER)
            after = _andy_viewer_pids()
            checks["d. already-running: exit 0, says 'already running', no 2nd server"] = (
                r.returncode == 0 and "already running" in r.stderr.lower()
                and before == [] and after == [])
        finally:
            srv.shutdown()
            srv.server_close()

    # ---- e. moved out of the repo -> fails plainly, starts nothing ----
    tmp = Path(tempfile.mkdtemp())
    moved = tmp / "AgentAndy.app"
    shutil.copytree(APP, moved, symlinks=True)
    try:
        before = _andy_viewer_pids()
        r = _run(moved / "Contents" / "MacOS" / "AgentAndy")
        after = _andy_viewer_pids()
        checks["e. moved-out: non-zero exit, names start-andy.sh, downloads nothing, starts nothing"] = (
            r.returncode != 0 and "start-andy.sh" in r.stderr
            and "downloads nothing" in r.stderr.lower() and before == [] and after == [])
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    # ---- no-download: only 127.0.0.1, no external fetch ----
    lt = LAUNCHER.read_text(encoding="utf-8")
    url_lines = [ln for ln in lt.splitlines() if "http://" in ln or "https://" in ln]
    only_local = all(("127.0.0.1" in ln or "localhost" in ln) for ln in url_lines)
    checks["no-download: every URL in the launcher is 127.0.0.1/localhost"] = only_local
    checks["no-download: no https, no wget, no ftp in the launcher"] = (
        "https://" not in lt and "wget" not in lt and "ftp" not in lt)

    # ---- hygiene: plist permissions / entitlements ----
    with PLIST.open("rb") as f:
        info = plistlib.load(f)
    perm_keys = ["NSCameraUsageDescription", "NSMicrophoneUsageDescription",
                 "NSLocationUsageDescription", "NSLocationWhenInUseUsageDescription",
                 "NSDocumentsFolderUsageDescription", "NSDesktopFolderUsageDescription",
                 "NSDownloadsFolderUsageDescription", "NSAppleEventsUsageDescription"]
    checks["hygiene: Info.plist requests no camera/mic/location/files permission"] = (
        not any(k in info for k in perm_keys))
    checks["hygiene: Info.plist declares no entitlements / sandbox keys"] = (
        not any(k.startswith("com.apple.security.") for k in info))
    checks["hygiene: bundle is unsigned (no _CodeSignature / entitlements / profile)"] = (
        not (APP / "Contents" / "_CodeSignature").exists()
        and not list(APP.rglob("*.entitlements"))
        and not list(APP.rglob("embedded.provisionprofile")))

    # ---- hygiene: no committed image asset ----
    # The app icon is generated locally, never committed. The README's screenshots
    # in docs/img/ are documentation, the one exception, and never an .icns/.ico.
    tracked = _git("ls-files").stdout.lower().splitlines()
    img_ext = (".png", ".jpg", ".jpeg", ".gif", ".icns", ".ico", ".bmp", ".webp", ".tiff")
    images = [p for p in tracked if p.endswith(img_ext)
              and not (p.startswith("docs/img/") and p.endswith((".png", ".jpg", ".jpeg")))]
    checks["hygiene: no image/icon asset is committed (icon is generated locally; docs/img/ screenshots excepted)"] = (
        not images)
    if images:
        print("   committed image/icon assets:", images)

    # ---- hygiene: README makes no signing/notarization/distribution claim ----
    # Collapse whitespace so line wraps don't hide a claim (in either direction).
    readme = " ".join((ROOT / "README.md").read_text(encoding="utf-8").lower().split())
    positive_claims = ["is signed", "is notarized", "code-signed", "code signed", "codesigned",
                       "signed and notarized", "notarized and", "available on the app store",
                       "distributed via", "auto-update", "automatically updates"]
    offending = [c for c in positive_claims if c in readme]
    checks["hygiene: README makes no signing/notarization/distribution claim"] = (not offending)
    checks["hygiene: README states it is unsigned and not an installer"] = (
        ("unsigned" in readme or "not signed" in readme)
        and ("not notarized" in readme or "no notariz" in readme)
        and ("not an installer" in readme or "no installer" in readme or "not a .dmg" in readme))

    for label, passed in checks.items():
        print(f"  [{'PASS' if passed else 'FAIL'}] {label}")
    if offending:
        print("   offending README claims:", offending)

    if all(checks.values()):
        print("\nMAC APP LAUNCHER (headless) ACCEPTANCE: PASS")
        return 0
    print("\nMAC APP LAUNCHER (headless) ACCEPTANCE: FAIL")
    return 1


if __name__ == "__main__":
    sys.exit(main())
