"""Explicit, bounded experimental CALPHAD parameter fitting requests."""
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class Strict(BaseModel):
    model_config = ConfigDict(extra='forbid', allow_inf_nan=False)


class FitParameter(Strict):
    id: str = Field(pattern=r'^[A-Za-z][A-Za-z0-9_]{0,31}$')
    keys: list[str] = Field(min_length=1, max_length=128)
    basis: Literal['constant', 'temperature', 'heat_capacity'] = 'constant'
    scale: float = Field(gt=0)
    initial: float = 0.
    bounds: tuple[float, float]

    @model_validator(mode='after')
    def bounded(self):
        if not self.bounds[0] < self.bounds[1] or not self.bounds[0] <= self.initial <= self.bounds[1]:
            raise ValueError('Require lower < upper and initial within bounds')
        self.keys = [k.upper().replace(' ', '') for k in self.keys]
        if len(set(self.keys)) != len(self.keys):
            raise ValueError('Duplicate parameter keys')
        return self


class PhaseTarget(Strict):
    phase: str
    composition: dict[str, float] | None = None
    composition_exclusion_reason: str | None = None

    @model_validator(mode='after')
    def recorded_exclusion(self):
        if self.composition is None and not (self.composition_exclusion_reason or '').strip():
            raise ValueError('A phase-presence-only target requires a composition_exclusion_reason')
        return self


class FitObservation(Strict):
    id: str = Field(min_length=1)
    kind: Literal['phase_composition', 'property']
    role: Literal['train', 'validation'] = 'train'
    source: str = Field(min_length=3)
    independence_group: str | None = Field(default=None, min_length=3)
    T_K: float = Field(gt=0)
    composition: dict[str, float]
    error_scale: float = Field(gt=0)
    weight: float = Field(default=1., gt=0)
    phases: list[PhaseTarget] = Field(default_factory=list)
    phase: str | None = None
    site_fractions: list[dict[str, float]] | None = None
    property: Literal['GM', 'HM', 'SM', 'CPM'] | None = None
    value: float | None = None
    reference_state: str | None = None

    @model_validator(mode='after')
    def observation(self):
        if self.kind == 'phase_composition':
            if not self.phases or any(x is not None for x in (self.phase, self.site_fractions, self.property, self.value)):
                raise ValueError('phase_composition requires phases, without property fields')
        elif (self.phases or not self.phase or not self.site_fractions or not self.property
              or self.value is None or not self.reference_state):
            raise ValueError('property requires phase, site_fractions, property, value and reference_state')
        return self


class ParameterFitRequest(Strict):
    tdb_files: list[str] = Field(min_length=1, max_length=10)
    components: list[str] = Field(min_length=2, max_length=8)
    phases: list[str] = Field(min_length=1)
    parameters: list[FitParameter] = Field(min_length=1, max_length=12)
    observations: list[FitObservation] = Field(min_length=1, max_length=200)
    reference_temperature: float = Field(default=298.15, gt=0)
    pressure: float = Field(default=101325, gt=0)
    sampling_density: int = Field(default=100, ge=20, le=1000)
    max_nfev: int = Field(default=60, ge=1, le=200)
    regularization: float = Field(default=0., ge=0)
    finite_difference_step: float = Field(default=1e-4, ge=1e-7, le=.1)
    stability_scale_J_mol_atoms: float = Field(default=100., gt=0)
    preserve_training_assemblages: bool = True

    @model_validator(mode='after')
    def consistent(self):
        self.components = [c.upper() for c in self.components]
        self.phases = [p.upper() for p in self.phases]
        if 'VA' in self.components or len(set(self.components)) != len(self.components) or len(set(self.phases)) != len(self.phases):
            raise ValueError('Select unique real components and unique phases')
        if len({p.id for p in self.parameters}) != len(self.parameters):
            raise ValueError('Parameter ids must be unique')
        pairs = [(k,p.basis) for p in self.parameters for k in p.keys]
        if len(set(pairs)) != len(pairs):
            raise ValueError('Each key/basis may occur only once; use grouped keys for tied parameters')
        if len({o.id for o in self.observations}) != len(self.observations) or not any(o.role == 'train' for o in self.observations):
            raise ValueError('Observation ids must be unique and training data are required')
        def composition(values):
            values = {k.upper():v for k,v in values.items()}
            if not set(values) <= set(self.components) or any(v<0 for v in values.values()) or abs(sum(values.values())-1)>1e-9:
                raise ValueError('Compositions must be atomic fractions summing to one in selected components')
            return {c:values.get(c,0.) for c in self.components}
        for obs in self.observations:
            obs.composition = composition(obs.composition)
            for target in obs.phases:
                target.phase = target.phase.upper()
                if target.composition is not None:
                    target.composition = composition(target.composition)
                if target.phase not in self.phases:
                    raise ValueError('Observation phase must be selected')
            if obs.phase:
                obs.phase = obs.phase.upper()
                if obs.phase not in self.phases:
                    raise ValueError('Property phase must be selected')
        return self
