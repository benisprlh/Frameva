#!/bin/bash
set -euo pipefail
if [[ $# -ne 2 ]]; then
  echo 'Usage: bash macos/scripts/notarize.sh /absolute/Frameva.app-or.dmg KEYCHAIN_PROFILE' >&2; exit 2
fi
if [[ "$(uname -s)" != Darwin ]]; then
  echo 'Notarization requires macOS with Xcode command-line tools.' >&2; exit 1
fi
app_path="$1"
profile="$2"
if [[ "$app_path" == /*.dmg && -f "$app_path" ]]; then
  hdiutil verify "$app_path"
  codesign --verify --strict --verbose=2 "$app_path"
  xcrun notarytool submit "$app_path" --keychain-profile "$profile" --wait
  xcrun stapler staple "$app_path"
  xcrun stapler validate "$app_path"
  spctl --assess --type open --context context:primary-signature --verbose=2 "$app_path"
  printf '%s\n' "Notarized distribution disk image: $app_path"
  shasum -a 256 "$app_path"
  exit 0
fi
if [[ "$app_path" != /*.app || ! -d "$app_path/Contents" ]]; then
  echo 'Choose an absolute path to a signed Frameva.app or .dmg.' >&2; exit 2
fi
codesign --verify --deep --strict --verbose=2 "$app_path"
archive_path="${app_path%.app}-notarization.zip"
ditto -c -k --keepParent "$app_path" "$archive_path"
xcrun notarytool submit "$archive_path" --keychain-profile "$profile" --wait
xcrun stapler staple "$app_path"
xcrun stapler validate "$app_path"
spctl --assess --type execute --verbose=2 "$app_path"
distribution_path="${app_path%.app}-notarized.zip"
ditto -c -k --keepParent "$app_path" "$distribution_path"
printf '%s\n' "Notarization and Gatekeeper assessment completed." "Distribution archive: $distribution_path"
