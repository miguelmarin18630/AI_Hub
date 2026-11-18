"""Genera un .app de macOS a partir del proyecto (para ejecutar en un Mac)."""
from pathlib import Path

root = Path(__file__).resolve().parent.parent
app = root / "dist" / "AI Hub.app"
contents = app / "Contents"
macos = contents / "MacOS"
resources = contents / "Resources"
macos.mkdir(parents=True, exist_ok=True)
resources.mkdir(parents=True, exist_ok=True)

launcher = macos / "AIHub"
launcher.write_text(
    f'#!/bin/bash\ncd "{root}"\nexec python3 AIHub.pyw "$@"\n',
    encoding="utf-8",
)
launcher.chmod(0o755)

icon_src = root / "assets" / "AIHub.icns"
if icon_src.exists():
    (resources / "AIHub.icns").write_bytes(icon_src.read_bytes())

(contents / "Info.plist").write_text(
    """<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN"
  "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>CFBundleName</key><string>AI Hub</string>
  <key>CFBundleDisplayName</key><string>AI Hub</string>
  <key>CFBundleIdentifier</key><string>org.marinweb.aihub</string>
  <key>CFBundleVersion</key><string>1.0</string>
  <key>CFBundleShortVersionString</key><string>1.0</string>
  <key>CFBundlePackageType</key><string>APPL</string>
  <key>CFBundleExecutable</key><string>AIHub</string>
  <key>CFBundleIconFile</key><string>AIHub.icns</string>
  <key>LSMinimumSystemVersion</key><string>10.15</string>
  <key>NSHighResolutionCapable</key><true/>
  <key>LSUIElement</key><false/>
</dict>
</plist>
""",
    encoding="utf-8",
)

print("app creada:", app)
print("ejecuta en macOS: open dist/'AI Hub.app'")