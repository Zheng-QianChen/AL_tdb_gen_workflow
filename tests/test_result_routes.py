from fastapi.testclient import TestClient

from app import app
from routes import result_routes
from src.result_records import ResultConflictError


def test_results_page_and_config_picker(demo):
    path, _ = demo
    with TestClient(app) as client:
        assert client.get('/results').status_code == 200
        assert path.name in client.get('/api/results/configs').json()['configs']
        assert client.get('/static/results.js').status_code == 200


def test_results_api_rejects_outside_config_and_bad_revision(demo, tmp_path):
    path, _ = demo
    outside = tmp_path / 'outside.json'
    outside.write_text('{}')
    with TestClient(app) as client:
        assert client.get('/api/results', params={'config': str(outside)}).status_code == 422
        assert client.get('/api/results', params={'config': str(path), 'iteration': -1}).status_code == 422
        result = client.patch('/api/results/example', params={'config': str(path)}, json={
            'expected_revision': -1, 'actor': 'reviewer', 'reason': 'correction', 'energy_ev_cell': -8,
        })
        assert result.status_code == 422


def test_amendment_passes_actor_reason_and_reports_conflict(demo, monkeypatch):
    path, _ = demo
    received = {}
    def revise(config, record_id, **kwargs):
        received.update(kwargs)
        assert config == path.resolve()
        assert record_id == 'r1'
        raise ResultConflictError('stale revision')
    monkeypatch.setattr(result_routes, 'revise_result', revise)
    with TestClient(app) as client:
        result = client.patch('/api/results/r1', params={'config': path.name}, json={
            'expected_revision': 2, 'actor': 'researcher', 'reason': 'verified reference',
            'energy_ev_cell': -8.25, 'note': 'corrected energy',
        })
    assert result.status_code == 409
    assert received == {'changes': {'energy_ev_cell': -8.25, 'note': 'corrected energy'},
                        'actor': 'researcher', 'reason': 'verified reference', 'expected_revision': 2}


def test_empty_or_null_amendment_is_rejected(demo):
    path, _ = demo
    with TestClient(app) as client:
        for extra in ({}, {'energy_ev_cell': None}, {'note': None}):
            result = client.patch('/api/results/r1', params={'config': path.name}, json={
                'expected_revision': 1, 'actor': 'researcher', 'reason': 'checked', **extra})
            assert result.status_code == 422
