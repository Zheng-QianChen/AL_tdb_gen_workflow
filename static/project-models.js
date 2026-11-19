'use strict';

function modelDesk(){
  const models=current?.models||[];
  const rows=models.map(m=>({...m,label:m.title,tag:phaseName(phaseBy(m.phase)),sub:m.state}));
  if(rows.length){
    const selected=rows.find(m=>m.id===view.picks.model)||rows[0];
    view.picks.model=selected.id;
    const url=new URL(location.href);
    if(url.searchParams.get('model')!==selected.id){url.searchParams.set('model',selected.id);history.replaceState(null,'',url);}
  }
  const add=current&&!current.phases.length?act('phase','登记项目相','','primary'):act('new-model','新建模型','','primary');
  const detail=m=>{
    const toolLink=(k,label)=>`<a class="btn" href="${esc(WorkbenchNavigation.toolHref(k,current.id,m.config,m.id))}">${esc(label||WorkbenchNavigation.tools[k].label)} ${icon('arrow')}</a>`;
    return properties({项目相:m.tag,建模进度:m.state})+actions(toolLink('prepare','配置亚点阵与输入'),
      ...(m.configured?[act('new-model','由此派生模型',m.id)]:[]))+
      (m.configured?'<h3 class="subhead">计算与分析</h3>'+actions(...['control','jobs','results','training','analysis'].map(k=>toolLink(k))):'')+
      (m.archived?actions(`<a class="btn" href="${base()}/models/${m.id}/history">下载原运行文件</a>`):'');
  };
  const legacy=WorkbenchNavigation.toolHref('control',current?.id);
  return title('单相建模','为项目相建立独立模型。同一相可以并行比较多套亚点阵和占位方案。',
    actions('<a class="btn" href="'+esc(legacy)+'">已有独立运行</a>',add))+
    detailGrid(rows,detail,'项目模型',current?.phases.length?'新建模型后，在这里准备输入、查看作业和比较结果。':'先登记项目相，再为该相建立模型。');
}
function newModel(template){
  const source=current.models.find(m=>m.id===template);
  const phases=source?current.phases.filter(p=>p.id===source.phase):current.phases;
  const body=select('phase','项目相',phases.map(p=>[p.id,phaseName(p)]),source?.phase)+field('title','模型名称',source?source.title+' · 变体':'');
  openForm(source?'由现有方案建立模型':'新建单相模型',body,async d=>{
    const result=await api(base()+'/models','POST',{title:val(d,'title'),phase:val(d,'phase'),template:source?.id});
    view.picks.model=result.id;
    const url=new URL(location.href);url.searchParams.set('model',result.id);history.replaceState(null,'',url);
    status('模型已建立');
  },'建立模型');
}
let refreshingModels=false;
async function refreshModels(){
  if(refreshingModels||section!=='model'||!current||document.hidden||$('#dialog').open)return;
  const project=current;
  refreshingModels=true;
  try{
    const models=await api(base()+'/models');
    if(project===current&&section==='model'&&JSON.stringify(project.models)!==JSON.stringify(models)){
      project.models=models;draw();
    }
  }catch(err){status(err.message);}
  finally{refreshingModels=false;}
}
window.addEventListener('focus',refreshModels);
setInterval(refreshModels,5000);
