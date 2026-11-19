from pathlib import Path
from fastapi.testclient import TestClient
from app import app
from tests.test_fp import batch


def test_job_preview_and_confirm_share_dispatcher(batch, monkeypatch):
    from dpdispatcher import Submission
    path, machine = batch
    monkeypatch.setenv('AL_TDB_MACHINE_DIR',str(machine.parent))
    calls = []
    monkeypatch.setattr(Submission,'run_submission',lambda self,**kw: calls.append(kw))
    monkeypatch.setattr(Submission,'check_all_finished',lambda self: False)
    data={'config':path.name, 'machine':machine.name, 'iteration':0}
    with TestClient(app) as client:
        assert path.name in client.get('/api/jobs/options').json()['runs']
        assert client.post('/api/jobs/submit',json=data,headers={'origin':'https://example.org'}).status_code==403
        plan=client.post('/api/jobs/plan',json=data)
        assert plan.status_code==200, plan.text
        assert not calls and not plan.json()['connects_to_cluster']
        assert client.post('/api/jobs/submit',json=data).status_code==422
        data['confirmation']=plan.json()['confirmation']
        assert client.post('/api/jobs/submit',json={**data,'iteration':1}).status_code==422
        assert not calls
        result=client.post('/api/jobs/submit',json=data)
        assert result.status_code==200 and result.json()['status']=='submitted'
        assert calls[0]['exit_on_submit']
        assert client.post('/api/jobs/recover',json=data).status_code==200
        assert not calls[1]['exit_on_submit']
        assert client.get('/api/jobs/state',params={'config':path.name}).json()['dispatch']['submission_hash']
