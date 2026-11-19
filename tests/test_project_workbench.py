"""Project separation, literature lineage and fitting with synthetic Al–Ce observations."""

from fastapi.testclient import TestClient
from pymatgen.core import Lattice, Structure
from app import app


def test_project_round_trip_and_shared_structure(monkeypatch, tmp_path):
    monkeypatch.delenv("AL_TDB_PANDAT_FIT_ADAPTER", raising=False)
    with TestClient(app) as c:

        def post(path, body):
            response = c.post(path, json=body)
            assert response.is_success, response.text
            return response.json()

        def new(title, elements):
            pid = post("/api/projects", dict(title=title, elements=elements))["id"]
            return f"/api/projects/{pid}"

        p = new("Synthetic Al–Ce", ["Al", "Ce"])
        second = new("Another Al–Ce–La", ["Al", "Ce", "La"])
        other = new("Different", ["Al", "La"])
        s = Structure(Lattice.cubic(4), ["Al", "Ce"], [[0, 0, 0], [0.5, 0.5, 0.5]])
        from routes import project_routes

        monkeypatch.setattr(
            project_routes,
            "fetch_structures",
            lambda provider, system, offset: ([("test-id", s)], 1),
        )
        query = dict(provider="oqmd", elements=["Ce", "Al"])
        sid = post(p + "/structures/search", query)["ids"][0]
        assert post(second + "/structures/search", query)["ids"] == [sid]
        assert c.get(other + "/structures/" + sid).status_code == 422
        private = post(
            p + "/structures", dict(ref="private test", cif=s.to(fmt="cif"))
        )["id"]
        assert c.get(second + "/structures/" + private).status_code == 404
        comparison = c.get(p + "/compare", params={"first": private, "second": sid})
        assert comparison.status_code == 200, comparison.text
        assert comparison.json()["元素角色一一对应后同型"]
        assert comparison.json()["第一份结构"]["原胞平移指数"] == 2
        assert (
            c.patch(
                other, json={"title": "Extended", "elements": ["Al", "La", "Nd"]}
            ).status_code
            == 200
        )
        ph = post(
            p + "/phases",
            dict(alias="test prototype", name="test", system=["Al", "Ce"]),
        )["id"]
        post(p + "/links", dict(phase=ph, structure=sid))
        paper = post(
            p + "/papers", dict(title="Synthetic source", citation="Synthetic test 1")
        )["id"]
        res = c.post(
            p + "/papers/" + paper + "/pdf",
            files={"file": ("test.pdf", b"%PDF-1.4 test", "application/pdf")},
        )
        assert res.status_code == 200, res.text
        assert c.get(second).json()["papers"] == []
        assert (
            c.post(second + "/links", json=dict(phase=ph, structure=sid)).status_code
            == 404
        )
        rec = dict(
            paper=paper,
            phase=ph,
            locator="Table 1",
            payload=dict(
                kind="property",
                property="HM",
                T_K=800,
                composition={"Al": 0.5, "Ce": 0.5},
                site_fractions=[{"AL": 0.5, "CE": 0.5}],
                value=2500,
                reference_state="synthetic",
                error_scale=1,
            ),
        )
        oid = post(p + "/observations", rec)["id"]
        assert (
            c.put(
                p + "/observations/" + oid, json=rec | {"locator": "Table 1, row 2"}
            ).status_code
            == 200
        )
        body = """$ synthetic test only
ELEMENT AL FCC_A1 26.9815 0 0 !
ELEMENT CE FCC_A1 140.116 0 0 !
TYPE_DEFINITION % SEQ * !
PHASE TEST % 1 1 !
CONSTITUENT TEST :AL,CE: !
PARAMETER G(TEST,AL;0) 298.15 1000; 6000 N !
PARAMETER G(TEST,CE;0) 298.15 3000; 6000 N !
PARAMETER G(TEST,AL,CE;0) 298.15 0; 6000 N !
"""
        inp = post(p + "/inputs", dict(name="synthetic.tdb", text=body, paper=paper))[
            "id"
        ]
        assert c.get(f"{p}/inputs/{inp}/phases").json()["phases"] == ["TEST"]
        assert c.get(f"{second}/inputs/{inp}/phases").status_code == 404
        cfg = dict(
            inputs=[inp],
            observations=[oid],
            components=["Al", "Ce"],
            phases=["TEST"],
            parameters=[
                dict(id="A", keys=["G(TEST,AL,CE;0)"], scale=1000, bounds=[-10, 10])
            ],
        )
        assert post(p + "/fit/pandat", cfg)["mode"] == "external_request"
        fit = post(p + "/fit/native", cfg)
        assert (
            abs(fit["summary"]["parameters"][0]["physical_coefficient"] - 2000) < 1e-3
        )
        assert c.get(p + "/fits/" + fit["id"] + "/candidate").status_code == 200
        assert c.get(second + "/fits/" + fit["id"] + "/candidate").status_code == 404
        detail = c.get(p).json()
        assert detail["phases"][0]["name"] == "TEST"
        assert detail["observations"][0]["locator"] == "Table 1, row 2"
        assert len([r for r in detail["revisions"] if r["entity"] == oid]) == 2
        assert (
            c.get(second + "/pdf/" + detail["attachments"][0]["id"]).status_code == 404
        )

        # Restore against a fresh catalog as on a different workstation.
        import io
        import json
        import zipfile
        import config
        view = {"page": "papers", "picks": {"papers": paper}, "scope": "Al–Ce"}
        bundle = c.post(p + "/archive", json=view)
        assert bundle.status_code == 200, bundle.text[:200] if not bundle.is_success else ""
        with zipfile.ZipFile(io.BytesIO(bundle.content)) as archive:
            manifest = json.loads(archive.read("workspace.json"))
            assert manifest["project"]["title"] == "Synthetic Al–Ce"
            assert set(manifest["records"]["fits"][0]["files"]) >= {"candidate.tdb", "request.json", "fit.json"}
        monkeypatch.setattr(config, "BASE_DATA_DIR", tmp_path)
        def restore(raw):
            return c.post("/api/workspace/import", files={"file": ("desk.zip", raw, "application/zip")})
        result = restore(bundle.content)
        assert result.status_code == 201, result.text
        new_path = "/api/projects/" + result.json()["id"]
        clone = c.get(new_path).json()
        assert len(c.get("/api/projects").json()) == 1
        assert clone["id"] != detail["id"] and clone["elements"] == detail["elements"]
        assert result.json()["view"]["picks"]["papers"] == clone["papers"][0]["id"] != paper
        assert clone["observations"][0]["paper"] == clone["papers"][0]["id"]
        assert clone["observations"][0]["phase"] == clone["phases"][0]["id"]
        assert clone["links"] == [{"phase": clone["phases"][0]["id"], "structure": sid}]
        assert c.get(new_path+"/structures/"+sid).json()["晶胞对照"]["原胞平移指数"] == 2
        assert len(clone["structures"]) == 2
        assert c.get(new_path+"/pdf/"+clone["attachments"][0]["id"]).content == b"%PDF-1.4 test"
        assert c.get(new_path+"/inputs/"+clone["inputs"][0]["id"]+"/phases").json()["phases"] == ["TEST"]
        assert c.get(new_path+"/fits/"+clone["fits"][0]["id"]+"/candidate").is_success
        assert len(clone["revisions"]) == len(detail["revisions"])
        assert len([r for r in clone["revisions"] if r["entity"]==clone["observations"][0]["id"]]) == 2
        assert restore(bundle.content).status_code == 201
        # A corrupt payload discovered late must never leave a partial project.
        damaged = io.BytesIO()
        with zipfile.ZipFile(io.BytesIO(bundle.content)) as src, zipfile.ZipFile(damaged, "w") as output:
            target = "blobs/"+manifest["records"]["fits"][0]["files"]["candidate.tdb"]
            for name in src.namelist():
                output.writestr(name, b"damaged" if name==target else src.read(name))
        before = c.get("/api/projects").json()
        assert restore(damaged.getvalue()).status_code == 422
        assert c.get("/api/projects").json() == before
        project_settings = manifest["project"]
        first = post("/api/workspace/settings", project_settings)
        again = post("/api/workspace/settings", project_settings)
        assert first == {"id": detail["id"], "created": True}
        assert again == {"id": detail["id"], "created": False}
        blank = c.get(p).json()
        assert blank["papers"] == [] and blank["inputs"] == [] and blank["fits"] == []


def test_local_fit_adapter_requires_parseable_named_phase(tmp_path, monkeypatch):
    from pathlib import Path
    from types import SimpleNamespace
    from src import fit_adapter
    from examples.parameter_fit_demo import prepare_demo
    from src.parameter_fit_settings import ParameterFitRequest

    req = ParameterFitRequest.model_validate(prepare_demo()["request"])

    def fake_run(args, **kwargs):
        assert kwargs["shell"] is False
        Path(args[-1]).write_bytes(Path(req.tdb_files[0]).read_bytes())
        return SimpleNamespace(returncode=0)

    monkeypatch.setattr(fit_adapter.subprocess, "run", fake_run)
    path, summary = fit_adapter.run_adapter("pandat", tmp_path / "adapter.exe", req)
    assert Path(path).is_file() and summary["engine"] == "pandat"


def test_providers_read_coordinates_and_keep_the_key_on_server(monkeypatch):
    from src import structure_sources as ss

    s = Structure(Lattice.cubic(4), ["Al", "Ce"], [[0, 0, 0], [0.5, 0.5, 0.5]])

    class Response:
        status_code = 200

        def __init__(self, row):
            self.row = row

        def json(self):
            return {"data": [self.row]}

    def fetch(url, params, headers, timeout, allow_redirects):
        if "materialsproject.org" in url:
            assert headers["X-API-KEY"] == "test-only" and params["chemsys"] == "Al-Ce"
            return Response({"material_id": "mp-test", "structure": s.as_dict()})
        assert not headers and params["composition"] == "Al-Ce"
        return Response(
            dict(
                entry_id=123,
                sites=["Al @ 0 0 0", "Ce @ 0.5 0.5 0.5"],
                unit_cell=s.lattice.matrix.tolist(),
            )
        )

    monkeypatch.setattr(ss.requests, "get", fetch)
    monkeypatch.setenv("MP_API_KEY", "test-only")
    for provider in ("mp", "oqmd"):
        rows, count = ss.fetch_structures(provider, ["Al", "Ce"])
        assert count == 1 and rows[0][1] == s
