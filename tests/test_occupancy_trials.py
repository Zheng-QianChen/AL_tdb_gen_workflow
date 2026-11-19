import itertools

import numpy as np
import pandas as pd
import pytest
from fastapi.testclient import TestClient
from pycalphad import Database

from app import app
from config import BASE_DATA_DIR
from src.main_process.subl_model_assess import subl_assess
from src.occupancy_trials import lower_envelope


def test_mu_restriction_exports_only_selected_occupants(demo):
    import json
    path, config = demo
    allowed = [['FE'], ['NI','W','TA'], ['FE'], ['FE']]
    config['tdb_model'].update(comp=allowed, sublattice_number=4, occup_atoms_in_tdb=[1,4,2,6])
    path.write_text(json.dumps(config))
    folder = BASE_DATA_DIR / path.stem
    source = folder / 'members.csv'
    rows = []
    for atoms in itertools.product(*allowed):
        composition = {e: sum(w for atom,w in zip(atoms,[1,4,2,6]) if atom==e)/13
                       for e in ['FE','NI','W','TA']}
        rows.append({'endmember':':'.join(atoms), 'from':'synthetic', 'Energy':-2.,
                     'above_hull':0., **composition})
    pd.DataFrame(rows).to_csv(source)
    analyzer = subl_assess(path,source,folder)
    with TestClient(app) as client:
        app.state.manager.assessments['mu'] = analyzer
        body = {'selected_model':'4_A_B_C_D.csv', 'fix':[['FE'],['W','TA'],['FE'],['FE']],
                'analys':[[],[],[],[]], 'need_del':[[],['NI'],[],[]]}
        body['protected'] = [{'source':'synthetic Fe-Ni boundary','temperature_K':1000,
                              'composition':{'FE':9/13,'NI':4/13}}]
        result = client.post('/occupancy-trials?task_id=mu',json=body)
        assert result.status_code == 200, result.text
        report = result.json()
        assert report['ratios']==[1,4,2,6]
        base, trial = report['candidates']
        assert base['covered']==3 and trial['covered']==2 and trial['lost']==1
        assert trial['lost_binary_edges'] == ['FE–NI']
        assert trial['removed_sources'] == {'synthetic': 1}
        assert trial['protected_points'][0]['baseline_covered'] and not trial['protected_points'][0]['candidate_covered']
        url = '/occupancy-trials/'+report['id']+'/1/export?task_id=mu'
        exported = client.post(url)
        assert exported.status_code==200, exported.text
        content=client.get(exported.json()['url']).text
        assert ':FE:W,TA:FE:FE:' in content.replace(' ', '')
        assert content.count('PARAMETER G(')==2
        source.write_text(source.read_text()+'\n')
        assert client.post(url).status_code==422


def test_lower_envelope_preserves_outside_and_degenerate_domains():
    coords=np.array([[0,1],[.5,.5],[1,0.]])
    probes=np.array([[0,1],[.5,.5],[.75,.25],[1,0.]])
    assert lower_envelope(coords, np.array([0,-2,0]), probes) == pytest.approx([0,-2,-1,0])
    restricted=lower_envelope(coords[[0,1]],np.array([0,-2]),probes)
    assert np.isnan(restricted[-2:]).all()
    assert restricted[:2] == pytest.approx([0,-2])
