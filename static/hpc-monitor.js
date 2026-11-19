'use strict';

const hpcMonitor = (() => {
  const labels = {queued:'排队中', running:'运行中', finishing:'收尾中', submitted:'已提交 · 待确认',
    stale:'观测已过期', unknown:'状态待核实', suspended:'已挂起', failed:'失败', cancelled:'已取消',
    finished:'已完成', superseded:'已被后续作业替代'};
  const sources = {ok:'调度器观测正常', stale:'调度器观测已过期', unavailable:'无法读取调度器观测',
    unconfigured:'尚未配置调度器观测源'};
  const metrics = [['queued','排队中'],['running','运行中'],['submitted','提交待确认'],['review','需关注']];
  const needsReview = state => ['stale','unknown','failed','suspended'].includes(state);
  const stateOf = row => row.stale ? 'stale' : row.state;
  const time = value => value ? new Date(value).toLocaleString('zh-CN',{hour12:false}) : '—';
  let closeCurrent = () => {};
  function open(root) {
    root.innerHTML = title('超算任务','跨项目查看调度作业，页面打开时每 30 秒刷新一次。',
      '<button type="button" class="btn" id="queue-refresh">立即刷新</button>')+
      '<div class="queue-metrics" aria-label="作业数量"></div><section class="card queue-panel">'+
      '<div class="cardhead"><h2>作业列表</h2><div class="queue-filters">'+
      '<label>项目 <select id="queue-project"><option value="*">全部项目</option></select></label>'+
      '<label>状态 <select id="queue-state"><option value="">全部状态</option><option value="review">需关注</option>'+
      Object.entries(labels).map(([v,t])=>`<option value="${v}">${t}</option>`).join('')+'</select></label></div></div>'+
      '<p id="queue-source" role="status">正在读取作业状态…</p><div id="queue-rows"></div></section>';
    const refreshButton = root.querySelector('#queue-refresh'), scope = root.querySelector('#queue-project');
    const filter = root.querySelector('#queue-state'), list = root.querySelector('#queue-rows');
    const info = root.querySelector('#queue-source'), cards = root.querySelector('.queue-metrics');
    const controller = new AbortController();
    let data = null, busy = false;
    cards.innerHTML = metrics.map(([key,label])=>`<button class="queue-metric" type="button" data-filter="${key}" aria-pressed="false"><span>${label}</span><strong>—</strong></button>`).join('');
    function render() {
      const rows = (data?.jobs || []).filter(r=>scope.value==='*'||r.project===scope.value);
      for(const button of cards.children){
        const key = button.dataset.filter;
        const count = rows.filter(r=>key==='review'?needsReview(stateOf(r)):stateOf(r)===key).length;
        const live = ['queued','running'].includes(key);
        button.querySelector('strong').textContent = !data||(live && data.source.status!=='ok')?'—':count;
        button.setAttribute('aria-pressed',String(filter.value===key));
      }
      if(!data){list.replaceChildren();return;}
      const visible = rows.filter(r=>!filter.value||(filter.value==='review'?needsReview(stateOf(r)):stateOf(r)===filter.value));
      if(!visible.length){
        const msg = data.jobs.length?'当前筛选下没有作业。':data.source.status==='ok'?
          '当前范围内没有提交回执或调度作业。':'尚无本地提交回执，最新队列状态暂无法确认。';
        list.innerHTML = '<p class="queue-empty">'+msg+'</p>';return;
      }
      const order = Object.keys(labels);
      visible.sort((a,b)=>order.indexOf(stateOf(a))-order.indexOf(stateOf(b))||
        String(b.observed_at||b.receipt_at||'').localeCompare(String(a.observed_at||a.receipt_at||'')));
      list.innerHTML = '<div class="queue-table"><table><thead><tr><th>状态</th><th>项目 / 模型</th><th>调度作业号</th><th>平台 / 队列</th><th>计算轮次</th><th>状态来源与时间</th></tr></thead><tbody>'+
        visible.map(r=>{
          const state = stateOf(r), name = r.model_title||r.config||'';
          const model = r.config ? `<a href="${esc(WorkbenchNavigation.toolHref('jobs',r.project,r.config,r.model))}">${esc(name)}</a>` : '';
          const note = r.stale?'上次观测 · '+(labels[r.state]||labels.unknown):r.raw;
          return `<tr><td><span class="queue-badge" data-state="${esc(state)}">${esc(labels[state]||labels.unknown)}</span><small>${esc(note)}</small></td>
            <td>${model||esc(r.project_title)}<small>${esc(model?[r.project_title,r.phase].filter(Boolean).join(' · '):'')}</small></td>
            <td class="queue-id">${esc(r.scheduler_id||'未记录')}</td><td>${esc(r.platform||'—')}<small>${esc(r.queue)}</small></td>
            <td>${r.iteration==null?'—':'第 '+esc(r.iteration)+' 轮'}<small>${r.tasks==null?'':esc(r.tasks)+' 个计算任务'}</small></td>
            <td>${r.observed_at?'调度观测':'提交回执'}<small>${esc(time(r.observed_at||r.receipt_at))}</small></td></tr>`;
        }).join('')+'</tbody></table></div>';
    }
    async function refresh() {
      if(busy||document.hidden||controller.signal.aborted)return;
      busy=true;refreshButton.disabled=true;
      try {
        const res=await fetch('/api/jobs/monitor',{cache:'no-store',signal:controller.signal});
        if(!res.ok)throw Error();
        const result=await res.json();
        if(controller.signal.aborted)return;
        data=result;
        const choices=new Map(projects.map(p=>[p.id,p.title]));
        for(const job of data.jobs)choices.set(job.project,job.project_title);
        const selected=scope.value;
        scope.replaceChildren(new Option('全部项目','*'),...Array.from(choices,([id,name])=>new Option(name,id)));
        if(choices.has(selected))scope.value=selected;
        info.textContent=[sources[data.source.status],data.source.observed_at?'最近观测 '+time(data.source.observed_at):'',
          data.source.catalog==='unavailable'?'资产管理提交记录暂不可读':'',
          data.skipped?data.skipped+' 份本地文件未能读取':''].filter(Boolean).join(' · ');
      } catch {
        if(controller.signal.aborted)return;
        data=null;info.textContent='作业状态读取失败，请点击立即刷新重试。';
      } finally {busy=false;refreshButton.disabled=false;}
      render();
    }
    cards.onclick=e=>{
      const button=e.target.closest('button[data-filter]');
      if(button){filter.value=filter.value===button.dataset.filter?'':button.dataset.filter;render();}
    };
    filter.onchange=render;scope.onchange=render;refreshButton.onclick=refresh;
    const timer=setInterval(refresh,30000);
    document.addEventListener('visibilitychange',refresh);
    closeCurrent=()=>{clearInterval(timer);document.removeEventListener('visibilitychange',refresh);controller.abort();};
    refresh();
  }
  return {open,close(){closeCurrent();closeCurrent=()=>{};}};
})();
