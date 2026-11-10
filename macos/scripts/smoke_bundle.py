#!/usr/bin/env python3
"""Real macOS packaging smoke checks; never asserts that screen capture was tested."""
import argparse
import asyncio
import json
import os
from pathlib import Path
import socket
import subprocess
import tempfile
import time
import urllib.request

async def check_mcp_stdio(helper, environment, working_directory, port):
    """Exercise the frozen MCP runtime, not merely its printed configuration."""
    from mcp import ClientSession, StdioServerParameters
    from mcp.client.stdio import stdio_client

    parameters = StdioServerParameters(
        command=str(helper),
        args=['mcp'],
        env={**environment, 'FRAMEVA_URL': f'http://127.0.0.1:{port}'},
        cwd=working_directory,
    )
    async with asyncio.timeout(20):
        async with stdio_client(parameters) as (reader, writer):
            async with ClientSession(reader, writer) as session:
                initialized = await session.initialize()
                if not initialized.serverInfo.name:
                    raise RuntimeError('Bundled MCP initialize returned no server identity.')
                tools = await session.list_tools()
                names = {tool.name for tool in tools.tools}
                required = {
                    'analyze_repository', 'create_flow', 'record_flow',
                    'create_recording_shot', 'get_project_coverage', 'export_video',
                }
                missing = required - names
                if missing:
                    raise RuntimeError('Bundled MCP tools missing: ' + ', '.join(sorted(missing)))
                # This read-only call confirms the bridge uses the same data dir,
                # shared token file, and live worker port as the native app.
                result = await session.call_tool('list_projects', {})
                if result.isError:
                    raise RuntimeError('Bundled MCP could not read its authenticated worker.')
                return len(names)


parser = argparse.ArgumentParser()
parser.add_argument('app', type=Path)
args = parser.parse_args()
helper = args.app.resolve() / 'Contents/Helpers/FramevaWorker.app/Contents/MacOS/frameva-worker'
if not helper.is_file():
    raise SystemExit('Bundled worker entry is missing.')
with tempfile.TemporaryDirectory(prefix='frameva-native-smoke-') as directory:
    env = {**os.environ, 'FRAMEVA_DATA_DIR': directory}
    env.pop('FRAMEVA_TOKEN', None)
    result = subprocess.run([str(helper), 'doctor'], env=env, capture_output=True, text=True, timeout=60)
    if result.returncode:
        raise SystemExit('Bundled doctor failed: ' + result.stderr[-2000:])
    data = json.loads(result.stdout)
    if not data.get('ffmpeg_available'):
        raise SystemExit('Bundled FFmpeg is missing.')
    if not data.get('capture', {}).get('dependency_installed'):
        raise SystemExit('Bundled Playwright dependency/driver is missing.')
    config = subprocess.run([str(helper), 'mcp-config', '--format', 'json'], env=env, capture_output=True, text=True, check=True, timeout=60)
    entry = json.loads(config.stdout)['mcpServers']['frameva']
    if entry['args'] != ['mcp']:
        raise SystemExit('Frozen MCP configuration is not using the bundled helper.')
    with socket.socket() as listener:
        listener.bind(('127.0.0.1', 0)); port = listener.getsockname()[1]
    with (Path(directory) / 'worker.log').open('wb') as log:
        worker = subprocess.Popen([str(helper), 'serve', '--no-open', '--port', str(port)], env=env, stdout=log, stderr=log)
        try:
            token = (Path(directory) / 'token').read_text().strip()
            request = urllib.request.Request(f'http://127.0.0.1:{port}/api/config', headers={'Authorization': 'Bearer ' + token})
            for _ in range(100):
                if worker.poll() is not None:
                    raise SystemExit('Bundled worker exited before startup.')
                try:
                    with urllib.request.urlopen(request, timeout=1) as response:
                        metadata = json.load(response)
                    if metadata.get('version', '').startswith('0.2.'):
                        break
                except OSError:
                    pass
                time.sleep(.15)
            else:
                raise SystemExit('Bundled worker failed authenticated readiness.')
            tool_count = asyncio.run(check_mcp_stdio(helper, env, directory, port))
            print(f'PASS: frozen MCP initialize, {tool_count} tools, and authenticated list_projects call.')
        finally:
            worker.terminate()
            try: worker.wait(timeout=50)
            except subprocess.TimeoutExpired:
                worker.kill(); worker.wait(timeout=5)
print('PASS: bundled worker, FFmpeg, Playwright dependency, frozen MCP config/stdio, and authenticated API startup.')
print('Not tested here: native permission UI, actual window capture, microphone, or Mac video playback.')
