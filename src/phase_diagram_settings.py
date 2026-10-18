"""Shared, bounded requests for multi-phase equilibrium and phase diagrams."""
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class DiagramSource(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)
    tdb_files: list[str] = Field(default_factory=list, max_length=10)
    config: str | None = None

    @model_validator(mode="after")
    def has_source(self):
        if not self.tdb_files and not self.config:
            raise ValueError("Supply TDB files or a trained workflow config")
        return self


class PhaseDiagramRequest(DiagramSource):
    mode: Literal["binary", "ternary", "isopleth", "property", "point"] = "binary"
    components: list[str] = Field(min_length=2, max_length=8)
    phases: list[str] | None = None
    suspended_phases: list[str] = Field(default_factory=list)
    temperatures: list[float] = Field(min_length=1, max_length=301)
    pressure: float = Field(default=101325, gt=0)
    x_component: str | None = None
    composition_range: tuple[float, float] = (0., 1.)
    composition: dict[str, float] | None = None
    composition_start: dict[str, float] | None = None
    composition_end: dict[str, float] | None = None
    points: int = Field(default=31, ge=2, le=301)
    sampling_density: int = Field(default=200, ge=20, le=2000)
    verify_sampling: bool = True
    map_boundaries: bool = True
    max_mapping_steps: int = Field(default=5000, ge=10, le=20000)
    allow_missing_ordered_endmembers: bool = False

    @field_validator("components", "phases", "suspended_phases")
    @classmethod
    def names(cls, values):
        if values is None:
            return values
        values = [s.strip().upper() for s in values]
        if any(not s for s in values) or len(set(values)) != len(values):
            raise ValueError("Names must be nonempty and unique")
        return values

    @field_validator("temperatures")
    @classmethod
    def temperatures_in_kelvin(cls, values):
        if any(t <= 0 for t in values) or len(set(values)) != len(values):
            raise ValueError("Temperatures must be unique positive Kelvin values")
        return sorted(values)

    @model_validator(mode="after")
    def diagram_inputs(self):
        if "VA" in self.components:
            raise ValueError("components lists real elements only; VA is included automatically")
        if self.phases == []:
            raise ValueError("Use phases=null for all phases; an empty list selects no phases")
        if self.phases and set(self.phases) & set(self.suspended_phases):
            raise ValueError("A phase cannot be both selected and suspended")
        if self.x_component:
            self.x_component = self.x_component.strip().upper()
            if self.x_component not in self.components:
                raise ValueError("x_component must be in components")
        lo, hi = self.composition_range
        if not 0 <= lo < hi <= 1:
            raise ValueError("composition_range must satisfy 0 <= min < max <= 1")
        for name in ("composition", "composition_start", "composition_end"):
            values = getattr(self, name)
            if values is None:
                continue
            normalized = {k.upper(): v for k, v in values.items()}
            if len(normalized) != len(values) or not set(normalized) <= set(self.components):
                raise ValueError(f"{name} contains duplicate or unselected elements")
            if any(v < 0 for v in normalized.values()) or abs(sum(normalized.values()) - 1) > 1e-10:
                raise ValueError(f"{name} must contain nonnegative atomic fractions summing to one")
            setattr(self, name, {c: normalized.get(c, 0.) for c in self.components})
        if self.mode == "binary" and len(self.components) != 2:
            raise ValueError("binary requires exactly two elements; use isopleth for a multi-component section")
        if self.mode == "ternary" and (len(self.components) != 3 or len(self.temperatures) != 1):
            raise ValueError("ternary requires exactly three elements and one temperature")
        if self.mode in {"binary", "isopleth", "property"} and len(self.temperatures) < 2:
            raise ValueError("This mode requires at least two temperatures; use point for a single equilibrium")
        if self.mode == "point" and len(self.temperatures) != 1:
            raise ValueError("point requires exactly one temperature")
        if self.mode in {"point", "property"}:
            if self.composition is None:
                raise ValueError("point/property requires composition")
        elif self.composition is not None:
            raise ValueError("composition is only used for point/property")
        if self.mode == "isopleth":
            if self.composition_start is None or self.composition_end is None:
                raise ValueError("isopleth requires composition_start and composition_end")
            if self.composition_start == self.composition_end:
                raise ValueError("Composition path endpoints must differ")
        elif self.composition_start is not None or self.composition_end is not None:
            raise ValueError("Composition path endpoints are only used for isopleth")
        count = (self.points * (self.points + 1) // 2 if self.mode == "ternary" else
                 len(self.temperatures) * (self.points if self.mode in {"binary", "isopleth"} else 1))
        if count > 10000:
            raise ValueError("Use at most 10000 equilibrium points per request")
        return self
