"""Reproduce native all-phase equilibria at published binary measurement conditions."""
import hashlib
import os
from pathlib import Path
import re
import shutil
import subprocess
from examples.engine_runtime import hidden_startupinfo
import tempfile
import time

from examples.cross_engine_thermocalc import java_command
from examples.engine_runtime import thermocalc_home
from examples.seven_binary_validation import FOLDER
from examples.seven_binary_public_evidence import measurements
from src.storage import atomic_json


def run(pair, conditions):
    out=FOLDER/'public_literature_points'/pair
    out.mkdir(exist_ok=True,parents=True)
    if (out/'result.json').exists():
        print(pair,'existing evidence retained',flush=True)
        return
    source=FOLDER/'tc_final_first'/pair/'model.tdb'
    first,second=pair.split('-')
    lines=['set-echo','go data','switch_database user model.tdb',
           f'define_elements {first} {second}','get_data','go p-3']
    for i,row in enumerate(conditions):
        lines+=['reinitiate_module',
                f'set_condition T={row["T_K"]} P=101325 N=1 X({second})={row["X_second"]}',
                'compute_equilibrium','list_equilibrium',f'point_{i:02}.txt','VXNSD',
                'show_value GM NP(*) X(*,*)']
    macro_text='\n'.join(lines+['exit',''])
    (out/'input.tcm').write_text(macro_text,encoding='ascii')
    shutil.copyfile(source,out/'model.tdb')
    atomic_json(out/'conditions.json',conditions)
    timed_out=False
    with tempfile.TemporaryDirectory(prefix='seven_literature_') as temp:
        work=Path(temp);scratch=work/'scratch';scratch.mkdir()
        macro=work/'input.tcm';macro.write_text(macro_text,encoding='ascii')
        shutil.copyfile(source,work/'model.tdb')
        env=dict(os.environ,TC26B_HOME=str(thermocalc_home()),LSHOST='NO-NET',LSERVRC=str(thermocalc_home()/'lservrc'),
                 TEMP=str(scratch),TMP=str(scratch))
        command=java_command(thermocalc_home(),macro);command.insert(1,'-Djava.io.tmpdir='+str(scratch))
        si = hidden_startupinfo()
        with (out/'raw.log').open('wb') as log:
            proc=subprocess.Popen(command,cwd=work,env=env,stdin=subprocess.DEVNULL,
                                  stdout=log,stderr=subprocess.STDOUT,startupinfo=si)
            start=time.monotonic();done=None
            while proc.poll() is None:
                raw=(out/'raw.log').read_text(errors='replace')
                if 'Thermo-Calc completed normally' in raw:done=done or time.monotonic()
                if done and time.monotonic()-done>5:proc.kill();break
                if time.monotonic()-start>300:timed_out=True;proc.kill();break
                time.sleep(.3)
            proc.wait()
        for file in work.glob('point_*.txt'):shutil.copyfile(file,out/file.name)
    raw=(out/'raw.log').read_text(errors='replace')
    diagnostics=[line for line in raw.splitlines() if re.search(
        r'\bERROR\b|Results may be wrong|NOT CONVERGED|NO CONVERGENCE|Ambiguous command',line,re.I)]
    result=dict(pair=pair,model_sha256=hashlib.sha256(source.read_bytes()).hexdigest(),
                timed_out=timed_out,diagnostics=diagnostics,
                accepted=not timed_out and not diagnostics and 'Thermo-Calc completed normally' in raw
                and all((out/f'point_{i:02}.txt').exists() for i in range(len(conditions))))
    atomic_json(out/'result.json',result)
    print(result,flush=True)


if __name__=='__main__':
    for pair in ['CO-FE','CO-W','FE-NI','CU-FE']:
        run(pair,measurements(pair))
