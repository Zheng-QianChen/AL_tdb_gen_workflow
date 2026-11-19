'use strict';

const pages = WorkbenchNavigation.pages;
const libraries = {
  papers:['来源文献、题录与附件。','篇','paper','添加文献'],
  data:['相平衡、热力学性质与实验条件。','条','observation','手动摘录'],
  databases:['参考 TDB、版本与本库相名。','份','tdb','添加 TDB'],
  references:['文献中的子体系计算与相界。','条','observation','摘录计算结果'],
  dft:['外部结构、能量及其来源。','条','observation','摘录第一性原理数据']
};
const workAreas = {
  thermo:['计算多相平衡，对照文献相界和实验点。','多相平衡'],
  fit:['组合观测约束，检查参数与候选数据库。','AL–TDB / Pandat / TC'],
  model:['准备端元计算，复核作业结果与亚点阵占位。','VASP / CEF']
};
const structureTabs={systems:'按体系查相',binary:'二元结构档案',candidates:'结构候选',adopted:'本库结构方案'};
const freshView=()=>({scope:'all',structureTab:'systems',engine:'native',picks:{}});
let view=freshView();
const knownSection=k=>Object.hasOwn(pages,k)?k:'home';
function route(key){
  section=knownSection(key);
  if(location.hash!=='#'+section)history.pushState(null,'','#'+section);
  draw();
  $('#main').focus({preventScroll:true});
}
function menu(open){
  document.body.classList.toggle('navopen',open);$('#scrim').hidden=!open;
  $('#menu').setAttribute('aria-expanded',String(open));
}
function navButton(k){
  return `<button class="navitem" data-act="tab" data-id="${k}" ${k===section?'aria-current="page"':''}>${icon(pages[k][1])}${pages[k][0]}</button>`;
}
const title=(name,description,extra='')=>`<div class="pagehead"><div><h1>${esc(name)}</h1><p>${esc(description)}</p></div>${extra}</div>`;
const head=(name,extra='')=>`<div class="cardhead"><h2>${esc(name)}</h2>${extra}</div>`;
const meta=(key,value)=>`<div class="metarow"><span>${esc(key)}</span><strong>${esc(value)}</strong></div>`;
function properties(obj){
  return Object.entries(obj).map(([k,v])=>v&&typeof v==='object'&&!Array.isArray(v)?
    '<h3>'+esc(k)+'</h3>'+properties(v):meta(k,v===true?'是':v===false?'否':v??'—')).join('');
}
const scopeKey=system=>[...system].sort().join('–');
function systems(){
  const elements=current?.elements||[], names=new Set();
  if(elements.length<=12)elements.forEach((a,i)=>elements.slice(i+1).forEach(b=>names.add(scopeKey([a,b]))));
  if(elements.length)names.add(scopeKey(elements));
  if(view.scope!=='all'&&view.scope.split('–').every(el=>elements.includes(el)))names.add(view.scope);
  for(const item of [...current?.phases||[],...current?.structures||[]])names.add(scopeKey(item.system));
  for(const paper of current?.papers||[])for(const system of paper.systems||[])names.add(scopeKey(system));
  for(const obs of current?.observations||[])if(obs.payload.system?.length)names.add(scopeKey(obs.payload.system));
  return [...names].sort();
}
function scopePicker(){
  return `<label class="scopepick"><span>当前子体系</span><select id="projSystem"><option value="all">全项目</option>${systems().map(s=>`<option ${view.scope===s?'selected':''}>${esc(s)}</option>`).join('')}</select></label>`;
}
function inScope(system){return view.scope==='all'||system&&scopeKey(system)===view.scope;}
function isObserved(o){return inScope(o.payload.system||phaseBy(o.phase)?.system);}
function libraryRows(k){
  if(!current)return [];
  const observations=current.observations.filter(isObserved);
  const paperIds=new Set(observations.map(o=>o.paper));
  if(k==='papers')return current.papers.filter(p=>view.scope==='all'||paperIds.has(p.id)||p.systems?.some(inScope));
  if(k==='databases')return current.inputs.filter(i=>view.scope==='all'||paperIds.has(i.paper));
  const kinds={references:['calculation'],dft:['dft'],data:['experiment','phase_composition','property']};
  return observations.filter(o=>kinds[k].includes(o.payload.kind));
}
function overview(){
  const els=current?.elements||[],n=els.length;
  return title('数据库工作台',current?els.join('–')+'　·　'+n*(n-1)/2+' 个二元与 '+n*(n-1)*(n-2)/6+' 个三元目标子体系':'选择项目元素，建立热力学数据库。')+
    `<section class="hero projecthero"><div class="hero-info"><div class="eyebrow">热力学数据库 / 结构设计</div><h2>多元库采用哪些相？</h2>
    <p>从各阶子体系的直接证据出发，比较结构、占位和各相的稳定范围。</p>
    <div class="hero-actions">${current?act('structure-tab','按体系查看相记录 '+icon('arrow'),'systems','lime'):act('new','新建项目 '+icon('plus'),'','lime')}
    ${current?act('structure-tab','比较结构候选 '+icon('arrow'),'candidates','quiet'):act('read-workspace','读取工作台 '+icon('arrow'),'','quiet')}</div></div>
    <div class="chartplate matrixplate mt-hero"><div>${act('structure-tab','二元 · 结构档案','binary','quiet')}${act('structure-tab','多元 · 结构候选','candidates','quiet')}${act('structure-tab','本库 · 已选相结构','adopted','quiet')}</div></div></section>
    <div class="sectionhead"><h2>子体系资料与证据</h2>${scopePicker()}</div><div class="shelves">${Object.entries(libraries).map(([k,[caption,unit]])=>act('tab',`<span class="shelf-top">${icon(pages[k][1])}<small>${libraryRows(k).length} ${unit}</small></span><strong>${pages[k][0]}</strong><span class="shelf-text">${caption}</span>`,k,'shelf')).join('')}</div>
    <div class="sectionhead"><h2>项目工作区</h2></div><div class="workcards">${Object.entries(workAreas).map(([k,[caption,engine]])=>act('tab',`<span class="workcap">${icon(pages[k][1])}<span class="mono">${engine}</span></span><strong>${pages[k][0]} ${icon('arrow')}</strong><span>${caption}</span>`,k,'workcard')).join('')}</div>`;
}
function collectionKey(){return section==='phases'?'phases-'+view.structureTab:section;}
function detailGrid(rows,render,caption,empty){
  const selected=rows.find(r=>r.id===view.picks[collectionKey()])||rows[0];
  const list=rows.map(r=>`<button class="catalogrow" data-act="pick" data-id="${esc(r.id)}" aria-pressed="${selected.id===r.id}"><small>${esc(r.tag||'')}</small><strong>${esc(r.label)}</strong><span>${esc(r.sub||'')}</span></button>`).join('');
  return `<div class="details-grid libgrid"><section class="card">${head(caption,'<small>'+rows.length+' 项</small>')}${list||'<p class="cardbody">暂无条目</p>'}</section>
    <section class="card">${selected?`<div class="documenthead"><div class="docicon">${icon(pages[section][1])}</div><div><small>${esc(selected.tag||caption)}</small><h2>${esc(selected.label)}</h2></div></div><div class="cardbody">${render(selected)}</div>`:'<div class="cardbody">'+esc(empty)+'</div>'}</section></div>`;
}
const actions=(...controls)=>'<div class="actions">'+controls.join('')+'</div>';
const kinds={property:'热力学性质',phase_composition:'相平衡成分',experiment:'实验数据',calculation:'子体系计算',dft:'第一性原理',structure:'结构与稳定范围'};
function observationName(r){return phaseName(phaseBy(r.phase))+' · '+(r.payload.property||r.payload.quantity||kinds[r.payload.kind]||r.payload.kind);}
function catalogView(){
  const [caption,,action,label]=libraries[section];
  const list=libraryRows(section).map(r=>({...r,label:r.title||r.name||observationName(r),tag:r.locator||pages[section][0],sub:r.citation||paperBy(r.paper)?.title||''}));
  function details(r){
    if(section==='databases')return meta('来源',paperBy(r.paper)?.title||'项目自有数据库')+meta('SHA-256',r.digest)+actions(act('dbnames','查看并选用库名',r.id,'primary'));
    const csv=r.payload.csv_source;
    const original=csv?'<details><summary>导入原行 · '+esc(csv.file)+' · 第 '+esc(csv.line)+' 行</summary>'+properties(csv.cells)+meta('文件 SHA-256',csv.sha256)+'<a href="'+base()+'/observations/'+encodeURIComponent(r.id)+'/table">下载原始表格</a></details>':'';
    return properties({来源:paperBy(r.paper)?.title,位置:r.locator,相:phaseName(phaseBy(r.phase)),类型:kinds[r.payload.kind],测量项目:r.payload.quantity,数值:r.payload.value??(r.payload.phases||[]).map(p=>p.phase).join(' / '),单位:propUnits[r.payload.property]||r.payload.unit,温度:r.payload.T_K? r.payload.T_K+' K':null})+original+actions(act('observation','查看 / 修订',r.id,'primary'),act('read-source','查看来源文献',r.paper));
  }
  const controls=section==='data'?actions(act('csv-import','导入实验表格','','primary'),act(action,'手动摘录一条')):actions(act(action,label,'','primary'));
  return title(pages[section][0],caption,scopePicker())+controls+detailGrid(list,details,'归档条目','添加或摘录资料后，在这里查看来源与关联记录。');
}
function phaseDesk(){
  const p=current,structures=p?.structures||[],links=p?.links||[],obs=p?.observations||[];
  const isStructure=section==='phases'&&['binary','candidates'].includes(view.structureTab);
  const opts=section==='phases'?'<div class="filters">'+Object.entries(structureTabs).map(([k,v])=>`<button class="filter" data-act="structure-tab" data-id="${k}" aria-pressed="${view.structureTab===k}">${v}</button>`).join('')+'</div>':'';
  const data=isStructure?structures.filter(s=>inScope(s.system)&&(view.structureTab!=='binary'||s.system.length===2)):(p?.phases||[]).filter(r=>inScope(r.system)&&(section!=='phases'||view.structureTab!=='adopted'||r.name));
  const names=s=>links.filter(l=>l.structure===s.id).map(l=>phaseName(phaseBy(l.phase))).join(' / ');
  const rows=data.map(r=>({...r,tag:r.system.join('–'),label:isStructure?names(r)||r.formula:phaseName(r),sub:isStructure?r.sg:r.alias}));
  function details(r){
    if(isStructure)return properties({原型化学式:r.formula,空间群:r.sg,来源:r.source,来源编号:r.ref,关联相:names(r)||'待选'})+actions(act('geometry','晶胞与重复数',r.id),structures.length>1?act('compare','比较两份结构',r.id):'',act('link','关联项目相',r.id,'primary'));
    const refs=obs.filter(o=>o.phase===r.id).map(o=>act('observation',esc((paperBy(o.paper)?.title||'')+' · '+o.locator),o.id,'related'));
    return properties({本库相名:r.name||'待定',文献相名或原型:r.alias,适用体系:r.tag})+actions(act('phase','编辑相记录',r.id),act('observation','摘录文献证据'))+
      links.filter(l=>l.phase===r.id).map(l=>act('geometry',esc(structures.find(s=>s.id===l.structure)?.formula||'晶胞'),l.structure,'related')).join('')+refs.join('');
  }
  return title(pages[section][0],section==='phases'?'按体系查相，比较晶格重复、对称性与元素占位。':section==='inventory'?'核对文献相名、原型与本库命名。':'依据来源逐相复核适用体系和稳定范围。',scopePicker())+opts+
    actions(act('phase','登记相候选','','primary'),...(section==='phases'?[act('cif','导入 CIF'),act('search','查询外部库'),paging?act('more','查询下一页'):'']:[]))+
    detailGrid(rows,details,isStructure?'结构档案':'项目相记录',isStructure?'导入 CIF 或查询外部库后，可查看晶胞并比较结构。':'登记相候选后，可在这里关联结构、文献和本库相名。');
}
function workDesk(){
  if(section==='model')return modelDesk();
  const pane=(name,body)=>'<section class="card">'+head(name)+'<div class="cardbody">'+body+'</div></section>';
  const link=(url,name)=>`<a class="btn" href="${url}">${name} ${icon('arrow')}</a>`;
  const toolLink=key=>link(WorkbenchNavigation.toolHref(key,current?.id),WorkbenchNavigation.tools[key].label);
  let content;
  if(section==='fit'){
    const fits=(current?.fits||[]).map(f=>meta('拟合记录',f.id.slice(0,8))+actions(act('fitresult','查看结果',f.id),link(base()+'/fits/'+f.id+'/candidate','下载候选 TDB')));
    content=pane('优化条件',properties({项目数据库:(current?.inputs||[]).length+' 份',可用观测:(current?.observations||[]).filter(o=>['property','phase_composition'].includes(o.payload.kind)).length+' 条',执行器:'AL–TDB / Pandat / Thermo-Calc'})+actions(act('fit','配置优化','','primary'),toolLink('parameters')))+pane('已完成的拟合',fits.join('')||'还没有拟合结果。');
  }else if(section==='thermo'){
    content=pane('计算条件',meta('项目组元',(current?.elements||[]).join('–'))+actions(toolLink('diagram'),toolLink('gibbs')))+pane('对照资料',actions(act('tab','热力学数据库','databases'),act('tab','文献计算','references'),act('tab','实验数据','data')));

  }
  return title(pages[section][0],workAreas[section][0])+'<div class="enginegrid">'+content+'</div>';
}
function draw(){
  $('#nav').innerHTML=WorkbenchNavigation.grouped(navButton);
  $('#crumb').textContent=pages[section][0];$('#projectTitle').textContent=current?.title||'项目';
  $('#elements').textContent=current?.elements.join('–')||'从元素开始建库';$('#switcher').disabled=!projects.length;
  document.title=pages[section][0]+' · AL–TDB 工作台';
  hpcMonitor.close();
  if(section==='hpc'){hpcMonitor.open($('#main'));return;}
  if(section==='papers')paperReader.open($('#main'));
  else if(section==='data')experimentDesk.open($('#main'));
  else $('#main').innerHTML=section==='home'?overview():Object.hasOwn(libraries,section)?catalogView():Object.hasOwn(workAreas,section)?workDesk():phaseDesk();
  if(section==='home')$('#main .pagehead').insertAdjacentHTML('afterend','<p class="agent-invite">推荐接入 AI 助手，协助整理文献和核验实验数据。 <a href="/static/agent-guide.html" target="_blank" rel="noopener">查看协作指南 ↗</a></p>');
  const picker=$('#projSystem');if(picker)picker.onchange=()=>{view.scope=picker.value;draw();};
}
