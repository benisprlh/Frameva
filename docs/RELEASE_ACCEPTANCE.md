# Native release acceptance

This is an executable release gate for the developer alpha, not a record of
checks already performed. Actual results belong in VERIFICATION.md.

## Real browser pipeline

Install the source project with `.[dev,capture]`, then:

```bash
python -m frameva install-browser
python scripts/verify_live_demo.py --output-directory live-demo-output
```

The script serves only the bundled Orbit app on an ephemeral loopback port,
creates an isolated Frameva project, inspects demo source, records the complete
flow through the API queue, composes title / live footage / CTA, mixes original
procedural audio and downloads the exported MP4. It checks completed step count
and saves evidence JSON. Existing output directories are rejected.

Inspect `launch-film.mp4` and `raw-walkthrough.mp4`. Confirm actual task creation,
completion, filtering and analytics are visible; confirm text is readable and
cursor movement is useful. The capture report is not a substitute for watching
the film. Source analysis may also surface promotional headings as candidates;
the coverage report intentionally leaves unmapped candidates visible.

This script starts a real headless Chromium browser. It is opt-in and is not run
by the default mocked-driver unit suite. Failed output should be retained for
local diagnosis; no success report is written after a failed job.

## Native app on a Mac

Build the app using macos/README.md, then perform these checks:

1. Start the app from Finder on a clean user account without a separate Python
   installation. Verify the packaged worker starts and the project list loads.
2. Create a project, import source, review evidence, and create scenes. Quit and
   reopen; verify persistence. Connect an existing compatible worker and confirm
   quitting the native app does not terminate a worker it does not own.
3. Choose a window in the system picker; test cancel and choose again. Record a
   real workflow, including cursor movement and a click. Stop and confirm import
   occurs only after finalization. Test system-menu stop and selected-window close.
4. Test microphone off, consent allowed, and consent denied; test system audio.
   Listen to the recorded file before composing it.
5. Import an existing clip, adjust trim/speed/focus/zoom, render and preview.
   Confirm invalid trim is rejected. Compare against the original moving footage.
6. Record the Orbit browser flow. Install Chromium only when explicitly requested.
   Test a failing selector/assertion, cancellation, retry and edited-plan rerecord.
7. Export multiple scenes with crossfades and an audio track. Save outside the
   app cache, play in QuickTime, inspect duration and audio, and verify existing
   files survive cancelled/failed saves.
8. Connect Codex and Claude Code independently using the helper MCP command.
   Let each list projects, create a flow, inspect its job and download an export.
9. Quit during capture and during a render. Verify no partial recording is shown
   as complete, no orphan worker remains, and restart recovers queued job state.
10. Run the native Swift tests, Python suite, wheel smoke and bundle smoke.

Run these on every advertised architecture and minimum supported macOS version.
The initial build script builds the current Mac architecture; it is not an
untested universal binary. A public signed release also requires Developer ID,
inside-out signing, notarization/stapling and a Gatekeeper check on another Mac.
No developer account credential is included in this source project.
