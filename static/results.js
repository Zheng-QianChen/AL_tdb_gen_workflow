'use strict';
const $ = id => document.getElementById(id);
const sources = {vasp:'VASP 计算', synthetic:'人工示例', manual:'手工导入', manual_override:'人工修订', external_dataset:'外部数据', legacy_unverified:'旧格式 / 未重新验证', ml:'ML 预测'};
const labels = {incar:'INCAR 设置', settings:'计算设置', calculation_settings:'计算设置', timing:'计算耗时', convergence:'收敛性', electronic_converged:'电子收敛', ionic_converged:'离子收敛', elapsed_seconds:'实际耗时 / s', cpu_seconds:'CPU 时间 / s', vasp_version:'VASP 版本', energy_definition:'能量定义', ionic_steps:'离子步数', warnings:'待核查项', kpoints:'K 点设置', input_hashes:'输入文件 SHA256', source_hash:'结果 SHA256', completed:'完整结束', electronic:'电子收敛', ionic:'离子收敛'};
Object.assign(labels, {final_energy_definition:'能量定义', energy_ev_cell:'原始总能量 / eV·cell⁻¹', finished:'完整结束', ionic_convergence_applicability:'离子收敛适用性', electronic_steps_final:'最终电子步数', effective_settings:'输出记录的生效设置'});
let selected = null, activeConfig = '', rows = [], generation = 0, detailGeneration = 0;
const text = (tag, value, className) => {
  const el = document.createElement(tag); el.textContent = String(value ?? '未记录');
  if (className) el.className = className; return el;
};
const number = value => Number.isFinite(value) ? String(Number(value.toPrecision(12))) : '未记录';
const display = value => value === null || value === undefined ? '未记录 / 未判定' : typeof value === 'boolean' ? (value ? '是' : '否') : typeof value === 'object' ? JSON.stringify(value, null, 2) : String(value);
async function request(url, options) {
  const response = await fetch(url, options);
  const data = await response.json();
  if (!response.ok) {
    const message = typeof data.detail === 'string' ? data.detail : JSON.stringify(data.detail || data);
    const error = new Error(message); error.status = response.status; throw error;
  }
  return data;
}
function query(config = activeConfig) { return '?config=' + encodeURIComponent(config); }
function renderAttempts(attempts) {
  $('attempts').replaceChildren();
  if (!attempts.length) $('attempts').append(text('p','尚无计算收集记录。手工导入不产生 VASP 收集诊断。','muted'));
  attempts.forEach(item => {
    const details = document.createElement('details');
    details.append(text('summary', `轮次 ${item.iteration} · ${item.endmember} · ${item.status === 'valid' ? '通过' : '未通过'} · ${item.timestamp}`));
    if (item.error) details.append(text('p', item.error));
    details.append(text('pre', JSON.stringify({analysis:item.analysis,evidence:item.evidence}, null, 2)));
    $('attempts').append(details);
  });
}
function tab(panel) {
  document.querySelectorAll('[data-tab]').forEach(button => {
    const active = button.dataset.tab === panel;
    button.classList.toggle('active', active); button.setAttribute('aria-selected', String(active));
    $(button.dataset.tab).hidden = !active;
  });
}
document.querySelectorAll('[data-tab]').forEach(button => button.addEventListener('click', () => tab(button.dataset.tab)));
function renderRows() {
  $('records').replaceChildren(); $('count').textContent = `${rows.length} 条记录`;
  $('empty').hidden = rows.length > 0;
  $('empty').textContent = '这个运行尚无结果记录。导入结果或完成收集后，记录会显示在这里。';
  rows.forEach(row => {
    const tr = document.createElement('tr'); tr.classList.toggle('selected', row.id === selected?.id);
    const first = document.createElement('td'); const button = text('button', row.endmember, 'record-select');
    button.type = 'button'; button.addEventListener('click', () => selectRecord(row.id));
    first.append(button, text('small', `轮次 ${row.iteration}`));
    const origin = document.createElement('td'); origin.append(text('span', sources[row.source_kind] || row.source_kind), text('small', `v${row.revision}`));
    tr.append(first, text('td', number(row.energy_ev_cell)), origin); $('records').append(tr);
  });
}
function renderAnalysis(analysis) {
  $('analysis').replaceChildren();
  const scalar = {}, nested = [];
  Object.entries(analysis || {}).forEach(([key, value]) => {
    if (value && typeof value === 'object' && !Array.isArray(value)) nested.push([key, value]);
    else scalar[key] = value;
  });
  function group(title, values) {
    if (!Object.keys(values).length) return;
    const section = document.createElement('section'); section.className = 'analysis-group';
    section.append(text('h3', title)); const dl = document.createElement('dl'); dl.className = 'facts';
    Object.entries(values).forEach(([key, value]) => dl.append(text('dt', labels[key] || key), text('dd', display(value))));
    section.append(dl); $('analysis').append(section);
  }
  group('计算概况', scalar); nested.forEach(([key, value]) => group(labels[key] || key, value));
  if (!Object.keys(analysis || {}).length) $('analysis').append(text('p','此记录没有原始计算分析。手工导入的能量不能单独证明收敛。','muted'));
}
function showDetail(data) {
  selected = data.record; $('detail').hidden = false;
  $('record-title').textContent = selected.endmember;
  $('record-label').textContent = `轮次 ${selected.iteration} / 当前版本 v${selected.revision}`;
  $('source').textContent = sources[selected.source_kind] || selected.source_kind;
  $('energy').textContent = number(selected.energy_ev_cell);
  $('record-note').textContent = selected.note || '';
  renderAnalysis(selected.analysis);
  $('evidence').textContent = JSON.stringify({original: data.original, evidence: selected.evidence}, null, 2);
  $('history').replaceChildren();
  (data.history || []).slice().reverse().forEach(entry => {
    const li = document.createElement('li');
    li.append(text('h3', `v${entry.revision} · ${entry.actor || '系统导入'}`), text('p', entry.timestamp || entry.modified_at || entry.created_at || '', 'muted'), text('p', entry.reason || '初始记录'));
    const details = document.createElement('details'); details.append(text('summary','查看这一版本的完整记录'), text('pre',JSON.stringify(entry,null,2))); li.append(details); $('history').append(li);
  });
  $('edit-energy').value = selected.energy_ev_cell; $('edit-note').value = selected.note || '';
  $('revision').value = selected.revision; $('reason').value = ''; $('edit-status').textContent = '';
  renderRows();
}
async function selectRecord(id) {
  const ticket = ++detailGeneration, runTicket = generation, config = activeConfig;
  $('notice').textContent = '正在读取记录…';
  try {
    const data = await request('/api/results/' + encodeURIComponent(id) + query(config));
    if (ticket !== detailGeneration || runTicket !== generation) return;
    showDetail(data); $('notice').textContent = ''; tab('analysis-panel');
  } catch (error) { if (ticket === detailGeneration && runTicket === generation) $('notice').textContent = error.message; }
}
$('run-form').addEventListener('submit', async event => {
  event.preventDefault(); const config = $('config').value; if (!config) return;
  const ticket = ++generation; ++detailGeneration; selected = null; activeConfig = config;
  ToolShell.setRun(config);
  $('detail').hidden = true; $('records').replaceChildren(); $('attempts').replaceChildren(); $('notice').textContent = '正在读取结果记录…'; $('load').disabled = true;
  try {
    const iteration = $('iteration').value; const url = '/api/results' + query(config) + (iteration === '' ? '' : '&iteration=' + encodeURIComponent(iteration));
    const [data, diagnostics] = await Promise.all([request(url), request(url.replace('/api/results?', '/api/results/attempts?'))]); if (ticket !== generation) return;
    rows = data.records; renderRows(); renderAttempts(diagnostics.attempts); $('notice').textContent = '';
    if (rows.length) await selectRecord(rows[0].id);
  } catch (error) { if (ticket === generation) { rows=[]; renderRows(); $('notice').textContent=error.message; } }
  finally { if (ticket === generation) $('load').disabled = false; }
});
$('edit-form').addEventListener('submit', async event => {
  event.preventDefault(); if (!selected) return;
  const energy = Number($('edit-energy').value), actor = $('actor').value.trim(), reason = $('reason').value.trim();
  if (!Number.isFinite(energy) || !actor || !reason) { $('edit-status').textContent='请填写有限数值、修改人和原因。'; return; }
  const config=activeConfig, id=selected.id, ticket=generation, selectionTicket=detailGeneration;
  const payload={expected_revision:selected.revision, actor, reason};
  if (energy !== selected.energy_ev_cell) payload.energy_ev_cell=energy;
  if ($('edit-note').value !== (selected.note || '')) payload.note=$('edit-note').value;
  if (!('energy_ev_cell' in payload) && !('note' in payload)) { $('edit-status').textContent='条目尚未修改。'; return; }
  $('save').disabled=true; $('edit-status').textContent='正在保存修订…';
  try {
    const data=await request('/api/results/'+encodeURIComponent(id)+query(config), {method:'PATCH',headers:{'Content-Type':'application/json'},body:JSON.stringify(payload)});
    if (ticket!==generation || selectionTicket!==detailGeneration) return;
    rows=rows.map(row=>row.id===id?data.record:row); showDetail(data); tab('history-panel');
    $('notice').textContent=`已保存 v${data.record.revision}，原始记录和历史修订均已保留。`;
  } catch (error) {
    if(ticket===generation && selectionTicket===detailGeneration) $('edit-status').textContent=error.status===409?'这条记录已被更新。请重新选择该记录，核对最新版本后再修订；本次修改未保存。':error.message;
  } finally { $('save').disabled=false; }
});
async function initialize() {
  try {
    const data=await request('/api/results/configs'); if(ToolShell.modelRun)data.configs=data.configs.filter(n=>n===ToolShell.modelRun); $('config').replaceChildren();
    const placeholder=text('option',data.configs.length?'请选择运行配置':'尚无运行配置'); placeholder.value=''; $('config').append(placeholder);
    data.configs.forEach(name=>{const option=text('option',name); option.value=name; $('config').append(option);});
    const requested=new URLSearchParams(location.search).get('config');
    if(requested && data.configs.includes(requested)) { $('config').value=requested; $('run-form').requestSubmit(); }
  } catch(error) { $('notice').textContent=error.message; $('config').replaceChildren(text('option','读取配置失败')); }
}
initialize();
