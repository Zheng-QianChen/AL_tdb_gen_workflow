const el = id => document.getElementById(id);
async function post(url, body) {
  const response = await fetch(url, {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify(body)});
  const value = await response.json();
  if (!response.ok) throw new Error(typeof value.detail === 'string' ? value.detail : JSON.stringify(value.detail || value));
  return value;
}
el('demo').onclick = async () => {
  try { const data = await post('/parameter-fit/demo', {}); el('request').value = JSON.stringify(data.request,null,2); el('status').textContent = '已载入合成数据：目标系数 A=2400 J/mol、B=3 J/(mol·K)。'; }
  catch (error) { el('status').textContent = error.message; }
};
el('import').onchange = async event => {
  try { const file=event.target.files[0]; if(file) el('request').value=JSON.stringify(JSON.parse((await file.text()).replace(/^\uFEFF/,'')),null,2); }
  catch(error) { el('status').textContent='读取失败：'+error.message; }
};
el('run').onclick = async () => {
  el('run').disabled=true; el('demo').disabled=true; el('downloads').replaceChildren();
  el('parameters').hidden=true; el('details').textContent=''; el('status').textContent='正在拟合并检查分支、相组成和留出数据……';
  try {
    const data=await post('/parameter-fit/calculate',JSON.parse(el('request').value));
    el('status').textContent=(data.candidate_is_optimizer_solution
      ? (data.optimizer_success?'优化器已收敛。':'达到限制，优化器未收敛。')
      : '优化器的最终解未通过相组合检查，已回退到本次评估中误差最小且保留训练相组合的候选；此候选未被证明收敛。')
      +(data.training_assemblages_valid?'训练相组合检查通过。':'训练相组合检查未通过。')
      +(data.all_observations_within_requested_scales?'所有观测均在指定误差尺度内。':'仍有观测超出指定误差尺度。');
    const tbody=el('parameters').querySelector('tbody'); tbody.replaceChildren();
    for (const p of data.parameters) { const tr=document.createElement('tr'); for(const value of [p.id,p.fitted.toPrecision(8),p.physical_coefficient.toPrecision(8),p.near_bound?'是':'否']) {const td=document.createElement('td');td.textContent=value;tr.append(td);} tbody.append(tr); }
    el('parameters').hidden=false;
    for (const [key,url] of Object.entries(data.urls || {})) { if(!url.startsWith('/get_data_file/')) continue; const a=document.createElement('a');a.href=url;a.textContent=({candidate:'下载候选 TDB',result:'完整拟合记录',request:'任务 JSON'})[key] || key;el('downloads').append(a); }
    el('details').textContent=JSON.stringify({status:data.status,candidate_selection:data.candidate_selection,optimizer_success:data.optimizer_success,candidate_is_optimizer_solution:data.candidate_is_optimizer_solution,training_assemblages_valid:data.training_assemblages_valid,optimizer_training_assemblages_valid:data.optimizer_training_assemblages_valid,termination:data.termination,holdout_validation_passed:data.holdout_validation_passed,validation_scope:data.validation_scope,independent_validation_passed:data.independent_validation_passed,ready_for_production:data.ready_for_production,observations:data.observations},null,2);
  } catch(error) { el('status').textContent='拟合未完成：'+error.message; }
  finally { el('run').disabled=false;el('demo').disabled=false; }
};
