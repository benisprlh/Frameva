"""Trusted ComfyUI API workflow adapter, independent of any model vendor."""
from __future__ import annotations

from copy import deepcopy
import json
import math
import os
from pathlib import Path, PurePosixPath
import re
import tempfile
import time
from urllib.parse import urlsplit
import uuid

import httpx

from .render import RenderCancelled, _run_ffmpeg, validate_media

MAX_JSON = 12 * 1024 * 1024
MAX_VIDEO = 512 * 1024 * 1024
POLL_INTERVAL = 1.0
RENDER_TIMEOUT = 3600
BINDING_NAMES = {"prompt", "negative_prompt", "seed", "width", "height", "frames", "fps", "image"}


def validate_base_url(url: str) -> str:
    parsed = urlsplit(str(url))
    if parsed.scheme not in {"http", "https"} or not parsed.hostname or parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise ValueError("Renderer URL must be an HTTP(S) base URL without credentials, query or fragment.")
    try:
        parsed.port
    except ValueError as exc:
        raise ValueError("Renderer URL has an invalid port.") from exc
    if len(url)>2048 or any(char in url for char in "\r\n\t\\"):
        raise ValueError("Invalid renderer URL.")
    return url.rstrip("/")


def _client(base_url: str) -> httpx.Client:
    headers={}
    if os.environ.get("FRAMEVA_COMFY_TOKEN"):
        headers["Authorization"]="Bearer "+os.environ["FRAMEVA_COMFY_TOKEN"]
    return httpx.Client(base_url=validate_base_url(base_url)+"/", timeout=httpx.Timeout(30,connect=5), follow_redirects=False, trust_env=False, headers=headers)


def _json(client: httpx.Client, method: str, path: str, **kwargs) -> dict:
    # Stream also bounds error payloads from an unresponsive/misconfigured renderer.
    with client.stream(method,path,**kwargs) as response:
        if response.status_code >=300:
            # Do not return untrusted backend bodies that may contain local paths or secrets.
            raise ValueError(f"ComfyUI returned HTTP {response.status_code} for {path.split('/')[0]}.")
        data=bytearray()
        for chunk in response.iter_bytes():
            data.extend(chunk)
            if len(data)>MAX_JSON:
                raise ValueError("The renderer response exceeded the metadata limit.")
        try:
            result=json.loads(data)
        except (ValueError,UnicodeError) as exc:
            raise ValueError("The renderer did not return valid JSON.") from exc
        if not isinstance(result,dict):
            raise ValueError("The renderer returned an unexpected response.")
        return result


def validate_workflow(graph: dict, bindings: dict) -> None:
    if not isinstance(graph,dict) or not graph or len(graph)>500:
        raise ValueError("Workflow must be a nonempty API-format node object (at most 500 nodes).")
    if "nodes" in graph or "links" in graph:
        raise ValueError("This is an editor workflow. Export 'API Format' from ComfyUI first.")
    if not isinstance(bindings,dict) or set(bindings)-BINDING_NAMES:
        raise ValueError("Workflow has unsupported binding names.")
    if "prompt" not in bindings:
        raise ValueError("A prompt binding is required.")
    try:
        raw=json.dumps(graph,allow_nan=False)
    except (TypeError,ValueError,RecursionError) as exc:
        raise ValueError("Workflow must contain valid finite JSON.") from exc
    if len(raw)>2*1024*1024:
        raise ValueError("Workflow is larger than 2 MiB.")
    for node_id,node in graph.items():
        if not isinstance(node_id,str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,80}",node_id):
            raise ValueError("Workflow node IDs must be short alphanumeric identifiers.")
        if not isinstance(node,dict) or not isinstance(node.get("class_type"),str) or not re.fullmatch(r"[A-Za-z0-9_ .:/()\-]{1,150}",node["class_type"]):
            raise ValueError("Every workflow node needs a class_type.")
        if not isinstance(node.get("inputs"),dict) or len(node["inputs"])>200:
            raise ValueError("Every workflow node needs an inputs object.")
    for name,binding in bindings.items():
        if not isinstance(binding,dict) or set(binding)!={"node_id","input"}:
            raise ValueError(f"Binding {name} requires exactly node_id and input.")
        node_id=str(binding.get("node_id",""))
        input_name=binding.get("input")
        if node_id not in graph or not isinstance(input_name,str) or input_name not in graph[node_id]["inputs"]:
            raise ValueError(f"Binding {name} does not point to an existing input.")
        current=graph[node_id]["inputs"][input_name]
        if isinstance(current,(dict,list)):
            raise ValueError(f"Binding {name} must target a scalar widget, not a node connection.")


def renderer_status(base_url: str) -> dict:
    try:
        with _client(base_url) as client:
            info=_json(client,"GET","system_stats")
        devices=info.get("devices",[])
        names=[str(device.get("name","Unknown device"))[:160] for device in devices if isinstance(device,dict)]
        return {"connected":True,"device":", ".join(names) or "ComfyUI connected","devices":[{"name":str(d.get("name",""))[:160],"type":str(d.get("type",""))[:40],"vram_total":d.get("vram_total")} for d in devices if isinstance(d,dict)],"missing_nodes":[]}
    except (httpx.HTTPError,ValueError) as exc:
        return {"connected":False,"error":"Cannot connect to ComfyUI. Verify its URL and that its API server is running.","missing_nodes":[]}


def _condition_prompt(shot: dict) -> str:
    from .catalog import CAMERA_PRESETS,STYLE_PRESETS
    camera=next((p["prompt"] for p in CAMERA_PRESETS if p["id"]==shot.get("camera")),"")
    style=next((p["prompt"] for p in STYLE_PRESETS if p["id"]==shot.get("style")),"")
    return ". ".join(part.strip().strip(".") for part in [str(shot.get("prompt","")),camera,style] if part.strip())


def _bind(graph: dict,bindings: dict,key: str,value) -> None:
    if key in bindings:
        b=bindings[key]
        graph[str(b["node_id"])]["inputs"][b["input"]]=value


def _safe_output(item: dict) -> tuple[str,str,str] | None:
    name=item.get("filename","")
    folder=item.get("subfolder","")
    kind=item.get("type","output")
    if not isinstance(name,str) or not isinstance(folder,str) or len(name)>255 or len(folder)>1024:
        return None
    if not name or name!=PurePosixPath(name).name or "\\" in name or "/" in name or "\x00" in name:
        return None
    if Path(name).suffix.lower() not in {".mp4",".webm",".mov"}:
        return None
    if folder.startswith(("/","\\")) or ".." in PurePosixPath(folder).parts or "\\" in folder or "\x00" in folder or ":" in folder:
        return None
    if kind not in {"output","temp"}:
        return None
    return name,folder,kind


def render_comfy(shot: dict,workflow: dict,reference_path: Path | None,output_path: Path,base_url: str,progress,cancelled) -> None:
    graph=deepcopy(workflow.get("graph"))
    bindings=deepcopy(workflow.get("bindings"))
    validate_workflow(graph,bindings)
    if cancelled():
        raise RenderCancelled()
    if reference_path and "image" not in bindings:
        raise ValueError("This workflow has no image binding. Choose an image-to-video workflow or remove the reference.")
    if not reference_path and "image" in bindings:
        raise ValueError("This image-to-video workflow needs a reference image.")
    output_path=Path(output_path)
    output_path.parent.mkdir(parents=True,exist_ok=True)
    frames=round(float(shot.get("duration",3))*int(shot.get("fps",24)))
    # Video VAEs commonly require 4n+1 or 8n+1. Opt-in workflow metadata defines this.
    multiple=int(workflow.get("frame_multiple",1))
    if multiple not in {1,4,8}:
        raise ValueError("Unsupported workflow frame_multiple; use 1, 4 or 8.")
    if multiple>1:
        frames=max(1,((frames-1)//multiple)*multiple+1)
    values={"prompt":_condition_prompt(shot),"negative_prompt":str(shot.get("negative_prompt","")),"seed":int(shot.get("seed",42)),"width":int(shot.get("width",1280)),"height":int(shot.get("height",704)),"fps":int(shot.get("fps",24)),"frames":frames}
    for key,value in values.items():
        _bind(graph,bindings,key,value)
    progress(3)
    try:
        with _client(base_url) as client:
            # Fetch precise node descriptions, avoiding gigantic full custom-node catalogs.
            for class_type in sorted({node["class_type"] for node in graph.values()}):
                if cancelled():
                    raise RenderCancelled()
                from urllib.parse import quote
                available=_json(client,"GET","object_info/"+quote(class_type,safe=""))
                if class_type not in available:
                    raise ValueError(f"ComfyUI is missing node '{class_type}'. Install the trusted workflow requirements first.")
            if cancelled():
                raise RenderCancelled()
            if reference_path:
                from PIL import Image,ImageOps
                # Reencode to a random PNG so no uploaded filename/path is trusted.
                with tempfile.TemporaryFile() as upload:
                    with Image.open(reference_path) as image:
                        ImageOps.exif_transpose(image).convert("RGB").save(upload,format="PNG")
                    upload.seek(0)
                    result=_json(client,"POST","upload/image",files={"image":("frameva-"+uuid.uuid4().hex+".png",upload,"image/png")},data={"type":"input","overwrite":"false"})
                name=result.get("name")
                folder=result.get("subfolder","")
                if not isinstance(name,str) or not name or "/" in name or "\\" in name or not isinstance(folder,str) or ".." in PurePosixPath(folder).parts or folder.startswith("/") or "\\" in folder:
                    raise ValueError("ComfyUI returned an unsafe uploaded image name.")
                _bind(graph,bindings,"image",f"{folder}/{name}" if folder else name)
            if cancelled():
                raise RenderCancelled()
            result=_json(client,"POST","prompt",json={"prompt":graph,"client_id":"frameva-"+uuid.uuid4().hex})
            if result.get("error") or result.get("node_errors"):
                raise ValueError("ComfyUI rejected the workflow. Check model filenames, node inputs and installed nodes in ComfyUI.")
            prompt_id=result.get("prompt_id")
            if not isinstance(prompt_id,str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,120}",prompt_id):
                raise ValueError("ComfyUI did not return a valid prompt ID.")
            started=time.monotonic()
            progress(10)
            entry=None
            while time.monotonic()-started <RENDER_TIMEOUT:
                if cancelled():
                    # Cancel only this client's wait: /interrupt is global and unsafe on shared GPUs.
                    raise RenderCancelled()
                history=_json(client,"GET","history/"+prompt_id)
                entry=history.get(prompt_id)
                if isinstance(entry,dict):
                    status=entry.get("status",{})
                    if status.get("status_str")=="error" or any(isinstance(m,list) and m and m[0] in {"execution_error","execution_interrupted"} for m in status.get("messages",[])):
                        raise ValueError("The ComfyUI render failed. Open ComfyUI to review its execution error; check model memory and workflow inputs.")
                    if entry.get("outputs"):
                        break
                    if status.get("completed"):
                        raise ValueError("ComfyUI completed without a saved video. Add a SaveVideo or Video Combine output node.")
                # This is elapsed-time wait progress, not claimed model sampler progress.
                progress(min(75,10+int((time.monotonic()-started)/15)))
                time.sleep(POLL_INTERVAL)
            else:
                raise ValueError("ComfyUI did not complete within one hour. Its queued render may continue on the renderer.")
            candidates=[]
            for output in entry.get("outputs",{}).values():
                if not isinstance(output,dict):
                    continue
                for key in ("videos","gifs","images"):
                    for item in output.get(key,[]):
                        if isinstance(item,dict):
                            safe=_safe_output(item)
                            if safe:
                                candidates.append(safe)
            if not candidates:
                raise ValueError("The workflow produced no MP4/WebM/MOV video. Add a video-saving output node.")
            # Prefer native MP4 if a workflow outputs several previews.
            candidates.sort(key=lambda x:Path(x[0]).suffix.lower()!=".mp4")
            filename,subfolder,kind=candidates[0]
            progress(80)
            with tempfile.TemporaryDirectory(prefix="frameva-comfy-") as tmp:
                downloaded=Path(tmp)/("output"+Path(filename).suffix.lower())
                with client.stream("GET","view",params={"filename":filename,"subfolder":subfolder,"type":kind}) as response:
                    if response.status_code!=200:
                        raise ValueError("The generated video could not be downloaded from ComfyUI.")
                    size=0
                    with downloaded.open("wb") as out:
                        for chunk in response.iter_bytes(65536):
                            if cancelled():
                                raise RenderCancelled()
                            size+=len(chunk)
                            if size>MAX_VIDEO:
                                raise ValueError("The generated video exceeds the 512 MiB per-shot limit.")
                            out.write(chunk)
                info=validate_media(downloaded,"video/mp4")
                if info["kind"]!="video":
                    raise ValueError("ComfyUI returned a non-video output.")
                progress(90)
                # Normalize codecs for browser playback, even for AVI-like custom outputs.
                _run_ffmpeg(["-y","-protocol_whitelist","file,pipe","-i",str(downloaded),"-map","0:v:0","-map","0:a?","-c:v","libx264","-preset","veryfast","-crf","19","-pix_fmt","yuv420p","-c:a","aac","-movflags","+faststart",str(output_path)],cancelled)
                progress(100)
    except httpx.HTTPError as exc:
        output_path.unlink(missing_ok=True)
        raise ValueError("Connection to ComfyUI failed or timed out. Check the renderer connection before retrying.") from exc
    except BaseException:
        output_path.unlink(missing_ok=True)
        raise
