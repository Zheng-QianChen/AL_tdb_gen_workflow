'use strict';
const field = id => document.getElementById(id);
let current = null, preview = null, busy = false;
const stages = {new:'尚未初始化，请进入运行控制启动任务。', waiting:'等待本轮计算结果。', training:'本轮已取得训练数据。', selecting:'正在选择下一批端元。', completed:'运行已完成。'};
async function api(url, payload) {
  const response = await fetch(url, payload === undefined ? {} : {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify(payload)});
  const result = await response.json();
  if (!response.ok) throw Error(typeof result.detail === 'string' ? result.detail : JSON.stringify(result.detail));
  return result;
}
function picker(id, items, placeholder) {
  const el = field(id);
  el.replaceChildren(new Option(placeholder, ''), ...items.map(name => new Option(name, name)));
  if (items.length === 1) el.value = items[0];
}
function controls() {
  const waiting = current?.status === 'waiting' && !current?.results_ready;
  const sent = ['submitted','interrupted_or_failed'].includes(current?.dispatch?.status);
  const finished = current?.dispatch?.status === 'finished';
  field('preview').disabled = busy || !waiting || finished || !field('machine').value;
  field('collect').disabled = busy || !waiting;
  field('confirmation').hidden = !preview;
  field('submit').disabled = busy || !preview || !waiting || finished;
  field('submit').textContent = sent ? '等待已提交作业并取回输出' : '确认提交';
  for (const id of ['config','machine','refresh']) field(id).disabled = busy;
}
async function refresh() {
  current = null; preview = null; controls();
  const config = field('config').value, query = encodeURIComponent(config);
  field('phase').textContent = config || '选择运行';
  field('stage').textContent = '';
  ToolShell.setRun(config);
  field('run-links').hidden = !config;
  if (!config) return;
  const url = new URL(location.href);
  url.searchParams.set('config', config);
  history.replaceState(null, '', url);
  current = await api('/api/jobs/state?config=' + query);
  field('phase').textContent = current.phase + ' · 轮次 ' + current.iteration;
  field('stage').textContent = current.results_ready ? '完整批次已入库，可以继续训练。' : stages[current.status] || current.status;
  if (current.dispatch) field('stage').append('  作业状态 ' + current.dispatch.status);
  controls();
}
async function locked(work) {
  if (busy) return;
  busy = true; controls(); field('notice').textContent = '正在处理…';
  try { await work(); field('notice').textContent = ''; }
  catch (e) { field('notice').textContent = e.message; }
  finally { busy = false; controls(); }
}
async function action(name) {
  const payload = {config:field('config').value, machine:field('machine').value, iteration:current.iteration, confirmation:preview?.confirmation || ''};
  const result = await api('/api/jobs/' + name, payload);
  if (name === 'plan') {
    preview = result;
    field('plan').replaceChildren();
    for (const [label,value] of [['机器配置',payload.machine],['调度器',result.batch_type],['轮次',result.iteration],['队列',result.queue],['任务数',result.task_count],['命令',result.command]]) {
      const dt=document.createElement('dt'), dd=document.createElement('dd');
      dt.textContent=label; dd.textContent=value ?? '默认'; field('plan').append(dt,dd);
    }
    field('feedback').textContent = '';
  } else {
    field('feedback').textContent = name === 'collect' ? '通过 ' + result.valid + ' 项，待核查 ' + result.invalid + ' 项。详情见结果与修订。' : 'DPDispatcher · ' + result.status + ' · ' + result.submission_hash;
    await refresh();
  }
}
field('refresh').onclick = field('config').onchange = () => locked(async () => {field('feedback').textContent=''; await refresh();});
field('machine').onchange = () => {preview=null; controls();};
field('preview').onclick = () => locked(() => action('plan'));
field('submit').onclick = () => locked(() => action(['submitted','interrupted_or_failed'].includes(current.dispatch?.status) ? 'recover' : 'submit'));
field('collect').onclick = () => locked(() => action('collect'));
locked(async () => {
  const options = await api('/api/jobs/options');
  picker('config', ToolShell.modelRun?options.runs.filter(n=>n===ToolShell.modelRun):options.runs, '请选择配置');
  picker('machine', options.machines, '请选择机器');
  field('profiles').textContent = '服务端从此目录读取机器配置：' + options.profile_directory;
  const requested = new URLSearchParams(location.search).get('config');
  if (options.runs.includes(requested)) field('config').value=requested;
  await refresh();
});
