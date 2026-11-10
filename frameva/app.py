"""Authenticated local Frameva API and durable serial render queue."""
from __future__ import annotations
from contextlib import asynccontextmanager
import hmac
import json
import logging
from pathlib import Path
import platform
import secrets
import threading
import time
from urllib.parse import urlsplit

from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from starlette.concurrency import run_in_threadpool
from pydantic import ValidationError

from . import __version__
from .config import Config
from .store import Store, identifier, now
from .models import (SessionInput, ProjectInput, ProjectPatch, ShotInput, ShotPatch,
    OrderInput, JobInput, ExportInput, RendererInput, WorkflowInput, LaunchPlanInput,
    SourceAnalysisInput)
from . import render, comfy, catalog, source, flow
from .flow import FlowInput

log = logging.getLogger(__name__)
ACTIVE = {'queued','running'}
SESSION_COOKIE = 'frameva_session'


def public(value: dict) -> dict:
    return {k:v for k,v in value.items() if not k.startswith('_')}


def shot_signature(shot: dict) -> dict:
    return ShotInput.model_validate({k:shot[k] for k in ShotInput.model_fields if k in shot}).model_dump()


def create_app(config: Config | None = None) -> FastAPI:
    config = config or Config()
    store = Store(config.db_path)
    stopping = threading.Event()
    wake = threading.Event()
    sessions: dict[str,float] = {}
    attempts: dict[str,list[float]] = {}
    for workflow in catalog.BUILTIN_WORKFLOWS:
        if store.get('workflow',workflow['id']) is None:
            store.put('workflow',{**workflow,'builtin':True,'created_at':now(),'updated_at':now()})
    if store.get('setting','renderer') is None:
        store.put('setting',{'id':'renderer','comfy_url':comfy.validate_base_url(config.comfy_url)})

    def require(kind: str, id: str) -> dict:
        value = store.get(kind,id)
        if value is None:
            raise HTTPException(404,f'{kind.capitalize()} not found.')
        return value

    def touch(project_id: str):
        store.patch('project',project_id)

    def asset_path(asset: dict) -> Path:
        # Paths are created only by this API, and must remain direct children.
        path = (config.assets_dir / asset['_file']).resolve()
        if path.parent != config.assets_dir.resolve():
            raise ValueError('Invalid asset storage path.')
        return path

    def asset_record(path: Path, project_id: str, name: str, metadata: dict, job_id: str | None = None) -> dict:
        value = {'id':identifier(),'project_id':project_id,'name':name,
                 'kind':metadata['kind'],'mime_type':metadata['mime_type'],
                 'size':path.stat().st_size,'created_at':now(),'job_id':job_id,
                 '_file':path.name}
        for key in ('width','height','duration','video_duration'):
            if key in metadata: value[key]=metadata[key]
        value['url']=f"/api/assets/{value['id']}/file"
        return value

    def add_asset(path: Path, project_id: str, name: str, metadata: dict, job_id: str | None = None) -> dict:
        return store.put('asset',asset_record(path,project_id,name,metadata,job_id))

    def pending(project_id: str | None = None) -> list:
        return [j for j in store.list('job',project_id) if j['status'] in ACTIVE]

    def validate_shot_refs(shot: dict, project_id: str):
        if shot.get('reference_asset_id'):
            asset = require('asset',shot['reference_asset_id'])
            if asset['project_id'] != project_id or asset['kind'] != 'image':
                raise HTTPException(422,'The image reference must be an image in this project.')
        if shot.get('video_asset_id'):
            video=require('asset',shot['video_asset_id'])
            if video['project_id']!=project_id or video['kind']!='video':
                raise HTTPException(422,'The recording must be a video asset in this project.')
            if not asset_path(video).is_file():
                raise HTTPException(409,'The recording media is missing. Import it again.')
            if shot.get('provider')=='recording':
                duration=video.get('video_duration')
                if duration is None:
                    info=render.probe(asset_path(video))
                    stream=next((item for item in info.get('streams',[]) if item.get('codec_type')=='video' and not item.get('disposition',{}).get('attached_pic')),{})
                    duration=stream.get('duration') or info.get('duration') or 0
                duration=float(duration)
                required=float(shot.get('trim_start',0))+float(shot['duration'])*float(shot.get('playback_rate',1))
                if required>duration+0.001:
                    raise HTTPException(422,f'Recording is too short: the selected trim and playback rate need {required:.3f}s, but the video has {duration:.3f}s. Shorten the shot or adjust its trim/rate.')
        elif shot.get('provider')=='recording':
            raise HTTPException(422,'Choose a video asset for the recording shot.')
        if shot.get('workflow_id'):
            require('workflow',shot['workflow_id'])

    def new_shot(project_id: str, data: dict, position: int | None = None) -> dict:
        validated = ShotInput.model_validate(data).model_dump()
        validate_shot_refs(validated,project_id)
        shots = store.list('shot',project_id)
        if len(shots)>=200: raise HTTPException(409,'A project supports at most 200 shots.')
        value = {**validated,'id':identifier(),'project_id':project_id,
                 'position':position if position is not None else max((s['position'] for s in shots),default=-1)+1,
                 'created_at':now(),'updated_at':now()}
        store.put('shot',value); touch(project_id)
        return value

    def make_job(project_id: str, type: str, params: dict, shot_id: str | None = None) -> dict:
        if len(pending())>=200: raise HTTPException(409,'The queue is full (200 pending renders).')
        value={'id':identifier(),'project_id':project_id,'shot_id':shot_id,'type':type,
               'status':'queued','progress':0,'error':None,'asset_id':None,
               'created_at':now(),'updated_at':now(),'params':params}
        value=store.put('job',value); wake.set()
        return value

    def generation_params(shot: dict) -> dict:
        validate_shot_refs(shot,shot['project_id'])
        workflow=None
        if shot['provider']=='comfyui':
            if not shot.get('workflow_id'): raise HTTPException(422,'Select a ComfyUI workflow first.')
            workflow=require('workflow',shot['workflow_id'])
            if not shot['prompt']: raise HTTPException(422,'AI generation requires a prompt.')
        return {'shot':shot,'workflow':workflow,
                'comfy_url':require('setting','renderer')['comfy_url']}

    def worker():
        while not stopping.is_set():
            job=store.claim_job()
            if job is None:
                wake.wait(0.4); wake.clear(); continue
            output=config.assets_dir / f"{identifier()}.mp4"
            def cancelled():
                current=store.get('job',job['id'])
                return stopping.is_set() or current is None or current['status']=='cancelled'
            def progress(value):
                with store.lock:
                    current=store.get('job',job['id'])
                    if current and current['status']=='running':
                        store.patch('job',job['id'],progress=max(1,min(99,int(value))))
            try:
                params=job['params']; capture_report=None
                if job['type']=='record':
                    snapshot=params['flow']
                    plan=FlowInput.model_validate({k:snapshot[k] for k in FlowInput.model_fields if k in snapshot})
                    capture_report=flow.record_flow(plan,output,progress,cancelled)
                    name=f"{snapshot['name']} recording.mp4"
                elif job['type']=='generate':
                    shot=params['shot']
                    reference=asset_path(require('asset',shot['reference_asset_id'])) if shot.get('reference_asset_id') else None
                    if shot['provider']=='preview':
                        render.render_preview(shot,reference,output,progress,cancelled)
                    elif shot['provider']=='recording':
                        video=asset_path(require('asset',shot['video_asset_id']))
                        render.render_recording(shot,video,output,progress,cancelled)
                    else:
                        comfy.render_comfy(shot,params['workflow'],reference,output,params['comfy_url'],progress,cancelled)
                    name=f"{shot['name']}.mp4"
                elif job['type']=='export':
                    clips=[asset_path(require('asset',id)) for id in params['asset_ids']]
                    audio=asset_path(require('asset',params['audio_asset_id'])) if params.get('audio_asset_id') else None
                    render.render_export(clips,output,params['width'],params['height'],params['fps'],audio,progress,cancelled,transition=params.get('transition','cut'),transition_duration=params.get('transition_duration',0.35))
                    name='Frameva launch film.mp4'
                else:
                    raise ValueError('Unsupported render job type.')
                metadata=render.validate_media(output,'video/mp4')
                if metadata['kind']!='video': raise ValueError('Renderer did not return a video.')
                with store.lock:
                    if cancelled(): raise render.RenderCancelled()
                    asset=asset_record(output,job['project_id'],name,metadata,job['id'])
                    if capture_report is not None:
                        if not isinstance(capture_report,dict) or capture_report.get('status')!='completed':
                            raise ValueError('The browser flow did not return a completed capture report.')
                        if len(json.dumps(capture_report,allow_nan=False).encode())>1024*1024:
                            raise ValueError('Capture report exceeds the metadata limit.')
                        asset['capture_report']=capture_report
                        asset['recording_kind']='browser-flow'
                        asset['flow_id']=params['flow']['id']
                    if store.finalize_job(job['id'],asset) is None:
                        raise render.RenderCancelled()
            except render.RenderCancelled:
                output.unlink(missing_ok=True)
                current=store.get('job',job['id'])
                if current and current['status']!='cancelled':
                    store.patch('job',job['id'],status='failed' if stopping.is_set() else 'cancelled',error='Server stopped during render; retry to resume.' if stopping.is_set() else None)
            except Exception as exc:
                output.unlink(missing_ok=True)
                current=store.get('job',job['id'])
                if current and current['status']!='cancelled':
                    message=exc.detail if isinstance(exc,HTTPException) else str(exc)
                    # Never expose private credentials or host paths in job failures.
                    message=str(message).replace(config.token,'[redacted]').replace(str(config.data_dir),'[data]')
                    store.patch('job',job['id'],status='failed',error=message[:2000] or 'Render failed.')
                log.warning('Render failed (%s): %s',job['id'],type(exc).__name__)

    @asynccontextmanager
    async def lifespan(app):
        lock_handle=(config.data_dir/'server.lock').open('a+b')
        try:
            if platform.system()=='Windows':
                import msvcrt
                lock_handle.seek(0); lock_handle.write(b'0'); lock_handle.flush(); lock_handle.seek(0)
                msvcrt.locking(lock_handle.fileno(),msvcrt.LK_NBLCK,1)
            else:
                import fcntl
                fcntl.flock(lock_handle.fileno(),fcntl.LOCK_EX|fcntl.LOCK_NB)
        except OSError as exc:
            lock_handle.close()
            raise RuntimeError('Another Frameva server is using this data directory. Stop it before starting another.') from exc
        stopping.clear(); store.recover()
        thread=threading.Thread(target=worker,name='frameva-render',daemon=True)
        thread.start(); app.state.worker=thread
        try: yield
        finally:
            stopping.set(); wake.set(); thread.join(timeout=45)
            if platform.system()=='Windows':
                import msvcrt
                lock_handle.seek(0); msvcrt.locking(lock_handle.fileno(),msvcrt.LK_UNLCK,1)
            else:
                import fcntl
                fcntl.flock(lock_handle.fileno(),fcntl.LOCK_UN)
            lock_handle.close()

    app=FastAPI(title='Frameva',version=__version__,lifespan=lifespan,docs_url=None,redoc_url=None,openapi_url=None)
    app.state.store=store; app.state.config=config

    @app.middleware('http')
    async def guard(request: Request, call_next):
        raw_host=request.headers.get('host','')
        try: hostname=urlsplit('//'+raw_host).hostname
        except ValueError: hostname=None
        trusted={str(host).strip('[]').lower() for host in config.allowed_hosts}
        if hostname not in trusted:
            return JSONResponse({'detail':'Untrusted host.'},status_code=400)
        origin=request.headers.get('origin')
        if origin:
            try:
                parsed=urlsplit(origin)
                if parsed.scheme not in {'http','https'} or parsed.netloc.lower()!=raw_host.lower():
                    return JSONResponse({'detail':'Cross-origin requests are not allowed.'},status_code=403)
            except ValueError:
                return JSONResponse({'detail':'Invalid origin.'},status_code=403)
        limit=(config.max_source_bytes+1024*1024 if request.url.path.endswith('/source') else config.max_upload_bytes+1024*1024) if 'multipart/form-data' in request.headers.get('content-type','') else 2*1024*1024
        # Bound the actual body too: Content-Length may be absent for chunked requests.
        received=0
        original_receive=request._receive
        async def limited_receive():
            nonlocal received
            message=await original_receive()
            received+=len(message.get('body',b''))
            if received>limit: raise HTTPException(413,'Request is too large.')
            return message
        request._receive=limited_receive
        length=request.headers.get('content-length')
        if length:
            try:
                size=int(length)
                if size<0 or size>limit: return JSONResponse({'detail':'Request is too large.'},status_code=413)
            except ValueError:
                return JSONResponse({'detail':'Invalid content length.'},status_code=400)
        path=request.url.path
        if path.startswith('/api') and path not in {'/api/health','/api/session'}:
            authorization=request.headers.get('authorization','')
            bearer=authorization[7:] if authorization.startswith('Bearer ') else ''
            authenticated=bool(bearer) and hmac.compare_digest(bearer.encode(),config.token.encode())
            cookie=request.cookies.get(SESSION_COOKIE,'')
            if not authenticated and cookie:
                authenticated=sessions.get(cookie,0)>time.time()
            if not authenticated: return JSONResponse({'detail':'Sign in to your local Frameva studio.'},status_code=401)
        response=await call_next(request)
        response.headers['X-Content-Type-Options']='nosniff'
        response.headers['Referrer-Policy']='no-referrer'
        response.headers['X-Frame-Options']='DENY'
        response.headers['Content-Security-Policy']="default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' blob: data:; media-src 'self' blob:; connect-src 'self'; font-src 'self'; object-src 'none'; base-uri 'self'; frame-ancestors 'none'; form-action 'self'"
        if path.startswith('/api'): response.headers['Cache-Control']='no-store'
        return response

    @app.exception_handler(ValueError)
    async def invalid_value(request,exc):
        return JSONResponse({'detail':str(exc)[:2000]},status_code=422)

    @app.exception_handler(ValidationError)
    async def invalid_model(request,exc):
        return JSONResponse({'detail':'Invalid input: '+str(exc)[:1500]},status_code=422)

    @app.get('/api/health')
    def health(): return {'status':'ok','version':__version__}

    @app.post('/api/session')
    def login(data: SessionInput, request: Request):
        client=request.client.host if request.client else 'local'
        current=time.time()
        attempts[client]=[x for x in attempts.get(client,[]) if x>current-60]
        if len(attempts[client])>=20: raise HTTPException(429,'Too many sign-in attempts. Wait one minute.')
        if not hmac.compare_digest(data.token.encode(),config.token.encode()):
            attempts[client].append(current)
            raise HTTPException(401,'Incorrect Frameva token.')
        for key,expires in list(sessions.items()):
            if expires<current: sessions.pop(key,None)
        if len(sessions)>=100: sessions.pop(next(iter(sessions)))
        session=secrets.token_urlsafe(32); sessions[session]=current+86400
        response=JSONResponse({'status':'signed_in'})
        response.set_cookie(SESSION_COOKIE,session,httponly=True,samesite='strict',secure=request.url.scheme=='https',max_age=86400,path='/')
        return response

    @app.delete('/api/session')
    def logout(request: Request):
        sessions.pop(request.cookies.get(SESSION_COOKIE,''),None)
        response=JSONResponse({'status':'signed_out'}); response.delete_cookie(SESSION_COOKIE,path='/')
        return response

    @app.get('/api/config')
    def get_config():
        return {'version':__version__,'platform':platform.system(),'ffmpeg_available':bool(render.ffmpeg_path()),
                'comfy_url':require('setting','renderer')['comfy_url'],'data_dir':str(config.data_dir),
                'providers':[{'id':'recording','name':'Live recording','available':bool(render.ffmpeg_path()),'description':'Real app video with trim, speed, focus, motion and original audio.'},{'id':'preview','name':'Product motion','available':bool(render.ffmpeg_path()),'description':'Deterministic screenshot motion and typography on your CPU. No generative model.'},
                             {'id':'comfyui','name':'AI footage · ComfyUI','available':True,'description':'Requires a running trusted ComfyUI renderer, installed model and compatible workflow.'}],
                'models':catalog.MODELS,'camera_presets':catalog.CAMERA_PRESETS,'style_presets':catalog.STYLE_PRESETS,
                'workflows':store.list('workflow')}

    @app.put('/api/config')
    def set_config(data: RendererInput):
        url=comfy.validate_base_url(data.comfy_url)
        store.put('setting',{'id':'renderer','comfy_url':url})
        return get_config()

    @app.get('/api/renderer/status')
    def renderer_status(): return comfy.renderer_status(require('setting','renderer')['comfy_url'])

    @app.get('/api/projects')
    def projects(): return sorted(store.list('project'),key=lambda x:x['updated_at'],reverse=True)

    @app.post('/api/projects',status_code=201)
    def create_project(data: ProjectInput):
        return store.put('project',{**data.model_dump(),'id':identifier(),'created_at':now(),'updated_at':now()})

    @app.get('/api/projects/{project_id}')
    def project(project_id: str): return require('project',project_id)

    @app.patch('/api/projects/{project_id}')
    def update_project(project_id: str,data: ProjectPatch):
        require('project',project_id)
        return store.patch('project',project_id,**data.model_dump(exclude_unset=True,exclude_none=True))

    @app.delete('/api/projects/{project_id}')
    def delete_project(project_id: str):
        with store.lock:
            require('project',project_id)
            if pending(project_id): raise HTTPException(409,'Cancel or finish active renders before deleting this project.')
            assets=store.list('asset',project_id)
            store.delete_project(project_id)
            for asset in assets: asset_path(asset).unlink(missing_ok=True)
        return {'deleted':True}

    @app.get('/api/projects/{project_id}/shots')
    def shots(project_id: str):
        require('project',project_id); return [{**shot_signature(shot),**shot} for shot in store.list('shot',project_id)]

    @app.post('/api/projects/{project_id}/shots',status_code=201)
    def create_shot(project_id: str,data: ShotInput):
        with store.lock:
            require('project',project_id); return new_shot(project_id,data.model_dump())

    @app.put('/api/projects/{project_id}/shots/order')
    def reorder(project_id: str,data: OrderInput):
        with store.lock:
            current=shots(project_id)
            if len(data.shot_ids)!=len(set(data.shot_ids)) or set(data.shot_ids)!={s['id'] for s in current}:
                raise HTTPException(422,'Supply every project shot exactly once.')
            for position,id in enumerate(data.shot_ids): store.patch('shot',id,position=position)
            touch(project_id)
            return store.list('shot',project_id)

    @app.patch('/api/shots/{shot_id}')
    def update_shot(shot_id: str,data: ShotPatch):
        with store.lock:
            current=require('shot',shot_id)
            updated=shot_signature(current); updated.update(data.model_dump(exclude_unset=True))
            updated=ShotInput.model_validate(updated).model_dump()
            validate_shot_refs(updated,current['project_id'])
            result=store.patch('shot',shot_id,**updated); touch(current['project_id'])
            return result

    @app.delete('/api/shots/{shot_id}')
    def delete_shot(shot_id: str):
        with store.lock:
            shot=require('shot',shot_id)
            if any(j['shot_id']==shot_id for j in pending()): raise HTTPException(409,'Cancel or finish this shot’s active renders first.')
            store.delete('shot',shot_id); touch(shot['project_id'])
        return {'deleted':True}

    @app.get('/api/projects/{project_id}/flows')
    def flows(project_id: str):
        require('project',project_id)
        return store.list('flow',project_id)

    @app.post('/api/projects/{project_id}/flows',status_code=201)
    def create_flow(project_id: str,data: FlowInput):
        with store.lock:
            require('project',project_id)
            if len(store.list('flow',project_id))>=200:
                raise HTTPException(409,'A project supports at most 200 browser flows.')
            value={**data.model_dump(mode='json'),'id':identifier(),'project_id':project_id,'created_at':now(),'updated_at':now()}
            store.put('flow',value); touch(project_id)
            return value

    @app.get('/api/flows/{flow_id}')
    def get_flow(flow_id: str): return require('flow',flow_id)

    @app.put('/api/flows/{flow_id}')
    def update_flow(flow_id: str,data: FlowInput):
        with store.lock:
            current=require('flow',flow_id)
            value=store.patch('flow',flow_id,**data.model_dump(mode='json'))
            touch(current['project_id'])
            return value

    @app.delete('/api/flows/{flow_id}')
    def delete_flow(flow_id: str):
        with store.lock:
            current=require('flow',flow_id)
            if any(j['type']=='record' and j['params'].get('flow',{}).get('id')==flow_id for j in pending(current['project_id'])):
                raise HTTPException(409,'Cancel or finish this flow’s active recordings first.')
            store.delete('flow',flow_id); touch(current['project_id'])
            return {'deleted':True}

    @app.post('/api/flows/{flow_id}/record',status_code=202)
    def record_browser_flow(flow_id: str):
        with store.lock:
            current=require('flow',flow_id)
            require('project',current['project_id'])
            return make_job(current['project_id'],'record',{'flow':current})

    @app.get('/api/projects/{project_id}/coverage')
    def coverage(project_id: str):
        require('project',project_id)
        evidence=store.get('source',project_id)
        candidates=evidence['analysis'].get('features',[]) if evidence else []
        known_titles={candidate['title'] for candidate in candidates}
        recordings=[]
        flow_records={record['id']:record for record in store.list('flow',project_id)}
        def plan_signature(value):
            return FlowInput.model_validate({key:item for key,item in value.items() if key in FlowInput.model_fields}).model_dump(mode='json')
        for job in store.list('job',project_id):
            if job['type']!='record': continue
            snapshot=job['params']['flow']
            asset=store.get('asset',job['asset_id']) if job.get('asset_id') else None
            current=flow_records.get(snapshot['id'])
            titles=snapshot.get('feature_titles',[])
            recordings.append({'flow_id':snapshot['id'],'name':snapshot['name'],'job_id':job['id'],
                'status':job['status'],'sequence':job['sequence'],'asset_id':asset['id'] if asset else None,
                'recorded_at':job['updated_at'],'feature_titles':titles,
                'matched_feature_titles':[title for title in titles if title in known_titles],
                'unmatched_feature_titles':[title for title in titles if title not in known_titles],
                'recording_available':bool(asset and asset_path(asset).is_file()),
                'capture_report':asset.get('capture_report') if asset else None,
                'flow_currently_exists':bool(current),
                'matches_current_plan':bool(current and plan_signature(current)==plan_signature(snapshot))})
        successful=[item for item in recordings if item['status']=='succeeded' and item['recording_available'] and item['capture_report'] and item['capture_report'].get('status')=='completed']
        annotated=[]
        for candidate in candidates:
            matches=[record for record in successful if candidate['title'] in record['feature_titles']]
            refs=[{key:record[key] for key in ('flow_id','name','job_id','asset_id','recorded_at','matches_current_plan')} for record in matches]
            annotated.append({**candidate,'source_status':candidate.get('status','candidate'),
                              'status':'recorded' if refs else 'unrecorded','recordings':refs})
        recorded=sum(candidate['status']=='recorded' for candidate in annotated)
        unrecorded_flows=[]
        for current in flow_records.values():
            completed=[item for item in successful if item['flow_id']==current['id']]
            if not any(item['matches_current_plan'] for item in completed):
                unrecorded_flows.append({'flow_id':current['id'],'name':current['name'],
                    'reason':'Current plan changed since its completed recording; record it again.' if completed else 'This flow has no completed recording for its current plan.'})
        return {'schema_version':1,'project_id':project_id,'coverage_kind':'explicit_recorded_steps',
                'source_candidates':annotated,'unmapped_candidates':[candidate for candidate in annotated if candidate['status']=='unrecorded'],
                'recorded_flows':successful,'flow_recordings':recordings,
                'unmapped_flows':[item for item in successful if not item['matched_feature_titles']],
                'flows_with_unrecorded_changes':unrecorded_flows,
                'totals':{'candidate_count':len(annotated),'recorded_candidate_count':recorded,
                          'unrecorded_candidate_count':len(annotated)-recorded,
                          'recorded_percent':round(100*recorded/len(annotated),1) if annotated else None,
                          'completed_recording_count':len(successful)},
                'feature_mapping_status':'explicit' if recorded else 'unmapped','all_features_verified':False,
                'all_candidates_recorded':bool(annotated and recorded==len(annotated)),
                'explanation':'Recorded coverage uses exact source-feature titles explicitly mapped in successful recording snapshots. It documents those recorded steps, not feature correctness or all possible application behavior. Edited plans require a new recording.'}

    @app.get('/api/assets')
    def assets(project_id: str | None=None):
        if project_id: require('project',project_id)
        return [public(a) for a in store.list('asset',project_id)]

    @app.post('/api/assets',status_code=201)
    async def upload_asset(project_id: str=Form(...),file: UploadFile=File(...)):
        require('project',project_id)
        path=config.assets_dir / f'{identifier()}.upload'
        size=0
        try:
            with path.open('wb') as out:
                while chunk:=await file.read(1024*1024):
                    size+=len(chunk)
                    if size>config.max_upload_bytes: raise HTTPException(413,'Assets must be 256 MiB or smaller.')
                    out.write(chunk)
            metadata=await run_in_threadpool(render.validate_media,path,file.content_type or '')
            name=Path((file.filename or 'Uploaded asset').replace('\\','/')).name[:180]
            with store.lock:
                require('project',project_id)
                asset=add_asset(path,project_id,name,metadata); touch(project_id)
            return public(asset)
        except Exception:
            path.unlink(missing_ok=True); raise
        finally: await file.close()

    @app.get('/api/assets/{asset_id}/file')
    def asset_file(asset_id: str,download: bool=False):
        asset=require('asset',asset_id); path=asset_path(asset)
        if not path.is_file(): raise HTTPException(404,'Asset file is missing.')
        return FileResponse(path,media_type=asset['mime_type'],filename=asset['name'] if download else None,content_disposition_type='attachment' if download else 'inline')

    @app.delete('/api/assets/{asset_id}')
    def delete_asset(asset_id: str):
        with store.lock:
            asset=require('asset',asset_id)
            if any(s.get('reference_asset_id')==asset_id or s.get('video_asset_id')==asset_id for s in store.list('shot')):
                raise HTTPException(409,'This asset is referenced by a shot.')
            for job in pending():
                params=job['params']
                if asset_id in params.get('asset_ids',[]) or params.get('audio_asset_id')==asset_id or params.get('shot',{}).get('reference_asset_id')==asset_id or params.get('shot',{}).get('video_asset_id')==asset_id:
                    raise HTTPException(409,'This asset is in use by a queued or running render.')
            store.delete('asset',asset_id); asset_path(asset).unlink(missing_ok=True)
        return {'deleted':True}

    @app.get('/api/jobs')
    def jobs(project_id: str | None=None):
        if project_id: require('project',project_id)
        return sorted(store.list('job',project_id),key=lambda j:j['sequence'],reverse=True)

    @app.post('/api/jobs',status_code=202)
    def create_job(data: JobInput):
        with store.lock:
            shot=require('shot',data.shot_id)
            return make_job(shot['project_id'],'generate',generation_params(shot),shot['id'])

    @app.post('/api/projects/{project_id}/generate',status_code=202)
    def generate_project(project_id: str):
        with store.lock:
            selected=shots(project_id)
            if not selected: raise HTTPException(409,'Add storyboard shots first.')
            if len(pending())+len(selected)>200: raise HTTPException(409,'Not enough space in the render queue.')
            all_params=[generation_params(shot) for shot in selected]
            return [make_job(project_id,'generate',params,shot['id']) for shot,params in zip(selected,all_params)]

    @app.get('/api/jobs/{job_id}')
    def get_job(job_id: str): return require('job',job_id)

    @app.post('/api/jobs/{job_id}/cancel')
    def cancel_job(job_id: str):
        with store.lock:
            job=require('job',job_id)
            if job['status'] not in ACTIVE: return job
            return store.patch('job',job_id,status='cancelled',error=None)

    @app.post('/api/jobs/{job_id}/retry',status_code=202)
    def retry_job(job_id: str):
        with store.lock:
            job=require('job',job_id)
            if job['status'] not in {'failed','cancelled'}: raise HTTPException(409,'Only failed or cancelled jobs can be retried.')
            require('project',job['project_id'])
            if job['type']=='generate':
                # Replay the saved settings rather than silently using edited input.
                validate_shot_refs(job['params']['shot'],job['project_id'])
                require('shot',job['shot_id'])
            elif job['type']=='record':
                recorded_flow=require('flow',job['params']['flow']['id'])
                if recorded_flow['project_id']!=job['project_id']:
                    raise HTTPException(409,'The recorded flow no longer belongs to this project.')
                FlowInput.model_validate({k:v for k,v in job['params']['flow'].items() if k in FlowInput.model_fields})
            elif job['type']=='export':
                for id in job['params']['asset_ids']: require('asset',id)
                if job['params'].get('audio_asset_id'): require('asset',job['params']['audio_asset_id'])
            return make_job(job['project_id'],job['type'],job['params'],job['shot_id'])

    @app.post('/api/projects/{project_id}/export',status_code=202)
    def export_project(project_id: str,data: ExportInput):
        with store.lock:
            all_shots=shots(project_id)
            selected=all_shots
            if data.shot_ids is not None:
                if len(set(data.shot_ids))!=len(data.shot_ids) or not set(data.shot_ids)<={s['id'] for s in all_shots}:
                    raise HTTPException(422,'Export shot IDs must be distinct and belong to this project.')
                selected=[s for s in all_shots if s['id'] in data.shot_ids]
            if not selected: raise HTTPException(409,'Choose at least one storyboard shot.')
            asset_ids=[]; source_jobs=[]; clip_durations=[]
            successful=[j for j in store.list('job',project_id) if j['type']=='generate' and j['status']=='succeeded']
            for shot in selected:
                candidates=sorted((j for j in successful if j['shot_id']==shot['id']),key=lambda j:j['sequence'],reverse=True)
                if not candidates: raise HTTPException(409,f"Render shot '{shot['name']}' before exporting.")
                latest=candidates[0]
                if shot_signature(shot)!=shot_signature(latest['params']['shot']):
                    raise HTTPException(409,f"Shot '{shot['name']}' changed after its latest render. Render it again before exporting.")
                asset=require('asset',latest['asset_id'])
                if asset['kind']!='video' or not asset_path(asset).is_file(): raise HTTPException(409,'A rendered clip is missing; render the shot again.')
                asset_ids.append(asset['id']); source_jobs.append(latest['id'])
                clip_durations.append(float(asset.get('duration') or latest['params']['shot']['duration']))
            if len(asset_ids)>1 and data.transition=='crossfade' and data.transition_duration>min(clip_durations)/2:
                raise HTTPException(422,'The crossfade duration must be at most half the shortest clip.')
            if data.audio_asset_id:
                audio=require('asset',data.audio_asset_id)
                if audio['project_id']!=project_id or audio['kind']!='audio': raise HTTPException(422,'The soundtrack must be an audio asset in this project.')
            params={**data.model_dump(),'asset_ids':asset_ids,'shot_ids':[s['id'] for s in selected],'source_job_ids':source_jobs}
            return make_job(project_id,'export',params)

    @app.get('/api/workflows')
    def workflows(): return store.list('workflow')

    @app.get('/api/workflows/wan-template')
    def wan_template():
        workflow=store.get('workflow','wan22-5b-t2v')
        if workflow is None: raise HTTPException(404,'Import a trusted API-format ComfyUI workflow; see docs/WORKFLOWS.md.')
        return workflow

    @app.post('/api/workflows',status_code=201)
    def create_workflow(data: WorkflowInput):
        value=data.model_dump()
        if len(json.dumps(value))>1024*1024: raise HTTPException(413,'Workflow JSON must be at most 1 MiB.')
        comfy.validate_workflow(value['graph'],value['bindings'])
        return store.put('workflow',{**value,'id':identifier(),'builtin':False,'created_at':now(),'updated_at':now()})

    @app.delete('/api/workflows/{workflow_id}')
    def delete_workflow(workflow_id: str):
        with store.lock:
            workflow=require('workflow',workflow_id)
            if workflow.get('builtin'): raise HTTPException(409,'Bundled workflows cannot be deleted.')
            if any(s.get('workflow_id')==workflow_id for s in store.list('shot')): raise HTTPException(409,'This workflow is referenced by a shot.')
            store.delete('workflow',workflow_id)
        return {'deleted':True}

    def validate_analysis(analysis: dict) -> dict:
        if len(json.dumps(analysis,allow_nan=False).encode())>1024*1024: raise HTTPException(413,'Source analysis must be at most 1 MiB.')
        if analysis.get('schema_version')!=1: raise HTTPException(422,'Source analysis schema_version must be 1.')
        for field in ('name','product_name','description','summary'):
            if not isinstance(analysis.get(field,''),str) or len(analysis.get(field,''))>16000: raise HTTPException(422,f'Invalid source analysis {field}.')
        for field in ('frameworks','warnings','files'):
            value=analysis.get(field,[])
            if not isinstance(value,list) or len(value)>2000 or any(not isinstance(x,str) or len(x)>2000 for x in value): raise HTTPException(422,f'Invalid source analysis {field}.')
        features=analysis.get('features',[])
        if not isinstance(features,list) or len(features)>100: raise HTTPException(422,'Invalid source features.')
        for feature in features:
            if not isinstance(feature,dict) or not isinstance(feature.get('title'),str) or not isinstance(feature.get('description',''),str): raise HTTPException(422,'Invalid feature evidence.')
            if len(feature['title'])>200 or len(feature.get('description',''))>2000: raise HTTPException(422,'Feature text is too long.')
            evidence=feature.get('evidence',[])
            if not isinstance(evidence,list) or len(evidence)>100: raise HTTPException(422,'Invalid feature evidence.')
            for item in evidence:
                if not isinstance(item,dict) or not isinstance(item.get('path',''),str) or not isinstance(item.get('excerpt',''),str): raise HTTPException(422,'Invalid feature evidence.')
                if len(item.get('path',''))>400 or len(item.get('excerpt',''))>4000: raise HTTPException(422,'Feature evidence is too long.')
        routes=analysis.get('routes',[])
        if not isinstance(routes,list) or len(routes)>2000 or any(not isinstance(r,dict) or not isinstance(r.get('path',''),str) or not isinstance(r.get('kind',''),str) for r in routes):
            raise HTTPException(422,'Invalid source routes.')
        stats=analysis.get('stats',{})
        if not isinstance(stats,dict) or any(not isinstance(stats.get(k,0),int) for k in ('files_scanned','bytes_scanned','files_skipped')):
            raise HTTPException(422,'Invalid source statistics.')
        # Retain only supported evidence fields. Source never authorizes tools or commands.
        allowed={'schema_version','name','product_name','description','summary','frameworks','features','routes','files','stats','warnings'}
        analysis={key:value for key,value in analysis.items() if key in allowed}
        analysis['trust']='untrusted_source_evidence'
        return analysis

    @app.post('/api/projects/{project_id}/source')
    async def upload_source(project_id: str,file: UploadFile=File(...)):
        require('project',project_id)
        try:
            data=await file.read(config.max_source_bytes+1)
            if len(data)>config.max_source_bytes: raise HTTPException(413,'Source ZIP must be at most 64 MiB.')
            analysis=validate_analysis(await run_in_threadpool(source.inspect_archive,data))
            with store.lock:
                require('project',project_id)
                store.put('source',{'id':project_id,'project_id':project_id,'analysis':analysis,'created_at':now()}); touch(project_id)
            return analysis
        finally: await file.close()

    @app.post('/api/projects/{project_id}/source-analysis')
    def set_source_analysis(project_id: str,data: SourceAnalysisInput):
        with store.lock:
            require('project',project_id)
            analysis=validate_analysis(data.analysis)
            store.put('source',{'id':project_id,'project_id':project_id,'analysis':analysis,'created_at':now()}); touch(project_id)
            return analysis

    @app.get('/api/projects/{project_id}/source')
    def get_source(project_id: str):
        require('project',project_id)
        record=store.get('source',project_id)
        if record is None: raise HTTPException(404,'Import source code to inspect this product.')
        return record['analysis']

    @app.post('/api/projects/{project_id}/launch-plan',status_code=201)
    def launch_plan(project_id: str,data: LaunchPlanInput):
        with store.lock:
            project=require('project',project_id)
            analysis=get_source(project_id)
            planned=[ShotInput.model_validate(s).model_dump() for s in source.build_launch_plan(analysis,project['name'],data.aspect)]
            if data.replace_existing:
                if pending(project_id): raise HTTPException(409,'Finish or cancel renders before replacing the storyboard.')
                for shot in store.list('shot',project_id): store.delete('shot',shot['id'])
            elif len(store.list('shot',project_id))+len(planned)>200: raise HTTPException(409,'The storyboard would exceed 200 shots.')
            return [new_shot(project_id,shot) for shot in planned]

    @app.get('/api/projects/{project_id}/manifest')
    def manifest(project_id: str):
        project=require('project',project_id)
        records=[]
        for job in store.list('job',project_id):
            params={k:v for k,v in job['params'].items() if k not in {'comfy_url','workflow'}}
            records.append({**public(job),'params':params})
        report=store.get('source',project_id)
        return {'schema_version':1,'application':'Frameva','version':__version__,'exported_at':now(),
                'project':project,'shots':store.list('shot',project_id),
                'assets':[public(a) for a in store.list('asset',project_id)],'jobs':records,
                'flows':store.list('flow',project_id),'coverage':coverage(project_id),
                'source_analysis':report['analysis'] if report else None,
                'note':'Metadata manifest only. Asset media and model weights are not embedded.'}

    static=Path(__file__).parent/'static'
    app.mount('/static',StaticFiles(directory=static),name='static')
    @app.get('/')
    def index(): return FileResponse(static/'index.html')
    return app
