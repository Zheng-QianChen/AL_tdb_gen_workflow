"""Independent equilibria at published experimental conditions."""
import json
import os
from pathlib import Path
import shutil
import subprocess
from examples.engine_runtime import hidden_startupinfo
import tempfile
import time
from examples.seven_binary_validation import FOLDER
from examples.engine_runtime import thermocalc_home
from examples.cross_engine_thermocalc import java_command

out=FOLDER/'experimental_points_NI-W';out.mkdir(exist_ok=True)
source=FOLDER/'tc_maps2_first/NI-W/model.tdb'
lines=['set-echo','go data','switch_database user model.tdb','define_elements NI W','get_data','go p-3']
for i,x in enumerate([.15,.20]):
    lines+=['reinitiate_module',f'set_condition T=1223.15 P=101325 N=1 X(W)={x}',
            'compute_equilibrium','list_equilibrium',f'point_{i}.txt','VXNSD','show_value GM NP(*) X(*,*)']
lines+=['exit','']
macro_text='\n'.join(lines)
(out/'input.tcm').write_text(macro_text,encoding='ascii');shutil.copyfile(source,out/'model.tdb')
with tempfile.TemporaryDirectory(prefix='seven_exp_') as tmp:
    work=Path(tmp);scratch=work/'scratch';scratch.mkdir()
    macro=work/'input.tcm';macro.write_text(macro_text,encoding='ascii');shutil.copyfile(source,work/'model.tdb')
    env=dict(os.environ,TC26B_HOME=str(thermocalc_home()),LSHOST='NO-NET',LSERVRC=str(thermocalc_home()/'lservrc'),TEMP=str(scratch),TMP=str(scratch))
    command=java_command(thermocalc_home(),macro);command.insert(1,'-Djava.io.tmpdir='+str(scratch))
    si = hidden_startupinfo()
    with (out/'raw.log').open('wb') as log:
        p=subprocess.Popen(command,cwd=work,env=env,stdin=subprocess.DEVNULL,stdout=log,stderr=subprocess.STDOUT,startupinfo=si)
        start=time.monotonic();done=None
        while p.poll() is None:
            raw=(out/'raw.log').read_text(errors='replace')
            if 'Thermo-Calc completed normally' in raw:done=done or time.monotonic()
            if (done and time.monotonic()-done>5) or time.monotonic()-start>90:p.kill();break
            time.sleep(.3)
        p.wait()
    for file in work.glob('point_*.txt'):shutil.copyfile(file,out/file.name)
print((out/'raw.log').read_text(errors='replace')[-11000:])
