'use strict';

const ToolShell = (() => {
  const nav=WorkbenchNavigation;
  const key=document.body.dataset.tool;
  const tool=nav.tools[key];
  const params=new URLSearchParams(location.search);
  const project=params.get('project');
  let run=params.get('config')||params.get('task')||params.get('filename')||params.get('run')||'';
  const model=params.get('model');
  const modelRun=model?'model_'+model+'.json':null;
  if(modelRun)run=modelRun;
  const modelApi=model?'/api/projects/'+encodeURIComponent(project)+'/models/'+encodeURIComponent(model):null;
  const projectHref=page=>{
    const url=new URL(nav.href('/projects#'+page,project),location.href);
    if(page==='model'&&model)url.searchParams.set('model',model);
    return url.pathname+url.search+url.hash;
  };
  const lang=document.getElementById('langSelect');
  const rail=document.getElementById('rail');
  const header=document.querySelector('.topbar');
  const projectBox=rail.querySelector('.project-box');

  const translations={control:'common.nav_home',prepare:'common.nav_prep',analysis:'common.nav_analysis',training:'common.nav_viz'};
  function toolLabel(id,entry){
    return lang&&translations[id]?`<span data-i18n="${translations[id]}">${entry.label}</span>`:entry.label;
  }
  function railItem(page){
    const [label,glyph]=nav.pages[page];
    const parent=page===tool.parent;
    const top=`<a class="navitem${parent?' tool-parent':''}" href="${projectHref(page)}">${icon(glyph)}${label}</a>`;
    if(!parent)return top;
    return top+Object.entries(nav.tools).filter(([,entry])=>entry.parent===page).map(([id,entry])=>
      `<a class="navitem subnav" data-tool-target="${id}" href="${nav.toolHref(id,project,run,model)}" ${id===key?'aria-current="page"':''}>${toolLabel(id,entry)}</a>`).join('');
  }
  rail.querySelector('nav').innerHTML=nav.grouped(railItem);
  header.innerHTML=`<button id="menu" type="button" aria-label="项目导航" aria-controls="rail" aria-expanded="false">☰</button>
    <div class="crumb"><a id="tool-project" href="${projectHref('home')}">项目工作台</a><i>/</i>
    <a class="parent-crumb" href="${projectHref(tool.parent)}">${nav.pages[tool.parent][0]}</a><i class="parent-crumb">/</i><strong>${tool.label}</strong></div>
    <div class="tool-header-actions"><a class="btn" href="${projectHref(tool.parent)}">返回工作台</a></div>`;
  if(lang)header.querySelector('.tool-header-actions').prepend(lang);
  projectBox.querySelector('a').href=projectHref('home');
  if(project){
    fetch('/api/projects').then(response=>response.ok?response.json():[]).then(rows=>{
      const entry=rows.find(p=>p.id===project);
      if(entry){
        projectBox.querySelector('a').textContent=entry.title;
        if(!model)projectBox.querySelector('span').textContent=entry.elements.join('–');
        document.getElementById('tool-project').textContent=entry.title;
      }
    }).catch(()=>{ /* The navigation still works while project metadata is unavailable. */ });
  }

  function openMenu(open){
    document.body.classList.toggle('navopen',open);
    document.getElementById('scrim').hidden=!open;
    document.getElementById('menu').setAttribute('aria-expanded',String(open));
    if(open)rail.querySelector('[aria-current="page"]').focus();
    else document.getElementById('menu').focus();
  }
  document.getElementById('menu').onclick=()=>openMenu(!document.body.classList.contains('navopen'));
  document.getElementById('scrim').onclick=()=>openMenu(false);
  document.addEventListener('keydown',e=>{if(e.key==='Escape'&&document.body.classList.contains('navopen'))openMenu(false);});
  const visible=rail.querySelector('[aria-current="page"]');
  const list=rail.querySelector('nav');
  if(visible.getBoundingClientRect().bottom>list.getBoundingClientRect().bottom)
    list.scrollTop+=visible.getBoundingClientRect().bottom-list.getBoundingClientRect().bottom+8;

  function setRun(value){
    run=modelRun||value||'';
    document.querySelectorAll('[data-tool-target]').forEach(a=>{
      a.href=nav.toolHref(a.dataset.toolTarget,project,run,model);
    });
  }
  for(const anchor of document.querySelectorAll('main a[href]')){
    const url=new URL(anchor.href);
    if(url.origin!==location.origin||url.hash||url.search)continue;
    const path=url.pathname.replace(/\.html$/,'');
    const match=Object.entries(nav.tools).find(([,entry])=>entry.path.replace(/\.html$/,'')===path||(path==='/'&&entry.path==='/index.html'));
    if(match)anchor.dataset.toolTarget=match[0];
    if(path==='/projects')anchor.href=projectHref('home');
  }
  setRun(run);
  const detail=modelApi?fetch(modelApi).then(async r=>{if(!r.ok)throw Error('模型不存在或不属于当前项目');return r.json();}):null;
  if(detail){
    detail.then(m=>{
      projectBox.querySelector('span').textContent=m.phaseLabel+' / '+m.title;
      const crumb=header.querySelector('.parent-crumb');
      crumb.textContent=m.title;crumb.href=projectHref('model');
    }).catch(err=>{header.querySelector('strong').textContent=err.message;});
    for(const id of ['target-config-file','input-file-path','output-path']){
      const el=document.getElementById(id);if(el)el.readOnly=true;
    }
    const out=document.getElementById('output-path');
    if(out)out.value='workbench/models/'+model+'/exports';
  }
  const gibbsSourceKey = 'altdb_gibbs_source'+(modelRun || (project ? '/project/'+project : ''));
  return {setRun,modelRun,modelApi,detail,model,gibbsSourceKey};

})();
