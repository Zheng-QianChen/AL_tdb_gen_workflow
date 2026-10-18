"""Append saved occupancy diagnostics to an existing literature HTML report."""
import argparse
import csv
import html
import json
from pathlib import Path
import shutil

from src.storage import atomic_json, atomic_write


def update_report(run_folder, report):
    folder, report = Path(run_folder), Path(report)
    summary = json.loads((folder/"summary.json").read_text(encoding="utf-8"))
    symmetry = json.loads((folder/"symmetry.json").read_text(encoding="utf-8"))
    control = json.loads((folder/"alzn_control"/"summary.json").read_text(encoding="utf-8"))
    if summary["status"] == "running":
        raise ValueError("Wait for the experiments to finish")
    combined = {"experiments": summary, "symmetry": symmetry, "simple_database_controls": control}
    chemical_path = folder/"chemical_potential_check.json"
    chemical = json.loads(chemical_path.read_text(encoding="utf-8")) if chemical_path.is_file() else None
    if chemical:
        combined["chemical_potential_check"] = chemical
    atomic_json(report.parent/"occupancy-diagnosis.json", combined)
    by_name = {item["case"]: item for item in summary["cases"]}
    rows = []
    for point in symmetry["cases"]:
        case = by_name[point["case"]]
        lowest = min(point["hessians"][-1]["full_eigenvalues"]) if point["hessians"] else None
        released = [r for r in point["released_optimizations"] if r["success"] and r["feasible"]]
        rows.append({"case": point["case"], "T_K": point["T_K"],
                     "composition": ", ".join(f"{k}={v:g}" for k, v in case["composition"].items()),
                     "equality_pairs_one_based": "; ".join(f"{a}={b}" for a, b in point["equal_site_pairs"]),
                     "restricted_minus_Pandat_J_mol_atoms": point["restricted_minus_pandat"],
                     "lowest_full_curvature": lowest,
                     "Pandat_minus_local_J_mol_atoms": case["G_pandat_baseline"]-case["G_local"],
                     "restricted_minus_best_released_J_mol_atoms": point["G_restricted"]-min(r["G"] for r in released) if released else None,
                     "classification": "存在降能方向" if lowest is not None and lowest < 0 else "局部极小" if lowest is not None and lowest > 0 else "未判定"})
    with (report.parent/"occupancy-summary.csv").open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    def table(headers, body):
        return "<table><thead><tr>"+"".join(f"<th>{html.escape(str(h))}</th>" for h in headers)+"</tr></thead><tbody>"+"".join(
            "<tr>"+"".join(f"<td>{html.escape(str(v))}</td>" for v in row)+"</tr>" for row in body)+"</tbody></table>"
    diagnosis_table = table(["算例 / 温度", "原子分数", "等占位约束复现 G 的误差¹", "放开约束后的局部稳定性", "Pandat − 低能解¹"],
        [[f"{r['case']} / {r['T_K']:g} K", r["composition"], f"{r['restricted_minus_Pandat_J_mol_atoms']:.6f}",
          r["classification"], f"{r['Pandat_minus_local_J_mol_atoms']:.6f}"] for r in rows])
    variants = {}
    for case in summary["cases"]:
        for variant in case["variants"]:
            statuses = variants.setdefault(variant["variant"], {})
            statuses[variant["status"]] = statuses.get(variant["status"], 0)+1
    labels = {"homogeneous_result": "均匀单相输出", "execution_failed": "执行失败", "not_comparable_as_homogeneous": "非均匀单相比较对象"}
    variant_table = table(["计算模式及初值", "实际结果"], [[name, "；".join(f"{labels.get(s,s)} {n} 组" for s,n in statuses.items())] for name,statuses in variants.items()])
    total = sum(sum(statuses.values()) for statuses in variants.values())
    local_failed = sum("execution" not in item for item in control if item["mode"] == "local")
    chemical_section = ""
    if chemical:
        chemical_rows = []
        for point in chemical["points"]:
            spreads = []
            for name in ("pandat_export", "same_branch_refined", "local_multistart"):
                state = point["states"][name]
                spreads.append(f"{max(p['max_minus_min'] for p in state['exchange_potentials'].values()):.6g}"
                               if state["status"] == "interior" else "边界态：需单侧 KKT 检查")
            chemical_rows.append([point["case"], *spreads])
        chemical_section = '''<h3>亚点阵间交换化学势复核</h3>
<p>固定点阵容量、允许交换的内部占位满足 M<sub>A−B</sub><sup>(s)</sup> = (N<sub>atoms</sub>/a<sub>s</sub>)(∂G<sub>m</sub>/∂y<sub>A</sub><sup>(s)</sup> − ∂G<sub>m</sub>/∂y<sub>B</sub><sup>(s)</sup>)，各亚点阵的 M 应相等。这是固定总成分下自由能最小化的一阶条件，不要求各亚点阵占位相同。下表为跨点阵最大差；三元取两组独立交换势差中的较大值，单位 J/mol。</p>'''+table(
            ["算例", "Pandat 原始占位代入本程序", "同一分支在本程序内精化", "本程序原低能解"], chemical_rows)+'''
<p>Fe–Ni 同一分支精化后的交换势差约 6.6×10⁻⁸ J/mol，Al–Fe 约 1.3×10⁻⁶ J/mol，仍存在负曲率方向。因此这些差异不能解释为漏掉化学势平衡约束；满足一阶条件的驻点也可能是鞍点。精化值不是 Pandat 原始输出，原始值另列。</p>
<p>当前求解器通过归一化、组分守恒和占位边界约束下最小化 G，包含了该物理条件，但验收只检查求解器 success 和可行性，尚未单独将化学势/KKT 残差作为通过条件。本程序原 Al–Ni 低能解的交换势差约 0.221 J/mol，说明能量收敛不能代替导数残差验收。0/1 边界占位应检查允许交换方向的单侧条件，不能强制套用内部点的等式。此处不把边界点判为通过。</p>'''
    section = f'''<!-- OCCUPANCY_DIAGNOSIS_BEGIN -->
<section id="occupancy-diagnosis"><h2>新增诊断：对称占位、初值与计算模式</h2>
<p>在 {len(summary['cases'])} 个代表点完成 {total} 组受控实验，保持各点的数据库、温度、压力和总成分一致。原有 120 点统计与 19 个差异判定保留。</p>
<p><strong>证据支持两类问题：</strong>Al–Ni 的高能无序态是局部极小值；Fe–Ni、Al–Fe 及 Al–Fe–Nb 的所选返回态，在本程序完整占位空间中存在降能方向。</p>
{diagnosis_table}<p>¹ 单位 J/mol-atoms。等占位约束由实际导出的占位归纳，在本程序中显式施加；这不等于已证实 Pandat 内部硬编码了这些约束。</p>
<p>Fe–Ni：固定 y₁=y₄、y₂=y₃，重现约 −21713.239；解除相等条件后，约 10⁻³ 的守恒扰动并局部优化可到 −21808.051。Al–Fe：固定 y₁=y₂、y₃=y₄，得到约 −41911.340；放开后可到 −41920.894。固定 VA 始终保持 1。</p>
<p>Al–Ni 的两个无序态全空间局部曲率为正，小扰动返回同一高能解。其低能有序解需要跨越局部能垒，不能仅靠在对称点附近微扰获得。</p>
{chemical_section}
{variant_table}
<p>旧 individual_phase、显式 individual 和带低能占位初值的 individual 在本轮所选点返回相同能量；仅凭这一结果不能证明初值被忽略。global 模式输出相分解（包括同一模型的两个不同成分相），因此不作为均匀单相曲线通过的依据。</p>
<p>local 模式已同时提供占位和 Pandat 导出的化学势初值，仍出现 System.AccessViolationException。安装自带 AlMgZn.tdb 中的简单 Al–Zn 控制也有 {local_failed} 组 local 失败，global 控制成功；暂不能区分版本缺陷、当前运行入口兼容性或其他环境因素，不能归因于学习版限制。</p>
<p>每种模式使用独立进程，保存 PBFX、TDB 哈希、成功日志、DAT 和失败日志。以本程序低能解作初值的运行是定向诊断，不计为独立交叉验证。曲率检验采用三个差分步长；成功且可行的释放约束优化才纳入结论。</p>
<p><a href="occupancy-summary.csv">五点诊断摘要</a> · <a href="occupancy-diagnosis.json">模式、初值、约束与控制实验完整记录</a> · <a href="https://computherm.com/Pandat_Online_Help/LocalEquilibrium.html">官方局部平衡输入说明</a></p>
<p>原始证据：<code>{html.escape(str(folder.resolve()))}</code></p></section>
<!-- OCCUPANCY_DIAGNOSIS_END -->'''
    page = report.read_text(encoding="utf-8")
    begin, end = "<!-- OCCUPANCY_DIAGNOSIS_BEGIN -->", "<!-- OCCUPANCY_DIAGNOSIS_END -->"
    if begin in page:
        first, last = page.index(begin), page.index(end)+len(end)
        page = page[:first]+section+page[last:]
    else:
        marker = "<section><h2>模型与结果</h2>"
        if marker not in page:
            raise ValueError("Expected an existing literature report")
        page = page.replace(marker, section+"\n"+marker, 1)
    atomic_write(report, page)
    snapshots = Path("docs/validation")
    snapshots.mkdir(exist_ok=True)
    for name in ("occupancy-diagnosis.json", "occupancy-summary.csv"):
        shutil.copyfile(report.parent/name, snapshots/("pandat-"+name))
    return str(report.resolve())


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("run_folder")
    parser.add_argument("report")
    args = parser.parse_args()
    print(update_report(args.run_folder, args.report))
