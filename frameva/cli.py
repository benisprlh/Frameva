"""Portable CLI. No installation-wide state and no shell-dependent commands."""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import platform
import shlex
import sys
import threading
import time
from urllib.parse import quote
import webbrowser

from . import __version__


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="frameva", description="Frameva product launch video studio")
    parser.add_argument("--version", action="version", version=f"Frameva {__version__}")
    parser.add_argument("--data-dir", type=Path, help="Use this data directory (also sets the MCP configuration)")
    sub = parser.add_subparsers(dest="command", required=True)
    serve = sub.add_parser("serve", help="Run the local studio and open its browser window")
    serve.add_argument("--host", choices=("127.0.0.1", "localhost", "::1"), default="127.0.0.1")
    serve.add_argument("--port", type=int, default=8741)
    serve.add_argument("--no-open", action="store_true", help="Do not open a browser; use frameva token to sign in")
    sub.add_parser("install-browser", help="Explicitly download Playwright Chromium for browser-flow recording")
    sub.add_parser("doctor", help="Check local application prerequisites without downloading models")
    sub.add_parser("token", help="Show the local login token explicitly; keep this output private")
    sub.add_parser("mcp", help="Run the MCP stdio bridge (start frameva serve separately)")
    capture = sub.add_parser("capture", help="Capture an explicitly provided running app URL (optional capture install)")
    capture.add_argument("--url", required=True)
    capture.add_argument("--output", type=Path, required=True)
    capture.add_argument("--width", type=int, default=1440)
    capture.add_argument("--height", type=int, default=900)
    record = sub.add_parser("record-flow", help="Record a JSON browser-flow plan to continuous MP4 footage")
    record.add_argument("plan", type=Path, help="Path to a saved FlowInput JSON plan")
    record.add_argument("--output", type=Path, required=True, help="New .mp4 output path")
    cfg = sub.add_parser("mcp-config", help="Print Codex and Claude Code registration settings without secrets")
    cfg.add_argument("--format", choices=("all", "json", "toml"), default="all")
    cfg.add_argument("--url", default=None, help="Local studio URL, for a non-default port")
    return parser


def _command_quote(parts: list[str]) -> str:
    if os.name == "nt":
        # These commands are displayed for PowerShell, not passed to a shell.
        return "& " + " ".join("'" + part.replace("'", "''") + "'" for part in parts)
    return shlex.join(parts)


def configuration(data_dir: Path, url: str | None = None) -> dict:
    from .mcp_server import validate_local_url
    target = validate_local_url(url or os.environ.get("FRAMEVA_URL", "http://127.0.0.1:8741"))
    # Use the installed environment, excluding agent cwd and PYTHONPATH to prevent
    # a selected repository from shadowing the frameva package. Frozen helpers
    # already have an embedded entrypoint and must not receive Python flags.
    return {"command": str(Path(sys.executable).absolute()), "args": ["mcp"] if getattr(sys, "frozen", False) else ["-I", "-m", "frameva", "mcp"],
            "env": {"FRAMEVA_DATA_DIR": str(data_dir.absolute()), "FRAMEVA_URL": target}}


def print_configuration(data_dir: Path, url: str | None, format: str) -> None:
    conf = configuration(data_dir, url)
    json_output = json.dumps({"mcpServers": {"frameva": {"type": "stdio", **conf}}}, indent=2)
    toml_output = "\n".join([
        "[mcp_servers.frameva]", f"command = {json.dumps(conf['command'])}",
        f"args = {json.dumps(conf['args'])}", "", "[mcp_servers.frameva.env]",
        *[f"{key} = {json.dumps(value)}" for key, value in conf["env"].items()],
    ])
    if format == "json":
        print(json_output)
        return
    if format == "toml":
        print(toml_output)
        return
    env_args = [item for key, value in conf["env"].items() for item in ("--env", f"{key}={value}")]
    print("Start Frameva (native app or `frameva serve`) before connecting. Default worker port: 8741.\n")
    print("Codex CLI (registration only; does not change approval settings):")
    print(_command_quote(["codex", "mcp", "add", "frameva", *env_args, "--", conf["command"], *conf["args"]]))
    print("\nClaude Code CLI:")
    print(_command_quote(["claude", "mcp", "add", "--transport", "stdio", "--scope", "user", *env_args,
                          "frameva", "--", conf["command"], *conf["args"]]))
    print("\nClaude .mcp.json / Claude Desktop JSON (merge, do not overwrite existing servers):\n" + json_output)
    print("\nCodex ~/.codex/config.toml (merge, do not overwrite existing settings):\n" + toml_output)


def capture_status() -> dict:
    """Discover the configured browser binary without launching a browser."""
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        return {"dependency_installed": False, "chromium_binary_present": False,
                "chromium_executable": None, "status": "Install the optional capture extra or use the bundled native helper."}
    try:
        # This starts only Playwright's metadata driver, not a browser session.
        with sync_playwright() as playwright:
            executable = playwright.chromium.executable_path
        exists = Path(executable).is_file()
        return {"dependency_installed": True, "chromium_binary_present": exists,
                "chromium_executable": executable,
                "status": "Browser binary found; recording/runtime permissions are not verified." if exists else "Run install-browser explicitly to download Chromium."}
    except Exception as exc:
        return {"dependency_installed": True, "chromium_binary_present": False,
                "chromium_executable": None, "status": "Unable to inspect the Playwright driver: " + str(exc)[:300]}


def install_browser() -> int:
    """Own the installer child so cancelling the native helper cannot orphan it."""
    try:
        from playwright._impl._driver import compute_driver_executable, get_driver_env
    except ImportError as exc:
        raise RuntimeError("Capture support is missing. Install the capture extra or use a native bundle that includes it.") from exc
    import signal
    import subprocess
    driver, driver_cli = compute_driver_executable()
    child = None
    stop_signal = None
    cleaning = False
    previous_handlers = {}

    class InstallInterrupted(Exception):
        pass

    def interrupted(signum, _frame):
        nonlocal stop_signal
        if cleaning or stop_signal is not None:
            return
        stop_signal = signum
        # If a signal lands during Popen construction, remember it until the
        # returned child handle is assigned, so cleanup can still own the child.
        if child is not None:
            raise InstallInterrupted()

    if threading.current_thread() is threading.main_thread():
        for signum in (signal.SIGTERM, signal.SIGINT):
            previous_handlers[signum] = signal.signal(signum, interrupted)
    print("Downloading Playwright Chromium into its configured browser cache…", file=sys.stderr)
    try:
        if stop_signal is not None:
            raise InstallInterrupted()
        child = subprocess.Popen([driver, driver_cli, "install", "chromium"], env=get_driver_env(),
                                 start_new_session=(os.name != "nt"))
        if stop_signal is not None:
            raise InstallInterrupted()
        code = child.wait(timeout=900)
        if code:
            print("Chromium installation failed. Review the installer output and retry install-browser.", file=sys.stderr)
        return code
    except InstallInterrupted:
        print("Chromium installation cancelled.", file=sys.stderr)
        return 128 + (stop_signal or signal.SIGTERM)
    except subprocess.TimeoutExpired as exc:
        raise RuntimeError("Chromium installation exceeded 15 minutes; check connectivity and retry install-browser.") from exc
    finally:
        cleaning = True
        try:
            if child is not None and (stop_signal is not None or child.poll() is None):
                # On Unix the installer and its descendants own a new session.
                # Kill only that group, never the native app's process group.
                try:
                    if os.name != "nt":
                        os.killpg(child.pid, signal.SIGTERM)
                    else:
                        child.terminate()
                except (ProcessLookupError, OSError):
                    pass
                try:
                    child.wait(timeout=3)
                except subprocess.TimeoutExpired:
                    pass
                try:
                    if os.name != "nt":
                        # Also stop any descendants left after Node exits.
                        os.killpg(child.pid, signal.SIGKILL)
                    elif child.poll() is None:
                        child.kill()
                except (ProcessLookupError, OSError):
                    pass
                try:
                    child.wait(timeout=3)
                except subprocess.TimeoutExpired:
                    print("Could not confirm installer termination after the bounded cleanup timeout.", file=sys.stderr)
        finally:
            for signum, handler in previous_handlers.items():
                signal.signal(signum, handler)


def doctor(config) -> int:
    from .render import ffmpeg_path
    executable = ffmpeg_path()
    output = {
        "frameva": __version__, "python": platform.python_version(),
        "system": platform.system(), "machine": platform.machine(),
        "data_directory": str(config.data_dir), "ffmpeg_available": bool(executable),
        "ffmpeg": executable, "local_studio": "http://127.0.0.1:8741",
        "capture": capture_status(),
        "browser_flow_recording": "Optional capture extra and Playwright Chromium required; actual app must already be running.",
        "native_macos": "The macOS app is distributed separately; this Python package is its local worker.",
        "product_motion": "ready" if executable else "FFmpeg missing: reinstall imageio-ffmpeg or install FFmpeg",
        "ai_rendering": "Needs a separately installed ComfyUI renderer, model weights, and a compatible workflow.",
        "macos_windows": "Portable source and CI configuration included; this command is not proof of native OS or GPU validation.",
    }
    print(json.dumps(output, indent=2))
    return 0 if executable else 1


def _open_when_ready(base_url: str, token: str) -> None:
    import httpx
    # Avoid a misleading browser error page while uvicorn is starting.
    for _ in range(50):
        try:
            with httpx.Client(timeout=0.5, trust_env=False) as client:
                if client.get(base_url + "/api/health").is_success:
                    webbrowser.open(base_url + "/#token=" + quote(token, safe=""))
                    return
        except httpx.HTTPError:
            pass
        time.sleep(0.1)
    print("Could not open the studio automatically. Visit " + base_url + " and use `frameva token` to sign in.", file=sys.stderr)


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    if args.data_dir:
        os.environ["FRAMEVA_DATA_DIR"] = str(args.data_dir.expanduser().absolute())
    try:
        from .config import Config
        config = Config()
        if args.command == "token":
            print(config.token)
        elif args.command == "doctor":
            return doctor(config)
        elif args.command == "install-browser":
            return install_browser()
        elif args.command == "mcp-config":
            print_configuration(config.data_dir, args.url, args.format)
        elif args.command == "capture":
            from .capture import capture_screenshot
            print(json.dumps(capture_screenshot(args.url, args.output, width=args.width, height=args.height), indent=2))
        elif args.command == "record-flow":
            from .flow import record_flow
            plan_file = args.plan.expanduser()
            if not plan_file.is_file() or plan_file.stat().st_size > 1024 * 1024:
                raise ValueError("Choose a JSON flow plan no larger than 1 MiB")
            plan = json.loads(plan_file.read_text(encoding="utf-8"))
            if not isinstance(plan, dict):
                raise ValueError("Flow plan must be a JSON object")
            output = args.output.expanduser().absolute()
            if output.exists() or output.is_symlink():
                raise ValueError("Output already exists; choose a new .mp4 filename")
            last_progress = -10
            def progress(value):
                nonlocal last_progress
                value = int(value)
                if value >= last_progress + 10 or value == 100:
                    print(f"Recording: {value}%", file=sys.stderr)
                    last_progress = value
            result = record_flow(plan, output, progress=progress)
            print(json.dumps({"output": str(output), "report": result}, indent=2))
        elif args.command == "mcp":
            from .mcp_server import build_server
            build_server().run(transport="stdio")
        elif args.command == "serve":
            if not 1 <= args.port <= 65535:
                raise ValueError("Port must be between 1 and 65535")
            import uvicorn
            from .app import create_app
            host_for_url = "[::1]" if args.host == "::1" else args.host
            base_url = f"http://{host_for_url}:{args.port}"
            print(f"Frameva {__version__}: {base_url}", file=sys.stderr)
            print("Private local studio. Press Ctrl+C to stop.", file=sys.stderr)
            if not args.no_open:
                threading.Thread(target=_open_when_ready, args=(base_url, config.token), daemon=True).start()
            uvicorn.run(create_app(config), host=args.host, port=args.port, access_log=False, log_level="info")
        return 0
    except (ValueError, OSError, RuntimeError) as exc:
        print(f"Frameva: {exc}", file=sys.stderr)
        return 2
    except KeyboardInterrupt:
        return 130
