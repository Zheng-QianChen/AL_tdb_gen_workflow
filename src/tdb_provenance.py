"""Traceable TDB command scanning and explicit Thermo-Calc dialect preparation.

Reference lists are added after conversion; they never pass through a writer
which discards bibliography metadata. No parameter is selected or refitted here.
"""
import hashlib
import math
import re
import textwrap
import unicodedata
from collections import defaultdict


def parameter_key(record):
    groups = ':'.join(','.join(sorted(s.name for s in group)) for group in record['constituent_array'])
    return f"{record['parameter_type']}({record['phase_name']},{groups};{record['parameter_order']})"


def canonical_command_key(info):
    groups = ':'.join(','.join(sorted(group.split(','))) for group in info['constituents'].split(':'))
    return f"{info['parameter_type']}({info['phase']},{groups};{info['order']})"


def references(text):
    """Read inline bibliographies without assigning a publication to a parameter."""
    result = {}
    for command in commands(text):
        if command['text'].split()[0].upper() not in {'LIST_OF_REFERENCES', 'ADD_REFERENCES'}:
            continue
        for code, citation in re.findall(r"([\w:.-]+)\s+'([^']*)'", command['text'], re.S):
            citation = ' '.join(citation.split())
            if code in result and result[code] != citation:
                raise ValueError(f'Conflicting bibliography entry: {code}')
            result[code] = citation
    return result


def function_context(db, expression):
    """Snapshot the transitive function definitions used by a coefficient."""
    pending = [str(s) for s in expression.free_symbols]
    definitions = {}
    while pending:
        name = pending.pop()
        if name in definitions or name not in db.symbols:
            continue
        value = db.symbols[name]
        definitions[name] = str(value)
        pending.extend(str(s) for s in value.free_symbols)
    return tuple(sorted(definitions.items()))


def capture_references(db, texts, sources):
    """Restore metadata discarded by pycalphad's TDB parser.

    Store it on parameter records so restrictions and database copies retain it.
    Conflicting source codes receive independent portable reference identifiers.
    """
    entries = dict(db.references)
    by_key = defaultdict(set)
    for text, source in zip(texts, sources):
        bibliography = references(text)
        for command in commands(text):
            info = parameter_info(command['text'])
            if not info:
                continue
            original = info['original_reference']
            citation = bibliography.get(original)
            if citation is None:
                citation = (f"UNRESOLVED SOURCE. Input {source['sha256']}; "
                            f"original reference {original or 'absent'}. Bibliography unavailable.")
                if command['following_comment']:
                    citation += ' Authored comment (unverified): ' + command['following_comment']
            code = original
            if (not re.fullmatch(r'[A-Z][A-Z0-9]{0,7}', code) or
                    code in entries and entries[code] != citation):
                code = next((key for key, value in entries.items() if value == citation), None)
                if code is None:
                    number = len(entries) + 1
                    while f'ZQR{number:05d}' in entries:
                        number += 1
                    code = f'ZQR{number:05d}'
            entries[code] = citation
            by_key[canonical_command_key(info)].add(code)
    for row in db._parameters.all():
        codes = sorted(by_key.get(parameter_key(row), ()))
        if len(codes) == 1:
            code = codes[0]
        else:
            number = len(entries) + 1
            while f'ZQR{number:05d}' in entries:
                number += 1
            code = f'ZQR{number:05d}'
            entries[code] = ('Combined input provenance: ' + ' | '.join(entries[c] for c in codes)
                             if codes else 'UNRESOLVED SOURCE. Reader-generated parameter; no direct authored reference.')
        db._parameters.update(dict(reference=code, source_parameter=row['parameter'],
                                   source_function_context=function_context(db, row['parameter'])),
                              doc_ids=[row.doc_id])
    db.references = entries


def export_references(text, db):
    """Attach references after numerical serialization and label modified values."""
    if not db.references:
        return text
    entries = {}
    by_key = {}
    for row in db._parameters.all():
        code = row.get('reference')
        if code not in db.references:
            code = 'ZQUNKN'
            citation = 'UNRESOLVED SOURCE. This parameter has no registered source reference.'
        else:
            citation = db.references[code]
        source_expression = row.get('source_parameter')
        if source_expression is not None and (
                (source_expression-row['parameter']).simplify() != 0 or
                row['source_function_context'] != function_context(db, row['parameter'])):
            citation = ('LOCAL MODIFICATION. Coefficient or dependent function changed after input. '
                        f'Parent reference {code}: {citation} Consult the fit request and result ledger.')
            code = next((key for key, value in entries.items() if value == citation), None)
            if code is None:
                code = f'ZQM{len(entries)+1:05d}'
                while code in entries or code in db.references:
                    code = f'ZQM{int(code[3:])+1:05d}'
        entries[code] = citation
        key = parameter_key(row)
        if key in by_key and by_key[key] != code:
            raise ValueError(f'Conflicting parameter provenance: {key}')
        by_key[key] = code
    replacements = []
    for command in commands(text):
        info = parameter_info(command['text'])
        if info:
            replacements.append((command['start'], command['end'],
                                 info['body'] + ' ' + by_key[info['key']] + ' !'))
    for start, end, replacement in reversed(replacements):
        text = text[:start] + replacement + text[end:]
    from pycalphad.io.tdb import reflow_text
    return reflow_text(text, linewidth=78) + '\n\n' + reference_block(entries) + '\n'


def commands(text):
    masked = re.sub(r'\$[^\r\n]*', lambda m: ' ' * len(m[0]), text)
    start = 0
    for end in (m.start() for m in re.finditer('!', masked)):
        raw = masked[start:end]
        if raw.strip():
            begin = start + len(raw) - len(raw.lstrip())
            # A short comment immediately after this command is an authored
            # provenance hint, not an instruction and not a verified citation.
            tail = text[end+1:]
            hint = re.match(r'^\s*\$\s*([^\r\n]+)', tail)
            yield dict(text=raw.strip(), start=begin, end=end+1,
                       line=text.count('\n', 0, begin)+1,
                       following_comment=hint[1].strip() if hint else '')
        start = end + 1


def parameter_info(command):
    m = re.match(r'PARAMETER\s+(\w+)\(\s*([^,]+),([^;)]+)(?:;\s*(\d+))?\)', command, re.I)
    if not m:
        return None
    tail = re.search(r'\bN\s*(\S*)\s*$', command, re.I)
    body = command[:tail.start(1)] if tail and tail[1] else command
    elements = sorted(set(re.findall(r'[A-Z][A-Z]?', m[3].upper())) - {'VA'})
    return dict(key=re.sub(r'\s+', '', m[0][len('PARAMETER'):]).upper(),
                phase=m[2].upper(), parameter_type=m[1].upper(), order=int(m[4] or 0),
                constituents=m[3].upper(), system='-'.join(elements),
                original_reference=tail[1] if tail else '',
                body=body.rstrip(),
                expression_key=hashlib.sha256(re.sub(r'\s+', '', body).upper().encode()).hexdigest())


def portable_commands(text):
    """Return calculation commands + conversion audit, preserving duplicates.

OPTIMIZATION bounds belong to fitting; the stored value becomes a constant.
Unused phase type declarations are omitted, not model definitions. Known
literal +05 is read as +5, not guessed to mean E+05.
"""
    from pycalphad.io.tdb import _tdb_grammar, TCPrinter
    from symengine import Piecewise, RealDouble, E
    raw = list(commands(text))
    phases = {c['text'].split()[1].upper() for c in raw if c['text'].upper().startswith('PHASE ')}
    functions = {c['text'].split()[1].upper() for c in raw if re.match(r'(FUNCTION|OPTIMIZATION)\s',c['text'], re.I)}
    aliases = {}
    for i, name in enumerate(sorted(functions)):
        if len(name) > 8:
            new = 'ZQF%05d' % i
            if new in functions:
                raise ValueError('Function alias collision')
            aliases[name] = new
    audit = {'function_aliases': aliases, 'frozen_optimization': [], 'omitted_unused_types': [],
             'expression_roundtrip': [], 'duplicate_parameters_resolved': False,
             'omitted_empty_if_type_codes': []}
    empty_types={c['text'].split()[1] for c in raw if re.fullmatch(r'TYPE_DEFINITION\s+\S+\s+IF',c['text'],re.I)}
    parser = _tdb_grammar()
    def expand(expr):
        expr = expr.xreplace({RealDouble(math.e): E})
        if isinstance(expr, Piecewise):
            return Piecewise(*[(expand(expr.args[i]), expr.args[i+1]) for i in range(0,len(expr.args),2)])
        return expr.expand()
    results=[]
    if not any(re.match(r'TYPE_DEFINITION\s+%\s',c['text'],re.I) for c in raw):
        results.append(dict(text='TYPE_DEFINITION % SEQ *',portable='TYPE_DEFINITION % SEQ *',line=None,following_comment=''))
        audit['added_default_type_definition']='TYPE_DEFINITION % SEQ *'
    for item in raw:
        c=' '.join(item['text'].split()).upper()
        kind=c.split()[0].upper()
        if kind in ('LIST_OF_REFERENCES','LIST_OF_REFERENCE','ADD_REFERENCES','REFERENCE_FILE'):
            continue
        if kind=='OPTIMIZATION':
            m=re.fullmatch(r'OPTIMIZATION\s+(\S+)\s+(\S+)\s+(\S+)\s*;\s*(\S+)\s+N',c,re.I)
            if not m:raise ValueError('Unknown OPTIMIZATION format')
            audit['frozen_optimization'].append(dict(name=m[1],lower_bound=m[2],value=m[3],upper_bound=m[4]))
            c='FUNCTION {} 0 {}; 10000 N'.format(m[1],m[3]);kind='FUNCTION'
        if kind=='TYPE_DEFINITION':
            if re.fullmatch(r'TYPE_DEFINITION\s+\S+\s+IF',c,re.I):
                audit['omitted_empty_if_type_codes'].append(c);continue
            m=re.search(r'AMEND_PHASE_DESCRIPTION\s+(\S+)',c,re.I)
            if m and m[1].upper() not in phases:
                audit['omitted_unused_types'].append(c);continue
            c=c.replace('DISORDER_PART','DISORDERED_PART')
        if kind=='PHASE' and empty_types:
            parts=c.split();parts[2]=''.join(ch for ch in parts[2] if ch not in empty_types);c=' '.join(parts)
        if kind in ('FUNCTION','PARAMETER'):
            c=c.replace('4.910251+05*T**(-1)','4.910251+5*T**(-1)')
            for old,new in aliases.items():
                c=re.sub(r'\b'+re.escape(old)+r'\b',new,c,flags=re.I)
            parsed=parser.parse_string(c,parse_all=True)
            original=parsed[-1]
            expanded=expand(original)
            body=TCPrinter(if_incompatible='raise').doprint(expanded).upper().replace('LOG(', 'LN(')
            head=re.match(r'(FUNCTION\s+\S+|PARAMETER\s+[^)]+\))',c,re.I)[0]
            c=head+' '+body
            for f in sorted((aliases.get(f,f) for f in functions),key=len,reverse=True):
                # Only the expression, never FUNCTION declaration names.
                h,b=c[:len(head)],c[len(head):]
                c=h+re.sub(r'\b'+re.escape(f)+r'\b(?!#)',f+'#',b,flags=re.I)
            reread=parser.parse_string(c,parse_all=True)[-1]
            # Algebraic comparison plus evaluation across temperature pieces.
            symbols=sorted(original.free_symbols|reread.free_symbols,key=str)
            maximum=0.0
            for temp in (0.01,298.15,300,500,1000,1500,2500,3000,5000,9000):
                values={s:(temp if str(s)=='T' else 101325 if str(s)=='P' else 100.0+i) for i,s in enumerate(symbols)}
                a,b=float(original.subs(values)),float(reread.subs(values))
                maximum=max(maximum,abs(a-b))
                if not math.isclose(a,b,rel_tol=1e-12,abs_tol=1e-7):
                    raise ValueError('Expression conversion failed at '+head)
            audit['expression_roundtrip'].append(dict(command=head,max_abs_sample_difference=maximum))
        results.append(dict(item,portable=c))
    return results,audit


def reference_block(entries):
    lines=['LIST_OF_REFERENCES', ' NUMBER SOURCE']
    blocks=[]
    size=sum(map(len,lines))
    for code, text in entries.items():
        if not re.fullmatch(r'[A-Z][A-Z0-9]{0,7}',code):
            raise ValueError('Invalid reference code')
        text=text.translate(str.maketrans({'–':'-','—':'-','−':'-','’':"'",'‘':"'",'“':'"','”':'"','µ':'mu','α':'alpha','β':'beta','γ':'gamma'}))
        text=unicodedata.normalize('NFKD',text).encode('ascii','replace').decode().replace("'",'`').replace('!','.').replace('$',' ')
        content=' '.join(text.split())
        entry=textwrap.fill(code+" '"+content+"'",width=77,subsequent_indent='    ',break_long_words=True,break_on_hyphens=False)
        if len(entry)>7000:
            raise ValueError('One reference exceeds portable command size')
        # Native 2026b USER import enforces ~10k per command even though the
        # manual gives a larger LIST_OF_REFERENCES limit. ADD_REFERENCES is
        # the documented way to retain every entry across smaller commands.
        if size+len(entry)>7500:
            blocks.append('\n'.join(lines+['!']))
            lines=['ADD_REFERENCES', "DMP%05d 'Empty reference separator'" % len(blocks)]
            size=sum(map(len,lines))
        lines.append(entry);size+=len(entry)+1
    lines.append('!')
    blocks.append('\n'.join(lines))
    return '\n\n'.join(blocks)
