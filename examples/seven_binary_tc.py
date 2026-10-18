"""Native TC MAP exports, with strict import-error rejection."""
import argparse
import hashlib
import itertools
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
from examples.engine_runtime import hidden_startupinfo
import tempfile
import time
from examples.cross_engine_thermocalc import java_command
from examples.seven_binary_validation import FOLDER, ELEMENTS
from examples.seven_binary_variants import prepare
from examples.seven_binary_pandat import MELTING
from src.storage import atomic_json

from examples.engine_runtime import thermocalc_home

def run_one(pair, policy='first', timeout=150, reduce_unary_ordering=False, isolated=False):
    name='-'.join(pair)
    out=FOLDER/(('tc_final_' if isolated else 'tc_maps3_' if reduce_unary_ordering else 'tc_maps2_')+policy)/name
    if (out/'result.json').exists():
        return json.loads((out/'result.json').read_text())
    out.mkdir(parents=True,exist_ok=True)
    base=FOLDER/('native_unique_'+policy+'_expanded')/name
    if not (base/'adaptation.json').exists():prepare(pair,policy)
    audit=json.loads((base/'adaptation.json').read_text())
    high=min(max(MELTING[e] for e in pair)+200,3199 if 'CU' in pair else 3999)
    text='\n'.join(['set-echo','go data','switch_database user model.tdb',
          'define_elements '+' '.join(pair),'get_data','go p-3',
          f'set_condition T=1200 P=101325 N=1 X({pair[1]})=0.5',
          'compute_equilibrium','list_equilibrium','seed.txt','VXNSD',
          f'set_axis_variable 1 X({pair[1]}) 0 1 0.02',
          f'set_axis_variable 2 T 300 {high} 25','map','post',
          f'set_diagram_axis X MOLE_FRACTION {pair[1]}','set_diagram_axis Y T',
          'make_experimental calculated.exp','exit','exit',''])
    (out/'input.tcm').write_text(text,encoding='ascii')
    shutil.copyfile(base/'model.tdb',out/'model.tdb')
    if reduce_unary_ordering:
        from src.gibbs import read_databases
        from examples.pandat_tdb import pandat_text
        from examples.seven_binary_variants import restore_exp
        db,_=read_databases([str(out/'model.tdb')])
        phase=db.phases['FCC_L12']
        if 'CU' not in pair or any(len(group)!=1 for group in phase.constituents):
            raise ValueError('Reduction only proven for unary FCC_L12 in Cu binary restrictions')
        audit['unary_order_reduction']={'phase':'FCC_L12','reference':'FCC_A1',
            'constituents':[[str(s) for s in group] for group in phase.constituents],
            'free_site_fraction_variables':0,
            'proof':'All equivalent metal sites contain the same single species. y=y_dis exactly, so G_order(y)-G_order(y_dis)=0 (also TC/BMAG corrections). The unary ordered phase is the same pure-element endpoint already represented by FCC_A1. Remove only this redundant branch and its ordering link; no Cu ordering interaction is invented.'}
        del db.phases['FCC_L12']
        for phase in db.phases.values():
            if phase.model_hints.get('ordered_phase')=='FCC_L12':
                phase.model_hints.pop('ordered_phase',None);phase.model_hints.pop('disordered_phase',None)
        db._parameters.remove(doc_ids=[p.doc_id for p in db._parameters.all() if p['phase_name']=='FCC_L12'])
        restore_exp(db)
        (out/'model.tdb').write_text(pandat_text(db),encoding='utf-8')
    start=time.monotonic(); timed_out=False
    with tempfile.TemporaryDirectory(prefix='seven_tcmap_') as tmp:
        work=Path(tmp)
        shutil.copyfile(out/'model.tdb',work/'model.tdb')
        macro=work/'map.tcm';macro.write_text(text,encoding='ascii')
        si = hidden_startupinfo()
        env=dict(os.environ,TC26B_HOME=str(thermocalc_home()),LSHOST='NO-NET',LSERVRC=str(thermocalc_home()/'lservrc'))
        command=java_command(thermocalc_home(),macro)
        if isolated:
            scratch=work/'scratch';scratch.mkdir()
            env.update(TEMP=str(scratch),TMP=str(scratch))
            command.insert(1,'-Djava.io.tmpdir='+str(scratch))
        with (out/'raw.log').open('wb') as log:
            p=subprocess.Popen(command,cwd=work,env=env,stdin=subprocess.DEVNULL,
                               stdout=log,stderr=subprocess.STDOUT,startupinfo=si)
            done=None
            while p.poll() is None:
                raw=(out/'raw.log').read_text(errors='replace')
                if 'Thermo-Calc completed normally' in raw or 'Thermo-Calc completed with an error' in raw:done=done or time.monotonic()
                if done and time.monotonic()-done>5: p.kill(); break
                if time.monotonic()-start>timeout: timed_out=True; p.kill(); break
                time.sleep(.3)
            p.wait()
        for file in work.iterdir():
            if file.name not in {'map.tcm','model.tdb'} and file.is_file():shutil.copyfile(file,out/file.name)
    raw=(out/'raw.log').read_text(errors='replace')
    errors=[line.strip() for line in raw.splitlines() if re.search(r'\bERROR\b|Results may be wrong|NO SUCH COMMAND|NOT CONVERGED|NO CONVERGENCE|error reading|errors reading|Ambiguous command',line,re.I)]
    native_complete='Thermo-Calc completed normally' in raw
    result={'pair':name,'engine':'Thermo-Calc Education 2026b','pressure_Pa':101325,
            'temperature_range_K':[300,high],'nominal_max_axis_steps':{'X':.02,'T_K':25},
            'tdb_sha256':hashlib.sha256((out/'model.tdb').read_bytes()).hexdigest(),
            'duplicate_policy':policy,'adaptation':audit,'timed_out':timed_out,
            'normal_macro_completion':native_complete,'diagnostics':errors,
            'map_file_created':(out/'calculated.exp').exists(),'seconds':round(time.monotonic()-start,2)}
    result['status']='exported_requires_audit' if native_complete and not errors and not timed_out and result['map_file_created'] else 'rejected'
    atomic_json(out/'result.json',result)
    return result

if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--pairs',nargs='*');parser.add_argument('--policy',default='first');parser.add_argument('--timeout',type=float,default=150);parser.add_argument('--reduce-unary-ordering',action='store_true');parser.add_argument('--isolated',action='store_true');args=parser.parse_args()
    for pair in itertools.combinations(ELEMENTS,2):
        name='-'.join(pair)
        if args.pairs and name not in args.pairs:continue
        print('START',name,flush=True)
        try:r=run_one(pair,args.policy,args.timeout,args.reduce_unary_ordering or (args.isolated and 'CU' in pair),args.isolated)
        except Exception as e:r={'pair':name,'status':'exception','error':repr(e)}
        print(json.dumps({k:v for k,v in r.items() if k!='adaptation'},ensure_ascii=False),flush=True)
