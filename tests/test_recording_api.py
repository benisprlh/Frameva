"""Public API lifecycle tests for real footage and bounded browser-flow jobs."""
from __future__ import annotations
import io
import json
from pathlib import Path
import shutil
import subprocess
import tempfile
import threading
import time
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient
from PIL import Image
from frameva.app import create_app
from frameva.config import Config
from frameva import render


@unittest.skipUnless(render.ffmpeg_path(),'FFmpeg required')
class RecordingApiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.media_directory=tempfile.TemporaryDirectory()
        cls.clip=Path(cls.media_directory.name)/'app-recording.mp4'
        subprocess.run([render.ffmpeg_path(),'-hide_banner','-loglevel','error','-y',
            '-f','lavfi','-i','testsrc2=size=320x180:rate=24',
            '-f','lavfi','-i','sine=frequency=440:sample_rate=44100',
            '-t','4','-c:v','libx264','-preset','ultrafast','-pix_fmt','yuv420p',
            '-c:a','aac','-shortest',str(cls.clip)],check=True,timeout=30)

    @classmethod
    def tearDownClass(cls): cls.media_directory.cleanup()

    def setUp(self):
        self.directory=tempfile.TemporaryDirectory()
        self.config=Config(Path(self.directory.name))
        self.app=create_app(self.config)
        self.client=TestClient(self.app,base_url='http://127.0.0.1:8741')
        self.client.__enter__()
        self.headers={'Authorization':'Bearer '+self.config.token}
        self.project=self.call('POST','/api/projects',json={'name':'Live product'}).json()

    def tearDown(self):
        self.client.__exit__(None,None,None)
        self.directory.cleanup()

    def call(self,method,path,**kwargs):
        return self.client.request(method,path,headers=self.headers,**kwargs)

    def upload_video(self):
        response=self.call('POST','/api/assets',data={'project_id':self.project['id']},
                           files={'file':('window.mp4',self.clip.read_bytes(),'video/mp4')})
        self.assertEqual(response.status_code,201,response.text)
        return response.json()

    def new_flow(self,**changes):
        data={'name':'Demonstrate dashboard','base_url':'http://127.0.0.1:3000','width':640,'height':480,
              'max_duration':30,'steps':[{'action':'goto','url':'/','label':'Open dashboard'}],**changes}
        response=self.call('POST',f"/api/projects/{self.project['id']}/flows",json=data)
        self.assertEqual(response.status_code,201,response.text)
        return response.json()

    def wait(self,job,timeout=30):
        deadline=time.monotonic()+timeout
        while time.monotonic()<deadline:
            current=self.call('GET','/api/jobs/'+job['id']).json()
            if current['status'] not in {'queued','running'}: return current
            time.sleep(.03)
        self.fail('Job did not complete: '+str(current))

    def completed_record(self,plan,output,progress,cancelled):
        shutil.copyfile(self.clip,output)
        progress(90)
        data=plan.model_dump()
        return {'schema_version':1,'status':'completed','duration':4,
                'recording_kind':'browser-flow','warnings':[],
                'feature_titles':data.get('feature_titles',[]),
                'steps':[{'index':0,'action':'goto','label':'Open dashboard','status':'completed','start':0,'end':1}]}

    def test_video_ownership_trim_validation_and_reference_deletion(self):
        video=self.upload_video()
        other=self.call('POST','/api/projects',json={'name':'Other'}).json()
        body={'provider':'recording','video_asset_id':video['id'],'duration':2,'playback_rate':2}
        self.assertEqual(self.call('POST',f"/api/projects/{other['id']}/shots",json=body).status_code,422)
        response=self.call('POST',f"/api/projects/{self.project['id']}/shots",json=body)
        self.assertEqual(response.status_code,201,response.text)
        shot=response.json()
        self.assertEqual(self.call('PATCH','/api/shots/'+shot['id'],json={'trim_start':.5}).status_code,422)
        self.assertEqual(self.call('POST',f"/api/projects/{self.project['id']}/shots",json={'provider':'recording'}).status_code,422)
        self.assertEqual(self.call('POST',f"/api/projects/{self.project['id']}/shots",json={'provider':'preview','duration':120}).status_code,422)
        self.assertEqual(self.call('DELETE','/api/assets/'+video['id']).status_code,409)
        image=io.BytesIO(); Image.new('RGB',(32,32),'red').save(image,format='PNG')
        uploaded=self.call('POST','/api/assets',data={'project_id':self.project['id']},files={'file':('still.png',image.getvalue(),'image/png')}).json()
        response=self.call('PATCH','/api/shots/'+shot['id'],json={'video_asset_id':uploaded['id']})
        self.assertEqual(response.status_code,422)

    def test_long_audio_does_not_make_short_video_eligible_for_longer_shot(self):
        longer_audio=Path(self.directory.name)/'short-video-long-audio.mp4'
        subprocess.run([render.ffmpeg_path(),'-hide_banner','-loglevel','error','-y',
            '-f','lavfi','-i','testsrc2=size=320x180:rate=24:duration=1',
            '-f','lavfi','-i','sine=frequency=440:sample_rate=44100:duration=3',
            '-c:v','libx264','-preset','ultrafast','-pix_fmt','yuv420p','-c:a','aac',str(longer_audio)],check=True,timeout=30)
        uploaded=self.call('POST','/api/assets',data={'project_id':self.project['id']},
            files={'file':('short-video.mp4',longer_audio.read_bytes(),'video/mp4')})
        self.assertEqual(uploaded.status_code,201,uploaded.text)
        asset=uploaded.json()
        self.assertLess(asset['video_duration'],asset['duration'])
        response=self.call('POST',f"/api/projects/{self.project['id']}/shots",json={
            'provider':'recording','video_asset_id':asset['id'],'duration':2})
        self.assertEqual(response.status_code,422,response.text)
        self.assertIn('too short',response.json()['detail'])

    def test_real_recording_render_and_final_export_preserve_video_audio(self):
        video=self.upload_video()
        response=self.call('POST',f"/api/projects/{self.project['id']}/shots",json={
            'name':'Real app tour','provider':'recording','video_asset_id':video['id'],
            'duration':1,'trim_start':1,'playback_rate':2,'width':320,'height':180,'fps':24,
            'focus_x':.6,'focus_y':.4,'zoom':1.2,'keep_audio':True,'headline':'See it work'})
        self.assertEqual(response.status_code,201,response.text)
        shot=response.json()
        queued=self.call('POST','/api/jobs',json={'shot_id':shot['id']})
        result=self.wait(queued.json())
        self.assertEqual(result['status'],'succeeded',result)
        asset=self.app.state.store.get('asset',result['asset_id'])
        info=render.probe(self.config.assets_dir/asset['_file'])
        self.assertAlmostEqual(info['duration'],1,delta=.15)
        self.assertTrue(any(stream['codec_type']=='audio' for stream in info['streams']))
        queued=self.call('POST',f"/api/projects/{self.project['id']}/export",json={'width':320,'height':180,'fps':24,'transition':'crossfade','transition_duration':.3})
        self.assertEqual(queued.status_code,202,queued.text)
        final=self.wait(queued.json())
        self.assertEqual(final['status'],'succeeded',final)
        exported=self.app.state.store.get('asset',final['asset_id'])
        self.assertTrue(any(s['codec_type']=='audio' for s in render.probe(self.config.assets_dir/exported['_file'])['streams']))

    def test_flow_recording_report_mapping_and_edited_plan_warning(self):
        analysis={'schema_version':1,'name':'Product','features':[
            {'title':'Dashboard','description':'Shows project status','status':'candidate','evidence':[]},
            {'title':'Export reports','description':'Creates report files','status':'candidate','evidence':[]}]}
        self.assertEqual(self.call('POST',f"/api/projects/{self.project['id']}/source-analysis",json={'analysis':analysis}).status_code,200)
        flow=self.new_flow(feature_titles=['Dashboard'])
        with patch('frameva.app.flow.record_flow',self.completed_record):
            job=self.call('POST',f"/api/flows/{flow['id']}/record").json()
            result=self.wait(job)
        self.assertEqual(result['status'],'succeeded',result)
        asset=self.app.state.store.get('asset',result['asset_id'])
        self.assertEqual(asset['capture_report']['status'],'completed')
        self.assertEqual(asset['recording_kind'],'browser-flow')
        coverage=self.call('GET',f"/api/projects/{self.project['id']}/coverage").json()
        self.assertEqual(coverage['totals']['recorded_percent'],50.0)
        self.assertFalse(coverage['all_features_verified'])
        self.assertEqual(coverage['source_candidates'][0]['recordings'][0]['asset_id'],asset['id'])
        plan={key:value for key,value in flow.items() if key not in {'id','project_id','created_at','updated_at'}}
        plan['feature_titles']=['Export reports']
        self.assertEqual(self.call('PUT','/api/flows/'+flow['id'],json=plan).status_code,200)
        updated=self.call('GET',f"/api/projects/{self.project['id']}/coverage").json()
        self.assertEqual(updated['totals']['recorded_percent'],50.0)
        self.assertEqual(updated['source_candidates'][0]['status'],'recorded')
        self.assertEqual(updated['source_candidates'][1]['status'],'unrecorded')
        self.assertEqual(len(updated['flows_with_unrecorded_changes']),1)
        self.assertFalse(updated['recorded_flows'][0]['matches_current_plan'])
        manifest=self.call('GET',f"/api/projects/{self.project['id']}/manifest").json()
        self.assertEqual(len(manifest['flows']),1)
        self.assertIn('coverage',manifest)
        self.assertEqual(self.call('DELETE','/api/projects/'+self.project['id']).status_code,200)
        self.assertIsNone(self.app.state.store.get('flow',flow['id']))

    def test_failed_flow_retry_uses_original_snapshot(self):
        flow=self.new_flow(feature_titles=['Dashboard'])
        with patch('frameva.app.flow.record_flow',side_effect=ValueError('Required button not found.')):
            original=self.call('POST',f"/api/flows/{flow['id']}/record").json()
            failed=self.wait(original)
        self.assertEqual(failed['status'],'failed')
        self.assertEqual(self.call('GET','/api/assets',params={'project_id':self.project['id']}).json(),[])
        plan={key:value for key,value in flow.items() if key not in {'id','project_id','created_at','updated_at'}}
        plan['name']='Edited flow'; plan['feature_titles']=['Export reports']
        self.call('PUT','/api/flows/'+flow['id'],json=plan)
        seen=[]
        def recorder(snapshot,*args):
            seen.append(snapshot.model_dump())
            return self.completed_record(snapshot,*args)
        with patch('frameva.app.flow.record_flow',recorder):
            retry=self.call('POST','/api/jobs/'+failed['id']+'/retry')
            self.assertEqual(retry.status_code,202,retry.text)
            completed=self.wait(retry.json())
        self.assertEqual(completed['status'],'succeeded',completed)
        self.assertEqual(seen[0]['name'],flow['name'])
        self.assertEqual(seen[0]['feature_titles'],['Dashboard'])

    def test_cancelled_flow_blocks_deletion_and_removes_partial_output(self):
        flow=self.new_flow(); entered=threading.Event(); stopped=threading.Event(); written=[]
        def recorder(plan,output,progress,cancelled):
            output.write_bytes(b'partial'); written.append(output); entered.set()
            while not cancelled(): time.sleep(.01)
            stopped.set(); raise render.RenderCancelled()
        with patch('frameva.app.flow.record_flow',recorder):
            queued=self.call('POST',f"/api/flows/{flow['id']}/record").json()
            self.assertTrue(entered.wait(3))
            self.assertEqual(self.call('DELETE','/api/flows/'+flow['id']).status_code,409)
            self.assertEqual(self.call('DELETE','/api/projects/'+self.project['id']).status_code,409)
            self.assertEqual(self.call('POST','/api/jobs/'+queued['id']+'/cancel').json()['status'],'cancelled')
            self.assertTrue(stopped.wait(3))
            deadline=time.monotonic()+3
            while written[0].exists() and time.monotonic()<deadline: time.sleep(.01)
            self.assertFalse(written[0].exists())
        self.assertEqual(self.call('GET','/api/assets',params={'project_id':self.project['id']}).json(),[])
        self.assertEqual(self.call('DELETE','/api/flows/'+flow['id']).status_code,200)
        self.assertEqual(self.call('POST','/api/jobs/'+queued['id']+'/retry').status_code,404)

    def test_pending_job_keeps_video_after_shot_changes(self):
        video=self.upload_video()
        response=self.call('POST',f"/api/projects/{self.project['id']}/shots",json={'name':'Clip','provider':'recording','video_asset_id':video['id'],'duration':1})
        self.assertEqual(response.status_code,201,response.text)
        shot=response.json(); entered=threading.Event(); stopped=threading.Event()
        def blocked(shot,reference,output,progress,cancelled):
            entered.set()
            while not cancelled(): time.sleep(.01)
            stopped.set(); raise render.RenderCancelled()
        with patch('frameva.app.render.render_recording',blocked):
            job=self.call('POST','/api/jobs',json={'shot_id':shot['id']}).json()
            self.assertTrue(entered.wait(3))
            changed=self.call('PATCH','/api/shots/'+shot['id'],json={'provider':'preview','video_asset_id':None})
            self.assertEqual(changed.status_code,200,changed.text)
            self.assertEqual(self.call('DELETE','/api/assets/'+video['id']).status_code,409)
            self.call('POST','/api/jobs/'+job['id']+'/cancel')
            self.assertTrue(stopped.wait(3))
        self.assertEqual(self.call('DELETE','/api/assets/'+video['id']).status_code,200)

if __name__=='__main__': unittest.main()
