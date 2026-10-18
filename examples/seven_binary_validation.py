"""Reproducible audit of the user-selected V6 database; never edits the source."""
from pathlib import Path
import hashlib
import os
import itertools
import json
import re

ROOT = Path(__file__).resolve().parents[1]
FOLDER = Path(os.environ.get('AL_TDB_STUDY_DIR', ROOT / 'data/seven_element_validation_20261018')).expanduser().resolve()
ELEMENTS = ['CO', 'CU', 'FE', 'NI', 'TA', 'TI', 'W']


def prepare():
    source = FOLDER / 'source_v6.tdb'
    text = source.read_text(encoding='utf-8-sig')
    changes = []
    def freeze(match):
        changes.append({'type': 'freeze_optimization', 'name': match[1],
                        'lower_fit_bound': match[2], 'value': match[3], 'upper_fit_bound': match[4]})
        return f'FUNCTION {match[1]} 0 {match[3]}; 10000 N !'
    text = re.sub(r'(?im)^\s*OPTIMIZATION\s+(\S+)\s+([+-]?[\d.eE]+)\s+([+-]?[\d.eE]+)\s*;\s*([+-]?[\d.eE]+)\s+N\s*!', freeze, text)
    old = '4.910251+05*T**(-1)'
    if old in text:
        text = text.replace(old, '4.910251+5*T**(-1)')
        changes.append({'type': 'literal_integer_lexing', 'before': old,
                        'after': '4.910251+5*T**(-1)',
                        'warning': 'Preserves literal arithmetic; does NOT assume missing scientific-notation E.'})
    phases = set(re.findall(r'(?im)^\s*PHASE\s+(\S+)', text))
    def unused(match):
        if match[1] not in phases:
            changes.append({'type': 'unused_type_definition', 'original': match[0].strip()})
            return '$ omitted unused declaration: ' + match[0].strip()
        return match[0]
    text = re.sub(r'(?im)^\s*TYPE_DEFINITION\s+\S+\s+GES\s+AMEND_PHASE_DESCRIPTION\s+(\S+)[^!]*!', unused, text)
    out = FOLDER / 'calculation_v6.tdb'
    out.write_text(text, encoding='utf-8')
    record = {'source': str(source), 'source_sha256': hashlib.sha256(source.read_bytes()).hexdigest(),
              'calculation_sha256': hashlib.sha256(out.read_bytes()).hexdigest(), 'changes': changes}
    (FOLDER / 'parser_normalization.json').write_text(json.dumps(record, ensure_ascii=False, indent=2), encoding='utf-8')
    return out


def inspect():
    from src.gibbs import read_databases, phase_parameters
    from pycalphad.core.utils import filter_phases
    db, sources = read_databases([str(prepare())])
    report = {'sources': sources, 'phases': {name: {'sites': phase.sublattices, 'hints': phase.model_hints,
              'constituents': [sorted(s.name for s in site) for site in phase.constituents]}
              for name, phase in db.phases.items()}, 'binaries': []}
    for pair in itertools.combinations(ELEMENTS, 2):
        components = list(pair) + ['VA']
        active = filter_phases(db, components)
        problems = {}
        for name in active:
            phase = db.phases[name]
            groups = [sorted(s.name for s in site if s.name in components) for site in phase.constituents]
            try:
                phase_parameters(db, name, groups, allow_missing='ordered_phase' in phase.model_hints)
            except ValueError as exc:
                problems[name] = str(exc)
        report['binaries'].append({'components': pair, 'phases': active, 'problems': problems})
    (FOLDER / 'database_audit.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps(report, ensure_ascii=False, indent=2))


def binary_text(pair):
    """Exact zero-other-component restriction; preserve duplicate definitions and literal expressions."""
    text = prepare().read_text(encoding='utf-8')
    text = re.sub(r'(?m)^\s*\$[^\n]*', '', text)
    commands = [c.strip() for c in text.split('!') if c.strip()]
    components = set(pair) | {'VA'}
    allowed = {}
    for c in commands:
        m = re.match(r'CONSTITUENT\s+(\S+)\s*:(.*):\s*$', c, re.I | re.S)
        if m:
            groups = [[s.strip() for s in group.split(',') if s.strip() in components] for group in m[2].split(':')]
            if all(groups):
                allowed[m[1]] = groups
    result = []
    for c in commands:
        kind = c.split()[0].upper()
        if kind == 'ELEMENT' and c.split()[1] not in components:
            continue
        if kind == 'PHASE' and c.split()[1] not in allowed:
            continue
        if kind == 'CONSTITUENT':
            name = c.split()[1]
            if name not in allowed:
                continue
            c = f"CONSTITUENT {name} :" + ':'.join(','.join(g) for g in allowed[name]) + ':'
        if kind == 'TYPE_DEFINITION':
            m = re.search(r'AMEND_PHASE_DESCRIPTION\s+(\S+)', c, re.I)
            if m and m[1] not in allowed:
                continue
        if kind == 'PARAMETER':
            m = re.match(r'PARAMETER\s+\w+\(\s*([^,]+),([^)]*)\)', c, re.I)
            if not m:
                raise ValueError('Unrecognized parameter command: ' + c[:100])
            species = re.split(r'[:,]', m[2].split(';')[0])
            if m[1] not in allowed or not all(s.strip() in components | {'*'} for s in species):
                continue
        result.append(c + ' !')
    return '\n\n'.join(result) + '\n'


if __name__ == '__main__':
    inspect()
