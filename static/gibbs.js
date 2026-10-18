"use strict";
const element = id => document.getElementById(id);
let loadedSource = null;
let modelOptions = null;
const notice = (message, error = false) => {
    element("notice").textContent = message;
    element("notice").className = "alert " + (error ? "alert-danger" : "alert-secondary");
};
function source() {
    return {config: element("config").value.trim() || null,
        phase: element("phase").value.trim() || null,
        tdb_files: element("databases").value.split(/\r?\n/).map(s => s.trim()).filter(Boolean)};
}
async function post(url, data) {
    const response = await fetch(url, {method: "POST", headers: {"Content-Type": "application/json"}, body: JSON.stringify(data)});
    const result = await response.json();
    if (!response.ok) throw new Error(typeof result.detail === "string" ? result.detail : JSON.stringify(result.detail || result));
    return result;
}
function composition(text) {
    const result = {};
    for (const part of text.split(",")) {
        const pair = part.trim().split("=");
        if (pair.length !== 2 || !pair[0].trim() || !pair[1].trim()) throw new Error("成分请填写为 AL=0.5, NI=0.5，合计为 1。");
        const key = pair[0].trim().toUpperCase(), value = Number(pair[1]);
        if (key in result || !Number.isFinite(value)) throw new Error("成分包含重复组元或无效数值。");
        result[key] = value;
    }
    return result;
}
function selectedGroups() {
    return Array.from(element("sublattices").querySelectorAll("fieldset"), group =>
        Array.from(group.querySelectorAll("input:checked"), input => input.value));
}
function initialCompositions() {
    const groups = selectedGroups();
    if (groups.some(group => !group.length)) return;
    const start = {}, end = {}, middle = {};
    groups.forEach((group, i) => {
        const weight = modelOptions.site_ratios[i];
        if (group[0] !== "VA") start[group[0]] = (start[group[0]] || 0) + weight;
        const last = group[group.length - 1];
        if (last !== "VA") end[last] = (end[last] || 0) + weight;
    });
    for (const values of [start, end]) {
        const atoms = Object.values(values).reduce((a, b) => a + b, 0);
        if (!atoms) return;
        Object.keys(values).forEach(name => { values[name] /= atoms; });
    }
    const components = Array.from(new Set(groups.flat())).filter(name => name !== "VA").sort();
    components.forEach(name => { middle[name] = ((start[name] || 0) + (end[name] || 0)) / 2; });
    const format = values => Object.entries(values).map(([name, value]) => `${name}=${Number(value.toPrecision(15))}`).join(", ");
    element("start").value = format(start); element("end").value = format(end); element("composition").value = format(middle);
    element("axis").replaceChildren(...components.map(name => new Option(name, name)));
    element("axis").value = components.filter(name => (start[name] || 0) !== (end[name] || 0)).at(-1) || components[0];
}
element("load").addEventListener("click", async () => {
    element("load").disabled = true; element("calculate").disabled = true;
    notice("正在读取相模型…");
    try {
        modelOptions = await post("/gibbs/options", source());
        element("phase").value = modelOptions.phase;
        loadedSource = JSON.stringify(source());
        element("sublattices").replaceChildren();
        modelOptions.sublattices.forEach((group, index) => {
            const fieldset = document.createElement("fieldset"), legend = document.createElement("legend");
            legend.textContent = `亚点阵 ${index + 1} · 位点数 ${modelOptions.site_ratios[index]}`;
            fieldset.append(legend);
            group.forEach(name => {
                const label = document.createElement("label"), input = document.createElement("input");
                input.type = "checkbox"; input.value = name; input.checked = true; input.className = "form-check-input me-2";
                input.addEventListener("change", initialCompositions);
                label.append(input, document.createTextNode(name)); fieldset.append(label);
            });
            element("sublattices").append(fieldset);
        });
        initialCompositions(); element("calculate").disabled = false;
        notice(`已载入 ${modelOptions.phase}。默认成分端点来自所选亚点阵，可按需要修改。`);
    } catch (error) { notice(error.message, true); }
    finally { element("load").disabled = false; }
});
for (const id of ["config", "phase", "databases"]) element(id).addEventListener("input", () => {
    element("calculate").disabled = true; notice("模型来源已改变，请重新读取亚点阵。");
});
element("mode").addEventListener("change", () => {
    element("gx-fields").hidden = element("mode").value !== "gx";
    element("gt-fields").hidden = element("mode").value !== "gt";
});
element("calculate").addEventListener("click", async () => {
    element("calculate").disabled = true; element("results").hidden = true;
    try {
        if (JSON.stringify(source()) !== loadedSource) throw new Error("请重新读取当前模型。");
        const mode = element("mode").value;
        const payload = {...source(), mode, sublattices: selectedGroups(), pressure: Number(element("pressure").value), starts: Number(element("starts").value)};
        if (mode === "gx") {
            payload.temperatures = element("temperatures").value.split(",").map(s => Number(s.trim()));
            payload.points = Number(element("points").value); payload.x_axis = element("axis").value;
            payload.composition_start = composition(element("start").value); payload.composition_end = composition(element("end").value);
        } else {
            const lo = Number(element("t-min").value), hi = Number(element("t-max").value), count = Number(element("t-points").value);
            if (!Number.isInteger(count) || count < 2 || count > 501 || !(lo > 0 && hi > lo)) throw new Error("请设置递增的正温度范围与 2–501 个采样点。");
            payload.temperatures = Array.from({length: count}, (_, i) => lo + (hi-lo)*i/(count-1));
            payload.composition = composition(element("composition").value);
        }
        notice("正在计算各点自由能并优化亚点阵占位…");
        const result = await post("/gibbs/calculate", payload);
        element("compare-result").value = result.files.json;
        element("plot").src = result.urls.png;
        element("result-title").textContent = `${result.phase} · ${mode === "gx" ? "G–成分" : "G–温度"}`;
        element("summary").textContent = `${result.rows.length} 个计算点；图中单位 kJ/mol-atoms，CSV 中单位 J/mol-atoms。`;
        element("downloads").replaceChildren();
        for (const [key, url] of Object.entries(result.urls)) {
            const link = document.createElement("a"); link.href = url; link.download = `gibbs.${key}`;
            link.textContent = `下载 ${key.toUpperCase()}`; element("downloads").append(link);
        }
        const requestLink = document.createElement("a");
        if (element("downloads").dataset.requestUrl) URL.revokeObjectURL(element("downloads").dataset.requestUrl);
        requestLink.href = URL.createObjectURL(new Blob([JSON.stringify(payload, null, 2)], {type: "application/json"}));
        element("downloads").dataset.requestUrl = requestLink.href;
        requestLink.download = "gibbs-request.json"; requestLink.textContent = "保存参数供 CLI/TUI 使用"; element("downloads").append(requestLink);
        element("results").hidden = false; notice("计算完成。结果已保存到数据目录的 gibbs/ 文件夹。");
    } catch (error) { notice(error.message, true); }
    finally { element("calculate").disabled = JSON.stringify(source()) !== loadedSource; }
});
try {
    const saved = JSON.parse(sessionStorage.getItem("altdb_gibbs_source") || "null");
    if (saved) {
        element("databases").value = saved.tdb_files.join("\n"); element("phase").value = saved.phase;
        notice("已带入选定模型的 TDB。请添加相容参考数据库，再读取亚点阵。");
    }
} catch { /* Ignore stale browser state. */ }

function comparisonNotice(message, error = false) {
    element("compare-notice").textContent = message;
    element("compare-notice").className = "alert mt-3 " + (error ? "alert-danger" : "alert-secondary");
}
function comparisonDownloads(id, urls) {
    element(id).replaceChildren();
    for (const [key, url] of Object.entries(urls)) {
        const link = document.createElement("a");
        link.href = url; link.download = "";
        link.textContent = `下载 ${key.toUpperCase()}`;
        element(id).append(link);
    }
}
element("reference-template").addEventListener("click", async () => {
    element("reference-template").disabled = true;
    try {
        const result = await post("/gibbs/reference-template", {result: element("compare-result").value.trim()});
        comparisonDownloads("reference-downloads", result.urls);
        comparisonNotice(`已生成 ${result.point_count} 个点的空白参考表。请填入外部 G，修改 compare.json 的软件名、版本、单位，并核对模型条件。文件保存在：${result.files.request}`);
    } catch (error) { comparisonNotice(error.message, true); }
    finally { element("reference-template").disabled = false; }
});
element("compare").addEventListener("click", async () => {
    element("compare").disabled = true;
    element("comparison-downloads").replaceChildren();
    try {
        const file = element("compare-request").files[0];
        if (!file) throw new Error("请选择已填写的 compare.json。");
        const request = JSON.parse((await file.text()).replace(/^\uFEFF/, ""));
        comparisonNotice("正在匹配外部单点条件并统计误差…");
        const result = await post("/gibbs/compare", request);
        const pass = result.status === "within_tolerance";
        comparisonNotice(`${result.software} ${result.software_version} · ${result.reference_model.phase}：${result.compared_points}/${result.local_points} 个点已对比，${result.passed_points} 个在容差内。最大 |ΔG| = ${result.max_abs_error_J_mol_atoms.toPrecision(6)} J/mol-atoms，RMSE = ${result.rmse_J_mol_atoms.toPrecision(6)} J/mol-atoms。${result.uncompared_points} 个点未对比。模型条件依据导入请求中的声明。`, !pass);
        comparisonDownloads("comparison-downloads", result.urls);
    } catch (error) { comparisonNotice(error.message, true); }
    finally { element("compare").disabled = false; }
});
