"""Experimental regression and invariant comparisons, with reaction-type checks."""
from collections import Counter
import hashlib
import html
import json
import math
import statistics

from examples.seven_binary_validation import FOLDER
from examples.seven_binary_report import read_exp,family
from examples.seven_binary_public_analysis import parse_equilibrium
from examples.seven_binary_public_evidence import CUFE_SOURCE
from src.storage import atomic_json


def analyze():
    pair='CU-FE';folder=FOLDER/'public_literature_points'/pair
    run=json.loads((folder/'result.json').read_text());assert run['accepted']
    assert run['model_sha256']==hashlib.sha256((FOLDER/'tc_final_first'/pair/'model.tdb').read_bytes()).hexdigest()
    conditions=json.loads((folder/'conditions.json').read_text());rows=[]
    for i,row in enumerate(conditions):
        phases=parse_equilibrium(folder/f'point_{i:02}.txt','FE')
        assert abs(sum(p['amount'] for p in phases)-1)<5e-5
        assert abs(sum(p['amount']*p['X_second'] for p in phases)-row['X_second'])<5e-5
        assert len(phases)>1,'Require a saturated Cu-rich phase, not undersaturated single phase'
        fcc=min((p for p in phases if p['family']=='FCC'),key=lambda p:p['X_second'])
        assert fcc['X_second']<.1
        measured_w=10**(2.951-3357/row['T_K'])
        measured_x=(measured_w/55.845)/(measured_w/55.845+(100-measured_w)/63.546)
        calc_x=fcc['X_second'];calc_w=100*calc_x*55.845/(calc_x*55.845+(1-calc_x)*63.546)
        rows.append(dict(T_K=row['T_K'],reference_wt_pct=measured_w,reference_at_pct=100*measured_x,
                         calculated_wt_pct=calc_w,calculated_at_pct=100*calc_x,
                         delta_at_pct=100*(calc_x-measured_x),delta_wt_pct=calc_w-measured_w,
                         all_calculated_phases=phases,raw=f'public_literature_points/{pair}/point_{i:02}.txt'))
    cufe=dict(pair=pair,source=CUFE_SOURCE,rows=rows,
              rmse_at_pct=math.sqrt(statistics.mean(r['delta_at_pct']**2 for r in rows)),
              max_abs_at_pct=max(abs(r['delta_at_pct']) for r in rows),
              qualification='Five samples of one published experimental regression; not five raw data points or a full phase-diagram acceptance.')
    atomic_json(FOLDER/'CuFe_solubility_comparison.json',cufe)
    blocks=read_exp(FOLDER/'tc_final_first/CU-TI/calculated.exp')
    # All aliases correspond to matching source endmember stoichiometries and computed compositions.
    anchors=[
        dict(T_K=1276.15,phases=['LIQUID','BCC','C11_B'],reaction='eutectic',x_liquid=.69,
             experimental_reaction='L → beta-Ti + Ti2Cu',source_note='31 at.% Cu converted to 69 at.% Ti; Ti2Cu spelling in abstract cross-checked against adjacent text.'),
        dict(T_K=1233.15,phases=['LIQUID','C11_B','CUTI_B11'],reaction='eutectic',x_liquid=None,
             experimental_reaction='L → Ti2Cu + TiCu',source_note='Abstract prints 43 at.% Ce; composition excluded, temperature retained.'),
        dict(T_K=1133.15,phases=['LIQUID','CU2TI_H','CU4TI'],reaction='eutectic',x_liquid=.27,
             experimental_reaction='L → TiCu2 + TiCu4',source_note='73 at.% Cu converted to 27 at.% Ti.'),
        dict(T_K=1123.15,phases=['CU2TI_H','CU4TI','CU3TI2'],reaction='solid_decomposition',x_liquid=None,
             experimental_reaction='TiCu2 → TiCu4 + Ti2Cu3',source_note='High-temperature TiCu2 decomposition reported in publisher abstract.'),
    ]
    out=[]
    for anchor in anchors:
        found=[b for b in blocks if b['invariant'] and Counter(family(p) for p in b['phases'])==Counter(anchor['phases'])]
        assert len(found)==1,(anchor,found)
        b=found[0];candidates={}
        # Invariant triangles contain unlabelled coordinates. Recover phase identity
        # from the labelled two-phase branches that meet this exact temperature.
        for branch in blocks:
            if branch['invariant'] or not set(map(family,branch['phases'])).issubset(anchor['phases']):continue
            for curve in branch['curves']:
                if not curve['phase']:continue
                for x,t in curve['xy']:
                    if abs(t-b['T_K'])<1e-5:candidates.setdefault(family(curve['phase']),[]).append(x)
        comps={}
        for p,values in candidates.items():
            assert max(values)-min(values)<1e-6,(p,values)
            comps[p]=statistics.mean(values)
        assert len(comps)==3,comps
        kind=anchor['reaction'];xl=comps.get('LIQUID')
        if xl is not None:
            solids=[x for p,x in comps.items() if p!='LIQUID']
            kind='eutectic' if min(solids)<xl<max(solids) else 'peritectic'
        elif 'CU2TI_H' in comps:
            other=[x for p,x in comps.items() if p!='CU2TI_H']
            assert min(other)<comps['CU2TI_H']<max(other)
        sides={'above':set(),'below':set()}
        for branch in blocks:
            ps=tuple(sorted(map(family,branch['phases'])))
            if branch['invariant'] or len(ps)!=2 or not set(ps).issubset(anchor['phases']):continue
            for curve in branch['curves']:
                offsets=[t-b['T_K'] for x,t in curve['xy']]
                for k,offset in enumerate(offsets):
                    if abs(offset)>=1e-5:continue
                    # Follow adjacent curve samples, not the closest T anywhere on
                    # a nonmonotonic liquidus branch with a congruent-melting peak.
                    for j in [k-1,k+1]:
                        if 0<=j<len(offsets) and abs(offsets[j])>1e-5:
                            sides['above' if offsets[j]>0 else 'below'].add(ps)
        if kind=='eutectic':
            solid_pair=tuple(sorted(p for p in comps if p!='LIQUID'))
            assert solid_pair in sides['below'] and all(tuple(sorted(['LIQUID',p])) in sides['above'] for p in solid_pair),(anchor,sides)
        if kind=='peritectic':
            assert tuple(sorted(['LIQUID','BCC'])) in sides['above']
            assert tuple(sorted(['LIQUID','C11_B'])) in sides['below']
        if kind=='solid_decomposition':
            assert tuple(sorted(['CU4TI','CU3TI2'])) in sides['below']
            assert all(tuple(sorted(['CU2TI_H',p])) in sides['above'] for p in ['CU4TI','CU3TI2'])
        out.append(dict(**anchor,native_T_K=b['T_K'],delta_T_K=b['T_K']-anchor['T_K'],
                        native_reaction_type=kind,reaction_type_matches=kind==anchor['reaction'],
                        native_phase_X_Ti=comps,
                        adjacent_branches={side:sorted(value) for side,value in sides.items()},
                        liquid_delta_at_pct=100*(xl-anchor['x_liquid']) if xl is not None and anchor['x_liquid'] is not None else None))
    cuti=dict(pair='CU-TI',source={'doi':'10.1007/BF00775543','url':'https://link.springer.com/article/10.1007/BF00775543',
                                  'reference':'Eremenko, Buyanov and Prima (1966), publisher summary'},rows=out,
              qualification='Historical experimental summary also draws on literature. Later reassessments may revise it. One erroneous composition is excluded. Same phase set does not imply the same reaction topology; first node is not counted as a like-for-like reaction-temperature error.')
    atomic_json(FOLDER/'CuTi_invariant_comparison.json',cuti)
    print(json.dumps({'CuFe_rmse_at_pct':cufe['rmse_at_pct'],'CuFe_max_abs_at_pct':cufe['max_abs_at_pct'],'CuTi_nodes':out},ensure_ascii=False))


if __name__=='__main__':analyze()
