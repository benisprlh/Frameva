#!/usr/bin/env python3
"""Sign nested Mach-O code and bundles inside-out, never with --deep --sign."""
import argparse
from pathlib import Path
import struct
import subprocess
import sys

MAGIC = {b'\xcf\xfa\xed\xfe', b'\xfe\xed\xfa\xcf', b'\xce\xfa\xed\xfe', b'\xfe\xed\xfa\xce', b'\xca\xfe\xba\xbe', b'\xbe\xba\xfe\xca', b'\xca\xfe\xba\xbf'}

def macho(path):
    try:
        with path.open('rb') as stream:
            header = stream.read(32)
        return len(header) >= 16 and header[:4] in MAGIC
    except OSError:
        return False

def executable(path):
    # Entry points and bundled Node/ffmpeg are executable code. Shared libraries
    # are signed without process entitlements, even if their filesystem mode is +x.
    return path.name in {'Frameva', 'frameva-worker', 'node'} or path.name.startswith('ffmpeg-')

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('app', type=Path)
    parser.add_argument('--identity', required=True)
    args = parser.parse_args()
    app = args.app.resolve()
    if sys.platform != 'darwin' or app.suffix != '.app' or not app.is_dir():
        parser.error('Choose an existing .app on macOS.')
    entitlement_dir = Path(__file__).resolve().parents[1]
    def sign(path, entitlement=None):
        command = ['codesign', '--force', '--sign', args.identity]
        if args.identity != '-':
            command += ['--options', 'runtime', '--timestamp']
        if entitlement:
            command += ['--entitlements', str(entitlement)]
        subprocess.run(command + [str(path)], check=True)
    files = sorted((p for p in app.rglob('*') if not p.is_symlink() and p.is_file() and macho(p)), key=lambda p: len(p.parts), reverse=True)
    for path in files:
        entitlement = None
        if executable(path):
            entitlement = entitlement_dir / ('Frameva.entitlements' if path.name == 'Frameva' else 'Worker.entitlements')
        sign(path, entitlement)
    bundles = sorted((p for p in app.rglob('*') if not p.is_symlink() and p.is_dir() and p.suffix in {'.app', '.framework', '.xpc', '.bundle'}), key=lambda p: len(p.parts), reverse=True)
    for bundle in bundles:
        sign(bundle, entitlement_dir / 'Worker.entitlements' if bundle.name == 'FramevaWorker.app' else None)
    sign(app, entitlement_dir / 'Frameva.entitlements')

if __name__ == '__main__':
    main()
