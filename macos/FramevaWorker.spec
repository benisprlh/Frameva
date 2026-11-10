# PyInstaller specification for a nested, architecture-native macOS helper bundle.
from pathlib import Path
import importlib.util
from PyInstaller.utils.hooks import collect_all, collect_submodules

root = Path(SPECPATH).parent
macos = root / "macos"
datas, binaries, hiddenimports = [], [], []
for package in ("frameva", "imageio_ffmpeg", "playwright", "mcp"):
    package_data, package_binaries, package_hidden = collect_all(package)
    datas.extend(package_data); binaries.extend(package_binaries); hiddenimports.extend(package_hidden)
for package in ("uvicorn", "fastapi", "starlette", "pydantic", "pydantic_core", "httpx", "PIL", "multipart"):
    hiddenimports.extend(collect_submodules(package))

# Executables without .dylib/.so suffixes must be classified as code, not DATA.
# PyInstaller BUNDLE then places code correctly and creates resource symlinks.
def package_dir(name):
    return Path(importlib.util.find_spec(name).origin).parent

explicit_code = []
ffmpeg_dir = package_dir("imageio_ffmpeg") / "binaries"
for binary in ffmpeg_dir.glob("ffmpeg-*"):
    if not binary.is_file():
        continue
    with binary.open("rb") as stream:
        magic = stream.read(4)
    if magic in (b"\xcf\xfa\xed\xfe", b"\xfe\xed\xfa\xcf", b"\xca\xfe\xba\xbe", b"\xbe\xba\xfe\xca"):
        explicit_code.append((str(binary), "imageio_ffmpeg/binaries"))
node = package_dir("playwright") / "driver" / "node"
if not node.is_file():
    raise RuntimeError("Playwright's bundled Node driver is missing; install .[capture].")
explicit_code.append((str(node), "playwright/driver"))
if not any(destination == "imageio_ffmpeg/binaries" for _, destination in explicit_code):
    raise RuntimeError("No macOS ffmpeg binary found in imageio-ffmpeg. Build with the correct architecture wheel.")
code_sources = {str(Path(source).resolve()) for source, _ in explicit_code}
datas = [(source, target) for source, target in datas if str(Path(source).resolve()) not in code_sources]
binaries.extend(explicit_code)

a = Analysis([str(macos / "worker_entry.py")], pathex=[str(root)], binaries=binaries,
             datas=datas, hiddenimports=sorted(set(hiddenimports)), hookspath=[],
             runtime_hooks=[], excludes=["tkinter", "matplotlib", "pytest"], noarchive=False)
pyz = PYZ(a.pure)
exe = EXE(pyz, a.scripts, [], exclude_binaries=True, name="frameva-worker", debug=False,
          bootloader_ignore_signals=False, strip=False, upx=False, console=True,
          disable_windowed_traceback=True, argv_emulation=False, target_arch=None,
          codesign_identity=None, entitlements_file=None)
collection = COLLECT(exe, a.binaries, a.datas, strip=False, upx=False, name="frameva-worker")
app = BUNDLE(collection, name="FramevaWorker.app", icon=None, bundle_identifier="dev.frameva.studio.worker",
             info_plist={"CFBundleName": "Frameva Worker", "LSUIElement": True,
                         "LSMinimumSystemVersion": "15.0", "NSHighResolutionCapable": True})
