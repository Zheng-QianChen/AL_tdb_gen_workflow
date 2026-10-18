"""Probe MatCalc's installed public C API, retaining reader failures as failures.

The API and command signatures are supplied with MatCalc in include/matcalc and
src/example.c. No license server, license modification, or GUI automation is used.
This is an import/default-solver probe, not a certified homogeneous benchmark.
"""
import argparse
import ctypes as C
import hashlib
import json
import math
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile


def classify(parsed, log, returncode, official_smoke=False):
    """Command return code zero does not guarantee numerical/model success."""
    lower = log.lower()
    if "cannot attach disordered part" in lower or "type definition ignored" in lower:
        return "incompatible_order_disorder_syntax"
    if "unknown keyword" in lower:
        return "unsupported_database_keyword"
    if returncode != 0 or parsed.get("status") != "commands_completed":
        return "execution_or_command_failed"
    if "*** error ***" in lower or "maximum number of iterations" in lower or "* error *" in lower:
        return "calculation_failed"
    if official_smoke and parsed.get("variables", {}).get("GM") is not None:
        return "official_smoke_completed"
    return "requires_model_and_homogeneity_audit"


def worker(request, output, home):
    dll_directory = os.add_dll_directory(str(home))
    lib = C.CDLL(str(home/"mc_core.dll"))

    def bind(name, restype, *argtypes):
        function = getattr(lib, name)
        function.restype, function.argtypes = restype, list(argtypes)
        return function

    initialize = bind("MCC_InitializeExternalConstChar", C.c_bool, C.c_char_p, C.c_bool)
    error = bind("MCC_GetLastError", C.c_char_p)
    command = bind("MCCOL_ProcessCommandLineInputNewColineConst", C.c_int, C.c_char_p)
    sink = bind("MCC_ColineOutputSinkAddStdOutSink", C.c_int, C.c_char_p)
    category = bind("MCC_ColineOutputSinkSetCategory", C.c_int, C.c_int, C.c_int)
    enable = bind("MCC_ColineOutputSinkEnable", C.c_int, C.c_int)
    get = bind("MCC_GetCalcVariable", C.c_bool, C.c_char_p, C.POINTER(C.c_double), C.c_bool, C.c_bool)
    count = bind("MCC_GetNumPhases", C.c_int)
    phase_name = bind("MCC_GetPhaseNameFromIndex", C.c_char_p, C.c_int)
    data = {"initialized": bool(initialize(str(home).encode("ascii"), True)), "commands": []}
    output.write_text(json.dumps(data, indent=2), encoding="utf-8")
    if not data["initialized"]:
        return
    sid = sink(b"cross_engine")
    category(sid, -1)
    enable(sid)
    for text in request["commands"]:
        print("COMMAND:", text, flush=True)
        rc = command(text.encode("ascii"))
        data["commands"].append({"command": text, "returncode": rc,
                                 "error": (error() or b"").decode("utf-8", errors="replace")})
        print("RETURN:", rc, flush=True)
        output.write_text(json.dumps(data, indent=2), encoding="utf-8")
        if rc != 0:
            data["status"] = "command_failed"
            break
    else:
        data["status"] = "commands_completed"

    def value(name):
        number = C.c_double()
        ok = bool(get(name.encode("ascii"), C.byref(number), True, True))
        return number.value if ok and math.isfinite(number.value) else None

    data["variables"] = {key: value(key) for key in ("T", "P", "GM", "R")}
    data["phases"] = []
    for i in range(count()):
        name = phase_name(i).decode("ascii")
        data["phases"].append({"phase": name, "fraction": value(f"F${name}"),
                               "GM": value(f"GMP${name}"),
                               "X": {c: value(f"X${name}${c}") for c in request["components"]}})
    output.write_text(json.dumps(data, indent=2, allow_nan=False), encoding="utf-8")
    dll_directory.close()


def run(folder, home):
    baseline = json.loads((folder/"pycalphad.json").read_text(encoding="utf-8"))
    requests = [{"case": "official_AlMgSi_smoke", "components": ["AL", "MG", "SI"],
        "tdb": str(home/"database/thermodynamic/mc_al.tdb"),
        "commands": ["new-workspace", "open-thermodynamic-database file-name=model.tdb",
            "select-elements elements=Al Si Mg",
            "select-phases phases=SI_DIAMOND_A4 FCC_A1 LIQUID MG2SI_B",
            "read-thermodynamic-database", "set-reference-element element=Al",
            "enter-composition type=weight-percent composition=mg=1.0 si=1.0",
            "set-start-values", "set-temperature-celsius temperature=600", "calculate-equilibrium"]}]
    for point in baseline["cases"]:
        components = list(point["composition"])
        requests.append({"case": point["case"], "components": components, "tdb": point["original_tdb"],
            "commands": ["new-workspace", "open-thermodynamic-database file-name=model.tdb",
                "select-elements elements="+" ".join(components)+" VA",
                "select-phases phases="+point["phase"], "read-thermodynamic-database",
                "set-reference-element element="+components[-1],
                "enter-composition type=mole-percent composition="+" ".join(
                    f"{c}={100*point['composition'][c]:.16g}" for c in components[:-1]),
                "set-start-values", f"set-temperature-celsius temperature={point['T_K']-273.15:.16g}",
                "calculate-equilibrium"]})
    results = {"engine": "MatCalc", "version": "6.10.1.002", "home": str(home),
               "mc_core_sha256": hashlib.sha256((home/"mc_core.dll").read_bytes()).hexdigest(),
               "protocol": "official smoke plus original-TDB import/default-solver probes; no multistart", "cases": []}
    for request in requests:
        dest = folder/request["case"]/"matcalc"
        dest.mkdir(parents=True, exist_ok=True)
        (dest/"request.json").write_text(json.dumps(request, indent=2, ensure_ascii=False), encoding="utf-8")
        with tempfile.TemporaryDirectory(prefix="mc_cross_") as tmp:
            work = Path(tmp)
            shutil.copyfile(request["tdb"], work/"model.tdb")
            (work/"request.json").write_text(json.dumps(request), encoding="utf-8")
            try:
                process = subprocess.run([sys.executable, "-X", "utf8", str(Path(__file__).resolve()),
                    str(folder.resolve()), "--home", str(home), "--worker", str(work/"request.json"),
                    "--output", str(work/"result.json")], cwd=tmp, stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT, timeout=25)
                raw, returncode = process.stdout, process.returncode
            except subprocess.TimeoutExpired as exc:
                raw, returncode = exc.stdout or b"", None
            parsed = json.loads((work/"result.json").read_text(encoding="utf-8")) if (work/"result.json").is_file() else {}
        (dest/"raw.log").write_bytes(raw)
        parsed.update(case=request["case"], process_returncode=returncode)
        parsed["assessment"] = classify(parsed, raw.decode("utf-8", errors="replace"), returncode,
                                        request["case"] == "official_AlMgSi_smoke")
        parsed["included_in_literature_energy_comparison"] = False
        (dest/"result.json").write_text(json.dumps(parsed, indent=2, ensure_ascii=False), encoding="utf-8")
        results["cases"].append(parsed)
        (folder/"matcalc.json").write_text(json.dumps(results, indent=2, ensure_ascii=False), encoding="utf-8")
        print(request["case"], parsed.get("status"), parsed.get("variables"), flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("folder", type=Path)
    parser.add_argument("--home", type=Path, required=True)
    parser.add_argument("--worker", type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    if args.worker:
        worker(json.loads(args.worker.read_text(encoding="utf-8")), args.output, args.home)
    else:
        run(args.folder, args.home)
