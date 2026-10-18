"""Replay independent homogeneous single-phase starts with OpenCalphad 6.

Run cross_engine_pycalphad.py first to generate the common independent seeds.
No database parameters are rewritten; each run uses the author's original TDB.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import tempfile

NUMBER = r"[-+]?(?:\d+\.?\d*|\.\d+)(?:[EeDd][-+]?\d+)?"


def parse_output(output, phase, composition):
    text = output.replace("\r", "")
    def number(value):
        return float(value.upper().replace("D", "E"))
    values = re.findall(r"\bGM=\s*("+NUMBER+r")", text)
    phase_rows = re.findall(r"^([A-Z0-9_#]+)\.{2,}\s+([EFSDB])\s+("+NUMBER+r")", text, re.M)
    active = [(name, number(amount)) for name, status, amount in phase_rows if number(amount) > 1e-8]
    x = {c: number(m[-1]) for c in composition if (m := re.findall(
        r"\bX\("+re.escape(phase)+","+c+r"\)=\s*("+NUMBER+r")", text))}
    comp_error = max(abs(x[c]-composition[c]) for c in composition) if len(x) == len(composition) else None
    site_rows = re.findall(r"Sublattice\s+(\d+)\s+with\s+(\d+)\s+constituents[^\n]*sites\s*\n([^\n]+)", text)
    sites, site_errors, site_counts_valid = {}, [], True
    for index, count, line in site_rows:
        constituents = re.findall(r"\b([A-Z][A-Z0-9_]*)\s+("+NUMBER+r")", line)
        site_counts_valid &= len(constituents) == int(count)
        site_errors.append(abs(sum(number(y) for _, y in constituents)-1))
        sites.update({f"Y_{int(index)-1}_{c}": number(y) for c, y in constituents})
    site_error = max(site_errors) if site_errors else None
    site_valid = bool(sites and site_counts_valid and site_error < 1e-5
                      and min(sites.values()) >= 0 and max(sites.values()) <= 1)
    calculated = "Equilibrium result:" in text and "does not represent a calculated equilibrium" not in text
    comparable = bool(calculated and values and len(active) == 1 and active[0][0] == phase
                      and abs(active[0][1]-1) < 1e-7 and comp_error is not None and comp_error < 1e-7 and site_valid)
    return {"calculated": calculated, "comparable": comparable,
            "G": number(values[-1]) if values else None, "active_phases": active,
            "X": x, "max_composition_error": comp_error,
            "site_fractions_printed_precision": sites, "max_printed_site_sum_error": site_error,
            "site_count": len(site_rows),
            "reader_parameter_counts": re.findall(r"Out of\s+(\d+) model parameters\s+(\d+) have been entered", text),
            "diagnostic_lines": [line.strip() for line in text.splitlines()
                if any(word in line.lower() for word in ("warning", "error", "rejected", "missing"))][:25]}


def run(folder, exe, limit):
    source = json.loads((folder/"pycalphad.json").read_text(encoding="utf-8"))
    result = {"engine": "OpenCalphad", "executable": str(exe),
              "executable_sha256": hashlib.sha256(exe.read_bytes()).hexdigest(),
              "constraint": "one entered phase, calculate no-global, one fresh process per seed",
              "global_minimum_certified": False, "cases": []}
    env = dict(os.environ, OCHOME=str(exe.parent), OMP_NUM_THREADS="1")
    startup = None
    if os.name == "nt":
        startup = subprocess.STARTUPINFO()
        startup.dwFlags |= subprocess.STARTF_USESHOWWINDOW
        startup.wShowWindow = 0
    for point in source["cases"]:
        dest = folder/point["case"]/"opencalphad"
        dest.mkdir(exist_ok=True)
        seeds = json.loads((dest.parent/"independent_seeds.json").read_text(encoding="utf-8"))
        if limit:
            seeds = seeds[:limit]
        phase, composition = point["phase"], point["composition"]
        item = {"case": point["case"], "G_local": point["G_local"], "G_Pandat": point["G_Pandat"], "runs": []}
        for seed in seeds:
            # OC asks only the first nc-1 fractions on each substitutional site;
            # the last fraction is REST and a pure vacancy site needs no input.
            fractions = [seed["site_fractions"][f"Y_{i}_{c}"] for i in range(4) for c in list(composition)[:-1]]
            script = ("read tdb model\n\n\n\nset stat phase *=sus\n"
                      f"set stat phase {phase}=ent 1\n"
                      f"set cond t={point['T_K']} p={point['P_Pa']} n=1 "
                      +" ".join(f"x({c})={x:.16g}" for c, x in list(composition.items())[:-1])+"\n"
                      +f"amend constitution {phase} 1 n\n"
                      +"\n".join(f"{y:.16g}" for y in fractions)+"\nc n\nl r 2\nshow gm "
                      +" ".join(f"x({phase},{c})" for c in composition)+"\nexit y\n")
            (dest/f"{seed['name']}.input.txt").write_text(script, encoding="ascii")
            with tempfile.TemporaryDirectory(prefix="oc_cross_") as tmp:
                shutil.copyfile(point["original_tdb"], Path(tmp)/"model.TDB")
                try:
                    process = subprocess.run([str(exe)], input=script.encode("ascii"),
                        stdout=subprocess.PIPE, stderr=subprocess.STDOUT, cwd=tmp,
                        env=env, startupinfo=startup, timeout=15)
                    raw, returncode = process.stdout, process.returncode
                except subprocess.TimeoutExpired as exc:
                    raw, returncode = exc.stdout or b"", None
            (dest/f"{seed['name']}.log").write_bytes(raw)
            parsed = parse_output(raw.decode("utf-8", errors="replace"), phase, composition)
            parsed.update(seed=seed["name"], returncode=returncode)
            parsed["comparable"] = parsed["comparable"] and returncode == 0
            item["runs"].append(parsed)
        accepted = [r for r in item["runs"] if r["comparable"]]
        item.update(attempts=len(seeds), accepted=len(accepted),
                    best=min(accepted, key=lambda r: r["G"]) if accepted else None)
        result["cases"].append(item)
        (folder/"opencalphad.json").write_text(json.dumps(result, indent=2, ensure_ascii=False, allow_nan=False), encoding="utf-8")
        print(item["case"], "accepted", len(accepted), "best G", item["best"]["G"] if item["best"] else None, flush=True)
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("folder", type=Path)
    parser.add_argument("--exe", type=Path, required=True)
    parser.add_argument("--limit", type=int, default=0)
    args = parser.parse_args()
    run(args.folder, args.exe, args.limit)
