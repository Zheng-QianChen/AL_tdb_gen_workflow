"""Reproducible Pandat comparison of pinned public material TDBs (4/5 sites)."""
import argparse
import hashlib
import io
import json
from pathlib import Path
import sys
import urllib.request
import uuid
import zipfile

from config import BASE_DATA_DIR
from examples.pandat_material_validation import audit
from examples.pandat_tdb import prepare
from src.storage import atomic_json


MANIFEST = Path(__file__).resolve().parents[1]/"docs/validation/literature-sources.json"


def sources(directory, fetch=False):
    """Fetch only explicit small source files; always check pinned byte hashes."""
    definitions = json.loads(MANIFEST.read_text(encoding="utf-8"))
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    for source in definitions:
        path = directory/source["file"]
        if not path.is_file() and fetch:
            with urllib.request.urlopen(source["url"], timeout=60) as response:
                data = response.read(10_000_001)
            if len(data) > 10_000_000:
                raise ValueError("Unexpected source size")
            if "archive_member" in source:
                if hashlib.sha256(data).hexdigest() != source["archive_sha256"]:
                    raise ValueError("Source archive hash mismatch")
                with zipfile.ZipFile(io.BytesIO(data)) as archive:
                    info = archive.getinfo(source["archive_member"])
                    if info.file_size > 10_000_000:
                        raise ValueError("Unexpected extracted source size")
                    data = archive.read(info)
            if hashlib.sha256(data).hexdigest() != source["sha256"]:
                raise ValueError(f"Downloaded source hash mismatch: {source['file']}")
            path.write_bytes(data)
        if not path.is_file():
            raise ValueError(f"Missing {path}; supply the source or use --fetch")
        if hashlib.sha256(path.read_bytes()).hexdigest() != source["sha256"]:
            raise ValueError(f"Source hash mismatch: {path}")
    return definitions


def cases():
    temperatures = [300, 500, 650, 800, 1050, 1400]
    definitions = [
        ("AlNi", "FCC4", [{"AL": .25, "NI": .75}, {"AL": .1, "NI": .9}],
         {"AL": .02, "NI": .98}, {"AL": .5, "NI": .5}),
        ("FeNi", "FCC4", [{"FE": .5, "NI": .5}, {"FE": .25, "NI": .75}, {"FE": .215, "NI": .785}],
         {"FE": .05, "NI": .95}, {"FE": .75, "NI": .25}),
        ("AlFe", "BCC_4SL", [{"AL": .15, "FE": .85}, {"AL": .25, "FE": .75}, {"AL": .5, "FE": .5}],
         {"AL": .05, "FE": .95}, {"AL": .5, "FE": .5}),
        ("AlFeNb", "B2_4SL", [{"AL": .24, "FE": .75, "NB": .01}, {"AL": .25, "FE": .7, "NB": .05}],
         {"AL": .1, "FE": .88, "NB": .02}, {"AL": .45, "FE": .53, "NB": .02}),
    ]
    result = []
    for material, phase, compositions, start, end in definitions:
        common = {"phase": phase, "starts": 32, "allow_missing_ordered_endmembers": True}
        for i, composition in enumerate(compositions):
            result.append({"name": f"{material}_gt_{i+1}", "material": material,
                           "request": {**common, "mode": "gt", "temperatures": temperatures, "composition": composition}})
        result.append({"name": f"{material}_gx", "material": material,
                       "request": {**common, "mode": "gx", "temperatures": [300, 650, 1050], "points": 5,
                                   "composition_start": start, "composition_end": end}})
    return result


def validate(executable, version, directory, fetch=False, selected=None):
    chosen = [case for case in cases() if not selected or case["name"] in selected]
    if not chosen or (selected and set(selected) != {case["name"] for case in chosen}):
        raise ValueError("Unknown or empty case selection")
    manifest = {source["material"]: source for source in sources(directory, fetch)}
    folder = BASE_DATA_DIR/("pandat_literature_validation_"+uuid.uuid4().hex[:12])
    folder.mkdir()
    summary = {"folder": str(folder), "software_version": version, "cases": [], "expected_cases": len(chosen),
               "tolerances": {"energy_J_mol_atoms": 1, "fraction": 3e-6, "order_amplitude": 1e-3}, "sources": list(manifest.values())}
    prepared = {}
    for case in chosen:
        print("Validating "+case["name"], file=sys.stderr, flush=True)
        source = manifest[case["material"]]
        original = Path(directory)/source["file"]
        try:
            if case["material"] not in prepared:
                temperatures = sorted({t for item in chosen if item["material"] == case["material"] for t in item["request"]["temperatures"]})
                destination = folder/"prepared"/source["file"]
                conversion = prepare(original, case["request"]["phase"], destination, temperatures)
                prepared[case["material"]] = (destination, conversion)
            destination, conversion = prepared[case["material"]]
            result = audit({**case, "source": destination, "local_source": original, "synthetic": False,
                            "source_kind": "prepared_public_material_database",
                            "provenance": {"publication": source, "conversion": conversion}}, folder/case["name"], executable, version)
        except Exception as exc:
            result = {"name": case["name"], "status": "error", "error": f"{type(exc).__name__}: {exc}",
                      "folder": str(folder/case["name"])}
        result["material"] = case["material"]
        summary["cases"].append(result)
        summary["status"] = "running"
        atomic_json(folder/"summary.json", summary)
        print(json.dumps({key: value for key, value in result.items() if key not in {"source", "execution"}}, ensure_ascii=False), file=sys.stderr, flush=True)
    summary["status"] = "passed" if all(case["status"] == "passed" for case in summary["cases"]) else "failed"
    summary["passed_cases"] = sum(case["status"] == "passed" for case in summary["cases"])
    for key in ("points", "energy_points_passed", "formula_points_passed"):
        summary[key] = sum(case.get(key, 0) for case in summary["cases"])
    atomic_json(folder/"summary.json", summary)
    return summary


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--executable", required=True)
    parser.add_argument("--version", required=True)
    parser.add_argument("--source-dir", default=str(BASE_DATA_DIR/"literature_sources"))
    parser.add_argument("--fetch", action="store_true", help="Download missing pinned sources")
    parser.add_argument("--cases", nargs="+")
    args = parser.parse_args()
    result = validate(args.executable, args.version, args.source_dir, args.fetch, args.cases)
    print(json.dumps({key: value for key, value in result.items() if key not in {"cases", "sources"}}, indent=2, ensure_ascii=False))
    sys.exit(0 if result["status"] == "passed" else 5)
