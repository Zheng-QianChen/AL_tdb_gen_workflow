import hashlib
import json
from io import BytesIO
from zipfile import ZipFile

from fastapi.testclient import TestClient
from app import app


def test_inline_pdf_and_table_intake():
    with TestClient(app) as client:

        def project():
            result = client.post(
                "/api/projects", json={"title": "Test", "elements": ["Al", "Ni"]}
            )
            return "/api/projects/" + result.json()["id"]

        base, other = project(), project()
        phase = client.post(
            base + "/phases",
            json={"alias": "CsCl", "name": "B2", "system": ["Al", "Ni"]},
        ).json()["id"]
        paper = client.post(
            base + "/papers", json={"title": "Study", "citation": "Source"}
        ).json()["id"]
        pdf = b"%PDF-1.4 test"
        assert client.post(
            f"{base}/papers/{paper}/pdf", files={"file": ("read.pdf", pdf)}
        ).is_success
        aid = client.get(base).json()["attachments"][0]["id"]
        inline = client.get(f"{base}/pdf/{aid}")
        assert inline.content == pdf and inline.headers[
            "content-disposition"
        ].startswith("inline")
        assert client.get(f"{other}/pdf/{aid}").status_code == 404

        raw = (
            '\r\nphase\titem\tX\tU\ttemp\tNotes\r\nCsCl\t焓\t12\tJ/mol\t25\t"first\nline"'
            "\r\nb2\t焓\t14\tJ/mol\t30\tsecond"
        ).encode("gb18030")
        mapping = dict(
            paper=paper,
            phase_col="phase",
            locator="表 2",
            quantity_col="item",
            value_col="X",
            unit_col="U",
            temp_col="temp",
            temp_unit="°C",
        )

        def upload(action, data=raw, token="", **changes):
            return client.post(
                base + "/experiment-table/" + action,
                files={"file": ("measured.tsv", data)},
                data={"mapping": json.dumps(mapping | changes), "confirmation": token},
            )

        assert upload("inspect").json()["total"] == 2
        preview = upload("preview").json()
        assert [r["line"] for r in preview["sample"]] == [3, 5]
        assert (
            preview["sample"][0]["T_K"] == 298.15
            and preview["sample"][0]["quantity"] == "焓"
        )
        assert (
            "第 5 行"
            in upload("preview", raw.replace(b"b2", b"unassigned")).json()["detail"]
        )
        assert (
            upload("commit", token=preview["confirmation"], unit="cal/mol").status_code
            == 422
        )
        assert client.get(base).json()["observations"] == []
        token = preview["confirmation"]
        saved = upload("commit", token=token).json()
        assert saved["added"] == 2
        assert upload("commit", token=token).json()["duplicates"] == 2
        rid = saved["first"]
        record = next(
            r for r in client.get(base).json()["observations"] if r["id"] == rid
        )
        provenance = record["payload"]["csv_source"]
        assert provenance["cells"]["Notes"] == "first\nline"
        assert provenance["sha256"] == hashlib.sha256(raw).hexdigest()
        body = dict(
            paper=paper,
            phase=phase,
            locator="Table 2",
            payload={"kind": "experiment", "value": "13", "csv_source": {}},
        )
        assert client.put(f"{base}/observations/{rid}", json=body).is_success
        assert client.get(f"{base}/observations/{rid}/table").content == raw
        assert client.get(f"{other}/observations/{rid}/table").status_code == 404
        archive = client.post(base + "/archive", json={})
        with ZipFile(BytesIO(archive.content)) as z:
            assert json.loads(z.read("workspace.json"))["version"] == 4
            assert z.read("blobs/" + provenance["sha256"]) == raw
        restored = client.post(
            "/api/workspace/import", files={"file": ("data.zip", archive.content)}
        )
        assert restored.is_success, restored.text
        copied = "/api/projects/" + restored.json()["id"]
        edited = next(
            r
            for r in client.get(copied).json()["observations"]
            if r["locator"] == "Table 2"
        )
        assert edited["payload"]["csv_source"] == provenance
        assert client.get(f"{copied}/observations/{edited['id']}/table").content == raw
