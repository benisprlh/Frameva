'use strict';
const initial = [
 {id:'research',title:'Shape the product story',category:'Product',priority:'High',done:true,owner:'BS'},
 {id:'design',title:'Polish the onboarding experience',category:'Design',priority:'High',done:false,owner:'AK'},
 {id:'record',title:'Record the launch walkthrough',category:'Marketing',priority:'Medium',done:false,owner:'BS'},
 {id:'quality',title:'Test the complete user journey',category:'Engineering',priority:'High',done:false,owner:'JL'},
 {id:'brand',title:'Finalize the launch identity',category:'Design',priority:'Medium',done:true,owner:'AK'},
 {id:'publish',title:'Publish the release notes',category:'Marketing',priority:'Low',done:false,owner:'BS'}
];
let tasks;
try { tasks=JSON.parse(localStorage.getItem('orbit-demo-tasks')||'null'); } catch { tasks=null; }
if(!Array.isArray(tasks)||tasks.some(t=>typeof t.title!=='string')) tasks=structuredClone(initial);
let filter='all',search='';
const $=s=>document.querySelector(s);
function save(){localStorage.setItem('orbit-demo-tasks',JSON.stringify(tasks));}
function toast(message){const el=$('#toast');el.textContent=message;el.hidden=false;clearTimeout(toast.timer);toast.timer=setTimeout(()=>el.hidden=true,2500);}
function render(){
 const completed=tasks.filter(t=>t.done).length,active=tasks.length-completed,percent=tasks.length?Math.round(completed/tasks.length*100):0;
 $('#completed-count').textContent=completed;$('#active-count').textContent=active;$('#total-count').textContent=tasks.length;$('#progress-number').textContent=percent+'%';
 $('[data-view="board"] b').textContent=String(tasks.length).padStart(2,'0');
 $('#analytics-completed').textContent=completed;$('#analytics-total').textContent=tasks.length;$('#analytics-priorities').textContent=tasks.filter(t=>!t.done&&t.priority==='High').length;
 $('#analytics-percent').textContent=percent+'%';$('#donut').style.background=`conic-gradient(#b3d68b ${percent}%,#edf2e6 ${percent}%)`;$('#legend-done').textContent=completed;$('#legend-active').textContent=active;
 const list=$('#task-list');list.replaceChildren();
 const shown=tasks.filter(t=>(filter==='all'||(filter==='done'?t.done:!t.done))&&t.title.toLowerCase().includes(search.toLowerCase()));
 for(const task of shown){
  const row=document.createElement('article');row.className='task-row'+(task.done?' done':'');row.dataset.taskId=task.id;
  const toggle=document.createElement('button');toggle.className='task-toggle';toggle.textContent=task.done?'✓':'';toggle.setAttribute('aria-label',(task.done?'Reopen ':'Complete ')+task.title);toggle.dataset.testid='toggle-'+task.id;toggle.addEventListener('click',()=>{task.done=!task.done;save();render();toast(task.done?'Task completed. One step closer.':'Task reopened.');});
  const copy=document.createElement('div'),title=document.createElement('strong'),meta=document.createElement('span');title.className='task-title';title.textContent=task.title;meta.className='task-meta';meta.textContent=task.done?'COMPLETED · LAUNCH WORKSPACE':'FRAMEVA LAUNCH · THIS WEEK';copy.append(title,meta);
  const category=document.createElement('span');category.className='task-category '+task.category;category.textContent=task.category;
  const priority=document.createElement('span');priority.className='priority '+task.priority;priority.textContent=task.priority;
  const owner=document.createElement('span');owner.className='row-avatar';owner.textContent=task.owner;
  row.append(toggle,copy,category,priority,owner);list.append(row);
 }
 if(!shown.length){const empty=document.createElement('p');empty.className='empty';empty.textContent='No tasks here yet. A little room for your next big idea.';list.append(empty);}
}
document.querySelectorAll('[data-filter]').forEach(button=>button.addEventListener('click',()=>{filter=button.dataset.filter;document.querySelectorAll('[data-filter]').forEach(b=>b.classList.toggle('active',b===button));render();}));
document.querySelectorAll('[data-view]').forEach(button=>button.addEventListener('click',()=>{const name=button.dataset.view;$('#board-view').hidden=name!=='board';$('#analytics-view').hidden=name!=='analytics';$('#view-name').textContent=name==='board'?'Launch board':'Analytics';document.querySelectorAll('.nav').forEach(b=>b.classList.toggle('active',b.dataset.view===name));render();}));
$('#search').addEventListener('input',event=>{search=event.target.value;render();});
$('#add-task').addEventListener('click',()=>{$('#task-form').reset();$('#task-dialog').showModal();$('#task-title').focus();});
$('#close-dialog').addEventListener('click',()=>$('#task-dialog').close());$('#cancel-dialog').addEventListener('click',()=>$('#task-dialog').close());
$('#task-form').addEventListener('submit',event=>{event.preventDefault();const fields=new FormData(event.target);const title=String(fields.get('title')).trim();if(!title)return;const id='task-'+crypto.randomUUID().slice(0,8);tasks.unshift({id,title,category:String(fields.get('category')),priority:String(fields.get('priority')),done:false,owner:'BS'});save();filter='all';search='';$('#search').value='';document.querySelectorAll('[data-filter]').forEach(b=>b.classList.toggle('active',b.dataset.filter==='all'));render();$('#task-dialog').close();toast('Task created. Your next step is ready.');});
$('#reset-demo').addEventListener('click',()=>{tasks=structuredClone(initial);save();render();toast('Demo workspace reset.');});
document.addEventListener('keydown',event=>{if((event.metaKey||event.ctrlKey)&&event.key.toLowerCase()==='k'){event.preventDefault();$('#search').focus();}});
render();
