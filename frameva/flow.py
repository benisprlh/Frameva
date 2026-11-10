"""Record a real, explicitly described browser workflow into a video.

Plans are untrusted data, never JavaScript or shell instructions. Browser actions
can change the target application's data: use a dedicated demo account/dataset.
Playwright is optional and is never installed or launched during import.

Protocol references (checked 2026-11-10):
https://playwright.dev/python/docs/videos
https://playwright.dev/python/docs/api/class-browsercontext
https://playwright.dev/python/docs/api/class-locator
"""
from __future__ import annotations

import asyncio
from contextlib import suppress
import math
import os
from pathlib import Path
import re
import tempfile
import time
from typing import Annotated, Callable, Literal
from urllib.parse import urljoin, urlsplit
import uuid

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, field_validator, model_validator

from .render import RenderCancelled, _run_ffmpeg, validate_media


class FlowError(ValueError):
    """A sanitized recording failure; partial video is never published."""


def _origin(url: str) -> tuple[str, str, int]:
    if not isinstance(url, str) or len(url) > 4096 or any(ord(c) <= 32 or ord(c) == 127 for c in url) or "\\" in url:
        raise ValueError("Use an HTTP(S) URL without spaces, control characters or backslashes.")
    try:
        parsed = urlsplit(url)
        if parsed.scheme not in {"http", "https"} or not parsed.hostname or parsed.username is not None or parsed.password is not None:
            raise ValueError("Use an HTTP(S) app URL without embedded credentials.")
        host = parsed.hostname.encode("idna").decode("ascii").lower()
        if "%" in host:
            raise ValueError("Percent-encoded hostnames are not supported.")
        return parsed.scheme, host, parsed.port if parsed.port is not None else (443 if parsed.scheme == "https" else 80)
    except (UnicodeError, ValueError) as exc:
        raise ValueError("Use a valid HTTP(S) app URL without embedded credentials.") from exc


def resolve_flow_url(base_url: str, target: str) -> str:
    """Resolve relative navigation and require the exact base origin."""
    if not isinstance(target, str) or not target or any(ord(c) <= 32 or ord(c) == 127 for c in target) or "\\" in target:
        raise ValueError("Navigation URL is empty or contains unsupported characters.")
    resolved = urljoin(base_url, target)
    if _origin(resolved) != _origin(base_url):
        raise ValueError("Flow navigation must remain on the base URL's origin.")
    return resolved


class FlowStep(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, str_strip_whitespace=True, allow_inf_nan=False)
    action: Literal["goto", "click", "fill", "press", "scroll", "wait", "assert_text"]
    selector: str | None = Field(default=None, min_length=1, max_length=2000)
    value: Annotated[str, StringConstraints(strip_whitespace=False)] | None = Field(default=None, max_length=8000, description="Literal demo text is saved with the plan. Never put credentials here; use secret_env.")
    secret_env: str | None = Field(default=None, pattern=r"^FRAMEVA_FLOW_SECRET_[A-Z0-9_]{1,100}$")
    typing_delay_ms: int | None = Field(default=None, ge=0, le=150)
    url: str | None = Field(default=None, min_length=1, max_length=4096)
    text: Annotated[str, StringConstraints(strip_whitespace=False)] | None = Field(default=None, min_length=1, max_length=4000)
    key: str | None = Field(default=None, min_length=1, max_length=100)
    x: float | None = Field(default=None, ge=-4000, le=4000)
    y: float | None = Field(default=None, ge=-4000, le=4000)
    seconds: float | None = Field(default=None, ge=0, le=30)
    timeout_ms: int = Field(default=10000, ge=100, le=30000)
    label: str | None = Field(default=None, max_length=180)

    @model_validator(mode="after")
    def action_fields(self):
        allowed = {
            "goto": {"url"}, "click": {"selector"},
            "fill": {"selector", "value", "secret_env", "typing_delay_ms"},
            "press": {"selector", "key"},
            "scroll": {"selector", "x", "y"}, "wait": {"seconds"},
            "assert_text": {"selector", "text"},
        }[self.action] | {"action", "timeout_ms", "label"}
        supplied = {key for key in self.model_fields_set if getattr(self, key) is not None}
        if supplied - allowed:
            raise ValueError("This action contains fields that do not apply to it.")
        for field in {"goto": ("url",), "click": ("selector",), "fill": ("selector",), "press": ("key",), "wait": ("seconds",), "assert_text": ("text",)}.get(self.action, ()):
            if getattr(self, field) is None:
                raise ValueError(f"The {self.action} action requires {field}.")
        if self.action == "fill" and ((self.value is None) == (self.secret_env is None)):
            raise ValueError("Fill requires exactly one of value or secret_env.")
        if self.action == "scroll" and self.x is None and self.y is None:
            raise ValueError("Scroll requires x or y wheel distance.")
        if self.selector and any(c in self.selector for c in ("\x00", "\r", "\n")):
            raise ValueError("Selectors must be a single line.")
        return self


FeatureTitle = Annotated[str, Field(min_length=1, max_length=200)]


class FlowInput(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, str_strip_whitespace=True, allow_inf_nan=False)
    name: str = Field(min_length=1, max_length=120)
    base_url: str = Field(min_length=1, max_length=4096)
    width: int = Field(default=1440, ge=320, le=2560)
    height: int = Field(default=900, ge=320, le=2160)
    fps: int = Field(default=30, ge=8, le=60)
    max_duration: float = Field(default=120, ge=3, le=300)
    steps: list[FlowStep] = Field(min_length=1, max_length=80)
    feature_titles: list[FeatureTitle] = Field(default_factory=list, max_length=100)

    @field_validator("width", "height")
    @classmethod
    def even_dimensions(cls, value):
        if value % 2:
            raise ValueError("Recording dimensions must be even.")
        return value

    @model_validator(mode="after")
    def navigation_and_budget(self):
        _origin(self.base_url)
        for step in self.steps:
            if step.action == "goto":
                resolve_flow_url(self.base_url, step.url)
        if sum(step.seconds or 0 for step in self.steps) >= self.max_duration:
            raise ValueError("Explicit waits must leave time within max_duration for the actions and recording.")
        if len(set(self.feature_titles)) != len(self.feature_titles):
            raise ValueError("Feature mappings must be distinct titles.")
        return self


# Fixed first-party instrumentation: no user plan text is interpolated here.
# Pointer events paint the cursor/ripple, so they appear in the recorded pixels.
CURSOR_OVERLAY = r"""(() => {
  if (window.top !== window) return;
  let host, pointer, ring;
  const lift = () => {
    if (!host || typeof host.showPopover !== 'function') return;
    try {
      if (host.matches(':popover-open')) host.hidePopover();
      host.showPopover();
    } catch { host.removeAttribute('popover'); }
  };
  const mount = () => {
    if (pointer || !document.documentElement) return;
    host = document.createElement('div');
    host.setAttribute('aria-hidden', 'true');
    host.setAttribute('data-frameva-cursor', '');
    if (typeof host.showPopover === 'function') host.setAttribute('popover', 'manual');
    host.style.cssText = 'position:fixed;inset:0;width:100vw;height:100vh;margin:0;padding:0;border:0;background:transparent;z-index:2147483647;pointer-events:none;contain:strict';
    const root = host.attachShadow({mode:'closed'});
    const backdropStyle = document.createElement('style');
    backdropStyle.textContent = '[data-frameva-cursor]::backdrop{background:transparent!important;pointer-events:none!important}';
    document.documentElement.append(backdropStyle);
    const style = document.createElement('style');
    style.textContent = '.cursor{position:absolute;left:0;top:0;width:18px;height:18px;border-radius:50%;background:#c6ff79;border:2px solid #162311;box-shadow:0 2px 10px #0009;transform:translate(-100px,-100px);pointer-events:none}.ring{position:absolute;left:0;top:0;width:44px;height:44px;border:3px solid #c6ff79;border-radius:50%;opacity:0;pointer-events:none;box-sizing:border-box}';
    pointer = document.createElement('div'); pointer.className='cursor';
    ring = document.createElement('div'); ring.className='ring';
    root.append(style,pointer,ring); document.documentElement.append(host); lift();
  };
  document.addEventListener('DOMContentLoaded', mount, {once:true});
  document.addEventListener('mousemove', event => {
    mount(); lift(); if(pointer) pointer.style.transform=`translate(${event.clientX-9}px,${event.clientY-9}px)`;
  }, true);
  document.addEventListener('pointerdown', event => {
    mount(); lift(); if(!ring) return;
    ring.style.left=(event.clientX-22)+'px'; ring.style.top=(event.clientY-22)+'px';
    ring.animate([{opacity:0.95,transform:'scale(.6)'},{opacity:0,transform:'scale(1.8)'}],{duration:620,easing:'ease-out'});
  }, true);
  mount();
})();"""


def _runtime_secrets(plan: FlowInput) -> dict[str, str]:
    values = {}
    for step in plan.steps:
        if step.secret_env:
            value = os.environ.get(step.secret_env)
            if value is None or not 1 <= len(value) <= 8000:
                raise FlowError(f"Set {step.secret_env} to a nonempty secret of at most 8,000 characters before recording.")
            values[step.secret_env] = value
    return values


def _redact_report(value, secrets: dict[str, str]):
    if isinstance(value, str):
        for secret in sorted(secrets.values(), key=len, reverse=True):
            value = value.replace(secret, "[redacted]")
        return value
    if isinstance(value, list):
        return [_redact_report(item, secrets) for item in value]
    if isinstance(value, dict):
        return {key: _redact_report(item, secrets) for key, item in value.items()}
    return value


def _load_playwright():
    try:
        from playwright.async_api import async_playwright, expect
    except ImportError as exc:
        raise FlowError("Install browser recording support from the source checkout: python -m pip install -e '.[capture]'; then python -m frameva install-browser.") from exc
    return async_playwright, expect


async def _bounded_close(value, timeout: float):
    if value is not None:
        with suppress(Exception, asyncio.CancelledError):
            await asyncio.wait_for(value.close(), timeout=timeout)


async def _move_to(page, locator, cursor: list[float], timeout_ms: int, width: int, height: int) -> dict:
    await locator.scroll_into_view_if_needed(timeout=timeout_ms)
    box = await locator.bounding_box(timeout=timeout_ms)
    if not box or box["width"] <= 0 or box["height"] <= 0:
        raise FlowError("The target is not visible in the recorded viewport.")
    x = max(1.0, min(width - 1.0, box["x"] + box["width"] / 2))
    y = max(1.0, min(height - 1.0, box["y"] + box["height"] / 2))
    start_x, start_y = cursor
    for index in range(1, 13):
        t = index / 12
        ease = t * t * (3 - 2 * t)
        await page.mouse.move(start_x + (x - start_x) * ease, start_y + (y - start_y) * ease)
        await asyncio.sleep(0.016)
    cursor[:] = (x, y)
    return {"focus_x": round(x / width, 4), "focus_y": round(y / height, 4)}


async def _perform_step(page, step: FlowStep, plan: FlowInput, cursor: list[float], secrets: dict[str, str], expect) -> dict:
    """No failure propagates arbitrary Playwright logs or fill values."""
    locator = page.locator(step.selector) if step.selector else None
    focus = {}
    if step.action in {"click", "fill"} or (step.action in {"press", "scroll"} and locator is not None):
        focus = await _move_to(page, locator, cursor, step.timeout_ms, plan.width, plan.height)
    if step.action == "goto":
        response = await page.goto(resolve_flow_url(plan.base_url, step.url), wait_until="domcontentloaded", timeout=step.timeout_ms)
        if response is not None and response.status >= 400:
            raise FlowError("The target page returned an HTTP error.")
    elif step.action == "click":
        await locator.click(timeout=step.timeout_ms)
    elif step.action == "fill":
        value = secrets[step.secret_env] if step.secret_env else step.value
        delay = 35 if step.typing_delay_ms is None else step.typing_delay_ms
        if step.secret_env or delay == 0:
            await locator.fill(value, timeout=step.timeout_ms)
        else:
            await locator.fill("", timeout=step.timeout_ms)
            await locator.press_sequentially(value, delay=delay, timeout=step.timeout_ms)
    elif step.action == "press":
        if locator is not None:
            await locator.press(step.key, timeout=step.timeout_ms)
        else:
            await page.keyboard.press(step.key)
    elif step.action == "scroll":
        dx, dy = step.x or 0, step.y or 0
        for _ in range(12):
            await page.mouse.wheel(dx / 12, dy / 12)
            await asyncio.sleep(0.025)
    elif step.action == "wait":
        # Intentional cinematic hold, not a substitute for actionability/assertions.
        await asyncio.sleep(step.seconds)
    elif step.action == "assert_text":
        await expect(locator if locator is not None else page.locator("body")).to_contain_text(step.text, timeout=step.timeout_ms, use_inner_text=True)
    return focus


async def _capture(plan: FlowInput, directory: Path, progress, secrets: dict[str, str]) -> tuple[Path, dict]:
    factory, expect = _load_playwright()
    runtime = browser = context = None
    blocked_navigation = False
    popup_seen = False
    report_steps = []
    try:
        runtime = await factory().start()
        browser = await runtime.chromium.launch(headless=True, timeout=min(20000, int(plan.max_duration * 1000)))
        context = await browser.new_context(
            viewport={"width": plan.width, "height": plan.height},
            record_video_dir=str(directory), record_video_size={"width": plan.width, "height": plan.height},
            device_scale_factor=1, accept_downloads=False, service_workers="block",
        )
        context.set_default_timeout(10000)
        context.set_default_navigation_timeout(10000)
        await context.add_init_script(script=CURSOR_OVERLAY)

        async def route_request(route):
            nonlocal blocked_navigation
            request = route.request
            if request.is_navigation_request():
                try:
                    allowed = _origin(request.url) == _origin(plan.base_url)
                except ValueError:
                    allowed = False
                if not allowed:
                    blocked_navigation = True
                    await route.abort("blockedbyclient")
                    return
            await route.continue_()

        await context.route("**/*", route_request)
        # The time origin brackets page creation; exact encoder start is not exposed
        # by the stable record_video API. Report timings are approximate, not edits.
        recording_started = time.monotonic()
        page = await context.new_page()
        video = page.video
        if video is None:
            raise FlowError("Playwright did not create a video recorder.")

        async def close_popup(popup):
            nonlocal popup_seen
            popup_seen = True
            await _bounded_close(popup, 3)

        async def dismiss_dialog(dialog):
            with suppress(Exception):
                await asyncio.wait_for(dialog.dismiss(), timeout=3)

        page.on("popup", close_popup)
        page.on("dialog", dismiss_dialog)

        def check_navigation():
            if blocked_navigation:
                raise FlowError("A navigation left the allowed app origin and was blocked. Use a same-origin demo flow.")
            if popup_seen:
                raise FlowError("The workflow opened a popup. This recorder supports one page; use an in-page demo flow.")
            try:
                valid = _origin(page.url) == _origin(plan.base_url)
            except ValueError:
                valid = False
            if not valid:
                raise FlowError("The page left the allowed app origin.")

        response = await page.goto(plan.base_url, wait_until="domcontentloaded", timeout=min(20000, int(plan.max_duration * 1000)))
        if response is not None and response.status >= 400:
            raise FlowError("The app's starting page returned an HTTP error.")
        check_navigation()
        cursor = [plan.width * .82, plan.height * .75]
        await page.mouse.move(*cursor)
        await asyncio.sleep(0.6)
        progress(8)
        for index, step in enumerate(plan.steps):
            check_navigation()
            begin = time.monotonic() - recording_started
            try:
                focus = await _perform_step(page, step, plan, cursor, secrets, expect)
            except asyncio.CancelledError:
                raise
            except Exception:
                # Do not include Playwright exception bodies: they can quote fill
                # values, selectors, URLs or text from the target application.
                raise FlowError(f"Step {index + 1} ({step.action}) failed. Check its target, assertion, app state and timeout.") from None
            check_navigation()
            await asyncio.sleep(0.45 if step.action != "wait" else 0.1)
            report_steps.append({"index": index + 1, "action": step.action, "label": step.label or f"Step {index + 1}",
                                 "status": "passed", "start": round(begin, 3), "end": round(time.monotonic() - recording_started, 3), **focus})
            progress(8 + int((index + 1) / len(plan.steps) * 70))
        await asyncio.sleep(0.8)
        check_navigation()
        recording_elapsed = time.monotonic() - recording_started
        await asyncio.wait_for(context.close(), timeout=12)
        context = None
        path = Path(await video.path())
        if not path.is_file() or path.resolve().parent != directory.resolve():
            raise FlowError("The browser did not finish writing its recorded video.")
        report = {"schema_version": 1, "status": "completed", "steps": report_steps,
                  "recording_kind": "browser-flow", "feature_titles": plan.feature_titles,
                  "timing_origin": "page_creation_monotonic_approximate", "capture_elapsed": round(recording_elapsed, 3),
                  "warnings": [
                      "Step times are approximate offsets from page creation; they are not frame-accurate edit points.",
                      "Browser capture contains actual page pixels and interaction overlays; no browser/system audio is recorded.",
                      "Output FPS is normalized; older Playwright versions capture at 25 FPS, so extra frames may be duplicates.",
                      "Feature titles are explicit user/agent mappings. A passed flow is evidence of these steps, not proof of complete feature coverage.",
                  ]}
        if secrets:
            report["warnings"].append("Secret values are omitted from the plan/report; the target app may still display them in the recorded video. Review before sharing.")
        return path, _redact_report(report, secrets)
    except (FlowError, asyncio.CancelledError):
        raise
    except Exception:
        raise FlowError("Browser recording could not start or finish. Run python -m frameva install-browser (or frameva-worker install-browser for a bundled helper), then check the running app URL.") from None
    finally:
        await _bounded_close(context, 12)
        await _bounded_close(browser, 5)
        if runtime is not None:
            with suppress(Exception, asyncio.CancelledError):
                await asyncio.wait_for(runtime.stop(), timeout=5)


async def _capture_guarded(plan: FlowInput, directory: Path, progress, cancelled, secrets: dict[str, str]):
    task = asyncio.create_task(_capture(plan, directory, progress, secrets))
    async def watch_cancel():
        while not cancelled():
            await asyncio.sleep(0.05)
        return True
    watcher = asyncio.create_task(watch_cancel())
    try:
        done, _ = await asyncio.wait({task, watcher}, timeout=plan.max_duration, return_when=asyncio.FIRST_COMPLETED)
        if watcher in done:
            raise RenderCancelled()
        if task not in done:
            raise FlowError("The flow exceeded max_duration. Shorten the steps, fix the target app, or increase the time budget (maximum 300 seconds).")
        return await task
    finally:
        watcher.cancel()
        if not task.done():
            task.cancel()
        with suppress(asyncio.CancelledError, Exception):
            await asyncio.wait_for(task, timeout=25)
        with suppress(asyncio.CancelledError):
            await watcher


def record_flow(plan: dict | FlowInput, output_path: Path,
                progress: Callable[[int], None] = lambda n: None,
                cancelled: Callable[[], bool] = lambda: False) -> dict:
    """Record actual continuous browser video; raise on any incomplete step.

    The app must already be running. This function never starts repository code,
    installs packages/browsers, reuses a browser profile, or evaluates plan code.
    ``max_duration`` bounds capture including browser startup. Final media
    normalization has a separate 120-second ceiling and supports cancellation.
    """
    parsed = plan if isinstance(plan, FlowInput) else FlowInput.model_validate(plan)
    output_path = Path(output_path)
    if output_path.suffix.lower() != ".mp4":
        raise ValueError("Browser recordings must use an .mp4 output path.")
    if cancelled():
        raise RenderCancelled()
    secrets = _runtime_secrets(parsed)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    normalized = output_path.parent / (".frameva-recording-" + uuid.uuid4().hex + ".mp4")
    progress(1)
    try:
        with tempfile.TemporaryDirectory(prefix="frameva-flow-") as temp:
            recorded, report = asyncio.run(_capture_guarded(parsed, Path(temp), progress, cancelled, secrets))
            if cancelled():
                raise RenderCancelled()
            info = validate_media(recorded, "video/webm")
            if info["kind"] != "video" or not math.isfinite(info["duration"]) or info["duration"] > parsed.max_duration + 15:
                raise FlowError("The browser returned an invalid or overlong video.")
            progress(82)
            _run_ffmpeg(["-y", "-protocol_whitelist", "file,pipe", "-i", str(recorded), "-map", "0:v:0", "-an",
                         "-vf", f"scale={parsed.width}:{parsed.height},fps={parsed.fps}", "-c:v", "libx264", "-preset", "veryfast",
                         "-crf", "18", "-pix_fmt", "yuv420p", "-movflags", "+faststart", str(normalized)], cancelled, timeout=120)
            final = validate_media(normalized, "video/mp4")
            if final["kind"] != "video":
                raise FlowError("Video normalization did not produce a playable video.")
            if cancelled():
                raise RenderCancelled()
            report["duration"] = final["duration"]
            report["width"], report["height"], report["fps"] = parsed.width, parsed.height, parsed.fps
            os.replace(normalized, output_path)
            progress(100)
            return report
    except (RenderCancelled, FlowError):
        raise
    except Exception:
        raise FlowError("Recording media could not be finalized. Check FFmpeg, available disk space and the browser installation.") from None
    finally:
        normalized.unlink(missing_ok=True)
