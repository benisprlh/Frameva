# Changelog

## 0.2.0 — Native Mac and live workflows (developer alpha)

- Native macOS 15+ SwiftUI/AppKit source application, ScreenCaptureKit system
  content picker, cursor/click capture, optional system/microphone audio, and
  AVKit playback. Import waits for actual recording finalization.
- Bundled-worker build tooling and native CI configuration. Native compilation,
  permissions, signing and real device recording remain an unexecuted release gate.
- Structured browser flow plans with real continuous video, paced cursor/input,
  assertions, deadlines, cancellation, safe runtime secret inputs and step reports.
- Recording scenes with real temporal video, trim, speed, focus/zoom and source
  audio. Reject insufficient footage, including when an audio stream is longer
  than its video. Preserve duration validation without ffprobe.
- Cuts/crossfades with matching audio overlap; optional music mixed under source
  audio. Crossfades shorten final runtime by their overlap.
- Explicit source-feature mappings and recorded-coverage gaps. Edited plans and
  unrecorded candidates remain visible; no exhaustive verification claim.
- Persistent flow CRUD, queued record jobs, immutable retry snapshots, atomic
  report/asset completion, reference protection and project cleanup.
- 31 MCP tools; native frozen-helper configuration; record-flow and explicit
  install-browser CLI commands. Browser installation is never implicit at startup.
- Legacy web studio safely edits recording scenes and exports transitions.
- Working Orbit sample app, flow plan, opt-in real-browser acceptance script and
  cross-platform workflow configuration. These are runnable test assets, not a
  claim that real Chromium or Mac capture ran in the Linux development session.

## 0.1.0 — Source-aware studio alpha

- Bounded repository/ZIP evidence reader, launch storyboard and local media.
- Deterministic screenshot/title composition, ComfyUI adapter, persistent queue.
- Authenticated loopback service, browser studio, 22 MCP tools, portable launchers.
- 47 Linux tests, clean-wheel smoke and browser studio QA passed. No native
  desktop frontend or verified GPU inference was included.
