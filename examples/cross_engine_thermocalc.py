"""Prepare a single-point macro and read Thermo-Calc output."""
import math
import os
import re

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
