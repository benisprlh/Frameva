#!/bin/bash
set -euo pipefail
macos_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
project_dir="$(cd -- "$macos_dir/.." && pwd)"
cd "$project_dir"
if [[ "$(uname -s)" != Darwin ]]; then
  echo "The native app must be built on macOS 15+ with Xcode 16+." >&2
  exit 1
fi
build_arch="$(uname -m)"
if [[ "$build_arch" != arm64 && "$build_arch" != x86_64 ]]; then
  echo "Unsupported native architecture: $build_arch" >&2; exit 1
fi
native_python="${FRAMEVA_BUILD_PYTHON:-python3}"
"$native_python" -c 'import platform,sys; assert (3,11)<=sys.version_info[:2]<(3,14), "Python 3.11–3.13 required"; print("Building native",platform.machine(),"worker with",sys.version.split()[0])'
python_arch="$("$native_python" -c 'import platform; print(platform.machine())')"
if [[ "$python_arch" != "$build_arch" ]]; then
  echo "Python architecture $python_arch does not match shell architecture $build_arch. Use a native Python, not Rosetta." >&2; exit 1
fi
xcrun --find swift >/dev/null
xcrun --sdk macosx --show-sdk-version
build_dir="$project_dir/build/native-$build_arch"
venv_dir="$project_dir/.venv-native-$build_arch"
mkdir -p "$build_dir"
if [[ ! -x "$venv_dir/bin/python" ]]; then "$native_python" -m venv "$venv_dir"; fi
"$venv_dir/bin/python" -m pip install --upgrade pip
"$venv_dir/bin/python" -m pip install -e "$project_dir[capture]" 'pyinstaller>=6.11,<7'
"$venv_dir/bin/python" -I -m PyInstaller --noconfirm --clean --distpath "$build_dir/worker-dist" --workpath "$build_dir/worker-work" "$macos_dir/FramevaWorker.spec"
swift test --package-path "$macos_dir" --configuration release --arch "$build_arch"
swift build --package-path "$macos_dir" --configuration release --arch "$build_arch"
swift_bin="$(swift build --package-path "$macos_dir" --configuration release --arch "$build_arch" --show-bin-path)"
app_dir="$project_dir/dist/native-$build_arch/Frameva.app"
if [[ -e "$app_dir" ]]; then rm -rf -- "$app_dir"; fi
mkdir -p "$app_dir/Contents/MacOS" "$app_dir/Contents/Helpers" "$app_dir/Contents/Resources"
cp "$swift_bin/Frameva" "$app_dir/Contents/MacOS/Frameva"
cp "$macos_dir/Info.plist" "$app_dir/Contents/Info.plist"
cp -R "$build_dir/worker-dist/FramevaWorker.app" "$app_dir/Contents/Helpers/FramevaWorker.app"
cp "$project_dir/LICENSE" "$app_dir/Contents/Resources/LICENSE.txt"
"$venv_dir/bin/python" "$macos_dir/scripts/sign_bundle.py" "$app_dir" --identity "${FRAMEVA_SIGN_IDENTITY:--}"
codesign --verify --deep --strict --verbose=2 "$app_dir"
"$venv_dir/bin/python" "$macos_dir/scripts/smoke_bundle.py" "$app_dir"
printf '%s\n' "Built $app_dir" "Native capture still requires interactive testing on this Mac."
