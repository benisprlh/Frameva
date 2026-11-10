import math
from pathlib import Path
import struct
import tempfile
import unittest
from unittest.mock import patch
import shutil
import wave

from PIL import Image,ImageDraw

from frameva.render import RenderCancelled,ffmpeg_path,probe,render_export,render_preview,validate_media


@unittest.skipUnless(ffmpeg_path(),"FFmpeg required")
class RenderTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.root=Path(self.tmp.name)
        self.shot={"width":320,"height":192,"duration":1,"fps":12,"name":"Launch with clarity","headline":"Your product. In motion.","caption":"Real screenshots and evidence-backed features.","camera":"dolly_in","brand_color":"#b8ff65","style":"cinematic"}

    def tearDown(self):
        self.tmp.cleanup()

    def test_product_motion_and_export_preserve_duration_audio(self):
        screenshot=self.root/"screenshot.png"
        image=Image.new("RGB",(640,400),(235,239,247))
        d=ImageDraw.Draw(image)
        d.rectangle((0,0,140,400),fill=(20,30,45))
        d.rounded_rectangle((170,80,590,320),radius=12,fill=(255,255,255))
        image.save(screenshot)
        first=self.root/"first.mp4"
        progress=[]
        render_preview(self.shot,screenshot,first,progress.append,lambda:False)
        self.assertEqual(progress[-1],100)
        data=validate_media(first,"video/mp4")
        self.assertEqual(data["kind"],"video")
        self.assertEqual((data["width"],data["height"]),(320,192))
        self.assertAlmostEqual(data["duration"],1,delta=.15)
        second=self.root/"second.mp4"
        render_preview({**self.shot,"layout":"title","headline":"Built for your next launch."},None,second,lambda n:None,lambda:False)
        audio=self.root/"music.wav"
        with wave.open(str(audio),"wb") as wav:
            wav.setparams((1,2,24000,0,"NONE","not compressed"))
            wav.writeframes(b"".join(struct.pack("<h",int(1000*math.sin(i*2*math.pi*440/24000))) for i in range(24000)))
        exported=self.root/"launch.mp4"
        render_export([first,second],exported,320,192,12,audio,lambda n:None,lambda:False)
        info=probe(exported)
        self.assertAlmostEqual(info["duration"],2,delta=.2)
        self.assertTrue(any(s["codec_type"]=="audio" for s in info["streams"]))
        self.assertEqual(validate_media(audio,"audio/wav")["kind"],"audio")

    def test_probe_without_system_ffprobe(self):
        target=self.root/"fallback.mp4"
        render_preview(self.shot,None,target,lambda n:None,lambda:False)
        original=shutil.which
        with patch("frameva.render.shutil.which",side_effect=lambda name:None if name=="ffprobe" else original(name)):
            info=probe(target)
        self.assertAlmostEqual(info["duration"],1,delta=.1)
        video=next(s for s in info["streams"] if s["codec_type"]=="video")
        self.assertEqual((video["width"],video["height"]),(320,192))

    def test_cancel_removes_partial_video(self):
        target=self.root/"cancelled.mp4"
        with self.assertRaises(RenderCancelled):
            render_preview(self.shot,None,target,lambda n:None,lambda:True)
        self.assertFalse(target.exists())

    def test_media_magic_rejects_playlist_and_svg(self):
        path=self.root/"untrusted.mp4"
        path.write_text("#EXTM3U\nhttp://example.com/file.ts\n")
        with self.assertRaises(ValueError):
            validate_media(path,"video/mp4")
        path.write_text('<svg xmlns="http://www.w3.org/2000/svg"></svg>')
        with self.assertRaises(ValueError):
            validate_media(path,"image/svg+xml")

    def test_portrait_title_unicode_and_long_tokens(self):
        output=self.root/"portrait.mp4"
        render_preview({**self.shot,"width":192,"height":320,"headline":"Kemudahan untuk setiap tim 🚀","caption":"https://example.com/a/verylongproductidentifierwithoutspaces"},None,output,lambda n:None,lambda:False)
        self.assertTrue(output.stat().st_size>1000)

if __name__=="__main__":
    unittest.main()
