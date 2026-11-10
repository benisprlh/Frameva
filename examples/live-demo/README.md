# Orbit live workflow demo

A working local task app for demonstrating **real browser video recording** in Frameva. Task creation, completion, filtering and analytics change application state; the recording is not assembled from screenshots. This sample app and its data are examples, not claims about your own product.

## Features

- Create tasks
- Track project progress
- Filter tasks
- Inspect live analytics

## Run the target app

From the Frameva source directory, run:

```sh
python -m http.server 4173 --bind 127.0.0.1 --directory examples/live-demo
```

On Windows use `py -3` instead of `python` when appropriate. Open `http://127.0.0.1:4173` to inspect the app. It uses only local HTML/CSS/JavaScript and browser storage. No account, analytics or remote asset service is required.

## Record it

Install Frameva's optional capture dependencies in its Python environment:

```sh
python -m pip install -e '.[capture]'
python -m frameva install-browser
```

Keep the demo app and Frameva worker running. In Frameva, create a flow using the complete contents of `launch-flow.json`, then record it. The API route is `POST /api/projects/{project_id}/flows`; submit the returned flow ID to `POST /api/flows/{flow_id}/record`. The resulting video asset can be used by a recording shot, edited and exported. Codex/Claude Code can author and submit the same plan through Frameva MCP.

The recorder starts a clean browser context every time, so the demonstration starts with the six initial tasks even if you changed data in your own browser. Its steps create a task, complete an existing task, filter the board and check that analytics reflect the change. A failed assertion fails the recording; partial output is not published as successful footage.

## Recording boundaries

- This example was validated through schema/unit contracts and media normalization. A live Playwright recording still needs to be run on your machine; no native-browser execution is implied by those tests.
- Output is continuous browser video with a visible cursor/ripple overlay. Initial loading and action pauses remain real recorded time.
- Plain-text fields type at 35 ms per character by default. Set a fill step's `typing_delay_ms` to 0 for instant fill, or 1–150 for a custom pace. Secret values always fill instantly.
- Older Playwright versions record at 25 FPS. Frameva normalizes to the requested output FPS; this does not create additional captured motion detail.
- Browser/system audio is not captured. Add a soundtrack after recording, or use the native window recorder for supported capture modes.
- Steps use one origin and one page. Popups and cross-origin navigation fail the recording. External subresources remain permitted for normal applications.
- Use disposable demo accounts and data. `click`, `fill` and `press` are real actions and can change the target app. The recorder never executes uploaded source code or installs the target application.
- `secret_env` is only for explicitly provisioned `FRAMEVA_FLOW_SECRET_*` environment variables. Values stay out of the saved plan/report, but an app may display them in its video. Review recordings before sharing.
- Never put passwords, tokens or credentials in a literal `value`: literal values are saved in flow plans. Use `secret_env` for credentials.
- Feature mappings name the source features you intend to demonstrate. Passing these steps does not establish complete feature coverage.

## Official API basis

- [Playwright video lifecycle](https://playwright.dev/python/docs/videos): close the context before reading the completed video; set record size explicitly.
- [Isolated browser contexts](https://playwright.dev/python/docs/api/class-browsercontext)
- [Locator actions and assertions](https://playwright.dev/python/docs/api/class-locator)
