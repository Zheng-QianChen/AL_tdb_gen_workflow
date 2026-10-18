import copy
import hashlib
import json
import re
import uuid

import pytest
from pycalphad import Database

from config import BASE_DATA_DIR
from examples.pandat_literature_validation import sources
from examples.pandat_tdb import equivalence, pandat_text, phase_subset, prepare


SYMMETRIC = """$ SYNTHETIC CONVERSION TEST, NOT MATERIAL DATA
ELEMENT AL FCC_A1 26.98 0 0 !
ELEMENT NI FCC_A1 58.69 0 0 !
ELEMENT VA VACUUM 0 0 0 !
FUNCTION REFAL 298.15 1000-8*T; 6000 N !
FUNCTION REFNI 298.15 REFAL#+1000-2*T*LN(T); 6000 N !
TYPE_DEFINITION % SEQ * !
TYPE_DEFINITION & GES AMEND_PHASE_DESCRIPTION TEST DISORDERED_PART DIS !
TYPE_DEFINITION A GES AMEND_PHASE_DESCRIPTION DIS MAGNETIC -3 0.28 !
TYPE_DEFINITION B GES AMEND_PHASE_DESCRIPTION TEST MAGNETIC -3 0.28 !
PHASE DIS %A 2 1 1 !
CONSTITUENT DIS :AL,NI:VA: !
PARAMETER G(DIS,AL:VA;0) 298.15 REFAL#; 6000 N !
PARAMETER G(DIS,NI:VA;0) 298.15 REFNI#; 6000 N !
PARAMETER TC(DIS,NI:VA;0) 298.15 633; 6000 N !
PARAMETER BMAGN(DIS,NI:VA;0) 298.15 .52; 6000 N !
PHASE TEST:F %&B 5 .25 .25 .25 .25 1 !
CONSTITUENT TEST:F :AL,NI:AL,NI:AL,NI:AL,NI:VA: !
PARAMETER G(TEST,AL:AL:AL:AL:VA;0) 298.15 0; 6000 N !
PARAMETER G(TEST,AL:AL:AL:NI:VA;0) 298.15 -8000; 6000 N !
PARAMETER G(TEST,AL:AL:NI:NI:VA;0) 298.15 -12000; 6000 N !
PARAMETER G(TEST,AL:NI:NI:NI:VA;0) 298.15 -8000; 6000 N !
PARAMETER G(TEST,NI:NI:NI:NI:VA;0) 298.15 0; 6000 N !
PARAMETER G(TEST,AL,NI:*:*:*:VA;0) 298.15 1000-2*T; 6000 N !
PARAMETER TC(TEST,AL:AL:AL:NI:VA;0) 298.15 -100; 6000 N !
PARAMETER BMAGN(TEST,AL:AL:AL:NI:VA;0) 298.15 -.3; 6000 N !
"""


def test_conversion_retains_symmetry_wildcards_functions_and_magnetism():
    original = Database(SYMMETRIC)
    subset = phase_subset(original, "TEST")
    text = pandat_text(subset)
    prepared = Database(text.replace("DISORDER_PART", "DISORDERED_PART"))
    assert len(prepared._parameters.all()) == len(subset._parameters.all())
    assert len([p for p in prepared._parameters.all() if p["phase_name"] == "TEST" and p["parameter_type"] == "TC"]) == 4
    assert "TEST:F" not in text and "*:*:*" in text
    assert "LN(T)" in text and "REFAL#" in text and "FUNCTION REFAL#" not in text
    assert original.phases["TEST"].model_hints["symmetry_FCC_4SL"]
    code = re.search(r"TYPE_DEFINITION (\w) GES AMEND_PHASE_DESCRIPTION TEST DISORDER_PART", text)[1]
    assert code not in re.search(r"PHASE DIS (\S+)", text)[1]
    assert code in re.search(r"PHASE TEST (\S+)", text)[1]
    check = equivalence(original, prepared, "TEST", [300, 633, 1200], samples=4)
    assert check["states_per_temperature"] == 20
    assert check["status"] == "passed"


def test_conversion_audit_rejects_altered_magnetic_parameter():
    original = Database(SYMMETRIC)
    changed = Database(SYMMETRIC.replace("298.15 633;", "298.15 634;"))
    with pytest.raises(ValueError, match="changed G/TC/BMAG"):
        equivalence(original, changed, "TEST", [300], samples=1)


def test_preparation_keeps_source_bytes_and_records_both_hashes():
    root = BASE_DATA_DIR/("conversion_"+uuid.uuid4().hex)
    root.mkdir()
    path = root/"original.tdb"
    content = SYMMETRIC.replace("\n", "\r\n").encode()
    path.write_bytes(content)
    manifest = prepare(path, "TEST", root/"prepared.tdb", [300, 1200])
    assert path.read_bytes() == content
    assert manifest["source_sha256"] == hashlib.sha256(content).hexdigest()
    assert manifest["prepared_sha256"] != manifest["source_sha256"]
    assert manifest["ordered_magnetic_parameters"] == 8
    assert manifest["equivalence"]["status"] == "passed"
    with pytest.raises(ValueError, match="Keep the source TDB unchanged"):
        prepare(path, "TEST", path, [300])
    assert path.read_bytes() == content


def test_local_source_checksum_mismatch_is_never_silently_downloaded(tmp_path, monkeypatch):
    from examples import pandat_literature_validation as validation
    definitions = [{"material": "test", "file": "one.tdb", "url": "https://example.invalid/one.tdb", "sha256": "0"*64}]
    manifest = tmp_path/"sources.json"
    manifest.write_text(json.dumps(definitions))
    monkeypatch.setattr(validation, "MANIFEST", manifest)
    (tmp_path/"one.tdb").write_text("unexpected version")
    with pytest.raises(ValueError, match="Source hash mismatch"):
        sources(tmp_path, fetch=True)


def test_unknown_phase_rejected_without_mutating_database():
    original = Database(SYMMETRIC)
    hints = copy.deepcopy(original.phases["TEST"].model_hints)
    with pytest.raises(ValueError, match="Unknown phase"):
        phase_subset(original, "ABSENT")
    assert original.phases["TEST"].model_hints == hints
