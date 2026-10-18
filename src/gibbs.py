"""Homogeneous single-phase Gibbs curves from complete CALPHAD models.

pycalphad constructs the thermodynamic model. Constrained multi-start SLSQP
minimizes its internal site fractions, without allowing phase separation.
"""
import csv
import hashlib
import io
import itertools
import re
import threading
import textwrap
import uuid

import numpy as np
from scipy.linalg import qr
from scipy.optimize import Bounds, LinearConstraint, linprog, minimize

from config import resolve_data_path
from src.gibbs_settings import GibbsRequest, GibbsSource
from src.storage import atomic_json, atomic_write

_plot_lock = threading.Lock()


def source_options(source):
    source = GibbsSource.model_validate(source)
    if source.config:
        from src.workflow import load_config
        _, data = load_config(source.config)
        return {"phase": data["phase_name"].upper(), "phases": [data["phase_name"].upper()],
                "sublattices": data["tdb_model"]["comp"],
                "site_ratios": data["tdb_model"]["occup_atoms_in_tdb"]}
    db, _ = read_databases(source.tdb_files)
    phase = (source.phase or next(iter(db.phases), "")).upper()
    if phase not in db.phases:
        raise ValueError("Choose a phase present in the supplied TDB")
    definition = db.phases[phase]
    return {"phase": phase, "phases": sorted(db.phases),
            "sublattices": [sorted(s.name for s in group) for group in definition.constituents],
            "site_ratios": [float(x) for x in definition.sublattices]}


def read_databases(files):
    try:
        from pycalphad import Database
    except ImportError as exc:
        raise ImportError("Install requirements-thermo.txt to calculate Gibbs curves") from exc
    texts, sources = [], []
    for value in files:
        path = resolve_data_path(value)
        content = path.read_bytes()
        text = content.decode("utf-8-sig").replace("\r\n", "\n").replace("\r", "\n")
        # Pandat's documented example uses DISORDER_PART; pycalphad expects
        # DISORDERED_PART. Normalize only this TYPE_DEFINITION keyword. Keep
        # the source bytes/hash intact for same-file cross-solver validation.
        text, count = re.subn(
            r"(?im)^(\s*TYPE_DEFINITION\s+\S+\s+GES\s+(?:AMEND_PHASE_DESCRIPTION|AM_PH_DES)\s+\S+\s+)DISORDER_PART(?=\s)",
            r"\1DISORDERED_PART", text)
        texts.append(text)
        source = {"path": str(path), "sha256": hashlib.sha256(content).hexdigest()}
        if count:
            source["parser_normalizations"] = {"DISORDER_PART_to_DISORDERED_PART": count}
        sources.append(source)
    try:
        return Database("\n".join(texts)), sources
    except Exception as exc:
        raise ValueError(f"Cannot read the combined TDB: {exc}") from exc


def plain_expression(value):
    import sympy as sp
    expression = sp.sympify(value)
    # pycalphad StateVariables implement __getitem__; plain SymPy symbols
    # avoid lambdify treating them as iterable objects.
    return expression.xreplace({symbol: sp.Symbol(str(symbol)) for symbol in expression.free_symbols})


def validate_functions(db, parameters, temperatures, pressure, continuous_temperature_range=False):
    """Reject missing reference functions, cycles, and implicit extrapolation."""
    import sympy as sp
    seen, stack = set(), set()
    state = {sp.Symbol("T"), sp.Symbol("P")}

    def check(expression, label):
        expression = plain_expression(expression)
        for piece in expression.atoms(sp.Piecewise):
            conditions = [cond for value, cond in piece.args if not (cond == sp.true and value == 0)]
            if conditions and all(cond.free_symbols <= state for cond in conditions):
                if continuous_temperature_range:
                    domain = sp.Or(*conditions).subs(sp.Symbol("P"), pressure).as_set()
                    if not sp.Interval(min(temperatures), max(temperatures)).is_subset(domain):
                        raise ValueError(f"{label} is not defined throughout the temperature interval; extrapolation is disabled")
                for temperature in temperatures:
                    substitutions = {sp.Symbol("T"): temperature, sp.Symbol("P"): pressure}
                    if not any(bool(cond.subs(substitutions)) for cond in conditions):
                        raise ValueError(f"{label} is not defined at T={temperature:g} K; extrapolation is disabled")
        for symbol in expression.free_symbols - state:
            name = str(symbol)
            if name in stack:
                raise ValueError(f"Cyclic TDB function: {name}")
            if name in seen:
                continue
            if name not in db.symbols:
                raise ValueError(f"Missing TDB function {name}; supply a compatible reference TDB")
            stack.add(name)
            check(db.symbols[name], name)
            stack.remove(name)
            seen.add(name)

    for parameter in parameters:
        check(parameter["parameter"], f"{parameter['parameter_type']}({parameter['constituent_array']})")
    return sorted(seen)


def phase_parameters(db, phase, groups, allow_missing=False):
    parameters = []
    for parameter in db._parameters.all():
        # Mobility databases can contain separate MF/MQ parameters for several
        # diffusing species with the same constituent array. They do not enter G.
        if parameter["parameter_type"] in {"MF", "MQ"}:
            continue
        array = parameter["constituent_array"]
        if parameter["phase_name"] == phase and len(array) == len(groups) and all(
                all(s.name == "*" or s.name in group for s in site) for site, group in zip(array, groups)):
            parameters.append(parameter)
    keys = [(p["parameter_type"], tuple(tuple(s.name for s in site) for site in p["constituent_array"]), p["parameter_order"])
            for p in parameters]
    if len(set(keys)) != len(keys):
        raise ValueError("Duplicate phase parameters; combine temperature ranges into a single parameter definition")
    endmembers = [p for p in parameters if p["parameter_type"] == "G"
                  and p["parameter_order"] == 0 and all(len(site) == 1 for site in p["constituent_array"])]
    for member in (() if allow_missing else itertools.product(*groups)):
        if not any(all(site[0].name in {element, "*"} for site, element in zip(p["constituent_array"], member)) for p in endmembers):
            raise ValueError(f"Missing endmember G parameter in {phase}: {':'.join(member)}")
    return parameters


class GibbsModel:
    def __init__(self, db, phase, groups, temperatures, pressure, allow_missing_ordered_endmembers=False,
                 build_numeric=True, allow_vacancy_limit=False, continuous_temperature_range=False):
        import sympy as sp
        from pycalphad import variables as v
        from src.thermo_model import ThermodynamicModel
        self.phase = phase.upper()
        if self.phase not in db.phases:
            raise ValueError(f"Phase {self.phase} is absent from the supplied database")
        definition = db.phases[self.phase]
        if any(key in definition.model_hints for key in ("ionic_liquid_2SL", "mqmqa")):
            raise ValueError("Ionic and MQMQA models are not supported")
        allowed = [{s.name for s in group} for group in definition.constituents]
        groups = groups if groups is not None else [sorted(group) for group in allowed]
        self.groups = [[str(element).upper() for element in group] for group in groups]
        if len(self.groups) != len(allowed) or any(
                not group or len(set(group)) != len(group) or not set(group) <= valid
                for group, valid in zip(self.groups, allowed)):
            raise ValueError("Select a nonempty, valid constituent subset for every sublattice")
        self.groups = [sorted(group) for group in self.groups]
        self.species_names = sorted(set(itertools.chain.from_iterable(self.groups)))
        self.components = [name for name in self.species_names if name != "VA"]
        species = {s.name: s for s in db.species}
        for name in self.components:
            item = species[name]
            if item.charge != 0 or item.constituents != {name: 1.0}:
                raise ValueError("Gibbs curves require neutral elemental species or VA")
        if not allow_vacancy_limit and not any("VA" not in group for group in self.groups):
            raise ValueError("At least one sublattice must exclude VA to prevent a zero-atom phase")
        self.ratios = np.asarray(definition.sublattices, dtype=float)
        if not np.isfinite(self.ratios).all() or np.any(self.ratios <= 0):
            raise ValueError("Site ratios must be fixed, finite and positive")
        if np.prod([len(group) for group in self.groups], dtype=float) > 10000:
            raise ValueError("Selected model exceeds 10000 endmembers; reduce the constituent selection")
        partitioned = definition.model_hints.get("ordered_phase") == self.phase
        self.ordering = {"kind": "independent_cef"}
        if partitioned:
            disordered = definition.model_hints.get("disordered_phase")
            if disordered not in db.phases or disordered == self.phase:
                raise ValueError("Partitioned ordering requires a distinct disordered phase in the TDB")
            base = db.phases[disordered]
            base_ratios = np.asarray(base.sublattices, dtype=float)
            if not np.isfinite(base_ratios).all() or np.any(base_ratios <= 0):
                raise ValueError("Disordered reference site ratios must be fixed, finite and positive")
            base_groups = [{s.name for s in group} for group in base.constituents]
            substitutional = [i for i, group in enumerate(allowed) if group == base_groups[0]]
            count = len(substitutional)
            if count < 2 or substitutional != list(range(count)) or allowed[count:] != base_groups[1:]:
                raise ValueError("Partitioned ordering requires equivalent leading substitutional sites and matching trailing interstitial sites")
            scale = self.ratios[:count].sum()/base_ratios[0]
            if not np.allclose(self.ratios[count:], base_ratios[1:]*scale, atol=1e-12, rtol=1e-10):
                raise ValueError("Ordered/disordered interstitial site ratios are incompatible")
            if any(key in base.model_hints for key in ("ionic_liquid_2SL", "mqmqa")):
                raise ValueError("Unsupported disordered reference model")
            # Even an excluded ordered occupation can contribute at y=x in
            # G_ord(y)-G_ord(x). Validate the full active constituent closure.
            active = [sorted(group.intersection(self.species_names)) for group in allowed]
            if np.prod([len(group) for group in active], dtype=float) > 10000:
                raise ValueError("Partitioned model exceeds 10000 active endmembers")
            parameters = phase_parameters(db, self.phase, active, allow_missing=allow_missing_ordered_endmembers)
            if any(p["parameter_type"] not in {"G", "L", "TC", "BMAGN"} for p in parameters):
                raise ValueError("Partitioned models support chemical G/L and conventional IHJ TC/BMAGN terms only")
            if any(p["parameter_type"] in {"TC", "BMAGN"} for p in parameters) and not np.isclose(scale, 1):
                raise ValueError("Magnetic ordering corrections require matching ordered/disordered formula-unit site ratios")
            for key in ("ihj_magnetic_afm_factor", "ihj_magnetic_structure_factor"):
                if key in definition.model_hints and definition.model_hints[key] != base.model_hints.get(key):
                    raise ValueError("Ordered/disordered IHJ settings must match")
            parameters += phase_parameters(db, disordered, [sorted(group.intersection(self.species_names)) for group in base_groups])
            self.ordering = {"kind": "partitioned_order_disorder", "disordered_phase": disordered,
                             "ordering_sublattices": substitutional,
                             "disordered_site_mapping": [0]*count + list(range(1, len(base_groups))),
                             "allow_missing_ordered_endmembers": allow_missing_ordered_endmembers}
        else:
            parameters = phase_parameters(db, self.phase, self.groups)
        self.functions = validate_functions(db, parameters, temperatures, pressure, continuous_temperature_range)
        # Build with the original phase definitions so pycalphad's ordering
        # mapping remains intact, then apply the chosen site restrictions.
        model = ThermodynamicModel(db, self.species_names, self.phase)
        self.model = model
        if not build_numeric:
            return
        self.variables = [v.SiteFraction(self.phase, i, element) for i, group in enumerate(self.groups) for element in group]
        self.labels = [f"Y_{i}_{element}" for i, group in enumerate(self.groups) for element in group]
        symbols = [sp.Symbol(str(value)) for value in [v.T, v.P, *self.variables]]
        excluded = {sp.Symbol(str(site)): 0 for site in model.site_fractions if site not in self.variables}
        energy = plain_expression(model.GM).xreplace(excluded)
        if energy.free_symbols - set(symbols):
            raise ValueError(f"Unresolved model symbols: {energy.free_symbols - set(symbols)}")
        self.terms = list(model.models)
        expressions = [energy, *[plain_expression(model.models[key]).xreplace(excluded) for key in self.terms]]
        self.evaluate = sp.lambdify(symbols, expressions, modules="numpy", cse=True)
        self.derivative = sp.lambdify(symbols, [energy.diff(symbol) for symbol in symbols[2:]], modules="numpy", cse=True)
        self.magnetic_properties = sp.lambdify(symbols, [plain_expression(model.TC).xreplace(excluded),
                                                       plain_expression(model.BMAG).xreplace(excluded)], modules="numpy", cse=True)
        n = len(self.variables)
        self.site_matrix = np.zeros((len(self.groups), n))
        self.atom_matrix = np.zeros((len(self.components), n))
        index = 0
        for i, group in enumerate(self.groups):
            for element in group:
                self.site_matrix[i, index] = 1
                if element != "VA":
                    self.atom_matrix[self.components.index(element), index] = self.ratios[i]
                index += 1
        self.atom_vector = self.atom_matrix.sum(axis=0)

    def atomic_fractions(self, y):
        atoms = self.atom_matrix @ y
        return atoms/atoms.sum()

    def composition(self, value):
        value = {str(key).upper(): float(amount) for key, amount in value.items()}
        if not set(value) <= set(self.components):
            raise ValueError("Overall composition contains unselected elements")
        result = np.array([value.get(element, 0) for element in self.components])
        if not np.isfinite(result).all() or np.any(result < 0) or not np.isclose(result.sum(), 1, atol=1e-10, rtol=0):
            raise ValueError("Overall atomic fractions must be finite, nonnegative and sum to one")
        return result / result.sum()

    def fixed_sites(self, groups, composition):
        if len(groups) != len(self.groups):
            raise ValueError("One site-fraction mapping is required per sublattice")
        values = []
        for mapping, allowed in zip(groups, self.groups):
            mapping = {key.upper(): float(value) for key, value in mapping.items()}
            if not set(mapping) <= set(allowed):
                raise ValueError("Site fractions contain an excluded constituent")
            values.extend(mapping.get(name, 0) for name in allowed)
        y = np.asarray(values)
        if (not np.isfinite(y).all() or np.any(y < 0) or np.any(y > 1)
                or not np.allclose(self.site_matrix @ y, 1, atol=1e-10, rtol=0)
                or not np.allclose(self.atomic_fractions(y), composition, atol=1e-10, rtol=0)):
            raise ValueError("Site fractions must sum to one per site and match overall composition")
        return y

    def values(self, temperature, pressure, y):
        with np.errstate(all="ignore"):
            values = np.asarray(self.evaluate(temperature, pressure, *y), dtype=float)
        if not np.isfinite(values).all():
            raise ValueError("Nonfinite Gibbs energy; check TDB parameters and temperature limits")
        return values

    def feasible_space(self, composition):
        # N_i(y) / N_atoms(y) = x_i remains linear at fixed x, even when
        # variable vacancies/interstitial occupation changes the denominator.
        A = np.vstack([self.site_matrix, self.atom_matrix - composition[:, None]*self.atom_vector])
        b = np.concatenate([np.ones(len(self.groups)), np.zeros(len(composition))])
        n = A.shape[1]
        def linear(cost):
            answer = linprog(cost, A_eq=A, b_eq=b, bounds=(0, 1), method="highs")
            if not answer.success:
                raise ValueError(f"Composition {dict(zip(self.components, composition))} is infeasible for the selected sublattices")
            return answer.x
        vertices, lower, upper = [], [], []
        for cost in np.eye(n):
            lo, hi = linear(cost), linear(-cost)
            index = int(np.argmax(cost))
            lower.append(lo[index]); upper.append(hi[index])
            vertices.extend([lo, hi])
        vertices = np.unique(np.round(vertices, 13), axis=0)
        free = np.flatnonzero(np.asarray(upper) - lower > 1e-10)
        base = vertices.mean(axis=0)
        reduced = A[:, free]
        rhs = b - A @ base + reduced @ base[free]
        rank = np.linalg.matrix_rank(reduced, tol=1e-10) if len(free) else 0
        if rank:
            rows = qr(reduced.T, pivoting=True)[2][:rank]
            reduced, rhs = reduced[rows], rhs[rows]
        else:
            reduced, rhs = reduced[:0], rhs[:0]
        return A, b, vertices, free, base, reduced, rhs, rank

    def minimize(self, temperature, pressure, space, starts, previous=None):
        A, b, vertices, free, base, reduced, rhs, rank = space
        if len(free) <= rank:
            return base, {"method": "unique_constitution", "successful_starts": 1, "energy_spread": 0.0}
        rng = np.random.default_rng(42)
        candidates = [base]
        if previous is not None and np.max(np.abs(A @ previous - b)) < 1e-8:
            candidates.append(previous)
        for vertex in vertices:
            if len(candidates) >= starts:
                break
            candidates.append(.98 * vertex + .02 * base)
        while len(candidates) < starts:
            candidates.append(rng.dirichlet(np.full(len(vertices), .3)) @ vertices)
        def full(values):
            y = base.copy()
            y[free] = values
            return y
        def objective(values):
            return self.values(temperature, pressure, full(values))[0] / 1000
        def gradient(values):
            with np.errstate(all="ignore"):
                derivative = np.asarray(self.derivative(temperature, pressure, *full(values)), dtype=float)
            return derivative[free] / 1000
        successes = []
        for initial in candidates:
            result = minimize(objective, initial[free], jac=gradient, method="SLSQP",
                              bounds=Bounds(np.zeros(len(free)), np.ones(len(free))),
                              constraints=[LinearConstraint(reduced, rhs, rhs)] if rank else [],
                              options={"ftol": 1e-10, "maxiter": 500})
            y = full(result.x)
            if result.success and np.max(np.abs(A @ y - b)) < 1e-7 and np.all(y >= -1e-10) and np.all(y <= 1+1e-10):
                successes.append((self.values(temperature, pressure, y)[0], y))
        if not successes:
            raise ValueError(f"No optimizer start converged at T={temperature:g} K; no curve was published")
        successes.sort(key=lambda item: item[0])
        return successes[0][1], {"method": "multistart_slsqp", "successful_starts": len(successes),
                                "energy_spread": float(successes[-1][0] - successes[0][0])}


def calculate_curve(db, request):
    request = GibbsRequest.model_validate(request)
    if not request.phase:
        raise ValueError("Specify a phase")
    model = GibbsModel(db, request.phase, request.sublattices, request.temperatures, request.pressure,
                       allow_missing_ordered_endmembers=request.allow_missing_ordered_endmembers)
    if request.mode == "gx":
        start, end = model.composition(request.composition_start), model.composition(request.composition_end)
        changing = np.flatnonzero(np.abs(start - end) > 1e-12)
        if not len(changing):
            raise ValueError("G-x composition endpoints must differ")
        axis = (request.x_axis or model.components[changing[-1]]).upper()
        if axis not in model.components or model.components.index(axis) not in changing:
            raise ValueError("x_axis must be an element whose composition varies along the path")
        compositions = [(1 - fraction) * start + fraction * end for fraction in np.linspace(0, 1, request.points)]
    else:
        axis = "T"
        compositions = [model.composition(request.composition)]
    spaces = [model.feasible_space(composition) for composition in compositions]
    fixed = model.fixed_sites(request.site_fractions, compositions[0]) if request.site_fractions is not None else None
    rows, previous = [], None
    for temperature in request.temperatures:
        for index, (composition, space) in enumerate(zip(compositions, spaces)):
            if fixed is None:
                y, diagnostic = model.minimize(temperature, request.pressure, space, request.starts, previous)
            else:
                y, diagnostic = fixed, {"method": "fixed_site_fractions", "successful_starts": 0, "energy_spread": 0.0}
            values = model.values(temperature, request.pressure, y)
            previous = y
            row = {"T_K": temperature, "P_Pa": request.pressure,
                   "path_fraction": index / (len(compositions)-1) if len(compositions) > 1 else 0.0,
                   "G_J_mol_atoms": float(values[0]), **diagnostic}
            row.update({f"G_{name}_J_mol_atoms": float(value) for name, value in zip(model.terms, values[1:])})
            row.update({f"X_{name}": float(value) for name, value in zip(model.components, composition)})
            row.update({name: float(value) for name, value in zip(model.labels, y)})
            row["atoms_per_formula_unit"] = float(model.atom_vector @ y)
            tc, beta = model.magnetic_properties(temperature, request.pressure, *y)
            row.update(TC_K=float(tc), BMAG=float(beta))
            rows.append(row)
    return {"phase": model.phase, "mode": request.mode, "x_axis": "T_K" if axis == "T" else f"X_{axis}",
            "components": model.components, "sublattices": model.groups, "site_ratios": model.ratios.tolist(),
            "energy_unit": "J/mol-atoms", "phase_constraint": "homogeneous_single_phase",
            "site_fraction_mode": "fixed" if fixed is not None else "optimized",
            "ordering_model": model.ordering,
            "global_minimum_certified": False, "reference_functions": model.functions,
            "contributions": model.terms, "rows": rows,
            "notes": ["G uses the supplied database reference state and only its included physical contributions.",
                      "Internal site fractions are optimized unless explicitly fixed; phase separation is excluded.",
                      "Multi-start local optimization does not certify the global minimum; inspect energy_spread and increase starts when needed."]}


def save_plot(result, folder):
    from matplotlib.figure import Figure
    from matplotlib.backends.backend_agg import FigureCanvasAgg
    with _plot_lock:
        figure = Figure(figsize=(8.5, 5.3), constrained_layout=True)
        FigureCanvasAgg(figure)
        ax = figure.subplots()
        rows = result["rows"]
        groups = sorted({row["T_K"] for row in rows}) if result["mode"] == "gx" else [None]
        for temperature in groups:
            selected = [r for r in rows if temperature is None or r["T_K"] == temperature]
            ax.plot([r[result["x_axis"]] for r in selected], [r["G_J_mol_atoms"] / 1000 for r in selected],
                    linewidth=2, label=f"{temperature:g} K" if temperature is not None else result["phase"])
        ax.set_xlabel("Temperature (K)" if result["mode"] == "gt" else result["x_axis"] + " (atomic fraction)")
        ax.set_ylabel("G (kJ/mol-atoms)")
        def composition_label(row):
            return ", ".join(f"{name}={row['X_'+name]:.4g}" for name in result["components"])
        condition = composition_label(rows[0])
        if result["mode"] == "gx":
            condition += " -> " + composition_label(rows[-1])
        condition += f"; P={rows[0]['P_Pa']:g} Pa; {result['site_fraction_mode']} sites"
        ax.set_title(f"{result['phase']} | Homogeneous single phase\n" + textwrap.fill(condition, 92), fontsize=11)
        ax.grid(alpha=.2)
        ax.legend()
        figure.savefig(folder / "gibbs.png", dpi=170, bbox_inches="tight")
        figure.savefig(folder / "gibbs.svg", bbox_inches="tight")


def run_curve(request):
    request = GibbsRequest.model_validate(request)
    folder = resolve_data_path("gibbs") / f"curve_{uuid.uuid4().hex[:12]}"
    files = list(request.tdb_files)
    checkpoint = None
    if request.config:
        from src.workflow import load_config, read_checkpoint
        from src.tdb_generator import tdb_generate_from_MLmodel
        path, data = load_config(request.config)
        checkpoint = read_checkpoint(data)
        if checkpoint is None:
            raise ValueError("Train the workflow before calculating its Gibbs curve")
        if request.phase and request.phase.upper() != data["phase_name"].upper():
            raise ValueError("Selected phase differs from the workflow phase")
        request = request.model_copy(update={"phase": data["phase_name"].upper()})
        exported = tdb_generate_from_MLmodel(resolve_data_path(data["AL_set"]["pkl_phase_path"]),
                    iter=checkpoint["iter"], process=checkpoint["process"], user="gibbs", file_path=folder / "phase")
        files.append(str(exported["file_path"] / exported["file_name_tdb"]))
        checkpoint = {"config": str(path), "checkpoint": checkpoint["checkpoint"], "input_hashes": checkpoint["input_hashes"]}
    db, sources = read_databases(files)
    result = calculate_curve(db, request)
    folder.mkdir(parents=True, exist_ok=True)
    result.update({"sources": sources, "checkpoint": checkpoint, "request": request.model_dump()})
    buffer = io.StringIO(newline="")
    writer = csv.DictWriter(buffer, fieldnames=list(result["rows"][0]), lineterminator="\n")
    writer.writeheader(); writer.writerows(result["rows"])
    atomic_write(folder / "gibbs.csv", buffer.getvalue())
    save_plot(result, folder)
    result["files"] = {key: str(folder / name) for key, name in
                       (("csv", "gibbs.csv"), ("json", "gibbs.json"), ("png", "gibbs.png"), ("svg", "gibbs.svg"))}
    atomic_json(folder / "gibbs.json", result)
    return {"status": "calculated", **result}
