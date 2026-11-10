# Frameva model and rendering research

Verified against primary upstream sources on 10 November 2026. This is a design and documentation review, not a GPU benchmark or a claim that every workflow has been tested on macOS/Windows.

## Recommendation for the actual product

Use a deterministic CPU renderer for source-to-launch videos: screenshot or existing-media input, configurable pan/zoom/crop, captions, title cards, transitions, audio mixing, and MP4 export. This is appropriate for accurate product demos because it preserves the supplied UI. Label it **motion rendering**, not generative AI video. Let Codex/Claude Code author the storyboard through MCP, then render the approved scenes. AI-generated b-roll should be an optional provider, with the model name, license, GPU needs, and whether the output was actually generated visible in job metadata.

For optional AI, use an independently installed ComfyUI service behind the Frameva backend. Default recommendation: Wan2.2-TI2V-5B for permissively licensed text/image-to-video. Add LTX-2.5 as an opt-in workflow for synchronized audio/video and richer editing only after license acceptance and GPU validation. Keep Windows/macOS support for the application separate from model inference support; both systems can control a remote CUDA renderer.

## Model comparison

| Model | Verified capabilities | Official hardware guidance | License and product decision |
|---|---|---|---|
| Wan2.2-TI2V-5B | One model supports text and image inputs; 720p class output at 24 fps. Upstream reference dimensions are 1280×704 or 704×1280. | Upstream CLI needs at least 24GB VRAM using model offload, dtype conversion, and CPU text encoder. Upstream claims a five-second 720p clip in under nine minutes on a consumer GPU; this is not a Frameva benchmark. | Apache-2.0 models. Best permissive default for optional b-roll. [Wan upstream](https://github.com/Wan-Video/Wan2.2) |
| Wan2.2 A14B / S2V / Animate | Separate large text/image models, speech-conditioned video, and character animation/replacement exist. S2V consumes audio; it is not a guarantee of native newly generated soundtrack. | Larger workflows are materially heavier than 5B; do not map the 5B requirements onto these variants. | Treat as separately installed provider workflows with individual capability detection. [Wan upstream](https://github.com/Wan-Video/Wan2.2) |
| LTX-2.5 | Official model card describes synchronized video/audio, text/image/video input, native multishot, improved decoder and distilled model, and an optional duration predictor. | Current official requirements: NVIDIA 32GB+ VRAM, 32GB RAM, 100GB free storage, CUDA 12.7+, Python 3.12+. Recommended A100 80GB/H100 and 64GB+ RAM. | Model uses LTX-2.x Community License, separate from Apache inference code. Optional advanced renderer, not an unconditional permissive-model default. [Model card](https://huggingface.co/Lightricks/LTX-2.5), [requirements](https://docs.ltx.io/open-source-model/getting-started/system-requirements) |
| HunyuanVideo-1.5 | Text/image-to-video; upstream has distilled variants and super-resolution support. | Upstream specifies Linux, NVIDIA CUDA, Python 3.10+, minimum 14GB GPU memory with offloading. Source-code requirements do not establish native Windows/Mac support. | Tencent community terms have geographic/use restrictions. Do not enable globally by default. [Repository](https://github.com/Tencent-Hunyuan/HunyuanVideo-1.5) |
| Mochi 1 | Text-to-video, LoRA support, native ComfyUI integration; older baseline useful for comparisons. | Official reference implementation needs about 60GB VRAM; upstream says ComfyUI optimizations can run below 20GB. H100 recommended for reference implementation. | Apache-2.0. Optional, lower priority than Wan for the first integration. [Repository](https://github.com/genmoai/mochi) |
| Legacy LTX-Video v0.9.x | Text/image-to-video, keyframes, extension, pose/depth/canny control; original repository documents MPS support. | MPS was tested with PyTorch 2.3.0; upstream suggests 2.3 or >=2.6. Smaller 2B models exist. | Apache code does not establish the model-weight license. Historical checkpoint terms vary; do not label all checkpoints Apache. Upstream recommends LTX-2.5 for new projects. [Repository](https://github.com/Lightricks/LTX-Video) |

## ComfyUI integration contract

The official API supports `POST /prompt` (validated graph submission), `/history/{prompt_id}`, `/queue`, `/object_info`, `/system_stats`, `/upload/image`, `/view`, and `/ws` progress. `/interrupt` stops the currently running workflow, so it must not be exposed as cancellation of one job on a shared renderer without checking ownership and active prompt identity. See [official server routes](https://docs.comfy.org/development/comfyui-server/comms_routes).

Recommended Frameva implementation: maintain a stable local job ID mapped to upstream `prompt_id`; validate a small set of administrator-installed workflow templates; inject only declared inputs; reject arbitrary user-supplied executable nodes; persist queue/job events; handle polling, timeouts, upstream validation failures and reconnects; copy final artifacts into application-managed storage. Server-side connection configuration prevents users from turning a renderer URL into arbitrary SSRF. A provider being reachable is not equivalent to a model being installed or render-compatible. Capabilities should be based on required nodes, model filenames and a real smoke render.

ComfyUI's official Wan tutorial states 5B should fit in 8GB VRAM with its native offloading. This differs from the 24GB upstream CLI because the runtime and offload configuration differ. Do not promise comparable speed or resolution on all 8GB devices. Its example uses `wan2.2_ti2v_5B_fp16.safetensors`, `wan2.2_vae.safetensors`, and an FP8 text encoder. Treat that default as CUDA-oriented until validated elsewhere. Missing nodes may mean an outdated build or an import failure, not simply a missing model. [Official Wan ComfyUI tutorial](https://docs.comfy.org/tutorials/video/wan/wan2_2).

LTX's official integration recommends ComfyUI and supplies templates, models, custom nodes and advanced workflows. Its current setup page asks for CUDA hardware with 32GB+ VRAM. Pin the tested workflow JSON and node versions: installing the newest node package alone does not establish compatibility with every historical workflow. [Official LTX ComfyUI guide](https://docs.ltx.io/open-source-model/integration-tools/comfy-ui).

## Platform support and honest claims

| Platform | Frameva CPU app/render | Optional generative renderer |
|---|---|---|
| Windows 10/11 | Native Python/FFmpeg launch path can be provided; actual Windows E2E must run before claiming validated. | Windows Comfy Desktop is available. NVIDIA is the preferred initial qualification target. AMD/ARM64/CPU being supported by the app is not proof a given video graph works. |
| Apple Silicon macOS | Native Python/FFmpeg launch path can be provided; actual macOS E2E must run before claiming validated. | Comfy Desktop supports M1+ and macOS 13+. MPS operator/dtype support, available unified memory, and model precision remain workflow-specific. Avoid claiming a standard FP8 CUDA workflow works unchanged. |
| Intel macOS / low-memory devices | CPU motion rendering or remote renderer client. | Recommend remote NVIDIA ComfyUI; do not promise practical local diffusion-video speed. |
| Linux NVIDIA | CPU app and remote-provider interface. | Strongest upstream reference support for CUDA models; qualify the selected GPU, driver, PyTorch, model and workflow versions together. |

Sources: [Comfy macOS installation](https://docs.comfy.org/installation/desktop/macos), [Comfy Windows installation](https://docs.comfy.org/installation/desktop/windows). Upstream issue reports demonstrate Mac dtype/rendering failures, but these are not a universal verdict on all current MPS builds: [Wan2.2 Apple Silicon banding issue](https://github.com/Comfy-Org/ComfyUI/issues/15010), [MPS float8 issue](https://github.com/pytorch/pytorch/issues/132624).

## Licensing boundaries

Application source can have its own OSI license. Separately downloaded model weights, text encoders, LoRAs, ComfyUI/custom nodes, FFmpeg builds and media assets retain their own terms. Keep them out of a blanket claim that everything is MIT/Apache. Prefer independent services and documented notices; no model weights need to be redistributed with Frameva.

LTX-2.5 uses the LTX-2.x license dated August 11, 2026, amended October 29, 2026. It separates Apache inference/training source from model materials, imposes use restrictions and downstream terms, and generally requires a paid license when an entity's aggregated annual revenue reaches $10M, with its stated noncommercial exception. Fine-tune/LoRA transfers carry further conditions. [Authoritative license](https://github.com/Lightricks/LTX-2/blob/main/LICENSE-2_x). It should be described as **open weights under a community license**, not unrestricted open-source weights.

HunyuanVideo-1.5's current agreement excludes the EU, UK and South Korea from its defined territory; has a >100M monthly-active-user commercial licensing clause measured at release; restricts improving other AI models using it/output; and requires downstream notices/use terms. This is a poor default for a globally distributed SaaS. [Authoritative license](https://github.com/Tencent-Hunyuan/HunyuanVideo-1.5/blob/main/LICENSE).

## Existing project to evaluate before expanding scope

Official [LTX Desktop](https://github.com/Lightricks/LTX-Desktop) already offers an Apache-2.0 desktop app with local text/image/audio video generation, retake, extend, IC-LoRA effects, camera recipes, a persistent queue and assets, editor, and assistant. Weights are downloaded separately. Its current macOS local path is app-specific: macOS 26 and Apple Silicon, 48GB for full local generation, 32GB limited to 540p/five seconds. Windows/Linux guidance asks for NVIDIA 24GB+ VRAM and 32GB RAM. This is useful reference/reuse research; those requirements do not prove the separate ComfyUI adapter works on Macs.

## Qualification gates still required

1. Native macOS and Windows app startup, upload, Unicode paths, FFmpeg process cancellation and MP4 playback.
2. Actual GPU render for each optional workflow, with exact hardware, checkpoint hashes and dependency versions recorded.
3. Confirm all advertised controls are supported by that workflow. A camera prompt preset is a request to a model, not deterministic camera geometry.
4. Distinguish upscale/transcode from native high-resolution generation; distinguish audio muxing from generated audio.
5. End-to-end cancellation/retry/restart without overwriting completed assets or interrupting other users' renders.
6. License notices and provider-specific terms before enabling restricted model families for other users.

No paid inference, model download, GPU provisioning, native-platform execution or rendering benchmark was performed for this research.
