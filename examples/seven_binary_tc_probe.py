"""Read the native TC importer diagnostics for a binary variant."""
from pathlib import Path
import os
import shutil
import subprocess
from examples.engine_runtime import hidden_startupinfo
import tempfile
import time
from examples.cross_engine_thermocalc import java_command
from examples.seven_binary_validation import FOLDER

from examples.engine_runtime import thermocalc_home
home = thermocalc_home()
out=FOLDER/'tc_import_CO-FE';out.mkdir(exist_ok=True)
with tempfile.TemporaryDirectory(prefix='seven_tc_') as tmp:
    work=Path(tmp)
    shutil.copyfile(FOLDER/'native_unique_first/CO-FE/model.tdb',work/'model.tdb')
    macro=work/'probe.tcm'
    macro.write_text('set-echo\ngo data\nswitch_database user model.tdb\ndefine_elements CO FE\nget_data\ngo p-3\nset_condition T=1000 P=101325 N=1 X(FE)=0.5\ncompute_equilibrium\nlist_equilibrium\npoint.txt\nVXNSD\nshow_value GM NP(*) X(*,*)\nexit\n',encoding='ascii')
    shutil.copyfile(macro,out/'probe.tcm')
    si = hidden_startupinfo()
    env=dict(os.environ,TC26B_HOME=str(home),LSHOST='NO-NET',LSERVRC=str(home/'lservrc'))
    with (out/'raw.log').open('wb') as log:
        p=subprocess.Popen(java_command(home,macro),cwd=work,env=env,stdin=subprocess.DEVNULL,stdout=log,stderr=subprocess.STDOUT,startupinfo=si)
        start=time.monotonic();done=None
        while p.poll() is None:
            txt=(out/'raw.log').read_text(errors='replace')
            if 'Thermo-Calc completed normally' in txt:done=done or time.monotonic()
            if (done and time.monotonic()-done>3) or time.monotonic()-start>60:
                p.kill();break
            time.sleep(.5)
        p.wait()
    if (work/'point.txt').exists():shutil.copyfile(work/'point.txt',out/'point.txt')
print((out/'raw.log').read_text(errors='replace')[-20000:])
