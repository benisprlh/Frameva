"""Live-flow tools and frozen-worker CLI boundaries, without launching browsers."""
from contextlib import redirect_stdout, redirect_stderr
import io
import json
import os
from pathlib import Path
import sys
import tempfile
import types
import unittest
from unittest.mock import Mock, patch

import httpx

from frameva.cli import configuration, capture_status, install_browser, main
from frameva.mcp_server import APIClient, build_server


class FlowToolTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.calls = []
        def handler(request):
            self.calls.append((request.method, request.url.path, json.loads(request.content) if request.content else None))
            if request.url.path.endswith('/record'):
                return httpx.Response(202, json={'id': 'record-job', 'status': 'queued', 'type': 'record'})
            if request.method == 'GET' and request.url.path.endswith('/flows'):
                return httpx.Response(200, json=[])
            if request.method == 'DELETE':
                return httpx.Response(204)
            return httpx.Response(200, json={'id': 'result-1'})
        self.server = build_server(APIClient('test-token', transport=httpx.MockTransport(handler)))

    async def test_flow_crud_and_record_are_distinct_api_actions(self):
        plan = {'name': 'Review an item', 'base_url': 'http://127.0.0.1:3000',
                'feature_titles': ['Review inbox'], 'steps': [{'action': 'goto', 'url': '/'}]}
        await self.server.call_tool('list_flows', {'project_id': 'project-1'})
        await self.server.call_tool('create_flow', {'project_id': 'project-1', 'plan': plan})
        await self.server.call_tool('update_flow', {'flow_id': 'flow-1', 'plan': plan})
        await self.server.call_tool('record_flow', {'flow_id': 'flow-1'})
        await self.server.call_tool('get_project_coverage', {'project_id': 'project-1'})
        await self.server.call_tool('delete_flow', {'flow_id': 'flow-1'})
        self.assertEqual([(method, path) for method, path, _ in self.calls], [
            ('GET', '/api/projects/project-1/flows'), ('POST', '/api/projects/project-1/flows'),
            ('PUT', '/api/flows/flow-1'), ('POST', '/api/flows/flow-1/record'),
            ('GET', '/api/projects/project-1/coverage'), ('DELETE', '/api/flows/flow-1')])
        self.assertEqual(self.calls[1][2]['feature_titles'], ['Review inbox'])
        tools = {tool.name: tool for tool in await self.server.list_tools()}
        self.assertTrue(tools['record_flow'].annotations.openWorldHint)
        self.assertTrue(tools['record_flow'].annotations.destructiveHint)
        self.assertTrue(tools['delete_flow'].annotations.destructiveHint)
        self.assertTrue(tools['get_project_coverage'].annotations.readOnlyHint)

    async def test_recording_shot_keeps_real_video_controls(self):
        await self.server.call_tool('create_recording_shot', {'project_id': 'project-1', 'video_asset_id': 'asset-1',
            'name': 'Live review', 'duration': 4, 'trim_start': 2, 'playback_rate': 1.5,
            'focus_x': .7, 'focus_y': .3, 'zoom': 1.4, 'keep_audio': True})
        body = self.calls[0][2]
        self.assertEqual(body['provider'], 'recording')
        self.assertEqual(body['video_asset_id'], 'asset-1')
        self.assertEqual(body['trim_start'], 2)
        self.assertEqual(body['playback_rate'], 1.5)
        self.assertEqual(body['zoom'], 1.4)
        self.assertTrue(body['keep_audio'])
        self.assertNotIn('reference_asset_id', body)

    async def test_export_preserves_old_arguments_and_adds_transition_controls(self):
        await self.server.call_tool('export_video', {'project_id': 'project-1'})
        await self.server.call_tool('export_video', {'project_id': 'project-1', 'transition': 'cut', 'transition_duration': 0})
        self.assertEqual(self.calls[0][2]['transition'], 'crossfade')
        self.assertEqual(self.calls[1][2]['transition'], 'cut')
        self.assertEqual(self.calls[1][2]['transition_duration'], 0)


class FrozenAndCaptureCLITests(unittest.TestCase):
    def test_frozen_worker_configuration_invokes_mcp_without_python_module_flags(self):
        with tempfile.TemporaryDirectory() as tmp, patch.object(sys, 'frozen', True, create=True), patch.object(sys, 'executable', '/Applications/Frameva.app/Contents/Helpers/FramevaWorker.app/Contents/MacOS/frameva-worker'):
            conf = configuration(Path(tmp), 'http://127.0.0.1:8741')
        self.assertEqual(conf['args'], ['mcp'])
        self.assertTrue(conf['command'].endswith('frameva-worker'))
        self.assertNotIn('FRAMEVA_TOKEN', conf['env'])

    def test_cli_record_plan_uses_continuous_recorder_and_reports_actual_result(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            plan = {'name': 'Live demo', 'base_url': 'http://127.0.0.1:3000', 'steps': [{'action': 'wait', 'seconds': 1}]}
            plan_file = root / 'flow.json'
            plan_file.write_text(json.dumps(plan), encoding='utf-8')
            recorder = Mock(return_value={'status': 'completed', 'recording_kind': 'browser-flow', 'duration': 1})
            fake = types.ModuleType('frameva.flow'); fake.record_flow = recorder
            stdout = io.StringIO()
            with patch.dict(sys.modules, {'frameva.flow': fake}), redirect_stdout(stdout):
                code = main(['--data-dir', str(root / 'state'), 'record-flow', str(plan_file), '--output', str(root / 'demo.mp4')])
            self.assertEqual(code, 0)
            recorder.assert_called_once()
            self.assertEqual(recorder.call_args.args[0], plan)
            self.assertEqual(json.loads(stdout.getvalue())['report']['recording_kind'], 'browser-flow')
            target = root / 'existing.mp4'; target.write_bytes(b'existing')
            with patch.dict(sys.modules, {'frameva.flow': fake}), redirect_stderr(io.StringIO()):
                code = main(['--data-dir', str(root / 'state'), 'record-flow', str(plan_file), '--output', str(target)])
            self.assertEqual(code, 2)
            self.assertEqual(recorder.call_count, 1)
            self.assertEqual(target.read_bytes(), b'existing')

    def test_install_browser_uses_official_driver_not_frozen_executable(self):
        driver = types.ModuleType('playwright._impl._driver')
        driver.compute_driver_executable = lambda: ('/bundle/node', '/bundle/package/cli.js')
        driver.get_driver_env = lambda: {'TEST_DRIVER_ENV': '1'}
        import signal
        previous = {sig: signal.getsignal(sig) for sig in (signal.SIGINT, signal.SIGTERM)}
        process = Mock(); process.wait.return_value = 0; process.poll.return_value = 0
        with patch.dict(sys.modules, {'playwright._impl._driver': driver}), patch('subprocess.Popen', return_value=process) as run, redirect_stderr(io.StringIO()), patch.object(sys, 'frozen', True, create=True):
            self.assertEqual(install_browser(), 0)
        self.assertEqual(run.call_args.args[0], ['/bundle/node', '/bundle/package/cli.js', 'install', 'chromium'])
        self.assertEqual(run.call_args.kwargs['env'], {'TEST_DRIVER_ENV': '1'})
        self.assertNotIn(sys.executable, run.call_args.args[0])
        self.assertEqual(previous, {sig: signal.getsignal(sig) for sig in previous})
        process.terminate.assert_not_called()

    def test_installer_timeout_stops_child_and_restores_signal_handlers(self):
        import signal
        import subprocess
        previous = {sig: signal.getsignal(sig) for sig in (signal.SIGINT, signal.SIGTERM)}
        driver = types.ModuleType('playwright._impl._driver')
        driver.compute_driver_executable = lambda: ('fake-node', 'fake-cli')
        driver.get_driver_env = lambda: {}
        process = Mock(pid=12345)
        process.poll.return_value = None
        process.wait.side_effect = [subprocess.TimeoutExpired('fake-node', 900), 0, 0]
        with patch.dict(sys.modules, {'playwright._impl._driver': driver}), patch('subprocess.Popen', return_value=process), patch('os.killpg', create=True) as kill_group, redirect_stderr(io.StringIO()):
            with self.assertRaisesRegex(RuntimeError, '15 minutes'):
                install_browser()
        self.assertEqual(previous, {sig: signal.getsignal(sig) for sig in previous})
        if os.name != 'nt':
            self.assertEqual([call.args for call in kill_group.call_args_list], [(12345, signal.SIGTERM), (12345, signal.SIGKILL)])
        else:
            process.terminate.assert_called_once()
            process.kill.assert_called_once()
        self.assertEqual(process.wait.call_args.kwargs['timeout'], 3)

    @unittest.skipIf(os.name == 'nt', 'Native macOS quit uses Unix SIGTERM/process groups')
    def test_sigterm_native_helper_stops_installer_and_descendant(self):
        """Real processes, fake installer: no browser launch or network install."""
        import signal
        import subprocess
        import time
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            fake = root / 'fake_installer.py'
            pidfile = root / 'pids.json'
            ready = root / 'child-ready'
            fake.write_text(
                "import json, os, subprocess, sys, time\n"
                "from pathlib import Path\n"
                "code = \"import os, signal, time; from pathlib import Path; signal.signal(signal.SIGTERM, signal.SIG_IGN); Path(os.environ['CHILD_READY']).write_text('ready'); time.sleep(60)\"\n"
                "child = subprocess.Popen([sys.executable, '-c', code])\n"
                "while not Path(os.environ['CHILD_READY']).exists(): time.sleep(.01)\n"
                "Path(os.environ['INSTALLER_PIDS']).write_text(json.dumps({'node': os.getpid(), 'child': child.pid}))\n"
                "time.sleep(60)\n", encoding='utf-8')
            launcher = (
                "import os, sys, types; from frameva.cli import install_browser; "
                "driver=types.ModuleType('playwright._impl._driver'); "
                "driver.compute_driver_executable=lambda:(sys.executable, os.environ['FAKE_INSTALLER']); "
                "driver.get_driver_env=lambda:dict(os.environ); "
                "sys.modules['playwright._impl._driver']=driver; raise SystemExit(install_browser())"
            )
            helper = subprocess.Popen([sys.executable, '-c', launcher],
                cwd=str(Path(__file__).resolve().parents[1]), stdout=subprocess.DEVNULL, stderr=subprocess.PIPE,
                env={**os.environ, 'FAKE_INSTALLER': str(fake), 'INSTALLER_PIDS': str(pidfile), 'CHILD_READY': str(ready)})
            pids = None
            try:
                deadline = time.monotonic() + 8
                while not pidfile.exists() and helper.poll() is None and time.monotonic() < deadline:
                    time.sleep(.02)
                self.assertTrue(pidfile.exists(), 'Fake installer did not initialize')
                pids = json.loads(pidfile.read_text())
                helper.terminate()  # Same SIGTERM sent by native Process.terminate().
                self.assertEqual(helper.wait(timeout=8), 128 + signal.SIGTERM)
                for pid in pids.values():
                    state = subprocess.run(['ps', '-p', str(pid), '-o', 'stat='], capture_output=True, text=True, timeout=2).stdout.strip()
                    self.assertTrue(not state or state.startswith('Z'), f'Installer process {pid} still live: {state}')
            finally:
                if helper.poll() is None:
                    helper.kill(); helper.wait(timeout=3)
                if helper.stderr:
                    helper.stderr.close()
                if pids:
                    try:
                        os.killpg(pids['node'], signal.SIGKILL)
                    except ProcessLookupError:
                        pass

    def test_capture_status_checks_binary_without_launching_browser(self):
        with tempfile.TemporaryDirectory() as tmp:
            browser_path = Path(tmp) / 'chromium'; browser_path.write_bytes(b'placeholder-binary')
            manager = Mock()
            manager.__enter__ = Mock(return_value=types.SimpleNamespace(chromium=types.SimpleNamespace(executable_path=str(browser_path))))
            manager.__exit__ = Mock(return_value=False)
            module = types.ModuleType('playwright.sync_api'); module.sync_playwright = Mock(return_value=manager)
            with patch.dict(sys.modules, {'playwright.sync_api': module}):
                status = capture_status()
            self.assertTrue(status['dependency_installed'])
            self.assertTrue(status['chromium_binary_present'])
            self.assertIn('not verified', status['status'])
