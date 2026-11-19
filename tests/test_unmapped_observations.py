"""Multi-phase experimental samples remain readable before selecting a database phase."""

from io import BytesIO
import json
from zipfile import ZipFile

from fastapi.testclient import TestClient
from app import app


def test_unmapped_experimental_record_and_archive():
    with TestClient(app) as client:
        pid = client.post(
            "/api/projects", json={"title": "Study", "elements": ["Al", "Ni"]}
        ).json()["id"]
        base = f"/api/projects/{pid}"
        paper = client.post(
            base + "/papers", json={"title": "Sample", "citation": "Source"}
        ).json()["id"]
        record = {
            "paper": paper,
            "phase": None,
            "locator": "Fig. 2",
            "payload": {"kind": "experiment", "value": "A + B", "system": ["Ni", "Al"]},
        }
        saved = client.post(base + "/observations", json=record)
        assert saved.is_success, saved.text
        assert client.put(
            base + "/observations/" + saved.json()["id"],
            json=record | {"locator": "Table 2"},
        ).is_success
        assert not client.post(
            base + "/observations",
            json=record
            | {
                "payload": {"kind": "experiment", "value": "A+B", "system": ["W", "Al"]}
            },
        ).is_success
        raw = b"phase,value\nunassigned,12"
        mapping = dict(
            paper=paper,
            system=["Al", "Ni"],
            keep_unmapped=True,
            phase_col="phase",
            value_col="value",
            locator="Table 1",
        )

        def upload(action, confirmation=""):
            return client.post(
                base + "/experiment-table/" + action,
                files={"file": ("example.csv", raw)},
                data={"mapping": json.dumps(mapping), "confirmation": confirmation},
            )

        preview = upload("preview").json()
        assert "unassigned" in preview["sample"][0]["phase"]
        assert upload("commit", preview["confirmation"]).json()["added"] == 1
        archived = client.post(base + "/archive", json={}).content
        with ZipFile(BytesIO(archived)) as zipfile:
            assert json.loads(zipfile.read("workspace.json"))["version"] == 5
        copied = client.post(
            "/api/workspace/import", files={"file": ("copy.zip", archived)}
        )
        assert copied.is_success, copied.text
        observations = client.get("/api/projects/" + copied.json()["id"]).json()[
            "observations"
        ]
        assert len(observations) == 2 and all(r["phase"] is None for r in observations)
        assert all(r["payload"]["system"] == ["Al", "Ni"] for r in observations)
        assert any(
            r["payload"].get("reported_phase") == "unassigned" for r in observations
        )
