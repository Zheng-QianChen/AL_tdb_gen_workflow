"""Replay homogeneous single-phase seeds with installed Thermo-Calc Education.

Uses the bundled Java invocation observed from the official Education launcher,
including its `demo` argument and its unmodified, bundled local license. Each
seed reinitializes POLY; original author TDB bytes and physical parameters stay
unchanged. Java startup and the complete console transcript are retained.
"""
import argparse
import hashlib
import json
import math
import os
from pathlib import Path
import re
import subprocess
from examples.engine_runtime import hidden_startupinfo
import tempfile
import time

NUMBER = r"[-+]?(?:\d+\.?\d*|\.\d+)(?:[EeDd][-+]?\d+)?"


def audit_import(header):
    errors = [line.strip() for line in header.splitlines() if re.search(r'\bERROR\b|Errors have been detected', line, re.I)]
    known_metadata_fallback = ('Unknown phase name A2_B2 in assessed system: [Al, Fe]' in header
                               and 'previous version of the Gibbs Energy System, GES5' in header)
    def explained(line):
        if 'ERROR  1000 IN TDBGRT: NO REFERENCE FILE' in line:
            return True  # bibliography lookup, not a Gibbs parameter
        return known_metadata_fallback and any(s in line for s in (
            'Unknown phase name A2_B2 in assessed system: [Al, Fe]',
            'The database contains 1 errors', 'Errors have been detected in this database.'))
    return {'accepted_for_comparison': '-OK-' in header and all(explained(s) for s in errors),
            'GES': '5 (automatic metadata fallback)' if known_metadata_fallback else '6',
            'errors': errors, 'reference_file_missing': 'NO REFERENCE FILE' in header}


def parse_output(text, phase, composition, expected_sites):
    def number(value):
        return float(value.upper().replace("D", "E"))
    # GES v6 reports an order label on the same underlying TDB phase.
    aliases = {phase, *(phase+"_"+s for s in ("A1", "A2", "B2", "D03", "L10", "L12", "FP"))}
    gm = re.findall(r"\bGM=("+NUMBER+r")", text)
    amounts = [(p, number(n)) for p, n in re.findall(r"\bNP\(([^)]+)\)=("+NUMBER+r")", text)]
    active = [(p, n) for p, n in amounts if n > 1e-8]
    x = {c: number(v) for p, c, v in re.findall(
        r"\bX\(([^,]+),([^,)]+)\)=("+NUMBER+r")", text) if p in aliases}
    y = {f"Y_{int(i or 1)-1}_{c}": number(v) for p, c, i, v in re.findall(
        r"\bY\(([^,]+),([A-Z][A-Z0-9]*)(?:#(\d+))?\)=("+NUMBER+r")", text) if p in aliases}
    comp_error = max((abs(x[c]-v) for c, v in composition.items()), default=0) if x.keys() == composition.keys() else None
    groups = {}
    for key, value in y.items():
        groups.setdefault(key.split('_')[1], []).append(value)
    site_error = max((abs(sum(v)-1) for v in groups.values()), default=1)
    diagnostics = [line.strip() for line in text.splitlines() if re.search(
        r"\*\*\*|ERROR|FAILED|NO CONVERGENCE|MAXIMUM NUMBER OF ITERATIONS|IGNORED|NO SUCH COMMAND", line, re.I)]
    converged = bool(re.search(r"\d+ ITS,\s+CPU TIME USED", text)) and not diagnostics
    finite = bool(gm) and all(math.isfinite(v) for v in list(x.values())+list(y.values())+[number(gm[-1])])
    input_y = {f"Y_{int(i or 1)-1}_{c}": number(v) for p, c, i, v in re.findall(
        r"Y\(([^,]+),([A-Z][A-Z0-9]*)(?:#(\d+))?\)\s*/[^\n]*/:\s*\n\s*("+NUMBER+r")", text)}
    expected_free = {k: v for k, v in expected_sites.items()
                     if sum(other.split('_')[1] == k.split('_')[1] for other in expected_sites) > 1}
    input_valid = input_y.keys() == expected_free.keys() and all(
        abs(input_y[k]-v) < 1e-10 for k, v in expected_free.items())
    comparable = bool(converged and gm and finite and len(active) == 1
        and active[0][0] in aliases and abs(active[0][1]-1) < 1e-7
        and comp_error is not None and comp_error < 1e-7
        and input_valid and y.keys() == expected_sites.keys() and site_error < 1e-6
        and min(y.values(), default=-1) >= 0 and max(y.values(), default=2) <= 1)
    return {"converged": converged, "comparable": comparable, "G": number(gm[-1]) if gm else None,
            "active_phases": active, "X": x, "site_fractions_printed_precision": y,
            "max_composition_error": comp_error, "max_printed_site_sum_error": site_error,
            "input_site_fractions_verified": input_valid, "diagnostics": diagnostics[:30]}


def java_command(home, macro):
    jars = list(home.glob('gui-*.jar'))
    if len(jars) != 1:
        raise ValueError('Expected one installed Thermo-Calc GUI jar')
    args = [str(home/'bundled_jre'/'bin'/('java.exe' if os.name == 'nt' else 'java'))]
    args += ['--add-opens='+x+'=ALL-UNNAMED' for x in [
        'java.desktop/java.awt', 'java.desktop/java.awt.font', 'java.base/java.io',
        'java.base/java.lang', 'java.base/java.text', 'java.base/java.util']]
    return args+['--enable-native-access=ALL-UNNAMED', '-Djdk.xml.totalEntitySizeLimit=0',
        '-Djdk.xml.maxGeneralEntitySizeLimit=0', '-Dlog4j2.disable.jmx=true',
        '-Dfile.encoding=UTF-8', '-Xss2m', '-Xmx6G', '-XX:+UseG1GC',
        '-XX:MaxHeapFreeRatio=30', '-XX:MinHeapFreeRatio=10', '-Dshut.up.ojAlgo=true',
        '-Djogamp.gluegen.useTempJarCache=false', '-Dsun.java2d.opengl=false',
        '-Dsun.java2d.noddraw=true', '-jar', str(jars[0]), 'demo', str(macro), 'batch']


def macro_for(point, seeds):
    phase, comp = point['phase'], point['composition']
    lines = ['set-echo', 'go data', 'switch_database user model.tdb',
             'define_elements '+' '.join(comp), 'get_data', 'go p-3']
    for i, seed in enumerate(seeds):
        lines += ['reinitiate_module', 'change_status phase *=suspended',
                  f'change_status phase {phase}=entered 1',
                  f"set_condition T={point['T_K']:g} P={point['P_Pa']:g} N=1 "+' '.join(
                      f'X({c})={v:.16g}' for c, v in list(comp.items())[:-1]),
                  f'set_start_constitution {phase} NONE']
        # Thermo-Calc prompts only variable sublattices; pure VA is implicit.
        sites = seed['site_fractions']
        lines += [f'{v:.16g}' for k, v in sorted(sites.items())
                  if sum(other.split('_')[1] == k.split('_')[1] for other in sites) > 1]
        lines += ['compute_equilibrium -', 'list_equilibrium', f'equilibrium_{i:03d}.txt',
                  'VXNSD', f'show_value GM NP(*) X({phase},*) Y({phase},*)']
    return '\n'.join(lines+['exit', ''])


def run(folder, home, limit, case_filter):
    source = json.loads((folder/'pycalphad.json').read_text(encoding='utf-8'))
    result = {'engine': 'Thermo-Calc Education', 'version': '2026b (2026.2.201356-1197)',
              'directory': str(home), 'energy_unit': 'J/mol-atoms', 'cases': [],
              'protocol': 'original TDB; fresh POLY per seed; target phase only; COMPUTE_EQUILIBRIUM -; independent common seeds',
              'global_minimum_certified': False}
    for point in source['cases']:
        if case_filter and point['case'] != case_filter:
            continue
        dest = folder/point['case']/'thermocalc'
        dest.mkdir(exist_ok=True)
        seeds = json.loads((dest.parent/'independent_seeds.json').read_text(encoding='utf-8'))
        if limit:
            seeds = seeds[:limit]
        script = macro_for(point, seeds)
        (dest/'input.tcm').write_text(script, encoding='ascii')
        raw_tdb = Path(point['original_tdb']).read_bytes()
        if hashlib.sha256(raw_tdb).hexdigest() != point['tdb_sha256']:
            raise ValueError('Source TDB hash changed')
        with tempfile.TemporaryDirectory(prefix='tc_cross_') as temporary:
            work = Path(temporary)
            (work/'model.tdb').write_bytes(raw_tdb)
            macro = work/'input.tcm'
            macro.write_text(script, encoding='ascii')
            env = dict(os.environ, TC26B_HOME=str(home), LSHOST='NO-NET', LSERVRC=str(home/'lservrc'))
            si = hidden_startupinfo()
            with (dest/'raw.log').open('wb') as stream:
                process = subprocess.Popen(java_command(home, macro), cwd=work, env=env,
                    stdin=subprocess.DEVNULL, stdout=stream, stderr=subprocess.STDOUT, startupinfo=si)
                print(point['case'], 'PID', process.pid, flush=True)
                started, completed_at, stopped_after_completion = time.monotonic(), None, False
                while process.poll() is None:
                    observed = (dest/'raw.log').read_text(encoding='utf-8', errors='replace')
                    if 'Thermo-Calc completed normally' in observed and completed_at is None:
                        completed_at = time.monotonic()
                    # 2026b can leave the GUI waiting on its property-model messaging
                    # service after EXIT. Preserve calculation success separately from
                    # application shutdown; do not fabricate a zero return code.
                    if completed_at is not None and time.monotonic()-completed_at > 15:
                        stopped_after_completion = True
                        process.kill()
                        break
                    if time.monotonic()-started > 60+15*len(seeds):
                        process.kill()
                        break
                    time.sleep(.5)
                returncode = process.wait()
            # Only copy outputs from this fresh run, never consume stale files.
            outputs = {p.name: p.read_text(errors='replace') for p in work.glob('equilibrium_*.txt')}
            for name, contents in outputs.items():
                (dest/name).write_text(contents, encoding='utf-8')
        raw = (dest/'raw.log').read_text(encoding='utf-8', errors='replace')
        blocks = re.split(r'(?m)^reinitiate_module\s*$', raw.replace('\r', ''))[1:]
        import_audit = audit_import(raw.split('reinitiate_module', 1)[0])
        item = {'case': point['case'], 'tdb_sha256': point['tdb_sha256'], 'returncode': returncode,
                'stopped_after_normal_macro_completion': stopped_after_completion,
                'import_audit': import_audit,
                'G_local': point['G_local'], 'G_Pandat': point['G_Pandat'], 'runs': [],
                'import_diagnostics': [s.strip() for s in raw.split('reinitiate_module', 1)[0].splitlines()
                                       if re.search('missing|warn|error|ignored', s, re.I)]}
        for i, seed in enumerate(seeds):
            parsed = parse_output(blocks[i] if i < len(blocks) else '', point['phase'],
                                  point['composition'], seed['site_fractions'])
            parsed.update(seed=seed['name'], equilibrium_file=f'equilibrium_{i:03d}.txt')
            parsed['comparable'] &= bool(import_audit['accepted_for_comparison']
                                          and (returncode == 0 or stopped_after_completion)
                                          and 'Thermo-Calc completed normally' in raw
                                          and parsed['equilibrium_file'] in outputs)
            item['runs'].append(parsed)
        accepted = [r for r in item['runs'] if r['comparable']]
        item.update(attempts=len(seeds), accepted=len(accepted),
                    best=min(accepted, key=lambda r: r['G']) if accepted else None)
        result['cases'].append(item)
        (folder/'thermocalc.json').write_text(json.dumps(result, indent=2, ensure_ascii=False, allow_nan=False), encoding='utf-8')
        print(point['case'], 'accepted', len(accepted), 'best', item['best']['G'] if item['best'] else None, flush=True)
    return result


def reparse(folder):
    """Re-audit saved native logs without requiring an installed/licenseable engine."""
    result = json.loads((folder/'thermocalc.json').read_text(encoding='utf-8'))
    points = {p['case']: p for p in json.loads((folder/'pycalphad.json').read_text(encoding='utf-8'))['cases']}
    for item in result['cases']:
        point = points[item['case']]
        dest = folder/item['case']/'thermocalc'
        seeds = {s['name']: s for s in json.loads((dest.parent/'independent_seeds.json').read_text(encoding='utf-8'))}
        raw = (dest/'raw.log').read_text(encoding='utf-8', errors='replace').replace('\r', '')
        blocks = re.split(r'(?m)^reinitiate_module\s*$', raw)[1:]
        item['import_audit'] = audit_import(raw.split('reinitiate_module', 1)[0])
        for i, previous in enumerate(item['runs']):
            parsed = parse_output(blocks[i] if i < len(blocks) else '', point['phase'], point['composition'],
                                  seeds[previous['seed']]['site_fractions'])
            parsed.update(seed=previous['seed'], equilibrium_file=previous['equilibrium_file'])
            parsed['comparable'] &= bool(item['import_audit']['accepted_for_comparison']
                and (item['returncode'] == 0 or item.get('stopped_after_normal_macro_completion', False))
                and 'Thermo-Calc completed normally' in raw and (dest/parsed['equilibrium_file']).is_file()
                and i < len(blocks) and f"\n{parsed['equilibrium_file']}\n" in blocks[i])
            item['runs'][i] = parsed
        accepted = [r for r in item['runs'] if r['comparable']]
        item.update(accepted=len(accepted), best=min(accepted, key=lambda r: r['G']) if accepted else None)
        print(item['case'], 'audited', item['accepted'], '/', item['attempts'], item['import_audit']['GES'])
    (folder/'thermocalc.json').write_text(json.dumps(result, indent=2, ensure_ascii=False, allow_nan=False), encoding='utf-8')
    return result


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('folder', type=Path)
    parser.add_argument('--home', type=Path, default=Path(os.environ.get('LOCALAPPDATA', ''))/'Programs/Thermo-Calc-educational/2026b')
    parser.add_argument('--limit', type=int, default=0)
    parser.add_argument('--case', default='')
    parser.add_argument('--reparse', action='store_true', help='Audit saved native logs without rerunning Thermo-Calc')
    args = parser.parse_args()
    if args.reparse:
        reparse(args.folder)
    else:
        run(args.folder, args.home.resolve(), args.limit, args.case)
