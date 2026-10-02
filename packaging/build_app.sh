#!/bin/bash
# Builds "Manga Studio.app" (launcher only: runs this repo's .venv, so don't move/delete the repo).
set -euo pipefail
REPO="$(cd "$(dirname "$0")/.." && pwd)"
APP="${1:-$HOME/Applications}/Manga Studio.app"
rm -rf "$APP"; mkdir -p "$APP/Contents/MacOS" "$APP/Contents/Resources"
ICONSET="$(mktemp -d)/icon.iconset"; mkdir "$ICONSET"
for s in 16 32 128 256 512; do
  sips -z $s $s "$REPO/packaging/icon.png" --out "$ICONSET/icon_${s}x${s}.png" >/dev/null
  sips -z $((s*2)) $((s*2)) "$REPO/packaging/icon.png" --out "$ICONSET/icon_${s}x${s}@2x.png" >/dev/null
done
iconutil -c icns "$ICONSET" -o "$APP/Contents/Resources/icon.icns"
cat > "$APP/Contents/Info.plist" <<PLIST
<?xml version="1.0" encoding="UTF-8"?>
<plist version="1.0"><dict>
<key>CFBundleName</key><string>Manga Studio</string>
<key>CFBundleExecutable</key><string>MangaStudio</string>
<key>CFBundleIdentifier</key><string>local.manga-studio</string>
<key>CFBundleIconFile</key><string>icon</string>
<key>CFBundlePackageType</key><string>APPL</string>
<key>NSHighResolutionCapable</key><true/>
</dict></plist>
PLIST
cat > "$APP/Contents/MacOS/MangaStudio" <<LAUNCH
#!/bin/bash
cd "$REPO"
exec "$REPO/.venv/bin/python" MangaStudioMain.py >> "\$HOME/Library/Logs/MangaStudio.log" 2>&1
LAUNCH
chmod +x "$APP/Contents/MacOS/MangaStudio"
echo "Built: $APP"
