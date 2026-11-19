'use strict';
let trialRevision = 0;
function resetTrials() {
    trialRevision++;
    document.getElementById('trial-results').replaceChildren();
}
function occupancyChoices(groups, weights, model, task) {
    const container = document.getElementById('dynamic-element-groups');
    container.replaceChildren();
    container.dataset.model = model;
    container.dataset.task = task;
    resetTrials();
    groups.forEach((site, index) => {
        const group = document.createElement('fieldset');
        const legend = document.createElement('legend');
        legend.textContent = '位点 ' + (index + 1) + ' · 比例 ' + weights[index];
        group.append(legend);
        for (const element of site.slice().sort()) {
            const label = document.createElement('label'), select = document.createElement('select');
            label.className='me-3 mb-2';
            select.dataset.element = element;
            select.append(new Option('保留', 'fix'), new Option('尝试去掉', 'analys'), new Option('指定去掉', 'need_del'));
            select.onchange = resetTrials;
            label.append(element + ' ', select); group.append(label);
        }
        container.append(group);
    });
}
async function compareTrialChoices() {
    const container = document.getElementById('dynamic-element-groups');
    if (!assessmentTaskId || container.dataset.task !== assessmentTaskId || container.dataset.model !== selectedModel) {
        showAlert('请先确认当前模型'); return;
    }
    resetTrials();
    const revision = trialRevision, task = assessmentTaskId;
    const payload = {selected_model:selectedModel, fix:[], need_del:[], analys:[]};
    for (const site of container.querySelectorAll('fieldset')) {
        const choices = {fix:[], need_del:[], analys:[]};
        for (const select of site.querySelectorAll('select')) choices[select.value].push(select.dataset.element);
        if (!choices.fix.length && !choices.analys.length) {showAlert('每个位点至少保留一种元素'); return;}
        for (const key of Object.keys(choices)) payload[key].push(choices[key]);
    }
    const button = document.getElementById('apply-filters'), output = document.getElementById('trial-results');
    try {payload.protected = document.getElementById('trial-probes').value.split(/\r?\n/).map(line=>line.trim()).filter(Boolean).map(line=>JSON.parse(line));}
    catch (error) {output.textContent='实验成分格式有误：'+error.message; return;}
    button.disabled = true; output.textContent = '正在比较各候选的成分覆盖和下凸包能量…';
    try {
        const response = await fetch(assessmentURL('/occupancy-trials'), {method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(payload)});
        const data = await response.json();
        if (revision !== trialRevision || task !== assessmentTaskId || payload.selected_model !== selectedModel) return;
        if (!response.ok) throw Error(data.detail);
        output.replaceChildren();
        const table = document.createElement('table'); table.className='table table-sm';
        const head = table.createTHead().insertRow();
        for (const title of ['尝试','各位点允许元素','端元 / 缺项','覆盖成分 / 总数','最大能量升高 (kJ/mol-atoms)','删减影响','候选文件']) {
            const th=document.createElement('th'); th.textContent=title; head.append(th);
        }
        const body = table.createTBody();
        data.candidates.forEach((candidate, index) => {
            const row=body.insertRow();
            for (const value of [candidate.label, candidate.sites.map(s=>s.join('/')).join(' : '),
                 candidate.endmembers + ' / ' + candidate.missing, candidate.covered + ' / ' + data.compositions,
                 candidate.max_rise?.toPrecision(4) ?? '无共同成分']) row.insertCell().textContent=value;
            const evidence=row.insertCell();
            evidence.textContent = '有成分点失去覆盖的二元系：' + (candidate.lost_binary_edges.join('、') || '无') +
                '；移除端元来源：' + (Object.entries(candidate.removed_sources).map(([k,v])=>k+' × '+v).join('、') || '无');
            for (const p of candidate.protected_points) {
                const line=document.createElement('div');
                line.textContent=p.source+' · '+(p.temperature_K ? p.temperature_K+' K · ' : '')+
                    (p.candidate_covered ? '成分可表示' : p.baseline_covered ? '删减后失去覆盖' : '原模型亦未覆盖'); evidence.append(line);
            }
            const save=document.createElement('button'); save.type='button'; save.textContent='导出此候选'; save.className='btn btn-sm btn-outline-primary';
            save.disabled=Boolean(candidate.missing || !candidate.endmembers);
            const cell=row.insertCell(); cell.append(save);
            save.onclick=async () => {
                save.disabled=true;
                try {
                    const res=await fetch('/occupancy-trials/'+data.id+'/'+index+'/export?task_id='+encodeURIComponent(task), {method:'POST'});
                    const result=await res.json();
                    if (!res.ok) throw Error(result.detail);
                    const link=document.createElement('a'); link.href=result.url; link.textContent='下载候选 TDB'; link.download=''; cell.replaceChildren(link);
                } catch (error) {save.disabled=false; showAlert(error.message);}
            };
        });
        output.append(table);
        document.getElementById('step4-next').disabled=false;
    } catch (error) {if (revision===trialRevision) output.textContent=error.message;}
    finally {button.disabled=false;}
}
