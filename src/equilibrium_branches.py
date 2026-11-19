"""Deterministic tangent-plane searches and reseeding of missed CEF branches.

Searches supply counterexamples to stability, never a global-optimum certificate.
Compiled phase records are shared with the equilibrium calculation. The chemical
potentials, normalization and selected competing phases are therefore identical.
"""
from itertools import combinations

import numpy as np
from scipy.optimize import Bounds, LinearConstraint, minimize, minimize_scalar


class TangentSearch:
    def __init__(self, record, ratios):
        self.record = record
        self.nsv = len(record.state_variables)
        self.ny = record.phase_dof
        sites = list(record.variables)
        elements = list(record.nonvacant_elements)
        self.atoms = np.zeros((len(elements), self.ny))
        self.groups = [[j for j, site in enumerate(sites) if site.sublattice_index == i]
                       for i in sorted({site.sublattice_index for site in sites})]
        for j, site in enumerate(sites):
            if site.species.name != 'VA':
                self.atoms[elements.index(site.species.name), j] = ratios[site.sublattice_index]
        self.total = self.atoms.sum(axis=0)
        self.base = np.zeros(self.ny)
        columns, self.free = [], []
        for group in self.groups:
            self.base[group[-1]] = 1.
            for j in group[:-1]:
                column = np.zeros(self.ny); column[j] = 1.; column[group[-1]] = -1.
                columns.append(column); self.free.append(j)
        self.jac_y = np.array(columns).T if columns else np.zeros((self.ny, 0))
        self.constraints = []
        if columns:
            matrix = np.array([-self.jac_y[g[-1]] for g in self.groups if len(g) > 1])
            self.constraints = [LinearConstraint(matrix, 0., 1.-1e-12)]

    def evaluate(self, y, state, mu):
        denominator = self.total @ y
        if denominator < 1e-12:
            return None
        dof = np.ascontiguousarray(np.r_[state, y], dtype=float)
        value = np.zeros(1); grad = np.zeros(len(dof))
        self.record.obj(value, dof); self.record.prop_grad(grad, dof, b'GM')
        x = self.atoms @ y / denominator
        dx = (self.atoms-x[:, None]*self.total)/denominator
        tpd = float(value[0]-x@mu)
        derivative = (grad[self.nsv:]-mu@dx) @ self.jac_y
        if not np.isfinite(tpd) or not np.isfinite(derivative).all():
            return None
        return tpd, derivative, float(value[0]), x

    def search(self, state, mu, seeds, starts=8):
        n = len(self.free)
        if not n:
            answer = self.evaluate(self.base, state, mu)
            return [] if answer is None else [dict(tpd=answer[0], y=self.base.copy(),
                                                  energy=answer[2], composition=answer[3])]

        def objective(z):
            y = self.base+self.jac_y@z
            result = self.evaluate(y, state, mu)
            if result is None:
                return 1e20, np.zeros(n)
            return result[0]/10000., result[1]/10000.

        candidates = []
        if n == 1:
            # Capture distinct magnetic wells even when their energy difference
            # is smaller than the ordinary equilibrium acceptance tolerance.
            grid = np.unique(np.r_[np.linspace(1e-12, 1-1e-12, 1001),
                                   np.geomspace(1e-12, .01, 50), 1-np.geomspace(1e-12, .01, 50)])
            values = np.array([objective([x])[0] for x in grid])
            idx = np.flatnonzero((values[1:-1] <= values[:-2]) & (values[1:-1] <= values[2:]))+1
            idx = sorted(idx, key=lambda i: values[i])[:max(8, starts)]
            candidates.extend([np.array([grid[0]]), np.array([grid[-1]])])
            for i in idx:
                fit = minimize_scalar(lambda x: objective([x])[0], bounds=(grid[i-1], grid[i+1]),
                                      method='bounded', options={'xatol':1e-13})
                if fit.success:candidates.append(np.array([fit.x]))
        else:
            initial = [np.array(y, dtype=float) for y in seeds]
            initial.append(np.concatenate([np.full(len(g), 1/len(g)) for g in self.groups]))
            # Diagonal occupations explicitly seed the disordered branch of an
            # ordered model. This is only an initial guess, not an imposed symmetry.
            if all(len(g) in (1, 2) for g in self.groups):
                for x in [.01, .025, .05, .1, .25, .5, .75, .9, .975, .99]:
                    initial.append(np.concatenate([np.array([1.]) if len(g)==1 else np.array([1-x, x]) for g in self.groups]))
            rng = np.random.default_rng(42)
            for _ in range(starts):
                initial.append(np.concatenate([rng.dirichlet(np.ones(len(g))*.6) for g in self.groups]))
            initial = np.unique(np.round(initial, 12), axis=0)
            for y in initial:
                z = y[self.free]
                candidates.append(z.copy())
                fit = minimize(objective, z, jac=True, bounds=Bounds(np.full(n, 1e-12), np.full(n, 1-1e-12)),
                               constraints=self.constraints, method='SLSQP',
                               options={'ftol':1e-13, 'maxiter':250})
                # A non-converged feasible state still supplies a valid lower
                # energy counterexample, but is never called an equilibrium.
                candidates.append(fit.x)
        answers = []
        for z in candidates:
            y = self.base+self.jac_y@z
            if np.min(y) < -1e-9 or np.max(y)>1+1e-9:continue
            result = self.evaluate(y, state, mu)
            if result is None:continue
            if any(np.max(abs(y-a['y'])) < 1e-6 for a in answers):continue
            answers.append(dict(tpd=result[0], y=y, energy=result[2], composition=result[3]))
        return sorted(answers, key=lambda a:a['tpd'])


def branch_candidates(system, sets, mu, state, grid):
    discoveries = []
    for name in system.phases:
        if name not in system.branch_searches:
            system.branch_searches[name] = TangentSearch(system.records[name], system.db.phases[name].sublattices)
        record = system.records[name]
        selected = grid.Phase.reshape(-1)==name
        xx = grid.X.reshape((-1, len(mu)))[selected]
        gg = grid.GM.reshape(-1)[selected]
        yy = grid.Y.reshape((-1, grid.Y.shape[-1]))[selected, :record.phase_dof]
        finite = np.isfinite(gg) & np.isfinite(xx).all(axis=1) & np.isfinite(yy).all(axis=1)
        values = gg[finite]-xx[finite]@mu
        seeds = list(yy[finite][np.argsort(values)[:3]])
        seeds += [np.asarray(cs.dof[len(state):]).copy() for cs in sets if cs.phase_record.phase_name == name]
        found = system.branch_searches[name].search(state, mu, seeds, system.request.branch_starts)
        # A shallow miscibility gap can have two distinct wells below the
        # current tangent. Retaining only the deepest loses the second branch.
        distinct = []
        for item in found:
            if item['tpd'] >= -system.request.branch_tolerance:
                break
            if any(np.max(abs(item['composition']-other['composition'])) < 1e-6
                   for other in distinct):
                continue
            distinct.append(item)
            if len(distinct) >= len(system.elements):
                break
        discoveries.extend((name, item) for item in distinct)
    return discoveries


def refine_branches(system, sets, mu, raw, composition, grid, audit):
    """Retain the lowest audited state and reject unresolved negative TPD."""
    from pycalphad.core.composition_set import CompositionSet
    from pycalphad.core.solver import Solver
    state = np.array([raw[s] for s in system.records.state_variables], dtype=float)
    tolerance = system.request.branch_tolerance
    best = audit(sets, mu, composition)
    original = best['G_J_mol_atoms']
    history = []

    def clone(cs):
        copy = CompositionSet(cs.phase_record)
        copy.update(np.asarray(cs.dof[len(state):]).copy(), float(cs.NP), state)
        return copy

    for round_ in range(system.request.branch_rounds+1):
        discoveries = branch_candidates(system, sets, mu, state, grid)
        worst = max([-item['tpd'] for _,item in discoveries], default=0.)
        history.append({'round':round_, 'negative_tangent_distance_J_mol_atoms':float(worst),
                        'phases_with_lower_states':[name for name,_ in discoveries]})
        if not discoveries:
            best['branch_refinement'] = {'verified':True, 'history':history,
                'energy_decrease_J_mol_atoms':original-best['G_J_mol_atoms'],
                'global_minimum_certified':False}
            return best
        if round_ == system.request.branch_rounds:break
        new = []
        for name, item in discoveries:
            cs = CompositionSet(system.records[name]);cs.update(item['y'], 0., state);new.append(cs)
        trials = [[clone(cs) for cs in sets]+new]
        # Replacing a metastable branch also helps when the Newton solver fails
        # to admit a zero-amount composition set in an almost degenerate system.
        for name,item in discoveries:
            trial=[clone(cs) for cs in sets]
            for cs in trial:
                if cs.phase_record.phase_name == name:
                    cs.update(item['y'], float(cs.NP), state)
            trials.append(trial)
        # Zero-amount additions can be removed or collapse onto the original
        # homogeneous branch before Newton resolves a very shallow split.
        # Replace that *initial guess* with two discovered wells carrying a
        # share of its amount. Neither occupations nor amounts are fixed, and
        # all phases are searched again before accepting the resulting state.
        paired_starts = 0
        for name in dict.fromkeys(name for name, _ in discoveries):
            wells = [item for phase, item in discoveries if phase == name]
            amount = sum(float(cs.NP) for cs in sets if cs.phase_record.phase_name == name)
            if amount <= 1e-8:
                continue
            for left, right in combinations(wells, 2):
                trial = [clone(cs) for cs in sets if cs.phase_record.phase_name != name]
                for item in [left, right]:
                    cs = CompositionSet(system.records[name])
                    cs.update(item['y'], amount/2., state)
                    trial.append(cs)
                trials.append(trial)
                paired_starts += 1
        history[-1]['paired_branch_initializations'] = paired_starts
        improved = False
        for trial in trials:
            try:
                solution = Solver().solve(trial, raw)
                if not solution.converged:continue
                candidate = audit(trial, solution.chemical_potentials, composition)
            except (ValueError, RuntimeError, FloatingPointError, np.linalg.LinAlgError):
                continue
            if candidate['G_J_mol_atoms'] < best['G_J_mol_atoms']-1e-9:
                best, sets, mu = candidate, [clone(cs) for cs in trial], solution.chemical_potentials.copy()
                improved = True
        if not improved:break
    raise ValueError(f'Unresolved branch below tangent plane ({worst:.8g} J/mol-atoms); search history: {history}')
