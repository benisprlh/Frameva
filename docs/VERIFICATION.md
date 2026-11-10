# Verification — Frameva 0.2.0 developer alpha

Date: 10 November 2026. Execution host: Linux x86_64, Python 3.12.14. Native Mac
source was reviewed against Apple API documentation, but this host has no Swift
compiler, Mac SDK, ScreenCaptureKit runtime or Mac desktop.

The DMG packaging addition includes syntax/preflight checks on Linux only.
`hdiutil` creation, read-only mounting, signing and notarization still require
execution on macOS. The first native GitHub run did not start because GitHub
reported an account billing lock; it produced no native artifacts.

## Executed

| Check | Result |
| --- | --- |
| Python suite in isolated dependency environment | **85 tests passed** in 19.6 seconds, including actual MCP cwd/PYTHONPATH isolation and installer process-tree cancellation regressions |
| Real video composition | Moving video frames, trim, focus/zoom, portrait/square/landscape, playback-rate and audio-pitch preservation |
| Real exports | Video/audio crossfade overlap, soundtrack mixed under source audio, 9-scene grouped crossfade duration |
| Media bounds | Short video with longer audio rejected; video-duration fallback works without system ffprobe; insufficient footage cannot freeze silently |
| Recording API | Flow ownership/CRUD, success reports, queue snapshots, cancellation cleanup, original-plan retry, media reference protection and coverage gaps |
| Flow recorder unit contracts | 12 tests: schema, origin rules, timeout/cancel, redaction, timed typing, atomic output; mocked browser driver with actual FFmpeg WebM normalization |
| MCP | Actual stdio protocol and actual local HTTP backend for source/project/flow/coverage tools; native frozen command and optional browser install logic tested without launching a browser |
| Existing behavior | Source ZIP inspection, screenshot/title rendering, security negative cases, persistent FIFO, atomic completion, stale-export rejection and restart recovery |
| JavaScript | Web studio, example app and fixed cursor overlay parse; focused recording-form roundtrip and stale-state assertions passed |
| Visual compositor inspection | A 1280×720 synthetic moving test-pattern composition was inspected for framing and typography; it is not an application recording |
| Python compilation | Source, scripts and tests compile |
| Wheel isolation | 0.2 wheel installed outside checkout in a fresh venv; dependency check, API/static resources and bundled FFmpeg passed |

The media tests execute real encoders and inspect output. Browser-driving calls
are mocked in this suite; passing it does not establish live-browser correctness.
The scripted browser recorder needs Chromium installed separately. No actual
Playwright browser recording or ScreenCaptureKit recording ran in this session.

## Native static review

The native implementation was checked against primary Apple references. Review
identified and corrected recording-finalization timing, capture session identity,
busy-operation import handoff, stale project/preview results, worker ownership,
redirect handling and staged file replacement issues. Static review is not
compilation or hardware validation. The source includes Swift core tests and a
macOS build workflow, neither executed on this Linux host.

## Outstanding release gates

- Build Swift code and the frozen helper on macOS 15+, then launch from Finder.
- Verify system picker, cursor/click capture, audio/microphone consent, finalization,
  selected-window closure and shutdown on real Mac hardware.
- Execute `scripts/verify_live_demo.py` with a real Chromium browser on Mac and
  Windows; inspect both the raw walkthrough and the composed launch film.
- Run Codex and Claude Code host registration on the target Mac. MCP protocol
  tests passed, but those host application sessions were not available here.
- Run Windows native OS validation of the portable worker. No native Windows
  frontend or signed Windows installer is provided.
- Run optional ComfyUI/GPU inference with the exact installed model/node graph.
- Perform Developer ID signing, notarization/stapling and clean-Mac Gatekeeper
  validation before describing a build as a public Mac release.

Follow [RELEASE_ACCEPTANCE.md](RELEASE_ACCEPTANCE.md) for exact procedures.
Configured GitHub Actions workflows are supplied configuration, not remote run
results. No `.app`, `.dmg`, paid cloud runner or signing credential is fabricated.

## Reproduce

From the source folder, with the installed environment:

```bash
python -m unittest discover -s tests -v
python -m frameva doctor
python -m build
python scripts/verify_wheel.py dist/frameva_studio-0.2.0-py3-none-any.whl
```

For real-browser acceptance, install `.[dev,capture]`, run
`python -m frameva install-browser`, then the opt-in verifier. The Python wheel is
the portable worker and web studio; the complete source archive includes native
Mac source, build scripts, example app, tests and research. It excludes tokens,
private databases, virtual environments, downloaded browser binaries, generated
QA frames and model weights.

The 0.1 screenshot demo is historical output and is not presented as 0.2 live-flow
footage. Its previous browser UI QA does not substitute for native Mac validation.
