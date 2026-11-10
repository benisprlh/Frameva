#!/usr/bin/env python3
"""Smoke-test a wheel in a fresh venv, outside the source checkout.

This installs normal dependencies; internet access or a populated pip cache is
required. It works on Windows, macOS and Linux and never installs globally.
"""
from __future__ import annotations
import argparse
from pathlib import Path
import subprocess
import tempfile
import os
import venv


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("wheel", type=Path, help="Built frameva_studio wheel")
    args = parser.parse_args()
    wheel = args.wheel.resolve(strict=True)
    with tempfile.TemporaryDirectory(prefix="frameva-wheel-test-") as tmp:
        root = Path(tmp)
        environment = root / "venv"
        venv.EnvBuilder(with_pip=True).create(environment)
        python = environment / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
        subprocess.run([str(python), "-m", "pip", "install", "--disable-pip-version-check", str(wheel)], check=True, cwd=root)
        subprocess.run([str(python), "-m", "pip", "check"], check=True, cwd=root)
        smoke = r'''
from pathlib import Path
import importlib.metadata as metadata
import importlib.resources as resources
import json
import tempfile
import subprocess
from unittest.mock import patch
import frameva
from frameva.app import create_app
from frameva.config import Config
from frameva.render import ffmpeg_path
from fastapi.testclient import TestClient
with tempfile.TemporaryDirectory() as state:
    app = create_app(Config(Path(state)))
    with TestClient(app, base_url="http://127.0.0.1") as client:
        assert client.get("/api/health").status_code == 200
        index = client.get("/")
        assert index.status_code == 200 and "Frameva" in index.text
assert resources.files("frameva").joinpath("static/index.html").is_file()
with patch("frameva.render.shutil.which", return_value=None):
    bundled = ffmpeg_path()
    assert bundled, "FFmpeg fallback missing from a fresh installation"
    subprocess.run([bundled, "-version"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=True, timeout=10)
print(json.dumps({"wheel_smoke": "passed", "import_path": frameva.__file__, "version": frameva.__version__,
    "dependencies": {name: metadata.version(name) for name in ["fastapi", "uvicorn", "pydantic", "httpx", "Pillow", "python-multipart", "imageio-ffmpeg", "mcp"]}}, indent=2))
'''
        subprocess.run([str(python), "-c", smoke], check=True, cwd=root,
                       env={**os.environ, "FRAMEVA_DATA_DIR": str(root / "data"), "PYTHONPATH": ""})
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
