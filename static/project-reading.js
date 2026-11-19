'use strict';

const paperReader = (() => {
  let owner='', query='', onlyPdf=false, active='', tab='', attachment='';
  function open(root) {
    if(owner!==current?.id){owner=current?.id;query='';onlyPdf=false;active='';}
    const papers=libraryRows('papers'), byPaper=new Map();
    for(const pdf of current?.attachments||[]){
      if(!byPaper.has(pdf.paper))byPaper.set(pdf.paper,[]);
      byPaper.get(pdf.paper).push(pdf);
    }
    root.innerHTML=title('文献库','阅读原文和整理笔记，摘录实验数据。',scopePicker())+
      '<div class="details-grid reader-grid"><section class="card reader-index">'+head('项目文献',act('paper','添加文献'))+
      '<div class="reader-search"><label>查找文献<input type="search" id="paper-query" placeholder="标题、作者或 DOI"></label>'+
      '<label><input type="checkbox" id="papers-with-pdf"> 有 PDF</label><small id="paper-count"></small></div>'+
      '<div id="paper-list" class="reader-list"></div></section><section id="paper-detail" class="card"></section></div>';
    const search=$('#paper-query'), check=$('#papers-with-pdf'), list=$('#paper-list'), detail=$('#paper-detail');
    search.value=query;check.checked=onlyPdf;
    function show(p){
      detail.replaceChildren();
      if(!p){active='';detail.innerHTML='<p class="cardbody">当前条件下没有文献。</p>';return;}
      const pdfs=byPaper.get(p.id)||[], refs=current.observations.filter(o=>o.paper===p.id);
      if(active!==p.id){active=p.id;attachment='';tab=pdfs.length?'pdf':'notes';}
      if(tab==='pdf'&&!pdfs.length)tab='notes';
      const pdf=pdfs.find(a=>a.id===attachment||a.digest===attachment)||pdfs[0];
      const url=pdf?base()+'/pdf/'+encodeURIComponent(pdf.id):'';
      const tabs=[...(pdf?[['pdf','PDF 原文']]:[]),['notes','整理笔记'],['records','已摘录 '+refs.length]];
      const strip=tabs.map(([k,name])=>`<button type="button" class="filter" data-reading-tab="${k}" aria-pressed="${k===tab}">${name}</button>`).join('');
      const pdfSelect=pdfs.length>1?`<label>选择附件 <select id="read-pdf">${pdfs.map(a=>`<option value="${esc(a.id)}" ${a.id===pdf.id?'selected':''}>${esc(a.name)}</option>`).join('')}</select></label>`:esc(pdf?.name);
      const content=tab==='pdf'?`<div class="pdf-tools">${pdfSelect}<a href="${url}" target="_blank" rel="noopener">单独打开 PDF</a></div><iframe class="paper-pdf" title="${esc(pdf.name)}" src="${url}"></iframe>`:
        tab==='notes'?'<div class="reading-notes"><div>'+esc(p.notes||'尚未填写整理笔记。')+'</div></div>':
        refs.map(o=>act('observation',esc(observationName(o)+' · '+o.locator),o.id,'related')).join('')||'<p>尚无摘录。</p>';
      detail.innerHTML=`<div class="cardbody"><h2>${esc(p.title)}</h2><details class="paper-meta"><summary>题录与附件管理</summary>
        ${meta('来源',p.citation)}${p.systems?.length?meta('关联体系',p.systems.map(scopeKey).join('、')):''}
        ${actions(act('paper','编辑文献',p.id),act('pdf','添加 PDF',p.id))}</details>
        <div class="reader-tabs">${strip}</div>${content}
        </div>`;
      const bar=document.createElement('div');bar.className='reader-entry';
      bar.innerHTML=actions(act('csv-import','导入实验表格',p.id,'primary'),act('extract-paper','手动摘录',p.id));
      detail.querySelector('.reader-tabs').before(bar);
      detail.querySelectorAll('[data-reading-tab]').forEach(b=>b.onclick=()=>{tab=b.dataset.readingTab;show(p);});
      const picker=detail.querySelector('#read-pdf');if(picker)picker.onchange=()=>{attachment=picker.value;show(p);};
    }
    function filter(force=false){
      const term=query.trim().toLowerCase();
      const rows=papers.filter(p=>(!onlyPdf||byPaper.has(p.id))&&(!term||(p.title+' '+p.citation).toLowerCase().includes(term)));
      const selected=rows.find(r=>r.id===view.picks.papers)||rows[0];
      $('#paper-count').textContent=rows.length+' 条';
      const scroll=list.scrollTop;
      list.innerHTML=rows.map(p=>`<button type="button" class="catalogrow" data-paper-id="${esc(p.id)}" aria-pressed="${p===selected}"><strong>${esc(p.title)}</strong><small>${[byPaper.has(p.id)?'PDF':'',...(p.systems||[]).map(scopeKey)].filter(Boolean).map(esc).join(' · ')}</small></button>`).join('');
      list.scrollTop=scroll;
      if(force||selected?.id!==active)show(selected);
    }
    list.onclick=e=>{
      const b=e.target.closest('[data-paper-id]');if(!b)return;
      view.picks.papers=b.dataset.paperId;
      const url=new URL(location.href);url.searchParams.set('paper',b.dataset.paperId);history.replaceState(null,'',url);
      filter();
    };
    search.oninput=()=>{query=search.value;filter();};check.onchange=()=>{onlyPdf=check.checked;filter();};
    filter(true);
  }
  function reset(){query='';onlyPdf=false;active='';}
  function uploaded(paper,digest){view.picks.papers=paper;active=paper;attachment=digest;tab='pdf';}
  return {open,reset,uploaded};
})();
