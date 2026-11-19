from io import BytesIO
import json
from zipfile import ZipFile

from fastapi.testclient import TestClient
from app import app


def test_paper_notes_keep_scope_and_survive_archive():
    with TestClient(app) as client:
        pid = client.post("/api/projects",json={"title":"Notes","elements":["Co","Ti"]}).json()["id"]
        base = "/api/projects/"+pid
        body = {"title":"Study","citation":"Table 2","notes":"Observed phases\nAccess: abstract",
                "systems":[["Ti","Co"]]}
        rid = client.post(base+"/papers",json=body).json()["id"]
        assert client.put(base+"/papers/"+rid,json={"title":"Edited","citation":"p.2"}).is_success
        paper = client.get(base).json()["papers"][0]
        assert paper["notes"]==body["notes"] and paper["systems"]==[["Co","Ti"]]
        assert client.put(base+"/papers/"+rid,json=dict(body,systems=[["Al"]])).status_code==422
        saved = client.post(base+"/archive",json={"page":"papers"})
        assert saved.is_success
        with ZipFile(BytesIO(saved.content)) as z:
            manifest = json.loads(z.read("workspace.json"))
        assert manifest["version"]==3
        def restore(blob):
            res = client.post("/api/workspace/import",files={"file":("notes.zip",blob)})
            assert res.is_success, res.text
            return client.get("/api/projects/"+res.json()["id"]).json()["papers"][0]
        copy = restore(saved.content)
        assert copy["notes"]==paper["notes"] and copy["systems"]==paper["systems"]
        manifest["version"]=1
        del manifest["records"]["models"]
        old = manifest["records"]["papers"][0]
        del old["notes"],old["systems"]
        buffer=BytesIO()
        with ZipFile(buffer,"w") as z:
            z.writestr("workspace.json",json.dumps(manifest))
        legacy=restore(buffer.getvalue())
        assert legacy["notes"]=="" and legacy["systems"]==[]
