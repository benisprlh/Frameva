# Portable worker and Windows setup

For the native macOS15+ SwiftUI application, use [macos/README.md](../macos/README.md).
The instructions below start the portable local Python worker and legacy web
studio. Recording composition renders on the CPU; no AI accelerator is required.
GPU requirements apply only to optional generated b-roll.

## macOS portable worker

Use an installed Python 3.11, 3.12, or 3.13. Check `python3 --version`; Apple's
system Python may be older. Run from the extracted Frameva directory:

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -e .
.venv/bin/python -m frameva doctor
.venv/bin/python -m frameva serve
```

This application uses no CUDA imports, Linux-only file locks, shell rendering, or
hardcoded Windows paths. Apple Silicon and Intel application support is a source
compatibility target; actual hardware validation is recorded separately.

## Windows

Install Python 3.12 from python.org. Keep the Python Launcher enabled. In
PowerShell, from the extracted Frameva directory:

```powershell
py -3.12 -m venv .venv
.venv\Scripts\python.exe -m pip install -e .
.venv\Scripts\python.exe -m frameva doctor
.venv\Scripts\python.exe -m frameva serve
```

No PowerShell activation script or execution-policy change is needed. Paths may
contain spaces; keep quotes around manually supplied paths. Windows x64 is the
initial CI target. Availability of native dependency wheels on Windows ARM64
must be checked on the target system.

## Optional live browser flows and screenshots

Install the capture extra in the same environment:

```bash
python -m pip install -e '.[capture]'
python -m frameva install-browser
python -m frameva record-flow plan.json --output walkthrough.mp4
python -m frameva capture --url http://localhost:3000 --output app-screen.png
```

Use `.venv/bin/python` on Mac or `.venv\Scripts\python.exe` on Windows instead of
`python` if your environment is not activated. The URL must already be running;
Frameva does not execute arbitrary repository start scripts. A clean browser has
no saved login. Use an explicit demo sign-in flow or native manual capture for
authenticated apps. [LIVE_FLOWS.md](LIVE_FLOWS.md) describes the plan format and
the complete runnable example. Inspect recordings before publishing them.

## Optional AI video with ComfyUI

1. Install ComfyUI on a machine appropriate for the selected model. Start it and
   confirm its own example workflow can generate a video.
2. In Frameva Settings, set the renderer base URL (normally
   `http://127.0.0.1:8188`). For a remote GPU, use an authenticated tunnel or a
   trusted private network; Frameva itself remains bound to loopback.
3. Import an API-format workflow and map the prompt, frame count, dimensions,
   seed, and optional image inputs. See [workflow setup](WORKFLOWS.md).
4. Select that workflow for a shot, generate, inspect the clip, then export it
   alongside Product motion shots.

ComfyUI being installable on a Mac does not establish that every Wan/LTX workflow
will run on MPS. Windows NVIDIA or a remote CUDA renderer is the more predictable
route for those workflows. No model weights are downloaded automatically.

## Troubleshooting

| Symptom | Action |
|---|---|
| Python version rejected | Use Python 3.12; bootstrap supports 3.11–3.13 |
| First launch cannot install | Check internet/proxy, then rerun the bootstrap; your saved projects are separate |
| Browser asks for a token | Run `python -m frameva token` in the same environment and data directory |
| Port 8741 is occupied | Run `python -m frameva serve --port 8742`; regenerate MCP config with `--url http://127.0.0.1:8742` |
| FFmpeg unavailable | Reinstall `imageio-ffmpeg` or install FFmpeg; `FRAMEVA_FFMPEG` may point to its executable |
| Capture says browser missing | Run `python -m frameva install-browser` in the same environment, or use the native helper command |
| Screenshot shows login | Capture uses a clean session. Upload an authenticated screenshot manually |
| ComfyUI job fails | Run the workflow directly in ComfyUI first; check model filenames, installed nodes, VRAM and node-error message |
| MCP cannot connect | Keep Frameva running; verify Python path, `FRAMEVA_DATA_DIR`, `FRAMEVA_URL` and `codex mcp list` / `claude mcp list` |

Back up the entire data directory while the application is stopped. Replacing
the source directory does not erase your projects. Do not copy the token into
source control, shared MCP JSON, or a public support report.
