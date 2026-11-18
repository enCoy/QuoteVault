#!/bin/sh
# Builds "Quote Vault.app": a small launcher that starts the server, opens the
# window, and stops the server when you quit. Nothing is set to run at login.
#
#   launcher/build.sh              installs into /Applications
#   launcher/build.sh ~/Desktop    installs somewhere else
#
# Run it again if you move the project folder.
set -e
ROOT=$(cd "$(dirname "$0")/.." && pwd)
DEST=${1:-/Applications}
[ -w "$DEST" ] || DEST="$HOME/Applications"
mkdir -p "$DEST"
APP="$DEST/Quote Vault.app"

rm -rf "$APP"
mkdir -p "$APP/Contents/MacOS" "$APP/Contents/Resources"

# Icon
TMP=$(mktemp -d)
SET="$TMP/icon.iconset"
mkdir -p "$SET"
for s in 16 32 128 256 512; do
  sips -z $s $s "$ROOT/launcher/icon-1024.png" --out "$SET/icon_${s}x${s}.png" >/dev/null
  d=$((s * 2))
  sips -z $d $d "$ROOT/launcher/icon-1024.png" --out "$SET/icon_${s}x${s}@2x.png" >/dev/null
done
iconutil -c icns "$SET" -o "$APP/Contents/Resources/icon.icns"
rm -rf "$TMP"

cat > "$APP/Contents/Info.plist" <<PLIST
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>CFBundleName</key><string>Quote Vault</string>
  <key>CFBundleDisplayName</key><string>Quote Vault</string>
  <key>CFBundleIdentifier</key><string>local.quote-vault</string>
  <key>CFBundleVersion</key><string>1</string>
  <key>CFBundleShortVersionString</key><string>0.1</string>
  <key>CFBundlePackageType</key><string>APPL</string>
  <key>CFBundleExecutable</key><string>quote-vault</string>
  <key>CFBundleIconFile</key><string>icon</string>
  <key>NSHighResolutionCapable</key><true/>
  <key>LSArchitecturePriority</key><array><string>arm64</string><string>x86_64</string></array>
  <key>NSMicrophoneUsageDescription</key><string>Quote Vault listens while you dictate a quote. The recording stays on this Mac.</string>
</dict>
</plist>
PLIST

# The app's program: a small C launcher that runs Python inside itself, so that macOS sees
# "Quote Vault" (not the shared Python runtime) as the running app. See launcher/launcher.c.
PY="$ROOT/.venv/bin/python"
PYHOME=$("$PY" -c 'import sys; print(sys.base_prefix)')
PYINC=$("$PY" -c 'import sysconfig; print(sysconfig.get_paths()["include"])')
PYSITE=$("$PY" -c 'import sysconfig; print(sysconfig.get_paths()["purelib"])')
PYLIB="$PYHOME/Python"                                   # the Python framework's library
[ -f "$PYLIB" ] || PYLIB=$("$PY" -c 'import sysconfig, os; print(os.path.join(sysconfig.get_config_var("LIBDIR"), sysconfig.get_config_var("LDLIBRARY")))')
clang -O2 -arch "$(uname -m)" -o "$APP/Contents/MacOS/quote-vault" "$ROOT/launcher/launcher.c" \
  -I"$PYINC" "$PYLIB" \
  -DQV_ROOT="\"$ROOT\"" -DQV_SITE="\"$PYSITE\"" -DQV_PYTHONHOME="\"$PYHOME\""

# A local ("ad hoc") signature gives the app a stable identity, which macOS needs
# to remember the microphone permission. Nothing is sent anywhere.
codesign --force --sign - "$APP" >/dev/null 2>&1 || echo "Note: could not sign the app; macOS may ask for the microphone each time."

echo "Built: $APP"
echo "Open it from Applications. To keep it in the Dock: right-click its Dock icon > Options > Keep in Dock."
