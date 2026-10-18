"""Additional public experimental evidence in the existing binary audit report."""
import html
import json
import re

from examples.seven_binary_validation import FOLDER
from src.storage import atomic_json


def load():
    path=FOLDER/'public_literature_comparisons.json'
    return {r['pair']:r for r in json.loads(path.read_text())} if path.exists() else {}


def extra_coverage():
    return {p for p,f in [('CU-FE','CuFe_solubility_comparison.json'),('CU-TI','CuTi_invariant_comparison.json')]
            if (FOLDER/f).exists()}


def extra_section(cases):
    import matplotlib.pyplot as plt
    parts=[]
    if 'CU-FE' in extra_coverage():
        r=json.loads((FOLDER/'CuFe_solubility_comparison.json').read_text())
        fig,ax=plt.subplots(figsize=(8,4.8),layout='constrained')
        ax.plot([p['T_K'] for p in r['rows']],[p['reference_at_pct'] for p in r['rows']],'-o',color='#b7472f',label='1978 experimental regression')
        ax.plot([p['T_K'] for p in r['rows']],[p['calculated_at_pct'] for p in r['rows']],'-s',color='#1d6174',label='V6 equilibrium')
        ax.set(xlabel='Temperature (K)',ylabel='Fe solubility in Cu-rich FCC (at.%)',title='Cu-Fe | published regression vs V6')
        ax.grid(alpha=.15);ax.legend();fig.savefig(FOLDER/'plots/CU-FE_solubility.png',dpi=150);plt.close(fig)
        rows=''.join(f'<tr><td>{p["T_K"]:g}</td><td>{p["reference_wt_pct"]:.4f}</td><td>{p["reference_at_pct"]:.4f}</td><td>{p["calculated_at_pct"]:.4f}</td><td>{p["delta_at_pct"]:+.4f}</td><td><a href="{p["raw"]}">输出</a></td></tr>' for p in r['rows'])
        parts.append(f'<h3 id="public-CU-FE">Cu–Fe：Cu 端固溶度</h3><p>依据 <a href="{r["source"]["url"]}">Salje / Feller-Kniepmeier（1978）的 EPMA 实验回归式</a>：log₁₀ C(Fe, wt.%) = 2.951 − 3357/T(K)，仅在原文的 650–1050°C 范围内取五个诊断温度，并按 Fe=55.845、Cu=63.546 g/mol 转为原子分数。本库全相平衡中 Cu 富集 FCC 的固溶度与该回归式比较，RMSE 为 {r["rmse_at_pct"]:.3f} at.%，最大差 {r["max_abs_at_pct"]:.3f} at.%。五点来自同一实验回归，不能当作五次独立实测；原始散点和不确定度未取得。</p><img loading="lazy" src="plots/CU-FE_solubility.png" alt="Cu-rich FCC Fe solubility"><details><summary>单位转换与逐温度结果</summary><table><tr><th>T/K</th><th>文献回归 wt.%</th><th>文献回归 at.%</th><th>本库 at.%</th><th>差 at.%</th><th>证据</th></tr>{rows}</table><p><a href="CuFe_solubility_comparison.json">机器可读结果</a></p></details>')
    if 'CU-TI' in extra_coverage():
        r=json.loads((FOLDER/'CuTi_invariant_comparison.json').read_text())
        rows=''.join(f'<tr><td>{html.escape(p["experimental_reaction"])}</td><td>{p["T_K"]:.2f}</td><td>{p["native_T_K"]:.2f}</td><td>{p["delta_T_K"]:+.2f}</td><td>{"同类反应" if p["reaction_type_matches"] else "共晶 / 包晶不同，温差不能作为同一反应误差"}</td></tr>' for p in r['rows'])
        parts.append(f'<h3 id="public-CU-TI">Cu–Ti：历史实验的温度与反应类型</h3><p><a href="{r["source"]["url"]}">Eremenko 等（1966）的原始实验摘要</a>可提供四个具有明确相集合的节点。Ti 富集侧原文称共晶，本库却为包晶：液相含 64.8239 at.% Ti，Ti₂Cu 为 66.6661 at.% Ti，BCC 为 84.0654 at.% Ti，液相成分不在两固相之间。其余三个同类节点偏差如下。原文还综合了历史文献，较新的评估可能修订这些认识；本节只表明与这份历史实验摘要的差异，不能据此断言现库必错。</p><table><tr><th>原文反应</th><th>实验 K</th><th>计算节点 K</th><th>节点温差 K</th><th>是否同类</th></tr>{rows}</table><p>73 at.% Cu 的共晶换算为 27 at.% Ti，本库液相端为 25.4746 at.% Ti，差 −1.5254 at.%。另一条共晶成分在公开摘要中印为“43 at.% Ce”，不猜改、不纳入成分误差。Ti₂Cu ↔ C11_B、TiCu ↔ CUTI_B11、TiCu₂ ↔ CU2TI_H、TiCu₄ ↔ CU4TI、Ti₂Cu₃ ↔ CU3TI2；映射核对了源库端元化学计量。相身份由汇聚到该节点的带相名二相曲线确定，不由未标注相名的三相三角坐标猜测。</p><p><a href="CuTi_invariant_comparison.json">节点、各相成分与排除说明</a> · <a href="tc_final_first/CU-TI/calculated.exp">原始相界文件</a></p>')
    if not parts:return ''
    return '<section id="public-additional"><h2>补充公开实验基准</h2>'+''.join(parts)+'</section>'


def overlay(ax,result,x_range=None):
    """Measured phase endpoints, or explicitly labelled overall sample conditions."""
    symbols={'BCC':'s','FCC':'o','MU':'^','TAO':'D'}
    used=set()
    for row in result['rows']:
        if row['observed_at_pct'] is None:
            label='Sample: '+ '+'.join(row['phases'])
            ax.scatter([100*row['X_second']],[row['T_K']],marker='x' if len(row['phases'])==1 else '+',color='#b7472f',s=60,
                       label=label if label not in used else None,zorder=4)
            used.add(label)
            continue
        for j,(phase,x) in enumerate(zip(row['phases'],row['observed_at_pct'])):
            if x_range and not x_range[0]<=x<=x_range[1]:continue
            excluded=j in row['exclude_indices']
            ordered=row.get('expected_ordering',[None]*len(row['phases']))[j]=='ORD'
            label='Experiment: '+('B2 ordered' if ordered else phase)+(' (source flags unreliable)' if excluded else '')
            ax.scatter([x],[row['T_K']],s=38,marker='D' if ordered else symbols[phase],facecolors='none',
                       edgecolors='#a1a7a9' if excluded else '#b7472f',
                       label=label if label not in used else None,zorder=4)
            used.add(label)


def source_audit():
    lines=(FOLDER/'source_v6.tdb').read_text(errors='replace').splitlines()
    model=(FOLDER/'tc_final_first/CO-FE/model.tdb').read_text()
    result={
        'commented_order_block':[{'line':i+1,'text':s} for i,s in enumerate(lines) if 1062<=i+1<=1136],
        'active_binary_ORDER_B2_parameters':[s for s in model.splitlines() if re.match(r'\s*PARAMETER\s+\w+\(ORDER_B2,',s)],
        'interpretation':'Co-Fe ordering block is deliberately disabled: source comment cites poor Co-Fe-X ternary assessment. Several alternative parameterizations occur in comments. This audit does not select or reactivate them.',
        'occupancy_evidence':'public_literature_points/CO-FE/point_06.txt',
        'scope':'Absence of active binary Co-Fe ordering terms explains the missing B2 order; not proof that all phase-boundary errors have the same cause.',
    }
    atomic_json(FOLDER/'CoFe_ordering_source_audit.json',result)


def section(cases,results):
    if not results:return ''
    import matplotlib.pyplot as plt
    by_pair={c['pair']:c for c in cases}
    limits={'CO-FE':((0,40),(640,1120)), 'CO-W':((0,55),(1120,1680)), 'FE-NI':((0,40),(650,1050))}
    cards=[]
    prose={
        'CO-FE':'7 个温度的 BCC/FCC 两相家族均出现，但不能据此判定有序状态正确。450°C、400°C 的实验表明确标注 B2，计算却均为 DISORD。源库第 1063 行说明因 Co–Fe–X 三元评估变差而禁用这些参数；1064–1136 行保存着多套被注释的 Co–Fe 有序参数。400°C 时两个金属亚点阵的 Fe 占位均为 0.241098。缺失有序项是具体配置问题，恢复时还须重新检查三元体系，不能直接取消整段注释。',
        'CO-W':'12 个条件中 10 个相家族组合相同。1373 K、16 at.% W：实验为 FCC＋μ，计算为 FCC＋D0₁₉-Co₃W（TAO）；1183 K 的扩散偶观测到两个 FCC 分支（2.6 与 4.2 at.% W），以其中点 3.4 at.% W 计算却为 FCC＋TAO。原文给出的磁性三相反应在 1173–1183 K 之间，本库节点约 1186.60 K；邻近相界的小温差也会改变相组合。因此不能将两处不一致直接归因于求解器或磁性模型失效。',
        'FE-NI':'仅核对经过剧烈变形并再结晶、充分退火的试样。500°C、7.6 at.% Ni、143 天：作者报告 BCC 单相，本库给出 BCC＋FCC；11.5 at.% Ni、两个月：双方均为 BCC＋FCC。本库计算的两相端点为 4.5857 与 29.1799 at.% Ni，提示这一温度下 BCC 的 Ni 固溶度低于新实验所支持的范围。这里没有从示意图猜测相界数值，也没有把未达平衡的未变形试样用于验收。',
    }
    for pair,result in results.items():
        case=by_pair[pair]
        fig,ax=plt.subplots(figsize=(9,5.4),layout='constrained')
        first=True
        for block in case.get('blocks',[]):
            for curve in block['curves']:
                xy=curve['xy']
                if len(xy)<2:continue
                ax.plot([100*x for x,t in xy],[t for x,t in xy],color='#1d6174',lw=1.1,
                        label='V6 calculated boundaries' if first else None)
                first=False
        overlay(ax,result,x_range=limits[pair][0])
        ax.set(xlim=limits[pair][0],ylim=limits[pair][1],xlabel=pair.split('-')[1]+' (at.%)',
               ylabel='Temperature (K)',title=pair+' | published observations vs V6')
        ax.grid(alpha=.15);ax.spines[['top','right']].set_visible(False)
        ax.legend(loc='upper left',bbox_to_anchor=(1.01,1),fontsize=8)
        fig.savefig(FOLDER/'plots'/f'{pair}_public_zoom.png',dpi=150)
        fig.savefig(FOLDER/'plots'/f'{pair}_public_zoom.svg')
        plt.close(fig)
        source=result['rows'][0]['source'];rows=[]
        for row in result['rows']:
            observed=' + '.join(row['phases'])
            if row['observed_at_pct'] is not None:
                observed+=' / '+', '.join(f'{x:g}'+('*' if j in row['exclude_indices'] else '') for j,x in enumerate(row['observed_at_pct']))
            calc=' + '.join(p['family']+(' [有序]' if p['ordering']=='ORD' else '')+f' {100*p["X_second"]:.4f}' for p in row['calculated_phases'])
            badorder=any(p['ordering_mismatch'] for p in row['phase_composition_comparisons'])
            state='相家族不同' if not row['phase_families_match'] else '有序状态不同' if badorder else '相家族相同，成分见数值' if row['observed_at_pct'] is not None else '相家族相同'
            raw=row['raw_equilibrium'].replace('\\','/')
            rows.append(f'<tr><td>{row["T_K"]:g}</td><td>{100*row["X_second"]:g}</td><td>{html.escape(observed)}</td><td>{html.escape(calc)}</td><td class="{"bad" if badorder or not row["phase_families_match"] else ""}">{state}</td><td><a href="{raw}">原始输出</a></td></tr>')
        metrics=(f'仅对相家族相同且原文未标为不可靠的 {result["matched_reliable_compositions"]} 个相成分，RMSE = {result["rmse_at_pct"]:.2f} at.%，最大绝对差 = {result["max_abs_at_pct"]:.2f} at.%。有序状态不一致仍计入家族层面的成分误差，并单独标记，不以删点掩盖。' if result['rmse_at_pct'] is not None else '两项为相组合检验，不报告相界 RMSE。')
        extra='<p><a href="CoFe_ordering_source_audit.json">有序参数注释与有效参数审计</a></p>' if pair=='CO-FE' else '<p><a href="literature/CoW_Sato_2005.pdf">开放原始论文</a> · <a href="literature/CoW_Sato_2005_table1.png">已目视核对的实验表</a></p>' if pair=='CO-W' else ''
        cards.append(f'<h3 id="public-{pair}">{pair}：{result["conditions"]} 个实验条件</h3><p>{prose[pair]}</p><p>{metrics}</p><p><a href="{source["url"]}">{html.escape(source["reference"])}</a></p>{extra}<img loading="lazy" src="plots/{pair}_public_zoom.png" alt="{pair} measured points and calculated boundaries"><details><summary>逐条件结果、相成分（at.%）及原始输出</summary><table><tr><th>T / K</th><th>总成分 at.%</th><th>实验相 / 相成分</th><th>计算相 / 相成分</th><th>核对结果</th><th>证据</th></tr>{"".join(rows)}</table><p>总成分：Co–Fe 和 Co–W 的 FCC/FCC 扩散偶采用实测连线中点作为诊断条件，其他为报道的试样名义成分。* 为原作者注明不可靠的成分，保留展示但不纳入误差。TAO 是源库 D0₁₉-Co₃W 的相名。化学有序与铁磁/顺磁是不同概念。</p></details>')
    source_audit()
    return '<section id="public-literature"><h2>公开文献追加检验</h2><p>新增独立单点求解均使用与全相图相同的二元计算副本、常压、全部有效相参与。逐点通过日志、相分数归一和质量守恒检查。局部符合不能代替整图验收；若实验已参与原库拟合，本检验属于再现性核查，不能称为独立留出验证。</p>'+''.join(cards)+'<p><a href="public_literature_comparisons.json">全部新增条件、来源、误差与守恒检查</a></p></section>'
