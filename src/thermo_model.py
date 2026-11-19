"""CEF model with explicit partitioning of IHJ magnetic parameters.

pycalphad 0.11.1 partitions magnetic properties but not their energy. Partition
TC and BMAGN first, then evaluate the nonlinear magnetic energy exactly once.
"""
from contextvars import ContextVar
from pycalphad import Model, variables as v
from symengine import Piecewise, S, log
from tinydb import where

_model_parameters = ContextVar('thermodynamic_model_parameters', default=None)


def ihj_energy(raw_tc, raw_beta, hints, normalization):
    afm = hints["ihj_magnetic_afm_factor"]
    p = hints["ihj_magnetic_structure_factor"]
    if afm >= 0 or not 0 < p <= 1:
        raise ValueError("Partitioned magnetic energy requires the conventional IHJ model (negative AFM factor, 0<p<=1)")
    tc = Piecewise((raw_tc/afm, raw_tc < 0), (raw_tc, True))
    beta = Piecewise((raw_beta/afm, raw_beta < 0), (raw_beta, True))
    # A tiny denominator guard avoids eager numerical evaluation of 0/0 in
    # the inactive branches; the exact zero-TC branch has zero magnetic G.
    a = 518/1125 + (11692/15975)*(1/p-1)
    def low(tau):
        return 1 - ((79/(140*p))/tau + (474/497)*(1/p-1)*(tau**3/6+tau**9/135+tau**15/600))/a
    def high(tau):
        return -(tau**-5/10+tau**-15/315+tau**-25/1500)/a
    positive, negative = v.T/(raw_tc+1e-12), v.T/(raw_tc/afm+1e-12)
    # Conditions stay in terms of raw TC: differentiating a condition that
    # contains Piecewise itself can produce a non-boolean numpy.select input.
    g = Piecewise((low(positive), raw_tc >= v.T), (low(negative), raw_tc/afm >= v.T),
                  (high(positive), raw_tc > 0), (high(negative), raw_tc < 0), (S.Zero, True))
    return v.R*v.T*log(beta+1)*g/normalization, tc, beta


class ThermodynamicModel(Model):
    def __init__(self, dbe, comps, phase_name, parameters=None):
        # pycalphad 0.11 constructs the disordered child through self.__class__
        # without forwarding parameters. Context-local inheritance covers both
        # symbolic fitting variables and explicit numeric overrides, including
        # the second child built by our magnetic partitioning below.
        if parameters is None:
            parameters = _model_parameters.get()
        token = _model_parameters.set(parameters)
        try:
            super().__init__(dbe, comps, phase_name, parameters=parameters)
        finally:
            _model_parameters.reset(token)

    def redlich_kister_sum(self, phase, param_search, param_query):
        # Native Thermo-Calc 2026b controls with unequal site ratios and unequal
        # occupations establish the three-binary-sublattice L1 convention:
        # product(y) * (y_A-y_B) on the FIRST mixing sublattice. It is not the
        # two-sublattice reciprocal convention. Limit this extension to the
        # G/L case tested; other unsupported forms retain upstream rejection.
        def extended(p):
            groups = p['constituent_array']
            three_binary_l1 = (p['parameter_order'] == 1
                    and sum(len(g) == 2 for g in groups) == 3
                    and all(len(g) <= 2 for g in groups))
            # Native unequal-site, asymmetric-occupation controls establish
            # the L0 product basis for two ternary mixing sublattices. This
            # form occurs in the Co-Ta-Ti ORDER_B2 parameter set. Do not extend
            # higher orders or other unsupported arities by inference.
            two_ternary_l0 = (p['parameter_order'] == 0
                    and sum(len(g) == 3 for g in groups) == 2
                    and all(len(g) in {1, 3} for g in groups))
            return (p['parameter_type'] in {'G', 'L'}
                    and (three_binary_l1 or two_ternary_l0)
                    and all(s.name != '*' for g in groups for s in g)
                    and not phase.model_hints.get('ionic_liquid_2SL', False))
        extra = [p for p in param_search(param_query) if extended(p)]
        result = super().redlich_kister_sum(phase,
            lambda query: [p for p in param_search(query) if not extended(p)], param_query)
        for p in extra:
            term = S.One
            first = True
            for index, group in enumerate(p['constituent_array']):
                ys = [v.SiteFraction(phase.name, index, s) for s in group]
                for y in ys:
                    term *= y
                if p['parameter_order'] == 1 and len(ys) == 2 and first:
                    term *= ys[0]-ys[1]
                    first = False
            result += term*p['parameter']
        return result

    def magnetic_energy(self, dbe):
        phase = dbe.phases[self.phase_name]
        def parameter(name):
            query = ((where("phase_name") == phase.name) & (where("parameter_type") == name)
                     & where("constituent_array").test(self._array_validity))
            return self.symbol_replace(self.redlich_kister_sum(phase, dbe.search, query), self._symbols)
        self.raw_tc, self.raw_beta = parameter("TC"), parameter("BMAGN")
        hints = phase.model_hints
        if "ihj_magnetic_afm_factor" not in hints:
            self.TC = self.curie_temperature = S.Zero
            self.BMAG = self.beta = S.Zero
            return S.Zero
        if hints["ihj_magnetic_afm_factor"] == 0:
            return super().magnetic_energy(dbe)
        energy, tc, beta = ihj_energy(self.raw_tc, self.raw_beta, hints, self._site_ratio_normalization)
        self.TC = self.curie_temperature = tc
        self.BMAG = self.beta = beta
        return energy

    def atomic_ordering_energy(self, dbe):
        phase = dbe.phases[self.phase_name]
        if phase.model_hints.get("ordered_phase") != self.phase_name:
            return S.Zero
        base_name = phase.model_hints["disordered_phase"]
        base = dbe.phases[base_name]
        own_tc, own_beta = self.raw_tc, self.raw_beta
        own_magnetic_energy = self.models["mag"]
        own_effective_tc, own_effective_beta = self.TC, self.BMAG
        # Partition chemical energy with the upstream mapping, while excluding
        # the incorrect difference of two independently evaluated magnetic Gs.
        self.models["mag"] = S.Zero
        ordering = super().atomic_ordering_energy(dbe)
        base_model = self.__class__(dbe, sorted(self.components), base_name)
        if phase.model_hints.get("never_disorder", False):
            # NEVER_DISORDER adds the ordered CEF contribution without
            # subtracting its random-occupation value. Its magnetic energy
            # likewise belongs to the ordered phase, whose IHJ settings may
            # be absent from the nonmagnetic disordered reference (e.g. Co-W MU).
            # A magnetic reference would require separately validated coupling;
            # never silently apply the ordinary disorder-part subtraction.
            if base_model.models["mag"] != S.Zero:
                raise ValueError("NEVER_DISORDER with a magnetic reference requires a validated coupling model")
            self.raw_tc, self.raw_beta = own_tc, own_beta
            self.models["mag"] = own_magnetic_energy
            self.TC = self.curie_temperature = own_effective_tc
            self.BMAG = self.beta = own_effective_beta
            return ordering
        substitutional = [i for i, group in enumerate(phase.constituents) if group == base.constituents[0]]
        constituents = [sorted(set(group).intersection(self.components)) for group in phase.constituents]
        def quasi(species):
            return self._quasi_mole_fraction(species, self.phase_name, constituents, phase.sublattices, substitutional)
        ord_map = {v.SiteFraction(self.phase_name, index, species): quasi(species)
                   for index in substitutional for species in constituents[index]}
        base_map = {site: (quasi(site.species) if site.sublattice_index == 0 else
                          v.SiteFraction(self.phase_name, site.sublattice_index+len(substitutional)-1, site.species))
                    for site in base_model.site_fractions}
        self.raw_tc = base_model.raw_tc.xreplace(base_map) + own_tc - own_tc.xreplace(ord_map)
        self.raw_beta = base_model.raw_beta.xreplace(base_map) + own_beta - own_beta.xreplace(ord_map)
        if self.raw_tc != S.Zero or self.raw_beta != S.Zero:
            hints = base.model_hints
            if "ihj_magnetic_afm_factor" not in hints:
                raise ValueError("A magnetic ordering correction requires IHJ settings on the disordered phase")
            normalization = base_model._site_ratio_normalization.xreplace(base_map)
            self.models["mag"], self.TC, self.BMAG = ihj_energy(self.raw_tc, self.raw_beta, hints, normalization)
            self.curie_temperature, self.beta = self.TC, self.BMAG
        return ordering
