"""Portable, deterministic product-motion rendering. No AI model is implied.

Media operations use argv lists, bounded subprocesses and local-only protocols.
"""
from __future__ import annotations

import json
import math
import os
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
import threading
from queue import SimpleQueue, Empty
import time
from typing import Callable

from PIL import Image, ImageColor, ImageDraw, ImageFilter, ImageFont, ImageOps

Progress = Callable[[int], None]
Cancelled = Callable[[], bool]
Image.MAX_IMAGE_PIXELS = 40_000_000


class RenderCancelled(Exception):
    """A local render was cancelled. Shared renderer jobs are never interrupted."""


def ffmpeg_path() -> str | None:
    explicit = os.environ.get("FRAMEVA_FFMPEG")
    if explicit:
        return str(Path(explicit).resolve()) if Path(explicit).is_file() else None
    found = shutil.which("ffmpeg")
    if found:
        return found
    try:
        import imageio_ffmpeg
        return imageio_ffmpeg.get_ffmpeg_exe()
    except (ImportError, RuntimeError):
        return None


def _ffmpeg() -> str:
    exe = ffmpeg_path()
    if not exe:
        raise ValueError("FFmpeg is unavailable. Install Frameva dependencies or set FRAMEVA_FFMPEG to the executable.")
    return exe


def _packet_video_duration(path: Path, stream_index: int = 0) -> float:
    """Measure video timestamps without decoding when bundled FFmpeg lacks ffprobe.

    Container duration may be extended by an audio track. Copying video packets
    into the framecrc muxer exposes their PTS and duration, including VFR media.
    """
    result=subprocess.run([_ffmpeg(),"-hide_banner","-loglevel","error","-nostdin","-protocol_whitelist","file,pipe","-i",str(path),"-map",f"0:{stream_index}","-c:v","copy","-an","-f","framecrc","pipe:1"],capture_output=True,timeout=25)
    if result.returncode or len(result.stdout)>24*1024*1024:
        raise ValueError("Cannot inspect the recording's video timeline. Install FFmpeg with ffprobe for this media.")
    time_base=None
    first=None
    end=None
    for line in result.stdout.decode("ascii","replace").splitlines():
        match=re.match(r"#tb\s+0:\s*(\d+)/(\d+)",line)
        if match:
            time_base=int(match[1])/int(match[2])
        if line.startswith("#") or not line.strip():
            continue
        fields=[field.strip() for field in line.split(",")]
        if len(fields)<4:
            continue
        try:
            pts=int(fields[2]);length=int(fields[3])
        except ValueError:
            continue
        first=pts if first is None else min(first,pts)
        end=pts+length if end is None else max(end,pts+length)
    if time_base is None or first is None or end is None or end<=first:
        raise ValueError("The recording has no measurable video timeline.")
    return (end-first)*time_base


def probe(path: Path) -> dict:
    """Read stream metadata using ffprobe, or bundled ffmpeg when unavailable."""
    path = Path(path).resolve()
    ffprobe = shutil.which("ffprobe")
    if ffprobe:
        p = subprocess.run([ffprobe, "-v", "error", "-protocol_whitelist", "file,pipe", "-show_streams", "-show_format", "-of", "json", str(path)], capture_output=True, timeout=25)
        if p.returncode:
            raise ValueError("The file could not be decoded as supported media.")
        try:
            result = json.loads(p.stdout)
        except (ValueError, UnicodeError) as exc:
            raise ValueError("Invalid media metadata.") from exc
        result["duration"] = float(result.get("format", {}).get("duration", 0) or 0)
        return result
    p = subprocess.run([_ffmpeg(), "-hide_banner", "-protocol_whitelist", "file,pipe", "-i", str(path)], capture_output=True, timeout=25)
    info = p.stderr.decode("utf-8", "replace")
    duration = re.search(r"Duration:\s*(\d+):(\d+):(\d+(?:\.\d+)?)", info)
    seconds = sum(float(x) * factor for x, factor in zip(duration.groups(), (3600, 60, 1))) if duration else 0
    streams = []
    for line in info.splitlines():
        if "Stream #" not in line:
            continue
        if "Video:" in line:
            dims = re.search(r"\b(\d{2,5})x(\d{2,5})\b", line)
            index_match=re.search(r"Stream #0:(\d+)",line)
            streams.append({"index":int(index_match[1]) if index_match else 0,"codec_type": "video", "width": int(dims[1]) if dims else 0, "height": int(dims[2]) if dims else 0, "disposition": {"attached_pic": int("attached pic" in line.lower())}})
        elif "Audio:" in line:
            streams.append({"codec_type": "audio"})
    if not streams:
        raise ValueError("The file could not be decoded as supported media.")
    video=next((item for item in streams if item.get("codec_type")=="video" and not item.get("disposition",{}).get("attached_pic")),None)
    if video:
        video["duration"]=_packet_video_duration(path,video.get("index",0))
    return {"streams": streams, "format": {"duration": str(seconds)}, "duration": seconds}


def validate_media(path: Path, content_type: str) -> dict:
    """Validate content, not extension; never pass playlists/URLs to FFmpeg."""
    path = Path(path)
    if not path.is_file() or path.stat().st_size == 0:
        raise ValueError("The uploaded file is empty.")
    with path.open("rb") as handle:
        magic = handle.read(32)
    image_magic = magic.startswith((b"\x89PNG\r\n\x1a\n", b"\xff\xd8\xff")) or (magic[:4] == b"RIFF" and magic[8:12] == b"WEBP")
    if image_magic:
        try:
            with Image.open(path) as image:
                if image.width * image.height > Image.MAX_IMAGE_PIXELS or max(image.size) > 16384:
                    raise ValueError("Images must be at most 40 megapixels and 16,384 pixels on either side.")
                image.verify()
            with Image.open(path) as image:
                image.load()
                return {"kind": "image", "mime_type": Image.MIME.get(image.format, "image/png"), "width": image.width, "height": image.height}
        except (OSError, SyntaxError, Image.DecompressionBombError) as exc:
            raise ValueError("The image is corrupt or too large.") from exc
    container = None
    if magic[4:8] == b"ftyp":
        container = "mp4"
    elif magic.startswith(b"\x1aE\xdf\xa3"):
        container = "webm"
    elif magic[:4] == b"RIFF" and magic[8:12] == b"WAVE":
        container = "wav"
    elif magic.startswith(b"fLaC"):
        container = "flac"
    elif magic.startswith(b"OggS"):
        container = "ogg"
    elif magic.startswith(b"ID3") or (len(magic) > 1 and magic[0] == 255 and (magic[1] & 0xE0) == 0xE0):
        container = "mp3"
    if container is None:
        raise ValueError("Use PNG, JPEG, WebP, MP4, WebM, WAV, MP3, FLAC or Ogg media. Playlists and SVG are not accepted.")
    info = probe(path)
    video = next((s for s in info["streams"] if s.get("codec_type") == "video" and not s.get("disposition", {}).get("attached_pic")), None)
    audio = next((s for s in info["streams"] if s.get("codec_type") == "audio"), None)
    if not video and not audio:
        raise ValueError("The media has no decodable audio or video stream.")
    if info["duration"] <= 0 or info["duration"] > 3600:
        raise ValueError("Media duration must be greater than zero and at most one hour.")
    if video and (max(video.get("width", 0), video.get("height", 0)) > 8192 or video.get("width", 0) * video.get("height", 0) > 34_000_000):
        raise ValueError("Video resolution is too large.")
    kind = "video" if video else "audio"
    mime = {"mp4": "video/mp4" if video else "audio/mp4", "webm": "video/webm" if video else "audio/webm", "wav": "audio/wav", "flac": "audio/flac", "ogg": "video/ogg" if video else "audio/ogg", "mp3": "audio/mpeg"}[container]
    return {"kind": kind, "mime_type": mime, "duration": info["duration"], "video_duration": _video_duration(info) if video else None, "width": video.get("width") if video else None, "height": video.get("height") if video else None}


def _font(size: int, bold: bool = False) -> ImageFont.ImageFont:
    candidates = [
        Path(__file__).parent / "fonts" / ("DejaVuSans-Bold.ttf" if bold else "DejaVuSans.ttf"),
        Path("/usr/share/fonts/truetype/dejavu") / ("DejaVuSans-Bold.ttf" if bold else "DejaVuSans.ttf"),
        Path("/System/Library/Fonts/Supplemental") / ("Arial Bold.ttf" if bold else "Arial.ttf"),
        Path(os.environ.get("WINDIR", "C:/Windows")) / "Fonts" / ("arialbd.ttf" if bold else "arial.ttf"),
    ]
    for candidate in candidates:
        if candidate.is_file():
            try:
                return ImageFont.truetype(str(candidate), max(10, size))
            except OSError:
                continue
    return ImageFont.load_default(size=max(10, size))


def _wrap(draw: ImageDraw.ImageDraw, text: str, font, max_width: int, max_lines: int) -> list[str]:
    words = str(text).replace("\n", " ").split()
    lines: list[str] = []
    current = ""
    for word in words:
        # Split exceptionally long tokens (URLs, identifiers) to avoid clipping.
        while draw.textlength(word, font=font) > max_width and len(word) > 1:
            n = max(1, int(len(word) * max_width / draw.textlength(word, font=font)) - 1)
            if current:
                lines.append(current)
                current = ""
            lines.append(word[:n])
            word = word[n:]
        trial = (current + " " + word).strip()
        if current and draw.textlength(trial, font=font) > max_width:
            lines.append(current)
            current = word
        else:
            current = trial
    if current:
        lines.append(current)
    if len(lines) > max_lines:
        lines = lines[:max_lines]
        tail = lines[-1]
        while tail and draw.textlength(tail + "…", font=font) > max_width:
            tail = tail[:-1]
        lines[-1] = tail + "…"
    return lines


def _background(width: int, height: int, color: tuple[int, int, int], style: str) -> Image.Image:
    background = Image.new("RGB", (width, height), (10, 13, 18))
    draw = ImageDraw.Draw(background)
    for y in range(height):
        shade = y / max(1, height - 1)
        draw.line((0, y, width, y), fill=(int(10 + 5 * shade), int(13 + 6 * shade), int(18 + 9 * shade)))
    if style == "natural":
        background = Image.new("RGB", (width, height), (18, 24, 28))
    elif style == "noir":
        color = (175, 175, 175)
    elif style == "dream":
        color = (175, 125, 255)
    # Low-resolution glow compositing keeps 4K-independent setup light.
    glow = Image.new("RGB", (max(1, width // 8), max(1, height // 8)), (0, 0, 0))
    gd = ImageDraw.Draw(glow)
    gw, gh = glow.size
    gd.ellipse((gw * .40, -gh * .6, gw * 1.3, gh * .7), fill=tuple(int(v * .20) for v in color))
    gd.ellipse((-gw * .5, gh * .5, gw * .4, gh * 1.5), fill=(6, 12, 20))
    glow = glow.filter(ImageFilter.GaussianBlur(max(2, gw // 8))).resize((width, height), Image.Resampling.BILINEAR)
    from PIL import ImageChops
    background = ImageChops.add(background, glow)
    draw = ImageDraw.Draw(background)
    step = max(32, width // 18)
    for x in range(0, width, step):
        draw.line((x, 0, x, height), fill=(21, 26, 32), width=1)
    for y in range(0, height, step):
        draw.line((0, y, width, y), fill=(21, 26, 32), width=1)
    return background


def _browser_card(image: Image.Image, width: int, height: int, scale: float) -> Image.Image:
    radius = max(8, round(15 * scale))
    chrome = max(20, round(35 * scale))
    card = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    d = ImageDraw.Draw(card)
    d.rounded_rectangle((0, 0, width - 1, height - 1), radius=radius, fill=(29, 35, 44), outline=(76, 86, 99), width=max(1, round(scale)))
    for i, c in enumerate(((246, 106, 102), (244, 194, 80), (97, 199, 117))):
        x = int((17 + i * 16) * scale)
        r = max(2, int(4 * scale))
        d.ellipse((x-r, chrome//2-r, x+r, chrome//2+r), fill=c)
    bar_x = max(int(83 * scale), width // 5)
    d.rounded_rectangle((bar_x, int(chrome*.22), width-int(16*scale), int(chrome*.76)), radius=max(3, int(5*scale)), fill=(19, 24, 31))
    # Contain rather than crop: every screenshot stays truthful and inspectable.
    viewport = Image.new("RGB", (max(1,width - 2), max(1,height - chrome - 2)), (15, 18, 23))
    fit = ImageOps.contain(image.convert("RGB"), viewport.size, Image.Resampling.LANCZOS)
    viewport.paste(fit, ((viewport.width-fit.width)//2, (viewport.height-fit.height)//2))
    card.paste(viewport, (1, chrome))
    return card


def _text_layer(shot: dict, width: int, height: int, has_reference: bool, color: tuple[int,int,int]) -> tuple[Image.Image, tuple[int,int,int,int]]:
    layer = Image.new("RGBA", (width, height), (0,0,0,0))
    d = ImageDraw.Draw(layer)
    scale = width / 1280
    portrait = height > width * 1.15
    margin = max(18, int(width * .055))
    layout = shot.get("layout", "showcase")
    headline = str(shot.get("headline") or shot.get("name") or "Your next big idea.")[:120]
    caption = str(shot.get("caption") or "")[:300]
    title_size = int(width * (.065 if portrait else .047 if has_reference else .068))
    font = _font(title_size, True)
    caption_font = _font(int(width * (.029 if portrait else .018)))
    label_font = _font(int(width * (.018 if portrait else .011)), True)
    top = int(height * (.075 if portrait else .065))
    label = "PRODUCT STORY" if has_reference else "INTRODUCING"
    d.rounded_rectangle((margin, top, margin + max(18,int(width*.022)), top+max(3,int(width*.004))), radius=3, fill=color)
    d.text((margin + int(width*.035), top-int(width*.005)), label, fill=color, font=label_font)
    y = top + int(height * (.045 if portrait else .055))
    text_width = width - margin*2
    if not has_reference and layout == "detail" and not portrait:
        text_width = int(width * .65)
    lines = _wrap(d, headline, font, text_width, 3 if portrait or not has_reference else 2)
    for line in lines:
        d.text((margin, y), line, fill=(246,248,251), font=font, stroke_width=0)
        y += int(title_size * 1.17)
    y += int(height * .014)
    cap_lines = _wrap(d, caption, caption_font, text_width, 3 if portrait else 2)
    for line in cap_lines:
        d.text((margin, y), line, fill=(169,181,197), font=caption_font)
        y += int(caption_font.size*1.4)
    if has_reference:
        card_top = max(y + int(height*.035), int(height*(.39 if portrait else .31)))
        card_bottom = height - int(height*.065)
        card_left = margin if portrait else int(width*.09)
        region = (card_left, card_top, width-card_left, max(card_top+24,card_bottom))
    else:
        region = (margin, int(height*.65), width-margin, int(height*.88))
        base_y = min(height-int(height*.09), y+int(height*.12))
        line_width = min(width-margin*2, int(width*.7))
        d.line((margin, base_y, margin+line_width, base_y), fill=(64,75,86), width=max(1,int(scale)))
        d.rounded_rectangle((margin, base_y-int(4*scale), margin+int(line_width*.23), base_y+int(4*scale)), radius=max(2,int(4*scale)), fill=color)
        d.text((margin, base_y+int(24*scale)), "BUILT WITH INTENTION.", fill=(114,130,145), font=label_font)
    return layer, region


def _stop(process: subprocess.Popen) -> None:
    if process.poll() is None:
        process.terminate()
        try:
            process.wait(timeout=3)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=3)


def _run_ffmpeg(args: list[str], cancelled: Cancelled, timeout: float = 600, progress: Progress | None = None, duration: float | None = None) -> None:
    """Run FFmpeg with cancellable polling and optional real encoded-time progress."""
    if cancelled():
        raise RenderCancelled()
    with tempfile.TemporaryFile() as log:
        command = [_ffmpeg(), "-hide_banner", "-loglevel", "error", "-nostdin"]
        if progress:
            command += ["-progress", "pipe:1", "-nostats"]
        updates: SimpleQueue = SimpleQueue()
        process = subprocess.Popen([*command, *args], stdout=subprocess.PIPE if progress else subprocess.DEVNULL, stderr=log)
        def read_progress():
            try:
                for raw in process.stdout:
                    line=raw.decode("ascii", "replace").strip()
                    key, _, value=line.partition("=")
                    if key in {"out_time_us", "out_time_ms"}:
                        try:
                            updates.put(float(value)/1_000_000)
                        except ValueError:
                            pass
            except (OSError, ValueError):
                pass
        reader=threading.Thread(target=read_progress,daemon=True) if progress else None
        if reader:
            reader.start()
        started = time.monotonic()
        try:
            while process.poll() is None:
                if cancelled():
                    raise RenderCancelled()
                if time.monotonic() - started > timeout:
                    raise ValueError("The media operation exceeded its time limit.")
                if progress and duration:
                    latest=None
                    while True:
                        try:
                            latest=updates.get_nowait()
                        except Empty:
                            break
                    if latest is not None:
                        progress(max(0,min(99,int(latest/duration*100))))
                time.sleep(.05)
            if cancelled():
                raise RenderCancelled()
            if process.returncode:
                log.seek(0)
                detail = log.read(5000).decode("utf-8", "replace")
                raise ValueError("FFmpeg could not process this media: " + detail[-1200:])
            if progress:
                progress(100)
        finally:
            _stop(process)
            if reader:
                reader.join(timeout=2)
            if process.stdout:
                process.stdout.close()


def render_preview(shot: dict, reference_path: Path | None, output_path: Path, progress: Progress, cancelled: Cancelled) -> None:
    """Render product typography and screenshot motion into a real H.264 MP4."""
    width, height = int(shot.get("width",1280)), int(shot.get("height",720))
    fps, duration = int(shot.get("fps",24)), float(shot.get("duration",3))
    if min(width,height) < 64 or max(width,height) > 2560 or width%2 or height%2 or not 1 <= duration <=30 or not 8 <= fps <=30:
        raise ValueError("Product motion requires even dimensions 64–2560, 1–30 seconds and 8–30 FPS.")
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True,exist_ok=True)
    try:
        color = ImageColor.getrgb(shot.get("brand_color", "#b8ff65"))
    except (ValueError, TypeError):
        color = (184,255,101)
    if len(color) != 3:
        color = color[:3]
    reference = None
    if reference_path:
        try:
            with Image.open(reference_path) as src:
                reference = ImageOps.exif_transpose(src).convert("RGB")
        except (OSError, ValueError) as exc:
            raise ValueError("Product motion needs an image screenshot as its reference.") from exc
    background = _background(width,height,color,shot.get("style","cinematic"))
    text, region = _text_layer(shot,width,height,reference is not None,color)
    x1,y1,x2,y2 = region
    card = None
    if reference:
        # Match the browser window to the screenshot's aspect, avoiding invented
        # letterboxed UI areas inside the product itself.
        max_w, max_h = x2-x1, y2-y1
        chrome = max(20, round(35 * width/1280))
        image_ratio = reference.width / max(1, reference.height)
        card_w = min(max_w, max(32, int((max_h-chrome)*image_ratio)))
        card_h = min(max_h, max(32, int(card_w/image_ratio)+chrome))
        x1 += (max_w-card_w)//2
        y1 += max(0,(max_h-card_h)//3)
        card = _browser_card(reference,card_w,card_h,width/1280)
    nframes = max(1,round(fps*duration))
    with tempfile.TemporaryFile() as log:
        process = subprocess.Popen([_ffmpeg(),"-hide_banner","-loglevel","error","-y","-f","rawvideo","-pix_fmt","rgb24","-s",f"{width}x{height}","-r",str(fps),"-i","pipe:0","-an","-c:v","libx264","-preset","veryfast","-crf","20","-pix_fmt","yuv420p","-movflags","+faststart",str(output_path)],stdin=subprocess.PIPE,stdout=subprocess.DEVNULL,stderr=log)
        try:
            started = time.monotonic()
            for i in range(nframes):
                if cancelled():
                    raise RenderCancelled()
                if time.monotonic()-started >600:
                    raise ValueError("Product motion exceeded its render time limit.")
                t = i/max(1,nframes-1)
                intro = min(1.0,i/max(1,fps*.55))
                ease = 1-(1-intro)**3
                frame = background.copy().convert("RGBA")
                alpha_text = text.copy()
                alpha_text.putalpha(alpha_text.getchannel("A").point(lambda a:int(a*ease)))
                frame.alpha_composite(alpha_text,(0,int((1-ease)*12)))
                if card:
                    camera = shot.get("camera","dolly_in")
                    zoom = 1 + .035*t if camera=="dolly_in" else 1.035-.035*t if camera=="dolly_out" else 1.0
                    dx = int((t-.5)*width*.025) if camera=="pan_right" else int((.5-t)*width*.025) if camera=="pan_left" else int(math.sin(t*math.pi)*width*.012) if camera=="orbit" else 0
                    dy = int((1-ease)*height*.04) + (int(math.sin(t*math.pi*2)*height*.006) if camera=="orbit" else 0)
                    displayed = card.resize((max(1,int(card.width*zoom)),max(1,int(card.height*zoom))),Image.Resampling.BICUBIC)
                    displayed.putalpha(displayed.getchannel("A").point(lambda a:int(a*ease)))
                    px,py = x1-(displayed.width-card.width)//2+dx,y1-(displayed.height-card.height)//2+dy
                    shadow = Image.new("RGBA",frame.size,(0,0,0,0))
                    sd=ImageDraw.Draw(shadow)
                    sd.rounded_rectangle((px,py+12,px+displayed.width,py+displayed.height+12),radius=max(8,int(width*.012)),fill=(0,0,0,int(75*ease)))
                    shadow=shadow.filter(ImageFilter.GaussianBlur(max(3,int(width*.009))))
                    frame.alpha_composite(shadow)
                    frame.alpha_composite(displayed,(px,py))
                # A fine moving accent is a visible progress beat, never a UI simulation.
                d=ImageDraw.Draw(frame)
                d.rectangle((0,height-3,int(width*t),height),fill=color)
                process.stdin.write(frame.convert("RGB").tobytes())
                if i%max(1,fps//4)==0:
                    progress(min(97,int((i+1)/nframes*97)))
            process.stdin.close()
            try:
                result=process.wait(timeout=30)
            except subprocess.TimeoutExpired as exc:
                raise ValueError("FFmpeg did not finish writing the video.") from exc
            if result:
                log.seek(0)
                raise ValueError("Video encoding failed: "+log.read(2000).decode("utf-8","replace")[-800:])
            progress(100)
        except BaseException:
            _stop(process)
            output_path.unlink(missing_ok=True)
            raise
        finally:
            if process.stdin and not process.stdin.closed:
                try:
                    process.stdin.close()
                except BrokenPipeError:
                    pass
            _stop(process)


def _video_stream(info: dict) -> dict:
    return next((s for s in info.get("streams", []) if s.get("codec_type")=="video" and not s.get("disposition",{}).get("attached_pic")), {})


def _video_duration(info: dict) -> float:
    stream=_video_stream(info)
    try:
        value=float(stream.get("duration") or info.get("duration") or 0)
    except (TypeError,ValueError):
        value=0
    return value if math.isfinite(value) else 0


def _atempo(rate: float) -> str:
    """Preserve audio pitch with an atempo chain valid on all supported FFmpeg builds."""
    values=[]
    remaining=rate
    while remaining>2:
        values.append(2.0)
        remaining/=2
    while remaining<.5:
        values.append(.5)
        remaining/=.5
    values.append(remaining)
    return ",".join(f"atempo={v:.8f}" for v in values)


def _recording_background(shot: dict, source_width: int, source_height: int, width: int, height: int, color: tuple) -> tuple[Image.Image, tuple[int,int,int,int]]:
    background=_background(width,height,color,shot.get("style","cinematic")).convert("RGBA")
    typography,region=_text_layer(shot,width,height,True,color)
    background.alpha_composite(typography)
    x1,y1,x2,y2=region
    max_w,max_h=max(32,x2-x1),max(32,y2-y1)
    chrome=max(20,round(35*width/1280))
    ratio=source_width/max(1,source_height)
    # An actual recording is contained at its true aspect; zoom is an explicit crop.
    card_w=min(max_w,max(32,int((max_h-chrome)*ratio)))
    card_w=max(32,card_w//2*2)
    viewport_w=card_w-4
    viewport_h=max(16,int(viewport_w/ratio)//2*2)
    card_h=viewport_h+chrome+4
    x=x1+(max_w-card_w)//2
    y=y1+max(0,(max_h-card_h)//3)
    shadow=Image.new("RGBA",background.size,(0,0,0,0))
    sd=ImageDraw.Draw(shadow)
    radius=max(8,int(width*.012))
    sd.rounded_rectangle((x,y+12,x+card_w,y+card_h+12),radius=radius,fill=(0,0,0,105))
    background.alpha_composite(shadow.filter(ImageFilter.GaussianBlur(max(3,int(width*.009)))))
    card=_browser_card(Image.new("RGB",(viewport_w,viewport_h),(13,17,23)),card_w,card_h,width/1280)
    background.alpha_composite(card,(x,y))
    return background.convert("RGB"),(x+2,y+chrome,viewport_w,viewport_h)


def render_recording(shot: dict, video_path: Path, output_path: Path, progress: Progress, cancelled: Cancelled) -> None:
    """Compose *temporal video frames* into a product launch scene.

    No screenshot-loop or freeze-frame fallback is used. Zoom/focus crop real
    recording frames; pitch-correct audio follows trim and playback speed.
    """
    output_path=Path(output_path)
    if cancelled():
        raise RenderCancelled()
    video_path=Path(video_path).resolve()
    if output_path.resolve()==video_path:
        raise ValueError("Recording output must differ from the source recording.")
    if not video_path.is_file():
        raise ValueError("The source recording is unavailable.")
    width,height=int(shot.get("width",1280)),int(shot.get("height",720))
    fps=int(shot.get("fps",24))
    duration=float(shot.get("duration",3))
    trim_start=float(shot.get("trim_start",0))
    rate=float(shot.get("playback_rate",1))
    zoom=float(shot.get("zoom",1))
    focus_x,focus_y=float(shot.get("focus_x",.5)),float(shot.get("focus_y",.5))
    if not all(math.isfinite(v) for v in (duration,trim_start,rate,zoom,focus_x,focus_y)):
        raise ValueError("Recording controls must be finite numbers.")
    if min(width,height)<64 or max(width,height)>2560 or width%2 or height%2 or not 8<=fps<=30:
        raise ValueError("Recording output requires even dimensions 64–2560 and 8–30 FPS.")
    if not 1<=duration<=120 or trim_start<0 or not .25<=rate<=4 or not 1<=zoom<=2.5 or not 0<=focus_x<=1 or not 0<=focus_y<=1:
        raise ValueError("Invalid recording duration, trim, playback rate, zoom or focus.")
    media=validate_media(video_path,"video/mp4")
    if media["kind"]!="video":
        raise ValueError("Recording composition needs an actual video asset.")
    info=probe(video_path)
    stream=_video_stream(info)
    source_duration=_video_duration(info)
    consumed=duration*rate
    if source_duration<=0 or trim_start+consumed>source_duration+.025:
        raise ValueError(f"Insufficient recording footage: need {trim_start+consumed:.2f}s, source has {source_duration:.2f}s. Reduce trim, duration or playback rate; Frameva will not freeze the final frame.")
    source_w,source_h=int(stream.get("width",0)),int(stream.get("height",0))
    rotation=next((s.get("rotation",0) for s in stream.get("side_data_list",[]) if "rotation" in s),0)
    if abs(float(rotation))%180==90:
        source_w,source_h=source_h,source_w
    if source_w<1 or source_h<1:
        raise ValueError("The recording has invalid video dimensions.")
    keep_audio=bool(shot.get("keep_audio",True)) and any(s.get("codec_type")=="audio" for s in info["streams"])
    try:
        color=ImageColor.getrgb(shot.get("brand_color","#b8ff65"))[:3]
    except (ValueError,TypeError):
        color=(184,255,101)
    background,(vx,vy,vw,vh)=_recording_background(shot,source_w,source_h,width,height,color)
    output_path.parent.mkdir(parents=True,exist_ok=True)
    progress(3)
    frames=max(1,round(duration*fps))
    camera=shot.get("camera","static")
    # zoompan d=1 emits exactly one frame per actual input frame after fps conversion.
    # Expressions contain validated numbers and fixed operators, never user text.
    movement=f"{min(1.08,2.5/zoom)-1:.8f}*on/{max(1,frames-1)}"
    z=f"{zoom:.8f}*(1+{movement})" if camera=="dolly_in" else f"{zoom:.8f}*(1+{min(1.08,2.5/zoom)-1:.8f}-{movement})" if camera=="dolly_out" else f"{zoom:.8f}"
    fx=f"{focus_x:.8f}"
    fy=f"{focus_y:.8f}"
    if camera=="pan_left":
        fx=f"max(0,{focus_x:.8f}+.12*(.5-on/{max(1,frames-1)}))"
    elif camera=="pan_right":
        fx=f"min(1,{focus_x:.8f}+.12*(on/{max(1,frames-1)}-.5))"
    elif camera=="orbit":
        fx=f"min(1,max(0,{focus_x:.8f}+.035*sin(on/{max(1,frames-1)}*PI*2)))"
    crop_x=f"min(max(0,iw*({fx})-iw/(2*zoom)),iw-iw/zoom)"
    crop_y=f"min(max(0,ih*({fy})-ih/(2*zoom)),ih-ih/zoom)"
    with tempfile.TemporaryDirectory(prefix="frameva-recording-") as temp:
        backdrop=Path(temp)/"scene.png"
        background.save(backdrop)
        args=["-y","-filter_complex_threads","1","-ss",f"{trim_start:.8f}","-t",f"{consumed:.8f}","-protocol_whitelist","file,pipe","-i",str(video_path),"-loop","1","-framerate",str(fps),"-protocol_whitelist","file,pipe","-i",str(backdrop)]
        filters=[f"[0:v:0]setpts=(PTS-STARTPTS)/{rate:.8f},fps={fps},zoompan=z='{z}':x='{crop_x}':y='{crop_y}':d=1:s={vw}x{vh}:fps={fps},setsar=1[screen]",f"[1:v:0]format=rgba[backdrop]",f"[backdrop][screen]overlay=x={vx}:y={vy}:shortest=1:eof_action=endall,format=yuv420p[vout]"]
        if keep_audio:
            filters.append(f"[0:a:0]asetpts=PTS-STARTPTS,{_atempo(rate)},aresample=48000:async=1:first_pts=0,atrim=duration={duration:.8f}[aout]")
        args += ["-filter_complex",";".join(filters),"-map","[vout]"]
        if keep_audio:
            args += ["-map","[aout]","-c:a","aac","-ar","48000","-ac","2"]
        else:
            args += ["-an"]
        args += ["-t",f"{duration:.8f}","-c:v","libx264","-preset","veryfast","-crf","18","-pix_fmt","yuv420p","-movflags","+faststart",str(output_path)]
        try:
            _run_ffmpeg(args,cancelled,timeout=max(600,duration*12),progress=lambda value:progress(min(99,5+int(value*.94))),duration=duration)
            result=probe(output_path)
            actual=_video_duration(result)
            # Frame quantization can shorten by one frame; a truly short decode is a failure.
            if actual<duration-max(.06,1.5/fps):
                raise ValueError("The recording ended before the requested shot duration. No freeze-frame was inserted.")
            progress(100)
        except BaseException:
            output_path.unlink(missing_ok=True)
            raise


def _crossfade_group(clips: list[Path], durations: list[float], output: Path, transition_duration: float, fps: int, cancelled: Cancelled, progress: Progress | None = None) -> float:
    """Join up to eight normalized clips with time-correct video/audio overlap."""
    if len(clips)==1:
        shutil.copyfile(clips[0],output)
        return durations[0]
    args=["-y","-filter_complex_threads","1"]
    graph=[]
    for i,clip in enumerate(clips):
        args += ["-threads","2","-protocol_whitelist","file,pipe","-i",str(clip)]
        graph.append(f"[{i}:v:0]setpts=PTS-STARTPTS,fps={fps},settb=AVTB,format=yuv420p[v{i}]")
        graph.append(f"[{i}:a:0]atrim=duration={durations[i]:.8f},asetpts=PTS-STARTPTS[a{i}]")
    video,audio="v0","a0"
    elapsed=durations[0]
    for i in range(1,len(clips)):
        next_video,next_audio=f"vx{i}",f"ax{i}"
        offset=max(0,elapsed-transition_duration)
        graph.append(f"[{video}][v{i}]xfade=transition=fade:duration={transition_duration:.8f}:offset={offset:.8f}[{next_video}]")
        graph.append(f"[{audio}][a{i}]acrossfade=d={transition_duration:.8f}:c1=tri:c2=tri[{next_audio}]")
        elapsed+=durations[i]-transition_duration
        video,audio=next_video,next_audio
    script=output.with_suffix(".filter.txt")
    script.write_text(";".join(graph),encoding="utf-8")
    args += ["-filter_complex_script",str(script),"-map",f"[{video}]","-map",f"[{audio}]","-t",f"{elapsed:.8f}","-r",str(fps),"-c:v","libx264","-preset","veryfast","-crf","18","-pix_fmt","yuv420p","-c:a","aac","-ar","48000","-ac","2","-movflags","+faststart",str(output)]
    try:
        _run_ffmpeg(args,cancelled,timeout=max(600,elapsed*10),progress=progress,duration=elapsed)
    finally:
        script.unlink(missing_ok=True)
    return elapsed


def render_export(clips: list[Path], output_path: Path, width: int, height: int, fps: int, audio_path: Path | None, progress: Progress, cancelled: Cancelled, transition: str = "cut", transition_duration: float = .35) -> None:
    """Normalize and edit real shots, optionally crossfading and mixing music.

    With crossfades, output duration is sum(shot durations) minus one overlap per
    adjacent pair. Music plays beneath preserved source audio at 18% volume.
    """
    if not clips or len(clips)>100:
        raise ValueError("Export needs between 1 and 100 completed shots.")
    if min(width,height)<64 or max(width,height)>3840 or width%2 or height%2 or not 8<=fps<=30:
        raise ValueError("Export dimensions must be even, 64–3840 pixels, at 8–30 FPS.")
    if transition not in {"cut","crossfade"} or not math.isfinite(transition_duration) or not 0<=transition_duration<=.8:
        raise ValueError("Use cut or crossfade, with a transition duration from zero to 0.8 seconds.")
    output_path=Path(output_path)
    output_path.parent.mkdir(parents=True,exist_ok=True)
    if cancelled():
        raise RenderCancelled()
    if output_path.resolve() in {Path(clip).resolve() for clip in clips} or (audio_path and output_path.resolve()==Path(audio_path).resolve()):
        raise ValueError("Export output must differ from its source media.")
    metadata=[probe(Path(clip)) for clip in clips]
    source_durations=[_video_duration(info) for info in metadata]
    if any(not _video_stream(info) or duration<=0 or duration>1800 for info,duration in zip(metadata,source_durations)):
        raise ValueError("An export clip has an invalid video stream or duration.")
    use_crossfade=transition=="crossfade" and transition_duration>0 and len(clips)>1
    if use_crossfade and transition_duration>min(source_durations)/2+.001:
        raise ValueError("Crossfade duration cannot exceed half the shortest clip.")
    try:
        with tempfile.TemporaryDirectory(prefix="frameva-export-") as temp:
            tmp=Path(temp)
            normalized=[]
            durations=[]
            for i,(clip,info,duration) in enumerate(zip(clips,metadata,source_durations)):
                if cancelled():
                    raise RenderCancelled()
                has_audio=any(s.get("codec_type")=="audio" for s in info["streams"])
                dest=tmp/f"clip-{i:04d}.mp4"
                args=["-y","-protocol_whitelist","file,pipe","-i",str(Path(clip).resolve())]
                if not has_audio:
                    args += ["-f","lavfi","-i","anullsrc=channel_layout=stereo:sample_rate=48000"]
                args += ["-map","0:v:0","-map","0:a:0" if has_audio else "1:a:0","-vf",f"scale={width}:{height}:force_original_aspect_ratio=decrease,pad={width}:{height}:(ow-iw)/2:(oh-ih)/2:color=0x0a0d12,setsar=1,setpts=PTS-STARTPTS,fps={fps}","-c:v","libx264","-preset","veryfast","-crf","18","-pix_fmt","yuv420p","-c:a","aac","-ar","48000","-ac","2","-af",f"apad,atrim=duration={duration:.8f},asetpts=PTS-STARTPTS","-t",str(duration),str(dest)]
                _run_ffmpeg(args,cancelled)
                normalized.append(dest)
                durations.append(_video_duration(probe(dest)))
                progress(int((i+1)/len(clips)*65))
            joined=tmp/"joined.mp4" if audio_path else output_path
            if use_crossfade:
                if transition_duration>min(durations)/2+.001:
                    raise ValueError("Crossfade is too long after frame-rate normalization.")
                # Limit simultaneously decoded inputs and Windows command-line length.
                generation=0
                while len(normalized)>8:
                    next_clips,next_durations=[],[]
                    for group_idx,start in enumerate(range(0,len(normalized),8)):
                        dest=tmp/f"group-{generation}-{group_idx}.mp4"
                        actual=_crossfade_group(normalized[start:start+8],durations[start:start+8],dest,transition_duration,fps,cancelled)
                        next_clips.append(dest)
                        next_durations.append(actual)
                    normalized,durations=next_clips,next_durations
                    generation+=1
                _crossfade_group(normalized,durations,joined,transition_duration,fps,cancelled,lambda n:progress(65+int(n*.20)))
            else:
                listing=tmp/"concat.txt"
                listing.write_text("".join(f"file '{p.name}'\n" for p in normalized),encoding="utf-8")
                _run_ffmpeg(["-y","-protocol_whitelist","file,pipe","-f","concat","-safe","1","-i",str(listing),"-c","copy","-movflags","+faststart",str(joined)],cancelled)
            progress(87)
            if audio_path:
                audio_info=validate_media(Path(audio_path),"audio/wav")
                if audio_info["kind"]!="audio":
                    raise ValueError("The soundtrack must be an audio asset.")
                joined_duration=_video_duration(probe(joined))
                fade=min(.5,joined_duration/2)
                audio_graph=f"[0:a:0]aresample=48000,volume=1[source];[1:a:0]aresample=48000,volume=0.18,afade=t=in:st=0:d={fade:.8f},afade=t=out:st={max(0,joined_duration-fade):.8f}:d={fade:.8f}[music];[source][music]amix=inputs=2:duration=first:dropout_transition=0:normalize=0,alimiter=limit=0.95[mixed]"
                _run_ffmpeg(["-y","-protocol_whitelist","file,pipe","-i",str(joined),"-stream_loop","-1","-protocol_whitelist","file,pipe","-i",str(Path(audio_path).resolve()),"-filter_complex",audio_graph,"-map","0:v:0","-map","[mixed]","-c:v","copy","-c:a","aac","-ar","48000","-ac","2","-t",f"{joined_duration:.8f}","-movflags","+faststart",str(output_path)],cancelled,progress=lambda n:progress(87+int(n*.12)),duration=joined_duration)
            progress(100)
    except BaseException:
        output_path.unlink(missing_ok=True)
        raise
