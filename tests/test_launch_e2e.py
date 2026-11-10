"""A real CPU source-to-launch pipeline, not a fake renderer smoke test."""
import io
import json
import tempfile
import time
import unittest
import wave
import zipfile
from pathlib import Path

from fastapi.testclient import TestClient
from PIL import Image, ImageDraw


class LaunchPipelineTests(unittest.TestCase):
    def test_source_screenshot_render_export_download_and_persistence(self):
        from frameva.app import create_app
        from frameva.config import Config
        from frameva.render import probe, ffmpeg_path
        if not ffmpeg_path():
            self.skipTest("FFmpeg not installed")
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            config = Config(root / "data")
            app = create_app(config)
            with TestClient(app, base_url="http://127.0.0.1") as client:
                self.assertEqual(client.get("/api/projects").status_code, 401)
                self.assertEqual(client.post("/api/session", json={"token": config.token}).status_code, 200)
                project_response = client.post("/api/projects", json={"name": "InboxFlow", "description": "Integration test product"})
                self.assertLess(project_response.status_code, 300, project_response.text)
                project = project_response.json()
                project_id = project["id"]
                archive = io.BytesIO()
                with zipfile.ZipFile(archive, "w") as z:
                    z.writestr("app/README.md", "# InboxFlow\n## Features\n- Shared inbox\n")
                    z.writestr("app/package.json", json.dumps({"name": "inboxflow", "dependencies": {"react": "19"}}))
                    z.writestr("app/src/page.tsx", "export default function App(){ return <h1>Shared inbox</h1>; }")
                    z.writestr("app/.env", "API_KEY=DO_NOT_SHARE")
                analysis_response = client.post(f"/api/projects/{project_id}/source", files={"file": ("source.zip", archive.getvalue(), "application/zip")})
                self.assertLess(analysis_response.status_code, 300, analysis_response.text)
                self.assertNotIn("DO_NOT_SHARE", analysis_response.text)
                self.assertIn("Shared inbox", analysis_response.text)
                plan_response = client.post(f"/api/projects/{project_id}/launch-plan", json={"aspect": "landscape"})
                self.assertLess(plan_response.status_code, 300, plan_response.text)
                shots = client.get(f"/api/projects/{project_id}/shots").json()
                self.assertEqual(len(shots), 3)
                # A clearly synthetic test screenshot; never represented as user app footage.
                screen = Image.new("RGB", (640, 400), "#edf0f4")
                draw = ImageDraw.Draw(screen)
                draw.rectangle((0, 0, 140, 400), fill="#151a21")
                draw.text((170, 30), "Shared inbox — test fixture", fill="#151a21")
                for y in (90, 150, 210):
                    draw.rounded_rectangle((170, y, 600, y + 45), 8, fill="white")
                png = io.BytesIO(); screen.save(png, format="PNG")
                upload = client.post("/api/assets", data={"project_id": project_id}, files={"file": ("test-screen.png", png.getvalue(), "image/png")})
                self.assertLess(upload.status_code, 300, upload.text)
                screenshot = upload.json()
                for index, shot in enumerate(shots):
                    update = {"width": 320, "height": 192, "fps": 8, "duration": 1,
                        "reference_asset_id": screenshot["id"] if index == 1 else None}
                    response = client.patch(f"/api/shots/{shot['id']}", json=update)
                    self.assertLess(response.status_code, 300, response.text)
                queue = client.post(f"/api/projects/{project_id}/generate")
                self.assertLess(queue.status_code, 300, queue.text)
                def completed(job_type):
                    deadline = time.monotonic() + 60
                    while time.monotonic() < deadline:
                        jobs = [j for j in client.get(f"/api/jobs?project_id={project_id}").json() if j["type"] == job_type]
                        if jobs and all(j["status"] not in {"queued", "running"} for j in jobs):
                            self.assertTrue(all(j["status"] == "succeeded" for j in jobs), jobs)
                            return jobs
                        time.sleep(.05)
                    self.fail(f"Timed out awaiting {job_type} jobs")
                generated = completed("generate")
                self.assertEqual(len(generated), 3)
                audio = io.BytesIO()
                with wave.open(audio, "wb") as wav:
                    wav.setnchannels(1); wav.setsampwidth(2); wav.setframerate(16000)
                    wav.writeframes(b"\x00\x00" * 16000)
                soundtrack = client.post("/api/assets", data={"project_id": project_id}, files={"file": ("silence.wav", audio.getvalue(), "audio/wav")}).json()
                export = client.post(f"/api/projects/{project_id}/export", json={"width": 320, "height": 192, "fps": 8, "audio_asset_id": soundtrack["id"], "transition": "cut"})
                self.assertLess(export.status_code, 300, export.text)
                output = completed("export")[0]
                download = client.get(f"/api/assets/{output['asset_id']}/file?download=true")
                self.assertEqual(download.status_code, 200)
                self.assertGreater(len(download.content), 1000)
                result_file = root / "launch.mp4"; result_file.write_bytes(download.content)
                metadata = probe(result_file)
                self.assertAlmostEqual(metadata["duration"], 3, delta=.4)
                self.assertTrue(any(s["codec_type"] == "audio" for s in metadata["streams"]))
                manifest = client.get(f"/api/projects/{project_id}/manifest")
                self.assertEqual(manifest.status_code, 200)
                self.assertNotIn(config.token, manifest.text)
                self.assertNotIn(str(config.data_dir), manifest.text)
                # New copy must not silently export an old rendered clip.
                self.assertLess(client.patch(f"/api/shots/{shots[1]['id']}", json={"headline": "Updated verified copy"}).status_code, 300)
                stale = client.post(f"/api/projects/{project_id}/export", json={"width": 320, "height": 192, "fps": 8})
                self.assertEqual(stale.status_code, 409, stale.text)
            with TestClient(create_app(config), base_url="http://127.0.0.1", headers={"Authorization": f"Bearer {config.token}"}) as client:
                self.assertEqual(client.get(f"/api/projects/{project_id}").status_code, 200)
                self.assertEqual(len(client.get(f"/api/projects/{project_id}/shots").json()), 3)
                self.assertEqual(client.get(f"/api/assets/{output['asset_id']}/file").status_code, 200)


if __name__ == "__main__":
    unittest.main()
