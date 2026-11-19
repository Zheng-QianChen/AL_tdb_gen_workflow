import sqlite3
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

from fastapi.testclient import TestClient

from app import app
from config import resolve_data_path
from src import fp, hpc_monitor
from src.storage import atomic_json


def test_monitor_observations_and_receipt_isolation(tmp_path, monkeypatch):
    now = datetime.now(timezone.utc)
    recent = now.isoformat()
    old = (now - timedelta(hours=2)).isoformat()
    feed = tmp_path / "observations.json"
    monkeypatch.setenv("AL_TDB_HPC_OBSERVATIONS", str(feed))
    with TestClient(app) as client:
        project = client.post("/api/projects", json={"title":"HPC test","elements":["Ni"]}).json()["id"]
        base = "/api/projects/" + project
        phase = client.post(base+"/phases", json={"alias":"fcc","name":"FCC_A1","system":["Ni"]}).json()["id"]
        mid = client.post(base+"/models", json={"title":"FCC variant","phase":phase}).json()["id"]
        monkeypatch.setenv("AL_TDB_HPC_PROJECTS", "external="+project)
        calc = "workbench/models/"+mid+"/calculated"
        atomic_json(resolve_data_path("run/model_"+mid+".json"), {"AL_set":{"calced_DFT_path":calc}})
        record = {"platform":"cpu","queue":"short","status":"submitted","recorded_at":old,
                  "jobs":[{"id":sid,"tasks":2} for sid in ("123","124","125","126")]}
        atomic_json(resolve_data_path(calc+"/iter.000001/02.fp/dispatch.json"), record)
        atomic_json(resolve_data_path(calc+"/iter.000000/02.fp/dispatch.json"), {"status":"finished","task_count":6})
        def obs(sid, raw, **kwargs):
            return dict({"scheduler_id":sid,"project":"external","platform":"cpu","raw":raw,
                         "detail":"PRIVATE_PROBE_OUTPUT"}, **kwargs)
        jobs = {"a":obs("123","RUNNING"), "b":obs("124","PENDING", observed_at=old),
                "c":obs("125","UNKNOWN"), "d":obs("126","PENDING"),
                "e":obs("123","FAILED", platform="gpu"), "f":obs("123","COMPLETED", project="other")}
        atomic_json(feed, {"observed_at":recent,"jobs":jobs})
        def fetch():
            response = client.get("/api/jobs/monitor")
            assert response.status_code == 200
            assert "PRIVATE_PROBE_OUTPUT" not in response.text
            return response.json()
        result = fetch()
        assert result["source"]["status"] == "ok"
        rows = [r for r in result["jobs"] if r["project"] == project]
        assert len(rows) == 6
        by_id = {r["scheduler_id"]:r for r in rows if r["model"]==mid}
        assert by_id["123"]["state"] == "running" and by_id["123"]["phase"] == "FCC_A1"
        assert by_id["124"]["stale"] and by_id["124"]["state"] == "queued"
        assert by_id["125"]["state"] == "unknown"
        assert by_id["126"]["state"] == "queued" and not by_id["126"]["stale"]
        assert by_id[""]["state"] == "finished" and by_id[""]["iteration"] == 0
        atomic_json(feed, {"observed_at":old, "jobs":jobs})
        assert fetch()["source"]["status"] == "stale"
        feed.write_text("{", encoding="utf-8")
        result = fetch()
        assert result["source"]["status"] == "unavailable"
        assert all(r["state"] in {"submitted","finished"} for r in result["jobs"] if r["model"]==mid)
        monkeypatch.delenv("AL_TDB_HPC_PROJECTS")
        assert fetch()["source"]["status"] == "unconfigured"


def test_retry_receipt_preserves_scheduler_ids(tmp_path):
    job = SimpleNamespace(job_id="341", job_state=SimpleNamespace(name="waiting"), job_hash="group", job_task_list=[1,2])
    submission = SimpleNamespace(submission_hash="batch", belonging_jobs=[job])
    plan = dict(queue="batch", task_count=2)
    first = fp.save_dispatch(tmp_path, submission, "cpu.json", plan, "submitted")
    assert first["jobs"][0]["state"] == "submitted"
    job.job_id = "342"
    second = fp.save_dispatch(tmp_path, submission, "cpu.json", plan, "submitted")
    assert [r["state"] for r in second["jobs"]] == ["superseded","submitted"]
    submission.belonging_jobs = []
    final = fp.save_dispatch(tmp_path, submission, "cpu.json", plan, "interrupted_or_failed")
    assert final["jobs"] == second["jobs"]


def test_scoped_asset_receipts_require_scheduler_id(tmp_path, monkeypatch):
    catalog = tmp_path / "catalog.sqlite"
    with sqlite3.connect(catalog) as db:
        db.execute("CREATE TABLE jobs (project, platform, scheduler_id, status, updated_at)")
        db.executemany("INSERT INTO jobs VALUES (?, 'cpu', ?, ?, '2026-01-01T00:00:00Z')",
                       [("demo", "89", "submitted"), ("demo", "", "queued"), ("hidden", "42", "done")])
    monkeypatch.setenv("AL_TDB_HPC_CATALOG", str(catalog))
    jobs, state = hpc_monitor.asset_receipts({"demo":"local"})
    assert state == "ok" and len(jobs) == 1
    assert jobs[0]["state"] == "submitted" and jobs[0]["scheduler_id"] == "89"
    monkeypatch.setenv("AL_TDB_HPC_CATALOG", str(tmp_path / "absent"))
    assert hpc_monitor.asset_receipts({"demo":"local"}) == ([], "unavailable")
