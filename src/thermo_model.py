"""CEF model with explicit partitioning of IHJ magnetic parameters.

pycalphad 0.11.1 partitions magnetic properties but not their energy. Partition
TC and BMAGN first, then evaluate the nonlinear magnetic energy exactly once.
"""
from pycalphad import Model, variables as v
from symengine import Piecewise, S, log
from tinydb import where


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
        # Partition chemical energy with the upstream mapping, while excluding
        # the incorrect difference of two independently evaluated magnetic Gs.
        self.models["mag"] = S.Zero
        ordering = super().atomic_ordering_energy(dbe)
        base_model = self.__class__(dbe, sorted(self.components), base_name)
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
