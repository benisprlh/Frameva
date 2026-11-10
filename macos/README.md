# Frameva for macOS — native source alpha

Frameva 0.2 has a **SwiftUI/AppKit application**, not a browser or WKWebView wrapper.
Its native window uses ScreenCaptureKit, AVKit, native open/save panels, and an
editable recording timeline. A bundled Python helper owns projects, source
analysis, actual video rendering, browser-flow recording, and MCP integration.

**Verification boundary:** this source was authored and statically reviewed on
Linux. No Mac executable was produced or tested in that environment. The build
and CI below must succeed on a real Mac before describing the native app as
Mac-verified. Screen recording, microphone consent, video playback, and Apple
signing require additional interactive/native checks.

## Requirements

- macOS 15 or later.
- Xcode 16 or newer, with its macOS SDK selected (`sudo xcode-select -s
  /Applications/Xcode.app/Contents/Developer`). Full Xcode is the supported build
  environment; older command-line tools do not provide the required capture API.
- Native-architecture Python 3.11–3.13 for building the helper. Python is bundled
  afterward; end users of a completed `.app` do not need a separate installation.
- Apple Silicon or Intel, built on the matching architecture. The script rejects
  an architecture-mismatched Python. It does not create a universal binary.

## Build the complete application

If `python3.12: command not found` appears, Python 3.12 is either not installed
or not on your shell's PATH. With [Homebrew](https://brew.sh) already installed,
install the versioned interpreter and select it by its absolute path:

```bash
brew install python@3.12
FRAMEVA_BUILD_PYTHON="$(brew --prefix python@3.12)/bin/python3.12" \
  bash macos/scripts/build.sh --dmg
```

Run this from the Frameva repository directory. There is no need to clone it
again. Selecting the versioned path avoids depending on Homebrew's default
`python3` version or on a versioned executable being in PATH. An existing native
Python 3.11–3.13 can also be selected with `FRAMEVA_BUILD_PYTHON`; full Xcode is
still required as described above.

If an older checkout fails in PyInstaller with `Error: typer is required` or
`SystemExit: 1` from `mcp/cli/cli.py`, update with `git pull --ff-only` and rerun
the same build command. The packaging spec now excludes the MCP SDK's optional
development CLI before module discovery; Frameva uses its own CLI to run the MCP
server. Python does not need reinstalling, and this fix does not require adding
`typer` or the SDK's `[cli]` extra.

From the repository root on the target Mac:

```bash
bash macos/scripts/build.sh
```

The script creates a build virtual environment, installs Frameva with the
Playwright dependency, freezes the helper as a proper nested `.app`, runs Swift
unit tests, compiles the native UI, signs code inside-out using an ad-hoc
signature, and checks the packaged helper and authenticated API startup.

The output is one of:

```text
dist/native-arm64/Frameva.app
dist/native-x86_64/Frameva.app
```

Open the applicable `Frameva.app` with Finder. This is a local development build,
not a Developer ID–signed, notarized public distribution. Do not disable macOS
security protections to bypass an unexplained signing or build failure.

The optional `FRAMEVA_BUILD_PYTHON` environment variable selects the build
interpreter. It must match the Mac architecture. Builds use the installed source
package and no `PYTHONPATH` override.

## Build a drag-to-Applications DMG

Build and package in one command on a Mac with the requirements above:

```bash
FRAMEVA_BUILD_PYTHON=python3.12 bash macos/scripts/build.sh --dmg
```

This builds the app and bundled worker first, runs their checks, then creates
`dist/Frameva-0.2.0-macos-arm64-development.dmg` on Apple Silicon or the
`x86_64` equivalent on Intel. The disk image contains `Frameva.app` and an
Applications shortcut. Packaging verifies the disk image and the app signature
inside a read-only mounted copy before publishing it. It refuses to overwrite an
existing DMG; move the old output aside or choose a new output filename.

To package an existing successful build without rebuilding:

```bash
bash macos/scripts/package-dmg.sh "dist/native-$(uname -m)/Frameva.app"
```

The native GitHub Actions workflow also runs this packaging step. **Only a
successful run** provides the DMG inside its `Frameva-macOS-…-development`
artifact. Download and unzip that artifact, open the DMG, drag Frameva to
Applications, eject it, and open the installed app. End users of the packaged app
need neither Xcode nor Python. Chromium remains an optional in-app download for
scripted browser flows. The CI artifact is ad-hoc signed, not notarized.

If GitHub reports an account billing lock, no build or download is produced;
resolve the account issue and run **Actions → Native macOS application → Run
workflow**, or build locally. Packaging scripts cannot bypass that lock. No DMG
has been built or mounted on the Linux development host.

## Run the native UI during development

Install the worker first, then run SwiftUI with the installed environment:

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -e '.[capture]'
FRAMEVA_WORKER_EXECUTABLE="$PWD/.venv/bin/python" swift run --package-path macos Frameva
```

The override can also be set to an absolute `frameva` executable. Native Settings
provides the same developer override. A Python worker is launched with
`-I -m frameva`, so it must actually have Frameva installed; an import from the
current directory is not a substitute. The packaged helper is invoked directly.

Running an unbundled Swift executable is useful for UI development. Test capture
and microphone permissions with the complete app bundle, where the usage strings
and bundle identity exist.

## Source → live app → launch film

1. Create a production. Import a source ZIP or use the MCP repository-inspection
   tools. Source candidates show file/line evidence; they are not automatically
   verified product features.
2. Start the app you are demonstrating yourself or through an explicitly
   authorized development workflow. Frameva never installs or executes an
   uploaded source ZIP.
3. Choose **Record app**. macOS presents its system sharing picker for a window
   or display. Cursor movement is included; click highlights and system audio
   are configurable. Enable the microphone only when narration is wanted.
4. Demonstrate the actual interface and choose **Stop & finalize**. Frameva waits
   for `SCRecordingOutputDelegate.recordingOutputDidFinishRecording`, not merely
   `stopCapture()`, before uploading the MP4. The same completion rule applies
   when sharing is stopped from macOS.
5. The imported take becomes a **Real recording** scene. Its initial duration
   includes the available footage up to the 120-second scene limit. Trim the
   start, shorten the output, adjust playback rate, focus, zoom, motion, titles,
   or format. Requested footage overruns fail explicitly rather than freezing
   the last frame. Split a longer take into multiple scenes.
6. Render changed scenes, then export the ordered film using cuts or crossfades.
   Original clip audio is preserved; an optional imported soundtrack is mixed.
   Download/save the finished MP4 from **Render queue**.

Native originals are retained in `~/.frameva/native-recordings` (or the selected
`FRAMEVA_DATA_DIR`). Failed uploads do not delete the take. Media uploads are
limited to 256 MiB, and source ZIPs to 64 MiB. Use **Reveal file** to recover a
large or interrupted recording and import a shorter or recompressed copy.
Unfinished recordings are never automatically uploaded as successful takes.

AVKit previews use authenticated downloads to private local cache files; tokens
are not placed in player URLs. Native captures and worker output use H.264/MP4.
Imported formats such as WebM depend on the Mac's AVKit codec support and may not
preview natively even when the rendering worker can read them. Use MP4 for a
predictable native preview.

## Record a repeatable browser flow

**Live flows** accepts explicit JSON steps (`goto`, `click`, `fill`, `press`,
`scroll`, `wait`, `assert_text`) for an already-running app. The first example
contains placeholder visible text and must be edited to match the product.
Clicking **Save & record workflow** is the explicit action that drives the app.
Use demo accounts and data. Navigation remains on the base URL's origin.

Choose **Install flow browser** to download Chromium explicitly. ScreenCaptureKit
recording needs no browser installation. The helper bundles the Python Playwright
package and its Node driver; browser binaries are installed in Playwright's
normal OS cache rather than copied from a personal browser profile.

Use exact source candidate titles in `feature_titles` to map runtime evidence.
The coverage view distinguishes candidates from completed mapped recordings and
never equates one successful flow with full product verification. See the
repository's [live-flow guide](../docs/LIVE_FLOWS.md).

## Codex and Claude Code

**Codex / Claude → Agent setup** shows local MCP JSON for the bundled helper:

```text
Frameva.app/Contents/Helpers/FramevaWorker.app/Contents/MacOS/frameva-worker
```

Its MCP arguments are `mcp`, not `-m frameva`. The helper also supports
`mcp-config`, `doctor`, `install-browser`, and `serve`. For exact Codex TOML and
registration commands, run:

```bash
"/absolute/path/Frameva.app/Contents/Helpers/FramevaWorker.app/Contents/MacOS/frameva-worker" mcp-config
```

Keep Frameva open while an agent uses its tools. Native and MCP processes read
the same private `~/.frameva/token` file and use `Authorization: Bearer` to reach
the worker. The native app removes inherited `FRAMEVA_TOKEN` overrides from
worker startup so configuration cannot silently diverge. No token is embedded
in MCP configuration.

## Worker ownership and data

The default endpoint is `http://127.0.0.1:8741`. The app first verifies an existing
worker using authenticated `/api/config`, confirms its identity and 0.2-or-newer
version, and adopts it if compatible. It never stops an adopted process. A
mismatched-token or old worker produces an error instead of spawning a second
server against the same database lock.

`FRAMEVA_DATA_DIR` selects another private data directory.
`FRAMEVA_NATIVE_PORT` selects a port from 1024–65535. If a different worker already
owns that data directory, stop it or use its endpoint; changing only the port
does not bypass the database lock. Settings also expose the chosen directory and
endpoint. Worker diagnostics go to `native-worker.log` inside that directory.

On quit, the app waits for capture finalization and pending take imports, then
stops only a worker it owns. Owned worker cleanup has a bounded grace period;
force termination is a last resort. Completed projects remain durable. Restart
behavior for interrupted render jobs is explicit in the queue.

## Signing and distribution

A Developer ID identity can be supplied explicitly:

```bash
FRAMEVA_SIGN_IDENTITY='Developer ID Application: YOUR NAME (TEAMID)' \
  bash macos/scripts/build.sh
```

The signing helper signs Mach-O code and nested bundles inside-out. It does not
use `codesign --deep --sign`. `--deep --verify` is used only for verification.
The app requests microphone input permission; the worker's separate entitlements
allow the bundled Node runtime's JIT. There is no App Sandbox entitlement because
the local worker needs the explicitly selected local project/media and loopback
server workflows.

After configuring an Apple notarytool keychain profile yourself:

```bash
bash macos/scripts/notarize.sh \
  "$PWD/dist/native-arm64/Frameva.app" YOUR_NOTARY_KEYCHAIN_PROFILE
```

For DMG distribution, instead build with Developer ID and package the signed app
with the same identity, then notarize and staple the outermost DMG:

```bash
FRAMEVA_SIGN_IDENTITY='Developer ID Application: YOUR NAME (TEAMID)' \
  FRAMEVA_BUILD_PYTHON=python3.12 bash macos/scripts/build.sh --dmg
bash macos/scripts/notarize.sh \
  "$PWD/dist/Frameva-0.2.0-macos-$(uname -m)-signed.dmg" \
  YOUR_NOTARY_KEYCHAIN_PROFILE
```

The `signed` filename indicates signing intent, not successful
notarization; the notarization script must finish with a successful Gatekeeper
assessment. Its final SHA-256 reflects the stapled image. Do not submit the
development DMG as though it were a signed public release. These steps follow
Apple's [packaging](https://developer.apple.com/documentation/xcode/packaging-mac-software-for-distribution)
and [notarization](https://developer.apple.com/documentation/security/customizing-the-notarization-workflow)
guidance.

No signing credentials are embedded or acquired by these scripts. Review bundled
third-party notices and the exact FFmpeg build's distribution obligations before
publishing binary releases. App MIT licensing does not override dependency or
model licenses.

## Checks required on a real Mac

The native CI runs `swift test`, compiles the application, freezes and verifies
the helper, and uploads a development artifact only if those commands succeed.
The workflow tests the architecture of its actual hosted runner; it does not
claim universal or dual-architecture verification.

Before declaring a release ready, additionally verify:

- clean launch with no system Python dependency; adoption of a matching worker;
- rejected mismatched/old worker and graceful owned-worker shutdown;
- sharing picker selection/cancel/denial, Retina geometry and child windows;
- pointer and click highlights, system audio, microphone allow/deny;
- manual and system-initiated stop, exactly-once finalized upload, repeat takes;
- source ZIP → candidate evidence → mapped flow recording → native timeline;
- trim/rate/focus/zoom with real temporal video and preserved audio;
- final crossfade export, native playback, save/replace and reopen;
- packaged helper MCP handshake in both Codex and Claude Code;
- Intel and Apple Silicon builds independently, plus signing/notarization.
