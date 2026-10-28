#!/usr/bin/env bash
# Build AgentAndy.app — a local launcher bundle for the Agent Andy viewer.
#
# Generates the .app from committed sources only:
#   mac/launcher.sh            -> Contents/MacOS/AgentAndy  (the launcher)
#   mac/Info.plist.template    -> Contents/Info.plist
#   scripts/make_app_icon.py   -> Contents/Resources/AgentAndy.icns (local, best-effort)
#
# The generated AgentAndy.app is gitignored and NEVER committed. This builds a
# plain local bundle only: no .dmg, no .pkg, no code signing, no notarization,
# no auto-update, and no download. The terminal ./start-andy.sh stays the
# canonical launcher; this bundle only runs it.
set -euo pipefail

cd "$(dirname "$0")/.."
REPO="$(pwd)"
APP="${REPO}/AgentAndy.app"
VERSION="0.1.0"

if [ ! -f "${REPO}/start-andy.sh" ]; then
  echo "error: start-andy.sh not found in ${REPO}; run this from inside the agent-andy repo." >&2
  exit 1
fi

echo "Building ${APP}"
rm -rf "${APP}"
mkdir -p "${APP}/Contents/MacOS" "${APP}/Contents/Resources"

# Info.plist (version substituted from the template).
cp "${REPO}/mac/Info.plist.template" "${APP}/Contents/Info.plist"
/usr/bin/sed -i '' "s/__VERSION__/${VERSION}/g" "${APP}/Contents/Info.plist"

# Launcher executable.
cp "${REPO}/mac/launcher.sh" "${APP}/Contents/MacOS/AgentAndy"
chmod +x "${APP}/Contents/MacOS/AgentAndy"

# Icon — built locally, best-effort. If the tools or the build are unavailable,
# ship a plain (generic) icon and say so, rather than faking one.
ICON_STATUS="plain generic icon (no local .icns was built)"
if command -v sips >/dev/null 2>&1 && command -v iconutil >/dev/null 2>&1; then
  TMP="$(mktemp -d)"
  if python3 "${REPO}/scripts/make_app_icon.py" "${TMP}/icon_1024.png" >/dev/null 2>&1; then
    ISET="${TMP}/AgentAndy.iconset"
    mkdir -p "${ISET}"
    ok=1
    for sz in 16 32 128 256 512; do
      sips -z "${sz}" "${sz}" "${TMP}/icon_1024.png" \
           --out "${ISET}/icon_${sz}x${sz}.png" >/dev/null 2>&1 || ok=0
      sips -z "$((sz*2))" "$((sz*2))" "${TMP}/icon_1024.png" \
           --out "${ISET}/icon_${sz}x${sz}@2x.png" >/dev/null 2>&1 || ok=0
    done
    if [ "${ok}" = 1 ] && iconutil -c icns "${ISET}" \
         -o "${APP}/Contents/Resources/AgentAndy.icns" >/dev/null 2>&1; then
      /usr/libexec/PlistBuddy -c "Add :CFBundleIconFile string AgentAndy" \
           "${APP}/Contents/Info.plist" >/dev/null 2>&1 || true
      ICON_STATUS="custom checkmark glyph (generated locally by scripts/make_app_icon.py)"
    fi
  fi
  rm -rf "${TMP}"
fi

# Nudge LaunchServices/Finder to notice the fresh bundle and its icon.
/usr/bin/touch "${APP}" || true

echo "Icon:    ${ICON_STATUS}"
echo "Bundle:  ${APP}"
echo
echo "Next: drag AgentAndy.app to the Dock, then double-click it. Keep it inside"
echo "this repo — it is a launcher bound to this checkout, not a standalone app."
