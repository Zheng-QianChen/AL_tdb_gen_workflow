'use strict';
const $=s=>document.querySelector(s);
const esc=v=>String(v??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const split=v=>v.trim().split(/[\s,，;、–—-]+/).filter(Boolean);
const propUnits={GM:'J/mol 原子',HM:'J/mol 原子',SM:'J/(mol 原子·K)',CPM:'J/(mol 原子·K)'};
let current=null,projects=[],section='home',pageRequest=0,paging=null;
const phaseName=p=>p?.name||p?.alias||'待定';
const phaseBy=id=>current.phases.find(p=>p.id===id);
const paperBy=id=>current.papers.find(p=>p.id===id);
const act=(name,label,id='',cls='btn')=>`<button type="button" class="${cls}" data-act="${name}" data-id="${esc(id)}">${label}</button>`;
const field=(k,label,val='',type='text',required=true)=>`<label>${label}<input name="${k}" type="${type}" value="${esc(val)}" ${required?'required':''}></label>`;
const area=(k,label,value='',required=true)=>`<label>${label}<textarea name="${k}" ${required?'required':''}>${esc(value)}</textarea></label>`;
const select=(k,label,items,selected='')=>`<label>${label}<select required name="${k}">${items.map(([v,t])=>`<option value="${esc(v)}" ${v===selected?'selected':''}>${esc(t)}</option>`).join('')}</select></label>`;
const opts=items=>items.map(v=>[v,v]);
const emptyReason=msg=>{throw new Error(msg);};
async function api(path,method='GET',data){
  const args={method};if(data instanceof FormData)args.body=data;
  else if(data!==undefined){args.headers={'Content-Type':'application/json'};args.body=JSON.stringify(data);}
  const res=await fetch(path,args),body=await res.json();
  if(!res.ok)throw new Error(typeof body.detail==='string'?body.detail:JSON.stringify(body.detail||body));
  return body;
}
const base=()=>'/api/projects/'+current.id;
let toastTimer;
function status(msg){clearTimeout(toastTimer);const el=$('#toast');el.textContent=msg;el.classList.toggle('show',!!msg);toastTimer=setTimeout(()=>el.classList.remove('show'),6500);}
async function load(id){
  const ticket=++pageRequest,all=await api('/api/projects');
  if(ticket!==pageRequest)return;
  const selected=all.find(p=>p.id===id)||all[0];
  const data=selected?await api('/api/projects/'+selected.id):null;
  if(ticket!==pageRequest)return;
  if(current?.id!==data?.id)view=freshView();
  projects=all;current=data;
  const paperId=new URL(location.href).searchParams.get('paper');
  if(section==='papers'&&paperId&&current?.papers.some(p=>p.id===paperId))view.picks.papers=paperId;
  const modelUrl=new URL(location.href),selectedModel=modelUrl.searchParams.get('model');
  if(selectedModel&&current?.models.some(m=>m.id===selectedModel))view.picks.model=selectedModel;
  else if(selectedModel){modelUrl.searchParams.delete('model');history.replaceState(null,'',modelUrl);}
  $('#switcher').innerHTML=all.map(p=>`<option value="${p.id}" ${p.id===selected?.id?'selected':''}>${esc(p.title)}</option>`).join('')||'<option>暂无项目</option>';
  if(selected){const url=new URL(location.href);url.searchParams.set('project',selected.id);history.replaceState(null,'',url);}
  draw();
}
function openForm(title,html,save,label='保存'){
  $('#fields').oninput=null;$('#modalTitle').textContent=title;$('#fields').innerHTML=html;$('#error').textContent='';
  const f=$('#form'),submit=f.querySelector('[type=submit]');submit.textContent=label;submit.hidden=!save;
  f.onsubmit=async e=>{
    e.preventDefault();if(!save||submit.disabled)return;submit.disabled=true;$('#error').textContent='';
    try{const result=await save(new FormData(f));await load(result?.id||result||current?.id);$('#dialog').close();if(result?.view){applyView(result.view);status(result.message);}}
    catch(err){$('#error').textContent=err.message;}
    finally{submit.disabled=false;}
  };
  $('#dialog').showModal();
}
const val=(d,k)=>String(d.get(k)||'').trim();
function projectForm(){openForm('新建项目',field('title','项目名称')+field('elements','元素符号（用空格或逗号分隔）'),async d=>{
  const p=await api('/api/projects','POST',{title:val(d,'title'),elements:split(val(d,'elements'))});
  route('home');paging=null;status('项目已创建');return p.id;
});}
function phaseForm(id,fromDatabase=''){const r=phaseBy(id);openForm(r?'编辑相':'登记相候选',field('alias','文献相名 / 原型',r?.alias||fromDatabase)+field('name','本库相名（可稍后确定）',r?.name||fromDatabase,'text',false)+field('system','该相记录的体系',(r?.system||current.elements).join(' ')),async d=>{
  await api(base()+'/phases'+(r?'/'+id:''),r?'PUT':'POST',{alias:val(d,'alias'),name:val(d,'name'),system:split(val(d,'system'))});status('相记录已保存');
});}
function paperForm(id){const r=paperBy(id);openForm(r?'编辑文献':'添加文献',field('title','文献标题',r?.title)+area('citation','题录、DOI 或可追溯的来源',r?.citation)+
  field('systems','关联体系（如 Fe-Ta，多个体系用逗号分隔）',(r?.systems||[]).map(scopeKey).join('，'),'text',false)+area('notes','整理笔记',r?.notes||'',false),async d=>{
  const systems=val(d,'systems').split(/[,，;；、]+/).filter(v=>v.trim()).map(split);
  await api(base()+'/papers'+(r?'/'+id:''),r?'PUT':'POST',{title:val(d,'title'),citation:val(d,'citation'),systems,notes:val(d,'notes')});status('文献已保存');
});}
function extraction(id,paperId){
  if(!current.papers.length)emptyReason('请先登记来源文献。');
  const r=current.observations.find(o=>o.id===id),v=r?.payload||{};
  const kinds=[['property','热力学性质'],['phase_composition','相平衡成分'],['experiment','实验数据'],['calculation','文献子系统计算'],['dft','外部第一性原理'],['structure','结构与稳定范围']];
  const body=select('paper','来源文献',[['','选择来源文献'],...current.papers.map(p=>[p.id,p.title])],r?.paper||paperId)+field('locator','图 / 表 / 页码',r?.locator)+select('phase','项目相',[['','选择项目相'],...current.phases.map(p=>[p.id,phaseName(p)])],r?.phase)+select('kind','数据类型',kinds,v.kind||({references:'calculation',dft:'dft'}[section])||'experiment')+
  '<div id="recordFields"></div>';
  openForm('手动摘录与修订',body,async d=>{
    const kind=val(d,'kind');let payload={kind};
    if(kind==='experiment'&&val(d,'system'))payload.system=split(val(d,'system'));
    if(['property','phase_composition'].includes(kind)){
      Object.assign(payload,{T_K:Number(val(d,'T')),composition:JSON.parse(val(d,'x')),error_scale:Number(val(d,'scale')),role:val(d,'role')});
      if(kind==='property')Object.assign(payload,{property:val(d,'prop'),value:Number(val(d,'value')),site_fractions:JSON.parse(val(d,'sites')),reference_state:val(d,'ref')});
      else payload.phases=JSON.parse(val(d,'target'));
    }else {
      Object.assign(payload,{value:val(d,'value'),unit:val(d,'unit')});
      if(kind==='experiment'){
        if(val(d,'quantity'))payload.quantity=val(d,'quantity');
        if(val(d,'T'))payload.T_K=Number(val(d,'T'));
      }
    }
    await api(base()+'/observations'+(r?'/'+id:''),r?'PUT':'POST',{paper:val(d,'paper'),phase:val(d,'phase')||null,locator:val(d,'locator'),payload});status('摘录已保存');
  });
  const x=Object.fromEntries(current.elements.slice(0,2).map((s,_,a)=>[s,1/a.length]));
  function dataFields(){const kind=$('#form [name=kind]').value;
    const phase=$('#form [name=phase]');phase.required=kind!=='experiment';
    phase.options[0].text=phase.required?'选择项目相':'待映射 / 多相试样';
    const prop=select('prop','性质和单位',Object.entries(propUnits).map(([k,u])=>[k,k+' · '+u]),v.property);
    const n=(k,l,value)=>field(k,l,value,'number').replace('type="number"','type="number" step="any"');
    $('#recordFields').innerHTML=['property','phase_composition'].includes(kind)?
      n('T','温度 / K',v.T_K)+area('x','总成分 / 原子分数',JSON.stringify(v.composition||x))+n('scale','残差尺度（与观测值同单位）',v.error_scale||1)+select('role','用途',[['train','拟合'],['validation','留出验证']],v.role)+
      (kind==='property'?prop+n('value','数值',v.value)+area('sites','各亚点阵占位 / JSON',JSON.stringify(v.site_fractions||[x]))+field('ref','参考态',v.reference_state):area('target','平衡相及组成 / JSON',JSON.stringify(v.phases||[{phase:phaseName(phaseBy($('#form [name=phase]').value)),composition:x}]))):
      (kind==='experiment'?field('quantity','测量项目',v.quantity,'text',false):'')+area('value','摘录数值、相界或结构判断',v.value)+field('unit','单位或实验条件',v.unit,'text',false)+(kind==='experiment'?field('T','温度 / K',v.T_K,'number',false).replace('type="number"','type="number" min="0.000001" step="any"'):'');
  }
  $('#form [name=kind]').onchange=dataFields;dataFields();
  if(v.kind==='experiment'||!r)$('#recordFields').insertAdjacentHTML('beforebegin',field('system','实测子体系（元素符号）',(v.system||[]).join(' '),'text',false));
}
async function lookup(q){const data=await api(base()+'/structures/search','POST',q);paging=data.next_offset===null?null:{...q,offset:data.next_offset};
  status('本页取得 '+data.ids.length+' 份结构，已按来源缓存。');}
function checkboxes(k,rows){return rows.map(([id,label])=>`<label class="check"><input type="checkbox" name="${k}" value="${esc(id)}" ${(!view.fitSetup||view.fitSetup[k].includes(id))?'checked':''}>${esc(label)}</label>`).join('');}
function optimize(){
  const obs=current.observations.filter(o=>['property','phase_composition'].includes(o.payload.kind));
  const names=[...new Set(current.phases.map(r=>r.name).filter(Boolean))];
  if(!current.inputs.length||!obs.length||!names.length)emptyReason('请先添加 TDB、确定本库相名，并摘录可用于拟合的热力学性质或相平衡成分。');
  const example=[{id:'A',keys:['G('+names[0]+','+current.elements.slice(0,2).map(s=>s.toUpperCase()).join(',')+';0)'],scale:1000,bounds:[-10,10]}];
  openForm('配置参数优化',select('engine','执行器',[['native','AL–TDB 自有优化器 · 本机执行'],['pandat','Pandat · '+(current.executors.pandat?'本机适配器':'导出任务')],['thermocalc','Thermo-Calc · '+(current.executors.thermocalc?'本机适配器':'导出任务')]],view.engine||'native')+
    field('components','本轮组元',view.fitSetup?.components??current.elements.join(' '))+'<h3>项目 TDB</h3>'+checkboxes('inputs',current.inputs.map(r=>[r.id,r.name]))+'<h3>竞争相</h3>'+checkboxes('phases',names.map(n=>[n,n]))+
    '<h3>观测</h3>'+checkboxes('observations',obs.map(r=>[r.id,phaseName(phaseBy(r.phase))+' · '+r.locator+' · '+r.payload.role]))+area('parameters','现有 G/L 参数键、尺度与边界',view.fitSetup?.parameters??JSON.stringify(example,null,2)),async d=>{
    const result=await api(base()+'/fit/'+val(d,'engine'),'POST',{inputs:d.getAll('inputs'),phases:d.getAll('phases'),observations:d.getAll('observations'),components:split(val(d,'components')),parameters:JSON.parse(val(d,'parameters'))});
    if(result.mode==='external_request')download(val(d,'engine')+'-request.json',result);
    status(result.id?'拟合完成，可下载候选 TDB':'外部执行器任务已导出');
  },'执行 / 导出');
  const remember=()=>{
    const d=new FormData($('#form'));
    view.engine=val(d,'engine');
    view.fitSetup={components:val(d,'components'),parameters:val(d,'parameters'),
      inputs:d.getAll('inputs'),observations:d.getAll('observations'),phases:d.getAll('phases')};
  };
  $('#fields').oninput=remember;remember();
}
function download(name,obj){const url=URL.createObjectURL(new Blob([JSON.stringify(obj,null,2)],{type:'application/json'}));const a=document.createElement('a');a.href=url;a.download=name;a.click();setTimeout(()=>URL.revokeObjectURL(url),2000);}
async function handle(a,id){
  status('');
  if(a==='new')return projectForm();
  if(a==='read-workspace')return readWorkspace();
  if(a==='save-workspace')return saveWorkspace();
  if(a==='tab')return route(id);
  if(a==='structure-tab'){view.structureTab=id;return route('phases');}
  if(a==='pick'){
    view.picks[collectionKey()]=id;
    if(section==='model'){const url=new URL(location.href);url.searchParams.set('model',id);history.replaceState(null,'',url);}
    if(section==='papers'){const url=new URL(location.href);url.searchParams.set('paper',id);history.replaceState(null,'',url);}
    return draw();
  }
  if(!current)return projectForm();
  if(a==='new-model')return newModel(id);
  if(a==='extend')return openForm('编辑项目元素',field('title','项目名称',current.title)+field('elements','项目元素',current.elements.join(' ')),async d=>{
    await api(base(),'PATCH',{title:val(d,'title'),elements:split(val(d,'elements'))});status('项目元素已更新');
  });
  if(a==='compare'){
    const choices=current.structures.filter(s=>s.id!==id).map(s=>[s.id,s.formula+' · '+s.source+' '+s.ref]);
    openForm('比较两份结构',select('other','对照结构',choices)+'<div id="comparison"></div>');
    const show=async()=>{try{const r=await api(base()+'/compare?first='+id+'&second='+encodeURIComponent($('#form [name=other]').value));$('#comparison').innerHTML=properties(r);}catch(e){$('#error').textContent=e.message;}};
    $('#form [name=other]').onchange=show;await show();return;
  }
  if(a==='dbnames'){
    const result=await api(base()+'/inputs/'+id+'/phases');
    return openForm('选择数据库中的相名',result.phases.map(n=>act('fromdb',esc(n),n)).join(' ')||'<p>未读取到相定义。</p>');
  }
  if(a==='fromdb'){$('#dialog').close();return phaseForm('',id);}
  if(a==='phase')return phaseForm(id);if(a==='paper')return paperForm(id);
  if(a==='csv-import')return importExperimentTable(id);
  if(a==='read-source'){view.scope='all';view.picks.papers=id;paperReader.reset();const url=new URL(location.href);url.searchParams.set('paper',id);history.replaceState(null,'',url);return route('papers');}
  if(a==='extract-paper')return extraction('',id);if(a==='observation')return extraction(id,'');
  if(a==='fit')return optimize();
  if(a==='fitresult')return openForm('拟合结果','<pre>'+esc(JSON.stringify(current.fits.find(r=>r.id===id).summary,null,2))+'</pre>');
  if(a==='pdf')return openForm('添加文献附件','<label>PDF 文件<input type="file" name="file" accept=".pdf" required></label>',async d=>{
    const result=await api(base()+'/papers/'+id+'/pdf','POST',d);
    paperReader.uploaded(id,result.sha256);
  });
  if(a==='tdb')return openForm('添加热力学数据库','<label>TDB 文件<input type="file" name="file" accept=".tdb" required></label>'+select('paper','来源',[['none','项目自有数据库'],...current.papers.map(p=>[p.id,p.title])]),async d=>{
    const file=d.get('file');await api(base()+'/inputs','POST',{name:file.name,text:await file.text(),paper:val(d,'paper')==='none'?null:val(d,'paper')});
  });
  if(a==='cif')return openForm('导入结构','<label>CIF 文件<input type="file" name="file" accept=".cif" required></label>'+field('ref','来源 / 条目标识')+'<label class="check"><input type="checkbox" name="shared">允许其他包含相应元素的本机项目复用此结构</label>',async d=>{
    await api(base()+'/structures','POST',{cif:await d.get('file').text(),ref:val(d,'ref'),shared:d.has('shared')});
  });
  if(a==='link'){const s=current.structures.find(r=>r.id===id),phases=current.phases.filter(p=>s.system.every(el=>p.system.includes(el)));
    if(!phases.length)emptyReason('请先登记覆盖这些元素的相候选。');
    return openForm('关联结构',select('phase','项目相',phases.map(p=>[p.id,phaseName(p)])),async d=>{await api(base()+'/links','POST',{phase:val(d,'phase'),structure:id});});}
  if(a==='geometry'){const r=await api(base()+'/structures/'+id);return openForm('晶胞与占位',properties(r['晶胞对照'])+properties({来源:r.source,条目:r.ref}));}
  if(a==='search')return openForm('查询公开结构库',select('provider','数据源',[['oqmd','OQMD'],['mp','Materials Project']])+field('elements','精确查询的化学体系',current.elements.slice(0,2).join(' '))+'<p class="muted">每页最多 20 条，结构在本机共享。Materials Project 读取服务端的 MP_API_KEY。</p>',async d=>lookup({provider:val(d,'provider'),elements:split(val(d,'elements')),offset:0}),'查询并缓存');
  if(a==='more'){await lookup(paging);await load(current.id);}
}
document.addEventListener('click',async e=>{const b=e.target.closest('[data-act]');if(!b)return;$('#projectMenu').open=false;menu(false);try{await handle(b.dataset.act,b.dataset.id);}catch(err){status(err.message);}});
$('#switcher').onchange=async e=>{route('home');paging=null;status('');try{await load(e.target.value);}catch(err){status(err.message);}};
$('#close').onclick=()=>$('#dialog').close();
section=knownSection(location.hash.slice(1));
window.addEventListener('hashchange',()=>{section=knownSection(location.hash.slice(1));draw();});
$('#menu').onclick=()=>menu(!document.body.classList.contains('navopen'));$('#scrim').onclick=()=>menu(false);
document.addEventListener('keydown',e=>{if(e.key==='Escape'){menu(false);$('#projectMenu').open=false;}});
document.addEventListener('click',e=>{if(!e.target.closest('#projectMenu'))$('#projectMenu').open=false;});
load(new URL(location.href).searchParams.get('project')).catch(err=>status(err.message));
