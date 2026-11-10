"""Real media tests; the moving source is explicitly a synthetic test fixture."""
from array import array
import math
from pathlib import Path
import subprocess
import tempfile
import unittest
import shutil
from unittest.mock import patch

from frameva.render import RenderCancelled, ffmpeg_path, probe, render_recording, render_export, validate_media


@unittest.skipUnless(ffmpeg_path(), 'FFmpeg required')
class RecordingRenderTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.storage=tempfile.TemporaryDirectory(prefix='frameva-moving-fixture-')
        cls.root=Path(cls.storage.name)
        cls.source=cls.root/'synthetic-moving-fixture.mp4'
        subprocess.run([ffmpeg_path(),'-hide_banner','-loglevel','error','-y','-f','lavfi','-i','testsrc2=size=320x180:rate=24:duration=4','-f','lavfi','-i','sine=frequency=440:sample_rate=48000:duration=4','-c:v','libx264','-preset','ultrafast','-pix_fmt','yuv420p','-c:a','aac','-shortest',str(cls.source)],check=True,capture_output=True,timeout=30)
        cls.music=cls.root/'synthetic-soundtrack.wav'
        subprocess.run([ffmpeg_path(),'-hide_banner','-loglevel','error','-y','-f','lavfi','-i','sine=frequency=880:sample_rate=48000:duration=2',str(cls.music)],check=True,capture_output=True,timeout=15)

    @classmethod
    def tearDownClass(cls):
        cls.storage.cleanup()

    def setUp(self):
        self.output=tempfile.TemporaryDirectory(prefix='frameva-recording-test-')
        self.directory=Path(self.output.name)
        self.shot={'width':320,'height':192,'fps':12,'duration':1.5,'trim_start':.5,'playback_rate':1.5,'zoom':1.2,'focus_x':.6,'focus_y':.4,'keep_audio':True,'camera':'dolly_in','headline':'A real moving recording','caption':'Synthetic compositor fixture, not an app demo.','brand_color':'#b8ff65','layout':'showcase'}

    def tearDown(self):
        self.output.cleanup()

    def frame(self,path,at):
        result=subprocess.run([ffmpeg_path(),'-hide_banner','-loglevel','error','-ss',str(at),'-protocol_whitelist','file,pipe','-i',str(path),'-frames:v','1','-f','rawvideo','-pix_fmt','rgb24','pipe:1'],check=True,capture_output=True,timeout=20)
        return result.stdout

    def tone(self,path,frequency):
        result=subprocess.run([ffmpeg_path(),'-hide_banner','-loglevel','error','-ss','0.6','-protocol_whitelist','file,pipe','-i',str(path),'-t','0.5','-vn','-ar','8000','-ac','1','-f','s16le','pipe:1'],check=True,capture_output=True,timeout=20)
        values=array('h');values.frombytes(result.stdout)
        if not values:
            return 0
        real=sum(v*math.cos(2*math.pi*frequency*i/8000) for i,v in enumerate(values))
        imag=sum(v*math.sin(2*math.pi*frequency*i/8000) for i,v in enumerate(values))
        return 2*math.hypot(real,imag)/len(values)

    def test_recording_uses_moving_source_and_preserves_pitch_after_trim_rate(self):
        path=self.directory/'recorded-scene.mp4'
        updates=[]
        render_recording({**self.shot,'camera':'static'},self.source,path,updates.append,lambda:False)
        info=probe(path)
        self.assertAlmostEqual(info['duration'],1.5,delta=.1)
        self.assertTrue(any(s['codec_type']=='audio' for s in info['streams']))
        self.assertGreater(self.tone(path,440),1000)
        self.assertLess(self.tone(path,660),150)
        early,late=self.frame(path,.2),self.frame(path,1.2)
        self.assertEqual(len(early),320*192*3)
        self.assertGreater(sum(abs(a-b) for a,b in zip(early,late))/len(early),.5)
        self.assertEqual(updates[-1],100)

    def test_portrait_and_square_output_without_audio(self):
        for shape in [(192,320),(192,192)]:
            with self.subTest(shape=shape):
                path=self.directory/f'{shape[0]}x{shape[1]}.mp4'
                render_recording({**self.shot,'width':shape[0],'height':shape[1],'keep_audio':False,'duration':1,'playback_rate':.5},self.source,path,lambda n:None,lambda:False)
                info=probe(path)
                video=next(s for s in info['streams'] if s['codec_type']=='video')
                self.assertEqual((video['width'],video['height']),shape)
                self.assertFalse(any(s['codec_type']=='audio' for s in info['streams']))
                self.assertAlmostEqual(info['duration'],1,delta=.1)

    def test_no_ffprobe_does_not_mistake_long_audio_for_video_footage(self):
        source=self.directory/'one-second-video-three-second-audio.mp4'
        subprocess.run([ffmpeg_path(),'-hide_banner','-loglevel','error','-y','-f','lavfi','-i','testsrc2=size=160x96:rate=12:duration=1','-f','lavfi','-i','sine=frequency=440:sample_rate=48000:duration=3','-c:v','libx264','-pix_fmt','yuv420p','-c:a','aac',str(source)],check=True,capture_output=True,timeout=20)
        original=shutil.which
        with patch('frameva.render.shutil.which',side_effect=lambda name:None if name=='ffprobe' else original(name)):
            media=validate_media(source,'video/mp4')
            self.assertAlmostEqual(media['duration'],3,delta=.1)
            self.assertAlmostEqual(media['video_duration'],1,delta=.1)
            with self.assertRaisesRegex(ValueError,'Insufficient recording footage'):
                render_recording({**self.shot,'trim_start':0,'duration':2,'playback_rate':1},source,self.directory/'must-fail.mp4',lambda n:None,lambda:False)

    def test_insufficient_source_fails_instead_of_freezing(self):
        path=self.directory/'must-not-exist.mp4'
        with self.assertRaisesRegex(ValueError,'Insufficient recording footage'):
            render_recording({**self.shot,'trim_start':3.5,'duration':2},self.source,path,lambda n:None,lambda:False)
        self.assertFalse(path.exists())

    def test_recording_cancel_removes_partial_output(self):
        path=self.directory/'cancelled.mp4'
        calls=0
        def cancelled():
            nonlocal calls
            calls+=1
            return calls>2
        with self.assertRaises(RenderCancelled):
            render_recording(self.shot,self.source,path,lambda n:None,cancelled)
        self.assertFalse(path.exists())

    def test_crossfade_has_real_overlap_and_music_mixes_with_source(self):
        clips=[]
        for index in range(2):
            path=self.directory/f'shot-{index}.mp4'
            render_recording({**self.shot,'trim_start':.5+index,'playback_rate':1,'camera':'static'},self.source,path,lambda n:None,lambda:False)
            clips.append(path)
        output=self.directory/'crossfaded-launch.mp4'
        render_export(clips,output,320,192,12,self.music,lambda n:None,lambda:False,transition='crossfade',transition_duration=.25)
        self.assertAlmostEqual(probe(output)['duration'],2.75,delta=.12)
        # Both frequencies remain: music is mixed beneath source narration/audio.
        original=self.tone(output,440)
        music=self.tone(output,880)
        self.assertGreater(original,1000)
        self.assertGreater(music,150)
        self.assertGreater(original,music*2)
        self.assertNotEqual(self.frame(output,.3),self.frame(output,2.2))

    def test_many_shot_crossfade_preserves_all_overlap_durations(self):
        path=self.directory/'one-second-recording.mp4'
        render_recording({**self.shot,'duration':1,'playback_rate':1,'camera':'static'},self.source,path,lambda n:None,lambda:False)
        # Nine clips exercises both chained xfade filters and the bounded-input grouping path.
        output=self.directory/'nine-shot-launch.mp4'
        render_export([path]*9,output,320,192,12,None,lambda n:None,lambda:False,transition='crossfade',transition_duration=.25)
        self.assertAlmostEqual(probe(output)['duration'],9-8*.25,delta=.13)

    def test_source_file_cannot_be_overwritten_or_removed(self):
        before=self.source.stat().st_size
        with self.assertRaisesRegex(ValueError,'differ from'):
            render_recording(self.shot,self.source,self.source,lambda n:None,lambda:False)
        with self.assertRaisesRegex(ValueError,'differ from'):
            render_export([self.source],self.source,320,192,12,None,lambda n:None,lambda:False)
        self.assertEqual(self.source.stat().st_size,before)

    def test_crossfade_rejects_excessive_overlap(self):
        path=self.directory/'short.mp4'
        render_recording({**self.shot,'duration':1,'playback_rate':1},self.source,path,lambda n:None,lambda:False)
        with self.assertRaisesRegex(ValueError,'half the shortest'):
            render_export([path,path],self.directory/'invalid.mp4',320,192,12,None,lambda n:None,lambda:False,transition='crossfade',transition_duration=.8)


if __name__=='__main__':
    unittest.main()
