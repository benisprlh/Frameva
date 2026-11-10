# Live workflows and launch films

A live workflow recording is continuous video of the running app. It captures
navigation, typing, clicks, scrolling, animation and results. A composed film
uses selected parts of that footage with editorial titles and transitions.

## Native Mac recording

Build/open the native app using [macos/README.md](../macos/README.md). Create or
select a project, open the recorder, choose the window with the macOS system
picker, and start capture. Perform the product journey in the selected app, then
stop. Import begins after ScreenCaptureKit finishes writing the file. You can
also import an existing local MP4/WebM.

Use a demo account, readable window dimensions and deliberate pacing. Native
capture follows the person using the app; it does not invent or replay unobserved
native controls. The system picker and optional microphone consent are local OS
permissions, not Frameva account permissions. See native setup for troubleshooting.

## Scripted browser recording

Install the optional recorder into the same Python environment as Frameva:

```bash
python -m pip install -e '.[capture]'
python -m frameva install-browser
```

For the native bundle, run the embedded helper's `install-browser` command instead;
the helper includes the Python driver. Chromium is a separate download in the
normal Playwright cache. Startup never downloads it implicitly.

The target app must already be running. A flow file looks like this:

```json
{
  "name": "Create and inspect a project",
  "base_url": "http://127.0.0.1:3000",
  "width": 1440,
  "height": 900,
  "fps": 30,
  "max_duration": 90,
  "feature_titles": ["Project creation"],
  "steps": [
    {"action": "click", "selector": "button:has-text('New project')", "label": "Start a project"},
    {"action": "fill", "selector": "input[name='name']", "value": "Launch week"},
    {"action": "click", "selector": "button:has-text('Create')"},
    {"action": "assert_text", "selector": "main", "text": "Launch week"},
    {"action": "wait", "seconds": 2, "label": "Show the result"}
  ]
}
```

Selectors must match the target application. This example is illustrative; the
included [live demo](../examples/live-demo/README.md) supplies matching app code
and a complete plan. The agent should inspect the actual UI before authoring a
plan, and use exact source feature titles for coverage mappings.

```bash
python -m frameva record-flow plan.json --output walkthrough.mp4
```

The native Flow editor and MCP tools can save the same plan and queue recording
as a persistent job. On success the asset has a step report. On failure, fix the
plan/app state and record again. Retry replays the original job snapshot; after
editing a plan, queue a new record operation to use the edits.

Supported actions: `goto`, `click`, `fill`, `press`, `scroll`, `wait`,
`assert_text`. Only HTTP(S) URLs are accepted. Navigation stays on the exact base
origin (scheme, host and port); one page is supported, popups are rejected.
Third-party sign-in/SSO and cross-origin frames may therefore require native
manual capture instead. A clean browser starts without the person's login state.
Source repositories are never executed by the recorder.

`fill` visibly types ordinary demo text at 35 ms per character by default. Set
`typing_delay_ms` from 0 to 150 to adjust it (0 fills instantly). Secret inputs
are filled instantly. Pointer movement and scroll are paced. Use assertions for
readiness and short `wait` actions for editorial holds, not long arbitrary waits
to hide a broken workflow. `max_duration` bounds capture including startup;
normalization has its own bounded timeout. Recording itself is limited to 300 s;
a recording scene can use up to 120 s, and a film can combine multiple scenes.

## Secret inputs

For a secret fill use `secret_env` instead of `value`:

```json
{"action":"fill","selector":"input[type='password']","secret_env":"FRAMEVA_FLOW_SECRET_DEMO_PASSWORD"}
```

Set that variable in the worker environment before starting it. Only names
beginning with `FRAMEVA_FLOW_SECRET_` are accepted. Plans/reports do not include
resolved environment values. Literal values in `value` are persisted as plan
content, so use them for demo data. A website can still display an input or
response in the recorded pixels; inspect the video before sharing it.

## Editing real footage

Create a scene with `provider: "recording"` and its `video_asset_id`. Set
`trim_start`, output `duration`, `playback_rate`, `zoom`, normalized `focus_x` /
`focus_y`, `keep_audio`, headline, caption and brand color. The source needs at
least `trim_start + duration * playback_rate` seconds. Focus identifies the point
around which the crop/zoom is placed. Avoid cutting important user input/results.

For a launch film, keep the opening short, show complete useful journeys, and
finish with a clear action. A 30–60s teaser may not fit every function; create a
longer walkthrough or a series when the coverage report shows omitted journeys.
A practical structure is title → key journey → second journey → result → CTA.
This is an editorial guide, not a fabricated claim that every app fits the same
story.

Crossfade overlap reduces final duration. Source audio is retained when enabled;
optional uploaded music/narration is mixed at the renderer's fixed level. No
voice generation is included. Browser recording is silent; native capture can
include app/system audio and optionally the microphone.

## Validation boundaries

- Browser step timestamps are approximate, not frame-accurate edit points.
- Output FPS is normalized; it may include duplicate frames from the browser's
  lower capture rate. Native recording requests 30 fps.
- A feature mapped to a completed flow is marked recorded, not exhaustively
  verified. Changed flow plans need another recording.
- Source analysis discovers heuristic candidates; it cannot infer every business
  rule or every hidden application function.
- Native capture, compiled packaging and actual browser-driver operation require
  the platform checks listed in [VERIFICATION.md](VERIFICATION.md).
