"""Explicit duplicate-policy sensitivity cases; never alter the frozen V6 source."""
import argparse
from collections import defaultdict
import hashlib
import itertools
import json
import shutil
import time
import math

from examples.seven_binary_pandat import portable, document, MELTING
from examples.engine_runtime import pandat_executable
from examples.seven_binary_validation import FOLDER, ELEMENTS
from examples.pandat_tdb import pandat_text
from examples.pandat_batch import run_document
from src.gibbs import read_databases
from src.storage import atomic_json

def expand_tdb(expression):
    from symengine import Piecewise
    if isinstance(expression, Piecewise):
        args=expression.args
        return Piecewise(*[(expand_tdb(args[i]),args[i+1]) for i in range(0,len(args),2)])
    return expression.expand()

def restore_exp(db):
    # pycalphad 0.11.1 calls .n() while parsing EXP(), turning E into a
    # floating base; its own writer then rejects the symbolic exponent.
    from symengine import E, RealDouble
    substitution={RealDouble(math.e):E}
    for p in db._parameters.all():
        db._parameters.update({'parameter':p['parameter'].xreplace(substitution)},doc_ids=[p.doc_id])
    db.symbols={k:v.xreplace(substitution) for k,v in db.symbols.items()}


def prepare(pair, policy):
    original_path, db, original_audit = portable(pair, serialize=False)
    groups = defaultdict(list)
    for p in db._parameters.all():
        groups[(p['phase_name'], p['parameter_type'], str(p['constituent_array']), p['parameter_order'])].append(p)
    changes = []
    for key, pars in groups.items():
        if len(pars) < 2:
            continue
        identical = len({str(p['parameter']) for p in pars}) == 1
        chosen = 0 if policy == 'first' else len(pars)-1
        changes.append({'key': list(key), 'identical': identical,
                        'expressions': [str(p['parameter']) for p in pars], 'retained_index': chosen})
        db._parameters.remove(doc_ids=[p.doc_id for i, p in enumerate(pars) if i != chosen])
    expansions=[]
    for p in db._parameters.all():
        expanded=expand_tdb(p['parameter'])
        if str(expanded)!=str(p['parameter']):
            expansions.append({'phase':p['phase_name'],'before':str(p['parameter']),'after':str(expanded)})
        db._parameters.update({'parameter':expanded},doc_ids=[p.doc_id])
    db.symbols={k:expand_tdb(v) for k,v in db.symbols.items()}
    restore_exp(db)
    folder = FOLDER / ('native_unique_'+policy+'_expanded') / '-'.join(pair)
    folder.mkdir(parents=True, exist_ok=True)
    dest = folder/'model.tdb'
    content = pandat_text(db)
    dest.write_text(content, encoding='utf-8')
    reread, _ = read_databases([str(dest)])
    def pars(database):
        return sorted((p['phase_name'], p['parameter_type'], str(p['constituent_array']),
                       p['parameter_order'], str(p['parameter'].n())) for p in database._parameters.all())
    def phases(database):
        return {k: (v.sublattices, v.constituents,
                    {a:b for a,b in v.model_hints.items() if not a.startswith('symmetry_')})
                for k,v in database.phases.items()}
    checks = {'parameters': pars(db)==pars(reread),
              'functions': {k:str(v.n()) for k,v in db.symbols.items()}=={k:str(v.n()) for k,v in reread.symbols.items()},
              'phase_structures_and_model_hints': phases(db)==phases(reread)}
    if not all(checks.values()):
        raise ValueError(f'Roundtrip failed: {checks}')
    audit = {'source_audit': original_audit, 'duplicate_policy': policy, 'duplicate_changes': changes,
             'conflicting_duplicates': sum(not x['identical'] for x in changes),
             'roundtrip': checks, 'EXP_preserved_through_writer': True, 'algebraic_expansions':expansions, 'sha256': hashlib.sha256(dest.read_bytes()).hexdigest(),
             'qualification': 'Conditional interpretation of ambiguous V6 declarations; not an unmodified-source validation.'}
    atomic_json(folder/'adaptation.json', audit)
    return folder, db, audit


def run(pairs=None, policy='first', timeout=120, density=8):
    for pair in itertools.combinations(ELEMENTS, 2):
        name = '-'.join(pair)
        if pairs and name not in pairs:
            continue
        folder = FOLDER/('native_unique_'+policy+'_expanded')/name
        if (folder/'result.json').exists():
            print('EXISTS', name, flush=True)
            continue
        item={'pair': name, 'duplicate_policy': policy}
        start=time.monotonic()
        print('START', name, flush=True)
        try:
            folder, db, audit=prepare(pair, policy)
            upper=min(max(MELTING[el] for el in pair)+200,3199 if 'CU' in pair else 3999)
            item.update(temperature_range_K=[300,upper], adaptation=audit)
            doc=document(pair,list(db.phases),300,upper).replace('scanline_density value="8"',f'scanline_density value="{density}"')
            if (folder/'raw').exists():
                raise ValueError('Refusing to overwrite raw evidence')
            result=run_document(pandat_executable(),folder,doc,1,timeout=timeout)
            item.update(status='output_created',execution=result)
        except Exception as exc:
            item.update(status='error',error=f'{type(exc).__name__}: {exc}')
        item['seconds']=round(time.monotonic()-start,2)
        folder.mkdir(parents=True,exist_ok=True)
        atomic_json(folder/'result.json',item)
        print(json.dumps({k:v for k,v in item.items() if k!='adaptation'},ensure_ascii=False),flush=True)


if __name__=='__main__':
    parser=argparse.ArgumentParser()
    parser.add_argument('--pairs',nargs='*')
    parser.add_argument('--policy',choices=['first','last'],default='first')
    parser.add_argument('--timeout',type=float,default=120)
    parser.add_argument('--density',type=int,default=8)
    args=parser.parse_args()
    run(args.pairs,args.policy,args.timeout,args.density)
