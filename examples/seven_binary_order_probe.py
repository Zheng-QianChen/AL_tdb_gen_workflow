"""Audit the ordering state near the reported Co-Ti eutectic; retain native output."""
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
from src.storage import atomic_json


def main():
    out = FOLDER / 'experimental_order_CO-TI'
    out.mkdir(exist_ok=True)
    if (out / 'result.json').exists():
        raise FileExistsError('Keep existing evidence; use a new directory for another run.')
    source = FOLDER / 'tc_final_first/CO-TI/model.tdb'
    # Below/above the experimental 1427.15 K eutectic and the computed 1439.18 K node.
    conditions = [(1425, .25), (1427.15, .25), (1438, .25), (1440, .25)]
    lines = ['set-echo', 'go data', 'switch_database user model.tdb',
             'define_elements CO TI', 'get_data', 'go p-3']
    for i, (temperature, composition) in enumerate(conditions):
        lines += ['reinitiate_module',
                  f'set_condition T={temperature} P=101325 N=1 X(TI)={composition}',
                  'compute_equilibrium', 'list_equilibrium', f'point_{i}.txt', 'VXNSD',
                  'show_value GM NP(*) X(*,*)']
    macro_text = '\n'.join(lines + ['exit', ''])
    (out / 'input.tcm').write_text(macro_text, encoding='ascii')
    shutil.copyfile(source, out / 'model.tdb')
    timed_out = False
    with tempfile.TemporaryDirectory(prefix='seven_order_') as tmp:
        work = Path(tmp)
        scratch = work / 'scratch'
        scratch.mkdir()
        macro = work / 'input.tcm'
        macro.write_text(macro_text, encoding='ascii')
        shutil.copyfile(source, work / 'model.tdb')
        env = dict(os.environ, TC26B_HOME=str(thermocalc_home()), LSHOST='NO-NET',
                   LSERVRC=str(thermocalc_home() / 'lservrc'), TEMP=str(scratch), TMP=str(scratch))
        command = java_command(thermocalc_home(), macro)
        command.insert(1, '-Djava.io.tmpdir=' + str(scratch))
        si = hidden_startupinfo()
        with (out / 'raw.log').open('wb') as log:
            process = subprocess.Popen(command, cwd=work, env=env, stdin=subprocess.DEVNULL,
                                       stdout=log, stderr=subprocess.STDOUT, startupinfo=si)
            start = time.monotonic()
            done = None
            while process.poll() is None:
                raw = (out / 'raw.log').read_text(errors='replace')
                if 'Thermo-Calc completed normally' in raw:
                    done = done or time.monotonic()
                if done and time.monotonic() - done > 5:
                    process.kill()
                    break
                if time.monotonic() - start > 120:
                    timed_out = True
                    process.kill()
                    break
                time.sleep(.3)
            process.wait()
        for file in work.glob('point_*.txt'):
            shutil.copyfile(file, out / file.name)
    raw = (out / 'raw.log').read_text(errors='replace')
    diagnostics = [line for line in raw.splitlines() if re.search(
        r'\bERROR\b|Results may be wrong|NOT CONVERGED|NO CONVERGENCE|Ambiguous command', line, re.I)]
    accepted = not timed_out and not diagnostics and 'Thermo-Calc completed normally' in raw
    accepted &= all((out / f'point_{i}.txt').exists() for i in range(len(conditions)))
    result = {'conditions_T_K_X_Ti': conditions, 'accepted': accepted,
              'diagnostics': diagnostics, 'timed_out': timed_out,
              'model_sha256': hashlib.sha256(source.read_bytes()).hexdigest()}
    atomic_json(out / 'result.json', result)
    print(result)


if __name__ == '__main__':
    main()
