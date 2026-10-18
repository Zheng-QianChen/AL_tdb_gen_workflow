"""Multi-phase CALPHAD calculations with explicit numerical audits.

The small cached-grid adapter below follows pycalphad 0.11's Workspace.recompute
path. A separate convex-hull start and equilibrium solve is made at every point;
only the sampled energy surface and compiled phase records are shared.
"""
from collections import Counter, OrderedDict
import hashlib
import itertools
from pathlib import Path
import uuid
import warnings

import numpy as np

from config import resolve_data_path
from src.gibbs import GibbsModel, read_databases
from src.phase_diagram_settings import DiagramSource, PhaseDiagramRequest
from src.storage import atomic_json

FRACTION_TOL = 1e-7
ENERGY_TOL = 0.1  # J/mol-atoms, absolute; no relative-to-reference-state test
PRESENT_TOL = 1e-8


def materialize_source(source, folder):
    files = list(source.tdb_files)
    checkpoint = None
    if source.config:
        from src.workflow import load_config, read_checkpoint
        from src.tdb_generator import tdb_generate_from_MLmodel
        path, data = load_config(source.config)
        saved = read_checkpoint(data)
        if saved is None:
            raise ValueError("Train the workflow before using its phase in a diagram")
        exported = tdb_generate_from_MLmodel(resolve_data_path(data["AL_set"]["pkl_phase_path"]),
            iter=saved["iter"], process=saved["process"], user="phase-diagram", file_path=folder / "phase")
        files.append(str(exported["file_path"] / exported["file_name_tdb"]))
        checkpoint = {"config": str(path), "checkpoint": saved["checkpoint"], "input_hashes": saved["input_hashes"]}
    db, sources = read_databases(files)
    return db, sources, checkpoint


def diagram_options(source):
    source = DiagramSource.model_validate(source)
    db, sources, _ = materialize_source(source, resolve_data_path("phase_diagrams") / ("source_" + uuid.uuid4().hex[:12]))
    return {"components": sorted(db.elements - {"VA", "/-"}), "sources": sources,
            "phases": [{"name": name, "sublattices": [sorted(s.name for s in group) for group in phase.constituents],
                        "site_ratios": list(phase.sublattices), "model_hints": phase.model_hints}
                       for name, phase in sorted(db.phases.items())]}


def conditions_grid(request):
    """Return paired compositions, never a Cartesian product of path coordinates."""
    components = request.components
    axis = request.x_component or components[-1]
    if request.mode == "binary":
        other = next(c for c in components if c != axis)
        path = [(float(x), {axis: float(x), other: float(1-x)})
                for x in np.linspace(*request.composition_range, request.points)]
    elif request.mode == "isopleth":
        path = [(float(f), {c: float((1-f)*request.composition_start[c] + f*request.composition_end[c]) for c in components})
                for f in np.linspace(0, 1, request.points)]
    elif request.mode == "ternary":
        n = request.points - 1
        path = [(None, dict(zip(components, [i/n, j/n, (n-i-j)/n])))
                for i in range(n+1) for j in range(n+1-i)]
    else:
        path = [(None, request.composition)]
    return [{"point_id": idx, "T_K": float(t), "P_Pa": request.pressure, "path_coordinate": coordinate,
             "composition": composition}
            for idx, (t, (coordinate, composition)) in enumerate(itertools.product(request.temperatures, path))]


def audit_state(sets, chemical_potentials, composition, total_energy=None):
    """Check thermodynamic identities without interpreting solver exit codes as proof."""
    if not sets:
        raise ValueError("No equilibrium composition sets")
    elements = list(sets[0].phase_record.nonvacant_elements)
    mu = np.asarray(chemical_potentials, dtype=float)
    if len(mu) != len(elements) or not np.isfinite(mu).all():
        raise ValueError("Nonfinite or incomplete chemical potentials")
    amount_error = abs(sum(float(cs.NP) for cs in sets) - 1)
    mass = sum(float(cs.NP)*np.asarray(cs.X) for cs in sets)
    mass_error = max(abs(mass[i]-composition[c]) for i, c in enumerate(elements))
    energy = sum(float(cs.NP)*float(cs.energy) for cs in sets)
    energy_error = abs(energy-total_energy) if total_energy is not None else 0.
    site_error, tangent_error = 0., 0.
    records = []
    for cs in sets:
        record = cs.phase_record
        y = np.asarray(cs.dof)[len(record.state_variables):]
        x = np.asarray(cs.X)
        if not np.isfinite(np.r_[cs.NP, cs.energy, y, x]).all():
            raise ValueError("Nonfinite equilibrium state")
        if (cs.NP < -FRACTION_TOL or cs.NP > 1+FRACTION_TOL or np.min(y) < -FRACTION_TOL
                or np.max(y) > 1+FRACTION_TOL or np.min(x) < -FRACTION_TOL or np.max(x) > 1+FRACTION_TOL):
            raise ValueError("Equilibrium fractions outside [0, 1]")
        site_sums = {}
        site_values = {}
        for site, value in zip(record.variables, y):
            index = site.sublattice_index
            site_sums[index] = site_sums.get(index, 0.) + float(value)
            site_values[f"Y_{index}_{site.species.name}"] = float(value)
        site_error = max(site_error, abs(float(x.sum())-1), *(abs(value-1) for value in site_sums.values()))
        tangent_error = max(tangent_error, abs(float(cs.energy) - float(x @ mu)))
        records.append({"phase": str(record.phase_name), "amount": float(cs.NP),
                        "composition": dict(zip(elements, x.tolist())), "site_fractions": site_values,
                        "G_J_mol_atoms": float(cs.energy)})
    audit = {"mass_balance_error": float(mass_error), "phase_fraction_sum_error": float(amount_error),
             "site_sum_error": float(site_error), "energy_balance_error_J_mol_atoms": float(energy_error),
             "tangent_error_J_mol_atoms": float(tangent_error)}
    if max(mass_error, amount_error, site_error) > FRACTION_TOL or max(energy_error, tangent_error) > ENERGY_TOL:
        raise ValueError(f"Equilibrium audit failed: {audit}")
    # IDs are local to a point: they do not pretend to track a branch across T.
    records.sort(key=lambda s: (s["phase"], tuple(s["composition"][c] for c in elements)))
    counts = Counter(s["phase"] for s in records)
    seen = Counter()
    for row in records:
        seen[row["phase"]] += 1
        row["instance"] = row["phase"] + (f"#{seen[row['phase']]}" if counts[row["phase"]] > 1 else "")
    return {"G_J_mol_atoms": float(energy), "chemical_potentials_J_mol_atoms": dict(zip(elements, mu.tolist())),
            "phases": records, "audit": audit,
            "assemblage": " + ".join(s["instance"] for s in records if s["amount"] > PRESENT_TOL)}


class EquilibriumSystem:
    def __init__(self, db, request):
        import pycalphad
        from pycalphad import variables as v
        from pycalphad.core.utils import filter_phases, unpack_species
        from pycalphad.codegen.phase_record_factory import PhaseRecordFactory
        self.db, self.request = db, request
        if not pycalphad.__version__.startswith("0.11."):
            raise ValueError("Phase diagrams require pycalphad 0.11.x; install requirements-thermo.txt")
        if set(request.components) - db.elements:
            raise ValueError("Selected components are not all present in the TDB")
        unknown = set((request.phases or []) + request.suspended_phases) - db.phases.keys()
        if unknown:
            raise ValueError(f"Unknown phase names: {sorted(unknown)}")
        self.components = sorted(request.components) + (["VA"] if "VA" in db.elements else [])
        candidates = sorted(set(request.phases or db.phases) - set(request.suspended_phases))
        self.phases = filter_phases(db, unpack_species(db, self.components), candidates)
        if not self.phases:
            raise ValueError("No active phases for the selected components")
        self.excluded = {}
        for name in sorted(db.phases.keys() - set(self.phases)):
            definition = db.phases[name]
            reason = ("suspended" if name in request.suspended_phases else
                      "not selected" if name not in candidates else
                      "represented by ordered model " + str(definition.model_hints.get("ordered_phase"))
                      if definition.model_hints.get("ordered_phase") in self.phases else "incompatible components")
            self.excluded[name] = reason
        self.models, self.metadata = {}, {}
        self.warnings = []
        for name in self.phases:
            definition = db.phases[name]
            magnetic_hints = [definition.model_hints]
            base = definition.model_hints.get("disordered_phase")
            if base in db.phases:
                magnetic_hints.append(db.phases[base].model_hints)
            if any(hints.get("ihj_magnetic_afm_factor", -1) >= 0 for hints in magnetic_hints):
                raise ValueError(f"{name}: phase diagrams currently validate only conventional IHJ magnetism (negative AFM factor)")
            groups = [sorted(s.name for s in group if s.name in self.components) for group in db.phases[name].constituents]
            # Upstream 0.11 materializes all endmember pairs before capping edge
            # samples. Bound that allocation independently of the point count.
            if np.prod([len(group) for group in groups], dtype=float) > 1024:
                raise ValueError(f"{name} exceeds 1024 active endmembers for phase-diagram sampling; reduce components")
            with warnings.catch_warnings(record=True) as caught:
                warnings.simplefilter("always")
                validated = GibbsModel(db, name, groups, request.temperatures, request.pressure,
                                       request.allow_missing_ordered_endmembers, build_numeric=False,
                                       allow_vacancy_limit=True,
                                       continuous_temperature_range=request.mode == "binary" and request.map_boundaries)
            self.warnings.extend(str(w.message) for w in caught)
            self.models[name] = validated.model
            self.metadata[name] = {"sublattices": groups, "site_ratios": validated.ratios.tolist(),
                                   "ordering": validated.ordering, "reference_functions": validated.functions}
        self.records = PhaseRecordFactory(db, self.components, [v.N, v.P, v.T], self.models)
        self.elements = list(self.records[self.phases[0]].nonvacant_elements)
        self.cache = OrderedDict()
        self.faces = {}

    def energy_grid(self, temperature, density):
        from pycalphad import calculate
        key = (temperature, density)
        if key not in self.cache:
            grid = calculate(self.db, self.components, self.phases, model=self.models,
                             phase_records=self.records, output="GM", fake_points=True,
                             N=1, P=self.request.pressure, T=temperature, pdens=density, to_xarray=False)
            self.cache[key] = grid
            while len(self.cache) > 2:
                self.cache.popitem(last=False)
        return self.cache[key]

    def solve_once(self, point, density):
        from pycalphad import variables as v
        from pycalphad.core.composition_set import CompositionSet
        from pycalphad.core.starting_point import starting_point
        from pycalphad.core.eqsolver import _solve_eq_at_conditions
        from pycalphad.core.solver import Solver
        # At an exact simplex face, solve the reduced component system. An
        # artificial epsilon can erase trace line compounds or fail convergence.
        present = tuple(c for c in self.elements if point["composition"][c] > 0)
        if len(present) < len(self.elements):
            if present not in self.faces:
                face_request = self.request.model_copy(update={"components": list(present)})
                self.faces[present] = EquilibriumSystem(self.db, face_request)
            result = self.faces[present].solve_once(point, density)
            absent = sorted(set(self.elements)-set(present))
            for state in result["phases"]:
                state["composition"].update({c: 0. for c in absent})
                for site in self.models[state["phase"]].site_fractions:
                    state["site_fractions"].setdefault(f"Y_{site.sublattice_index}_{site.species.name}", 0.)
            result["solver_composition"].update({c: 0. for c in absent})
            result["undefined_chemical_potentials"] = absent
            return result
        composition = {c: point["composition"][c] for c in self.elements}
        raw = {v.N: 1., v.P: point["P_Pa"], v.T: point["T_K"],
               **{v.X(c): composition[c] for c in self.elements[:-1]}}
        conditions = OrderedDict((k, np.atleast_1d(value)) for k, value in sorted(raw.items(), key=lambda item: str(item[0])))
        grid = self.energy_grid(point["T_K"], density)
        statevars = self.records.state_variables
        initial = starting_point(conditions, statevars, self.records, grid)
        eq = _solve_eq_at_conditions(initial, self.records, grid, list(conditions), statevars, False, solver=Solver())
        if not np.isfinite(eq.GM).all():
            raise ValueError("Equilibrium solver did not converge")
        sets = []
        for name, amount, y in zip(eq.Phase.reshape(-1), eq.NP.reshape(-1), eq.Y.reshape((-1, eq.Y.shape[-1]))):
            if name == "":
                continue
            if name not in self.models:
                raise ValueError(f"Unphysical/unknown equilibrium phase: {name}")
            record = self.records[str(name)]
            cs = CompositionSet(record)
            cs.update(np.asarray(y[:record.phase_dof]), float(amount), np.array([raw[s] for s in record.state_variables]))
            sets.append(cs)
        mu = eq.MU.reshape(-1)
        result = audit_state(sets, mu, composition, float(eq.GM.reshape(-1)[0]))
        gx = grid.X.reshape((-1, len(self.elements)))
        gg = grid.GM.reshape(-1)
        real = (grid.Phase.reshape(-1) != "_FAKE_") & np.isfinite(gg) & np.isfinite(gx).all(axis=1)
        residual = float(max(0., -np.min(gg[real] - gx[real] @ mu)))
        result["audit"]["sampled_driving_force_J_mol_atoms"] = residual
        if residual > ENERGY_TOL:
            raise ValueError(f"Sampled state lies {residual:g} J/mol-atoms below equilibrium tangent plane")
        result["solver_composition"] = composition
        result["sampling_density"] = density
        return result

    def solve(self, point):
        densities = [self.request.sampling_density]
        if self.request.verify_sampling:
            densities.append(2*densities[0])
        attempts = []
        accepted = []
        for density in densities:
            try:
                result = self.solve_once(point, density)
                attempts.append({"density": density, "status": "accepted", "G_J_mol_atoms": result["G_J_mol_atoms"],
                                 "assemblage": result["assemblage"]})
                accepted.append(result)
            except (ValueError, RuntimeError, FloatingPointError, np.linalg.LinAlgError) as exc:
                attempts.append({"density": density, "status": "failed", "error": str(exc)})
        if not accepted:
            return {**point, "status": "failed", "attempts": attempts, "phases": [], "assemblage": "FAILED"}
        best = min(accepted, key=lambda r: r["G_J_mol_atoms"])
        spread = max(a["G_J_mol_atoms"] for a in accepted) - best["G_J_mol_atoms"]
        verified = len(accepted) == 2 and spread <= ENERGY_TOL and accepted[0]["assemblage"] == accepted[1]["assemblage"]
        return {**point, **best, "status": "accepted", "attempts": attempts, "sampling_verified": verified,
                "sampling_energy_spread_J_mol_atoms": float(spread),
                "needs_refinement": self.request.verify_sampling and not verified}


def trace_boundaries(system, rows, progress=None):
    """Trace zero-phase-fraction lines; retain a finite step budget and all errors."""
    from pycalphad import variables as v
    from pycalphad.mapping import BinaryStrategy, TernaryStrategy
    req = system.request
    if not req.map_boundaries or req.mode not in {"binary", "ternary"}:
        return {"status": "not_requested", "lines": [], "invariants": []}
    conditions = {v.N: 1., v.P: req.pressure}
    if req.mode == "binary":
        xc = req.x_component or req.components[-1]
        xvar, yvar = v.X(xc), v.T
        conditions.update({v.T: (req.temperatures[0], req.temperatures[-1], min(np.diff(req.temperatures))),
                           xvar: (*req.composition_range, (req.composition_range[1]-req.composition_range[0])/(req.points-1))})
        cls = BinaryStrategy
    else:
        xvar, yvar = v.X(req.components[1]), v.X(req.components[2])
        conditions.update({v.T: req.temperatures[0], xvar: (0., 1., 1/(req.points-1)), yvar: (0., 1., 1/(req.points-1))})
        cls = TernaryStrategy
    result = {"status": "failed", "algorithm": "pycalphad zero-phase-fraction mapping",
              "x": str(xvar), "y": str(yvar), "lines": [], "invariants": [], "rejected_points": 0}
    try:
        strategy = cls(system.db, system.components, system.phases, conditions, models=system.models,
                       phase_record_factory=system.records, GLOBAL_MIN_PDENS=2*req.sampling_density,
                       GLOBAL_CHECK_INTERVAL=1)
        strategy.generate_automatic_starting_points()
        known = {tuple(sorted(node.stable_phases)) for node in strategy.node_queue.nodes}
        added = 0
        for row in rows:
            if row["status"] != "accepted":
                continue
            names = tuple(sorted(s["phase"] for s in row["phases"] if s["amount"] > PRESENT_TOL))
            if len(names) < 2 or names in known:
                continue
            seed = {v.N: 1., v.P: req.pressure, v.T: row["T_K"],
                    **{var: row["composition"][var.species.name] for var in conditions if isinstance(var, v.MoleFraction)}}
            if strategy.add_nodes_from_conditions(seed, force_add=False):
                known.add(names); added += 1
        result["interior_grid_seeds"] = added
        finished = False
        for step in range(req.max_mapping_steps):
            try:
                finished = strategy.iterate()
            except Exception as exc:
                result["iteration_error"] = f"{type(exc).__name__}: {exc}"
                break
            if progress and step % 100 == 0:
                progress({"stage": "mapping", "completed": step+1, "total": req.max_mapping_steps})
            if finished:
                break
        result["iterations"] = step+1

        def serialize(point):
            sets = point.stable_composition_sets
            composition = {c: float(sum(cs.NP*cs.X[i] for cs in sets)) for i, c in enumerate(system.elements)}
            fixed = {c: float(np.asarray(point.global_conditions[v.X(c)]).item())
                     for c in system.elements if v.X(c) in point.global_conditions}
            composition.update(fixed)
            missing = set(system.elements)-set(fixed)
            if len(missing) == 1:
                composition[missing.pop()] = 1-sum(fixed.values())
            audited = audit_state(sets, point.chemical_potentials, composition)
            return {"T_K": float(point.global_conditions[v.T]), "P_Pa": req.pressure, "composition": composition, **audited}

        for line in strategy.zpf_lines:
            # Keep gaps as null; never connect through a rejected point.
            points = []
            for point in line.points:
                try:
                    points.append(serialize(point))
                except ValueError:
                    points.append(None)
                    result["rejected_points"] += 1
            result["lines"].append({"termination": line.status.name, "points": points})
        for node in strategy.node_queue.nodes:
            if len(node.stable_composition_sets) == 3:
                try:
                    result["invariants"].append(serialize(node))
                except ValueError:
                    result["rejected_points"] += 1
        failed_lines = sum(line.status.name == "FAILED" for line in strategy.zpf_lines)
        result["status"] = "completed" if finished and not result["rejected_points"] and not failed_lines else "partial"
        if failed_lines:
            result["warning"] = f"{failed_lines} tracing branches terminated unsuccessfully; inspect line_terminations"
        if not finished:
            result["warning"] = ("Mapping iteration failed; completed segments and the grid remain available"
                                 if "iteration_error" in result else "Mapping step limit reached; the grid remains available")
        result["line_terminations"] = dict(Counter(line.status.name for line in strategy.zpf_lines))
    except Exception as exc:
        result["error"] = f"{type(exc).__name__}: {exc}"
    return result


def calculate_diagram(db, request, progress=None):
    import pycalphad
    request = PhaseDiagramRequest.model_validate(request)
    system = EquilibriumSystem(db, request)
    points = conditions_grid(request)
    rows = []
    for point in points:
        rows.append(system.solve(point))
        if progress and (len(rows) == len(points) or len(rows) % 10 == 0):
            progress({"stage": "equilibria", "completed": len(rows), "total": len(points)})
    mapping = trace_boundaries(system, rows, progress)
    accepted = [r for r in rows if r["status"] == "accepted"]
    summary = {"total_points": len(rows), "accepted_points": len(accepted), "failed_points": len(rows)-len(accepted),
               "sampling_verified_points": sum(r["sampling_verified"] for r in accepted),
               "needs_refinement_points": sum(r["needs_refinement"] for r in accepted),
               "assemblages": sorted({r["assemblage"] for r in accepted})}
    partial = summary["failed_points"] or summary["needs_refinement_points"] or mapping["status"] in {"failed", "partial"}
    return {"status": "partial" if partial else "calculated", "mode": request.mode, "request": request.model_dump(),
            "components": request.components, "active_phases": system.phases, "excluded_phases": system.excluded,
            "models": system.metadata, "engine": {"name": "pycalphad", "version": pycalphad.__version__,
            "model": "ThermodynamicModel (partition magnetic parameters before IHJ energy)",
            "model_sha256": hashlib.sha256(Path(__file__).with_name("thermo_model.py").read_bytes()).hexdigest()},
            "energy_unit": "J/mol-atoms", "phase_fraction_basis": "moles of atoms", "composition_basis": "atomic fraction",
            "phase_constraint": "multiphase_equilibrium_with_composition_set_splitting", "global_minimum_certified": False,
            "tolerances": {"fractions": FRACTION_TOL, "energy_J_mol_atoms": ENERGY_TOL,
                           "present_phase_fraction": PRESENT_TOL},
            "summary": summary, "rows": rows, "boundaries": mapping, "warnings": sorted(set(system.warnings)),
            "notes": ["All selected phases compete; duplicate phase names denote distinct coexisting compositions.",
                      "Phase fractions are atom-mole fractions, not mass or volume fractions.",
                      "Zero-component faces are solved as reduced systems; absent-element chemical potentials are undefined and omitted.",
                      "Sampling and boundary tracing are numerical searches, not a proof of global stability or exhaustive topology.",
                      "An isopleth fixes the bulk composition path; phase compositions may lie outside that path.",
                      "Excluding competing phases produces a constrained/metastable diagram.",
                      "Only the physical terms present in the supplied database are included."]}


def run_diagram(request, progress=None):
    from src.phase_diagram_output import save_diagram
    request = PhaseDiagramRequest.model_validate(request)
    folder = resolve_data_path("phase_diagrams") / ("diagram_" + uuid.uuid4().hex[:12])
    db, sources, checkpoint = materialize_source(request, folder)
    result = calculate_diagram(db, request, progress)
    result.update(sources=sources, checkpoint=checkpoint)
    folder.mkdir(parents=True, exist_ok=True)
    save_diagram(result, folder)
    atomic_json(folder / "diagram.json", result)
    return result
