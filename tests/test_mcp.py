"""Protocol, authentication boundary, and portable configuration regression tests."""
from __future__ import annotations
import asyncio
from contextlib import redirect_stdout
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import io
import json
import os
from pathlib import Path
import sys
import tempfile
import threading
import tomllib
import unittest
from unittest.mock import patch

import httpx
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

from frameva.cli import configuration, print_configuration, _parser, _command_quote
from frameva.mcp_server import APIClient, build_server, validate_local_url


class ClientBoundaryTests(unittest.TestCase):
    def test_only_loopback_origins_receive_tokens(self):
        for bad in ["https://example.com", "http://127.0.0.1.evil.test", "file:///tmp/foo",
                    "http://user:password@localhost:8741", "http://localhost:8741/api",
                    "http://localhost:8741/?x=1", "http://localhost:8741/#x"]:
            with self.subTest(url=bad), self.assertRaises(ValueError):
                validate_local_url(bad)
        self.assertEqual(validate_local_url("http://127.0.0.1:8741/"), "http://127.0.0.1:8741")
        self.assertEqual(validate_local_url("http://[::1]:8741"), "http://[::1]:8741")

    def test_redirect_does_not_forward_token(self):
        seen = []
        def handle(request):
            seen.append(str(request.url))
            return httpx.Response(302, headers={"location": "https://attacker.invalid/"})
        api = APIClient("secret-local-token", transport=httpx.MockTransport(handle))
        with self.assertRaisesRegex(ValueError, "302"):
            api.request("GET", "/api/projects")
        self.assertEqual(len(seen), 1)

    def test_http_calls_authenticate_and_preserve_payload(self):
        def handle(request):
            self.assertEqual(request.headers["authorization"], "Bearer test-token")
            self.assertEqual(request.url.path, "/api/projects")
            self.assertEqual(json.loads(request.content), {"name": "Launch"})
            return httpx.Response(201, json={"id": "project-1", "name": "Launch"})
        api = APIClient("test-token", transport=httpx.MockTransport(handle))
        self.assertEqual(api.request("POST", "/api/projects", json={"name": "Launch"})["id"], "project-1")

    def test_unavailable_studio_has_actionable_error(self):
        def handle(request):
            raise httpx.ConnectError("refused")
        api = APIClient("test-token", transport=httpx.MockTransport(handle))
        with self.assertRaisesRegex(ValueError, "frameva serve"):
            api.request("GET", "/api/projects")

    def test_download_writes_asset_and_refuses_overwrite(self):
        payload = b"video-output-test-bytes"
        def handle(request):
            self.assertEqual(request.headers["authorization"], "Bearer test-token")
            self.assertEqual(request.url.path, "/api/assets/asset-1/file")
            return httpx.Response(200, content=payload)
        api = APIClient("test-token", transport=httpx.MockTransport(handle))
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "launch.mp4"
            self.assertEqual(api.download("asset-1", target)["size_bytes"], len(payload))
            self.assertEqual(target.read_bytes(), payload)
            with self.assertRaisesRegex(ValueError, "already exists"):
                api.download("asset-1", target)

    def test_upload_rejects_nonmedia_and_symlink(self):
        api = APIClient("test-token")
        with tempfile.TemporaryDirectory() as tmp:
            secret = Path(tmp) / ".env"
            secret.write_text("secret", encoding="utf-8")
            with self.assertRaises(ValueError):
                api.upload(secret, "project-1")
            if os.name != "nt":
                link = Path(tmp) / "image.png"
                link.symlink_to(secret)
                with self.assertRaisesRegex(ValueError, "symbolic"):
                    api.upload(link, "project-1")


class MCPToolTests(unittest.IsolatedAsyncioTestCase):
    async def test_tools_have_real_schemas_and_read_write_hints(self):
        server = build_server(APIClient("test-token", transport=httpx.MockTransport(lambda req: httpx.Response(200, json=[]))))
        tools = {t.name: t for t in await server.list_tools()}
        self.assertGreaterEqual(len(tools), 20)
        self.assertTrue(tools["analyze_repository"].annotations.readOnlyHint)
        self.assertFalse(tools["generate_project"].annotations.readOnlyHint)
        self.assertIn("repository_path", tools["create_launch_project"].inputSchema["properties"])
        self.assertIn("width", tools["capture_app_screenshot"].inputSchema["properties"])
        result = await server.call_tool("list_projects", {})
        self.assertIsNotNone(result)

    async def test_tool_validates_ids_before_network(self):
        seen = []
        def handle(request):
            seen.append(request)
            return httpx.Response(200, json={})
        server = build_server(APIClient("test-token", transport=httpx.MockTransport(handle)))
        with self.assertRaises(Exception):
            await server.call_tool("get_job", {"job_id": "../../config"})
        self.assertEqual(seen, [])

    async def test_launch_project_uses_actual_source_evidence(self):
        requests = []
        def handle(request):
            requests.append((request.url.path, json.loads(request.content)))
            if request.url.path == "/api/projects":
                return httpx.Response(201, json={"id": "launch-1", "name": "Sample"})
            return httpx.Response(200, json={"ok": True})
        server = build_server(APIClient("test-token", transport=httpx.MockTransport(handle)))
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp)
            (p / "package.json").write_text(json.dumps({"name": "sample-app", "dependencies": {"react": "19.0"}}))
            (p / "README.md").write_text("# Sample\nA task manager.\n\n## Features\n- Manage tasks\n")
            await server.call_tool("create_launch_project", {"repository_path": tmp, "name": "Sample"})
        self.assertEqual([r[0] for r in requests], ["/api/projects", "/api/projects/launch-1/source-analysis", "/api/projects/launch-1/launch-plan"])
        self.assertIn("analysis", requests[1][1])
        self.assertEqual(requests[2][1]["replace_existing"], False)


class ConfigurationTests(unittest.TestCase):
    def test_configs_are_parseable_absolute_and_contain_no_token(self):
        with tempfile.TemporaryDirectory(prefix="frameva space ") as tmp:
            conf = configuration(Path(tmp), "http://127.0.0.1:9123")
            self.assertTrue(Path(conf["command"]).is_absolute())
            self.assertNotIn("FRAMEVA_TOKEN", conf["env"])
            for kind in ["json", "toml"]:
                out = io.StringIO()
                with redirect_stdout(out):
                    print_configuration(Path(tmp), "http://127.0.0.1:9123", kind)
                parsed = json.loads(out.getvalue()) if kind == "json" else tomllib.loads(out.getvalue())
                group = "mcpServers" if kind == "json" else "mcp_servers"
                self.assertEqual(parsed[group]["frameva"]["args"], ["-I", "-m", "frameva", "mcp"])
                self.assertEqual(parsed[group]["frameva"]["env"]["FRAMEVA_URL"], "http://127.0.0.1:9123")

    def test_windows_registration_commands_quote_all_powershell_metacharacters(self):
        # The generated command is intended for copy-paste; punctuation in a
        # Windows username must remain literal, including a single quote.
        parts = ["codex", "mcp", "add", "frameva", "--", r"C:\Users\A&B; O'Brien (work)\python.exe", "-m", "frameva", "mcp"]
        with patch("frameva.cli.os.name", "nt"):
            command = _command_quote(parts)
        self.assertTrue(command.startswith("& 'codex' 'mcp' 'add' 'frameva' '--' "))
        self.assertIn("'C:\\Users\\A&B; O''Brien (work)\\python.exe'", command)
        self.assertTrue(command.endswith("'-m' 'frameva' 'mcp'"))
        # Parse the limited grammar this formatter emits: a call operator,
        # then single-quoted literal arguments with doubled quote escaping.
        import re
        tokens = re.findall(r"'((?:[^']|'')*)'(?: |$)", command[2:])
        self.assertEqual([token.replace("''", "'") for token in tokens], parts)

    def test_serve_rejects_nonloopback_binding(self):
        with redirect_stdout(io.StringIO()), patch("sys.stderr", new_callable=io.StringIO):
            with self.assertRaises(SystemExit):
                _parser().parse_args(["serve", "--host", "0.0.0.0"])


class ProtocolTests(unittest.IsolatedAsyncioTestCase):
    async def test_generated_config_isolates_cwd_namespace_and_pythonpath(self):
        """Launch the generated command from a colliding repository parent."""
        import importlib.metadata
        try:
            importlib.metadata.distribution("frameva-studio")
        except importlib.metadata.PackageNotFoundError:
            self.skipTest("Requires installed Frameva; CI and the clean verification venv install the package")
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            cwd = root / "repository-parent"
            # Matches a checkout named frameva: a namespace directory containing
            # code, rather than the actual installed top-level Python package.
            (cwd / "frameva").mkdir(parents=True)
            (cwd / "frameva" / "__main__.py").write_text("raise RuntimeError('cwd package shadowed installed Frameva')", encoding="utf-8")
            poison = root / "pythonpath"
            (poison / "frameva").mkdir(parents=True)
            (poison / "frameva" / "__init__.py").write_text("raise RuntimeError('PYTHONPATH shadowed installed Frameva')", encoding="utf-8")
            conf = configuration(root / "state", "http://127.0.0.1:8741")
            self.assertEqual(conf["args"], ["-I", "-m", "frameva", "mcp"])
            params = StdioServerParameters(command=conf["command"], args=conf["args"],
                env={**os.environ, **conf["env"], "PYTHONPATH": str(poison)}, cwd=str(cwd))
            async with stdio_client(params) as (read, write):
                async with ClientSession(read, write) as session:
                    result = await session.initialize()
                    self.assertEqual(result.serverInfo.name, "Frameva")
                    listed = await session.list_tools()
                    self.assertIn("record_flow", [tool.name for tool in listed.tools])

    async def test_stdio_source_to_storyboard_against_real_frameva_api(self):
        """Verify the bridge against the actual HTTP app and persistent store."""
        import socket
        import uvicorn
        from frameva.app import create_app
        from frameva.config import Config
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            repository = root / "product"
            repository.mkdir()
            (repository / "README.md").write_text("# ReviewFlow\n## Features\n- Shared review inbox\n", encoding="utf-8")
            config = Config(root / "state")
            sock = socket.socket()
            sock.bind(("127.0.0.1", 0))
            port = sock.getsockname()[1]
            server = uvicorn.Server(uvicorn.Config(create_app(config), host="127.0.0.1", port=port,
                                                   log_level="error", access_log=False, loop="asyncio"))
            thread = threading.Thread(target=server.run, kwargs={"sockets": [sock]}, daemon=True)
            thread.start()
            try:
                for _ in range(100):
                    if server.started:
                        break
                    await asyncio.sleep(.05)
                self.assertTrue(server.started, "Test HTTP server did not start")
                env = {**os.environ, "FRAMEVA_DATA_DIR": str(config.data_dir), "FRAMEVA_TOKEN": config.token,
                       "FRAMEVA_URL": f"http://127.0.0.1:{port}"}
                params = StdioServerParameters(command=sys.executable, args=["-m", "frameva", "mcp"], env=env,
                                               cwd=str(Path(__file__).resolve().parents[1]))
                async with stdio_client(params) as (read, write):
                    async with ClientSession(read, write) as session:
                        await session.initialize()
                        created = await session.call_tool("create_launch_project", {"repository_path": str(repository), "name": "ReviewFlow"})
                        self.assertFalse(created.isError, str(created.content))
                        project_id = created.structuredContent["project"]["id"]
                        project = await session.call_tool("get_project", {"project_id": project_id})
                        self.assertFalse(project.isError, str(project.content))
                        manifest = project.structuredContent
                        self.assertEqual(len(manifest["shots"]), 3)
                        self.assertIn("Shared review inbox", json.dumps(manifest))
                        self.assertNotIn(config.token, json.dumps(manifest))
                        feature_title = manifest["source_analysis"]["features"][0]["title"]
                        plan = {"name": "Inspect inbox", "base_url": "http://127.0.0.1:3000", "feature_titles": [feature_title],
                                "steps": [{"action": "wait", "seconds": 1}]}
                        flow = await session.call_tool("create_flow", {"project_id": project_id, "plan": plan})
                        self.assertFalse(flow.isError, str(flow.content))
                        flow_id = flow.structuredContent["id"]
                        loaded = await session.call_tool("get_flow", {"flow_id": flow_id})
                        self.assertEqual(loaded.structuredContent["feature_titles"], [feature_title])
                        coverage = await session.call_tool("get_project_coverage", {"project_id": project_id})
                        self.assertFalse(coverage.isError, str(coverage.content))
                        self.assertEqual(coverage.structuredContent["totals"]["recorded_candidate_count"], 0)
                        self.assertEqual(coverage.structuredContent["recorded_flows"], [])
                        deleted = await session.call_tool("delete_flow", {"flow_id": flow_id})
                        self.assertFalse(deleted.isError, str(deleted.content))
            finally:
                server.should_exit = True
                await asyncio.to_thread(thread.join, 8)
                sock.close()
                self.assertFalse(thread.is_alive(), "HTTP server did not stop")

    async def test_real_stdio_initialize_list_and_authenticated_tool(self):
        """Spawn the actual module and speak MCP via its official client."""
        token = "test-only-frameva-stdio-token-0000000000000"
        requests = []
        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):
                requests.append((self.path, self.headers.get("Authorization")))
                if self.path != "/api/projects" or self.headers.get("Authorization") != f"Bearer {token}":
                    self.send_error(403)
                    return
                data = json.dumps([{"id": "protocol-project", "name": "Protocol test"}]).encode()
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)
            def log_message(self, *args):
                pass
        http = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        thread = threading.Thread(target=http.serve_forever, daemon=True)
        thread.start()
        try:
            with tempfile.TemporaryDirectory() as tmp:
                env = {**os.environ, "FRAMEVA_DATA_DIR": tmp, "FRAMEVA_TOKEN": token,
                       "FRAMEVA_URL": f"http://127.0.0.1:{http.server_port}"}
                params = StdioServerParameters(command=sys.executable, args=["-m", "frameva", "mcp"], env=env,
                                               cwd=str(Path(__file__).resolve().parents[1]))
                async with stdio_client(params) as (read, write):
                    async with ClientSession(read, write) as session:
                        initialized = await session.initialize()
                        self.assertEqual(initialized.serverInfo.name, "Frameva")
                        tools = await session.list_tools()
                        self.assertIn("create_launch_project", [t.name for t in tools.tools])
                        result = await session.call_tool("list_projects", {})
                        self.assertFalse(result.isError)
                        self.assertIn("protocol-project", str(result.content))
                self.assertEqual(requests, [("/api/projects", f"Bearer {token}")])
        finally:
            http.shutdown()
            http.server_close()
            thread.join(timeout=3)
