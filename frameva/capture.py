"""Opt-in screenshot capture of a user-specified running application.

Installs no browsers, runs no source code, uses a clean browser profile.
"""
from __future__ import annotations
from pathlib import Path
from urllib.parse import urlsplit


def capture_screenshot(url: str, output_path: Path, width: int = 1440, height: int = 900) -> dict:
    parsed = urlsplit(url)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname or parsed.username or parsed.password:
        raise ValueError("Use an HTTP(S) app URL without embedded credentials.")
    if not 320 <= width <= 3840 or not 320 <= height <= 2160:
        raise ValueError("Capture dimensions must be 320–3840 wide and 320–2160 high.")
    output_path = Path(output_path)
    if output_path.suffix.lower() != ".png":
        raise ValueError("Screenshot output must have a .png extension.")
    try:
        from playwright.sync_api import sync_playwright
    except ImportError as exc:
        raise RuntimeError("Install capture support: python -m pip install '.[capture]' and python -m playwright install chromium") from exc
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with sync_playwright() as p:
        browser = p.chromium.launch()
        try:
            context = browser.new_context(viewport={"width": width, "height": height}, device_scale_factor=1, reduced_motion="reduce", accept_downloads=False)
            page = context.new_page()
            page.goto(url, wait_until="domcontentloaded", timeout=30000)
            try:
                page.wait_for_load_state("networkidle", timeout=5000)
            except Exception:
                pass  # Live apps may maintain connections; DOM is still capturable.
            page.evaluate("Promise.race([document.fonts.ready, new Promise(resolve => setTimeout(resolve, 2000))])")
            title = page.title()
            page.screenshot(path=str(output_path), full_page=False, animations="disabled", timeout=15000)
            return {"path": str(output_path), "url": url, "title": title, "width": width, "height": height,
                "note": "Captured a clean browser session. Sign-in protected apps may show their login screen; review before using."}
        finally:
            browser.close()
