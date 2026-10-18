"""Regenerate the evidence matrix and check internal report consistency."""
import hashlib
from html.parser import HTMLParser
import json
from urllib.parse import unquote,urlsplit

from examples.seven_binary_validation import FOLDER
from examples.seven_binary_public_report import load,extra_coverage
from src.storage import atomic_json


class Links(HTMLParser):
    def __init__(self):super().__init__();self.links=[];self.ids=set()
    def handle_starttag(self,tag,attrs):
        attrs=dict(attrs)
        if 'id' in attrs:self.ids.add(attrs['id'])
        for name in ['href','src']:
            if name in attrs:self.links.append(attrs[name])


def check():
    cases=json.loads((FOLDER/'validation_results.json').read_text())
    public=load()
    matrix=json.loads((FOLDER/'acceptance_matrix.json').read_text())
    previous={r['pair']:r for r in matrix}
    assert len(cases)==21 and len({c['pair'] for c in cases})==21
    matrix=[]
    for case in cases:
        pair=case['pair'];entry=previous[pair]
        entry.update(calculation_audit_passed=case['accepted_for_screening'],complete_experimental_validation=False)
        if pair in public:
            data=public[pair]
            entry.update(partial_experimental_evidence=f'{data["conditions"]} published experimental conditions: '
                         f'{data["phase_family_matches"]} phase-family matches, '
                         f'{data["ordering_mismatch_conditions"]} conditions with chemical-order mismatch',
                         experimental_evidence_file=f'public_literature_points/{pair}/comparison.json',
                         status='partial_experiment_only')
            for row in data['rows']:assert row['balance_audit']['passed']
        if pair in extra_coverage():
            entry.update(status='partial_experiment_only',
                         partial_experimental_evidence='Five evaluation temperatures of published EPMA solubility regression' if pair=='CU-FE' else 'Four historical experimental invariant nodes, including one reaction-topology mismatch',
                         experimental_evidence_file='CuFe_solubility_comparison.json' if pair=='CU-FE' else 'CuTi_invariant_comparison.json')
        matrix.append(entry)
    atomic_json(FOLDER/'acceptance_matrix.json',matrix)
    document=(FOLDER/'report.html').read_text(encoding='utf8')
    parser=Links();parser.feed(document)
    broken=[]
    for link in parser.links:
        url=urlsplit(link)
        if url.scheme or url.netloc:continue
        if url.path:
            if not (FOLDER/unquote(url.path)).exists():broken.append(link)
        elif url.fragment and url.fragment not in parser.ids:broken.append(link)
    digest=hashlib.sha256((FOLDER/'source_v6.tdb').read_bytes()).hexdigest()
    assert digest=='2bf1ce0e798a411ab5110b8389fe934a80ead3ed1b90c6273e63cf588b226782'
    covered=sum(bool(r['partial_experimental_evidence']) for r in matrix)
    assert covered==5+len(public)+len(extra_coverage())
    assert f'共 {covered} 个体系' in document
    ledger=json.loads((FOLDER/'public_literature_search_ledger.json').read_text())
    assert len(ledger)==21 and sum(r['partial_comparison'] for r in ledger)==covered
    assert not broken,broken
    result=dict(binary_cases=len(cases),accepted_run_audits=sum(c['accepted_for_screening'] for c in cases),
                rejected_run_audits=sum(not c['accepted_for_screening'] for c in cases),
                systems_with_partial_direct_experiment=covered,
                systems_without_direct_experimental_comparison=21-covered,
                systems_validated_over_entire_experimental_diagram=0,
                additional_public_conditions=sum(r['conditions'] for r in public.values()),
                additional_phase_family_mismatches=sum(r['conditions']-r['phase_family_matches'] for r in public.values()),
                additional_ordering_mismatches=sum(r['ordering_mismatch_conditions'] for r in public.values()),
                experimental_regression_evaluation_temperatures=5 if 'CU-FE' in extra_coverage() else 0,
                historical_experimental_nodes=4 if 'CU-TI' in extra_coverage() else 0,
                historical_reaction_topology_mismatches=1 if 'CU-TI' in extra_coverage() else 0,
                broken_local_links=broken,source_copy_sha256=digest,
                evidence_note='18 is an import/run/coordinate audit count, not an experimental acceptance count. Fe-Ni observations are recounted by the original researchers in an open review.',
                visual_review=['plots/all_21.png','plots/NI-W.png','plots/CU-NI.png','plots/CO-TA.png',
                               'plots/CO-FE_public_zoom.png','plots/CO-W_public_zoom.png','plots/FE-NI_public_zoom.png',
                               'plots/CU-FE_solubility.png'])
    atomic_json(FOLDER/'report_checks.json',result)
    print(json.dumps(result,ensure_ascii=False))


if __name__=='__main__':check()
