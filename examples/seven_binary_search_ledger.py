"""Public literature availability and the limits of all 21 binary comparisons."""
import html
from examples.seven_binary_evidence import REFERENCES
from examples.seven_binary_validation import FOLDER
from examples.seven_binary_public_report import load,extra_coverage
from src.storage import atomic_json


LIMITS={
 'CO-NI':('已取得热力学实验与评估文献线索；未取得独立固液相线逐点表。实验过剩焓/自由能不是相界坐标。','https://doi.org/10.1002/bbpc.19790831016'),
 'CU-TA':('公开评估提到历史实验；铸态残留溶解度缺少完整温度条件，单个液相线点的温度和成分未取得。模型图不作实验。','https://www.sciencedirect.com/science/article/abs/pii/S0254058419303979'),
 'CU-W':('未取得原始平衡相界数表；检索到的共蒸发薄膜研究属于亚稳样品，不能用其过饱和固溶度验收平衡图。','https://doi.org/10.1116/1.572799'),
 'FE-TA':('源库纯端元阶数定义导致导入拒绝；现有 Fe–Ta–Ti 文献的三元实验不能直接替代本二元体系。','https://doi.org/10.1016/j.calphad.2019.03.002'),
 'FE-TI':('源库纯端元阶数定义导致导入拒绝；需核对端元原意后重算，当前不计算实验误差。','https://doi.org/10.1016/j.calphad.2019.03.002'),
 'FE-W':('已定位原评估及作者博士论文；全文读取受下载页面限制，未核实疑似科学记数法错误，也未取得新增实验表。','https://juser.fz-juelich.de/record/203363/files/'),
 'NI-TA':('已定位 2018 关键实验；后续论文转引了 DSC 数值，但本轮未取得原始实验表，转引值未计入直接实验统计。','https://doi.org/10.1016/j.tca.2018.06.011'),
 'NI-TI':('TC 对倒易交互项组合不兼容，计算拒绝；先处理模型约定问题。马氏体与稳定平衡相界不能混用。','https://doi.org/10.1016/j.calphad.2020.102194'),
 'TA-TI':('找到历史原始工作的公开节选，尚缺原始固液相线数表。评估归纳的溶解度、亚稳分相与从头算预测分别保留为线索。','https://www.onetunnel.org/documents/institute-of-metals-division-titanium-tungsten-and-titanium-tantalum-systems'),
 'TA-W':('定位到 Rudy 的历史技术报告记录；未取得可读取的实验熔化温度数表，完全互溶的概括不足以验证固液相线。','https://www.osti.gov/biblio/4754828'),
 'TI-W':('找到 Maykuth 与 Rudy/Windisch 的历史工作节选，早期拓扑有修订；未取得能核对单位、热处理和误差的原始相界表。','https://onemine.org/documents/part-v-may-1968-communications-revision-of-the-titanium-tungsten-system'),
}


def section():
    covered={'CO-CU','CO-TA','CO-TI','CU-NI','NI-W'}|set(load())|extra_coverage()
    public=load();ledger=[];rows=[]
    for pair,(doi,label) in REFERENCES.items():
        if pair in covered:
            if pair in public:
                source=public[pair]['rows'][0]['source']['url']
            elif pair=='CU-FE':source='https://doi.org/10.1063/1.324336'
            elif pair=='CU-TI':source='https://doi.org/10.1007/BF00775543'
            elif pair=='CU-NI':source='https://smenec.org/index.php/1/article/view/619'
            elif pair=='CO-CU':source='https://doi.org/10.1080/01411594.2012.668547'
            else:source='https://doi.org/'+doi
            state='已有局部实验对照'
            limit='覆盖范围及具体排除条件见对应章节；没有任何体系被标记为完整实验验收通过。'
        else:
            limit,source=LIMITS[pair];state='尚无有效逐点实验对照'
        ledger.append(dict(pair=pair,status=state,partial_comparison=pair in covered,
                           source_or_lead=source,limit=limit,
                           full_diagram_validated=False,search_date='2026-10-18'))
        rows.append(f'<tr><td><a href="#{pair}">{pair}</a></td><td>{state}</td><td>{limit}</td><td><a href="{html.escape(source,quote=True)}">来源 / 检索线索</a></td></tr>')
    assert len(ledger)==21
    atomic_json(FOLDER/'public_literature_search_ledger.json',ledger)
    return '<section id="literature-coverage"><h2>21 个体系的公开文献覆盖与缺口</h2><p>补充检索覆盖全部二元体系。对子任务提供的可用数值，已回查出版社原文页面后才纳入计算；其余条目只作为检索线索。历史评估图、厂商计算图、DFT 预测、亚稳薄膜和缺少条件的数据不冒充原始平衡实验。无法取得的原表或被拒绝的计算，保留为明确缺口。</p><table><tr><th>体系</th><th>本轮状态</th><th>限制与下一项所需证据</th><th>文献</th></tr>'+''.join(rows)+'</table><p><a href="public_literature_search_ledger.json">完整检索台账 JSON</a></p></section>'
