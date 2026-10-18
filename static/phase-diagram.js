"use strict";
const el = id => document.getElementById(id);
let sourceLoaded = null, output = null, busy = false;
function notice(text, error = false) {
    el("notice").textContent = text;
    el("notice").className = "alert " + (error ? "alert-warning" : "alert-secondary");
}
function source() {
    return {tdb_files: el("databases").value.split(/\r?\n/).map(s => s.trim()).filter(Boolean), config: el("config").value.trim() || null};
}
async function post(url, data) {
    const response = await fetch(url, {method: "POST", headers: {"Content-Type": "application/json"}, body: JSON.stringify(data)});
    const result = await response.json();
    if (!response.ok) throw new Error(typeof result.detail === "string" ? result.detail : JSON.stringify(result.detail || result));
    return result;
}
function number(id) {
    if (!el(id).value.trim()) throw new Error("请填写 " + id);
    const value = Number(el(id).value);
    if (!Number.isFinite(value)) throw new Error("无效数值：" + id);
    return value;
}
function composition(id) {
    const result = {};
    for (const item of el(id).value.split(",")) {
        const pair = item.trim().split("="), key = pair[0].trim().toUpperCase();
        if (pair.length !== 2 || !key || !pair[1].trim() || key in result || !Number.isFinite(Number(pair[1])))
            throw new Error("成分格式：AL=0.5, NI=0.5；合计为 1。");
        result[key] = Number(pair[1]);
    }
    return result;
}
function payload() {
    if (JSON.stringify(source()) !== sourceLoaded) throw new Error("数据库来源已改变，请重新读取。");
    const mode = el("mode").value;
    const start = number("temperature-min");
    let temperatures = [start];
    if (!["ternary", "point"].includes(mode)) {
        const end = number("temperature-max"), count = number("temperature-count");
        if (end <= start || !Number.isInteger(count) || count < 2 || count > 301) throw new Error("检查温度范围和点数。");
        temperatures = Array.from({length: count}, (_, i) => start + (end-start)*i/(count-1));
    }
    const result = {...source(), mode, temperatures, pressure: number("pressure"),
        components: el("components").value.split(",").map(s => s.trim().toUpperCase()).filter(Boolean),
        phases: Array.from(el("phase-choices").querySelectorAll("input:checked"), input => input.value),
        points: number("points"), sampling_density: number("density"), verify_sampling: el("verify").checked,
        map_boundaries: el("mapping").checked, max_mapping_steps: number("mapping-steps"),
        allow_missing_ordered_endmembers: el("missing-ordered").checked};
    if (mode === "binary") {
        result.x_component = el("x-component").value.trim().toUpperCase() || null;
        result.composition_range = el("x-range").value.split(",").map(Number);
        if (result.composition_range.length !== 2 || !result.composition_range.every(Number.isFinite)) throw new Error("横轴范围格式：0, 1");
    }
    if (mode === "isopleth") {
        result.composition_start = composition("composition-start"); result.composition_end = composition("composition-end");
    }
    if (["point", "property"].includes(mode)) result.composition = composition("composition");
    return result;
}
function modeChanged() {
    const mode = el("mode").value;
    for (const [cls, visible] of Object.entries({"temperature-sweep": !["ternary", "point"].includes(mode),
        "composition-grid": ["binary", "ternary", "isopleth"].includes(mode), "binary-only": mode === "binary",
        "path-only": mode === "isopleth", "fixed-only": ["point", "property"].includes(mode)}))
        document.querySelectorAll("." + cls).forEach(item => { item.hidden = !visible; });
    const n = Number(el("points").value), t = Number(el("temperature-count").value);
    const count = mode === "ternary" ? n*(n+1)/2 : mode === "point" ? 1 : mode === "property" ? t : n*t;
    el("estimate").textContent = `共 ${count} 个平衡点（上限 10000）。有序多亚点阵数据库和相界追踪可能需要数分钟。`;
}
async function loadSource() {
    const options = await post("/phase-diagram/options", source());
    el("phase-choices").replaceChildren();
    for (const phase of options.phases) {
        const label = document.createElement("label"), checkbox = document.createElement("input");
        checkbox.type = "checkbox"; checkbox.checked = true; checkbox.value = phase.name; checkbox.className = "me-2";
        label.append(checkbox, document.createTextNode(`${phase.name} (${phase.sublattices.length} 亚点阵)`));
        label.title = phase.sublattices.map((s, i) => `${phase.site_ratios[i]}: ${s.join(",")}`).join(" | ");
        el("phase-choices").append(label);
    }
    el("available-components").textContent = "数据库组元：" + options.components.join(", ");
    if (!el("components").value.trim()) el("components").value = options.components.slice(0, 2).join(", ");
    sourceLoaded = JSON.stringify(source());
    el("model-options").hidden = false;
    el("calculate").disabled = false; el("save-request").disabled = false;
    notice("已载入数据库。选择组元与计算条件后开始计算。");
}
el("load").addEventListener("click", async () => {
    el("load").disabled = true; el("calculate").disabled = true; el("save-request").disabled = true;
    try { await loadSource(); } catch (error) { notice(error.message, true); }
    finally { el("load").disabled = false; }
});
for (const id of ["databases", "config"]) el(id).addEventListener("input", () => {
    sourceLoaded = null; el("calculate").disabled = true; el("save-request").disabled = true;
});
for (const id of ["mode", "points", "temperature-count"]) el(id).addEventListener("change", modeChanged);
el("tdb-upload").addEventListener("change", async () => {
    try {
        for (const file of el("tdb-upload").files) {
            const data = new FormData(); data.append("file", file);
            const response = await fetch("/upload_file", {method: "POST", body: data});
            const result = await response.json();
            if (!response.ok) throw new Error(result.detail || "TDB 上传失败");
            el("databases").value += (el("databases").value.trim() ? "\n" : "") + result.file_path;
        }
        el("databases").dispatchEvent(new Event("input"));
        notice("文件已上传，请读取组元与相。");
    } catch (error) { notice(error.message, true); }
});
function saveRequest() {
    const url = URL.createObjectURL(new Blob([JSON.stringify(payload(), null, 2)], {type: "application/json"}));
    const link = document.createElement("a"); link.href = url; link.download = "phase-diagram-request.json"; link.click();
    setTimeout(() => URL.revokeObjectURL(url), 1000);
}
el("save-request").addEventListener("click", () => { try { saveRequest(); } catch (error) { notice(error.message, true); } });
function showPoint() {
    const row = output.rows[Number(el("point").value)];
    el("point-summary").textContent = row.status === "accepted" ?
        `G = ${row.G_J_mol_atoms.toPrecision(10)} J/mol-atoms；${row.sampling_verified ? "两档采样一致" : "采样未确认"}；` +
        Object.entries(row.chemical_potentials_J_mol_atoms).map(([c, mu]) => `μ(${c})=${mu.toPrecision(7)}`).join("，") : "求解失败，参见数值检查。";
    el("point-phases").replaceChildren();
    for (const state of row.phases) {
        const tr = document.createElement("tr");
        const values = [state.instance, state.amount.toPrecision(7),
            Object.entries(state.composition).map(([c, x]) => `${c}=${x.toPrecision(6)}`).join(", "), state.G_J_mol_atoms.toPrecision(10),
            Object.entries(state.site_fractions).map(([c, y]) => `${c}=${y.toPrecision(5)}`).join("; ")];
        values.forEach(value => { const td = document.createElement("td"); td.textContent = value; tr.append(td); });
        el("point-phases").append(tr);
    }
    el("diagnostics").textContent = JSON.stringify({point: row, active_phases: output.active_phases, excluded_phases: output.excluded_phases,
        sources: output.sources, engine: output.engine, mapping: Object.fromEntries(Object.entries(output.boundaries).filter(([k]) => !["lines", "invariants"].includes(k))), warnings: output.warnings}, null, 2);
}
el("point").addEventListener("change", showPoint);
el("calculate").addEventListener("click", async () => {
    if (busy) return;
    let request;
    try { request = payload(); } catch (error) { notice(error.message, true); return; }
    busy = true; el("calculate").disabled = true; el("results").hidden = true;
    notice("正在求解多相平衡、复查采样密度并追踪相界。请保持页面打开；长计算也可以使用 CLI / TUI。");
    try {
        output = await post("/phase-diagram/calculate", request);
        const s = output.summary;
        el("summary").textContent = `${s.accepted_points}/${s.total_points} 个点通过数值审查；${s.failed_points} 个失败；${s.needs_refinement_points} 个需加密复查。相界追踪：${output.boundaries.status}。`;
        el("result-title").textContent = output.components.join("–") + " · " +
            Array.from(el("mode").options).find(option => option.value === output.mode).textContent;
        el("plot").src = output.urls.png;
        el("downloads").replaceChildren();
        for (const [kind, url] of Object.entries(output.urls)) {
            const link = document.createElement("a"); link.href = url; link.textContent = kind.toUpperCase();
            if (kind !== "html") link.download = ""; else link.target = "_blank";
            el("downloads").append(link);
        }
        el("point").replaceChildren(...output.rows.map((r, i) => new Option(
            `#${r.point_id} · ${r.T_K.toFixed(2)} K · ${Object.entries(r.composition).map(([c,x])=>`${c}=${x.toFixed(4)}`).join(", ")} · ${r.assemblage}`, i)));
        showPoint(); el("results").hidden = false;
        notice(output.status === "calculated" ? "计算完成，所有请求点已通过数值审查。" : "已保存部分结果。请检查失败点、采样差异或提前终止的相界分支，再加密复算。", output.status !== "calculated");
    } catch (error) { notice(error.message, true); }
    finally { busy = false; el("calculate").disabled = JSON.stringify(source()) !== sourceLoaded; }
});
el("request-upload").addEventListener("change", async () => {
    try {
        const file = el("request-upload").files[0]; if (!file) return;
        const request = JSON.parse((await file.text()).replace(/^\uFEFF/, ""));
        const known = new Set(["mode", "tdb_files", "config", "components", "phases", "suspended_phases", "temperatures", "pressure", "x_component", "composition_range", "composition", "composition_start", "composition_end", "points", "sampling_density", "verify_sampling", "map_boundaries", "max_mapping_steps", "allow_missing_ordered_endmembers"]);
        if (Object.keys(request).some(k => !known.has(k))) throw new Error("请求包含网页不支持的字段；请使用 CLI 原样运行。");
        const ts = request.temperatures;
        if (!Array.isArray(ts) || !ts.length || ts.some((t, i) => i && t <= ts[i-1])) throw new Error("网页导入需要升序温度序列。");
        if (ts.length > 2 && ts.some((t, i) => Math.abs(t-(ts[0]+i*(ts.at(-1)-ts[0])/(ts.length-1))) > 1e-8)) throw new Error("非均匀温度序列请使用 CLI；网页不自动重采样。");
        el("databases").value = (request.tdb_files || []).join("\n"); el("config").value = request.config || "";
        el("components").value = request.components.join(", ");
        await loadSource();
        const boxes = Array.from(el("phase-choices").querySelectorAll("input"));
        const names = new Set(boxes.map(input => input.value));
        if ([...(request.phases || []), ...(request.suspended_phases || [])].some(name => !names.has(name))) throw new Error("请求包含数据库中不存在的相。");
        boxes.forEach(input => { input.checked = (!request.phases || request.phases.includes(input.value)) && !(request.suspended_phases || []).includes(input.value); });
        el("mode").value = request.mode || "binary";
        for (const [id, value] of Object.entries({"temperature-min": ts[0], "temperature-max": ts.at(-1), "temperature-count": ts.length,
            pressure: request.pressure ?? 101325, points: request.points ?? 31, density: request.sampling_density ?? 200,
            "mapping-steps": request.max_mapping_steps ?? 5000, "x-component": request.x_component || "", "x-range": (request.composition_range || [0,1]).join(", ")})) el(id).value = value;
        for (const [id, key] of [["composition", "composition"], ["composition-start", "composition_start"], ["composition-end", "composition_end"]])
            el(id).value = Object.entries(request[key] || {}).map(([c,x]) => `${c}=${x}`).join(", ");
        el("verify").checked = request.verify_sampling ?? true; el("mapping").checked = request.map_boundaries ?? true;
        el("missing-ordered").checked = request.allow_missing_ordered_endmembers ?? false;
        modeChanged(); notice("计算参数已导入，可以计算或导出参数。");
    } catch (error) { sourceLoaded = null; el("calculate").disabled = true; el("save-request").disabled = true; notice(error.message, true); }
});
modeChanged();
