from contextlib import contextmanager
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import httpx

from frameva.comfy import render_comfy,renderer_status,validate_base_url,validate_workflow
from frameva.render import RenderCancelled,ffmpeg_path,render_preview,probe


GRAPH={"1":{"class_type":"Text","inputs":{"text":"old"}},"2":{"class_type":"Sampler","inputs":{"seed":1,"frames":25,"width":320,"height":192}},"3":{"class_type":"SaveVideo","inputs":{"filename_prefix":"frameva"}}}
BINDINGS={"prompt":{"node_id":"1","input":"text"},"seed":{"node_id":"2","input":"seed"},"frames":{"node_id":"2","input":"frames"}}


def mock_client(handler):
    return httpx.Client(base_url="http://127.0.0.1:8188/",transport=httpx.MockTransport(handler))


class ComfyTests(unittest.TestCase):
    def test_workflow_validation_rejects_editor_and_invalid_binding(self):
        validate_workflow(GRAPH,BINDINGS)
        with self.assertRaises(ValueError):
            validate_workflow({"nodes":[]},{})
        with self.assertRaises(ValueError):
            validate_workflow(GRAPH,{"prompt":{"node_id":"99","input":"text"}})
        with self.assertRaises(ValueError):
            validate_workflow(GRAPH,{"prompt":{"node_id":"1","input":"text"},"unknown":{"node_id":"1","input":"text"}})

    def test_url_does_not_accept_secrets_or_non_http(self):
        self.assertEqual(validate_base_url("http://127.0.0.1:8188/"),"http://127.0.0.1:8188")
        for bad in ["file:///etc/passwd","https://user:pass@host/","https://host/?token=secret","https://host/#fragment"]:
            with self.assertRaises(ValueError):
                validate_base_url(bad)

    def test_status_checks_backend(self):
        def handler(request):
            self.assertEqual(request.url.path,"/system_stats")
            return httpx.Response(200,json={"devices":[{"name":"Test GPU","type":"cuda","vram_total":123}]})
        with patch("frameva.comfy._client",side_effect=lambda u:mock_client(handler)):
            result=renderer_status("http://127.0.0.1:8188")
        self.assertTrue(result["connected"])
        self.assertEqual(result["device"],"Test GPU")

    def test_missing_nodes_and_failure_have_clear_errors(self):
        def handler(request):
            if request.url.path.startswith("/object_info/"):
                name=request.url.path.rsplit("/",1)[-1]
                return httpx.Response(200,json={name:{}})
            if request.url.path=="/prompt":
                return httpx.Response(200,json={"prompt_id":"job-123"})
            return httpx.Response(200,json={"job-123":{"status":{"status_str":"error","messages":[]}}})
        with tempfile.TemporaryDirectory() as tmp,patch("frameva.comfy._client",side_effect=lambda u:mock_client(handler)):
            with self.assertRaisesRegex(ValueError,"render failed"):
                render_comfy({"prompt":"test"},{"graph":GRAPH,"bindings":BINDINGS},None,Path(tmp)/"out.mp4","http://localhost:8188",lambda n:None,lambda:False)

    def test_cancel_never_calls_global_interrupt(self):
        requests=[]
        def handler(request):
            requests.append(request.url.path)
            name=request.url.path.rsplit("/",1)[-1]
            return httpx.Response(200,json={name:{}})
        with tempfile.TemporaryDirectory() as tmp,patch("frameva.comfy._client",side_effect=lambda u:mock_client(handler)):
            with self.assertRaises(RenderCancelled):
                render_comfy({},{"graph":GRAPH,"bindings":BINDINGS},None,Path(tmp)/"out.mp4","http://localhost:8188",lambda n:None,lambda:True)
        self.assertNotIn("/interrupt",requests)

    def test_cancel_during_node_discovery_stops_before_next_request(self):
        requests=[]
        def handler(request):
            requests.append(request.url.path)
            name=request.url.path.rsplit("/",1)[-1]
            return httpx.Response(200,json={name:{}})
        with tempfile.TemporaryDirectory() as tmp,patch("frameva.comfy._client",side_effect=lambda u:mock_client(handler)):
            with self.assertRaises(RenderCancelled):
                render_comfy({},{"graph":GRAPH,"bindings":BINDINGS},None,Path(tmp)/"out.mp4","http://localhost:8188",lambda n:None,lambda:bool(requests))
        self.assertEqual(len(requests),1)
        self.assertTrue(requests[0].startswith('/object_info/'))

    @unittest.skipUnless(ffmpeg_path(),"FFmpeg required")
    def test_complete_render_protocol_download_and_input_binding(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)
            sample=root/"fixture.mp4"
            render_preview({"width":160,"height":96,"fps":8,"duration":1,"headline":"Fixture"},None,sample,lambda n:None,lambda:False)
            payload=sample.read_bytes()
            submitted=[]
            def handler(request):
                path=request.url.path
                if path.startswith("/object_info/"):
                    name=path.rsplit("/",1)[-1]
                    return httpx.Response(200,json={name:{}})
                if path=="/prompt":
                    submitted.append(json.loads(request.content))
                    return httpx.Response(200,json={"prompt_id":"job-123"})
                if path=="/history/job-123":
                    return httpx.Response(200,json={"job-123":{"status":{"completed":True,"status_str":"success"},"outputs":{"3":{"images":[{"filename":"generated.mp4","subfolder":"video","type":"output"}]}}}})
                if path=="/view":
                    self.assertEqual(request.url.params["filename"],"generated.mp4")
                    return httpx.Response(200,content=payload,headers={"content-type":"video/mp4"})
                self.fail("Unexpected path "+path)
            target=root/"final.mp4"
            with patch("frameva.comfy._client",side_effect=lambda u:mock_client(handler)):
                render_comfy({"prompt":"A product launch","seed":99,"duration":2,"fps":24,"camera":"dolly_in"},{"graph":GRAPH,"bindings":BINDINGS,"frame_multiple":4},None,target,"http://localhost:8188",lambda n:None,lambda:False)
            self.assertEqual(submitted[0]["prompt"]["2"]["inputs"]["seed"],99)
            self.assertEqual(submitted[0]["prompt"]["2"]["inputs"]["frames"],45)
            self.assertIn("A product launch",submitted[0]["prompt"]["1"]["inputs"]["text"])
            self.assertEqual(GRAPH["1"]["inputs"]["text"],"old")
            self.assertGreater(probe(target)["duration"],0)

if __name__=="__main__":
    unittest.main()
