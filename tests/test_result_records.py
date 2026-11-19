import math
from pathlib import Path

import pytest

from examples.demo import write_synthetic_results
from src.result_records import (
    ResultConflictError, bind_training_snapshot, export_calc_txt,
    has_database, ingest_legacy_calc, list_results, records_for_training,
    result_detail, revise_result, training_snapshot,
)


def test_list_empty_without_database(demo):
    assert list_results(demo[0]) == {"records": [], "total": 0}
    assert not has_database(demo[0])


def test_register_revise_and_conflict(phase):
    path = write_synthetic_results(phase)
    assert path.is_file() and has_database(phase.data)
    listing = list_results(phase.data, iteration=0)
    assert listing["total"] >= 1
    record = listing["records"][0]
    detail = result_detail(phase.data, record["id"])
    assert detail["original"]["revision"] == 0
    assert detail["record"]["source_kind"] == "synthetic"

    revised = revise_result(phase.data, record["id"],
                            {"energy_ev_cell": record["energy_ev_cell"] - 0.5, "note": "manual fix"},
                            actor="tester", reason="correct energy",
                            expected_revision=0)
    assert revised["record"]["revision"] == 1
    assert revised["record"]["source_kind"] == "manual_override"
    assert revised["record"]["evidence"]["original_source_kind"] == "synthetic"
    assert revised["history"][-1]["actor"] == "tester"

    with pytest.raises(ResultConflictError):
        revise_result(phase.data, record["id"], {"note": "stale"}, actor="tester",
                      reason="should fail", expected_revision=0)
    with pytest.raises(ValueError, match="finite"):
        revise_result(phase.data, record["id"], {"energy_ev_cell": math.nan},
                      actor="tester", reason="bad", expected_revision=1)
    with pytest.raises(ValueError, match="actor"):
        revise_result(phase.data, record["id"], {"note": "x"}, actor=" ",
                      reason="ok", expected_revision=1)
    with pytest.raises(ValueError, match="analysis|rejected|Only"):
        revise_result(phase.data, record["id"], {"analysis": {}}, actor="tester",
                      reason="no", expected_revision=1)
    with pytest.raises(KeyError):
        result_detail(phase.data, "missing:id")


def test_training_snapshot_pins_revision(phase):
    write_synthetic_results(phase)
    record = list_results(phase.data, iteration=0)["records"][0]
    revise_result(phase.data, record["id"], {"energy_ev_cell": record["energy_ev_cell"] + 1},
                  actor="tester", reason="before train", expected_revision=0)
    consumed = records_for_training(phase.data, 0)
    snap = bind_training_snapshot(phase.data, 0, "model_000000_2.pd", records=consumed)
    assert snap["records"][0]["revision"] == 1
    # Later edits must not mutate the bound snapshot.
    revise_result(phase.data, record["id"], {"note": "after train"}, actor="tester",
                  reason="post", expected_revision=1)
    stored = training_snapshot(phase.data, 0, "model_000000_2.pd")
    assert stored["snapshot_hash"] == snap["snapshot_hash"]
    assert stored["records"][0]["revision"] == 1
    tip = result_detail(phase.data, record["id"])["record"]
    assert tip["revision"] == 2 and tip["note"] == "after train"


def test_legacy_ingest_once_only(phase, tmp_path):
    write_synthetic_results(phase)
    legacy = tmp_path / "legacy.txt"
    legacy.write_text((Path(phase.phase.calced_DFT_path) / "iter.000000" / "calc.txt").read_text())
    with pytest.raises(ValueError, match="already exists"):
        ingest_legacy_calc(phase.data, 0, legacy, actor="tester", reason="too late")


def test_legacy_ingest_without_prior_batch(phase, tmp_path):
    folder = Path(phase.phase.generate_DFT_path) / "0"
    members = [path.parent.name.replace("_", ":") for path in sorted(folder.glob("*/POSCAR"))]
    legacy = tmp_path / "legacy.txt"
    legacy.write_text("".join(f"{m},-1,-1\n" for m in members))
    report = ingest_legacy_calc(phase.data, 0, legacy, actor="tester", reason="migrate file-only",
                                source_kind="legacy_unverified", expected=members)
    assert report["status"] == "registered"
    assert records_for_training(phase.data, 0, expected=members)[0]["source_kind"] == "legacy_unverified"
    text = export_calc_txt(phase.data, 0)
    assert "-1,-1" in text


def test_edited_calc_txt_does_not_change_training_records(phase):
    write_synthetic_results(phase)
    calc = Path(phase.phase.calced_DFT_path) / "iter.000000" / "calc.txt"
    original = records_for_training(phase.data, 0)
    calc.write_text("TAMPERED,0,0\n")
    assert records_for_training(phase.data, 0) == original


def test_binding_consumed_versions_survives_concurrent_edit_and_retry(phase):
    write_synthetic_results(phase)
    consumed = records_for_training(phase.data, 0)
    first = consumed[0]
    revise_result(phase.data, first['id'], {'energy_ev_cell': -123},
                  actor='other user', reason='edit during training', expected_revision=0)
    snapshot = bind_training_snapshot(phase.data, 0, 'model_000000_2.pd', records=consumed)
    assert snapshot['records'][0]['revision'] == 0
    assert records_for_training(phase.data, 0, checkpoint='model_000000_2.pd') == consumed
    assert bind_training_snapshot(phase.data, 0, 'model_000000_2.pd', records=consumed) == snapshot
    with pytest.raises(ResultConflictError, match='already pins'):
        bind_training_snapshot(phase.data, 0, 'model_000000_2.pd',
                               records=records_for_training(phase.data, 0))
    # Reimporting the same source preserves manual revisions rather than resetting them.
    write_synthetic_results(phase)
    assert result_detail(phase.data, first['id'])['record']['energy_ev_cell'] == -123


def test_audit_rows_cannot_be_updated(phase):
    import sqlite3
    from src.result_records import database_path
    write_synthetic_results(phase)
    with sqlite3.connect(database_path(phase.data)) as connection:
        with pytest.raises(sqlite3.IntegrityError, match='append-only'):
            connection.execute('DELETE FROM revisions')
