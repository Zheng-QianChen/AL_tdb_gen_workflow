"""Read native curve files and build a traceable experimental-comparison report."""
import csv
import hashlib
import html
import itertools
import json
from pathlib import Path
import re
import statistics
import math
from collections import Counter
from examples.seven_binary_validation import FOLDER,ELEMENTS
from examples.seven_binary_evidence import REFERENCES,NOTES,BENCHMARKS,CUNI_ROWS
from examples.seven_binary_public_report import load as load_public, overlay as overlay_public, section as public_section
from examples.seven_binary_public_report import extra_coverage,extra_section
from examples.seven_binary_search_ledger import section as literature_section
from src.storage import atomic_json

NUM=r'[-+]?\d+(?:\.\d*)?(?:[EeDd][-+]?\d+)?'

def read_exp(path):
    blocks=[]; block=None; curve=[]; plotted=None
    def close_curve():
        nonlocal curve
        if curve and block is not None:
            block['curves'].append({'phase':plotted,'xy':curve})
        curve=[]
    for line in path.read_text(errors='replace').splitlines():
        line=line.strip()
        if line.startswith('$ BLOCK #'):
            close_curve()
            block={'label':line,'phases':[],'invariant':False,'curves':[]};blocks.append(block)
            plotted=None
        elif re.match(r'\$(?:F0|E) ',line) and block is not None:
            block['phases'].append(line.split(None,1)[1])
        elif line.startswith('$ INVARIANT') and block is not None:block['invariant']=True
        elif line.startswith('$ PLOTTED'):
            close_curve()
            m=re.search(r'X\(([^,]+),',line);plotted=m[1] if m else None
        elif line=='BLOCKEND':close_curve()
        elif block is not None:
            m=re.fullmatch(r'('+NUM+r')\s+('+NUM+r')(?:\s+(M))?',line)
            if m:
                if m[3]:close_curve()
                curve.append([float(m[1].replace('D','E')),float(m[2].replace('D','E'))])
    close_curve()
    for b in blocks:
        pts=[xy for c in b['curves'] for xy in c['xy']]
        if b['invariant'] and pts:
            b['T_K']=statistics.mean(p[1] for p in pts)
            b['compositions']=sorted(set(p[0] for p in pts))
    return blocks

def collect():
    cases=[]
    for pair in itertools.combinations(ELEMENTS,2):
        name='-'.join(pair)
        resultfile=FOLDER/'tc_final_first'/name/'result.json'
        if not resultfile.exists():continue
        r=json.loads(resultfile.read_text())
        r['folder']=str(resultfile.parent.relative_to(FOLDER))
        # A successful MAP does not certify extrapolation beyond declared TDB ranges.
        model_text='\n'.join(line for line in (resultfile.parent/'model.tdb').read_text().splitlines()
                             if not line.lstrip().startswith('$'))
        r['temperature_domain_warnings']=[]
        for statement in model_text.split('!'):
            statement=statement.strip()
            if not re.match(r'^(FUNCTION|PARAMETER)\s',statement):continue
            bounds=re.findall(r';\s*([0-9.Ee+-]+)\s+[YN]\b',statement)
            if bounds and float(bounds[-1])<r['temperature_range_K'][1]:
                r['temperature_domain_warnings'].append({'declaration':statement.split()[1],
                                                        'upper_T_K':float(bounds[-1])})
        exp=resultfile.parent/'calculated.exp'
        if exp.exists():
            blocks=read_exp(exp)
            r['blocks']=blocks
            r['invariants']=[{k:v for k,v in b.items() if k!='curves'} for b in blocks if b['invariant']]
            r['point_count']=sum(len(c['xy']) for b in blocks for c in b['curves'])
            points=[xy for b in blocks for c in b['curves'] for xy in c['xy']]
            content=exp.read_text(errors='replace')
            checks={'nonempty_curves':bool(points),'finite_coordinates':all(math.isfinite(x) and math.isfinite(t) for x,t in points),
                    'mole_fractions_in_range':all(-1e-8<=x<=1+1e-8 for x,t in points),
                    'temperature_range':all(r['temperature_range_K'][0]-.01<=t<=r['temperature_range_K'][1]+.01 for x,t in points),
                    'complete_block_delimiters':content.count('BLOCK X=')==content.count('BLOCKEND'),
                    'model_hash':hashlib.sha256((resultfile.parent/'model.tdb').read_bytes()).hexdigest()==r['tdb_sha256']}
            r['curve_audit']=checks
            r['accepted_for_screening']=r['status']=='exported_requires_audit' and all(checks.values())
        else:r['accepted_for_screening']=False
        cases.append(r)
    atomic_json(FOLDER/'native_map_analysis.json',cases)
    atomic_json(FOLDER/'temperature_domain_audit.json',[
        {'pair':c['pair'],'calculation_upper_K':c['temperature_range_K'][1],
         'declarations_with_lower_upper_limit':c['temperature_domain_warnings']} for c in cases])
    return cases


def family(name):
    name=name.split('#')[0].upper()
    if name in {'FCC_A1','FCC_L12','FCC','L12','L12_CO3TI'}:return 'FCC'
    if name in {'BCC','BCC_A2','ORDER_B2','COTI','FETI','NITI'}:return 'BCC'
    if name in {'HCP','HCP_A3'}:return 'HCP'
    if name.endswith('_C14') or name in {'FE2TA','FE2TI'}:return 'C14'
    if name.endswith('_C15'):return 'C15'
    if name.endswith('_C36'):return 'C36'
    return name


def matches(case, phases):
    signature=Counter(family(s) for s in phases)
    return [b for b in case.get('invariants',[]) if Counter(family(s) for s in b['phases'])==signature
            and max(b['compositions'])-min(b['compositions'])>1e-6]


def vendor_matches(case, ref):
    results=[]
    for table in ref.get('tables',[]):
        if len(table)<3 or table[0][:2]!=['T','reaction'] or table[1][0]!='C':continue
        for row in table[2:]:
            phases=[s.strip() for s in re.split(r'\+|=>',row[1])]
            # Only verified structure/stoichiometry aliases are used.
            aliases={
                'CO-TA':{'COTA2':'C16'},'CO-W':{'CO3W':'TAO'},
                'NI-TI':{'NITI2':'NITI2','NI3TI':'NI3TI'},
            }.get(case['pair'],{})
            phases=[aliases.get(s.upper(),s) for s in phases]
            candidates=matches(case,phases)
            target=float(row[0])+273.15
            candidate=min(candidates,key=lambda b:abs(b['T_K']-target)) if candidates else None
            item={'reference_T_K':target,'reference_reaction':row[1], 'kind':'vendor_calculation_not_experiment',
                  'comparison':'structure-family only; ordering state and reaction direction not certified',
                  'native_T_K':candidate['T_K'] if candidate else None,
                  'delta_T_K':candidate['T_K']-target if candidate else None}
            results.append(item)
    return results


def interpolate_boundary(case, phase, x):
    values=[]
    for block in case.get('blocks',[]):
        if block['invariant'] or Counter(family(p) for p in block['phases'])!=Counter(['FCC','LIQUID']):continue
        for curve in block['curves']:
            if family(curve['phase'] or '')!=phase:continue
            for (x0,t0),(x1,t1) in zip(curve['xy'],curve['xy'][1:]):
                if min(x0,x1)<=x<=max(x0,x1) and abs(x1-x0)>1e-12:
                    values.append(t0+(t1-t0)*(x-x0)/(x1-x0))
    return statistics.median(values) if values else None


def cuni_check(case):
    rows=[]
    for i,(wcu,wni,ts,tl,acu,ani,carbon) in enumerate(CUNI_ROWS,1):
        invalid=[]
        if ts>tl:invalid.append('原表固相线高于液相线')
        if abs(wcu+wni-100)>.05:invalid.append('名义质量百分比合计不为100')
        x=(wni/58.69)/(wni/58.69+wcu/63.546)
        xa=None if acu is None or ani is None else (ani/58.69)/(ani/58.69+acu/63.546)
        pred=[interpolate_boundary(case,p,x) for p in ['FCC','LIQUID']]
        pred_a=[interpolate_boundary(case,p,xa) if xa is not None else None for p in ['FCC','LIQUID']]
        rows.append({'table_row':i,'nominal_weight_pct_Cu':wcu,'nominal_weight_pct_Ni':wni,
            'X_Ni_from_nominal_weights':x,'X_Ni_from_analysed_metal_weights':xa,
            'reported_carbon_weight_pct':carbon,'experimental_T_K':[ts,tl],
            'calculated_T_K':pred,'calculated_at_analysed_composition_T_K':pred_a,
            'delta_T_K':[p-t if p is not None else None for p,t in zip(pred,[ts,tl])],
            'excluded_from_statistics':bool(invalid),'data_issues':invalid})
    errors=[e for row in rows if not row['excluded_from_statistics'] for e in row['delta_T_K'] if e is not None]
    return {'source':'https://smenec.org/index.php/1/article/view/619','table':'Table 2, p.65',
        'basis':'Nominal mass percentages converted using Cu=63.546, Ni=58.69 g/mol; analysed composition shown separately; no correction of published typos.',
        'qualification':'Data-quality-limited comparison, not an accuracy acceptance test; measured carbon and composition uncertainty are not modeled.',
        'rows':rows,'matched_temperatures':len(errors),'rmse_K':math.sqrt(statistics.mean(e*e for e in errors)) if errors else None,
        'max_abs_error_K':max(map(abs,errors)) if errors else None}


def fmt(x):return '—' if x is None else f'{x:.2f}'
def esc(x):return html.escape(str(x))


def build():
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    cases=collect();by_pair={c['pair']:c for c in cases}
    public=load_public()
    assert len(cases)==21, 'Final report requires all 21 attempted binary calculations.'
    order_probe=json.loads((FOLDER/'experimental_order_CO-TI/result.json').read_text())
    assert order_probe['accepted'] and order_probe['model_sha256']==by_pair['CO-TI']['tdb_sha256']
    refs={r['pair']:r for r in json.loads((FOLDER/'public_reference_tables.json').read_text())}
    comparisons=[]
    for case in cases:
        case['literature']=REFERENCES[case['pair']]
        case['notes']=NOTES[case['pair']]
        case['vendor_reference']=refs[case['pair']]
        case['vendor_comparison']=vendor_matches(case,refs[case['pair']]) if case['accepted_for_screening'] else []
        if case['pair'] in public:case['public_experimental_comparison']=public[case['pair']]
        for anchor in BENCHMARKS:
            if anchor['pair']!=case['pair'] or not case['accepted_for_screening']:continue
            found=matches(case,anchor['phases'])
            if len(found)!=1:continue
            comparisons.append({**anchor,'native_T_K':found[0]['T_K'],'delta_T_K':found[0]['T_K']-anchor['T_K']})
    cuni=cuni_check(by_pair['CU-NI']) if 'CU-NI' in by_pair and by_pair['CU-NI']['accepted_for_screening'] else None
    if cuni:atomic_json(FOLDER/'CuNi_experimental_comparison.json',cuni)
    atomic_json(FOLDER/'experimental_temperature_comparison.json',comparisons)
    atomic_json(FOLDER/'validation_results.json',cases)
    plots=FOLDER/'plots';plots.mkdir(exist_ok=True)
    def draw(ax,case,overview=False):
        accepted=case['accepted_for_screening']
        limits=case.get('temperature_domain_warnings',[])
        if limits:
            t_limit=min(item['upper_T_K'] for item in limits)
            ax.axhspan(t_limit,case['temperature_range_K'][1],color='#d8dfe2',alpha=.5,hatch='//',zorder=0)
            if not overview:
                ax.text(.02,.98,f'Above {t_limit:g} K: some TDB terms outside declared range',
                        transform=ax.transAxes,va='top',fontsize=8,color='#68574c')
        for b in case.get('blocks',[]):
            for c in b['curves']:
                if len(c['xy'])<2:continue
                ax.plot([p[0]*100 for p in c['xy']],[p[1] for p in c['xy']],color='#1d6174' if accepted else '#aeb5ba',lw=.65 if overview else 1.1)
        name=case['pair'];second=name.split('-')[1]
        if not overview:
            if name=='CO-TA':
                for t in [1320,1303]:ax.axhline(t,color='#c95036',lw=1,ls='--',alpha=.8,label=f'DTA {t} K (T only)')
            elif name=='CO-TI':
                ax.axhline(1427.15,color='#c95036',lw=1,ls='--',label='2020 experiment: L + L12 + C36 (T only)')
            elif name=='CO-CU':
                ax.axhspan(1378,1386.5,color='#c95036',alpha=.2,label='DTA onset: 10–40 K/min')
            elif name=='CU-NI' and cuni:
                valid=[r for r in cuni['rows'] if not r['excluded_from_statistics']]
                for index,marker,label in [(0,'o','2008 solidus'),(1,'^','2008 liquidus')]:
                    ax.scatter([r['X_Ni_from_nominal_weights']*100 for r in valid],[r['experimental_T_K'][index] for r in valid],s=27,marker=marker,facecolors='none',edgecolors='#c95036',label=label,zorder=4)
            elif name=='NI-W':
                ax.scatter([15],[1223.15],marker='x',s=60,color='#c95036',label='Experiment: FCC + Ni4W',zorder=5)
            if name in public:
                overlay_public(ax,public[name]);ax.legend(loc='upper right',fontsize=7)
            if name in {'CO-TA','CO-CU','CO-TI','CU-NI','NI-W'}:ax.legend(loc='upper right',fontsize=8)
        ax.set(xlim=(0,100),ylim=case['temperature_range_K'],xlabel=f'{second} (at.%)',ylabel='Temperature (K)',title=name)
        ax.grid(alpha=.16);ax.spines[['top','right']].set_visible(False)
        if not accepted:ax.text(.5,.5,'REJECTED INPUT / RUN\nNot a validated diagram',transform=ax.transAxes,ha='center',va='center',color='#b7422b',fontsize=9 if overview else 14,bbox=dict(facecolor='white',alpha=.9,edgecolor='none'))
    for c in cases:
        fig,ax=plt.subplots(figsize=(9,5.5),layout='constrained');draw(ax,c)
        fig.savefig(plots/(c['pair']+'.png'),dpi=140);fig.savefig(plots/(c['pair']+'.svg'));plt.close(fig)
    fig,axes=plt.subplots(7,3,figsize=(15,24),layout='constrained')
    for ax,pair in zip(axes.flat,itertools.combinations(ELEMENTS,2)):
        name='-'.join(pair)
        if name in by_pair:draw(ax,by_pair[name],True)
        else:ax.set_title(name+' — pending');ax.axis('off')
    fig.savefig(plots/'all_21.png',dpi=135);plt.close(fig)
    count=sum(c['accepted_for_screening'] for c in cases)
    direct=''.join(f'<tr><td>{esc(c["pair"])}</td><td>{esc(" + ".join(c["phases"]))}</td><td>{fmt(c["T_K"])}</td><td>{fmt(c["native_T_K"])}</td><td>{c["delta_T_K"]:+.2f}</td><td><a href="https://doi.org/{c["doi"]}">{esc(c.get("heating_K_min","DTA"))}{" K/min" if "heating_K_min" in c else ""}</a></td></tr>' for c in comparisons)
    rows=[];cards=[]
    for pair in itertools.combinations(ELEMENTS,2):
        name='-'.join(pair);c=by_pair.get(name)
        if c is None:continue
        deltas=[abs(x['delta_T_K']) for x in c['vendor_comparison'] if x['delta_T_K'] is not None]
        assessment='局部实验温度对照' if name in {'CO-CU','CO-TA'} else '实验相序对照' if name=='CO-TI' else '实验点对照' if name=='NI-W' else '实验数表有质量限制' if name=='CU-NI' else '完整实验坐标未取得'
        if name in public:assessment=f'{public[name]["conditions"]} 个公开实验条件，局部对照'
        if name in extra_coverage():assessment='实验固溶度回归式对照' if name=='CU-FE' else '历史实验节点与反应类型对照'
        status='相界可用于筛查' if c['accepted_for_screening'] else '输入/运行未通过审计'
        rows.append(f'<tr data-pair="{name}"><td><a href="#{name}">{name}</a></td><td class="{"ok" if c["accepted_for_screening"] else "bad"}">{status}</td><td>{assessment}</td><td>{len(deltas)}</td><td>{fmt(max(deltas) if deltas else None)}</td></tr>')
        inv=''.join(f'<tr><td>{fmt(b["T_K"])}</td><td>{esc(" + ".join(b["phases"]))}</td><td>{esc(", ".join(f"{x*100:.4f}" for x in b["compositions"]))}</td></tr>' for b in c.get('invariants',[]) if max(b['compositions'])-min(b['compositions'])>1e-6)
        vendor=''.join(f'<tr><td>{esc(x["reference_reaction"])}</td><td>{fmt(x["reference_T_K"])}</td><td>{fmt(x["native_T_K"])}</td><td>{fmt(x["delta_T_K"])}</td></tr>' for x in c['vendor_comparison'])
        folder=c['folder'].replace('\\','/')
        diagnostics=''.join('<li>'+esc(s)+'</li>' for s in c['diagnostics'])
        range_warning='<p class="bad">3000 K 以上有部分函数或参数超出声明温区（图中阴影），仅作外推筛查，不作实验验收。</p>' if c['temperature_domain_warnings'] else ''
        cards.append(f'''<article id="{name}" data-pair="{name}"><h2>{name}<small>{status}</small></h2><div class="pairgrid"><img loading="lazy" src="plots/{name}.png" alt="{name} calculated phase boundaries"><div><p>{esc(c['notes'])}</p><p><a href="https://doi.org/{REFERENCES[name][0]}">{esc(REFERENCES[name][1])}</a></p><p>范围 {c['temperature_range_K'][0]:g}–{c['temperature_range_K'][1]:g} K · 1.01325 bar · 原子分数 · {c.get('point_count',0)} 个导出相界点。</p>{range_warning}<p><a href="{folder}/raw.log">原始日志</a> · <a href="{folder}/input.tcm">复现宏</a> · <a href="{folder}/model.tdb">计算副本</a> · <a href="{folder}/result.json">转换与运行审计</a> · <a href="plots/{name}.svg">矢量图</a></p>{'<ul class="bad">'+diagnostics+'</ul>' if diagnostics else ''}</div></div><details><summary>计算三相节点（排除纯端点退化节点）</summary><table><thead><tr><th>T / K</th><th>TC 原始相名</th><th>各端点成分 / at.%</th></tr></thead><tbody>{inv or '<tr><td colspan="3">未发现非退化三相节点；这不等于通过实验验证。</td></tr>'}</tbody></table></details><details><summary>公开数据库参考筛查：{len(deltas)} 项可匹配温度，最大差值 {fmt(max(deltas) if deltas else None)} K</summary><p><a href="{refs[name]['url']}">CompuTherm 公开相图</a>为计算参考，不是原始实验。仅按已确认的结构家族匹配，未确认名称的反应留空；温度差不能单独判定实验误差。</p><table><tr><th>参考反应</th><th>参考 T/K</th><th>本库 T/K</th><th>差 / K</th></tr>{vendor or '<tr><td colspan="4">没有可匹配的公开反应表。</td></tr>'}</table></details></article>''')
    niw=(FOLDER/'experimental_points_NI-W/raw.log').read_text(errors='replace') if (FOLDER/'experimental_points_NI-W/raw.log').exists() else ''
    niw_verified='NP(FCC_L12)=1' in niw and 'NP(NI4W)=0' in niw and 'Thermo-Calc completed normally' in niw and not re.search(r'\bERROR\b',niw)
    primary_niw='在 950°C、15 at.% W，实验观察 FCC + Ni4W；本库全相平衡给出无序 FCC 单相，Ni4W 相分数为零。20 at.% W 则给出化学计量 Ni4W；实验报道 Ni4W 有约 18.4–19.3 at.% W 的成分范围。相组合及均匀区描述均需复查。' if niw_verified else 'Ni–W 实验条件处的计算未通过日志核验，暂不下结论。'
    cuni_text=(f'用名义质量分数转为原子分数，排除 2 行明确自相矛盾的数据后，{cuni["matched_temperatures"]} 个温度的初步 RMSE 为 {fmt(cuni["rmse_K"])} K，最大绝对差 {fmt(cuni["max_abs_error_K"])} K。这个数字受原文成分偏差、碳污染及剩余印刷错误影响，不能作为严格验收指标。' if cuni else '尚未得到有效对照结果。')
    document=f'''<!doctype html><html lang="zh-CN"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>第6版数据库 · 21个二元体系验证</title><style>
    *{{box-sizing:border-box}}body{{margin:0;background:#f4f6f7;color:#1a3038;font:16px/1.65 "Microsoft YaHei",sans-serif}}main{{max-width:1250px;margin:auto;padding:36px 24px}}h1{{font-size:38px;line-height:1.2;margin:12px 0}}h2{{font-size:25px}}h3{{font-size:19px}}p{{max-width:1050px}}a{{color:#146579;text-underline-offset:3px}}.eyebrow{{letter-spacing:2px;color:#54737d;font-size:13px}}.banner{{background:#fff0e8;border-left:5px solid #ba4a2c;padding:18px 24px;border-radius:8px}}.kpis{{display:flex;gap:18px;flex-wrap:wrap;margin:26px 0}}.kpis div{{flex:1;min-width:160px;background:white;padding:18px 22px;border-radius:12px}}.kpis b{{display:block;font-size:32px}}article,section{{background:white;padding:26px;margin:24px 0;border-radius:14px}}table{{border-collapse:collapse;width:100%;font-size:14px}}td,th{{padding:11px 10px;border-bottom:1px solid #e3e8ea;text-align:left;vertical-align:top}}th{{color:#45616b;background:#f0f5f6}}small{{font-size:13px;color:#647a82;display:block;font-weight:400}}.pairgrid{{display:grid;grid-template-columns:1.2fr 1fr;gap:22px;align-items:start}}img{{width:100%;height:auto}}.bad{{color:#ad3e25}}.ok{{color:#216e63}}details{{margin-top:15px;border-top:1px solid #e0e7e9;padding-top:12px}}summary{{cursor:pointer;color:#266879}}input{{padding:12px 16px;border:1px solid #bed0d5;border-radius:8px;width:280px;max-width:100%;font:inherit}}code{{word-break:break-all;font-size:13px}}.muted{{color:#607983}}@media(max-width:800px){{.pairgrid{{grid-template-columns:1fr}}main{{padding:20px 12px}}h1{{font-size:29px}}article,section{{padding:16px}}table{{font-size:12px}}td,th{{padding:8px 5px}}}}
    </style><main><div class="eyebrow">Co · Cu · Fe · Ni · Ta · Ti · W / V6 / 2026-10-18</div><h1>21 个二元体系的计算与实验核查</h1><p class="muted">固定用户选定的第 6 版，不含 Re。源文件保留原样；计算使用有记录的兼容副本和显式重复参数解释。</p><div class="banner"><strong>结论：目前不能认为所有二元相图都与实验吻合。</strong><br>Co–Ta 两项实测反应温度存在偏差，Ni–W 有实验相组合不一致，Co–Ti 与 2020 实验的有序反应相序不同；输入定义和兼容性问题也需要处理。多数体系尚缺完整、可追溯的实验相界坐标，下面的公开数据库筛查不替代实验验收。</div>
    <div class="kpis"><div><b>{len(cases)}/21</b>已执行独立目录相图计算</div><div><b>{count}</b>通过导入与相界导出审计</div><div><b>{len(cases)-count}</b>结果被拒绝，保留诊断</div><div><b>{len(comparisons)}</b>直接实验反应温度对照</div></div>
    <section><h2>直接实验对照</h2><p>目前取得局部直接实验对照的有 Co–Cu、Co–Ta、Co–Ti、Cu–Ni、Ni–W 共 5 个体系；其余 16 个尚未取得足以逐点核查的实验坐标。下表差值为“本库计算 − 实测”。未设置任意的统一通过阈值；DTA 升温速率、成分误差、平衡状态与实验不确定度必须分别考虑。</p><table><tr><th>体系</th><th>相组合／家族</th><th>实测 K</th><th>计算 K</th><th>差 K</th><th>原始文献／条件</th></tr>{direct}</table><h3>Co–Ta 的冲突参数影响</h3><p>C36 的 <code>G(C36,CO:CO:CO,TA;0)</code> 有两个不同表达式。保留第一条时两项反应为 1373.12、1332.96 K；保留后一条时为 721.65、667.11 K。文献 DTA 分别为 1320、1303 K。这不是可忽略的文件格式差别，必须回查源参数表。</p><p><a href="tc_maps2_last/CO-TA/raw.log">后一条声明的原始计算日志</a> · <a href="native_unique_last_expanded/CO-TA/adaptation.json">两条表达式与选择记录</a></p><h3>Ni–W：实验相组合不一致</h3><p>{primary_niw}</p><p><a href="https://doi.org/10.1016/j.intermet.2008.11.001">2009 原始实验</a> · <a href="experimental_points_NI-W/point_0.txt">950°C / 15 at.% W 平衡输出</a> · <a href="experimental_points_NI-W/point_1.txt">20 at.% W 输出</a> · <a href="experimental_points_NI-W/raw.log">完整求解日志</a></p><h3>Co–Ti：温度接近，但有序反应相序不一致</h3><p>Wu 等（2020）报道 1154°C（1427.15 K）的 L → L1₂ + C36 共晶。当前模型先在 1426.17 K 出现 FCC 有序／无序支与 C36 的三相节点，随后在 1439.18 K 出现 L + 无序 FCC + C36 节点。在 25 at.% Ti 的独立全相平衡中，1425 K 为有序 L1₂ + C36，1427.15 和 1438 K 已为无序 FCC + C36，1440 K 为液相 + C36。因此不能把 1439.18 K 简单当成同一实验反应的 +12.03 K 温差；反应相的有序状态已经不同。这里比较的是该篇实验结果，不意味着文献争议已解决。</p><p><a href="https://doi.org/10.1016/j.jct.2019.105995">2020 原始实验</a> · <a href="experimental_order_CO-TI/point_0.txt">1425 K 占位</a> · <a href="experimental_order_CO-TI/point_1.txt">1427.15 K 占位</a> · <a href="experimental_order_CO-TI/point_2.txt">1438 K 占位</a> · <a href="experimental_order_CO-TI/point_3.txt">1440 K 输出</a> · <a href="experimental_order_CO-TI/result.json">独立计算审计</a></p><h3>Cu–Ni：可作初筛的实验数表</h3><p>{cuni_text}</p><p><a href="CuNi_experimental_comparison.json">逐点误差及排除理由</a> · <a href="https://smenec.org/index.php/1/article/view/619">2008 原始论文</a> · <a href="literature/CuNi_2008_page3.png">已目视核对的原表页</a></p></section>
    <section><h2>输入问题与计算流程边界</h2><ul><li><b>Fe–Ta、Fe–Ti：</b>源文件第 3258、3275 行分别定义 <code>G(C14,FE:TA:TA;1)</code>、<code>G(C14,FE:TI:TI;1)</code>。这两个纯端元的阶数应为 0；TC 明确报出 END MEMBERS MUST HAVE DEGREE ZERO。这两套输出不参与实验误差统计，尚未猜测重写参数的原意。</li><li><b>Ni–Ti：</b>第 8129、8131 行的 <code>G(NI3TI,NI:NI:NI,TI:NI,TI;n)</code> 仅有 n=0、1；TC GES6 不接受这种倒易交互项组合并回退 GES5。这是需要核对模型约定的兼容性问题，不能直接删项、补零后宣布通过。</li><li><b>NI8W：</b>实际组元为 NI:VA，没有 W，也没有 G 参数，无法代表 Ni8W 的热力学性质。</li><li><b>Fe–W：</b>μ 相疑似漏写科学记数法的 E；本次保留字面算式，不猜测修正。</li><li><b>含 Cu 的有序关联：</b>FCC_A1 包含 Cu，FCC_L12 不包含。二元限制下 FCC_L12 的所有金属亚点阵只剩同一单一元素，严格满足 y=y_dis，其有序差项恒为零；仅在这些二元副本中移除冗余纯端点及关联，未补造 Cu 有序参数。</li><li><b>重复参数：</b>相同声明仅保留一条；Co–Ta 的冲突声明分别测试。未补零端元、未重新拟合。</li><li><b>转换审计：</b>冻结 OPTIMIZATION 的存储值，代数展开括号，保留 EXP，复读核对参数、函数与相结构。只证明表达式转换，不等于跨软件物理语义已全部一致。</li><li><b>引擎流程：</b>Pandat 的“Success”但空表一律拒绝。TC 使用独立 TEMP/TMP 和 Java 临时目录；先前共享临时文件时的错误结果被排除。</li><li><b>范围：</b>300 K 起，常压，全成分；Cu–Ta、Cu–W 仅到 3199 K，未覆盖 Ta / W 端熔化范围。Cu–Ta、Cu–W、Ni–Ta、Ni–W、Ta–Ti、Ti–W 的部分函数或参数在 3000 K 截止，超过该温区的图段已加阴影，不纳入准确性判断。图中细小相区或临界端点还需要加密及独立求解复查。未包含压力扫描、动力学、亚稳相图或完整七元内部验证。</li></ul><p>TC 的 FCC_L12 / ORDER_B2 名称可能代表无序 FCC / BCC 支；不能把名称本身当作有序证据。相界坐标审计也不能证明每一个点的全局最优性。</p></section>
    <section><h2>21 个体系总览</h2><p>“公开参考最大差”只统计可按结构家族匹配的反应温度，单位 K。它是数据库之间的筛查差值，<b>不是实验误差或通过率</b>。Ni–W 的公开表还包含被后续实验质疑的 NiW / NiW2。</p><input id="filter" placeholder="筛选元素或体系，例如 FE / CO-TA" aria-label="筛选体系"><table><thead><tr><th>体系</th><th>计算审计</th><th>直接实验覆盖</th><th>参考匹配数</th><th>公开参考最大差 K</th></tr></thead><tbody>{''.join(rows)}</tbody></table><details><summary>查看全部相图缩略图</summary><a href="plots/all_21.png"><img loading="lazy" src="plots/all_21.png" alt="21 binary phase diagram overview"></a></details></section>
    {''.join(cards)}
    <section><h2>复现与数据追溯</h2><p>源文件 SHA-256：<code>{hashlib.sha256((FOLDER/'source_v6.tdb').read_bytes()).hexdigest()}</code></p><p><a href="validation_results.json">全部结果、相界与审计 JSON</a> · <a href="acceptance_matrix.json">逐体系验证状态（无整图实验通过项）</a> · <a href="experimental_temperature_comparison.json">直接实验温度对照</a> · <a href="public_reference_tables.json">公开参考表及来源</a> · <a href="parser_normalization.json">源文件预处理记录</a> · <a href="database_audit.json">模型定义审查</a> · <a href="temperature_domain_audit.json">参数温区与外推审查</a></p><p>复现脚本：<code>python -m examples.seven_binary_tc --isolated</code>；已有输出不会覆盖。每个目录的 input.tcm 和 model.tdb 可在相同 TC 版本中重放。本报告未改写 NAS 源库，未将未验证数据标为通过。</p></section></main><script>document.getElementById('filter').addEventListener('input',e=>{{const q=e.target.value.toUpperCase().replaceAll('–','-').trim();document.querySelectorAll('[data-pair]').forEach(x=>x.hidden=!x.dataset.pair.includes(q));}})</script></html>'''
    covered=sorted({'CO-CU','CO-TA','CO-TI','CU-NI','NI-W'}|set(public)|extra_coverage())
    original='目前取得局部直接实验对照的有 Co–Cu、Co–Ta、Co–Ti、Cu–Ni、Ni–W 共 5 个体系；其余 16 个尚未取得足以逐点核查的实验坐标。'
    updated=f'目前取得局部实验条件对照的有 {"、".join(covered)} 共 {len(covered)} 个体系；其余 {21-len(covered)} 个尚未形成有效的逐点实验对照。Fe–Ni 使用原实验作者在开放综述中重述的试样观测；Cu–Fe 新增对照为实验回归式，Cu–Ti 新增对照来自历史实验摘要。'
    assert original in document
    document=document.replace(original,updated)
    document=document.replace(f'<div><b>{len(comparisons)}</b>直接实验反应温度对照</div>',f'<div><b>{len(covered)}/21</b>已有局部实验对照的体系</div>')
    document=document.replace('Co–Ta 两项实测反应温度存在偏差，','新增检验还发现 Co–Fe 缺少 B2 有序状态、Co–W 和 Fe–Ni 的局部相组合不一致。Co–Ta 两项实测反应温度存在偏差，')
    document=document.replace('<section><h2>输入问题与计算流程边界</h2>',public_section(cases,public)+extra_section(cases)+'<section><h2>输入问题与计算流程边界</h2>')
    document=document.replace('<section><h2>21 个体系总览</h2>',literature_section()+'<section><h2>21 个体系总览</h2>')
    document=document.replace('</main><script>', '<section><h2>新增文献对照的复现顺序</h2><p>依次运行模块：<code>examples.seven_binary_public_points</code> → <code>examples.seven_binary_public_analysis</code> → <code>examples.seven_binary_more_public</code> → <code>examples.seven_binary_report</code> → <code>examples.seven_binary_report_checks</code>。前一步需要本机已有的 TC 教育版；其余从归档计算结果重新生成分析和报告。已存在的原始计算结果不会覆盖。</p><p><a href="report_checks.json">报告一致性与链接审查</a></p></section></main><script>')
    (FOLDER/'report.html').write_text(document,encoding='utf-8')
    print(json.dumps({'cases':len(cases),'accepted_for_screening':count,'direct_temperatures':len(comparisons),'NiW_point_audited':niw_verified,'CuNi_rmse_K':cuni['rmse_K'] if cuni else None},ensure_ascii=False))

if __name__=='__main__':build()
