"""Build a portable, read-only snapshot of acquired binary literature and runs.

No download or thermodynamic calculation is performed by this command.
Experimental coverage is read from the audited evidence, never inferred from
the number of files or successful solver runs.
"""
import argparse
from datetime import datetime, timezone
import html
import itertools
import json
from pathlib import Path
import shutil
from urllib.parse import quote

from examples.seven_binary_evidence import REFERENCES, NOTES
from examples.verify_research_archive import digest, verify


def read(path):
    return json.loads(path.read_text(encoding='utf-8'))


def save(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')


def link(path, label=None):
    return '<a href="{}">{}</a>'.format(quote(path, safe='/#'), html.escape(label or path))


def build(study, output):
    study, output = Path(study).resolve(), Path(output).resolve()
    if study == output or study in output.parents or output in study.parents:
        raise ValueError('Study and output must be separate, non-overlapping directories')
    if output.exists():
        raise FileExistsError('Snapshot already exists; choose a new output directory')
    ledger = read(study/'public_literature_search_ledger.json')
    acceptance = {r['pair']: r for r in read(study/'acceptance_matrix.json')}
    expected = {'-'.join(p) for p in itertools.combinations(['CO','CU','FE','NI','TA','TI','W'], 2)}
    if {r['pair'] for r in ledger} != expected or len(ledger) != 21 or set(acceptance) != expected:
        raise ValueError('Expected exactly the 21 Co-Cu-Fe-Ni-Ta-Ti-W binary systems')
    source_files = sorted(p for p in study.rglob('*') if p.is_file())
    if any(p.is_symlink() for p in study.rglob('*')):
        raise ValueError('Resolve linked files explicitly before archiving')
    output.mkdir(parents=True)
    originals = []
    for source in source_files:
        relative = source.relative_to(study)
        target = output/'study'/relative
        target.parent.mkdir(parents=True, exist_ok=True)
        before = digest(source)
        shutil.copy2(source, target)
        if before != digest(target) or before != digest(source):
            raise ValueError('Source changed while copying: ' + str(relative))
        originals.append({'path': 'study/'+relative.as_posix(), 'bytes': target.stat().st_size, 'sha256': before})

    supplements = read(study/'screening_20261019.json') if (study/'screening_20261019.json').exists() else {}
    public = {d['pair']: d for d in read(study/'public_literature_comparisons.json')}
    metadata = read(study/'literature_metadata.json') if (study/'literature_metadata.json').exists() else []
    metadata_by_doi = {str(d.get('DOI', '')).lower(): d for d in metadata}
    temperature_rows = read(study/'experimental_temperature_comparison.json')
    data_names = {'CU-NI': 'CuNi_experimental_comparison.json', 'CU-FE':'CuFe_solubility_comparison.json',
                  'CU-TI':'CuTi_invariant_comparison.json', 'CO-FE':'CoFe_ordering_source_audit.json'}
    all_sources, all_records, catalogs = [], [], []
    for item in ledger:
        pair = item['pair']
        doi, title = REFERENCES[pair]
        sources = [dict(id=pair+'-context', doi=doi, title=title, url='https://doi.org/'+doi,
                        evidence_type='bibliographic_context_not_automatically_experimental',
                        metadata=metadata_by_doi.get(doi.lower()))]
        sources.append(dict(id=pair+'-screened', url=item['source_or_lead'],
                            evidence_type='screened_source_or_lead', limitations=item['limit']))
        if pair in public:
            for row in public[pair]['rows']:
                src = row.get('source')
                if src and not any(s.get('url') == src.get('url') and s.get('doi') == src.get('doi') for s in sources):
                    sources.append(dict(src, id=pair+'-measurement-source', evidence_type='experimental_source_as_documented'))
        sources += [s for s in supplements.get('sources', []) if pair == s.get('pair') or pair in s.get('pairs', [])]
        datasets = []
        for row in temperature_rows:
            if row['pair'] == pair:
                datasets.append(dict(kind='temperature_comparison', origin='study/experimental_temperature_comparison.json', data=row))
        if pair in public:
            datasets.append(dict(kind='published_condition_comparisons', origin='study/public_literature_comparisons.json', data=public[pair]))
        if pair in data_names:
            filename = data_names[pair]
            datasets.append(dict(kind='documented_comparison_or_diagnostic', origin='study/'+filename, data=read(study/filename)))
        for subdir in ['experimental_points_NI-W', 'experimental_order_CO-TI']:
            if subdir.endswith(pair):
                for name in ['conditions.json', 'result.json']:
                    if (study/subdir/name).exists():
                        datasets.append(dict(kind='native_followup_not_experimental_measurement',
                                             origin='study/'+subdir+'/'+name, data=read(study/subdir/name)))
        additions = [r for r in supplements.get('records', []) if r.get('pair') == pair]
        related = [r['path'] for r in originals if pair in r['path'] or pair.replace('-','').lower() in r['path'].lower()]
        record = dict(pair=pair, prior_screening=item, calculation=acceptance[pair],
                      interpretation=NOTES[pair], sources=sources, datasets=datasets,
                      supplemental_records=additions, related_files=related,
                      full_diagram_validated=bool(acceptance[pair]['complete_experimental_validation']))
        catalogs.append(record)
        save(output/'binaries'/pair/'index.json', record)
        all_sources += [dict(s, binary=pair) for s in sources]
        all_records += [dict(binary=pair, **d) for d in datasets]
        all_records += [dict(binary=pair, kind='supplemental_evidence', data=r) for r in additions]

    summary = dict(created_at=datetime.now(timezone.utc).isoformat(), binary_count=21,
                   source_file_count=len(originals), source_bytes=sum(r['bytes'] for r in originals),
                   calculation_audit_passed=sum(r['calculation_audit_passed'] for r in acceptance.values()),
                   partial_experimental_comparisons=sum(bool(r['partial_comparison']) for r in ledger),
                   full_diagrams_validated=sum(r['full_diagram_validated'] for r in catalogs),
                   supplemental_records=len(supplements.get('records', [])),
                   source_tdb_sha256=digest(study/'source_v6.tdb'),
                   scope='All acquired files in the input study; not all publications or every point in plotted literature figures.',
                   confidentiality='Contains the user\'s TDB and private research records; do not publish this snapshot to a public code repository.')
    save(output/'catalog.json', dict(summary=summary, binaries=catalogs))
    save(output/'sources.json', all_sources)
    save(output/'search_events.json', dict(prior_21_pair_screening=ledger, followup=supplements.get('search_events', [])))
    (output/'records.jsonl').write_text(''.join(json.dumps(r, ensure_ascii=False)+'\n' for r in all_records), encoding='utf-8')
    shutil.copyfile(Path(__file__).with_name('verify_research_archive.py'), output/'verify_archive.py')
    rows, sections = [], []
    for entry in catalogs:
        pair = entry['pair']
        rows.append('<tr><td>'+link('#'+pair,pair)+'</td><td>'+('通过运行审计' if entry['calculation']['calculation_audit_passed'] else '计算拒绝')+
                    '</td><td>'+('局部对照' if entry['prior_screening']['partial_comparison'] else '待比较 / 缺原始表')+
                    '</td><td>'+str(len(entry['supplemental_records']))+'</td><td>'+html.escape(entry['interpretation'])+'</td></tr>')
        source_links=''.join('<li><a href="'+html.escape(s['url'],quote=True)+'">'+html.escape(s.get('title',s.get('reference',s.get('id','source'))))+
                             '</a> — '+html.escape(s.get('evidence_type','source'))+'</li>' for s in entry['sources'])
        files=''.join('<li>'+link(path)+'</li>' for path in entry['related_files'])
        sections.append('<section id="'+pair+'"><h2>'+pair+'</h2><p>'+html.escape(entry['interpretation'])+'</p><p>'+link('binaries/'+pair+'/index.json','完整数据与来源 JSON')+
                        '</p><ul>'+source_links+'</ul><details><summary>已保存文件（'+str(len(entry['related_files']))+'）</summary><ul>'+files+'</ul></details></section>')
    document='''<!doctype html><html lang="zh-CN"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>21 个二元体系 · 文献与计算归档</title>
<style>body{max-width:1200px;margin:40px auto;padding:0 24px;font:16px/1.6 system-ui;color:#182b3c;background:#f7f9fb}h1{font-size:30px}a{color:#145d9c}table{border-collapse:collapse;width:100%;background:white}td,th{padding:10px;border:1px solid #d6dfe6;text-align:left}td:first-child{white-space:nowrap}section{background:white;padding:20px;margin:24px 0;border:1px solid #d6dfe6}li{overflow-wrap:anywhere}.note{background:#fff4d4;padding:16px}</style>
<h1>Co–Cu–Fe–Ni–Ta–Ti–W：21 个二元体系</h1>
<p>V6 数据库的公开文献筛查、实验记录与完整计算存档。Re 不包含在这 21 个二元体系中。</p>
<p class="note">18 个计算通过运行审计，10 个体系有局部实验对照，0 个完成完整实验验收。新增 Fe–Ti 原始实验记录仍待模型导入修复后比较。未取得的原文、原图散点及不确定度均保留为缺口；“全部”指本次已取得的文件与数据。</p>
<p>原始数据库、转换副本、成功及拒绝的计算、原生日志、文献 PDF、图表和现有报告均在 study/ 中。计算软件导出的 calculated.exp 是计算曲线，不是实验散点。</p>
<p>校验：<code>python3 verify_archive.py</code>；每个文件的大小和 SHA256 见 '''+link('manifest.json')+'''。</p><p>'''+link('catalog.json')+' · '+link('sources.json')+' · '+link('records.jsonl')+' · '+link('search_events.json')+' · '+link('study/report.html','原始对照报告')+'''</p>
<table><thead><tr><th>体系</th><th>计算状态</th><th>实验对照</th><th>新增记录</th><th>结论与缺口</th></tr></thead><tbody>'''+''.join(rows)+'</tbody></table>'+''.join(sections)+'</html>'
    (output/'index.html').write_text(document, encoding='utf-8')
    manifest_files = [dict(path=p.relative_to(output).as_posix(),bytes=p.stat().st_size,sha256=digest(p))
                      for p in sorted(output.rglob('*')) if p.is_file()]
    save(output/'manifest.json',dict(schema=1,summary=summary,files=manifest_files))
    checked = verify(output)
    if not checked['ok']:
        raise ValueError(checked)
    return dict(summary=summary, integrity=checked)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--study', required=True, type=Path)
    parser.add_argument('--output', required=True, type=Path)
    args = parser.parse_args()
    print(json.dumps(build(args.study,args.output),ensure_ascii=False,indent=2))


if __name__ == '__main__':
    main()
