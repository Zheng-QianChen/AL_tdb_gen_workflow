import json
import numpy as np
import pytest
from pycalphad import Database
from config import resolve_data_path
from src.parameter_fit import fit_parameters, run_fit
from src.parameter_fit_settings import ParameterFitRequest
from src.storage import atomic_write
from tests.test_gibbs import binary_tdb


def test_new_zero_parameter_accepts_symbolic_temperature_correction():
    from src.parameter_fit import corrected
    from pycalphad import variables as v
    assert corrected(0, 2*(v.T-1373.15)) == 2*v.T-2746.3
    assert corrected(0, 0) == 0


def heat_capacity_request():
    req=request();req['observations']=[]
    req['parameters'].append(dict(id='Cp',keys=['G(TEST,AL,NI;0)'],basis='heat_capacity',scale=1.,bounds=[-20,20]))
    a,b,cp,tref=2400.,3.,8.,298.15
    for x in [.2,.6]:
        weight=x*(1-x);base=1000*(1-x)+3000*x
        ideal=8.3145*(x*np.log(x)+(1-x)*np.log(1-x))
        for T in [500.,900.,1100.]:
            common=dict(T_K=T,composition={'AL':1-x,'NI':x},kind='property',phase='TEST',
                site_fractions=[{'AL':1-x,'NI':x}],source='synthetic:integrated heat capacity',
                reference_state='synthetic pure AL=1000 and NI=3000 J/mol atoms',error_scale=1.)
            properties={'HM':base+weight*(a-b*tref+cp*(T-tref)),
                        'SM':-ideal+weight*(-b+cp*np.log(T/tref)),
                        'CPM':weight*cp}
            if T==1100.:
                properties={'GM':base+T*ideal+weight*(a+b*(T-tref)+cp*(T-tref-T*np.log(T/tref)))}
            for prop,value in properties.items():
                req['observations'].append(dict(**common,id=f'{prop}_{x}_{T}',property=prop,value=value,
                    role='validation' if T==1100. else 'train'))
    return req


def test_heat_capacity_fit_recovers_curvature_and_heldout_gibbs_after_export():
    # Cp identifies curvature; independent H/S observables identify the two
    # integration constants. Held-out G and serialized TDB test consistency.
    from src.parameter_fit import FitProblem
    atomic_write(resolve_data_path('fit_input.tdb'),source())
    original=resolve_data_path('fit_input.tdb').read_bytes()
    req=heat_capacity_request();result=run_fit(req)
    assert result['optimizer_success'] and result['holdout_validation_passed']
    assert [p['physical_coefficient'] for p in result['parameters']]==pytest.approx([2400,3,8],abs=2e-5)
    assert resolve_data_path('fit_input.tdb').read_bytes()==original
    exported=Database(resolve_data_path(result['files']['candidate']).read_text())
    zero=ParameterFitRequest.model_validate(req)
    problem=FitProblem(exported,zero)
    for obs in zero.observations:
        assert problem.property_value(obs)==pytest.approx(obs.value,abs=1e-6)


def test_heat_capacity_basis_has_zero_reference_enthalpy_entropy_and_keeps_range():
    from src.parameter_fit import patch_database,parameter_key
    from src.parameter_fit_settings import FitParameter
    from pycalphad import variables as v
    p=FitParameter(id='Cp',keys=['G(TEST,AL,NI;0)'],basis='heat_capacity',scale=1.,bounds=[-20,20])
    db=patch_database(Database(source()),[p],[8.],800.)
    expr=next(q['parameter'] for q in db._parameters.all() if parameter_key(q)==p.keys[0])
    assert float(expr.subs({v.T:800}))==pytest.approx(0,abs=1e-10)
    assert float(expr.diff(v.T).subs({v.T:800}))==pytest.approx(0,abs=1e-10)
    assert float((-v.T*expr.diff(v.T,2)).subs({v.T:1200}))==pytest.approx(8)
    assert float(expr.subs({v.T:100}))==0  # Original TDB range is retained.


def request():
    # H and S independently identify A+B*(T-298.15). Deliberately leave GM
    # held out so the test also checks thermodynamic consistency of the fit.
    observations=[]
    a,b=2400.,3.
    for x in [.2,.6]:
        common=dict(T_K=800.,composition={'AL':1-x,'NI':x},kind='property',phase='TEST',
                    site_fractions=[{'AL':1-x,'NI':x}],source='synthetic:analytic regular solution',
                    reference_state='synthetic pure AL=1000 and NI=3000 J/mol-atoms',error_scale=1.)
        base=1000*(1-x)+3000*x
        ideal=8.3145*(x*np.log(x)+(1-x)*np.log(1-x))
        observations += [dict(**common,id=f'h{x}',property='HM',value=base+x*(1-x)*(a-b*298.15)),
                         dict(**common,id=f's{x}',property='SM',value=-ideal-x*(1-x)*b),
                         dict(**common,id=f'g{x}',property='GM',value=base+800*ideal+x*(1-x)*(a+b*(800-298.15)),role='validation')]
    return dict(tdb_files=['fit_input.tdb'],components=['AL','NI'],phases=['TEST'],observations=observations,
                parameters=[dict(id='A',keys=['G(TEST,AL,NI;0)'],scale=1000.,bounds=[-10,10]),
                            dict(id='B',keys=['G(TEST,AL,NI;0)'],basis='temperature',scale=1.,bounds=[-10,10])])


def source():
    return binary_tdb(interactions=True).replace('298.15 10000;6000','298.15 0;6000')


def test_fit_recovers_parameters_without_using_validation_or_mutating_source():
    db=Database(source()); original=db.to_string(fmt='tdb')
    result,candidate=fit_parameters(db,request())
    assert result['optimizer_success']
    assert [p['physical_coefficient'] for p in result['parameters']]==pytest.approx([2400,3],abs=1e-5)
    assert result['holdout_validation_passed']
    assert not result['independent_validation_passed']
    assert result['validation_scope']=='heldout_only'
    assert db.to_string(fmt='tdb')==original
    altered=request()
    for obs in altered['observations']:
        if obs.get('role')=='validation':
            obs['value']+=500
    other,_=fit_parameters(db,altered)
    assert [p['fitted'] for p in other['parameters']]==pytest.approx([p['fitted'] for p in result['parameters']],abs=1e-8)
    assert not other['holdout_validation_passed']


def test_validation_independence_requires_declared_disjoint_source_groups():
    req=request()
    for obs in req['observations']:
        obs['independence_group']='same-publication'
    result,_=fit_parameters(Database(source()),req)
    assert result['holdout_validation_passed']
    assert not result['independent_validation_passed']
    for obs in req['observations']:
        obs['independence_group']='independent-measurements' if obs.get('role')=='validation' else 'training-measurements'
    result,_=fit_parameters(Database(source()),req)
    assert result['independent_validation_passed']
    assert result['validation_scope']=='declared_independent_groups'


def test_presence_only_target_retains_assemblage_check_and_exclusion_reason():
    from src.parameter_fit import FitProblem
    req=request()
    req['observations']=[dict(id='presence',kind='phase_composition',T_K=1200.,
        composition={'AL':.6,'NI':.4},source='synthetic:presence only',error_scale=.01,
        phases=[dict(phase='TEST',composition=None)])]
    with pytest.raises(ValueError,match='exclusion'):
        ParameterFitRequest.model_validate(req)
    req['observations'][0]['phases'][0]['composition_exclusion_reason']='Endpoint measurement reported unreliable'
    validated=ParameterFitRequest.model_validate(req)
    problem=FitProblem(Database(source()),validated)
    residual,row=problem.observe(validated.observations[0])
    assert residual==pytest.approx([0.],abs=1e-6)
    assert row['phase_assemblage_matches']
    assert row['global_phases'][0]['phase']=='TEST'
    assert row['global_G_J_mol_atoms']==pytest.approx(row['restricted_G_J_mol_atoms'],abs=1e-6)
    assert row['normalized_residual']==[]
    assert row['matches'][0]['observed'] is None
    assert 'unreliable' in row['matches'][0]['composition_exclusion_reason']
    assert row['matches'][0]['predicted']['NI']==pytest.approx(.4,abs=1e-6)


def test_export_and_reload_isolated_candidate():
    annotated = source().replace('G(TEST,AL,NI;0) 298.15 0;6000 N !',
                                 'G(TEST,AL,NI;0) 298.15 0;6000 N REFTEST !')
    annotated += "\nLIST_OF_REFERENCES NUMBER SOURCE\nREFTEST 'Synthetic regression source'\n!\n"
    path=resolve_data_path('fit_input.tdb');atomic_write(path,annotated)
    old=path.read_bytes()
    result=run_fit(request())
    assert path.read_bytes()==old
    assert result['sources'][0]['sha256']
    assert 'ALFIT' not in resolve_data_path(result['files']['candidate']).read_text()
    candidate_text=resolve_data_path(result['files']['candidate']).read_text()
    assert 'LOCAL MODIFICATION' in candidate_text
    assert 'Synthetic regression source' in candidate_text
    assert json.loads(resolve_data_path(result['files']['result']).read_text())['optimizer_success']


def test_export_rounding_cancels_reference_symbols_after_selecting_piecewise(monkeypatch):
    import src.parameter_fit as module
    from pycalphad import variables as v
    from symengine import Piecewise,Symbol,And,S
    atomic_write(resolve_data_path('fit_input.tdb'),source())
    candidate=Database(source())
    row=next(p for p in candidate._parameters.all() if module.parameter_key(p)=='G(TEST,AL;0)')
    expression=Piecewise((-62115.415440805345+3*Symbol('GHSERAL')+Symbol('GHSERNI')
        +33.9684322759383*v.T-.00130978391697406*(v.T-1173),And(v.T>=298.15,v.T<6000)),(0,S.true))
    candidate._parameters.update({'parameter':expression},doc_ids=[row.doc_id])
    monkeypatch.setattr(module,'fit_parameters',lambda *args: ({'optimizer_success':True},candidate))
    result=run_fit(request())
    parsed=Database(resolve_data_path(result['files']['candidate']).read_text())
    after=next(p['parameter'] for p in parsed._parameters.all() if module.parameter_key(p)=='G(TEST,AL;0)')
    assert abs(float((expression-after).subs({v.T:800}).expand()))<1e-6


def test_rejects_unsafe_or_inconsistent_fit_inputs():
    req=request();req['parameters'][0]['keys']=['TC(TEST,AL;0)']
    with pytest.raises(ValueError,match='exactly one|chemical'):
        fit_parameters(Database(source()),req)
    req=request();req['observations'][0]['site_fractions']=[{'AL':.5,'NI':.5}]
    with pytest.raises(ValueError,match='occupations'):
        fit_parameters(Database(source()),req)
    req=request();req['parameters'][0]['bounds']=[0,0]
    with pytest.raises(ValueError,match='lower'):
        ParameterFitRequest.model_validate(req)


def test_tie_line_fit_uses_two_distinct_composition_sets():
    from scipy.optimize import brentq
    temperature=400.
    x=brentq(lambda x:8.3145*temperature*np.log(x/(1-x))+12000*(1-2*x),1e-6,.4)
    req=dict(tdb_files=['unused.tdb'],components=['AL','NI'],phases=['TEST'],sampling_density=30,max_nfev=12,
        parameters=[dict(id='L',keys=['G(TEST,AL,NI;0)'],scale=1000,bounds=[-1,5])],
        observations=[dict(id='gap',kind='phase_composition',T_K=temperature,composition={'AL':.5,'NI':.5},
            source='synthetic:regular-solution common tangent',error_scale=.001,
            phases=[dict(phase='TEST',composition={'AL':1-x,'NI':x}),dict(phase='TEST',composition={'AL':x,'NI':1-x})])])
    result,_=fit_parameters(Database(binary_tdb(interactions=True)),req)
    assert result['optimizer_success']
    assert result['parameters'][0]['physical_coefficient']==pytest.approx(2000,abs=.1)
    matches=result['observations'][0]['matches']
    assert abs(matches[0]['predicted']['NI']-matches[1]['predicted']['NI'])>.8


def test_cli_and_api_share_fitting_and_serve_candidate(tmp_path,capsys):
    from altdb.cli import main
    from fastapi.testclient import TestClient
    from app import app
    atomic_write(resolve_data_path('fit_input.tdb'),source())
    path=tmp_path/'fit.json';path.write_text(json.dumps(request()),encoding='utf-8')
    assert main(['--json','fit',str(path)])==0
    assert json.loads(capsys.readouterr().out)['holdout_validation_passed']
    with TestClient(app) as client:
        assert client.get('/parameter-fit').status_code==200
        assert client.post('/parameter-fit/demo').json()['synthetic']
        response=client.post('/parameter-fit/calculate',json=request())
        assert response.status_code==200,response.text
        result=response.json()
        assert result['optimizer_success']
        assert client.get(result['urls']['candidate']).status_code==200
        invalid=client.post('/parameter-fit/calculate',json={**request(),'tdb_files':['../outside.tdb']})
        assert invalid.status_code==422


def test_unstable_optimizer_solution_cannot_replace_stable_training_candidate():
    text=source()
    rival=text[text.index('PHASE TEST'):].replace('TEST','RIVAL').replace('GHSERAL#','GHSERAL#+100').replace('GHSERNI#','GHSERNI#+100')
    req=dict(tdb_files=['unused.tdb'],components=['AL','NI'],phases=['TEST','RIVAL'],sampling_density=20,max_nfev=8,
        parameters=[dict(id='offset',keys=['G(TEST,AL;0)','G(TEST,NI;0)'],scale=1000,bounds=[-.2,1])],
        stability_scale_J_mol_atoms=1000,
        observations=[dict(id='g',kind='property',phase='TEST',property='GM',T_K=1000,
            composition={'AL':.5,'NI':.5},site_fractions=[{'AL':.5,'NI':.5}],value=2500-8.3145*1000*np.log(2),
            reference_state='synthetic',source='synthetic competing ideal phases',error_scale=1),
            dict(id='presence',kind='phase_composition',T_K=1000,composition={'AL':.5,'NI':.5},
                 phases=[dict(phase='TEST',composition_exclusion_reason='synthetic identity constraint')],
                 source='synthetic competing ideal phases',error_scale=.01)])
    unsafe,_=fit_parameters(Database(text+rival),{**req,'preserve_training_assemblages':False})
    assert not unsafe['training_assemblages_valid']
    safe,_=fit_parameters(Database(text+rival),req)
    assert safe['optimizer_success']
    assert not safe['optimizer_training_assemblages_valid']
    assert safe['training_assemblages_valid']
    assert safe['candidate_selection']=='best_evaluated_training_stable'
    assert not safe['candidate_is_optimizer_solution']
    assert safe['parameters'][0]['physical_coefficient']<100


@pytest.mark.parametrize('changed',[{'candidate_is_optimizer_solution':False},
                                  {'training_assemblages_valid':False}])
def test_cli_does_not_label_fallback_or_unstable_candidate_success(monkeypatch,tmp_path,changed):
    from argparse import Namespace
    from altdb.cli import execute
    import src.parameter_fit as module
    path=tmp_path/'request.json';path.write_text('{}')
    result=dict(optimizer_success=True,candidate_is_optimizer_solution=True,
                training_assemblages_valid=True,all_observations_within_requested_scales=True)
    result.update(changed)
    monkeypatch.setattr(module,'run_fit',lambda *args,**kwargs:result)
    code,returned=execute(Namespace(command='fit',request=str(path)))
    assert code==7 and returned==result
