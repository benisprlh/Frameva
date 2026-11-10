#!/bin/bash
set -euo pipefail
if [[ $# -lt 1 || $# -gt 2 ]]; then
  echo 'Usage: bash macos/scripts/package-dmg.sh /path/Frameva.app [/path/output.dmg]' >&2; exit 2
fi
if [[ "$(uname -s)" != Darwin ]]; then
  echo 'DMG packaging requires macOS and a successfully built native Frameva.app.' >&2; exit 1
fi
macos_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
project_dir="$(cd -- "$macos_dir/.." && pwd)"
app_path="$1"
if [[ ! -d "$app_path/Contents" || ! -x "$app_path/Contents/MacOS/Frameva" ]]; then
  echo 'Build Frameva.app successfully before packaging it.' >&2; exit 2
fi
app_path="$(cd -P -- "$app_path" && pwd)"
bundle_id="$(/usr/libexec/PlistBuddy -c 'Print :CFBundleIdentifier' "$app_path/Contents/Info.plist")"
version="$(/usr/libexec/PlistBuddy -c 'Print :CFBundleShortVersionString' "$app_path/Contents/Info.plist")"
if [[ "$bundle_id" != dev.frameva.studio || ! "$version" =~ ^[0-9]+\.[0-9]+\.[0-9]+$ ]]; then
  echo 'Expected a Frameva app with a numeric major.minor.patch version.' >&2; exit 2
fi
build_arch="$(lipo -archs "$app_path/Contents/MacOS/Frameva")"
if [[ "$build_arch" != arm64 && "$build_arch" != x86_64 ]]; then
  echo "Expected one supported architecture, got: $build_arch" >&2; exit 2
fi
codesign --verify --deep --strict --verbose=2 "$app_path"
distribution_kind=development
sign_identity="${FRAMEVA_SIGN_IDENTITY:--}"
if [[ "$sign_identity" != - ]]; then distribution_kind=signed; fi
output_path="${2:-$project_dir/dist/Frameva-$version-macos-$build_arch-$distribution_kind.dmg}"
if [[ "$output_path" != *.dmg ]]; then
  echo 'Output must end in .dmg.' >&2; exit 2
fi
if [[ ! -d "$(dirname -- "$output_path")" ]]; then
  echo 'Choose an existing output directory outside the app bundle.' >&2; exit 2
fi
output_path="$(cd -P -- "$(dirname -- "$output_path")" && pwd)/$(basename -- "$output_path")"
if [[ "$output_path" == "$app_path/"* ]]; then
  echo 'The disk image must be stored outside the app bundle.' >&2; exit 2
fi
if [[ -e "$output_path" || -L "$output_path" ]]; then
  echo "Refusing to replace existing output: $output_path" >&2; exit 2
fi
work_dir="$(mktemp -d "$(dirname -- "$output_path")/.frameva-dmg.XXXXXX")"
mount_dir="$work_dir/mounted"
mount_attempted=false
cleanup() {
  local result=$?
  trap - EXIT
  if [[ "$mount_attempted" == true ]]; then
    if ! hdiutil detach "$mount_dir"; then
      echo "Could not detach disk image. Temporary files retained at $work_dir" >&2
      exit 1
    fi
  fi
  rm -rf -- "$work_dir"
  exit "$result"
}
trap cleanup EXIT
trap 'exit 130' INT
trap 'exit 143' TERM
mkdir -p "$work_dir/staging" "$mount_dir"
ditto "$app_path" "$work_dir/staging/Frameva.app"
ln -s /Applications "$work_dir/staging/Applications"
cat > "$work_dir/staging/Read Me.txt" <<'EOF'
Frameva for macOS 15 or later

Drag Frameva.app onto Applications, eject this disk image, then open Frameva
from Applications. Python and the media worker are included inside the app.
Install the optional Chromium browser from Live flows when you need it.

Development builds are not notarized releases. A DMG container alone does not
establish Gatekeeper approval or native feature verification.
Project and build documentation: https://github.com/benisprlh/Frameva
EOF
candidate="$work_dir/Frameva.dmg"
hdiutil create -volname Frameva -srcfolder "$work_dir/staging" -format UDZO -fs HFS+ "$candidate"
if [[ "$sign_identity" != - ]]; then
  codesign --force --sign "$sign_identity" --timestamp "$candidate"
  codesign --verify --strict --verbose=2 "$candidate"
fi
hdiutil verify "$candidate"
mount_attempted=true
hdiutil attach "$candidate" -readonly -nobrowse -noautoopen -mountpoint "$mount_dir"
codesign --verify --deep --strict --verbose=2 "$mount_dir/Frameva.app"
if [[ "$(readlink "$mount_dir/Applications")" != /Applications ]]; then
  echo 'The installation shortcut is missing from the disk image.' >&2; exit 1
fi
hdiutil detach "$mount_dir"
mount_attempted=false
# Same-filesystem hard link publishes atomically and refuses concurrent overwrite.
ln "$candidate" "$output_path"
printf '%s\n' "Created $output_path" 'Notarization and interactive Mac acceptance are separate release steps.'
shasum -a 256 "$output_path"
