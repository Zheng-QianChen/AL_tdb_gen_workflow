"""Append external-engine evidence to the existing literature validation report."""
import argparse
import csv
import html
import json
from pathlib import Path
import shutil

BEGIN = "<!-- CROSS_ENGINE_BEGIN -->"
END = "<!-- CROSS_ENGINE_END -->"


def table(headers, rows):
    def cells(values, tag):
        return "".join(f"<{tag}>{html.escape(str(value))}</{tag}>" for value in values)
    return "<table><thead><tr>"+cells(headers, "th")+"</tr></thead><tbody>"+"".join(
        "<tr>"+cells(row, "td")+"</tr>" for row in rows)+"</tbody></table>"


def update(folder, report, docs):
    py = json.loads((folder/"pycalphad.json").read_text(encoding="utf-8"))
    oc = json.loads((folder/"opencalphad.json").read_text(encoding="utf-8"))
    mc = json.loads((folder/"matcalc.json").read_text(encoding="utf-8"))
    tc = json.loads((folder/"thermocalc.json").read_text(encoding="utf-8")) if (folder/"thermocalc.json").is_file() else None
    rows = []
    for p in py["cases"]:
        o = next(c for c in oc["cases"] if c["case"] == p["case"])
        assert o["best"] and all(p["modes"][m]["best"] for m in p["modes"])
        native = p["modes"]["native_model_native_solver"]
        shared = p["modes"]["project_model_native_solver"]
        rows.append({"case": p["case"], "phase": p["phase"], "T_K": p["T_K"],
            "composition": ", ".join(f"{c}={x:g}" for c, x in p["composition"].items()),
            "G_local": p["G_local"], "G_Pandat": p["G_Pandat"], "G_OpenCalphad": o["best"]["G"],
            "OpenCalphad_minus_local": o["best"]["G"]-p["G_local"],
            "G_pycalphad_native": native["best"]["G"],
            "native_model_minus_local": native["best"]["G"]-p["G_local"],
            "G_project_model_native_solver": shared["best"]["G"],
            "same_model_native_solver_minus_local": shared["best"]["G"]-p["G_local"],
            "pycalphad_native_model_warnings": " | ".join(native["warnings"]),
            "OC_accepted_starts": o["accepted"], "OC_attempts": o["attempts"],
            "native_model_accepted_starts": native["accepted"],
            "project_model_accepted_starts": shared["accepted"]})
        if tc:
            t = next((c for c in tc['cases'] if c['case'] == p['case']), None)
            best = t['best'] if t else None
            rows[-1].update(G_ThermoCalc=best['G'] if best else None,
                           ThermoCalc_minus_local=best['G']-p['G_local'] if best else None,
                           TC_accepted_starts=t['accepted'] if t else 0,
                           TC_attempts=t['attempts'] if t else 0)
    maximum = max(abs(r["OpenCalphad_minus_local"]) for r in rows)
    summary = {"date": "2026-10-18", "energy_unit": "J/mol-atoms", "rows": rows,
               "max_abs_OpenCalphad_minus_local": maximum,
               "OpenCalphad_version": "6.056 (2022-07-16 executable)",
               "pycalphad_version": py["version"], "MatCalc_version": mc["version"],
               "global_minimum_certified": False,
               "baseline_120_point_statistics_changed": False,
               "MatCalc_assessments": [{"case": c["case"], "assessment": c["assessment"]} for c in mc["cases"]],
               "raw_data": str(folder.resolve())}
    tc_section = ''
    tc_install = '尚未运行。'
    if tc:
        errors = [abs(r['ThermoCalc_minus_local']) for r in rows if r['ThermoCalc_minus_local'] is not None]
        summary.update(ThermoCalc_version=tc['version'],
                       max_abs_ThermoCalc_minus_local=max(errors) if errors else None,
                       ThermoCalc_cases=[{k: v for k, v in c.items() if k != 'runs'} for c in tc['cases']])
        tc_install = (f"{html.escape(tc['version'])} 已安装于 <code>{html.escape(tc['directory'])}</code>。"
                      "官方教育版启动器使用 <code>demo</code> 参数；本地许可证及自定义 TDB 批处理已实测可用。"
                      "教育版最多三组分，不等于最多三亚点阵。")
        tc_values = table(['算例', 'Thermo-Calc 最低 G', 'TC − 本程序', '接受初值 / 尝试', 'GES'], [
            [r['case'], f"{r['G_ThermoCalc']:.6f}" if r['G_ThermoCalc'] is not None else '无可比结果',
             f"{r['ThermoCalc_minus_local']:+.6f}" if r['ThermoCalc_minus_local'] is not None else '—',
             f"{r['TC_accepted_starts']}/{r['TC_attempts']}",
             next((c.get('import_audit', {}).get('GES', '待审计') for c in tc['cases'] if c['case'] == r['case']), '—')]
            for r in rows])
        tc_section = f'''<h3>Thermo-Calc Education 2026b：相同原始文献库复核</h3>
<p>读取与其他引擎逐字节相同的原始 TDB（SHA256 已核对）。每个点采用相同的 37 个独立初值，
每次 <code>REINITIATE_MODULE</code> 重置 POLY，显式重设全部可变亚点阵的占位和单相量，
使用 <code>COMPUTE_EQUILIBRIUM -</code> 禁用本次全局最小化。纯 VA 亚点阵由引擎固定为 1，不额外输入。</p>
{tc_values}
<p>逐次检查收敛信息、原始输入占位回显、相量、总体成分、全部亚点阵归一化和有效输出文件。
仅接受一个目标相的组成集；记录 GES 的 A1、L12、D03、FP 等有序类型后缀，不把它们计为额外相。
G 来自 SHOW_VALUE 的约 8 位有效数字；保留打印精度，不补造更多精度。</p>
<p>Fe–Ni 的对称初值可停在约 −21713.244 J/mol 原子的分支，非对称初值找到更低分支；
说明同一引擎、同一模型也会因初始占位不同得到不同驻点。这里的多初值最低值仍不是全局最低的数学证明。</p>
<p>Al–Fe 原库的 ASSESSED_SYSTEM 引用了不存在的 A2_B2 名称，Thermo-Calc 自动回退到 GES5，
原始参数未改；该点不能宣称已通过 GES6 验证。Al–Fe–Nb 出现 NO REFERENCE FILE 的文献索引提示，
Al–Ni 有 REF0 引用缺失提示，完整导入记录保留；未知参数/模型错误会使解析器拒绝比较。</p>
<p>部分宏已报告正常完成后，2026b 的消息服务仍使应用等待退出。脚本保留实际退出码，
只在正常完成标记及所有数值检查满足后接受结果，并单独记录结束残留进程的情况。
探索阶段的三个初值日志存于 thermocalc-pilot3，包含多余固定 VA 输入，已与最终 37 初值证据分开。</p>
<p><a href="thermocalc-validation.json">Thermo-Calc 全部初值与导入审计 JSON</a></p>'''
    for destination in (folder, report.parent, docs):
        destination.mkdir(parents=True, exist_ok=True)
        (destination/"cross-engine-summary.json").write_text(json.dumps(summary, indent=2, ensure_ascii=False), encoding="utf-8")
        with (destination/"cross-engine-summary.csv").open("w", encoding="utf-8-sig", newline="") as stream:
            writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
            writer.writeheader()
            writer.writerows(rows)
    if (folder/"installations.json").is_file():
        shutil.copyfile(folder/"installations.json", report.parent/"cross-engine-installations.json")
        shutil.copyfile(folder/"installations.json", docs/"cross-engine-installations.json")
    if tc:
        shutil.copyfile(folder/'thermocalc.json', report.parent/'thermocalc-validation.json')
        shutil.copyfile(folder/'thermocalc.json', docs/'thermocalc-validation.json')
    values = table(["算例 / K / 原子分数", "本程序原解", "Pandat 原解", "OpenCalphad 最低解", "OC − 本程序"],
        [[f"{r['case']} / {r['T_K']:g} / {r['composition']}", f"{r['G_local']:.6f}",
          f"{r['G_Pandat']:.6f}", f"{r['G_OpenCalphad']:.6f}", f"{r['OpenCalphad_minus_local']:+.6f}"] for r in rows])
    solvers = table(["算例", "pycalphad 默认模型的 G", "默认模型 − 本程序", "现有模型 + 原生求解器 − 本程序", "原生 / 现有模型接受起点"],
        [[r["case"], f"{r['G_pycalphad_native']:.6f}", f"{r['native_model_minus_local']:+.6f}",
          f"{r['same_model_native_solver_minus_local']:+.9f}",
          f"{r['native_model_accepted_starts']}/37 · {r['project_model_accepted_starts']}/37"] for r in rows])
    section = f'''{BEGIN}
<section id="cross-engine"><h2>新增：Thermo-Calc、OpenCalphad、pycalphad 与 MatCalc 交叉检查</h2>
<p><strong>OpenCalphad 独立复现了 5 个代表性差异点的较低能量分支，最大能量差 {maximum:.6f} J/mol 原子。</strong>
这些是原 19 个差异点中的 5 个，不是全 120 点重新验证，也不是全局最小值证明。原 Pandat 统计与失败判定保留。</p>
<h3>已安装与实际可用范围</h3><ul>
<li><a href="https://www.opencalphad.com/downloads.php">OpenCalphad</a> 6.056：安装于 <code>D:\\ThermoTools\\OpenCalphad</code>。
官方 Windows 稳定安装包内核日期 2022-07-16；Ag–Cu 官方算例通过。不是 GitHub 最新开发版。</li>
<li><a href="https://pycalphad.org/">pycalphad</a> {html.escape(py['version'])}：独立环境 <code>review/thermo-engines/pycalphad-venv</code>。
项目原环境及依赖锁定仍为 0.11.1，本轮没有将生产模型替换为上游默认模型。</li>
<li><a href="https://download.matcalc.at/">MatCalc</a> {html.escape(mc['version'])}：安装于 <code>D:\\ThermoTools\\MatCalc6</code>。
无需许可证的免费模式最多三种元素。公开 C API 跑通官方 Al–Mg–Si 算例：873.15 K、101325 Pa、98/1/1 wt%，G = −34754.071647 J/mol，FCC_A1 与 LIQUID 两相。</li>
<li><a href="https://thermocalc.com/academia/free-educational-package/">Thermo-Calc Education</a>：{tc_install}</li>
<li><a href="https://factsage.com/factsage-edu/">FactSage Education</a>：官网明确禁用 TDB 导入、宏和 ChemApp for Python，未安装，暂不适合本次相同文献库的比较。</li>
</ul><h3>真正独立的引擎：OpenCalphad</h3>
<p>所有 G 的单位均为 J/mol 原子，压力均为 101325 Pa。读取原始文献 TDB，每点 37 个独立起点：均匀占位、守恒多面体顶点与凸组合。
未使用本程序或 Pandat 的最终占位作为这些起点。仅开启目标相，使用 <code>calculate no-global</code>，每个起点启用新进程，禁止通过全局网格自动生成新的组成集。</p>
{values}
<p>185/185 次输出满足单个目标相、相量 1、目标组成及打印精度下位点归一化检查；它们并非都到达同一能量分支。
表中取每点最低值，不将求解器收敛等同于全局稳定性或独立 KKT 通过。OC 控制台能量仅约 8 位有效数字，占位约 6 位有效数字，保留原始打印精度。
原始库存在参考文献标记缺失、未选中相被跳过等读取提示，完整日志与参数计数已保存；未改物理参数。</p>
{tc_section}
<h3>pycalphad：公式检查与求解器检查分开</h3>
{solvers}
<p>原生求解器每次只给一个 <code>CompositionSet</code>，不调用可能产生同名相分裂的多相 equilibrium 入口。
本程序本身使用 pycalphad 的模型基础，因此“现有模型 + 原生求解器”仅是求解器对照，不能冒充完全独立引擎。
两种模型共 370 次求解，其中 367 次满足收敛及可行性；Al–Fe–Nb 的现有模型有 3 个起点不接受，原始记录保留。</p>
<p>0.11.2 默认模型在 Fe–Ni、Al–Fe、Al–Fe–Nb 上仍发出有序/无序物性分配警告。
固定相同占位时能量已不一致，说明不能把它们全部解释为极小化器差异。使用现有磁性模型的原生求解器与原结果最大差小于 0.000004 J/mol 原子。</p>
<h3>MatCalc：安装可用，但原始文献库导入尚不等价</h3>
<p>五个点均已尝试，并明确选择 VA。Al–Ni 两点、Fe–Ni 和 Al–Fe–Nb 的读取日志报告无法用 TYPE_DEFINITION 连接无序参考，忽略该定义并要求
<code>ATTACH_CONTRIBUTION</code>；Al–Fe 在 <code>ASSESSED_SYSTEM</code> 元数据处报未知关键字。
Al–Ni 的一次运行还达到迭代上限。即使 API 返回 0，也不能把这些数值当作正确模型的 G；本轮全部排除于文献能量比较。</p>
<p>因此，现有证据支持较低能量分支确实存在，尚不能仅据此把全部 Pandat 差异归因于软件缺陷。
下一步优先补全另外 14 个差异点，并检查边界 KKT 与稳定性；五点外推到所有模型仍需更多证据。</p>
<p><a href="cross-engine-summary.csv">五点数值 CSV</a> · <a href="cross-engine-summary.json">摘要 JSON</a> ·
<a href="cross-engine-installations.json">安装清单与下载来源</a></p>
<p>原始输入、起点、完整运行日志及失败记录：<code>{html.escape(str(folder.resolve()))}</code></p></section>
{END}'''
    contents = report.read_text(encoding="utf-8")
    if BEGIN in contents:
        before, rest = contents.split(BEGIN, 1)
        _, after = rest.split(END, 1)
        contents = before+section+after
    else:
        marker = "<!-- OCCUPANCY_DIAGNOSIS_BEGIN -->"
        if marker not in contents:
            raise ValueError("Expected existing literature report with occupancy diagnosis")
        contents = contents.replace(marker, section+"\n"+marker, 1)
    report.write_text(contents, encoding="utf-8")
    print(json.dumps({"report": str(report), "maximum_OC_error": maximum, "points": len(rows)}, ensure_ascii=False))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("folder", type=Path)
    parser.add_argument("report", type=Path)
    parser.add_argument("--docs", type=Path, default=Path(__file__).resolve().parents[1]/"docs/validation")
    args = parser.parse_args()
    update(args.folder, args.report, args.docs)
