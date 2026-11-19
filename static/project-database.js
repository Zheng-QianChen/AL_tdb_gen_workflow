"use strict";

(async function projectDatabasePicker() {
    const project = new URLSearchParams(location.search).get("project");
    if (!project || ToolShell.model) return;
    const files = document.getElementById("databases");
    const config = document.getElementById("config");
    const select = document.createElement("select");
    select.id = "project-database";
    select.className = "form-select";
    const label = document.createElement("label");
    label.htmlFor = select.id;
    label.textContent = "项目数据库";
    try {
        const response = await fetch("/api/projects/" + encodeURIComponent(project));
        if (!response.ok) throw Error();
        const data = await response.json();
        if (data.id !== project || !data.inputs.length) return;
        select.add(new Option("手动指定 TDB 路径", ""));
        for (const entry of data.inputs) {
            const path = "workbench/inputs/" + data.id + "/" + entry.digest + ".tdb";
            select.add(new Option(entry.name, path));
        }
        const pathLabel = document.querySelector('label[for="databases"]');
        pathLabel.before(label, select);
        const sync = () => {
            const match = Array.from(select.options).find(item => item.value === files.value.trim());
            select.value = match?.value || "";
        };
        files.addEventListener("input", sync);
        select.onchange = () => {
            files.value = select.value;
            files.dispatchEvent(new Event("input"));
            if (!select.value) files.focus();
        };
        if (data.inputs.length === 1 && !files.value.trim() && !config.value.trim()) {
            files.value = select.options[1].value;
            files.dispatchEvent(new Event("input"));
        }
        sync();
    } catch {
        const message = document.createElement("p");
        message.textContent = "项目数据库列表读取失败，可刷新重试或手动填写 TDB 路径。";
        files.after(message);
    }
})();
