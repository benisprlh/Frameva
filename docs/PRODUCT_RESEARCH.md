# Frameva product and integration research

Research date: 10 November 2026. This is an independent product design, not a claim of Higgsfield compatibility or feature parity. Sources are official vendor documentation and upstream repositories. Hardware/model licensing research is recorded separately.

## Product conclusion

Frameva should first deliver a reliable source-to-launch workflow: inspect a selected code repository without executing it, derive an editable product brief with evidence, create a storyboard, attach screenshots from the real application, render animated product scenes, and export a playable MP4. A CPU renderer makes this useful on Mac and Windows immediately. Generative AI footage should be an optional renderer for supplementary scenes, not a dependency for making a truthful product demonstration.

This follows the user's clarified objective rather than cloning the entire Higgsfield suite. The strongest differentiation is the coding-agent workflow: an agent already working in a repository can prepare and revise a launch video through MCP while preserving traceability to actual application screens and features.

## What Higgsfield currently provides

Higgsfield's enterprise help center describes a creative suite spanning cinematic generation, reusable characters/locations/props, marketing assets, model graphs, agent-led production, ad variants, and narrated content. Cinema Studio groups project references and generations with camera, lighting, acting, and extension controls. These are useful workflow categories to benchmark, not implementation details to reproduce. [H1]

Its integration documentation describes an authenticated MCP service and CLI access. Agent-generated outputs join the asset library. The documented operations extend beyond video into images, audio, editing and reusable characters. References uploaded into a chat are not automatically available to its generator. [H2]

The Cinema Studio help article describes shot-level camera parameters, global visual direction, reference Elements, and an assistant that drafts prompts for review. It says version 4.0 supports clips up to 30 seconds. [H3] The current marketing landing page instead advertises up to one minute and native 4K. [H4] The CLI page describes video up to 15 seconds. [H5] These values are inconsistent across pages and likely refer to changing surfaces/models. Frameva must report its own tested limits rather than treat one of these numbers as a universal parity target.

## Achievable scope and truthful labels

The table is a proposed product boundary; the release verification document must state what was actually implemented and tested.

| Capability | Frameva approach | Required qualification |
|---|---|---|
| Source inspection | Read-only local folder or bounded ZIP scan | Source findings are candidates, not proof of working features |
| Product brief | Name, description, feature candidates, evidence paths | User/agent reviews claims before publication |
| Script and storyboard | Editable ordered shots with headline, caption, camera and layout | Rule-based drafts must not be labelled LLM reasoning |
| UI footage | Screenshots from a user-specified running app or uploaded images | Never invent an interface and present it as the user's app |
| Motion graphics | CPU rendering of typography, screenshots and transitions | Real product-motion rendering, not a generative video model |
| Text/image-to-video | ComfyUI API workflow adapter | Model, nodes and weights must be installed separately |
| Camera presets | Motion transforms for product scenes; prompt/binding controls for AI | Prompt wording is not guaranteed physical camera control |
| Asset library | Project-owned uploaded and generated media | Reusable references do not guarantee identity consistency |
| Render queue | Durable jobs, status, cancellation, retry and provenance | Distinguish local cancellation from remote GPU interruption |
| Multi-shot export | Normalize clip dimensions/FPS, concatenate, attach audio | Validate actual media before accepting a completed job |
| Codex/Claude Code | Same operations exposed through local stdio MCP | An MCP transport test is different from testing both host apps |
| macOS/Windows | Python service, browser UI, cross-platform launchers | Native OS testing needs those operating systems |
| Full video editing | Small ordered-shot composition first | Do not claim a complete nonlinear editor |
| Voice cloning, lip sync, face replacement | Outside first release | Separate model licensing, identity and quality work |
| Team collaboration, billing, cloud fleet | Outside local-first release | A single-user desktop service is not a multi-tenant SaaS |

## Source-to-launch evidence architecture

Recommended separation:

1. **Inspect:** accept a user-selected source root or ZIP. Read bounded text only. Skip dependency/build/hidden/credential files and symlinks; never run package scripts or import source modules. Return candidate features with file/line evidence and scanning limits.
2. **Plan:** convert evidence into an editable brief and ordered shots. Preserve `candidate`, `documentation_claim`, or `ui_heading` provenance rather than silently promoting findings to verified features.
3. **Capture:** independently capture a running app chosen by the user or consume uploaded screenshots. A screenshot proves what appeared at capture time; it does not prove an entire workflow works. Avoid repository-supplied browser instructions or credentials.
4. **Compose:** use deterministic motion graphics for actual UI demonstrations. Keep generated b-roll visually and structurally separate from genuine interface footage.
5. **Render:** persist the scene settings, renderer version, referenced asset IDs, errors and output IDs. Restart should recover unfinished jobs without duplicating completed work.
6. **Review/export:** play the result, inspect representative frames and metadata, and export an MP4 with clear product claims. A launch plan is a draft until reviewed.

The app should not automatically execute a repository merely because it was uploaded. An agent can separately start the user's trusted application using its normal permission model. Source text, README instructions and filenames remain untrusted data throughout Frameva's pipeline.

## ComfyUI local API contract

ComfyUI documents separate API routes for queue submission, status/history, uploads, output retrieval, node discovery and system diagnostics. [C1]

| Purpose | Route | Adapter behavior |
|---|---|---|
| Diagnostics | `GET /system_stats` | Check connectivity/device information; redact unnecessarily detailed diagnostics in UI |
| Node capability discovery | `GET /object_info` | Verify every workflow node class and required input |
| Image input | `POST /upload/image` | Multipart upload; use returned name, subfolder and type |
| Submit | `POST /prompt` | Send API-format graph and client ID; persist returned prompt ID |
| Poll | `GET /history/{prompt_id}` | Distinguish empty history, execution error and completed output |
| Output | `GET /view` | Retrieve only returned filenames/subfolders/types; bound bytes |
| Pending queue | `GET/POST /queue` | Remove only the matching pending prompt when supported |
| Interrupt | `POST /interrupt` | Treat as renderer-wide unless deployed version proves scoped interruption |
| Progress | `WS /ws` | Filter events by prompt ID; handle reconnect through history polling |

The official WebSocket documentation distinguishes start, error, interruption, cached nodes, progress and successful completion. `executed` is a UI update event, not a universal signal that each node finished. [C2] The upstream Python API example submits a graph keyed by string node IDs, each containing `class_type` and `inputs`; connections use a pair of upstream node ID and output index. It downloads outputs after consulting history. [C3]

Implementation recommendations: apply a request timeout, a maximum job deadline and bounded downloads; do not retry submission blindly after an ambiguous response; use a unique local job-to-prompt correlation; preserve execution errors rather than mark an empty history result successful. A dedicated ComfyUI instance simplifies safe cancellation. Avoid using global interrupt against a shared instance.

## Workflow import and native video outputs

The visual editor workflow JSON and executable API prompt graph are different representations. Frameva should require API-format import with explicit field bindings instead of trying to guess positional widget meanings from arbitrary editor graphs. UI controls should map only to declared existing node inputs. Never evaluate imported expressions or scripts.

ComfyUI's template browser includes native and custom-node examples and manages model requirements; template model links are embedded in loader metadata. Availability still depends on installed ComfyUI version and nodes. [C4] Its official Wan 2.2 tutorial documents a 5B hybrid workflow supporting both text and image inputs, plus separate larger T2V, I2V and first/last-frame workflows. [C5]

For the native 5B path, the important latent node accepts `vae`, `width`, `height`, `length`, `batch_size`, and optional `start_image`. Width/height use steps of 32; frame length follows a step of four with default 49. [C6] `CreateVideo` combines images using `fps`, with optional audio. [C7] `SaveVideo` accepts a video and filename/container settings; its current schema has dynamic codec options, so version-aware discovery matters. [C8]

The upstream native video implementation returns `PreviewVideo` containing saved result descriptors. [C9] The UI serializer places native video descriptors under `images` with an animated marker, rather than requiring a `videos` field. [C10] A robust adapter must inspect extensions/content and support the documented native shape plus explicitly supported extension-node output shapes. It must not declare an image-only output to be a completed video.

## Acceptance evidence

For the source-to-launch path, a useful end-to-end test uses a fixture repository with a known README feature and real UI screenshot, creates a plan, edits/reorders scenes, renders two or more clips, exports a final video and confirms dimensions, duration, codec and successful decoding. Inspect frames to ensure screenshot content, long headings and portrait layouts remain legible. Add secret/symlink/ZIP traversal/ZIP bomb bounds and HTML/script-like text cases.

For the ComfyUI adapter, protocol fixtures can verify submission, uploads, node errors, history, output download, timeout and cancellation behavior. These are integration-contract tests, not proof of neural generation. Final readiness for a model requires a live ComfyUI instance, exact weights, a real generated clip and its metadata. For macOS and Windows, packaging/launcher tests in CI help, but native launch and render evidence must be reported separately. Never label a CPU motion video an AI-generated sample to hide missing GPU verification.

## Sources

- [H1 — Higgsfield Tools & Workflows](https://higgsfield.ai/enterprise-help-center/platform/tools-creative-workflow)
- [H2 — Higgsfield MCP, CLI & Plugins](https://higgsfield.ai/enterprise-help-center/platform/integrations)
- [H3 — Higgsfield Cinema Studio help](https://higgsfield.ai/creator-hub/help-center/tools/how-do-i-use-cinema-studio)
- [H4 — Higgsfield Cinema Studio product page](https://higgsfield.ai/cinematic-video-generator)
- [H5 — Higgsfield CLI](https://higgsfield.ai/CLI)
- [C1 — ComfyUI server routes](https://docs.comfy.org/development/comfyui-server/comms_routes)
- [C2 — ComfyUI server messages](https://docs.comfy.org/development/comfyui-server/comms_messages)
- [C3 — Upstream WebSocket API example](https://github.com/Comfy-Org/ComfyUI/blob/master/script_examples/websockets_api_example.py)
- [C4 — ComfyUI workflow templates](https://docs.comfy.org/interface/features/template)
- [C5 — Official Wan 2.2 workflow tutorial](https://docs.comfy.org/tutorials/video/wan/wan2_2)
- [C6 — Wan22ImageToVideoLatent](https://docs.comfy.org/built-in-nodes/Wan22ImageToVideoLatent)
- [C7 — CreateVideo](https://docs.comfy.org/built-in-nodes/CreateVideo)
- [C8 — SaveVideo](https://docs.comfy.org/built-in-nodes/SaveVideo)
- [C9 — Native video nodes source](https://github.com/Comfy-Org/ComfyUI/blob/master/comfy_extras/nodes_video.py)
- [C10 — Native UI output serialization](https://github.com/Comfy-Org/ComfyUI/blob/master/comfy_api/latest/_ui.py)
