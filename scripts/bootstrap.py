#!/usr/bin/env python3
"""Create an isolated Frameva environment, then launch it on Windows/macOS/Linux."""
from __future__ import annotations
import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import venv


def main() -> int:
    parser = argparse.ArgumentParser(description="Set up and start Frameva")
    parser.add_argument("--reinstall", action="store_true", help="Reinstall dependencies")
    parser.add_argument("--doctor", action="store_true", help="Check prerequisites instead of opening the studio")
    parser.add_argument("--no-open", action="store_true")
    args = parser.parse_args()
    if not (3, 11) <= sys.version_info[:2] < (3, 14):
        print("Frameva needs Python 3.11, 3.12, or 3.13. Install one from https://www.python.org/downloads/", file=sys.stderr)
        return 2
    root = Path(__file__).resolve().parent.parent
    environment = root / ".venv"
    python = environment / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
    stamp = environment / ".frameva-install.json"
    fingerprint = hashlib.sha256((root / "pyproject.toml").read_bytes()).hexdigest()
    if not python.is_file():
        print("Creating Frameva's isolated Python environment…", flush=True)
        venv.EnvBuilder(with_pip=True).create(environment)
    installed = {}
    try:
        installed = json.loads(stamp.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        pass
    if args.reinstall or installed.get("pyproject") != fingerprint or installed.get("root") != str(root):
        print("Installing Frameva and its dependencies. This first setup needs internet access…", flush=True)
        subprocess.run([str(python), "-m", "pip", "install", "--disable-pip-version-check", "-e", str(root)],
                       check=True, cwd=root)
        stamp.write_text(json.dumps({"pyproject": fingerprint, "root": str(root)}), encoding="utf-8")
    command = [str(python), "-m", "frameva", "doctor" if args.doctor else "serve"]
    if args.no_open and not args.doctor:
        command.append("--no-open")
    return subprocess.call(command, cwd=root)


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except KeyboardInterrupt:
        raise SystemExit(130)
    except (OSError, subprocess.CalledProcessError) as error:
        print(f"Frameva setup failed: {error}\nFix the error above and run this launcher again; your projects are retained.", file=sys.stderr)
        raise SystemExit(1)
