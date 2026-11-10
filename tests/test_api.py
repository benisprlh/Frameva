import io
import json
import sqlite3
from pathlib import Path
import tempfile
import threading
import time
import unittest
from unittest.mock import patch
import zipfile

from fastapi.testclient import TestClient
from PIL import Image

from frameva.app import create_app
from frameva.config import Config
from frameva.store import Store
from frameva import render


class ApiTests(unittest.TestCase):
    def setUp(self):
        self.directory=tempfile.TemporaryDirectory()
        self.config=Config(Path(self.directory.name))
        self.app=create_app(self.config)
        self.client=TestClient(self.app,base_url='http://127.0.0.1:8741')
        self.client.__enter__()
        self.headers={'Authorization':'Bearer '+self.config.token}

    def tearDown(self):
        self.client.__exit__(None,None,None)
        self.directory.cleanup()

    def request(self,method,path,**kwargs):
        return self.client.request(method,path,headers=self.headers,**kwargs)

    def project(self,name='Test product'):
        response=self.request('POST','/api/projects',json={'name':name})
        self.assertEqual(response.status_code,201,response.text)
        return response.json()

    def shot(self,project,**kwargs):
        data={'name':'Hero','headline':'Ship better','caption':'Your real product in motion','width':320,'height':180,'duration':1,'fps':8,**kwargs}
        response=self.request('POST',f"/api/projects/{project['id']}/shots",json=data)
        self.assertEqual(response.status_code,201,response.text)
        return response.json()

    def wait(self,job,timeout=25):
        deadline=time.monotonic()+timeout
        while time.monotonic()<deadline:
            current=self.request('GET','/api/jobs/'+job['id']).json()
            if current['status'] not in ('queued','running'): return current
            time.sleep(.05)
        self.fail('Render timed out: '+str(current))

    def test_auth_origin_hosts_and_cookie(self):
        self.assertEqual(self.client.get('/api/projects').status_code,401)
        self.assertEqual(self.client.get('/api/health').status_code,200)
        self.assertEqual(self.client.get('/api/health',headers={'Host':'evil.example'}).status_code,400)
        response=self.client.post('/api/session',json={'token':self.config.token},headers={'Origin':'https://evil.example'})
        self.assertEqual(response.status_code,403)
        response=self.client.post('/api/session',json={'token':self.config.token},headers={'Origin':'http://127.0.0.1:8741'})
        self.assertEqual(response.status_code,200)
        self.assertIn('HttpOnly',response.headers['set-cookie'])
        self.assertIn('SameSite=strict',response.headers['set-cookie'])
        self.assertEqual(self.client.get('/api/projects').status_code,200)
        self.client.delete('/api/session')
        self.assertEqual(self.client.get('/api/projects').status_code,401)

    def test_request_bounds_unicode_token_and_single_server_lock(self):
        self.assertEqual(self.client.post('/api/session',json={'token':'é'*40}).status_code,401)
        response=self.client.post('/api/session',content=b'{"token":"'+b'a'*(2*1024*1024)+b'"}',headers={'Content-Type':'application/json'})
        self.assertEqual(response.status_code,413)
        second=create_app(Config(Path(self.directory.name)))
        with self.assertRaisesRegex(RuntimeError,'Another Frameva server'):
            with TestClient(second,base_url='http://127.0.0.1:8741'):
                pass

    def test_project_shots_reorder_and_validation(self):
        project=self.project()
        a=self.shot(project,name='A'); b=self.shot(project,name='B')
        url=f"/api/projects/{project['id']}/shots/order"
        self.assertEqual(self.request('PUT',url,json={'shot_ids':[a['id'],a['id']]}).status_code,422)
        result=self.request('PUT',url,json={'shot_ids':[b['id'],a['id']]}).json()
        self.assertEqual([s['id'] for s in result],[b['id'],a['id']])
        response=self.request('PATCH','/api/shots/'+a['id'],json={'width':321})
        self.assertEqual(response.status_code,422)
        self.assertEqual(self.request('PATCH','/api/shots/'+a['id'],json={'unknown':True}).status_code,422)
        self.assertEqual(self.request('DELETE','/api/projects/'+project['id']).status_code,200)
        self.assertEqual(self.request('GET','/api/shots/'+a['id']).status_code,405)
        self.assertEqual(self.request('GET',f"/api/projects/{project['id']}/shots").status_code,404)

    def test_asset_validation_project_isolation_and_range(self):
        project=self.project(); other=self.project('Other')
        payload=io.BytesIO(); Image.new('RGB',(80,50),'#b8ff65').save(payload,format='PNG')
        response=self.request('POST','/api/assets',data={'project_id':project['id']},files={'file':('../screenshot.png',payload.getvalue(),'image/png')})
        self.assertEqual(response.status_code,201,response.text)
        asset=response.json(); self.assertNotIn('_file',asset); self.assertEqual(asset['name'],'screenshot.png')
        self.assertEqual(self.request('GET',asset['url']).status_code,200)
        range_response=self.client.get(asset['url'],headers={**self.headers,'Range':'bytes=0-15'})
        self.assertEqual(range_response.status_code,206)
        self.assertEqual(len(range_response.content),16)
        self.assertEqual(self.request('POST',f"/api/projects/{other['id']}/shots",json={'reference_asset_id':asset['id']}).status_code,422)
        self.shot(project,reference_asset_id=asset['id'])
        self.assertEqual(self.request('DELETE','/api/assets/'+asset['id']).status_code,409)
        response=self.request('POST','/api/assets',data={'project_id':project['id']},files={'file':('fake.png',b'<script>alert(1)</script>','image/png')})
        self.assertEqual(response.status_code,422,response.text)

    @unittest.skipUnless(render.ffmpeg_path(),'FFmpeg required')
    def test_real_product_render_export_and_stale_rejection(self):
        project=self.project(); shot=self.shot(project)
        response=self.request('POST','/api/jobs',json={'shot_id':shot['id']})
        self.assertEqual(response.status_code,202,response.text)
        rendered=self.wait(response.json())
        self.assertEqual(rendered['status'],'succeeded',rendered)
        video=self.request('GET',f"/api/assets/{rendered['asset_id']}/file")
        self.assertEqual(video.status_code,200)
        self.assertIn(b'ftyp',video.content[:32])
        result=self.request('POST',f"/api/projects/{project['id']}/export",json={'width':320,'height':180,'fps':8})
        self.assertEqual(result.status_code,202,result.text)
        exported=self.wait(result.json())
        self.assertEqual(exported['status'],'succeeded',exported)
        self.request('PATCH','/api/shots/'+shot['id'],json={'headline':'A changed product'})
        result=self.request('POST',f"/api/projects/{project['id']}/export",json={})
        self.assertEqual(result.status_code,409,result.text)
        manifest=self.request('GET',f"/api/projects/{project['id']}/manifest").json()
        text=json.dumps(manifest)
        self.assertNotIn(self.config.token,text); self.assertNotIn(str(self.config.data_dir),text)
        self.assertNotIn('comfy_url',text); self.assertNotIn('_file',text)

    def test_latest_render_uses_sequence_when_timestamps_tie(self):
        project=self.project(); shot=self.shot(project)
        store=self.app.state.store
        clip=self.config.assets_dir/'existing.mp4'; clip.write_bytes(b'existing-render')
        store.put('asset',{'id':'existing','project_id':project['id'],'kind':'video','_file':clip.name})
        for id,snapshot in [('a-older',shot),('z-newer',{**shot,'headline':'Old wording'})]:
            store.put('job',{'id':id,'project_id':project['id'],'shot_id':shot['id'],
                'type':'generate','status':'succeeded','progress':100,'asset_id':'existing',
                'error':None,'created_at':'same-timestamp','updated_at':'same-timestamp',
                'params':{'shot':snapshot}})
        response=self.request('POST',f"/api/projects/{project['id']}/export",json={})
        self.assertEqual(response.status_code,409,response.text)
        jobs=self.request('GET','/api/jobs',params={'project_id':project['id']}).json()
        self.assertEqual([job['id'] for job in jobs],['z-newer','a-older'])
        self.assertGreater(jobs[0]['sequence'],jobs[1]['sequence'])

    def test_source_import_and_launch_plan(self):
        project=self.project()
        archive=io.BytesIO()
        with zipfile.ZipFile(archive,'w') as zipped:
            zipped.writestr('sample/README.md','# Sample\nA dashboard for your team.\n## Features\n- Track project progress\n- Export reports\n')
            zipped.writestr('sample/package.json',json.dumps({'name':'sample','dependencies':{'next':'15.0.0'}}))
            zipped.writestr('sample/.env','API_KEY=sk-not-for-export')
        response=self.request('POST',f"/api/projects/{project['id']}/source",files={'file':('source.zip',archive.getvalue(),'application/zip')})
        self.assertEqual(response.status_code,200,response.text)
        analysis=response.json(); self.assertEqual(analysis['trust'],'untrusted_source_evidence')
        self.assertNotIn('sk-not-for-export',json.dumps(analysis))
        response=self.request('POST',f"/api/projects/{project['id']}/launch-plan",json={'aspect':'portrait'})
        self.assertEqual(response.status_code,201,response.text)
        shots=response.json(); self.assertGreaterEqual(len(shots),3)
        self.assertGreater(shots[0]['height'],shots[0]['width'])
        response=self.request('POST',f"/api/projects/{project['id']}/source-analysis",json={'analysis':{'schema_version':999}})
        self.assertEqual(response.status_code,422)

    def test_cancellation_retry_and_restart_recovery(self):
        entered=threading.Event()
        def blocked(shot,reference,output,progress,cancelled):
            entered.set()
            while not cancelled(): time.sleep(.01)
            raise render.RenderCancelled()
        project=self.project(); shot=self.shot(project)
        with patch('frameva.app.render.render_preview',blocked):
            job=self.request('POST','/api/jobs',json={'shot_id':shot['id']}).json()
            self.assertTrue(entered.wait(3))
            self.assertEqual(self.request('DELETE','/api/projects/'+project['id']).status_code,409)
            response=self.request('POST','/api/jobs/'+job['id']+'/cancel')
            self.assertEqual(response.json()['status'],'cancelled')
            retried=self.request('POST','/api/jobs/'+job['id']+'/retry')
            self.assertEqual(retried.status_code,202)
            self.assertNotEqual(job['id'],retried.json()['id'])
            self.request('POST','/api/jobs/'+retried.json()['id']+'/cancel')
            time.sleep(.1)
        self.app.state.store.patch('job',job['id'],status='running')
        self.app.state.store.recover()
        self.assertEqual(self.app.state.store.get('job',job['id'])['status'],'failed')

    def test_workflow_validation_and_snapshot(self):
        workflows=self.request('GET','/api/workflows').json()
        self.assertTrue(any(w['id']=='wan22-5b-t2v' for w in workflows))
        response=self.request('POST','/api/workflows',json={'name':'Bad editor graph','graph':{'nodes':[]},'bindings':{}})
        self.assertEqual(response.status_code,422)
        response=self.request('PUT','/api/config',json={'comfy_url':'file:///etc/passwd'})
        self.assertEqual(response.status_code,422)
        response=self.request('PUT','/api/config',json={'comfy_url':'http://user:password@127.0.0.1:8188'})
        self.assertEqual(response.status_code,422)

class StoreAtomicityTests(unittest.TestCase):
    def setUp(self):
        self.directory=tempfile.TemporaryDirectory()
        self.path=Path(self.directory.name)/'test.sqlite3'
        self.store=Store(self.path)
        self.store.put('project',{'id':'project','created_at':'fixed','updated_at':'before'})

    def tearDown(self): self.directory.cleanup()

    def job(self,id,status='queued'):
        return self.store.put('job',{'id':id,'project_id':'project','created_at':'same-timestamp',
            'updated_at':'before','status':status,'progress':0,'error':None,'asset_id':None})

    def asset(self,job_id,id='asset'):
        return {'id':id,'project_id':'project','job_id':job_id,'kind':'video','_file':'complete.mp4'}

    def test_timestamp_ties_are_fifo_and_sequences_survive_reopen_delete_vacuum(self):
        first=self.job('z-first'); second=self.job('a-second')
        self.assertLess(first['sequence'],second['sequence'])
        self.assertEqual([j['id'] for j in self.store.list('job')],['z-first','a-second'])
        self.assertEqual(self.store.claim_job()['id'],'z-first')
        self.assertEqual(self.store.claim_job()['id'],'a-second')
        self.store.patch('job',first['id'],sequence=99999)
        self.assertEqual(self.store.get('job',first['id'])['sequence'],first['sequence'])
        self.store.delete('job',second['id'])
        with self.store.connection() as db: db.execute('VACUUM')
        self.store=Store(self.path)
        third=self.job('newest')
        self.assertGreater(third['sequence'],second['sequence'])
        self.assertEqual(self.store.get('job',first['id'])['sequence'],first['sequence'])

    def test_finalization_rolls_back_asset_job_and_project_on_write_failure(self):
        job=self.job('render','running'); asset=self.asset(job['id'])
        with self.store.connection() as db:
            db.execute("CREATE TRIGGER fail_finalize BEFORE UPDATE ON records WHEN OLD.kind='project' BEGIN SELECT RAISE(ABORT,'injected final write failure'); END")
        with self.assertRaises(sqlite3.IntegrityError): self.store.finalize_job(job['id'],asset)
        self.assertIsNone(self.store.get('asset',asset['id']))
        self.assertEqual(self.store.get('job',job['id']),job)
        self.assertEqual(self.store.get('project','project')['updated_at'],'before')
        with self.store.connection() as db: db.execute('DROP TRIGGER fail_finalize')
        result=self.store.finalize_job(job['id'],asset)
        self.assertEqual(result['status'],'succeeded')
        self.assertEqual(result['asset_id'],asset['id'])
        self.assertEqual(self.store.get('asset',asset['id']),asset)
        self.assertEqual(self.store.get('project','project')['updated_at'],result['updated_at'])

    def test_cancelled_job_cannot_finalize_or_publish_asset(self):
        job=self.job('cancelled-render','cancelled')
        self.assertIsNone(self.store.finalize_job(job['id'],self.asset(job['id'])))
        self.assertIsNone(self.store.get('asset','asset'))
        self.assertEqual(self.store.get('job',job['id'])['status'],'cancelled')

    def test_legacy_jobs_migrate_in_insert_order(self):
        with self.store.connection() as db:
            for id in ('z-legacy-first','a-legacy-second'):
                value={'id':id,'project_id':'project','created_at':'same','status':'queued'}
                db.execute("INSERT INTO records(kind,id,project_id,data) VALUES ('job',?,'project',?)",(id,json.dumps(value)))
        self.store=Store(self.path)
        self.assertEqual([j['id'] for j in self.store.list('job')],['z-legacy-first','a-legacy-second'])
        self.assertEqual(self.store.claim_job()['id'],'z-legacy-first')

class ConfigTests(unittest.TestCase):
    def test_token_persists(self):
        with tempfile.TemporaryDirectory() as directory:
            a=Config(Path(directory)); b=Config(Path(directory))
            self.assertEqual(a.token,b.token); self.assertGreaterEqual(len(a.token),32)

if __name__=='__main__': unittest.main()
