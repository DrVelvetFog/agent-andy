#!/bin/bash
# AgentAndy.app launcher — a thin shim, NOT a new Andy.
#
# It runs the repo's own ./start-andy.sh, which starts the local viewer on
# 127.0.0.1:8799 and opens it in the default browser. This bundle changes no Andy
# code and no gate / receipt / checker behavior; the terminal ./start-andy.sh is
# the canonical launcher. The .app is bound to the agent-andy repo it was built
# inside: it resolves that repo from its own location and refuses to run from
# anywhere else, so it can never launch a stray copy of Andy, and it downloads
# nothing.
#
# ANDY_APP_NONINTERACTIVE=1 suppresses the GUI dialog and the browser-open (used
# by the acceptance suite); a real double-click leaves it unset.

set -u

PORT=8799
URL="http://127.0.0.1:${PORT}"

# LaunchServices hands GUI apps a sparse PATH, so add the usual homes to resolve
# python3 / open the same way a terminal does. Terminal users are unaffected —
# this only shapes the environment of this launcher process.
export PATH="/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin:${PATH:-}"

EXEC_DIR="$(cd "$(dirname "$0")" && pwd)"       # <repo>/AgentAndy.app/Contents/MacOS
REPO="$(cd "${EXEC_DIR}/../../.." && pwd)"      # <repo>  (the bundle sits at the repo root)
START="${REPO}/start-andy.sh"

say_fail() {
  msg="$1"
  printf 'Agent Andy: %s\n' "${msg}" >&2
  if [ -z "${ANDY_APP_NONINTERACTIVE:-}" ]; then
    /usr/bin/osascript -e "display dialog \"${msg}\" buttons {\"OK\"} default button \"OK\" with icon stop with title \"Agent Andy\"" >/dev/null 2>&1 || true
  fi
  exit 1
}

open_url() {
  if [ -z "${ANDY_APP_NONINTERACTIVE:-}" ]; then
    /usr/bin/open "${URL}" >/dev/null 2>&1 || true
  else
    printf 'Agent Andy: would open %s\n' "${URL}" >&2
  fi
}

# Bound to its repo: if start-andy.sh is not right here, fail plainly. Never
# search elsewhere, never download.
if [ ! -f "${START}" ]; then
  say_fail "start-andy.sh was not found at ${START}. Keep AgentAndy.app inside its agent-andy repo — it will not run a copy of Andy from anywhere else, and it downloads nothing. Delete this .app and rebuild it with scripts/build_mac_app.sh."
fi

# Already running? Do not start a second server — just open the existing page.
if /usr/bin/curl -s -o /dev/null --max-time 2 "${URL}/"; then
  printf 'Agent Andy: already running on %s — opening the existing page.\n' "${URL}" >&2
  open_url
  exit 0
fi

# Run the canonical launcher as a child. start-andy.sh opens the browser itself and
# serves the viewer, trapping INT/TERM/EXIT to stop its server.
/bin/bash "${START}" "${PORT}" &
SRV=$!

# Free the port whenever THIS app ends — a clean Quit (⌘Q / Dock → Quit) or a
# force quit. A detached watchdog outlives even a SIGKILL of this launcher: once
# this process is gone it stops start-andy.sh, whose own trap stops the viewer, so
# the port is always released and the next launch is clean. No stray server, and
# only the server THIS app started is touched.
LAUNCHER_PID=$$
/usr/bin/nohup /bin/bash -c '
  while /bin/kill -0 '"${LAUNCHER_PID}"' 2>/dev/null; do /bin/sleep 1; done
  /bin/kill -TERM '"${SRV}"' 2>/dev/null
' >/dev/null 2>&1 &

# Clean-quit path: stop the server as soon as we are asked to quit.
trap '/bin/kill -TERM "${SRV}" 2>/dev/null' INT TERM
wait "${SRV}"
