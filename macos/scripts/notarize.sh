#!/bin/bash
set -euo pipefail
if [[ $# -ne 2 ]]; then
  echo 'Usage: bash macos/scripts/notarize.sh /absolute/Frameva.app KEYCHAIN_PROFILE' >&2; exit 2
fi
app_path="$1"
profile="$2"
if [[ "$app_path" != /* || ! -d "$app_path/Contents" ]]; then
  echo 'Choose an absolute path to a signed Frameva.app.' >&2; exit 2
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
