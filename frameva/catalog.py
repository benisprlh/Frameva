"""Capabilities are descriptive; model installation/licensing remains separate."""
CAMERA_PRESETS = [
    {"id":"static","name":"Locked off","prompt":"locked-off camera, stable composition"},
    {"id":"dolly_in","name":"Slow push in","prompt":"slow smooth camera push toward the subject"},
    {"id":"dolly_out","name":"Pull back","prompt":"slow smooth camera pull back revealing the scene"},
    {"id":"pan_left","name":"Pan left","prompt":"smooth camera pan left"},
    {"id":"pan_right","name":"Pan right","prompt":"smooth camera pan right"},
    {"id":"orbit","name":"Gentle drift","prompt":"subtle smooth lateral camera movement around the subject"},
]
STYLE_PRESETS = [
    {"id":"cinematic","name":"Cinematic","prompt":"cinematic lighting, subtle contrast, carefully composed framing"},
    {"id":"natural","name":"Natural","prompt":"natural lighting and realistic colors"},
    {"id":"noir","name":"Noir","prompt":"monochrome film noir lighting, deep shadows and high contrast"},
    {"id":"dream","name":"Dream","prompt":"soft diffused lighting, dreamlike purple and blue atmosphere"},
]
MODELS = [
    {"id":"product-motion","name":"Product motion","license":"Frameva MIT","hardware":"CPU · macOS / Windows / Linux","description":"Real screenshot motion and typography. Deterministic MP4 rendering, not generative AI."},
    {"id":"wan-2.2-ti2v-5b","name":"Wan 2.2 TI2V 5B","license":"Apache-2.0 model weights; verify selected distribution","hardware":"NVIDIA renderer recommended; upstream 24 GB VRAM, ComfyUI offload configurations may use less","description":"Text/image-to-video via your installed ComfyUI workflow. Mac model compatibility is not guaranteed.","source":"https://github.com/Wan-Video/Wan2.2"},
    {"id":"ltx-2.5","name":"LTX 2.5","license":"Custom LTX model license; application code and weights have different terms","hardware":"Workflow-dependent. Apple Silicon requires a compatible renderer, not CUDA.","description":"Optional user-provided ComfyUI workflow. Native audio depends on the installed model and workflow.","source":"https://github.com/Lightricks/LTX-2"},
    {"id":"custom-comfyui","name":"Custom ComfyUI workflow","license":"Check every model and custom node separately","hardware":"Determined by your workflow and renderer","description":"Import API-format JSON with explicit bindings. Only import workflows you trust.","source":"https://docs.comfy.org/development/core-concepts/workflow"},
]
# Independently assembled API configurations from the official native node graph.
# These configurations are schema-reviewed; no real GPU generation is claimed.
import json
from pathlib import Path
BUILTIN_WORKFLOWS = [
    json.loads(path.read_text(encoding="utf-8"))
    for path in sorted((Path(__file__).parent / "workflows").glob("*.json"))
]
