"""Bounded CALPHAD fitting with frozen source databases and held-out data.

Coefficients correct existing G/L records only. Site properties are evaluated
at the supplied occupations. Phase-composition targets use constrained phase
equilibria plus a stability penalty against every selected competing phase.
"""
from collections import Counter
import copy
import hashlib
from pathlib import Path
import uuid

import numpy as np
from scipy.optimize import least_squares, linear_sum_assignment
from symengine import Piecewise, S, Symbol, sympify, log
from pycalphad import variables as v

from config import resolve_data_path
from src.gibbs import read_databases
from src.parameter_fit_settings import ParameterFitRequest
from src.phase_diagram import EquilibriumSystem, PRESENT_TOL
from src.phase_diagram_settings import PhaseDiagramRequest
from src.storage import atomic_json, atomic_write


def parameter_key(p):
    groups = ':'.join(','.join(s.name for s in group) for group in p['constituent_array'])
    return f"{p['parameter_type']}({p['phase_name']},{groups};{p['parameter_order']})"


def corrected(expression, delta):
    expression, delta = sympify(expression), sympify(delta)
    if isinstance(expression, Piecewise):
        pairs = list(zip(expression.args[::2], expression.args[1::2]))
        return Piecewise(*[(value if condition == S.true and value == 0 else (value+delta).expand(), condition)
                           for value,condition in pairs])
    # Thermo-Calc's TDB reader rejects arbitrary factored parentheses such as
    # coefficient*(T-Tref). Export the equivalent expanded polynomial.
    return (expression+delta).expand()


def patch_database(db, specs, values, reference_temperature):
    result = copy.deepcopy(db)
    result.symbols = dict(db.symbols)  # pycalphad deepcopy can share the symbol dictionary
    index = {}
    for row in result._parameters.all():
        index.setdefault(parameter_key(row), []).append(row)
    changes = {}
    for spec,value in zip(specs,values):
        if spec.basis == 'constant':
            basis = 1
        elif spec.basis == 'temperature':
            basis = v.T-reference_temperature
        else:
            # A unit coefficient adds a unit heat capacity per formula.
            # G and its T derivative vanish at Tref. Expand the logarithm
            # to LN(T)-LN(Tref), which is supported by native TDB readers.
            basis = v.T-reference_temperature-v.T*(log(v.T)-log(reference_temperature))
        for key in spec.keys:
            if key not in index or len(index[key]) != 1:
                raise ValueError(f'Fit key must identify exactly one existing parameter: {key}')
            row = index[key][0]
            if row['parameter_type'] not in {'G','L'}:
                raise ValueError('Only chemical G/L parameters are fitted; TC/BMAGN remain frozen')
            changes[key] = changes.get(key,S.Zero)+spec.scale*value*basis
    for key,delta in changes.items():
        row = index[key][0]
        result._parameters.update({'parameter':corrected(row['parameter'],delta)}, doc_ids=[row.doc_id])
    return result


class FitProblem:
    def __init__(self, db, request):
        self.request = request
        self.names = [f'ALFIT{i:03}' for i in range(len(request.parameters))]
        if any(name in db.symbols for name in self.names):
            raise ValueError('Source contains reserved ALFIT symbols')
        self.db = patch_database(db, request.parameters, [Symbol(n) for n in self.names], request.reference_temperature)
        self.db.symbols.update({name:S.Zero for name in self.names})
        self.parameters = dict(zip(self.names,[p.initial for p in request.parameters]))
        temperatures = sorted({o.T_K for o in request.observations})
        self.diagram = PhaseDiagramRequest(tdb_files=request.tdb_files, components=request.components,
            phases=request.phases, temperatures=temperatures, pressure=request.pressure,
            mode='point' if len(temperatures)==1 else 'property', composition=request.observations[0].composition,
            sampling_density=request.sampling_density, verify_sampling=True, map_boundaries=False,
            allow_missing_ordered_endmembers=True)
        self.systems = {}
        self.system = self.get_system(request.phases)
        active = set(self.system.phases)
        referenced = {p for o in request.observations for p in ([o.phase] if o.phase else [t.phase for t in o.phases])}
        if not referenced <= active:
            raise ValueError(f'Observation phases excluded/replaced by ordered models: {sorted(referenced-active)}')

    def get_system(self, phases):
        key = tuple(sorted(set(phases)))
        if key not in self.systems:
            request = self.diagram.model_copy(update={'phases':list(key)})
            self.systems[key] = EquilibriumSystem(self.db,request,parameters=self.parameters)
        return self.systems[key]

    def set_parameters(self, values):
        self.parameters = dict(zip(self.names,map(float,values)))
        for system in self.systems.values():
            system.update_parameters(self.parameters)

    def equilibrium(self, system, obs):
        point = dict(point_id=obs.id, T_K=obs.T_K, P_Pa=self.request.pressure, composition=obs.composition)
        row = system.solve(point)
        if row['status'] != 'accepted' or not row['sampling_verified']:
            raise ValueError(f'{obs.id}: equilibrium failed branch/density validation: {row.get("attempts")}')
        return row

    def property_value(self, obs):
        from src.equilibrium_branches import TangentSearch
        record = self.system.records[obs.phase]
        groups = self.system.metadata[obs.phase]['sublattices']
        occupations = [{k.upper():value for k,value in g.items()} for g in obs.site_fractions]
        if len(occupations) != len(groups):
            raise ValueError(f'{obs.id}: wrong number of sublattices')
        for allowed, supplied in zip(groups,occupations):
            if (not set(supplied) <= set(allowed) or any(x<0 or x>1 for x in supplied.values())
                    or abs(sum(supplied.values())-1)>1e-9):
                raise ValueError(f'{obs.id}: invalid site fractions')
        y = np.array([occupations[s.sublattice_index].get(s.species.name,0.) for s in record.variables])
        search = TangentSearch(record,self.db.phases[obs.phase].sublattices)
        total = search.total@y
        if total <= 1e-12:
            raise ValueError('A property observation must contain occupied atoms')
        x = search.atoms@y/total
        if max(abs(x[i]-obs.composition[c]) for i,c in enumerate(record.nonvacant_elements))>1e-8:
            raise ValueError(f'{obs.id}: occupations do not reproduce the stated atomic composition')
        state = {v.N:1.,v.P:self.request.pressure,v.T:obs.T_K}
        dof = np.array([state[s] for s in record.state_variables]+list(y),dtype=float)
        value = np.zeros(1)
        record.prop(value,dof,obs.property.encode('ascii'))
        if not np.isfinite(value[0]):
            raise ValueError(f'{obs.id}: nonfinite property')
        return float(value[0])

    def observe(self, obs):
        if obs.kind == 'property':
            predicted = self.property_value(obs)
            residual = [(predicted-obs.value)/obs.error_scale]
            return residual, dict(id=obs.id,role=obs.role,source=obs.source,kind=obs.kind,
                predicted=predicted,observed=obs.value,property=obs.property,reference_state=obs.reference_state,
                normalized_residual=residual,within_requested_scale=abs(residual[0])<=1)
        restricted = self.equilibrium(self.get_system([t.phase for t in obs.phases]),obs)
        global_row = self.equilibrium(self.system,obs)
        states = [p for p in restricted['phases'] if p['amount']>PRESENT_TOL]
        residual, matches = [], []
        for phase in sorted({t.phase for t in obs.phases}):
            targets = [t for t in obs.phases if t.phase==phase]
            predictions = [p for p in states if p['phase']==phase]
            if len(targets)!=len(predictions):
                raise ValueError(f'{obs.id}: {phase} target/predicted instance count differs; revise starting parameters or phase targets')
            # One-to-one matching prevents both miscibility-gap endpoints from
            # being matched to the same composition set.
            cost = np.array([[sum((t.composition[c]-p['composition'][c])**2 for c in self.request.components) if t.composition else 0.
                              for p in predictions] for t in targets])
            ti,pi = linear_sum_assignment(cost)
            for i,j in zip(ti,pi):
                t,p = targets[i],predictions[j]
                if t.composition is not None:
                    residual += [(p['composition'][c]-t.composition[c])/obs.error_scale for c in self.request.components]
                matches.append(dict(phase=phase,predicted=p['composition'],observed=t.composition,
                                    composition_exclusion_reason=t.composition_exclusion_reason,
                                    site_fractions=p['site_fractions']))
        gap = max(0.,restricted['G_J_mol_atoms']-global_row['G_J_mol_atoms'])
        composition_residual = residual.copy()
        residual.append(gap/self.request.stability_scale_J_mol_atoms)
        expected = Counter(t.phase for t in obs.phases)
        actual = Counter(p['phase'] for p in global_row['phases'] if p['amount']>PRESENT_TOL)
        stable = expected==actual and gap<=1e-3
        return residual,dict(id=obs.id,role=obs.role,source=obs.source,kind=obs.kind,matches=matches,
            normalized_residual=composition_residual,stability_gap_J_mol_atoms=gap,
            restricted_G_J_mol_atoms=restricted['G_J_mol_atoms'],global_G_J_mol_atoms=global_row['G_J_mol_atoms'],
            global_phases=global_row['phases'],
            global_assemblage=global_row['assemblage'],phase_assemblage_matches=expected==actual,
            within_requested_scale=stable and max(map(abs,composition_residual),default=0.)<=1,
            global_minimum_certified=False)

    def evaluate(self, values, role=None):
        self.set_parameters(values)
        residual,records = [],[]
        for obs in self.request.observations:
            if role is not None and obs.role!=role:
                continue
            values,row = self.observe(obs)
            residual.extend(np.sqrt(obs.weight)*np.array(values))
            records.append(row)
        return np.array(residual,dtype=float),records


def fit_parameters(db, request, progress=None):
    request = ParameterFitRequest.model_validate(request)
    problem = FitProblem(db,request)
    initial = np.array([p.initial for p in request.parameters])
    lower,upper = np.array([p.bounds for p in request.parameters]).T
    trace = []
    _,baseline = problem.evaluate(initial)
    best_stable = None

    def assemblages_valid(records):
        return all(r['kind']!='phase_composition' or
                   (r['phase_assemblage_matches'] and r['stability_gap_J_mol_atoms']<=1e-3)
                   for r in records)

    def objective(x):
        nonlocal best_stable
        residual,records = problem.evaluate(x,role='train')
        if request.regularization:
            residual = np.r_[residual,np.sqrt(request.regularization)*(x-initial)]
        score=float(residual@residual)
        stable=assemblages_valid(records)
        if stable and (best_stable is None or score<best_stable['score']):
            best_stable=dict(parameters=x.copy(),score=score,evaluation=len(trace)+1)
        trace.append(dict(evaluation=len(trace)+1,parameters=x.tolist(),sum_squared_residual=score,
                          training_assemblages_valid=stable))
        if progress:
            progress(trace[-1])
        return residual

    def jacobian(x):
        columns=[]
        for i in range(len(x)):
            step=request.finite_difference_step*max(1.,abs(x[i]))
            lo=x.copy(); hi=x.copy()
            lo[i]=max(lower[i],x[i]-step); hi[i]=min(upper[i],x[i]+step)
            columns.append((objective(hi)-objective(lo))/(hi[i]-lo[i]))
        return np.array(columns).T

    fit = least_squares(objective,initial,bounds=(lower,upper),jac=jacobian,max_nfev=request.max_nfev,
                        ftol=1e-8,xtol=1e-8,gtol=1e-8)
    _,optimizer_train = problem.evaluate(fit.x,role='train')
    optimizer_stable=assemblages_valid(optimizer_train)
    selected=fit.x.copy()
    selection='optimizer_solution'
    if request.preserve_training_assemblages and not optimizer_stable:
        if best_stable is None:
            raise ValueError('No evaluated candidate preserves all training phase assemblages; no TDB exported')
        selected=best_stable['parameters'].copy()
        selection='best_evaluated_training_stable'
    _,final = problem.evaluate(selected)
    if request.preserve_training_assemblages and not assemblages_valid([r for r in final if r['role']=='train']):
        raise ValueError('Selected candidate failed repeated training assemblage validation; no TDB exported')
    candidate = patch_database(db,request.parameters,selected,request.reference_temperature)
    parameters = [dict(**p.model_dump(),fitted=float(x),physical_coefficient=float(x*p.scale),
                       near_bound=bool(min(x-p.bounds[0],p.bounds[1]-x)<.01*(p.bounds[1]-p.bounds[0])))
                  for p,x in zip(request.parameters,selected)]
    validation = [r for r in final if r['role']=='validation']
    train_groups={o.independence_group for o in request.observations if o.role=='train'}
    validation_groups={o.independence_group for o in request.observations if o.role=='validation'}
    independent=bool(validation_groups) and None not in (train_groups|validation_groups) and not (train_groups&validation_groups)
    passes = all(r['within_requested_scale'] for r in final)
    result = dict(status='stable_fallback_candidate' if selection!='optimizer_solution' else 'converged_candidate' if fit.success else 'not_converged',optimizer_success=bool(fit.success),
        candidate_selection=selection,candidate_is_optimizer_solution=selection=='optimizer_solution',
        optimizer_parameters=fit.x.tolist(),optimizer_training_assemblages_valid=optimizer_stable,
        training_assemblages_valid=assemblages_valid([r for r in final if r['role']=='train']),
        best_stable_evaluation=best_stable['evaluation'] if best_stable else None,
        termination=str(fit.message),nfev=int(fit.nfev),residual_evaluations=len(trace),parameters=parameters,
        baseline=baseline,observations=final,trace=trace,request=request.model_dump(),
        all_observations_within_requested_scales=passes,
        holdout_validation_passed=bool(validation) and all(r['within_requested_scale'] for r in validation),
        independent_validation_passed=independent and all(r['within_requested_scale'] for r in validation),
        validation_scope='declared_independent_groups' if independent else 'heldout_only' if validation else 'no_holdout',
        ready_for_production=False,global_minimum_certified=False,
        notes=['Error scales are user-specified numerical weights, not inferred experimental uncertainties.',
               'Validation observations never enter the training objective.',
               'Property energies are per mole of occupied atoms; entropy/heat capacity additionally per Kelvin.',
               'Corrections are per TDB formula unit, not per atom. Temperature basis is T-reference_temperature.',
               'Candidate export does not replace or approve the source database.'])
    return result,candidate


def serialize_candidate(candidate, temperatures, pressure):
    from src.tdb_compat import portable_tdb_text
    text=portable_tdb_text(candidate)
    # Reparse exported coefficients; malformed output is never published.
    from pycalphad import Database
    parsed=Database(text.replace('DISORDER_PART','DISORDERED_PART'))
    before={parameter_key(p):p['parameter'] for p in candidate._parameters.all()}
    after={parameter_key(p):p['parameter'] for p in parsed._parameters.all()}
    if before.keys()!=after.keys():
        raise ValueError('Candidate export changed parameter keys')
    for key in before:
        if (before[key]-after[key]).expand()!=0:
            # Serializer rounding is checked numerically over all requested temperatures.
            for t in temperatures:
                # Piecewise branches select only after substitution; expand
                # then so shared GHSER symbols cancel before the free-symbol check.
                delta=(before[key]-after[key]).subs({v.T:t,v.P:pressure}).expand()
                if delta.free_symbols or abs(float(delta))>1e-6:
                    raise ValueError(f'Candidate export changed expression: {key}')
    return text


def run_fit(request, progress=None):
    request = ParameterFitRequest.model_validate(request)
    folder = resolve_data_path('parameter_fits')/('fit_'+uuid.uuid4().hex[:12])
    folder.mkdir(parents=True,exist_ok=False)
    atomic_json(folder/'request.json',request.model_dump())
    sources=[]
    try:
        db,sources=read_databases(request.tdb_files)
        result,candidate=fit_parameters(db,request,progress)
        # Preserve the completed numerical run even if serialization fails.
        # This record is explicitly provisional and is never a published TDB.
        atomic_json(folder/'optimizer_result.json',dict(**result,export_verified=False,sources=sources))
        text=serialize_candidate(candidate,{o.T_K for o in request.observations},request.pressure)
        atomic_write(folder/'candidate.tdb',text.encode('utf-8'),binary=True)
        result.update(sources=sources,candidate_sha256=hashlib.sha256(text.encode()).hexdigest(),
                      files={'result':str(folder/'fit.json'),'candidate':str(folder/'candidate.tdb'),
                             'request':str(folder/'request.json')})
        atomic_json(folder/'fit.json',result)
        return result
    except Exception as exc:
        atomic_json(folder/'failure.json',dict(status='failed',error=f'{type(exc).__name__}: {exc}',sources=sources))
        raise
