#!/usr/bin/env bash
# Launch Agent Andy's local demo: the receipt viewer + chat pane, on 127.0.0.1.
# This is the launcher for now — no .app, no installer, no auto-start.
#
#   ./start-andy.sh            # port 8799
#   ./start-andy.sh 9000       # a different port
set -e
cd "$(dirname "$0")"
PORT="${1:-8799}"
URL="http://127.0.0.1:${PORT}"

# Sign chain tips and earned answers with Andy's dedicated key when it is on this
# Mac (receipts/signing.py). No passphrase, so nothing to load first. Without the
# key, chains still hash-check but read UNSIGNED, and earned answers stage.
if [ -z "${ANDY_CHAIN_SIGNING_KEY:-}" ] && [ -f "${HOME}/.ssh/id_ed25519_andy_chain" ]; then
  export ANDY_CHAIN_SIGNING_KEY="${HOME}/.ssh/id_ed25519_andy_chain"
fi

echo "Agent Andy  →  ${URL}"
if [ -n "${ANDY_CHAIN_SIGNING_KEY:-}" ]; then
  echo "  Signing: ON (Andy chain key)"
else
  echo "  Signing: OFF — no Andy chain key, so chains will read UNSIGNED"
fi
echo
echo "  TYPED-CHAT FALLBACK: if voice or the Meta Model API is down on stage,"
echo "  just type in the chat box. Typed input runs through the exact same"
echo "  checker and receipts as voice — nothing is bypassed."
echo
echo "  Ctrl-C to stop."
echo

python3 viewer/andy_viewer.py --port "${PORT}" &
SRV=$!
trap 'kill "${SRV}" 2>/dev/null' INT TERM EXIT
sleep 1.2
command -v open >/dev/null 2>&1 && open "${URL}" || echo "  open ${URL} in your browser"
wait "${SRV}"
