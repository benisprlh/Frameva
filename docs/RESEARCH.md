# Research decision record — 10 November 2026

## Decision

Build Frameva around **source evidence → explicit user journeys → continuous app recording → edited launch MP4**. Use Codex/Claude Code as the director through MCP, a native SwiftUI Mac workspace for the creator, and ScreenCaptureKit for actual Mac window recordings. Make neural video generation optional.

A product launch film needs readable UI, complete user journeys, consistent branding, pacing and easy revision. Version 0.1 used screenshot motion. The clarified product requirement needs moving application footage, so version 0.2 adds native window capture, repeatable browser-flow recording and composition over actual video frames. ScreenCaptureKit handles visible Mac applications; Playwright handles explicit same-origin web flows. FFmpeg edits the footage on a CPU. A separate ComfyUI adapter can supply generated b-roll.

The native Mac frontend uses SwiftUI/AppKit rather than embedding the web studio. Reusing the portable authenticated worker preserves the existing project/agent workflow and Windows path. macOS 15 is the minimum because the direct SCRecordingOutput recording path and microphone/click APIs used here are available there. Completion must wait for its recording delegate, not merely stopCapture. These decisions and primary Apple references are detailed in [MAC_NATIVE_RESEARCH.md](MAC_NATIVE_RESEARCH.md). Browser video must likewise wait for context closure; see [Playwright's video lifecycle](https://playwright.dev/python/docs/videos).

## Alternatives considered

| Approach | Benefits | Reason for this release's choice |
|---|---|---|
| Train a new video foundation model | Ownership of model behavior | Requires datasets, accelerator training, evaluation and funding; not necessary for accurate product launch footage |
| Wrap only closed model APIs | Fast access to multiple models | Introduces keys, external data transfer and per-generation costs; does not satisfy an independent local rendering path |
| Fork LTX Desktop | Existing open application with rich local video features | Strong reference; its model/hardware workflow differs from a lightweight source-to-launch studio, and model weights have separate community terms |
| ComfyUI as the entire UI | Many models and composable workflows | Useful inference engine; graph editing is not a complete evidence-to-product-launch workflow |
| Native capture + explicit browser flows + CPU composition | Actual application behavior, repeatable journeys, readable UI and agent control | Selected for 0.2; native source supplied, Mac runtime gate remains open |

## What the research established

Higgsfield is a wider creative suite, not just a single text-to-video model. Its official sources cover cinematic camera controls, reusable reference assets, project workflows and agent integration. The appropriate comparison is the workflow, not copying its proprietary models or branding. Official clip-length claims differ between pages, so they are not used as Frameva acceptance criteria.

Open video options differ materially in licensing and hardware needs. Wan2.2-5B provides a practical Apache-licensed optional baseline. LTX-2.5 offers audio/video capabilities under separate model terms. A renderer being installable on macOS does not prove a particular FP8/CUDA model graph works on Apple Silicon.

A source scanner can discover evidence candidates, not prove feature readiness. Frameva preserves file/line references and the candidate label; the coding agent should review implementation and actual screens before writing public product claims. ZIP uploads are never executed.

## Implemented release versus research proposals

The two detailed reports below include proposed capabilities and qualification gates. They are research, not a checklist of features claimed to ship. The README capability table and [verification record](VERIFICATION.md) are authoritative for this release.

- [Product, Higgsfield and ComfyUI research](PRODUCT_RESEARCH.md): official source URLs, workflow categories, API contracts, conflicting marketing claims, acceptance criteria.
- [Models, licensing and hardware research](MODEL_RESEARCH.md): Wan, LTX, Hunyuan, Mochi, Windows/Mac boundaries and existing OSS alternatives.
- [Architecture](ARCHITECTURE.md): actual local-first implementation and trust boundaries.
- [ComfyUI setup](WORKFLOWS.md): shipped templates, version assumptions and actual adapter limits.

## Remaining evidence gates

- Run native installation and source-to-MP4 E2E on macOS and Windows. CI is supplied; its jobs must actually complete before reporting native validation.
- Run each AI workflow on real hardware, with exact checkpoint, ComfyUI and custom-node versions. Protocol tests cannot replace this.
- Validate capture against the user's running app and authentication flow. Frameva cannot reconstruct a live rendered interface from source alone.
- Review a real launch video for legibility, complete journey coverage, temporal fidelity, sound and factual copy before publication.

All model research used public primary sources. No paid inference, GPU rental, model training or proprietary-model extraction was performed.
