"""Recorder contracts with fake browser objects; never launch a browser in QA."""
import asyncio
import copy
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import AsyncMock, patch

from pydantic import ValidationError

from frameva import flow, render


def plan(**overrides):
    return {"name": "Demo", "base_url": "http://127.0.0.1:4173", "width": 640, "height": 360,
            "max_duration": 30, "steps": [{"action": "wait", "seconds": 0.1}], **overrides}


class FakeLocator:
    def __init__(self, page, selector):
        self.page, self.selector = page, selector

    async def scroll_into_view_if_needed(self, **kwargs): pass
    async def bounding_box(self, **kwargs): return {"x": 100, "y": 80, "width": 100, "height": 40}
    async def click(self, **kwargs):
        self.page.calls.append(("click", self.selector))
        if self.selector == "#missing": raise RuntimeError("private failure body password=never-log")
    async def fill(self, value, **kwargs): self.page.calls.append(("fill", value))
    async def press_sequentially(self, value, **kwargs): self.page.calls.append(("type", value, kwargs["delay"]))
    async def press(self, value, **kwargs): self.page.calls.append(("press", value))


class FakeVideo:
    def __init__(self, context): self.context = context
    async def path(self):
        if not self.context.closed: raise AssertionError("Context must close before video retrieval")
        return self.context.path


class FakePage:
    def __init__(self, context):
        self.context, self.calls = context, []
        self.mouse = type("Mouse", (), {"move": AsyncMock(), "wheel": AsyncMock()})()
        self.keyboard = type("Keyboard", (), {"press": AsyncMock()})()
        self.url = "about:blank"
        self.video = FakeVideo(context)
        self.events = {}

    async def goto(self, url, **kwargs):
        self.url = url
        self.calls.append(("goto", url))
        return type("Response", (), {"status": 200})()
    def locator(self, selector): return FakeLocator(self, selector)
    def on(self, event, callback): self.events[event] = callback


class FakeContext:
    def __init__(self, directory):
        self.path = Path(directory) / "capture.webm"
        self.path.write_bytes(b"mock-browser-video")
        self.page = FakePage(self)
        self.closed = False
        self.script = None
        self.route_handler = None
    def set_default_timeout(self, value): pass
    def set_default_navigation_timeout(self, value): pass
    async def add_init_script(self, script): self.script = script
    async def route(self, pattern, handler): self.route_handler = handler
    async def new_page(self): return self.page
    async def close(self): self.closed = True


class FakeBrowser:
    def __init__(self): self.context = None; self.kwargs = None; self.closed = False
    async def new_context(self, **kwargs):
        self.kwargs = kwargs
        self.context = FakeContext(kwargs["record_video_dir"])
        return self.context
    async def close(self): self.closed = True


class FakeRuntime:
    def __init__(self):
        self.browser = FakeBrowser()
        self.chromium = type("Chromium", (), {"launch": AsyncMock(return_value=self.browser)})()
        self.stopped = False
    async def stop(self): self.stopped = True


class FakeExpectation:
    def __init__(self, locator): self.locator = locator
    async def to_contain_text(self, text, **kwargs): self.locator.page.calls.append(("assert", text))


class FlowValidationTests(unittest.TestCase):
    def test_strict_plan_and_action_fields(self):
        for bad in [plan(width="640"), plan(width=641), plan(steps=[]), plan(max_duration=301),
                    plan(steps=[{"action": "evaluate", "value": "alert(1)"}]),
                    plan(steps=[{"action": "click", "selector": "#ok", "value": "ignored"}]),
                    plan(steps=[{"action": "fill", "selector": "#password", "value": "x", "secret_env": "FRAMEVA_FLOW_SECRET_PASSWORD"}]),
                    plan(steps=[{"action": "fill", "selector": "#password", "secret_env": "FRAMEVA_TOKEN"}]),
                    plan(steps=[{"action": "click", "selector": "#ok", "typing_delay_ms": 10}]),
                    plan(steps=[{"action": "fill", "selector": "#title", "value": "x", "typing_delay_ms": 151}]),
                    plan(steps=[{"action": "wait", "seconds": float("nan")}])]:
            with self.subTest(bad=bad), self.assertRaises(ValidationError): flow.FlowInput.model_validate(bad)

    def test_same_origin_url_policy(self):
        base = "https://example.test/app"
        self.assertEqual(flow.resolve_flow_url(base, "/tasks"), "https://example.test/tasks")
        self.assertEqual(flow.resolve_flow_url(base, "https://example.test:443/tasks"), "https://example.test:443/tasks")
        for url in ["https://example.test.evil/tasks", "//evil.test/", "http://example.test/", "file:///etc/passwd", "javascript:alert(1)", "https://user:password@example.test/", "https://example.test:444", "/foo\nbar", "https://example.test\\@evil.test"]:
            with self.subTest(url=url), self.assertRaises(ValueError): flow.resolve_flow_url(base, url)
        with self.assertRaises(ValueError): flow.resolve_flow_url("http://example.test:0", "http://example.test:80")

    def test_literal_fill_preserves_exact_text(self):
        checked = flow.FlowStep.model_validate({"action": "fill", "selector": "#title", "value": "  space sensitive  "})
        self.assertEqual(checked.value, "  space sensitive  ")

    def test_feature_mapping_and_wait_budget(self):
        checked = flow.FlowInput.model_validate(plan(feature_titles=["Create tasks"]))
        self.assertEqual(checked.feature_titles, ["Create tasks"])
        for bad in [plan(feature_titles=["Create tasks", "Create tasks"]), plan(feature_titles=["x" * 201]),
                    plan(max_duration=3, steps=[{"action": "wait", "seconds": 3}])]:
            with self.assertRaises(ValidationError): flow.FlowInput.model_validate(bad)

    def test_secrets_must_be_explicitly_provisioned(self):
        checked = flow.FlowInput.model_validate(plan(steps=[{"action": "fill", "selector": "#password", "secret_env": "FRAMEVA_FLOW_SECRET_TEST"}]))
        with patch.dict(os.environ, {}, clear=True), self.assertRaises(flow.FlowError): flow._runtime_secrets(checked)
        with patch.dict(os.environ, {"FRAMEVA_FLOW_SECRET_TEST": "secret-test"}):
            self.assertEqual(flow._runtime_secrets(checked)["FRAMEVA_FLOW_SECRET_TEST"], "secret-test")
        result = flow._redact_report({"label": "has secret-test", "nested": ["secret-test"]}, {"key": "secret-test"})
        self.assertNotIn("secret-test", json.dumps(result))


class CaptureContractTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.runtime = FakeRuntime()
        manager = type("Manager", (), {"start": AsyncMock(return_value=self.runtime)})()
        self.loader = patch("frameva.flow._load_playwright", return_value=(lambda: manager, FakeExpectation))
        self.loader.start()
        self.original_sleep = asyncio.sleep
        async def short_sleep(seconds): await self.original_sleep(0)
        self.sleep = patch("frameva.flow.asyncio.sleep", side_effect=short_sleep)
        self.sleep.start()

    async def asyncTearDown(self):
        self.sleep.stop(); self.loader.stop(); self.temp.cleanup()

    async def test_records_actions_without_screenshots_and_closes_before_path(self):
        checked = flow.FlowInput.model_validate(plan(steps=[
            {"action": "goto", "url": "/tasks"}, {"action": "click", "selector": "#add"},
            {"action": "fill", "selector": "#title", "value": "Demo task"},
            {"action": "fill", "selector": "#password", "secret_env": "FRAMEVA_FLOW_SECRET_TEST"},
            {"action": "press", "selector": "#title", "key": "Enter"},
            {"action": "scroll", "y": 300}, {"action": "assert_text", "text": "Task created"},
            {"action": "wait", "seconds": 0.1}], feature_titles=["Create tasks"]))
        path, report = await flow._capture(checked, Path(self.temp.name), lambda n: None, {"FRAMEVA_FLOW_SECRET_TEST": "secret-test"})
        self.assertTrue(path.is_file())
        self.assertEqual(len(report["steps"]), 8)
        self.assertEqual(report["steps"][1]["focus_x"], round(150 / 640, 4))
        self.assertTrue(self.runtime.browser.context.closed)
        self.assertTrue(self.runtime.stopped)
        self.assertEqual(self.runtime.browser.kwargs["record_video_size"], {"width": 640, "height": 360})
        self.assertEqual(self.runtime.browser.context.script, flow.CURSOR_OVERLAY)
        self.assertNotIn("secret-test", json.dumps(report))
        self.assertNotIn("Demo task", json.dumps(report))
        self.assertEqual(report["feature_titles"], ["Create tasks"])
        self.assertIn(("type", "Demo task", 35), self.runtime.browser.context.page.calls)
        self.assertIn(("fill", "secret-test"), self.runtime.browser.context.page.calls)
        self.assertFalse(any(call[0] == "type" and call[1] == "secret-test" for call in self.runtime.browser.context.page.calls))

    async def test_typing_pace_can_be_disabled(self):
        checked = flow.FlowInput.model_validate(plan(steps=[{"action": "fill", "selector": "#title", "value": "Instant", "typing_delay_ms": 0}]))
        await flow._capture(checked, Path(self.temp.name), lambda n: None, {})
        self.assertIn(("fill", "Instant"), self.runtime.browser.context.page.calls)
        self.assertFalse(any(call[0] == "type" for call in self.runtime.browser.context.page.calls))

    async def test_failed_step_does_not_return_success_or_private_log(self):
        checked = flow.FlowInput.model_validate(plan(steps=[{"action": "click", "selector": "#missing"}]))
        with self.assertRaises(flow.FlowError) as error:
            await flow._capture(checked, Path(self.temp.name), lambda n: None, {})
        self.assertIn("Step 1 (click) failed", str(error.exception))
        self.assertNotIn("never-log", str(error.exception))
        self.assertTrue(self.runtime.browser.context.closed)
        self.assertTrue(self.runtime.stopped)

    async def test_route_handler_blocks_external_navigation_but_allows_assets(self):
        checked = flow.FlowInput.model_validate(plan())
        await flow._capture(checked, Path(self.temp.name), lambda n: None, {})
        handler = self.runtime.browser.context.route_handler
        for navigation, url, allowed in [(True, "https://evil.test/", False), (True, "http://127.0.0.1:4173/tasks", True), (False, "https://cdn.example/style.css", True)]:
            req = type("Request", (), {"url": url, "is_navigation_request": lambda self: navigation})()
            route = type("Route", (), {"request": req, "abort": AsyncMock(), "continue_": AsyncMock()})()
            await handler(route)
            self.assertEqual(route.continue_.await_count, int(allowed))
            self.assertEqual(route.abort.await_count, int(not allowed))

    async def test_global_cancel_and_deadline(self):
        checked = flow.FlowInput.model_validate(plan(max_duration=3))
        async def forever(*args): await asyncio.Future()
        with patch("frameva.flow._capture", side_effect=forever), self.assertRaises(render.RenderCancelled):
            await flow._capture_guarded(checked, Path(self.temp.name), lambda n: None, lambda: True, {})
        # Smaller runtime budget tests the timeout mechanism without waiting three seconds.
        checked = checked.model_copy(update={"max_duration": .02})
        with patch("frameva.flow._capture", side_effect=forever), self.assertRaises(flow.FlowError):
            await flow._capture_guarded(checked, Path(self.temp.name), lambda n: None, lambda: False, {})


class FinalizeTests(unittest.TestCase):
    def test_failures_preserve_existing_output(self):
        with tempfile.TemporaryDirectory() as directory:
            dest = Path(directory) / "result.mp4"; dest.write_bytes(b"existing")
            with patch("frameva.flow._capture_guarded", new=AsyncMock(side_effect=flow.FlowError("Step failed"))):
                with self.assertRaises(flow.FlowError): flow.record_flow(plan(), dest)
            self.assertEqual(dest.read_bytes(), b"existing")
            self.assertEqual(list(Path(directory).iterdir()), [dest])

    @unittest.skipUnless(render.ffmpeg_path(), "FFmpeg required")
    def test_real_video_normalization_without_running_browser(self):
        with tempfile.TemporaryDirectory() as directory:
            dest = Path(directory) / "result.mp4"
            async def fake_capture(checked, temp, progress, cancelled, secrets):
                raw = temp / "capture.webm"
                render._run_ffmpeg(["-y", "-f", "lavfi", "-i", "testsrc2=size=640x360:rate=25", "-t", "1", "-c:v", "libvpx", "-deadline", "realtime", str(raw)], lambda: False)
                return raw, {"schema_version": 1, "status": "completed", "recording_kind": "browser-flow", "steps": [{"index": 1, "action": "wait", "status": "passed", "start": 0, "end": .5}], "warnings": []}
            with patch("frameva.flow._capture_guarded", side_effect=fake_capture):
                report = flow.record_flow(plan(), dest)
            self.assertEqual(report["status"], "completed")
            self.assertAlmostEqual(report["duration"], 1, delta=.08)
            self.assertEqual(render.validate_media(dest, "video/mp4")["kind"], "video")
            self.assertEqual(report["fps"], 30)
            self.assertEqual(list(Path(directory).iterdir()), [dest])


if __name__ == "__main__": unittest.main()
