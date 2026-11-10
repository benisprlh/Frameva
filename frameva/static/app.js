'use strict';

const $ = (selector, root = document) => root.querySelector(selector);
const $$ = (selector, root = document) => [...root.querySelectorAll(selector)];
const esc = value => String(value ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const idpath = value => encodeURIComponent(value);
const state = { authenticated:false, config:{}, projects:[], project:null, shots:[], assets:[], jobs:[], source:null, workflows:[], selected:null, tab:'storyboard', page:'project', dirty:false, polling:false, previewMode:'auto', sourceError:null, modalHandler:null, loadedAsset:null, requestVersion:0, lastMetadataSync:0, rendererConnected:false };
const formatBytes = n => n >= 1048576 ? `${(n / 1048576).toFixed(1)} MB` : `${Math.max(1,Math.round((n || 0) / 1024))} KB`;
const formatTime = value => { const d = new Date(value); return Number.isNaN(+d) ? '' : d.toLocaleTimeString([], {hour:'2-digit',minute:'2-digit'}); };
const assetURL = (id,download=false) => `/api/assets/${idpath(id)}/file${download?'?download=true':''}`;
const selectedShot = () => state.shots.find(s => s.id === state.selected);
const newestJobFirst = (a,b) => Number.isFinite(a.sequence)&&Number.isFinite(b.sequence) ? b.sequence-a.sequence : String(b.created_at).localeCompare(String(a.created_at));
const latestJob = shotId => [...state.jobs].filter(j=>j.shot_id===shotId && j.type==='generate').sort(newestJobFirst)[0];
const successfulJob = shotId => [...state.jobs].filter(j=>j.shot_id===shotId&&j.type==='generate'&&j.status==='succeeded'&&j.asset_id).sort(newestJobFirst)[0];
const renderFields = ['name','prompt','negative_prompt','provider','workflow_id','reference_asset_id','video_asset_id','trim_start','playback_rate','focus_x','focus_y','zoom','keep_audio','camera','style','width','height','duration','fps','seed','headline','caption','brand_color','layout'];
const recordingDefaults = {video_asset_id:null,trim_start:0,playback_rate:1,focus_x:0.5,focus_y:0.5,zoom:1,keep_audio:true};
function renderFresh(shot, job) {
  if (!shot || !job) return false;
  const snapshot = job.params?.shot || job.params;
  if (!snapshot || snapshot.width === undefined) return false;
  return renderFields.every(key => {
    const left = shot[key] ?? recordingDefaults[key] ?? '', right = snapshot[key] ?? recordingDefaults[key] ?? '';
    return String(left) === String(right);
  });
}
const activeJobs = () => state.jobs.filter(j=>['running','queued'].includes(j.status));

function toast(message, error=false) {
  const node = document.createElement('div'); node.className=`toast${error?' error':''}`; node.textContent=message;
  $('#toast-stack').append(node); setTimeout(()=>node.remove(),error?8500:4800);
}
function detailMessage(data) {
  const detail=data?.detail ?? data?.error ?? data?.message;
  if(Array.isArray(detail)) return detail.map(x=>`${(x.loc||[]).filter(y=>y!=='body').join('.')}: ${x.msg||'Invalid value'}`).join('; ');
  return typeof detail==='string'?detail:detail?JSON.stringify(detail):'Request failed. Please try again.';
}
async function api(path, options={}) {
  const opts={credentials:'same-origin',...options,headers:{...(options.headers||{})}};
  if(options.body && !(options.body instanceof FormData)) {opts.headers['Content-Type']='application/json';opts.body=JSON.stringify(options.body);}
  const response=await fetch(`/api${path}`,opts);
  let data; const type=response.headers.get('content-type')||'';
  if(type.includes('application/json')) data=await response.json(); else data=await response.text();
  if(!response.ok){ if(response.status===401 && state.authenticated){state.authenticated=false;showLogin();} throw new Error(typeof data==='string'?data:detailMessage(data)); }
  return data;
}
async function runBusy(button, task) {
  if(button?.disabled)return;
  const original=button?.innerHTML;
  if(button){button.disabled=true;button.innerHTML='<span class="spinner"></span> Working';}
  try{return await task();} catch(error){toast(error.message||'Something went wrong.',true);}
  finally{if(button?.isConnected){button.disabled=false;button.innerHTML=original;}}
}
function showLogin(message='') {$('#app').hidden=true;$('#login').hidden=false;$('#login-error').textContent=message;setTimeout(()=>$('#token').focus(),50);}
async function boot() {
  try {
    const fragment=new URLSearchParams(location.hash.slice(1)); const token=fragment.get('token');
    if(token){history.replaceState(null,'',location.pathname+location.search);await api('/session',{method:'POST',body:{token}});}
    await loadWorkspace();
  } catch(error){showLogin(error.message.includes('Unauthorized')?'':error.message);}
}
async function loadWorkspace() {
  const [config,projects,workflows]=await Promise.all([api('/config'),api('/projects'),api('/workflows')]);
  Object.assign(state,{config,projects,workflows,authenticated:true});
  $('#login').hidden=true;$('#app').hidden=false;$('#version-label').textContent=`FRAMEVA ${config.version||'0.1'}`;
  $('#engine-dot').classList.remove('ready');$('#engine-dot').title='AI renderer connection has not been tested';state.rendererConnected=false;
  renderSidebar();
  const remembered=localStorage.getItem('frameva.last-project');
  const project=projects.find(p=>p.id===remembered)||projects[0];
  if(project)await selectProject(project.id);else renderWelcome();
}
function renderSidebar(){
  $('#project-count').textContent=state.projects.length;
  $('#project-list').innerHTML=state.projects.length?state.projects.map(p=>`<button class="project-item${p.id===state.project?.id&&state.page==='project'?' active':''}" data-action="select-project" data-id="${esc(p.id)}"><span class="project-avatar">${esc((p.name||'P').slice(0,2).toUpperCase())}</span><span class="project-label">${esc(p.name)}</span>${p.id===state.project?.id&&state.page==='project'?'<span class="project-arrow">↗</span>':''}</button>`).join(''):'<p class="sidebar-empty">Your next launch starts here.<br>Create your first production.</p>';
  $$('.nav-button').forEach(n=>n.classList.toggle('active',n.dataset.action===state.page));
}
async function selectProject(id){
  if(state.dirty&&!confirm('You have unsaved shot changes. Discard them?'))return;
  state.dirty=false;state.page='project';state.tab='storyboard';state.selected=null;state.previewMode='auto';
  const version=++state.requestVersion;
  $('#main').innerHTML='<div class="loading-page"><span class="spinner"></span> Opening production</div>';
  const [project,shots,assets,jobs,source]=await Promise.all([api(`/projects/${idpath(id)}`),api(`/projects/${idpath(id)}/shots`),api(`/assets?project_id=${idpath(id)}`),api(`/jobs?project_id=${idpath(id)}`),api(`/projects/${idpath(id)}/source`).catch(()=>null)]);
  if(version!==state.requestVersion)return;
  Object.assign(state,{project,shots,assets,jobs,source,selected:shots[0]?.id||null});
  localStorage.setItem('frameva.last-project',id);$('#sidebar').classList.remove('open');renderSidebar();renderProject();
}
async function refreshProject({preserveTab=true}={}){
  if(!state.project)return;
  const projectId=state.project.id;
  const [shots,assets,jobs,source]=await Promise.all([api(`/projects/${idpath(projectId)}/shots`),api(`/assets?project_id=${idpath(projectId)}`),api(`/jobs?project_id=${idpath(projectId)}`),api(`/projects/${idpath(projectId)}/source`).catch(()=>null)]);
  if(projectId!==state.project?.id)return;
  Object.assign(state,{shots,assets,jobs,source});if(!shots.some(s=>s.id===state.selected))state.selected=shots[0]?.id||null;
  state.dirty=false;if(!preserveTab)state.tab='storyboard';renderProject();
}
function renderWelcome(){
  state.page='home';state.project=null;$('#project-name').textContent='Your productions';$('#project-menu').hidden=true;$('#export-button').hidden=true;renderSidebar();
  $('#main').innerHTML=`<section class="welcome-page"><div class="welcome-header"><div><p class="eyebrow">THE OPEN-SOURCE PRODUCT FILM STUDIO</p><h1>You built something.<br>Now make it <em>seen.</em></h1><p class="muted">Turn your source code into a launch story. Bring your app's real screens, shape every shot, and leave with a film worth sharing.</p><div class="welcome-actions"><button class="button primary" data-action="new-project">Create your first film <span>↗</span></button><button class="button subtle" data-action="integrations">Connect an agent</button></div></div><span class="welcome-index">YOUR VISION. EVERY FRAME. / 01</span></div><div class="welcome-visual" aria-label="Illustration of source code becoming a product film"><div class="visual-code"><div class="code-header"><span>your-product / source</span><span>⌘</span></div><pre><span>const</span> yourNextLaunch = {\n  product: <span>yourApp</span>,\n  story: <span>yourVision</span>,\n  possibilities: <span>∞</span>\n}</pre></div><div class="visual-arrow">→</div><div class="visual-film"><small>INTRODUCING</small><strong>Your next<br>big thing.</strong><span>Made by you. Brought to life.</span><div class="play-circle">▶</div></div><span class="visual-caption">SOURCE → STORY → SCREEN · ILLUSTRATION</span></div><div class="welcome-steps"><div class="welcome-step"><span class="step-number">01 /</span><div><h3>Start with what you've built</h3><p>Import a source ZIP, or let Codex and Claude Code inspect your repository.</p></div></div><div class="welcome-step"><span class="step-number">02 /</span><div><h3>Give your product a story</h3><p>Draft a storyboard from code evidence. Add real screenshots and fine-tune every scene.</p></div></div><div class="welcome-step"><span class="step-number">03 /</span><div><h3>Make the launch yours</h3><p>Render local motion graphics, add optional AI footage, and export your finished film.</p></div></div></div></section>`;
}
function projectTabs(){return `<nav class="project-tabs" aria-label="Project views">${[['storyboard','Storyboard',state.shots.length],['source','Source & story',null],['assets','Media library',state.assets.length],['queue','Render queue',null]].map(([id,label,count])=>`<button class="tab${state.tab===id?' active':''}" data-action="tab" data-tab="${id}" aria-current="${state.tab===id?'page':'false'}">${label}${count!==null?`<span class="tab-count">${count}</span>`:''}${id==='queue'&&activeJobs().length?'<span class="active-job"></span>':''}</button>`).join('')}</nav>`;}
function renderProject(){
  if(!state.project)return renderWelcome();state.page='project';renderSidebar();
  $('#project-name').textContent=state.project.name;$('#project-menu').hidden=false;$('#export-button').hidden=false;
  const duration=state.shots.reduce((total,s)=>total+(Number(s.duration)||0),0);
  $('#main').innerHTML=`<section class="project-heading"><div><p class="eyebrow">PRODUCT LAUNCH / PRODUCTION</p><h1>${esc(state.project.name)}</h1><p class="description">${esc(state.project.description||'A new story for what you’ve built.')}</p></div><div class="project-meta"><span>${state.shots.length} shots</span><i class="dot"></i><span>${Number(duration.toFixed(1))}s timeline</span><i class="dot"></i><span>Saved locally</span></div></section>${projectTabs()}<div id="project-content"></div>`;
  if(state.tab==='storyboard')renderStudio();else if(state.tab==='assets')renderAssets();else if(state.tab==='queue')renderQueue();else renderSource();
}
function renderStudio(){
  $('#project-content').innerHTML=`<div class="studio-grid"><section class="canvas-area"><div class="section-toolbar"><span class="small-title">${state.shots.length?'DIRECTOR’S VIEW':'YOUR FIRST SCENE STARTS HERE'}</span><div class="tools"><button class="button subtle compact" data-action="upload-assets">↑ Add media</button><button class="button subtle compact" data-action="new-shot">＋ New shot</button></div></div><div id="canvas-wrap"></div><div class="storyboard-heading"><h3>Shot sequence <span>${state.shots.length} scenes</span></h3><button class="text-button" data-action="generate-all" ${state.shots.length?'':'disabled'}>Render all <span aria-hidden="true">↗</span></button></div><div id="storyboard-strip" class="storyboard-strip"></div><div id="shot-actions" class="shot-actions"></div><div class="info-strip"><span>⌘</span><div>Built for real product stories. Your source informs the script; your screenshots show the actual app. Product motion runs locally without a GPU.</div></div></section><aside class="inspector" id="inspector" aria-label="Shot settings"></aside></div>`;
  renderCanvas();renderStoryboard();renderInspector();
}
function renderCanvas(){
  const wrap=$('#canvas-wrap');if(!wrap)return;
  const shot=selectedShot();
  if(!shot){wrap.innerHTML=`<div class="empty-panel" style="min-height:320px"><div class="empty-icon">⌁</div><h2>From source to story.</h2><p>Import your repository to draft an evidence-based launch storyboard, or begin with a shot of your own.</p><button class="button primary" data-action="tab" data-tab="source">Start with your source <span>↗</span></button></div>`;return;}
  const output=successfulJob(shot.id);const image=state.assets.find(a=>a.id===shot.reference_asset_id&&a.kind==='image');
  const color=/^#[0-9a-f]{6}$/i.test(shot.brand_color)?shot.brand_color:'#b8ff65';
  const stale=output&&(!renderFresh(shot,output)||!state.assets.some(a=>a.id===output.asset_id));
  const shouldVideo=output&&!stale&&state.previewMode!=='layout';
  const label=shot.provider==='recording'?'LIVE RECORDING':shot.provider==='comfyui'?'AI FOOTAGE':'PRODUCT MOTION';
  wrap.innerHTML=`<div class="canvas${shouldVideo?' video-canvas':''}" style="aspect-ratio:${Number(shot.width)||1280}/${Number(shot.height)||720}">${shouldVideo?`<video controls playsinline preload="metadata" src="${assetURL(output.asset_id)}" aria-label="Rendered ${esc(shot.name)}"></video>`:`<div class="preview-design${image?' with-image':''}" style="--shot-color:${color}"><span class="preview-kicker">${esc(state.project.name).toUpperCase()}</span><h2>${esc(shot.headline||shot.name||'Your next big thing.')}</h2><p>${esc(shot.caption||'Add your headline, bring in a screenshot, and make it move.')}</p>${image?`<div class="browser-frame"><div class="browser-dots"><i></i><i></i><i></i><span>${esc(state.project.name)}</span></div><img src="${assetURL(image.id)}" alt="Reference screenshot for ${esc(shot.name)}"></div>`:''}</div><span class="scene-number">SHOT ${String(state.shots.indexOf(shot)+1).padStart(2,'0')}</span><span class="canvas-corner">${label} / LAYOUT PREVIEW</span><span class="canvas-corner right">${Number(shot.duration)} SECONDS</span>`}</div><div class="canvas-detail"><span>${shouldVideo?'Rendered video':stale?'Settings changed · render again':'Layout reference · rendered typography and animation may differ'} · ${Number(shot.width)} × ${Number(shot.height)} · ${Number(shot.fps)} fps</span><span>${output?`${!stale?`<button class="text-button" style="font-size:9px" data-action="toggle-preview">${shouldVideo?'View layout':'Play render'}</button> &nbsp; `:''}<a href="${assetURL(output.asset_id,true)}" download>${stale?'Previous render':'Download'} ↗</a>`:'Render a shot to preview its motion'}</span></div>`;
  state.loadedAsset=shouldVideo?output.asset_id:null;
}
function renderStoryboard(){
  const strip=$('#storyboard-strip');if(!strip)return;const previousScroll=strip.scrollLeft;
  strip.innerHTML=state.shots.map((shot,index)=>{const image=state.assets.find(a=>a.id===shot.reference_asset_id&&a.kind==='image');const job=latestJob(shot.id);const stale=job?.status==='succeeded'&&!renderFresh(shot,job);return `<button class="shot-card${shot.id===state.selected?' active':''}" data-action="select-shot" data-id="${esc(shot.id)}" aria-label="Shot ${index+1}: ${esc(shot.name)}" aria-pressed="${shot.id===state.selected}"><div class="shot-thumb">${image?`<img src="${assetURL(image.id)}" alt="">`:''}<strong>${esc((shot.headline||shot.name).slice(0,60))}</strong><span class="shot-duration">${Number(shot.duration)}s</span></div><div class="shot-card-footer"><span>${String(index+1).padStart(2,'0')}</span><strong>${esc(shot.name)}</strong><i class="shot-state ${stale?'stale':esc(job?.status||'')}" title="${stale?'Settings changed · render again':esc(job?.status||'Not rendered')}"></i></div></button>`;}).join('')+'<button class="add-shot-card" data-action="new-shot"><b>＋</b>Add shot</button>';
  strip.scrollLeft=previousScroll;
  const index=state.shots.findIndex(s=>s.id===state.selected);
  $('#shot-actions').innerHTML=index<0?'':`<button class="text-button" data-action="move-shot" data-direction="-1" ${index===0?'disabled':''}>← Move earlier</button><button class="text-button" data-action="move-shot" data-direction="1" ${index===state.shots.length-1?'disabled':''}>Move later →</button><button class="text-button" data-action="duplicate-shot">Duplicate shot</button><button class="text-button" data-action="delete-shot" style="margin-left:auto">Delete shot</button>`;
}
const option=(value,label,selected)=>`<option value="${esc(value)}" ${String(value)===String(selected)?'selected':''}>${esc(label)}</option>`;
function renderInspector(){
  const panel=$('#inspector');if(!panel)return;const shot=selectedShot();
  if(!shot){panel.innerHTML='<div class="inspector-header"><h3>Shot settings</h3></div><div class="empty-inspector"><div class="inspector-symbol">⌁</div>Every great launch starts with a clear story. Import your source or add a shot to begin directing.</div>';return;}
  const cameras=state.config.camera_presets?.length?state.config.camera_presets:[{id:'static',name:'Static'},{id:'dolly_in',name:'Dolly in'},{id:'dolly_out',name:'Dolly out'},{id:'pan_left',name:'Pan left'},{id:'pan_right',name:'Pan right'},{id:'orbit',name:'Orbit'}];
  const styles=state.config.style_presets?.length?state.config.style_presets:[{id:'cinematic',name:'Cinematic'},{id:'natural',name:'Natural'},{id:'noir',name:'Noir'},{id:'dream',name:'Dream'}];
  const resolutions=[['1280x720','Landscape · 720p'],['720x1280','Portrait · 720p'],['720x720','Square · 720p'],['640x368','Landscape · draft'],['368x640','Portrait · draft'],['512x512','Square · draft'],['1280x704','Wan landscape · 704p'],['704x1280','Wan portrait · 704p']];
  const current=`${shot.width}x${shot.height}`;if(!resolutions.some(([v])=>v===current))resolutions.push([current,`${shot.width} × ${shot.height}`]);
  panel.innerHTML=`<div class="inspector-header"><h3>Shot settings</h3><span class="save-state" id="save-state">All changes saved</span></div><form id="shot-form"><div class="inspector-form"><div class="field"><label for="shot-name">Shot name</label><input id="shot-name" name="name" value="${esc(shot.name)}" maxlength="120" required></div><div class="field"><label for="shot-provider">Render engine</label><select id="shot-provider" name="provider">${option('recording','Live recording · real app video',shot.provider)}${option('preview','Product motion · no GPU',shot.provider)}${option('comfyui','AI footage · ComfyUI',shot.provider)}</select></div><div class="field prompt-field"><label for="shot-headline">On-screen headline</label><input id="shot-headline" name="headline" value="${esc(shot.headline||'')}" placeholder="Your next big thing." maxlength="120"></div><div class="field prompt-field"><label for="shot-caption">Supporting line</label><textarea id="shot-caption" name="caption" rows="2" maxlength="300" placeholder="One clear benefit, grounded in your product.">${esc(shot.caption||'')}</textarea></div><div class="field prompt-field image-field" ${shot.provider==='recording'?'hidden':''}><label for="shot-reference">App screenshot / image reference</label><select id="shot-reference" name="reference_asset_id">${option('','No image · typography scene',shot.reference_asset_id||'')}${state.assets.filter(a=>a.kind==='image').map(a=>option(a.id,a.name,shot.reference_asset_id)).join('')}</select><p class="field-note">Use actual app screenshots to show its real interface. <button type="button" class="text-button" style="font-size:9px;color:#adc68e" data-action="upload-assets">Upload an image ↗</button></p></div><div class="recording-field" ${shot.provider!=='recording'?'hidden':''}><div class="field prompt-field"><label for="shot-video">App recording / video source</label><select id="shot-video" name="video_asset_id" ${shot.provider==='recording'?'required':''}>${option('','Choose a recording',shot.video_asset_id||'')}${shot.video_asset_id&&!state.assets.some(a=>a.id===shot.video_asset_id)?option(shot.video_asset_id,'Missing recording · import it again',shot.video_asset_id):''}${state.assets.filter(a=>a.kind==='video').map(a=>option(a.id,`${a.name}${Number(a.video_duration??a.duration)>0?` · ${Number(a.video_duration??a.duration).toFixed(1)}s`:''}`,shot.video_asset_id)).join('')}</select><p class="field-note">Use a screen recording from Frameva for Mac, a browser flow recorded through MCP, or an uploaded video. Edits keep the actual moving app pixels. <button type="button" class="text-button" style="font-size:9px;color:#adc68e" data-action="upload-assets">Upload a recording ↗</button></p></div><div class="field-row"><div class="field"><label for="shot-trim">Start · seconds</label><input id="shot-trim" name="trim_start" type="number" min="0" max="3600" step="any" value="${Number(shot.trim_start??0)}" required></div><div class="field"><label for="shot-rate">Playback speed</label><input id="shot-rate" name="playback_rate" type="number" min="0.25" max="4" step="any" value="${Number(shot.playback_rate??1)}" required></div></div><div class="field-row"><div class="field"><label for="shot-focus-x">Focus X · left to right</label><input id="shot-focus-x" name="focus_x" type="number" min="0" max="1" step="any" value="${Number(shot.focus_x??0.5)}" required></div><div class="field"><label for="shot-focus-y">Focus Y · top to bottom</label><input id="shot-focus-y" name="focus_y" type="number" min="0" max="1" step="any" value="${Number(shot.focus_y??0.5)}" required></div></div><div class="field"><label for="shot-zoom">Zoom</label><input id="shot-zoom" name="zoom" type="number" min="1" max="2.5" step="any" value="${Number(shot.zoom??1)}" required></div><label class="checkbox-row"><input id="shot-keep-audio" name="keep_audio" type="checkbox" ${shot.keep_audio!==false?'checked':''}><span>Keep the recording’s original audio</span></label><p class="field-note">The selected start plus duration × playback speed must fit the source video. Recording shots can last up to 120 seconds; Frameva will not freeze the last frame to fill a gap.</p></div><div class="field"><label for="shot-layout">Scene layout</label><select id="shot-layout" name="layout">${[['showcase','App showcase'],['title','Title card'],['detail','Feature detail']].map(([v,l])=>option(v,l,shot.layout||'showcase')).join('')}</select></div><div class="field"><label for="shot-color">Brand accent</label><div class="color-field"><input type="color" id="shot-color" name="brand_color" value="${esc(shot.brand_color||'#b8ff65')}"><span id="color-value">${esc(shot.brand_color||'#b8ff65')}</span></div></div><div class="separator"></div><p class="section-label">MOTION & FORMAT</p><div class="field-row"><div class="field"><label for="shot-camera">Camera movement</label><select id="shot-camera" name="camera">${cameras.map(c=>option(c.id,c.name,shot.camera)).join('')}</select></div><div class="field"><label for="shot-style">Visual style</label><select id="shot-style" name="style">${styles.map(s=>option(s.id,s.name,shot.style)).join('')}</select></div></div><div class="field prompt-field"><label for="shot-format">Frame format</label><select id="shot-format" name="resolution">${resolutions.map(([v,l])=>option(v,l,current)).join('')}</select></div><div class="field-row"><div class="field"><label for="shot-duration">Duration · seconds</label><input type="number" id="shot-duration" name="duration" min="1" max="${shot.provider==='recording'?120:30}" step="any" value="${Number(shot.duration)}" required></div><div class="field"><label for="shot-fps">Frame rate</label><select id="shot-fps" name="fps">${[...new Set([8,12,16,24,25,30,Number(shot.fps)])].sort((a,b)=>a-b).map(v=>option(v,`${v} fps`,shot.fps)).join('')}</select></div></div><div class="separator"></div><p class="section-label">CREATIVE DIRECTION</p><div class="field prompt-field"><label for="shot-prompt">Scene direction / AI prompt</label><textarea id="shot-prompt" name="prompt" rows="3" maxlength="8000" placeholder="Describe the scene, composition, and action.">${esc(shot.prompt||'')}</textarea><p class="field-note">Live recording edits your real video. Product motion animates screenshots and text. ComfyUI uses this prompt; its results depend on your model.</p></div><div class="field prompt-field ai-field" ${shot.provider!=='comfyui'?'hidden':''}><label for="shot-workflow">ComfyUI workflow</label><select id="shot-workflow" name="workflow_id">${option('','Select a workflow',shot.workflow_id||'')}${state.workflows.map(w=>option(w.id,w.name,shot.workflow_id)).join('')}</select><p class="field-note">Import a trusted API workflow in Render engines. Wan 2.2 templates use 704p landscape or portrait, 24 fps, and dimensions divisible by 32.</p></div><div class="field prompt-field ai-field" ${shot.provider!=='comfyui'?'hidden':''}><label for="shot-negative">Negative prompt</label><textarea id="shot-negative" name="negative_prompt" rows="2" maxlength="4000">${esc(shot.negative_prompt||'')}</textarea></div><div class="field ai-field" ${shot.provider!=='comfyui'?'hidden':''}><label for="shot-seed">Seed</label><input id="shot-seed" name="seed" type="number" value="${Number(shot.seed??42)}" min="0" max="4294967295"></div></div><div class="inspector-footer"><button type="button" class="button primary full" data-action="generate-shot">Render this shot <span>↗</span></button><button class="text-button" type="submit">Save changes <kbd>⌘ S</kbd></button></div></form>`;
  updateProviderControls();
}
function serializeShotForm(values,previous={}){
  const data={...values};
  if(data.provider!=='recording')for(const key of Object.keys(recordingDefaults))data[key]=previous[key]??recordingDefaults[key];
  const [width,height]=String(data.resolution||'').split('x').map(Number);delete data.resolution;
  const numeric=['duration','fps','seed','trim_start','playback_rate','focus_x','focus_y','zoom'];
  const defaults={seed:42,...recordingDefaults};
  for(const key of numeric)data[key]=Number(data[key]??defaults[key]);
  data.keep_audio=data.keep_audio===true||['on','true','1'].includes(data.keep_audio);
  return {...data,width,height,workflow_id:data.workflow_id||null,reference_asset_id:data.reference_asset_id||null,video_asset_id:data.video_asset_id||null};
}
function updateProviderControls(){
  const provider=$('#shot-provider')?.value;if(!provider)return;
  $$('.ai-field').forEach(node=>node.hidden=provider!=='comfyui');
  $$('.recording-field').forEach(node=>{node.hidden=provider!=='recording';$$('input, select',node).forEach(input=>input.disabled=provider!=='recording');});
  $$('.image-field').forEach(node=>node.hidden=provider==='recording');
  const duration=$('#shot-duration');if(duration)duration.max=provider==='recording'?'120':'30';
  const video=$('#shot-video');if(video)video.required=provider==='recording';
}
function shotFormData(){
  const form=$('#shot-form');if(!form)return null;if(!form.reportValidity())throw new Error('Please review the highlighted shot settings.');
  const data=serializeShotForm(Object.fromEntries(new FormData(form)),selectedShot()||{});const {width,height}=data;
  if(data.provider==='comfyui' && (data.workflow_id||'').startsWith('wan22-5b')) {
    if(width%32 || height%32 || data.fps!==24) throw new Error('Wan 2.2 needs dimensions divisible by 32 and 24 fps. Choose a Wan 704p format or 512 × 512.');
    if(data.workflow_id.endsWith('i2v')&&!data.reference_asset_id) throw new Error('The Wan image-to-video workflow needs an image reference.');
  }
  if(data.provider==='recording') {
    const video=state.assets.find(asset=>asset.id===data.video_asset_id&&asset.kind==='video');
    if(!video)throw new Error('Choose a recording from this project’s media library.');
    const available=Number(video.video_duration??video.duration),end=data.trim_start+data.duration*data.playback_rate;
    if(Number.isFinite(available)&&available>0&&end>available+0.001)throw new Error(`This edit needs ${end.toFixed(2)} seconds of source video, but the recording has ${available.toFixed(2)}. Reduce the start, duration, or playback speed.`);
  }
  return data;
}
async function saveShot({quiet=false}={}){
  const shot=selectedShot();if(!shot)return;const data=shotFormData();if(!data)return shot;
  const updated=await api(`/shots/${idpath(shot.id)}`,{method:'PATCH',body:data});const index=state.shots.findIndex(s=>s.id===shot.id);state.shots[index]=updated;
  state.dirty=false;const status=$('#save-state');if(status){status.textContent='All changes saved';status.classList.remove('dirty');}
  renderStoryboard();renderCanvas();renderInspector();if(!quiet)toast('Shot saved.');return updated;
}
function renderAssets(){
  $('#project-content').innerHTML=`<section class="panel-page"><div class="panel-top"><div><h2>Your media, in one place.</h2><p class="muted">Real app screens, generated clips, and the soundtrack to your launch.</p></div><button class="button primary" data-action="upload-assets">↑ Upload media</button></div>${state.assets.length?`<div class="asset-grid">${state.assets.map(asset=>`<article class="asset-card"><div class="asset-preview">${asset.kind==='image'?`<img src="${assetURL(asset.id)}" alt="${esc(asset.name)}" loading="lazy">`:asset.kind==='video'?`<video src="${assetURL(asset.id)}" controls preload="metadata" playsinline aria-label="${esc(asset.name)}"></video>`:`<audio src="${assetURL(asset.id)}" controls preload="metadata" aria-label="${esc(asset.name)}"></audio>`}<span class="badge neutral">${esc(asset.kind).toUpperCase()}</span></div><div class="asset-card-info"><h3 title="${esc(asset.name)}">${esc(asset.name)}</h3><div class="asset-meta"><span>${formatBytes(asset.size)}</span><span>${formatTime(asset.created_at)}</span></div></div><div class="asset-card-actions"><a href="${assetURL(asset.id,true)}" download>Download ↗</a>${asset.kind==='image'&&state.selected&&selectedShot()?.provider!=='recording'?`<button class="text-button" data-action="use-asset" data-id="${esc(asset.id)}">Use in shot</button>`:''}${asset.kind==='video'&&state.selected?`<button class="text-button" data-action="use-recording" data-id="${esc(asset.id)}">Use recording</button>`:''}<button class="icon-button" style="font-size:15px" data-action="delete-asset" data-id="${esc(asset.id)}" aria-label="Delete ${esc(asset.name)}">×</button></div></article>`).join('')}</div>`:`<div class="empty-panel"><div class="empty-icon">▧</div><h2>Show the real thing.</h2><p>Upload screenshots of your app for accurate product scenes. You can also add MP4 or WebM video and an audio track for your final export.</p><button class="button subtle" data-action="upload-assets">Choose files</button></div>`}</section>`;
}
function renderQueue(){
  const jobs=[...state.jobs].sort(newestJobFirst);
  $('#project-content').innerHTML=`<section class="panel-page"><div class="panel-top"><div><h2>On the render floor.</h2><p class="muted">${activeJobs().length?`${activeJobs().length} job${activeJobs().length===1?'':'s'} in progress. Videos render one at a time.`:'Your jobs and finished exports stay here, across sessions.'}</p></div><span class="badge neutral">${jobs.length} JOBS</span></div><div id="queue-list" class="queue-list">${jobs.length?jobs.map(job=>jobMarkup(job)).join(''):'<div class="empty-panel"><div class="empty-icon">▷</div><h2>Ready when you are.</h2><p>Render a shot from the storyboard. Track its progress, retry a failed job, or download the finished result here.</p><button class="button subtle" data-action="tab" data-tab="storyboard">Open storyboard</button></div>'}</div></section>`;
}
function jobMarkup(job){
  const shot=state.shots.find(s=>s.id===job.shot_id);const name=job.type==='record'?`${job.params?.flow?.name||'Browser flow'} recording`:job.type==='export'?'Final film export':shot?.name||job.params?.shot?.name||'Shot render';const symbols={queued:'◷',running:'↻',succeeded:'✓',failed:'!',cancelled:'−'};
  return `<article class="job-row"><div class="job-status-icon ${esc(job.status)}">${symbols[job.status]||'◷'}</div><div class="job-info"><h3>${esc(name)}</h3><p>${esc(job.status.charAt(0).toUpperCase()+job.status.slice(1))}${job.status==='running'?` · ${Math.round(Number(job.progress)||0)}%`:''} · ${esc(job.type==='record'?'Browser flow recording':job.type==='export'?'MP4 export':job.params?.shot?.provider==='recording'?'Live recording':job.params?.shot?.provider==='comfyui'?'ComfyUI':'Product motion')}</p>${['queued','running'].includes(job.status)?`<div class="progress-track"><div style="width:${Math.min(100,Math.max(0,Number(job.progress)||0))}%"></div></div>`:''}${job.error?`<p class="error-text">${esc(job.error)}</p>`:''}</div><span class="job-time">${formatTime(job.created_at)}</span><div class="job-actions">${job.asset_id&&job.status==='succeeded'?`<a href="${assetURL(job.asset_id,true)}" download>Download ↗</a>`:''}${['queued','running'].includes(job.status)?`<button class="button subtle compact" data-action="cancel-job" data-id="${esc(job.id)}">Cancel</button>`:''}${['failed','cancelled'].includes(job.status)?`<button class="button subtle compact" data-action="retry-job" data-id="${esc(job.id)}">Retry</button>`:''}</div></article>`;
}
function renderSource(){
  const src=state.source?.analysis||state.source;const hasSource=Boolean(src&&(src.features||src.stats||src.files));
  const features=src?.features||[];const stats=src?.stats||{};
  $('#project-content').innerHTML=`<section class="panel-page"><div class="panel-top"><div><h2>Find the story in your code.</h2><p class="muted">Evidence first. Let your product tell us what it actually does.</p></div><button class="button ${hasSource?'subtle':'primary'}" data-action="upload-source">↑ ${hasSource?'Replace source ZIP':'Import source ZIP'}</button></div>${hasSource?`<div class="source-summary"><div class="source-title"><h3>${esc(src.product_name||src.name||state.project.name)}</h3><span class="badge">SOURCE ANALYZED</span></div><p>${esc(src.summary||src.description||'Source inspected. Review these candidate features before building your story.')}</p><div class="source-stats"><span><b>${Number(stats.files_scanned??src.files?.length??0)}</b> files inspected</span><span><b>${features.length}</b> feature candidates</span>${src.frameworks?.length?`<span>${src.frameworks.map(esc).join(' · ')}</span>`:''}</div></div><div class="section-toolbar"><h3>Candidate features <span class="muted small">/ verify before publishing</span></h3><button class="button primary compact" data-action="launch-plan">Draft launch storyboard <span>↗</span></button></div>${features.length?`<div class="feature-list">${features.map(feature=>{const f=typeof feature==='string'?{title:feature}:feature;return `<article class="feature-card"><h3>${esc(f.title||f.name||'Feature candidate')}</h3><p>${esc(f.description||'Review the linked source before using this as a product claim.')}</p>${f.evidence?.length?`<div class="evidence">${f.evidence.slice(0,4).map(e=>typeof e==='string'?esc(e):`${esc(e.path||e.file||'source')}${e.line?`:${Number(e.line)}`:''}${e.excerpt?`<br><span style="color:#647957">${esc(e.excerpt.slice(0,140))}</span>`:''}`).join('<br>')}</div>`:''}</article>`;}).join('')}</div>`:'<div class="source-warning">No clear feature claims were found. Add a README describing your product, or use your coding agent to inspect the repository and write an evidence-based story.</div>'}${(src.warnings||[]).map(w=>`<p class="source-warning">${esc(w)}</p>`).join('')}<div class="info-strip"><span>⌁</span><div>The draft uses deterministic templates, not a built-in language model. Codex or Claude Code can review the evidence and refine the narrative through MCP. Source code is never executed by this import.</div></div>`:`<div class="source-intro"><div class="empty-panel source-drop" id="source-drop" tabindex="0" role="button" aria-label="Import source ZIP"><div class="empty-icon">⌘</div><h2>Drop your source ZIP.</h2><p>We inspect your README, manifests, routes, and components to find possible product features. No code is executed.</p><button class="button subtle" data-action="upload-source">Choose a ZIP file</button><span class="small muted" style="font-size:9px;margin-top:13px">Or use Codex / Claude Code to inspect a local repository.</span></div><aside class="source-notes"><h3>A film grounded in your product.</h3><ul><li>Feature candidates include their file and line references.</li><li>Review claims before turning them into on-screen copy.</li><li>Add real screenshots to show the app accurately.</li><li>Generated drafts are editable from the first shot to the last.</li></ul><button class="text-button" style="margin-top:17px;color:#b3d494" data-action="integrations">Connect your coding agent ↗</button></aside></div>`}</section>`;
  const drop=$('#source-drop');if(drop){drop.addEventListener('dragover',e=>{e.preventDefault();drop.classList.add('dragover');});drop.addEventListener('dragleave',()=>drop.classList.remove('dragover'));drop.addEventListener('drop',e=>{e.preventDefault();drop.classList.remove('dragover');const file=e.dataTransfer.files[0];if(file)uploadSource(file);});drop.addEventListener('click',e=>{if(!e.target.closest('button'))$('#source-input').click();});drop.addEventListener('keydown',e=>{if(e.key==='Enter'||e.key===' '){e.preventDefault();$('#source-input').click();}});}
}
function renderSettings(){
  state.page='settings';renderSidebar();$('#project-name').textContent='Render engines';$('#project-menu').hidden=true;$('#export-button').hidden=true;
  $('#main').innerHTML=`<section class="settings-page"><div class="settings-title"><p class="eyebrow">THE ENGINE ROOM</p><h1>One studio. Your choice of engine.</h1><p class="muted">Start with local product motion. Connect ComfyUI when your story needs generative footage. Your GPU can live on this machine or a trusted render server.</p></div><div class="settings-card"><div class="settings-card-head"><div><h3>Product motion</h3><p>Animated app screenshots, clean typography, camera movement, and MP4 exports. No model weights or GPU required.</p></div><span class="badge ${state.config.ffmpeg_available?'':'neutral'}">${state.config.ffmpeg_available?'READY':'FFMPEG NEEDED'}</span></div><p>This is deterministic motion design, not AI-generated footage. It is the default engine for accurate product launches.</p></div><div class="settings-card"><div class="settings-card-head"><div><h3>ComfyUI renderer</h3><p>Generate AI footage using an API workflow you have tested in your own ComfyUI installation.</p></div><span class="badge ai">OPTIONAL AI</span></div><form id="renderer-form"><label for="comfy-url">Renderer URL</label><div class="settings-row"><input id="comfy-url" name="comfy_url" type="url" value="${esc(state.config.comfy_url||'http://127.0.0.1:8188')}" required placeholder="http://127.0.0.1:8188"><button class="button subtle" type="submit">Save endpoint</button><button class="button primary" type="button" data-action="test-renderer">Test connection</button></div></form><p id="renderer-result" class="renderer-result"></p><p style="margin-top:15px;font-size:10px">Connect only to a renderer you trust. Model hardware support and licenses vary; running the studio on a Mac does not guarantee a model supports Apple Silicon.</p></div><div class="settings-card"><div class="settings-card-head"><div><h3>Trusted workflows</h3><p>Import ComfyUI API-format graphs with parameter bindings. Review custom nodes before running them.</p></div><button class="button subtle compact" data-action="import-workflow">＋ Import workflow</button></div><div class="workflow-list">${state.workflows.length?state.workflows.map(w=>`<div class="workflow-item"><div><h4>${esc(w.name)}</h4><p>${esc(w.description||'API workflow with explicit parameter bindings')}</p></div><span class="badge neutral">${esc(w.id)}</span></div>`).join(''):'<p class="muted">No workflows imported yet. Save an API workflow from ComfyUI, then map its prompt and generation inputs.</p>'}</div></div>${state.config.models?.length?`<div class="settings-card"><h3>Model research / hardware notes</h3><p>These are integration candidates, not installed or benchmarked models.</p><div class="model-grid">${state.config.models.map(m=>`<div class="model-card"><h4>${esc(m.name)}</h4><p>${esc(m.hardware||m.description||'Hardware requirements depend on your workflow.')}</p><div class="license">${esc(m.license||'Check model license')}</div></div>`).join('')}</div></div>`:''}</section>`;
}
function renderIntegrations(){
  state.page='integrations';renderSidebar();$('#project-name').textContent='Agent integrations';$('#project-menu').hidden=true;$('#export-button').hidden=true;
  $('#main').innerHTML=`<section class="settings-page"><div class="settings-title"><p class="eyebrow">YOUR CODING AGENT. NOW YOUR DIRECTOR.</p><h1>From the repo to the release film.</h1><p class="muted">Give Codex or Claude Code the tools to inspect your app, write a grounded launch story, and direct Frameva. Keep the studio running while your agent works.</p></div><div class="integration-grid"><article class="integration-card"><div class="integration-symbol">⌘</div><h2>Codex</h2><p>Register Frameva as a local stdio MCP server. Use the Python environment where Frameva is installed.</p><div class="code-block"><pre>codex mcp add frameva -- frameva mcp</pre><button class="text-button" data-action="copy" data-copy="codex mcp add frameva -- frameva mcp">Copy command ↗</button></div></article><article class="integration-card"><div class="integration-symbol">✳</div><h2>Claude Code</h2><p>Connect the same local MCP tools from Claude Code. Your agent can work with the project's real source and assets.</p><div class="code-block"><pre>claude mcp add --transport stdio frameva -- frameva mcp</pre><button class="text-button" data-action="copy" data-copy="claude mcp add --transport stdio frameva -- frameva mcp">Copy command ↗</button></div></article></div><div class="settings-card" style="margin-top:20px"><h3>Prefer exact, platform-specific configuration?</h3><p>Run this inside your Frameva environment. It prints configurations with absolute executable paths, including Windows paths. Keep the server and agent pointed at the same data directory.</p><div class="code-block"><pre>frameva mcp-config</pre><button class="text-button" data-action="copy" data-copy="frameva mcp-config">Copy command ↗</button></div></div><div class="integration-workflow"><div><span>01 / UNDERSTAND</span><h3>Read the actual repository</h3><p>The agent inspects manifests, routes, components, and documentation. Product claims need evidence.</p></div><div><span>02 / DIRECT</span><h3>Build a launch narrative</h3><p>Create the project, refine the shot sequence, and pair each feature with a real screenshot of your app.</p></div><div><span>03 / PRODUCE</span><h3>Render and export</h3><p>Queue your shots, inspect the results, and assemble the final film with a soundtrack.</p></div></div><blockquote class="example-prompt">“Read this app's source code. Find three real user benefits, with file references. Create a 20-second launch film in Frameva, use screenshots of the running app, and avoid claims that the code doesn't support.”</blockquote><div class="info-strip"><span>↗</span><div>The optional screenshot helper can capture a running app through Playwright. Start the app yourself or with your coding agent; Frameva does not execute an uploaded source archive. MCP uses local credentials and never puts your studio token into these commands.</div></div></section>`;
}
function openModal(title,body,onSubmit){
  $('#modal-title').textContent=title;$('#modal-body').innerHTML=body;state.modalHandler=onSubmit||null;$('#modal').showModal();const input=$('#modal input:not([type=checkbox]),#modal textarea');if(input)setTimeout(()=>input.focus(),20);
}
function closeModal(){$('#modal').close();state.modalHandler=null;}
function modalActions(label='Save',danger=false){return `<p id="modal-error" class="error-text" role="alert"></p><div class="modal-actions"><button type="button" class="button subtle" data-action="close-modal">Cancel</button><button type="submit" class="button ${danger?'danger':'primary'}">${esc(label)}</button></div>`;}
function newProjectModal(){
  openModal('Give your launch a name.',`<form id="modal-form"><p class="muted">A production holds your source analysis, shot sequence, media, and finished film.</p><label for="new-name">Product / project name</label><input id="new-name" name="name" required maxlength="120" placeholder="Your next big thing"><label for="new-description">Production brief <span class="muted">(optional)</span></label><textarea id="new-description" name="description" maxlength="2000" placeholder="Who is it for? What should they feel after watching?"></textarea>${modalActions('Create production')}</form>`,async data=>{const p=await api('/projects',{method:'POST',body:Object.fromEntries(data)});state.projects.unshift(p);closeModal();await selectProject(p.id);toast('Your production is ready. Start with source or add a shot.');});
}
function projectMenuModal(){
  if(!state.project)return;
  openModal('Production settings',`<form id="modal-form"><label for="edit-name">Project name</label><input id="edit-name" name="name" required maxlength="120" value="${esc(state.project.name)}"><label for="edit-description">Production brief</label><textarea id="edit-description" name="description" maxlength="2000">${esc(state.project.description||'')}</textarea><div style="display:flex;justify-content:space-between;gap:15px"><a class="text-button" href="/api/projects/${idpath(state.project.id)}/manifest" download="frameva-project.json">Download project manifest ↗</a><button type="button" class="text-button error-text" data-action="delete-project">Delete project</button></div>${modalActions('Save settings')}</form>`,async data=>{const p=await api(`/projects/${idpath(state.project.id)}`,{method:'PATCH',body:Object.fromEntries(data)});state.project=p;state.projects=state.projects.map(x=>x.id===p.id?p:x);closeModal();renderProject();toast('Production settings saved.');});
}
async function newShot(){
  if(!state.project)return newProjectModal();if(state.dirty)await saveShot({quiet:true});
  const shot=await api(`/projects/${idpath(state.project.id)}/shots`,{method:'POST',body:{name:`Shot ${state.shots.length+1}`,headline:state.shots.length?'Built for what’s next.':`Introducing ${state.project.name}`,caption:'',prompt:'A clean product launch scene. Use the real app screenshot as the visual reference.',provider:'preview',camera:'dolly_in',style:'cinematic',layout:state.shots.length?'showcase':'title',brand_color:'#b8ff65',width:1280,height:720,duration:4,fps:24,seed:42}});
  state.shots.push(shot);state.selected=shot.id;state.tab='storyboard';state.previewMode='layout';state.dirty=false;renderProject();toast('New shot added.');
}
function exportModal(){
  const missing=state.shots.filter(s=>{const job=successfulJob(s.id);return !renderFresh(s,job)||!state.assets.some(a=>a.id===job?.asset_id);});
  if(!state.shots.length)return toast('Add and render at least one shot before exporting.',true);
  if(missing.length)return toast(`Render ${missing.length} remaining shot${missing.length===1?'':'s'} with current settings before exporting: ${missing.slice(0,3).map(s=>s.name).join(', ')}.`,true);
  const maxFade=Math.min(0.8,...state.shots.map(shot=>Number(state.assets.find(asset=>asset.id===successfulJob(shot.id)?.asset_id)?.video_duration??shot.duration)/2));
  const first=state.shots[0];let resolution=first.width>first.height?'1280x720':first.width<first.height?'720x1280':'720x720';
  openModal('Ready for the launch?',`<form id="modal-form"><p class="muted">Combine the latest successful render of every shot, in storyboard order. Your export will appear in the render queue and media library.</p><label for="export-resolution">Export format</label><select id="export-resolution" name="resolution">${[['1280x720','Landscape · 1280 × 720'],['1920x1080','Landscape · 1920 × 1080'],['720x1280','Portrait · 720 × 1280'],['1080x1920','Portrait · 1080 × 1920'],['720x720','Square · 720 × 720'],['1080x1080','Square · 1080 × 1080']].map(([v,l])=>option(v,l,resolution)).join('')}</select><label for="export-fps">Frame rate</label><select id="export-fps" name="fps">${[24,25,30].map(v=>option(v,`${v} fps`,24)).join('')}</select><label for="export-transition">Between shots</label><select id="export-transition" name="transition"><option value="crossfade">Crossfade</option><option value="cut">Straight cut</option></select><label for="export-fade">Crossfade duration · seconds</label><input id="export-fade" name="transition_duration" type="number" min="0" max="${maxFade}" step="any" value="${Math.min(0.35,maxFade)}" required><p class="field-note">Fades overlap adjacent clips and shorten the final film. Use at most half the shortest clip. Fade duration is ignored for straight cuts.</p><label for="export-audio">Background soundtrack</label><select id="export-audio" name="audio_asset_id">${option('','Original clip audio only','')}${state.assets.filter(a=>a.kind==='audio').map(a=>option(a.id,a.name,'')).join('')}</select><p class="muted">Original clip audio is preserved. An optional soundtrack is mixed underneath it. Use music you have permission to include.</p>${modalActions('Export film ↗')}</form>`,async data=>{const [width,height]=data.get('resolution').split('x').map(Number);await api(`/projects/${idpath(state.project.id)}/export`,{method:'POST',body:{width,height,fps:Number(data.get('fps')),audio_asset_id:data.get('audio_asset_id')||null,transition:data.get('transition'),transition_duration:Number(data.get('transition_duration'))}});closeModal();state.tab='queue';await refreshProject();toast('Your film export is queued.');});
}
function launchPlanModal(){
  openModal('Draft your launch storyboard',`<form id="modal-form"><p class="muted">Create an editable sequence from the inspected source. The template introduces your product and highlights candidate features with evidence. Review every claim and add your screenshots.</p><label for="plan-aspect">Film format</label><select id="plan-aspect" name="aspect"><option value="landscape">Landscape · product launch</option><option value="portrait">Portrait · social launch</option><option value="square">Square · feed</option></select>${state.shots.length?'<label class="checkbox-row"><input type="checkbox" name="replace_existing"><span>Replace existing storyboard shots. Render history is handled by the project backend.</span></label>':''}${modalActions('Draft storyboard')}</form>`,async data=>{await api(`/projects/${idpath(state.project.id)}/launch-plan`,{method:'POST',body:{replace_existing:data.get('replace_existing')==='on',aspect:data.get('aspect')}});closeModal();state.tab='storyboard';await refreshProject();toast('Storyboard drafted. Review the copy and attach your app screenshots.');});
}
async function uploadAssets(files){
  if(!state.project)return toast('Create a project before uploading media.',true);if(!files.length)return;
  const projectId=state.project.id;toast(`Uploading ${files.length} file${files.length===1?'':'s'}…`);let count=0,firstImage=null;
  for(const file of files){try{const form=new FormData();form.append('file',file);form.append('project_id',projectId);const asset=await api('/assets',{method:'POST',body:form});count++;if(asset.kind==='image'&&!firstImage)firstImage=asset;}catch(error){toast(`${file.name}: ${error.message}`,true);}}
  if(projectId!==state.project?.id)return;
  const shot=selectedShot();if(firstImage&&shot&&shot.provider!=='recording'&&!shot.reference_asset_id&&!state.dirty){try{const updated=await api(`/shots/${idpath(shot.id)}`,{method:'PATCH',body:{reference_asset_id:firstImage.id}});state.shots=state.shots.map(s=>s.id===shot.id?updated:s);}catch(error){toast(error.message,true);}}
  state.assets=await api(`/assets?project_id=${idpath(projectId)}`);if(state.dirty){toast(`${count} file${count===1?'':'s'} uploaded. Save your shot to refresh media choices.`);}else{renderProject();toast(`${count} file${count===1?'':'s'} added to your media library.`);}
}
async function uploadSource(file){
  if(!state.project)return toast('Create a project before importing source.',true);
  if(!/\.zip$/i.test(file.name))return toast('Choose a ZIP archive of your source code.',true);
  if(file.size>64*1024*1024)return toast('Please use a source archive no larger than 64 MiB. Exclude dependencies and build output.',true);
  if(state.dirty){try{await saveShot({quiet:true});}catch(error){return toast(error.message,true);}}
  const projectId=state.project.id;toast('Inspecting source. Your code will not be executed.');
  try{const form=new FormData();form.append('file',file);const result=await api(`/projects/${idpath(projectId)}/source`,{method:'POST',body:form});if(projectId===state.project?.id){state.source=result;state.tab='source';state.dirty=false;renderProject();}toast('Source inspected. Review the feature candidates before drafting.');}catch(error){toast(error.message,true);}
}
function workflowModal(initial={}){
  const graph=initial.graph||initial.prompt||initial;
  const graphText=Object.keys(graph).length?JSON.stringify(graph,null,2):'';
  const bindings=initial.bindings||{prompt:{node_id:'6',input:'text'},negative_prompt:{node_id:'7',input:'text'},seed:{node_id:'3',input:'seed'}};
  openModal('Import a trusted ComfyUI workflow',`<form id="modal-form"><p class="muted">Use ComfyUI's API format, not the editor graph. Bindings map Frameva parameters to node inputs. Change the example node IDs to match your graph.</p><label for="workflow-name">Workflow name</label><input id="workflow-name" name="name" required maxlength="120" value="${esc(initial.name||'')}" placeholder="Wan product b-roll"><label for="workflow-graph">API graph JSON</label><textarea id="workflow-graph" name="graph" required rows="6" style="font-family:monospace;font-size:10px">${esc(graphText)}</textarea><label for="workflow-bindings">Parameter bindings JSON</label><textarea id="workflow-bindings" name="bindings" required rows="6" style="font-family:monospace;font-size:10px">${esc(JSON.stringify(bindings,null,2))}</textarea><label for="workflow-frames">Frame count rule</label><select id="workflow-frames" name="frame_multiple">${[[1,'Any frame count'],[4,'4n + 1 · Wan'],[8,'8n + 1 · LTX']].map(([v,l])=>option(v,l,initial.frame_multiple||4)).join('')}</select><label class="checkbox-row"><input type="checkbox" name="trusted" required><span>I trust this workflow and the nodes it runs on my configured ComfyUI server.</span></label><button class="text-button" type="button" data-action="load-workflow-file">Load a JSON file ↗</button>${modalActions('Import workflow')}</form>`,async data=>{let parsedGraph,parsedBindings;try{parsedGraph=JSON.parse(data.get('graph'));parsedBindings=JSON.parse(data.get('bindings'));}catch{throw new Error('Graph and bindings must each be valid JSON.');}await api('/workflows',{method:'POST',body:{name:data.get('name'),graph:parsedGraph,bindings:parsedBindings,description:initial.description||'',frame_multiple:Number(data.get('frame_multiple'))}});state.workflows=await api('/workflows');closeModal();renderSettings();toast('Workflow imported. Test it in ComfyUI before generating.');});
}
async function copyText(value){try{await navigator.clipboard.writeText(value);toast('Copied to clipboard.');}catch{openModal('Copy this command',`<p class="muted">Select and copy the command below.</p><textarea readonly style="min-height:95px">${esc(value)}</textarea><div class="modal-actions"><button class="button primary" data-action="close-modal">Done</button></div>`);$('#modal textarea').select();}}
async function changeView(tab){if(state.dirty&&!confirm('Discard your unsaved shot changes?'))return;state.dirty=false;state.tab=tab;renderProject();}
async function handleAction(action,button){
  if(action==='new-project')return newProjectModal();
  if(action==='close-modal')return closeModal();
  if(action==='toggle-sidebar')return $('#sidebar').classList.toggle('open');
  if(action==='home'){if(state.dirty&&!confirm('Discard your unsaved shot changes?'))return;state.dirty=false;return renderWelcome();}
  if(action==='select-project')return runBusy(null,()=>selectProject(button.dataset.id));
  if(action==='tab')return changeView(button.dataset.tab);
  if(action==='settings'||action==='integrations'){if(state.dirty&&!confirm('Discard your unsaved shot changes?'))return;state.dirty=false;$('#sidebar').classList.remove('open');return action==='settings'?renderSettings():renderIntegrations();}
  if(action==='project-menu'){if(state.dirty)await saveShot({quiet:true});return projectMenuModal();}
  if(action==='new-shot')return runBusy(button,newShot);
  if(action==='select-shot'){if(state.dirty&&!confirm('Discard your unsaved shot changes?'))return;state.dirty=false;state.selected=button.dataset.id;state.previewMode='auto';renderCanvas();renderStoryboard();renderInspector();return;}
  if(action==='toggle-preview'){state.previewMode=state.previewMode==='layout'?'auto':'layout';return renderCanvas();}
  if(action==='upload-assets'){if(!state.project)return newProjectModal();return $('#asset-input').click();}
  if(action==='upload-source')return $('#source-input').click();
  if(action==='generate-shot')return runBusy(button,async()=>{await saveShot({quiet:true});await api('/jobs',{method:'POST',body:{shot_id:state.selected}});state.previewMode='auto';state.jobs=await api(`/jobs?project_id=${idpath(state.project.id)}`);renderStoryboard();toast('Shot queued. Track it in the render queue.');});
  if(action==='generate-all')return runBusy(button,async()=>{if(state.dirty)await saveShot({quiet:true});await api(`/projects/${idpath(state.project.id)}/generate`,{method:'POST'});state.tab='queue';await refreshProject();toast('Storyboard queued for rendering.');});
  if(action==='delete-shot')return runBusy(button,async()=>{const shot=selectedShot();if(!shot||!confirm(`Delete “${shot.name}” from the storyboard?`))return;await api(`/shots/${idpath(shot.id)}`,{method:'DELETE'});await refreshProject();toast('Shot deleted.');});
  if(action==='duplicate-shot')return runBusy(button,async()=>{if(state.dirty)await saveShot({quiet:true});const s=selectedShot();if(!s)return;const {id,project_id,position,created_at,updated_at,...payload}=s;const copy=await api(`/projects/${idpath(state.project.id)}/shots`,{method:'POST',body:{...payload,name:`${s.name} copy`.slice(0,120)}});state.selected=copy.id;await refreshProject();toast('Shot duplicated.');});
  if(action==='move-shot')return runBusy(button,async()=>{const ids=state.shots.map(s=>s.id),index=ids.indexOf(state.selected),next=index+Number(button.dataset.direction);if(next<0||next>=ids.length)return;[ids[index],ids[next]]=[ids[next],ids[index]];await api(`/projects/${idpath(state.project.id)}/shots/order`,{method:'PUT',body:{shot_ids:ids}});state.shots=ids.map(id=>state.shots.find(s=>s.id===id));renderStoryboard();renderCanvas();});
  if(action==='use-asset')return runBusy(button,async()=>{if(state.dirty)await saveShot({quiet:true});await api(`/shots/${idpath(state.selected)}`,{method:'PATCH',body:{reference_asset_id:button.dataset.id}});state.tab='storyboard';await refreshProject();toast('Screenshot attached to your selected shot.');});
  if(action==='use-recording')return runBusy(button,async()=>{if(state.dirty)await saveShot({quiet:true});const shot=selectedShot(),video=state.assets.find(asset=>asset.id===button.dataset.id&&asset.kind==='video');if(!shot||!video)return;const available=Number(video.video_duration??video.duration);if(!Number.isFinite(available)||available<1)throw new Error('Choose a recording with at least one second of video.');await api(`/shots/${idpath(shot.id)}`,{method:'PATCH',body:{provider:'recording',video_asset_id:video.id,trim_start:0,playback_rate:1,duration:Math.min(Number(shot.duration)||3,120,Math.floor(available*1000)/1000)}});state.tab='storyboard';await refreshProject();toast('Recording attached. Adjust its trim, speed, focus, and audio before rendering.');});
  if(action==='delete-asset')return runBusy(button,async()=>{if(!confirm('Delete this media asset? Referenced assets cannot be deleted.'))return;await api(`/assets/${idpath(button.dataset.id)}`,{method:'DELETE'});await refreshProject();toast('Asset deleted.');});
  if(action==='cancel-job'||action==='retry-job')return runBusy(button,async()=>{await api(`/jobs/${idpath(button.dataset.id)}/${action==='cancel-job'?'cancel':'retry'}`,{method:'POST'});await refreshProject();toast(action==='cancel-job'?'Cancellation requested.':'Job queued again.');});
  if(action==='export'){if(state.dirty)await saveShot({quiet:true});return exportModal();}
  if(action==='launch-plan')return launchPlanModal();
  if(action==='import-workflow')return workflowModal();
  if(action==='load-workflow-file')return $('#workflow-input').click();
  if(action==='test-renderer')return runBusy(button,async()=>{const result=await api('/renderer/status');state.rendererConnected=Boolean(result.connected);$('#engine-dot').classList.toggle('ready',state.rendererConnected);$('#engine-dot').title=result.connected?'ComfyUI connection verified':'ComfyUI is not connected';const element=$('#renderer-result');if(element){element.className=`renderer-result${result.connected?'':' error-text'}`;element.textContent=result.connected?`Connected${result.device?` · ${typeof result.device==='string'?result.device:JSON.stringify(result.device)}`:''}. Your workflow's model weights must be installed on the renderer.`:result.error||'Renderer not reachable. Start ComfyUI and check the endpoint.';}});
  if(action==='copy')return copyText(button.dataset.copy);
  if(action==='delete-project')return runBusy(button,async()=>{const p=state.project;if(!confirm(`Delete “${p.name}” and its project records? This cannot be undone.`))return;await api(`/projects/${idpath(p.id)}`,{method:'DELETE'});state.projects=state.projects.filter(x=>x.id!==p.id);closeModal();state.dirty=false;if(state.projects.length)await selectProject(state.projects[0].id);else renderWelcome();toast('Project deleted.');});
  if(action==='logout'){await api('/session',{method:'DELETE'});state.authenticated=false;$('#token').value='';showLogin();return;}
}
document.addEventListener('click',e=>{const button=e.target.closest('[data-action]');if(!button||button.disabled)return;e.preventDefault();Promise.resolve(handleAction(button.dataset.action,button)).catch(error=>toast(error.message,true));});
document.addEventListener('submit',async e=>{
  const form=e.target;if(!['login-form','shot-form','modal-form','renderer-form'].includes(form.id))return;e.preventDefault();
  if(form.id==='login-form'){const button=$('button',form);button.disabled=true;$('#login-error').textContent='';try{await api('/session',{method:'POST',body:{token:$('#token').value.trim()}});$('#token').value='';await loadWorkspace();}catch(error){$('#login-error').textContent=error.message;}finally{button.disabled=false;}return;}
  if(form.id==='shot-form')return runBusy($('button[type=submit]',form),()=>saveShot());
  if(form.id==='modal-form'){const button=$('button[type=submit]',form);if(button.disabled)return;button.disabled=true;$('#modal-error').textContent='';try{if(state.modalHandler)await state.modalHandler(new FormData(form));}catch(error){const message=$('#modal-error');if(message)message.textContent=error.message;else toast(error.message,true);}finally{if(button.isConnected)button.disabled=false;}return;}
  if(form.id==='renderer-form')return runBusy($('button[type=submit]',form),async()=>{const config=await api('/config',{method:'PUT',body:{comfy_url:$('#comfy-url').value}});state.config={...state.config,...config};state.rendererConnected=false;$('#engine-dot').classList.remove('ready');$('#engine-dot').title='AI renderer connection has not been tested';toast('Renderer endpoint saved.');$('#renderer-result').textContent='Endpoint saved. Test the connection before generating.';});
});
document.addEventListener('input',e=>{if(e.target.closest('#shot-form')){state.dirty=true;const saved=$('#save-state');if(saved){saved.textContent='Unsaved changes';saved.classList.add('dirty');}if(e.target.name==='brand_color')$('#color-value').textContent=e.target.value;}});
document.addEventListener('change',e=>{
  if(e.target.id==='shot-provider')updateProviderControls();
  if(e.target.id==='shot-workflow'&&e.target.value.startsWith('wan22-5b')) {
    const format=$('#shot-format'); const [width,height]=format.value.split('x').map(Number);
    format.value=width>height?'1280x704':width<height?'704x1280':'512x512';$('#shot-fps').value='24';
    toast('Set a Wan-compatible frame size and 24 fps.');
  }
});
document.addEventListener('keydown',e=>{if((e.metaKey||e.ctrlKey)&&e.key.toLowerCase()==='s'&&$('#shot-form')){e.preventDefault();runBusy(null,()=>saveShot());}if(e.key.toLowerCase()==='n'&&!e.metaKey&&!e.ctrlKey&&!e.altKey&&!['INPUT','TEXTAREA','SELECT'].includes(e.target.tagName)&&!$('#modal').open&&state.authenticated){e.preventDefault();newProjectModal();}});
window.addEventListener('beforeunload',e=>{if(state.dirty){e.preventDefault();e.returnValue='';}});
$('#asset-input').addEventListener('change',e=>{const files=[...e.target.files];e.target.value='';uploadAssets(files).catch(error=>toast(error.message,true));});
$('#source-input').addEventListener('change',e=>{const file=e.target.files[0];e.target.value='';if(file)uploadSource(file);});
$('#workflow-input').addEventListener('change',async e=>{const file=e.target.files[0];e.target.value='';if(!file)return;try{if(file.size>1024*1024)throw new Error('Use a workflow JSON no larger than 1 MiB.');const parsed=JSON.parse(await file.text());if($('#modal').open)closeModal();workflowModal(parsed);}catch(error){toast(`Cannot load workflow: ${error.message}`,true);}});
$('#modal').addEventListener('click',e=>{if(e.target===$('#modal')){const rect=$('#modal').getBoundingClientRect();if(e.clientX<rect.left||e.clientX>rect.right||e.clientY<rect.top||e.clientY>rect.bottom)closeModal();}});
function updateProjectBadges(){
  if(state.page!=='project')return;
  const mediaCount=$('[data-tab="assets"] .tab-count');if(mediaCount)mediaCount.textContent=state.assets.length;
  const shotCount=$('[data-tab="storyboard"] .tab-count');if(shotCount)shotCount.textContent=state.shots.length;
  const queueTab=$('[data-tab="queue"]');
  if(queueTab){let dot=$('.active-job',queueTab);if(activeJobs().length&&!dot){dot=document.createElement('span');dot.className='active-job';queueTab.append(dot);}else if(!activeJobs().length&&dot)dot.remove();}
  const metadata=$('.project-meta');
  if(metadata){const duration=state.shots.reduce((n,shot)=>n+Number(shot.duration||0),0);metadata.innerHTML=`<span>${state.shots.length} shots</span><i class="dot"></i><span>${Number(duration.toFixed(1))}s timeline</span><i class="dot"></i><span>Saved locally</span>`;}
  const sequence=$('.storyboard-heading h3');if(sequence)sequence.innerHTML=`Shot sequence <span>${state.shots.length} scenes</span>`;
}
async function syncMetadata(){
  const projectId=state.project?.id;
  const projects=await api('/projects');
  if(JSON.stringify(projects)!==JSON.stringify(state.projects)){state.projects=projects;renderSidebar();}
  if(!projectId||projectId!==state.project?.id)return;
  const [shots,assets,source]=await Promise.all([api(`/projects/${idpath(projectId)}/shots`),api(`/assets?project_id=${idpath(projectId)}`),api(`/projects/${idpath(projectId)}/source`).catch(()=>null)]);
  if(projectId!==state.project?.id)return;
  const assetsChanged=JSON.stringify(assets)!==JSON.stringify(state.assets);
  const sourceChanged=JSON.stringify(source)!==JSON.stringify(state.source);
  const shotsChanged=JSON.stringify(shots)!==JSON.stringify(state.shots);
  state.assets=assets;state.source=source;
  const focusedOnShot=Boolean(document.activeElement?.closest?.('#shot-form'));
  let selectedChanged=false;
  if(shotsChanged&&!state.dirty&&!focusedOnShot){
    const oldShot=JSON.stringify(renderFields.map(key=>selectedShot()?.[key]??''));state.shots=shots;
    if(!shots.some(s=>s.id===state.selected))state.selected=shots[0]?.id||null;
    selectedChanged=oldShot!==JSON.stringify(renderFields.map(key=>selectedShot()?.[key]??''));
  }
  if(state.page==='project'){
    if(state.tab==='assets'&&assetsChanged)renderAssets();
    else if(state.tab==='source'&&sourceChanged)renderSource();
    else if(state.tab==='storyboard'){
      if(shotsChanged&&!state.dirty&&!focusedOnShot){renderStoryboard();if(selectedChanged){renderCanvas();renderInspector();}}
      else if(assetsChanged){renderStoryboard();if(!state.dirty&&!focusedOnShot)renderInspector();}
    }
    updateProjectBadges();
  }
}
async function poll(){
  if(!state.authenticated||state.polling||document.hidden)return;
  const projectId=state.project?.id;state.polling=true;
  try{
    if(projectId){
      const jobs=await api(`/jobs?project_id=${idpath(projectId)}`);if(projectId!==state.project?.id)return;
      if(JSON.stringify(jobs)!==JSON.stringify(state.jobs)){
        const completed=jobs.some(j=>j.status==='succeeded'&&state.jobs.find(old=>old.id===j.id)?.status!=='succeeded');
        state.jobs=jobs;
        if(completed){const assets=await api(`/assets?project_id=${idpath(projectId)}`);if(projectId!==state.project?.id)return;state.assets=assets;}
        if(state.page==='project'){
          if(state.tab==='queue')renderQueue();
          else if(state.tab==='assets'&&completed)renderAssets();
          else if(state.tab==='storyboard'){
            renderStoryboard();const result=successfulJob(state.selected);
            if(result&&result.asset_id!==state.loadedAsset&&state.previewMode!=='layout')renderCanvas();
          }
          updateProjectBadges();
        }
      }
    }
    if(Date.now()-state.lastMetadataSync>6000){state.lastMetadataSync=Date.now();await syncMetadata();}
  }catch(error){if(state.authenticated)console.warn('Frameva refresh failed:',error.message);}
  finally{state.polling=false;}
}
setInterval(poll,2000);
boot();
