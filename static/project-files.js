'use strict';

const workspaceFormat='al-tdb-workspace';
function workspaceSettings(){
  const project=current?{id:current.id,title:current.title,elements:current.elements}:null;
  return {format:workspaceFormat,version:1,mode:'settings',project,view:{...view,page:section}};
}
function checkedView(raw){
  if(!raw||typeof raw!=='object')throw Error('工作台设置缺少视图。');
  const picks={};
  for(const key of [...Object.keys(pages),...Object.keys(structureTabs).map(k=>'phases-'+k)]){
    if(typeof raw.picks?.[key]==='string')picks[key]=raw.picks[key];
  }
  const fit=raw.fitSetup;
  const fitSetup=fit&&typeof fit.components==='string'&&typeof fit.parameters==='string'&&
    ['inputs','observations','phases'].every(k=>Array.isArray(fit[k])&&fit[k].every(id=>typeof id==='string'))?
    {components:fit.components,parameters:fit.parameters,inputs:fit.inputs,observations:fit.observations,phases:fit.phases}:null;
  return {page:knownSection(raw.page),scope:typeof raw.scope==='string'?raw.scope:'all',fitSetup,
    structureTab:Object.hasOwn(structureTabs,raw.structureTab)?raw.structureTab:'systems',picks,
    engine:['native','pandat','thermocalc'].includes(raw.engine)?raw.engine:'native'};
}
function applyView(raw){
  view=checkedView(raw);
  if(!systems().includes(view.scope))view.scope='all';
  route(view.page);
}
function saveWorkspace(){
  const options=(current?'<label class="check"><input type="radio" name="mode" value="full" checked>完整数据包（ZIP）</label><p>包含当前项目的文献与附件、数据库文件、结构、摘录、修订历史、单相模型的配置和运行文件、拟合文件及工作台设置。</p>':'')+
    '<label class="check"><input type="radio" name="mode" value="settings" '+(current?'':'checked')+'>仅工作台设置（JSON）</label><p>保存项目名称、元素、当前页面、子体系、所选条目与优化执行器。</p>';
  openForm('保存工作台',options,async d=>{
    const settings=workspaceSettings(), name=(current?.title||'AL-TDB').replace(/[\\/:*?"<>|]/g,'_');
    if(d.get('mode')==='settings')download(name+'-工作台设置.json',settings);
    else{
      const res=await fetch(base()+'/archive',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(settings.view)});
      if(!res.ok){const body=await res.json();throw Error(body.detail||'打包失败');}
      const url=URL.createObjectURL(await res.blob());
      const a=document.createElement('a');a.href=url;a.download=name+'-工作台.zip';a.click();
      setTimeout(()=>URL.revokeObjectURL(url),60000);
    }
    status('工作台文件已生成。');
  },'保存文件');
}
function readWorkspace(){
  const fields='<label>工作台文件<input required type="file" name="file" accept=".zip,.json"></label>'+
    '<p>完整包将恢复为独立项目。单相模型可用原配置重新运行，原计算文件在模型详情中下载。设置文件会重新打开原项目。若本机没有原项目，将按保存的名称和元素建立空项目。</p>';
  openForm('读取工作台',fields,async d=>{
    const file=d.get('file');
    if(file.name.toLowerCase().endsWith('.zip')){
      const upload=new FormData();upload.append('file',file);
      const result=await api('/api/workspace/import','POST',upload);
      return {id:result.id,view:result.view,message:'完整工作台已恢复为独立项目。'};
    }
    if(file.size>1024*1024)throw Error('请选择有效的工作台设置 JSON 或完整 ZIP 包。');
    let s;
    try{s=JSON.parse(await file.text());}catch{throw Error('工作台设置文件不是有效的 JSON。');}
    if(s?.format!==workspaceFormat||s.version!==1||s.mode!=='settings')throw Error('无法识别工作台设置的格式或版本。');
    const restored=checkedView(s.view);
    if(s.project===null)return {id:current?.id,view:restored,message:'工作台视图已读取。'};
    const p=s.project;
    if(!p||typeof p.id!=='string'||typeof p.title!=='string'||!Array.isArray(p.elements))throw Error('缺少有效的项目设置。');
    const result=await api('/api/workspace/settings','POST',{id:p.id,title:p.title,elements:p.elements});
    return {id:result.id,view:restored,message:result.created?'已按设置建立空项目。':'已读取设置并打开原项目。'};
  },'读取');
}
