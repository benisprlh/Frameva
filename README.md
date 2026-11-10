# Frameva

**From working software to a product launch film.**

Frameva reads your source code, helps a coding agent plan the product story,
records actual app workflows, and composes the footage into an MP4. Clicking,
typing, navigation, loading states and results come from the running application.
Source evidence tells the director what to investigate; a recording shows what
actually happened.

**0.2.0 — developer alpha.** The macOS client is written in SwiftUI/AppKit, with
ScreenCaptureKit recording and AVKit playback. It is a native application. Its
local Python worker handles projects, MCP, browser flows and rendering. The
portable worker and existing web studio remain available for Windows and Linux.

**Release status:** native macOS source and build automation are included. No
compiled, signed or notarized Mac app is supplied by this source release. Native
compilation, screen permissions and recording must still pass on a real Mac.
See [the verification record](docs/VERIFICATION.md) for executed tests and limits.

## Native Mac application

Target: **macOS 15 or later**, with **Xcode 16 or later** to build from source.
The app has native project controls, source import, recording, video playback,
scene settings, jobs and export. System capture lets you select the window to
record and use the application normally. Cursor/click visualization and optional
audio help communicate the interaction.

Build and run instructions: [macos/README.md](macos/README.md). Build on the Mac
architecture you want to distribute. The Python/FFmpeg helper stays inside the
app bundle. Developer builds and public distribution have different signing
requirements.

For a drag-to-Applications disk image, build on a Mac with
`FRAMEVA_BUILD_PYTHON=python3.12 bash macos/scripts/build.sh --dmg`.
The native workflow uploads the development DMG only after its build, tests and
image verification succeed. This source checkout does not include a compiled
DMG; packaging and public-release notarization are described in the native guide.

| Recording method | Best for | How it works |
| --- | --- | --- |
| Native window recording | Visible Mac apps and authenticated browser sessions | Select a window in the system picker, record the workflow, stop and import the completed MP4 |
| Scripted browser flow | Repeatable web-app walkthroughs | Execute clicks, typing, scrolling and assertions in a clean Chromium session; save continuous video and a step report |

## Make a launch film

1. Import the app source ZIP, or connect Codex/Claude Code to read a repository.
2. Review feature candidates and source references. Choose complete user
   journeys, for example create a project → add an item → inspect the result.
   Use demo data in an already running app.
3. Record the journey natively, or have the coding agent author a browser flow.
   Assertions check visible outcomes. A failed step fails the recording job.
4. Add the video as a recording scene. Set its in-point, duration, speed, focus,
   zoom, headline and caption. Add short title/CTA scenes around the walkthrough.
5. Render and preview the scenes, reorder the story, and export with cuts or
   crossfades. Keep source audio and optionally mix music or narration.
6. Check recorded feature coverage. Unmapped features remain visible as gaps.
   Recorded coverage does not prove every behavior or edge case is correct.

The compositor retains moving video frames. A trim that needs more footage than
exists is rejected rather than silently freezing the final frame. Screenshot
motion remains available for still assets and title cards.

## Codex and Claude Code

The coding agent supplies source understanding, copywriting and flow planning.
Frameva supplies persistent projects, recording, composition and exports through
MCP. Frameva itself needs no OpenAI or Anthropic API key; the agent's own account
requirements still apply. See [MCP setup](docs/MCP.md), including native helper
registration. Keep the app or worker running during agent operations.

Example brief:

> Use Frameva to create a 45-second launch film for this repository. My demo app
> is running at http://localhost:3000. Inspect source evidence and identify all
> user-facing feature candidates. Plan complete journeys using demo data. Record
> clicks, typing and results as continuous video, with assertions for important
> outcomes. Map flows to features and report anything not recorded. Compose an
> opening, the strongest journeys, and a call to action. Use readable pacing,
> focused zooms and restrained transitions. Check every job and export the MP4.
> Do not invent features, customer claims or performance metrics.

The source reader does not install dependencies, start repository code or obey
instructions embedded in source files. The target app must already be running.
An agent can help start a trusted project separately.

## Portable worker / Windows web studio

Requires Python 3.11–3.13; Python 3.12 is recommended. From this source folder:

```bash
# macOS / Linux
python3 scripts/bootstrap.py
```

```powershell
# Windows PowerShell
py -3.12 scripts/bootstrap.py
```

Legacy launchers `start-macos.command` and `start-windows.cmd` open the web studio
at `http://127.0.0.1:8741`. They are not native installers. The native Mac client
is under `macos/`; Windows currently uses the portable web studio/API.

For optional scripted browser recording, use the installed environment:

```bash
python -m pip install -e '.[capture]'
python -m frameva install-browser
python -m frameva record-flow examples/live-demo/launch-flow.json --output walkthrough.mp4
```

Start the included demo app first as described in
[examples/live-demo/README.md](examples/live-demo/README.md). See
[LIVE_FLOWS.md](docs/LIVE_FLOWS.md) for recording, inputs, pacing and limits.

## Included capabilities

| Capability | Implementation |
| --- | --- |
| Native Mac client | SwiftUI/AppKit, file dialogs, AVKit, ScreenCaptureKit |
| Source evidence | Bounded ZIP/folder inspection, framework/route/feature candidates and references |
| Live recordings | Native window capture; optional scripted Chromium workflows |
| Flow evidence | Step outcomes/timing, explicit feature mappings and coverage gaps |
| Composition | Video trim, speed, focus/zoom, branding, headlines and captions |
| Export | Ordered scenes, aspect/FPS normalization, cuts/crossfades, source audio and soundtrack mixing |
| Persistence | SQLite, serial jobs, cancel/retry, job snapshots, atomic completion and restart recovery |
| Agents | MCP tools for source, projects, flows, recording, scenes, coverage and export |
| Optional b-roll | ComfyUI adapter; separately installed model and workflow required |

## Development

```bash
python -m venv .venv
# Activate .venv with your platform's command, then:
python -m pip install -e '.[dev,capture]'
python -m unittest discover -s tests -v
python -m build
python -m frameva doctor
```

The unit suite uses a mocked browser driver for capture lifecycle tests. Media
tests execute FFmpeg on moving video and audio. The separate live-demo verifier
runs a real browser and pipeline when explicitly invoked. Native CI must actually
complete before a native binary can be described as validated.

## Documentation

- [Native Mac build/run](macos/README.md)
- [Live recording](docs/LIVE_FLOWS.md)
- [MCP integration](docs/MCP.md)
- [Architecture](docs/ARCHITECTURE.md)
- [Apple API research](docs/MAC_NATIVE_RESEARCH.md)
- [Research decisions](docs/RESEARCH.md)
- [Verification](docs/VERIFICATION.md)
- [Security](SECURITY.md)

Frameva code is MIT licensed and independent of Higgsfield. FFmpeg, browser
binaries, dependencies, weights, fonts and optional ComfyUI nodes retain their own
licenses. This release does not claim Higgsfield feature parity, automatic voice
generation, a full nonlinear editor or zero-touch support for every application.
