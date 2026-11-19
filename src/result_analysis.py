"""Parse calculation settings and convergence evidence from VASP outputs.

Timing fields are null when unknown; never invent a zero fallback.
Machine credentials are never stored — only allowlisted scientific settings.
"""
from __future__ import annotations

import hashlib
import math
import re
from pathlib import Path

# Scientific INCAR tags safe to surface in records / UI.
INCAR_ALLOWLIST = frozenset({
    "ADDGRID", "ALGO", "AMIN", "AMIX", "AMIX_MAG", "BMIX", "BMIX_MAG", "EDIFF",
    "EDIFFG", "ENAUG", "ENCUT", "ENCUTFOCK", "GGA", "IBRION", "ISIF", "ISMEAR",
    "ISPIN", "ISTART", "ISYM", "IVDW", "KGAMMA", "KSPACING", "LASPH", "LDAU",
    "LDAUJ", "LDAUL", "LDAUU", "LMAXMIX", "LORBIT", "LREAL", "LWAVE", "LCHARG",
    "MAGMOM", "METAGGA", "NBANDS", "NELM", "NELMIN", "NWRITE", "NSW", "PREC",
    "POTIM", "SIGMA", "SYMPREC", "VOSKOWN",
})

INPUT_HASH_NAMES = ("INCAR", "POTCAR", "KPOINTS", "POSCAR")


def file_sha256(path):
    path = Path(path)
    if not path.is_file():
        return None
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _finite_or_none(value):
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def parse_incar_text(text):
    """Return allowlisted INCAR parameters; unknown/secret keys are dropped."""
    from pymatgen.io.vasp.inputs import Incar
    raw = Incar.from_str(text)
    parsed = {}
    for key, value in raw.items():
        name = str(key).upper()
        if name not in INCAR_ALLOWLIST:
            continue
        if hasattr(value, "tolist"):
            value = value.tolist()
        parsed[name] = value
    return parsed


def parse_incar_file(path):
    path = Path(path)
    if not path.is_file():
        return {}
    return parse_incar_text(path.read_text(encoding="utf-8", errors="replace"))


def _parse_kpoints_file(path):
    path = Path(path)
    if not path.is_file():
        return None
    try:
        from pymatgen.io.vasp.inputs import Kpoints
        kpoints = Kpoints.from_file(path)
        payload = {"style": str(kpoints.style), "num_kpts": int(kpoints.num_kpts or 0)}
        if kpoints.kpts is not None:
            payload["kpts"] = [list(map(float, row)) for row in kpoints.kpts]
        if kpoints.kpts_shift is not None:
            payload["shift"] = [float(v) for v in kpoints.kpts_shift]
        return payload
    except Exception:
        return {"raw_sha256": file_sha256(path)}


def _scan_outcar_text(text):
    version = None
    match = re.search(r"vasp\.([\d.]+)", text, re.IGNORECASE)
    if match:
        version = match.group(1)

    warnings = []
    for line in text.splitlines():
        stripped = line.strip()
        if re.search(r"\bWWWW\b|\bWARNING\b", stripped, re.IGNORECASE):
            if stripped and stripped not in warnings:
                warnings.append(stripped[:500])
                if len(warnings) >= 50:
                    break

    elapsed = None
    cpu = None
    for pattern, target in (
        (r"Elapsed time \(sec\):\s*([0-9.Ee+-]+)", "elapsed"),
        (r"Total CPU time used \(sec\):\s*([0-9.Ee+-]+)", "cpu"),
        (r"Total CPU time used:\s*([0-9.Ee+-]+)", "cpu"),
    ):
        found = re.search(pattern, text)
        if not found:
            continue
        value = _finite_or_none(found.group(1))
        if target == "elapsed":
            elapsed = value
        else:
            cpu = value

    finished = "General timing and accounting" in text
    ionic_converged = "reached required accuracy" in text
    toten_count = len(re.findall(r"free\s+energy\s+TOTEN\s*=", text))
    energy = None
    energies = re.findall(r"free\s+energy\s+TOTEN\s*=\s*([-+0-9.Ee]+)", text)
    if energies:
        energy = _finite_or_none(energies[-1])

    # A timing footer proves termination, not SCF convergence. Only the final
    # electronic loop is relevant: an earlier ionic step may have converged.
    loops = list(re.finditer(r'Iteration\s+(\d+)\(\s*(\d+)\)', text))
    final_loop = text[loops[-1].start():] if loops else text
    electronic_steps = int(loops[-1].group(2)) if loops else None
    effective = {}
    for key in ('ENCUT', 'EDIFF', 'EDIFFG', 'NELM', 'NSW', 'IBRION', 'ISIF',
                'ISMEAR', 'SIGMA', 'ISPIN', 'NBANDS', 'NELECT', 'KSPACING'):
        found = re.search(r'\b' + key + r'\s*=\s*([-+\d.]+(?:[EeDd][-+]?\d+)?)', text)
        if found:
            value = _finite_or_none(found.group(1).replace('D', 'E').replace('d', 'e'))
            if value is not None:
                effective[key] = value
    electronic_converged = None
    if re.search(r'aborting loop because EDIFF is reached', final_loop, re.I):
        electronic_converged = True
    elif re.search(r'EDIFF (?:was|is) not reached', final_loop, re.I):
        electronic_converged = False
    elif electronic_steps is not None and effective.get('NELM') is not None:
        if electronic_steps >= effective['NELM']:
            electronic_converged = False

    kpoints = None
    grid = re.search(
        r"generate k-points.*?(\d+)\s+irreducible",
        text, re.IGNORECASE | re.DOTALL)
    nkpts = re.search(r"k-points in BZ\s*NKPTS\s*=\s*(\d+)", text, re.IGNORECASE)
    if nkpts:
        kpoints = {"nkpts": int(nkpts.group(1))}
    elif grid:
        kpoints = {"irreducible": int(grid.group(1))}

    return {
        "vasp_version": version,
        "elapsed_seconds": elapsed,
        "cpu_seconds": cpu,
        "electronic_converged": electronic_converged,
        "electronic_steps_final": electronic_steps,
        "effective_settings": effective,
        "ionic_converged": ionic_converged if finished else None,
        "final_energy_definition": "free_energy_TOTEN",
        "ionic_steps": toten_count if toten_count else None,
        "energy_ev_cell": energy,
        "finished": finished,
        "warnings": warnings,
        "kpoints": kpoints,
    }


def analyze_outcar(path, incar=None):
    path = Path(path)
    if not path.is_file():
        return {
            "vasp_version": None, "elapsed_seconds": None, "cpu_seconds": None,
            "electronic_converged": None, "ionic_converged": None,
            "final_energy_definition": "free_energy_TOTEN", "ionic_steps": None,
            "energy_ev_cell": None, "finished": False, "warnings": ["OUTCAR missing"],
            "kpoints": None, "incar": incar or {},
        }
    text = path.read_text(encoding="utf-8", errors="replace")
    analysis = _scan_outcar_text(text)
    analysis["incar"] = incar or {}
    settings = {**analysis['incar'], **analysis['effective_settings']}
    _ionic_applicability(analysis, settings)
    return analysis


def _ionic_applicability(analysis, settings):
    nsw, ibrion = settings.get('NSW'), settings.get('IBRION')
    if nsw == 0 or ibrion in (-1, 0, 5, 6, 7, 8):
        analysis['ionic_converged'] = None
        analysis['ionic_convergence_applicability'] = 'not_applicable'
    elif ibrion in (1, 2, 3) and nsw is not None and nsw > 0:
        analysis['ionic_convergence_applicability'] = 'relaxation'
    else:
        analysis['ionic_convergence_applicability'] = 'unknown'
        if analysis['ionic_converged'] is not True:
            analysis['ionic_converged'] = None


def analyze_vasprun(path, incar=None):
    path = Path(path)
    base = {
        "vasp_version": None, "elapsed_seconds": None, "cpu_seconds": None,
        "electronic_converged": None, "ionic_converged": None,
        "final_energy_definition": "free_energy_TOTEN", "ionic_steps": None,
        "energy_ev_cell": None, "finished": False, "warnings": [],
        "kpoints": None, "incar": incar or {},
    }
    if not path.is_file():
        base["warnings"] = ["vasprun.xml missing"]
        return base
    try:
        from pymatgen.io.vasp.outputs import Vasprun
        xml = Vasprun(path, parse_dos=False, parse_eigen=False,
                      parse_projected_eigen=False, parse_potcar_file=False)
    except Exception as exc:
        base["warnings"] = [f"vasprun parse failed: {exc}"]
        return base
    base["finished"] = True
    for key, attr in (('electronic_converged', 'converged_electronic'),
                      ('ionic_converged', 'converged_ionic')):
        value = getattr(xml, attr, None)
        base[key] = bool(value) if value is not None else None
    try:
        # dpdata vasp/xml consumes e_fr_energy, whereas Vasprun.final_energy
        # is the sigma->0 value. Keep the ledger on the training convention.
        base["energy_ev_cell"] = _finite_or_none(xml.ionic_steps[-1]['e_fr_energy'])
    except Exception:
        base["energy_ev_cell"] = None
    try:
        base["ionic_steps"] = len(xml.ionic_steps)
    except Exception:
        base["ionic_steps"] = None
    if getattr(xml, "vasp_version", None):
        base["vasp_version"] = str(xml.vasp_version)
    # VASP's <time name="totals"> contains CPU seconds then wall seconds.
    import xml.etree.ElementTree as ET
    try:
        for _, node in ET.iterparse(path, events=('end',)):
            if node.tag == 'time' and node.attrib.get('name') == 'totals':
                values = (node.text or '').split()
                if len(values) == 2:
                    base['cpu_seconds'], base['elapsed_seconds'] = map(_finite_or_none, values)
            node.clear()
    except (ET.ParseError, OSError):
        base['warnings'].append('XML timing could not be read')
    if getattr(xml, "kpoints", None) is not None:
        try:
            base["kpoints"] = {"num_kpts": int(getattr(xml.kpoints, "num_kpts", 0) or 0)}
        except Exception:
            base["kpoints"] = None
    if not base["incar"] and getattr(xml, "incar", None):
        allowlisted = {}
        for key, value in dict(xml.incar).items():
            name = str(key).upper()
            if name in INCAR_ALLOWLIST:
                allowlisted[name] = value.tolist() if hasattr(value, "tolist") else value
        base["incar"] = allowlisted
    parameters = getattr(xml, 'parameters', {}) or {}
    base['effective_settings'] = {k: v for k, v in parameters.items() if k in INCAR_ALLOWLIST}
    _ionic_applicability(base, {**base['incar'], **base['effective_settings']})
    return base


def collect_evidence_hashes(folder, result_name=None):
    folder = Path(folder)
    evidence = {}
    for name in INPUT_HASH_NAMES:
        digest = file_sha256(folder / name)
        if digest:
            evidence[name] = digest
    if result_name:
        result_path = folder / result_name
        if result_path.exists():
            evidence["result"] = file_sha256(result_path) if result_path.is_file() else None
            evidence["result_file"] = result_name
    return evidence


def analyze_task_directory(folder, *, result_format="vasp/outcar", result_file="OUTCAR",
                           metadata=None):
    """Build analysis + evidence for one task directory.

    ``metadata`` may carry non-secret collect hints (format, endmember, task_id).
    """
    folder = Path(folder)
    evidence = collect_evidence_hashes(folder, result_file if result_format.startswith('vasp/') else None)
    parse_warnings = []
    try:
        incar = parse_incar_file(folder / "INCAR")
    except (ValueError, TypeError, OSError) as exc:
        incar = {}
        parse_warnings.append(f'INCAR parse failed: {exc}')
    kpoints = _parse_kpoints_file(folder / "KPOINTS")
    if result_format == "vasp/xml":
        analysis = analyze_vasprun(folder / result_file, incar=incar)
    elif result_format == "vasp/outcar":
        analysis = analyze_outcar(folder / result_file, incar=incar)
    else:
        analysis = {
            "vasp_version": None, "elapsed_seconds": None, "cpu_seconds": None,
            "electronic_converged": None, "ionic_converged": None,
            "final_energy_definition": "external_dataset",
            "ionic_steps": None, "energy_ev_cell": None, "finished": None,
            "warnings": ["external_dataset: VASP convergence not re-proven from this format"],
            "kpoints": kpoints, "incar": incar,
        }
    if analysis.get("kpoints") is None and kpoints is not None:
        analysis["kpoints"] = kpoints
    elif kpoints is not None and "KSPACING" in incar and isinstance(analysis.get("kpoints"), dict):
        analysis["kpoints"] = {**analysis["kpoints"], "kspacing": incar.get("KSPACING"), "file": kpoints}
    elif analysis.get("kpoints") is None and "KSPACING" in incar:
        analysis["kpoints"] = {"kspacing": incar["KSPACING"], "kgamma": incar.get("KGAMMA")}

    analysis.setdefault('warnings', []).extend(parse_warnings)
    if evidence != collect_evidence_hashes(folder, result_file if result_format.startswith('vasp/') else None):
        raise ValueError('Calculation files changed during analysis')
    if metadata:
        safe_meta = {key: metadata[key] for key in ("task_id", "endmember", "format", "natoms", "frame",
                                                    "frames_in_source", "sha256", "convergence")
                     if key in metadata}
        evidence = {**evidence, "collect": safe_meta}
    return {"analysis": analysis, "evidence": evidence}
