"""Native Pandat binary sections for the frozen user V6 source."""
from pathlib import Path
import argparse
import hashlib
import itertools
import json
import shutil
import time
import xml.etree.ElementTree as ET

from examples.seven_binary_validation import FOLDER, ELEMENTS, binary_text
from examples.pandat_batch import run_document
from examples.pandat_tdb import pandat_text
from src.gibbs import read_databases
from src.storage import atomic_json

from examples.engine_runtime import pandat_executable
MELTING = dict(CO=1768, CU=1357.77, FE=1811, NI=1728, TA=3290, TI=1941, W=3695)


def portable(pair, serialize=True):
    from symengine import Symbol
    folder = FOLDER / 'binary_inputs' / '-'.join(pair)
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / 'model.tdb'
    path.write_text(binary_text(pair), encoding='utf-8')
    db, _ = read_databases([str(path)])
    needed, todo = set(), set(str(s) for p in db._parameters.all() for s in p['parameter'].free_symbols)-{'T', 'P'}
    while todo:
        name = todo.pop()
        if name in needed:
            continue
        needed.add(name)
        todo.update(str(s) for s in db.symbols[name].free_symbols if str(s) not in needed | {'T', 'P'})
    db.symbols = {k: v for k, v in db.symbols.items() if k in needed}
    renames = {k: f'F{i:06d}' for i, k in enumerate(sorted(db.symbols)) if len(k) > 8}
    subs = {Symbol(k): Symbol(v) for k, v in renames.items()}
    db.symbols = {renames.get(k, k): v.xreplace(subs) for k, v in db.symbols.items()}
    for par in db._parameters.all():
        db._parameters.update({'parameter': par['parameter'].xreplace(subs)}, doc_ids=[par.doc_id])
    if not serialize:
        return path, db, {'pair':pair,'source_sha256':hashlib.sha256((FOLDER/'source_v6.tdb').read_bytes()).hexdigest(),
                          'function_renames':renames,'parameter_count':len(db._parameters.all()),
                          'phases':list(db.phases),'missing_endmembers_filled':False,
                          'duplicate_parameters_resolved':False}
    text = pandat_text(db)
    dest = folder / 'portable.tdb'
    dest.write_text(text, encoding='utf-8')
    # Round-trip audit of every explicit parameter, including duplicate multiplicity.
    reread, _ = read_databases([str(dest)])
    def snapshot(database):
        return sorted((p['phase_name'], p['parameter_type'], str(p['constituent_array']),
                       p['parameter_order'], str(p['parameter'])) for p in database._parameters.all())
    same = snapshot(db) == snapshot(reread)
    if not same:
        raise ValueError('Portable parameter round-trip differs')
    audit = {'pair': pair, 'source_sha256': hashlib.sha256((FOLDER/'source_v6.tdb').read_bytes()).hexdigest(),
             'portable_sha256': hashlib.sha256(dest.read_bytes()).hexdigest(), 'function_renames': renames,
             'parameter_roundtrip_identical': same, 'parameter_count': len(db._parameters.all()),
             'phases': list(db.phases), 'missing_endmembers_filled': False,
             'duplicate_parameters_resolved': False}
    atomic_json(folder / 'portable_audit.json', audit)
    return dest, db, audit


def document(pair, phases, low, high):
    root = ET.Element('pbfx', version='1.0')
    ET.SubElement(ET.SubElement(root, 'Header'), 'Application', name='Pandat', version='2022')
    calc = ET.SubElement(root, 'calculation', name='point_0', type='section')
    ET.SubElement(ET.SubElement(calc, 'databases'), 'database', type='tdb', file_name='model.tdb')
    units = ET.SubElement(calc, 'units')
    for k, val in [('T', 'K'), ('P', 'atm'), ('n', 'mole')]:
        ET.SubElement(units, 'unit', name=k, value=val)
    system = ET.SubElement(calc, 'system', name='Default_System')
    components = ET.SubElement(system, 'components')
    for el in pair:
        ET.SubElement(components, 'component', name=el, status='Selected')
    phase_list = ET.SubElement(system, 'phases')
    ET.SubElement(phase_list, 'phase', name='*', status='suspend', type='')
    for phase in phases:
        ET.SubElement(phase_list, 'phase', name=phase, status='restore', type='')
    points = ET.SubElement(system, 'points')
    for temperature, x in [(high, 0), (low, 0), (low, 1)]:
        state = ET.SubElement(ET.SubElement(points, 'point'), 'statespace')
        ET.SubElement(state, 'T', value=str(temperature))
        ET.SubElement(state, 'P', value='1')
        for el, val in zip(pair, [1-x, x]):
            ET.SubElement(state, 'n', component=el, value=str(val))
    cond = ET.SubElement(system, 'condition')
    ET.SubElement(cond, 'equilibrium_type', type='global')
    ET.SubElement(cond, 'scanline_density', value='8')
    tables = ET.SubElement(ET.SubElement(calc, 'output', unit=''), 'tables')
    for name, kind, columns in [('point_0.dat','Default',['T','x(*)','phase_name','f(@*)','G','x(*@*)']),
                                ('tielines.dat','tieline',['T','x(*)','phase_name']),
                                ('invariants.dat','invariant',['T','x(*)','phase_name']),
                                ('invariant_tielines.dat','invariant_tieline',['T','x(*)','phase_name'])]:
        table = ET.SubElement(tables, 'table', name=name, source='Default', type=kind)
        for col in columns:
            ET.SubElement(table, 'column', name=col)
    ET.indent(root, space='  ')
    return ET.tostring(root, encoding='unicode')


def run(selected=None):
    summary = {'source_sha256': hashlib.sha256((FOLDER/'source_v6.tdb').read_bytes()).hexdigest(),
               'scope': ELEMENTS, 'engine': 'Pandat 2022a Education', 'pressure_Pa': 101325,
               'source_parameters_refitted': False, 'cases': []}
    for pair in itertools.combinations(ELEMENTS, 2):
        name = '-'.join(pair)
        if selected and name not in selected:
            continue
        start = time.monotonic()
        item = {'pair': name}
        print('START', name, flush=True)
        try:
            source, db, audit = portable(pair)
            # Cu solid/liquid reference functions stop at 3200 K; avoid extrapolation there.
            upper = min(max(MELTING[el] for el in pair)+200, 3199 if 'CU' in pair else 3999)
            folder = FOLDER / 'native_sections' / name
            folder.mkdir(parents=True, exist_ok=True)
            if (folder/'raw').exists():
                raise ValueError('Existing evidence folder; do not overwrite')
            shutil.copyfile(source, folder/'model.tdb')
            doc = document(pair, list(db.phases), 300, upper)
            item.update(temperature_range_K=[300, upper], portable_audit=audit, folder=str(folder))
            execution = run_document(pandat_executable(), folder, doc, 1, timeout=240)
            item.update(status='native_output_created', execution=execution)
        except Exception as exc:
            item.update(status='error', error=f'{type(exc).__name__}: {exc}')
        item['seconds'] = round(time.monotonic()-start, 2)
        summary['cases'].append(item)
        atomic_json(FOLDER / ('native_summary' + ('_'+'_'.join(selected) if selected else '') + '.json'), summary)
        print(json.dumps(item, ensure_ascii=False), flush=True)
    return summary


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--pairs', nargs='*')
    args = parser.parse_args()
    run(args.pairs)
