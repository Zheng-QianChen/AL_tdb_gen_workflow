'use strict';

const experimentDesk = (() => {
  let owner='', scope='', paper='', quantity='', page=0;
  const size=30;
  function reset(){paper='';quantity='';page=0;}
  function open(root){
    if(owner!==current?.id||scope!==view.scope){reset();owner=current?.id;scope=view.scope;}
    const rows=libraryRows('data');
    const type=r=>r.payload.quantity||r.payload.property||kinds[r.payload.kind];
    const sources=new Map(rows.map(r=>[r.paper,paperBy(r.paper)?.title||'']));
    if(!sources.has(paper))paper='';
    const bySource=rows.filter(r=>!paper||r.paper===paper);
    const types=[...new Set(bySource.map(type))].sort();
    if(!types.includes(quantity))quantity='';
    const filtered=bySource.filter(r=>!quantity||type(r)===quantity);
    const max=Math.max(0,Math.ceil(filtered.length/size)-1);
    page=Math.min(page,max);
    let index=filtered.findIndex(r=>r.id===view.picks.data);
    if(index>=0)page=Math.floor(index/size);
    const slice=filtered.slice(size*page,size*(page+1));
    const selected=filtered[index]||slice[0];
    const options=(items,selected)=>items.map(([v,t])=>'<option value="'+esc(v)+'" '+(v===selected?'selected':'')+'>'+esc(t)+'</option>').join('');
    const filters='<div class="exp-filters"><label>来源文献<select id="exp-paper">'+options([['','全部文献 · '+sources.size+' 篇'],...[...sources].sort((a,b)=>a[1].localeCompare(b[1]))],paper)+'</select></label>'+
      '<label>测量项目<select id="exp-type">'+options([['','全部测量项目'],...types.map(t=>[t,t])],quantity)+'</select></label></div>';
    function detail(r){
      const v=r.payload, original=v.archive_source, csv=v.csv_source;
      const record=original?.row||{};
      const present=Object.fromEntries(Object.entries({
        '实测子体系':v.system?.join('–'),'来源文献':paperBy(r.paper)?.title,'原文位置':r.locator,
        '试样 / 关联组':record.sample_id||record.independent_experimental_unit||record.independence_group||record.experimental_unit_group,
        '项目相':r.phase?phaseName(phaseBy(r.phase)):'待映射 / 多相试样','原文相名':v.reported_phase,
        '温度 / K':v.T_K,'单位':propUnits[v.property]||v.unit,'方法':record.method||record.measurement_method||record.conditions?.measurement||record.conditions?.method,
        '换算说明':record.conversion,'核验备注':v.quality_notes?.join('；')}).filter(([,x])=>x!==undefined&&x!==null&&x!==''));
      const raw=original?'<details class="exp-source"><summary>归档原始记录 · '+esc(original.id)+'</summary>'+meta('归档文件',original.file)+meta('归档 SHA-256',original.sha256)+'<pre>'+esc(JSON.stringify(record,null,2))+'</pre></details>':'';
      const imported=csv?'<details class="exp-source"><summary>导入原行 · '+esc(csv.file)+' · 第 '+esc(csv.line)+' 行</summary>'+properties(csv.cells)+meta('文件 SHA-256',csv.sha256)+'<a href="'+base()+'/observations/'+encodeURIComponent(r.id)+'/table">下载原始表格</a></details>':'';
      return '<div class="cardbody"><h2>'+esc(type(r))+'</h2><p class="exp-value">'+esc(v.value??(v.phases||[]).map(p=>p.phase).join(' / '))+'</p>'+properties(present)+raw+imported+
        actions(act('read-source','查看来源文献',r.paper),act('observation','查看 / 修订',r.id))+'</div>';
    }
    const indexRows=slice.map(r=>'<button type="button" class="catalogrow" data-act="pick" data-id="'+esc(r.id)+'" aria-pressed="'+(r===selected)+'"><small>'+esc(r.payload.system?.join('–')||phaseBy(r.phase)?.system.join('–')||'')+'</small><strong>'+esc(type(r))+'</strong><span>'+esc(r.locator)+(r.payload.T_K?' · '+esc(r.payload.T_K)+' K':'')+'</span></button>').join('');
    const pager=max?'<div class="exp-pages"><button type="button" class="btn" id="exp-prev" '+(!page?'disabled':'')+'>上一页</button> '+(page+1)+' / '+(max+1)+' <button type="button" class="btn" id="exp-next" '+(page===max?'disabled':'')+'>下一页</button></div>':'';
    root.innerHTML=title(pages.data[0],'按实测子体系、来源文献和测量项目查找记录。',scopePicker())+
      actions(act('csv-import','导入实验表格',paper,'primary'),act('extract-paper','手动摘录一条',paper))+filters+
      '<div class="details-grid reader-grid"><section class="card">'+head('实验记录','<small>'+filtered.length+' 条</small>')+'<div class="reader-list">'+(indexRows||'<p class="cardbody">当前范围内暂无实验记录。</p>')+'</div>'+pager+'</section><section class="card">'+(selected?detail(selected):'<p class="cardbody">选择记录查看实验条件与来源。</p>')+'</section></div>';
    function refresh(){delete view.picks.data;open(root);}
    $('#exp-paper').onchange=e=>{paper=e.target.value;quantity='';page=0;refresh();};
    $('#exp-type').onchange=e=>{quantity=e.target.value;page=0;refresh();};
    if(max){$('#exp-prev').onclick=()=>{page--;refresh();};$('#exp-next').onclick=()=>{page++;refresh();};}
  }
  return {open,reset};
})();
