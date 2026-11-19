"""Synthetic recoverable A+B(T-298.15) fitting example; no material claims."""
import math
import uuid
from config import resolve_data_path
from src.storage import atomic_json, atomic_write


def prepare_demo():
    root=resolve_data_path('parameter_fit_examples')/('demo_'+uuid.uuid4().hex[:12])
    tdb='''$ SYNTHETIC REGULAR SOLUTION: NOT A MATERIAL DATABASE
ELEMENT AL FCC_A1 26.9815 0.0 0.0 !
ELEMENT NI FCC_A1 58.6934 0.0 0.0 !
TYPE_DEFINITION % SEQ * !
PHASE TEST % 1 1 !
CONSTITUENT TEST :AL,NI: !
PARAMETER G(TEST,AL;0) 298.15 1000.0; 6000.0 N !
PARAMETER G(TEST,NI;0) 298.15 3000.0; 6000.0 N !
PARAMETER G(TEST,AL,NI;0) 298.15 0.0; 6000.0 N !
'''
    observations=[]
    for x in [.2,.6]:
        common=dict(T_K=800.,composition={'AL':1-x,'NI':x},kind='property',phase='TEST',
                    site_fractions=[{'AL':1-x,'NI':x}],source='synthetic:analytic regular solution A=2400,B=3',
                    reference_state='synthetic pure AL=1000 and NI=3000 J/mol-atoms',error_scale=1.)
        base=1000*(1-x)+3000*x
        ideal=8.3145*(x*math.log(x)+(1-x)*math.log(1-x))
        observations += [dict(**common,id=f'h{x}',property='HM',value=base+x*(1-x)*(2400-3*298.15)),
                         dict(**common,id=f's{x}',property='SM',value=-ideal-x*(1-x)*3),
                         dict(**common,id=f'g{x}',property='GM',value=base+800*ideal+x*(1-x)*(2400+3*(800-298.15)),role='validation')]
    request=dict(tdb_files=[str(root/'input.tdb')],components=['AL','NI'],phases=['TEST'],observations=observations,
        parameters=[dict(id='A',keys=['G(TEST,AL,NI;0)'],scale=1000.,bounds=[-10,10]),
                    dict(id='B',keys=['G(TEST,AL,NI;0)'],basis='temperature',scale=1.,bounds=[-10,10])])
    atomic_write(root/'input.tdb',tdb)
    atomic_json(root/'request.json',request)
    return {'request':request,'request_file':str(root/'request.json'),'synthetic':True}


if __name__=='__main__':
    import json
    print(json.dumps(prepare_demo(),ensure_ascii=False))
