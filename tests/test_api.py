import json
import uuid
import pytest
from fastapi.testclient import TestClient

from app import app
from config import BASE_DATA_DIR, resolve_data_path
from src.main_process.al_worker import ALRunner
from src.settings import parse_hyperparameters


@pytest.fixture
def client():
    with TestClient(app) as value:
        yield value


def test_entries_share_application():
    from main import app as desktop
    from local_server import app as legacy
    assert desktop is app and legacy is app


def test_pages_and_health(client):
    for url in ["/", "/data_preparation", "/visualization", "/model_analysis", "/health"]:
        response = client.get(url)
        assert response.status_code == 200, (url, response.text)


def test_new_and_duplicate_uploads_keep_extension_and_content(client):
    name = "data_" + uuid.uuid4().hex + ".csv"
    first = client.post("/upload_file", files={"file": (name, b"symbol,value\nAl,1", "text/csv")})
    second = client.post("/upload_file", files={"file": (name, b"second", "text/csv")})
    assert first.status_code == second.status_code == 200
    assert first.json()["filename"] == name
    assert second.json()["filename"] == name[:-4] + "_1.csv"
    assert client.get(first.json()["url"]).content == b"symbol,value\nAl,1"
    assert client.get(second.json()["url"]).content == b"second"


def test_path_escape_and_code_hyperparameters_rejected(client):
    response = client.post("/read-record", json={"file_path": "../config.py"})
    assert response.status_code == 403
    assert client.post("/upload_file", files={"file": ("../outside.txt", b"x")}).status_code == 422
    with pytest.raises(ValueError):
        parse_hyperparameters("__import__('os').getcwd()")
    assert parse_hyperparameters('{"n_estimators": 10}') == {"n_estimators": 10}


def test_paths_are_rooted_independent_of_cwd(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    assert resolve_data_path("uploads/a.csv") == BASE_DATA_DIR / "uploads/a.csv"
    with pytest.raises(ValueError):
        resolve_data_path("../outside.txt")


def test_json_config_validates_before_saving(client, demo):
    name = "test_" + uuid.uuid4().hex + ".json"
    assert client.post("/save_input_json", json={"filename": name, "data": demo[1]}).status_code == 200
    assert client.get("/get_config_status", params={"filename": name}).json()["phase_name"] == "DEMO_B2"
    bad = {**demo[1], "record_path": "../escape"}
    assert client.post("/save_input_json", json={"filename": name, "data": bad}).status_code == 422
    assert client.get("/get_config_status", params={"filename": name}).json()["record_path"] == demo[1]["record_path"]


def test_dict_start_uses_config_file_and_websocket_binds_to_task(client, demo, monkeypatch):
    seen = []
    async def fake_loop(self):
        seen.append(json.loads(self.input_json.read_text()))
        self.running = False
    monkeypatch.setattr(ALRunner, "main_loop", fake_loop)
    response = client.post("/api/start_task", json=demo[1])
    assert response.status_code == 200
    task_id = response.json()["task_id"]
    with client.websocket_connect("/ws/" + task_id) as ws:
        assert ws.receive_json()["type"] == "snapshot"
        assert seen[0]["phase_name"] == "DEMO_B2"
        assert len(app.state.manager.tasks[task_id].subscribers) == 1
    assert not app.state.manager.tasks[task_id].subscribers


def test_export_does_not_start_a_job(client, demo):
    response = client.post("/generate_tdb", json={"user": "guest", "input_file_path": demo[0].stem, "mask": 1.5})
    assert response.status_code == 422  # no checkpoint yet
    assert app.state.manager.tasks == {}


def test_multiple_assessments_need_explicit_task(client):
    from types import SimpleNamespace
    first = SimpleNamespace(site_weight=[1, 1], site_elements=[["AL"], ["NI"]])
    second = SimpleNamespace(site_weight=[1, 1], site_elements=[["FE"], ["CO"]])
    app.state.manager.assessments.update(one=first, two=second)
    payload = {"selected_model": "2_A_B.csv"}
    assert client.post("/get_element_groups", json=payload).status_code == 409
    result = client.post("/get_element_groups?task_id=two", json=payload)
    assert result.status_code == 200
    assert result.json()["element_groups"] == [["FE"], ["CO"]]
