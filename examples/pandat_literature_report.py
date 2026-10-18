"""Summarize saved literature comparisons without hiding failed points."""
import argparse
from datetime import datetime
import html
import json
from pathlib import Path
import uuid

from matplotlib.backends.backend_agg import FigureCanvasAgg
from matplotlib.figure import Figure

from config import BASE_DATA_DIR
from src.gibbs_compare import write_csv
from src.storage import atomic_json, atomic_write


def build_report(path):
    summary = json.loads(Path(path).read_text(encoding="utf-8"))
    run_date = datetime.fromtimestamp(Path(path).stat().st_mtime).astimezone().strftime("%Y-%m-%d")
    if summary["status"] == "running" or len(summary["cases"]) != summary["expected_cases"]:
        raise ValueError("Wait for the comparison to finish")
    folder = BASE_DATA_DIR/("pandat_literature_report_"+uuid.uuid4().hex[:12])
    folder.mkdir()
    points, materials = [], []
    for case in summary["cases"]:
        audits = Path(case["folder"])/"audits.json"
        if audits.is_file():
            for index, row in enumerate(json.loads(audits.read_text(encoding="utf-8"))):
                points.append({"material": case["material"], "case": case["name"], "point_index": index, **row})
    for source in summary["sources"]:
        rows = [row for row in points if row["material"] == source["material"]]
        cases = [case for case in summary["cases"] if case["material"] == source["material"]]
        materials.append({"material": source["material"], "phase": source["phase"], "sublattices": source["actual_sublattices"],
                          "points": len(rows), "energy_passed": sum(abs(row["equilibrium_delta_J_mol_atoms"]) <= 1 for row in rows),
                          "formula_passed": sum(abs(row["formula_delta_J_mol_atoms"]) <= 1 for row in rows),
                          "max_G_error": max((abs(row["equilibrium_delta_J_mol_atoms"]) for row in rows), default=None),
                          "max_formula_error": max((abs(row["formula_delta_J_mol_atoms"]) for row in rows), default=None),
                          "status": "passed" if all(case["status"] == "passed" for case in cases) else "failed"})
    failures = [row for row in points if abs(row["equilibrium_delta_J_mol_atoms"]) > 1]
    write_csv(folder/"materials.csv", materials)
    # A single schema includes both binary and ternary compositions.
    fields = sorted(set().union(*(row.keys() for row in points))) if points else []
    for name, rows in (("points", points), ("failures", failures)):
        write_csv(folder/f"{name}.csv", [{key: row.get(key) for key in fields} for row in rows])
    figure = Figure(figsize=(13, 8), layout="constrained")
    FigureCanvasAgg(figure)
    axes = figure.subplots(2, 2).flat
    for ax, material in zip(axes, materials):
        rows = [row for row in points if row["case"] == material["material"]+"_gx" and row["T_K"] == 300]
        axis = "X_FE" if material["material"] == "FeNi" else "X_AL"
        rows.sort(key=lambda row: row[axis])
        ax.plot([row[axis] for row in rows], [row["G_local"]/1000 for row in rows], "o-", label="Local: original TDB", color="#1d4ed8")
        ax.plot([row[axis] for row in rows], [row["G_pandat"]/1000 for row in rows], "s--", label="Pandat 2022a", color="#c2410c")
        ax.set_title(f"{material['material']} / {material['phase']} / {material['sublattices']} sublattices")
        ax.set_xlabel(axis+" (atomic fraction)"+("; X_NB = 0.02" if material["material"] == "AlFeNb" else ""))
        ax.set_ylabel("G [kJ/mol-atoms]")
        ax.grid(alpha=.2)
        ax.legend(fontsize=9)
    figure.suptitle("Literature material databases: homogeneous single-phase G at 300 K\nLines connect sampled points; differing order branches are retained", fontsize=14)
    for extension in ("png", "svg"):
        figure.savefig(folder/f"curves.{extension}", dpi=160)
    fig = Figure(figsize=(12, 4.6), layout="constrained")
    FigureCanvasAgg(fig)
    left, right = fig.subplots(1, 2)
    for index, material in enumerate(materials):
        rows = [row for row in points if row["material"] == material["material"]]
        label = material["material"]
        left.scatter([index]*len(rows), [abs(row["equilibrium_delta_J_mol_atoms"]) for row in rows], s=22, alpha=.7)
        right.scatter([row["T_K"] for row in rows], [row["formula_delta_J_mol_atoms"] for row in rows], s=24, alpha=.7, label=label)
    left.set_yscale("symlog", linthresh=.01)
    left.axhline(1, color="#b91c1c", linestyle="--", label="1 J/mol-atoms tolerance")
    left.set_xticks(range(len(materials)), [row["material"] for row in materials])
    left.set_ylabel("Absolute optimized G difference [J/mol-atoms]")
    left.set_title(f"Independent optimization: {summary['energy_points_passed']}/{summary['points']} within tolerance")
    left.legend(fontsize=9)
    right.axhline(0, color="#64748b", linewidth=.8)
    right.set_xlabel("Temperature [K]")
    right.set_ylabel("G(local at Pandat Y) - G(Pandat) [J/mol-atoms]")
    right.set_title(f"Same-occupancy formula: {summary['formula_points_passed']}/{summary['points']} within tolerance")
    right.legend(fontsize=9)
    for ax in (left, right):
        ax.grid(alpha=.2)
    for extension in ("png", "svg"):
        fig.savefig(folder/f"errors.{extension}", dpi=160)
    diagnosis_path = Path(summary["folder"])/"optimization_diagnosis.json"
    diagnosis = json.loads(diagnosis_path.read_text(encoding="utf-8")) if diagnosis_path.is_file() else None
    result = {"validation": str(Path(path).resolve()), "materials": materials,
              "points": len(points), "failures": len(failures), "max_formula_error": max((row["max_formula_error"] for row in materials if row["max_formula_error"] is not None), default=None),
              "diagnosis": diagnosis, "files": {key: str(folder/name) for key, name in
                (("html", "report.html"), ("json", "report.json"), ("points", "points.csv"), ("failures", "failures.csv"), ("curves", "curves.png"), ("errors", "errors.png"))}}
    atomic_json(folder/"report.json", result)
    def table(headers, rows):
        return "<table><thead><tr>"+"".join(f"<th>{html.escape(str(key))}</th>" for key in headers)+"</tr></thead><tbody>"+"".join(
            "<tr>"+"".join(f"<td>{html.escape(str(value))}</td>" for value in row)+"</tr>" for row in rows)+"</tbody></table>"
    material_table = table(["材料", "相", "亚点阵数", "优化 G 通过", "同占位公式通过", "最大 G 差 / J mol⁻¹", "最大公式差"],
                           [[row["material"], row["phase"], row["sublattices"], f"{row['energy_passed']}/{row['points']}", f"{row['formula_passed']}/{row['points']}",
                             f"{row['max_G_error']:.6f}" if row["max_G_error"] is not None else "无结果", f"{row['max_formula_error']:.6f}" if row["max_formula_error"] is not None else "无结果"] for row in materials])
    failed_table = table(["算例", "T / K", "原子分数", "本程序 − Pandat / J mol⁻¹", "Pandat 返回相"],
                         [[row["case"], row["T_K"], ", ".join(f"{key[2:]}={value:.4g}" for key, value in row.items() if key.startswith("X_")),
                           f"{row['equilibrium_delta_J_mol_atoms']:.6f}", row["pandat_reported_phase"]] for row in failures])
    source_list = "".join(f'<li><a href="{html.escape(source["url"], quote=True)}">{html.escape(source["material"])} — {html.escape(source["file"])}</a><br>{html.escape(source["note"])}</li>' for source in summary["sources"])
    diagnosis_text = "尚无独立搜索诊断。"
    if diagnosis:
        matched = sum(abs(row["difference_from_local_J_mol_atoms"]) <= .001 for row in diagnosis["points"])
        diagnosis_text = f"独立差分进化及后续局部优化复核了 {len(diagnosis['points'])} 个差异点，其中 {matched} 个与本程序相差不超过 0.001 J/mol-atoms。搜索收敛不等于全局最优证明，诊断不改变原始失败判定。"
    page = f'''<!doctype html><html lang="zh-CN"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>真实四、五亚点阵材料库验证</title><style>body{{font:16px/1.7 system-ui,"Microsoft YaHei",sans-serif;max-width:1200px;margin:32px auto;padding:0 24px;color:#172554;background:#f8fafc}}h1,h2{{line-height:1.3}}section{{background:white;padding:24px;border-radius:12px;margin:20px 0;overflow:auto}}table{{border-collapse:collapse;width:100%;font-size:14px}}th,td{{border-bottom:1px solid #e2e8f0;padding:10px;text-align:left}}th{{background:#eff6ff}}img{{width:100%;height:auto}}.status{{color:#9a3412;background:#ffedd5;padding:16px;border-radius:8px}}a{{color:#1d4ed8}}li{{margin:16px 0}}code{{overflow-wrap:anywhere}}</style>
<h1>真实四、五亚点阵材料库验证</h1><p>{run_date} · {html.escape(summary['software_version'])} · 300–1400 K · 101325 Pa</p>
<p class="status">已完成 {summary['expected_cases']} 组、{summary['points']} 个独立单点。优化 G：{summary['energy_points_passed']}/{summary['points']} 通过；同占位公式：{summary['formula_points_passed']}/{summary['points']} 通过。保留 {len(failures)} 个优化差异点。</p>
<section><h2>模型与结果</h2>{material_table}<p>Al–Ni 是四个置换亚点阵，磁性仅来自无序参考相。另三个材料相是四个置换亚点阵加固定 VA，且含有序侧 TC/BMAGN 修正。文件名中的“4SL”不代表总共只有四个亚点阵。</p><p>本程序读取下载的原文件；Pandat 读取经过等价性检查的导入副本。没有重新拟合或调节数据库参数。比较的是单一均匀相，允许内部占位优化，不允许两相分解。</p></section>
<section><h2>曲线与误差</h2><img src="curves.png" alt="300 K G–成分对比曲线"><img src="errors.png" alt="优化能量和同占位公式误差"><p>能量容差 1 J/mol-atoms，rtol=0；占位/成分容差 3e-6；有序振幅 q 容差 1e-3。图中连线只连接采样点。</p></section>
<section><h2>保留的差异</h2><p>{diagnosis_text}</p>{failed_table}</section>
<section><h2>来源与适用范围</h2><ul>{source_list}</ul><p>本次验证软件间的数值一致性，不验证数据库相对于实验的准确性。未覆盖全空位可达模型、Xiong 磁性耦合、多相平衡；尚无原生四亚点阵且含独立有序磁性修正的文献库验证结果。</p><p><a href="points.csv">{summary['points']} 点原始对照汇总</a> · <a href="failures.csv">差异点</a> · <a href="report.json">完整诊断</a></p><p>运行证据：<code>{html.escape(summary['folder'])}</code></p></section></html>'''
    atomic_write(folder/"report.html", page)
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("summary")
    print(json.dumps(build_report(parser.parse_args().summary)["files"], ensure_ascii=False, indent=2))
