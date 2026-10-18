"""Compare published tie lines with independently calculated native equilibria."""
from collections import Counter
import hashlib
import itertools
import json
import math
import re
import statistics

from examples.seven_binary_report import family
from examples.seven_binary_validation import FOLDER
from examples.seven_binary_public_evidence import measurements
from src.storage import atomic_json

NUMBER=r'[-+]?\d+(?:\.\d*)?(?:[EeDd][-+]?\d+)?'


def parse_equilibrium(path,second):
    raw=path.read_text(errors='replace')
    markers=list(re.finditer(r'^\s*(\S+)\s+(?:(ORD|DISORD)\s+)?Status\s+ENTERED',raw,re.M))
    phases=[]
    for i,marker in enumerate(markers):
        block=raw[marker.end():markers[i+1].start() if i+1<len(markers) else len(raw)]
        amount=re.search(r'\bMoles\s+('+NUMBER+')',block)
        if not amount:raise ValueError('Missing phase amount: '+marker[1])
        moles=float(amount[1])
        if moles<=1e-8:continue
        composition=block.split('Mole fractions:',1)[1].split('Constitution:',1)[0]
        values=dict((m[1],float(m[2])) for m in re.finditer(r'\b([A-Z]{1,2})\s+('+NUMBER+')',composition))
        phases.append(dict(name=marker[1],family=family(marker[1]),ordering=marker[2],
                           amount=moles,X_second=values.get(second,0),composition=values))
    return phases


def compare(pair):
    folder=FOLDER/'public_literature_points'/pair
    run=json.loads((folder/'result.json').read_text())
    assert run['accepted'],run
    assert run['model_sha256']==hashlib.sha256((FOLDER/'tc_final_first'/pair/'model.tdb').read_bytes()).hexdigest()
    conditions=json.loads((folder/'conditions.json').read_text())
    rows=[];errors=[];order_errors=[]
    current=measurements(pair)
    # Enrich source annotations without changing the archived calculation conditions.
    for row,annotation in zip(conditions,current):
        assert row['T_K']==annotation['T_K'] and row['X_second']==annotation['X_second']
        if 'expected_ordering' in annotation:row['expected_ordering']=annotation['expected_ordering']
    for i,row in enumerate(conditions):
        phases=parse_equilibrium(folder/f'point_{i:02}.txt',pair.split('-')[1])
        total=sum(p['amount'] for p in phases)
        weighted=sum(p['amount']*p['X_second'] for p in phases)
        audit={'phase_amount_sum':total,'composition_balance_residual':weighted-row['X_second'],
               'passed':abs(total-1)<5e-5 and abs(weighted-row['X_second'])<5e-5}
        if not phases or not audit['passed']:raise ValueError((pair,i,audit))
        same=Counter(p['family'] for p in phases)==Counter(row['phases'])
        pairs=[]
        if same and row['observed_at_pct'] is not None:
            # Repeated FCC branches are compared in increasing composition order.
            for phase in sorted(set(row['phases'])):
                observed=sorted((x,j) for j,(p,x) in enumerate(zip(row['phases'],row['observed_at_pct'])) if p==phase)
                calculated=sorted((p for p in phases if p['family']==phase),key=lambda p:p['X_second'])
                for (observed_x,j),p in zip(observed,calculated):
                    delta=100*p['X_second']-observed_x
                    excluded=j in row['exclude_indices']
                    # A chemically ordered FCC branch is not experimental disordered alpha-Co.
                    expected_order=row.get('expected_ordering',[None]*len(row['phases']))[j]
                    if expected_order is None and phase=='FCC':expected_order='DISORD'
                    order_mismatch=expected_order is not None and p['ordering']!=expected_order
                    use=not excluded
                    pairs.append(dict(phase=phase,experimental_at_pct=observed_x,
                                      calculated_at_pct=100*p['X_second'],delta_at_pct=delta,
                                      experimental_index=j,native_ordering=p['ordering'],
                                      expected_ordering=expected_order,ordering_mismatch=order_mismatch,
                                      excluded_from_statistics=not use,
                                      exclusion_reason='source measurement flagged unreliable' if excluded else None))
                    if use:errors.append(delta)
                    if use and not order_mismatch:order_errors.append(delta)
        rows.append(dict(index=i,**row,calculated_phases=phases,phase_families_match=same,
                         phase_composition_comparisons=pairs,balance_audit=audit,
                         raw_equilibrium=str((folder/f'point_{i:02}.txt').relative_to(FOLDER))))
    result=dict(pair=pair,rows=rows,conditions=len(rows),
                phase_family_matches=sum(row['phase_families_match'] for row in rows),
                matched_reliable_compositions=len(errors),
                rmse_at_pct=math.sqrt(statistics.mean(e*e for e in errors)) if errors else None,
                max_abs_at_pct=max(map(abs,errors)) if errors else None,
                ordering_mismatch_conditions=sum(any(p['ordering_mismatch'] for p in row['phase_composition_comparisons']) for row in rows),
                order_consistent_compositions=len(order_errors),
                order_consistent_rmse_at_pct=math.sqrt(statistics.mean(e*e for e in order_errors)) if order_errors else None,
                qualification='Composition errors only for matching phase assemblages; mismatched rows remain explicit and are not rescued by phase suppression. No full-diagram acceptance claim.')
    atomic_json(folder/'comparison.json',result)
    return result


if __name__=='__main__':
    results=[]
    for pair in ['CO-FE','CO-W','FE-NI']:
        result=compare(pair);results.append(result)
        print({key:value for key,value in result.items() if key!='rows'})
        for row in result['rows']:
            print(row['T_K'],row['phases'],[(p['name'],p['ordering'],round(100*p['X_second'],4)) for p in row['calculated_phases']],
                  [round(p['delta_at_pct'],4) for p in row['phase_composition_comparisons']])
    atomic_json(FOLDER/'public_literature_comparisons.json',results)
