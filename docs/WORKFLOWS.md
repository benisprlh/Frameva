# Product motion and optional AI renderers

Frameva's main product-launch workflow works on a CPU. It reads evidence from your source tree, creates editable shots, and renders real screenshots with typography and motion. This does **not** run a generative video model. It is useful when a launch video must show exactly the interface you shipped.

Use ComfyUI when you want optional AI-generated footage. Its models, custom nodes, GPU, and licenses are separate installations. Frameva does not download model weights, execute your source code, or install custom nodes automatically.

## Product motion

1. Analyze the repository or upload its ZIP and review the extracted evidence.
2. Create a launch plan, edit its headlines and captions, and add authentic screenshots as shot references.
3. Select **Product motion**. The slow push, pull back and lateral camera presets animate the screenshot in two dimensions; **Gentle drift** is a subtle translation, not reconstructed 3D geometry.
4. Generate the shots and export the storyboard. Without a screenshot, the shot becomes a designed title card. This is disclosed in the UI rather than presented as an app screenshot.
5. Optionally upload an audio track and select it for export. Frameva loops the supplied soundtrack to match the final edit; without it, original clip audio is preserved, and silent shots receive a silent audio track for reliable concatenation.

MP4 output uses H.264 video and AAC audio, with even pixel dimensions and fast-start metadata for browser playback. Frameva first looks for system FFmpeg, then the `imageio-ffmpeg` bundled executable. If no `ffprobe` is installed, metadata inspection falls back to FFmpeg. Set `FRAMEVA_FFMPEG` to an absolute executable path if you manage FFmpeg yourself.

## Connect ComfyUI

Install ComfyUI using [its official installation guide](https://docs.comfy.org/installation/desktop). Windows NVIDIA is the most direct local route for CUDA video workflows. The ComfyUI application also supports Apple Silicon, but that does not guarantee that a particular CUDA model or custom node runs on Metal/MPS. A Mac can operate Frameva against a separate Windows/Linux GPU renderer.

Start ComfyUI, then set the renderer base URL in Frameva's settings, usually `http://127.0.0.1:8188`. Keep the renderer private or behind authentication. For a compatible bearer-authenticated reverse proxy, set `FRAMEVA_COMFY_TOKEN` in Frameva's server environment. Frameva does not log or return this token. HTTPS verification is enabled; self-signed deployments need a properly trusted certificate rather than disabling verification.

## Included Wan 2.2 configurations

Frameva includes text-to-video and image-to-video API configurations assembled from the official ComfyUI native Wan 2.2 5B workflow. They require the following separately downloaded files:

| ComfyUI folder | Filename |
| --- | --- |
| `models/diffusion_models` | `wan2.2_ti2v_5B_fp16.safetensors` |
| `models/text_encoders` | `umt5_xxl_fp8_e4m3fn_scaled.safetensors` |
| `models/vae` | `wan2.2_vae.safetensors` |

Start at 1280×704 or 704×1280 and 24 FPS. Frame counts are rounded to 4n+1. The templates use native nodes, including `Wan22ImageToVideoLatent`, `CreateVideo` and `SaveVideo`. Their upstream reference was authored against ComfyUI core 0.3.45. Frameva checks that each node exists before submission; model filenames and schema still must match your installation. These templates were checked against upstream definitions, **not run on a GPU in this environment**. If a newer ComfyUI changes node inputs, export its working API graph and import the updated configuration.

Source: [official workflow JSON](https://raw.githubusercontent.com/Comfy-Org/workflow_templates/main/templates/video_wan2_2_5B_ti2v.json). Configuration in `frameva/workflows` is included in both source and Python wheel distributions.

## Import a trusted workflow

1. Start from an [official ComfyUI video example](https://docs.comfy.org/tutorials/video/wan/wan2_2) and install the exact model files it names.
2. Run it successfully **inside ComfyUI first**. Inspect all custom nodes and licenses before installing anything. Workflow nodes execute on your renderer and must be trusted.
3. Export the **API-format** workflow, not the visual editor JSON containing `nodes` and `links`.
4. In Frameva, import the API graph and bind your scene fields to the corresponding scalar node inputs. The UI accepts the wrapper below, which is also the REST `POST /api/workflows` format.

```json
{
  "name": "My verified text-to-video workflow",
  "description": "Runs on my private GPU renderer",
  "graph": { "...": "your exported API-format graph goes here" },
  "bindings": {
    "prompt": { "node_id": "6", "input": "text" },
    "negative_prompt": { "node_id": "7", "input": "text" },
    "seed": { "node_id": "3", "input": "seed" },
    "width": { "node_id": "5", "input": "width" },
    "height": { "node_id": "5", "input": "height" },
    "frames": { "node_id": "5", "input": "length" }
  }
}
```

The node numbers above are illustrative, **not a runnable model workflow**. Bind only nodes that actually exist in your exported graph. Required: `prompt`. Optional bindings: `negative_prompt`, `seed`, `width`, `height`, `frames`, `fps`, and `image`. Image-to-video workflows need an `image` binding pointing to the image loader's filename input; Frameva uploads the screenshot, then replaces that filename. For workflows whose VAE requires 4n+1 or 8n+1 frames, use `frame_multiple: 4` or `frame_multiple: 8` when supported by the workflow importer; the exact frame count is rounded down to a valid value, so the rendered duration can be slightly shorter than requested.

Camera and visual-style controls in AI mode append prompt conditioning. They are **not** a guarantee of 3D camera pose control, optical simulation, or identity consistency. Add actual control/pose/reference nodes in your own workflow if the model supports them.

The workflow must save a video to a ComfyUI output node, such as native `SaveVideo`. Frameva accepts saved MP4, WebM or MOV output and normalizes it to browser-compatible MP4. Image-only output is rejected. The per-shot download limit is 512 MiB and the wait limit is one hour.

## Queue and cancellation behavior

Frameva renders one job at a time to avoid local GPU/CPU overload. A ComfyUI job may still wait in the renderer's own queue. Frameva's wait progress is a waiting indicator, not a reported diffusion-step percentage.

Cancelling a Frameva ComfyUI job stops waiting for its result. It deliberately does not call ComfyUI's global `/interrupt` endpoint because that could stop another user's active job. A submitted render can continue using GPU resources until cancelled inside ComfyUI. A Frameva timeout has the same property; check ComfyUI before retrying to avoid duplicating expensive work.

## Verification boundary

Automated tests cover the real CPU renderer, MP4 metadata, screenshot composition, audio export, and the ComfyUI HTTP contract using a simulated ComfyUI server. A simulated server validates integration behavior, **not** real model quality or GPU compatibility. Run one short generation on your own hardware before relying on a model workflow.

## Primary references

- [ComfyUI server routes](https://docs.comfy.org/development/comfyui-server/comms_routes)
- [ComfyUI workflow format](https://docs.comfy.org/development/core-concepts/workflow)
- [Wan 2.2 official repository](https://github.com/Wan-Video/Wan2.2)
- [Wan 2.2 ComfyUI tutorial](https://docs.comfy.org/tutorials/video/wan/wan2_2)
- [LTX-2 official repository](https://github.com/Lightricks/LTX-2)
