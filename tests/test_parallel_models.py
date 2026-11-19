"""Competing model variants of the same physical phase have distinct run identities."""
from concurrent.futures import ThreadPoolExecutor
from io import BytesIO
import json
import time
from zipfile import ZipFile

from fastapi.testclient import TestClient

from app import app
from config import resolve_data_path
from examples.demo import prepare_demo
from src.project_models import config_path
from src.result_records import register_batch


def test_parallel_model_runs_and_portable_copy():
    _, source = prepare_demo()
    with TestClient(app) as client:
        def post(url, body):
            response = client.post(url, json=body)
            assert response.is_success, response.text
            return response.json()

        project = post("/api/projects", {"title":"Alloys","elements":["Al","Ni"]})["id"]
        base = "/api/projects/"+project
        phase = post(base+"/phases", {"name":"B2","alias":"B2","system":["Al","Ni"]})["id"]
        first = post(base+"/models", {"title":"Reference","phase":phase})["id"]
        def save(mid, raw):
            response = client.put(base+"/models/"+mid+"/config", json=raw)
            assert response.is_success, response.text
        save(first, source)
        second = post(base+"/models", {"title":"Alternative","phase":phase,"template":first})["id"]
        data = [json.loads(config_path(mid).read_text("utf-8")) for mid in [first,second]]
        data[1]["random_seed"] += 1
        save(second, data[1])
        assert data[0]["phase_name"] == data[1]["phase_name"] == "B2"
        assert data[0]["record_path"] != data[1]["record_path"]
        assert all(resolve_data_path(d["structure_file"]).is_file() for d in data)
        params = [{"user_id":"guest","configname":config_path(mid).stem} for mid in [first,second]]
        with ThreadPoolExecutor(max_workers=2) as pool:
            tasks = list(pool.map(lambda body:post("/start",body),params))
        assert len({r["task_id"] for r in tasks}) == 2
        deadline=time.monotonic()+60
        while time.monotonic()<deadline:
            if all((resolve_data_path(d["record_path"])/"checkpoint.json").is_file() for d in data):
                break
            time.sleep(.2)
        for i, d in enumerate(data):
            checkpoint = json.loads((resolve_data_path(d["record_path"])/"checkpoint.json").read_text("utf-8"))
            assert checkpoint["config"]["random_seed"] == d["random_seed"]
            assert client.get("/status",params=params[i]).json()["running"]
        assert all(m["state"]=="运行中" for m in client.get(base+"/models").json())
        assert client.post(base+"/archive",json={"page":"model"}).is_success
        post("/stop",params[0])
        assert client.get("/status",params=params[1]).json()["running"]
        post("/stop",params[1])
        deadline=time.monotonic()+15
        while any(client.get("/status",params=p).json()["running"] for p in params) and time.monotonic()<deadline:
            time.sleep(.1)
        assert client.put(base+"/models/"+first+"/config",json=source).status_code == 422
        for i, mid in enumerate([first, second]):
            register_batch(data[i], 0, [{"endmember":"AL:NI", "energy_ev_cell":-5.0-i}],
                           source_kind="synthetic", actor="test", reason="parallel result isolation")
            retrieved = client.get("/api/results", params={"config": config_path(mid).name}).json()
            assert retrieved["records"][0]["energy_ev_cell"] == -5.0-i
        other=post("/api/projects", {"title":"Other","elements":["Al"]})["id"]
        assert client.get("/jobs",params={"project":other,"model":first}).status_code==404
        direct=client.get("/jobs",params={"project":project,"model":first,"config":config_path(second).name})
        assert direct.url.params["config"]==config_path(first).name
        saved=client.post(base+"/archive",json={"page":"model","picks":{"model":second}})
        assert saved.is_success, saved.text[:200] if not saved.is_success else ""
        restored=client.post("/api/workspace/import",files={"file":("models.zip",saved.content)})
        assert restored.is_success, restored.text
        copy=restored.json()
        clone="/api/projects/"+copy["id"]
        models=client.get(clone+"/models").json()
        assert [m["title"] for m in models]==["Reference","Alternative"]
        assert copy["view"]["picks"]["model"]==models[1]["id"]
        for m in models:
            assert m["id"] not in (first,second) and m["configured"] and m["archived"]
            config=json.loads(config_path(m["id"]).read_text("utf-8"))
            assert resolve_data_path(config["structure_file"]).is_file()
            history=client.get(clone+"/models/"+m["id"]+"/history")
            with ZipFile(BytesIO(history.content)) as z:
                assert "record/checkpoint.json" in z.namelist()
                assert "record/results.sqlite" in z.namelist()
