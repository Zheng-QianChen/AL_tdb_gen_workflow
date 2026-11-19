'use strict';

const WorkbenchNavigation = (() => {
  const pages = {
    home:['项目总览','grid'], phases:['多元相与结构候选','layers'], inventory:['文献定相','scan'],
    roster:['适用范围复核','records'], papers:['文献库','records'], data:['实验数据','scan'],
    databases:['文献热力学库','layers'], references:['文献子系统计算','branch'], dft:['外部第一性原理','cpu'],
    thermo:['热力学计算','cpu'], fit:['参数优化','branch'], model:['单相建模','model'], hpc:['超算任务','clock']
  };
  const brand = '<div class="mark"><svg viewBox="0 0 32 32" fill="none" aria-hidden="true"><g stroke="currentColor" stroke-width="1.5"><path d="m5 11 11-6 11 6v11l-11 6-11-6z M5 11l11 6 11-6 M16 17v11 M10.5 8l11 6v11"/></g></svg></div><div><strong>AL–TDB</strong><small>热力学数据库工作台</small></div>';
  function renderBrand(){
    const slot=document.querySelector('#rail .brand');
    if(slot)slot.innerHTML=brand;
  }
  if(document.readyState==='loading')document.addEventListener('DOMContentLoaded',renderBrand,{once:true});
  else renderBrand();
  const groups = [
    ['', ['home','phases','inventory','roster']],
    ['资料与证据', ['papers','data','databases','references','dft']],
    ['计算与建模', ['thermo','fit','model','hpc']]
  ];
  const tools = {
    diagram:{label:'多相平衡与相图',path:'/phase-diagram',parent:'thermo'},
    gibbs:{label:'Gibbs 自由能曲线',path:'/gibbs',parent:'thermo'},
    parameters:{label:'拟合任务与结果',path:'/parameter-fit',parent:'fit'},
    control:{label:'运行控制',path:'/index.html',parent:'model',param:'task'},
    prepare:{label:'数据准备',path:'/data_preparation',parent:'model'},
    jobs:{label:'作业工作台',path:'/jobs',parent:'model',param:'config'},
    results:{label:'计算结果与修订',path:'/results',parent:'model',param:'config'},
    training:{label:'训练可视化',path:'/visualization',parent:'model',param:'task'},
    analysis:{label:'模型分析与输出',path:'/model_analysis',parent:'model',param:'config'}
  };
  function grouped(item){
    return groups.map(([title,keys])=>(title?`<div class="rail-label">${title}</div>`:'')+keys.map(item).join('')).join('');
  }
  function href(path,project,run,param){
    const url=new URL(path,location.href);
    if(project)url.searchParams.set('project',project);
    if(run&&param)url.searchParams.set(param,run);
    return url.pathname+url.search+url.hash;
  }
  function toolHref(key,project,run,model){
    const tool=tools[key];
    const url=new URL(href(tool.path,project,run,tool.param||'run'),location.href);
    if(model)url.searchParams.set('model',model);
    return url.pathname+url.search;
  }
  return {pages,tools,grouped,href,toolHref};
})();
