'use strict';

function importExperimentTable(paperId) {
  if(!current.papers.length)emptyReason('请先登记来源文献。');
  const endpoint=base()+'/experiment-table/';
  const papers=[['','请选择文献'],...current.papers.map(p=>[p.id,p.title])];
  const phases=[['','由表格相名确定'],...current.phases.map(p=>[p.id,phaseName(p)])];
  const source=select('paper','来源文献',papers,paperId||'')+
    '<label>实验表格<input required name="file" type="file" accept=".csv,.tsv,.txt"></label>'+
    '<p class="table-hint">首行为列名，每行一条实验记录。支持逗号、分号及制表符分隔。</p>';
  const example='\uFEFF相名,表号,测量项目,数值,单位,温度(K)\r\n'+
    '"'+phaseName(current.phases[0]).replaceAll('"','""')+'",表 1,焓,123,J/mol,1000\r\n';
  const template='<a download="实验数据模板.csv" href="data:text/csv;charset=utf-8,'+esc(encodeURIComponent(example))+'">下载 CSV 示例</a>';
  let generation=0, token='', busy=false;
  const build=(file,form,confirmation='')=>{
    const body=new FormData();body.append('file',file);
    if(form){
      const mapping={};for(const k of ['paper','phase','locator','phase_col','locator_col','quantity_col','value_col','unit_col','unit','temp_col','temp_unit'])mapping[k]=val(form,k);
      mapping.keep_unmapped=form.has('keep_unmapped');
      mapping.system=split(val(form,'system'));
      body.append('mapping',JSON.stringify(mapping));
    }
    if(confirmation)body.append('confirmation',confirmation);
    return body;
  };
  openForm('导入实验表格','<div id="table-import">'+source+template+
    '<div id="table-columns"></div><div id="mapped-preview" aria-live="polite"></div></div>',async form=>{
    if(!token)throw Error('请先预览待导入记录。');
    const result=await api(endpoint+'commit','POST',build(form.get('file'),form,token));
    view.scope='all';experimentDesk.reset();if(result.first)view.picks.data=result.first;
    route('data');status('已导入 '+result.added+' 条，跳过 '+result.duplicates+' 条重复原行。');
  },'确认导入');
  const wrapper=$('#table-import'), f=$('#form'),submit=f.querySelector('[type=submit]');
  const file=f.elements.file,columns=$('#table-columns'),out=$('#mapped-preview');
  submit.hidden=true;
  const live=n=>generation===n&&wrapper.isConnected&&$('#dialog').open;
  function invalidate(){
    generation++;token='';submit.hidden=true;out.replaceChildren();$('#error').textContent='';
  }
  function table(headers,rows){
    return '<div class="import-scroll"><table><thead><tr>'+headers.map(h=>'<th>'+esc(h)+'</th>').join('')+
      '</tr></thead><tbody>'+rows.map(row=>'<tr>'+row.map(v=>'<td>'+esc(v??'—')+'</td>').join('')+'</tr>').join('')+'</tbody></table></div>';
  }
  function choice(name,label,none,values,selected=''){
    return '<label>'+esc(label)+'<select name="'+name+'">'+[['',none],...values.map(v=>[v,v])].map(([v,l])=>
      `<option value="${esc(v)}" ${selected===v?'selected':''}>${esc(l)}</option>`).join('')+'</select></label>';
  }
  file.onchange=async()=>{
    invalidate();columns.replaceChildren();busy=false;
    const n=generation, chosen=file.files[0];if(!chosen)return;
    try{
      const d=await api(endpoint+'inspect','POST',build(chosen));
      if(!live(n))return;
      const h=d.headers,match=(...keys)=>h.find(v=>keys.includes(v.toLowerCase().trim()))||'';
      const temp=match('t_k','temperature_k','温度(k)','温度（k）','t_c','温度(°c)','温度（℃）','温度','temperature');
      columns.innerHTML='<h3>原表预览 · '+d.total+' 行</h3>'+table(h,d.sample)+'<h3>列对应关系</h3><div class="map-grid">'+
        choice('phase_col','相名列','使用默认相',h,match('phase','相名','相','项目相'))+
        choice('phase','默认相','由表格相名确定',[], '')+
        field('system','实测子体系（元素符号）',view.scope==='all'?'':view.scope,'text',false)+
        '<label class="check"><input name="keep_unmapped" type="checkbox" '+(!current.phases.length?'checked':'')+'>保留未映射的文献相名</label>'+
        choice('locator_col','图表或页码列','使用统一位置',h,match('locator','位置','页码','表号','图号','图 / 表 / 页码'))+
        field('locator','统一位置（如表 2）','','text',false)+
        choice('quantity_col','测量项目列','使用数值列名',h,match('quantity','property','测量项目','性质','物理量'))+
        choice('value_col','数值列','保留整行测量内容',h,match('value','数值','测量值'))+
        choice('unit_col','单位列','使用统一单位',h,match('unit','单位'))+
        field('unit','统一单位','','text',false)+choice('temp_col','温度列','无温度列',h,temp)+
        choice('temp_unit','原表温度单位','请选择', ['K','°C'],temp&&(/k[）)]?$/i.test(temp)?'K':/[c℃][）)]?$/i.test(temp)?'°C':''))+
        '</div><button type="button" class="btn" id="table-preview">预览入库记录</button>';
      const phasesEl=f.elements.phase;phasesEl.replaceChildren(...phases.map(([v,l])=>new Option(l,v)));
      $('#table-preview').onclick=preview;
    }catch(e){if(live(n))$('#error').textContent=e.message;}
  };
  wrapper.addEventListener('input',e=>{
    if(e.target!==file&&columns.children.length){invalidate();busy=false;}
  });
  async function preview(){
    if(busy||!f.reportValidity())return;
    invalidate();const n=generation;busy=true;
    try{
      const d=await api(endpoint+'preview','POST',build(file.files[0],new FormData(f)));
      if(!live(n))return;
      token=d.confirmation;
      out.innerHTML='<h3>待新增 '+(d.total-d.duplicates)+' 条 · 已存在 '+d.duplicates+' 条</h3>'+
        table(['原行','项目相','原文位置','测量项目','数值 / 内容','单位','温度 / K'],d.sample.map(r=>[r.line,r.phase,r.locator,r.quantity,r.value,r.unit,r.T_K]))+
        '<p class="table-hint">入库为实验摘录，保留原行全部列、文件名与校验值。</p>';
      submit.hidden=d.total===d.duplicates;
    }catch(e){if(live(n))$('#error').textContent=e.message;}
    finally{if(live(n))busy=false;}
  }
}
