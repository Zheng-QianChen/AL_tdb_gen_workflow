"""Inputs shared by the Gibbs API, CLI, and terminal interface."""
from typing import Literal
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class GibbsSource(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)
    config: str | None = None
    tdb_files: list[str] = Field(default_factory=list, max_length=10)
    phase: str | None = None

    @model_validator(mode="after")
    def source_present(self):
        if not self.config and not self.tdb_files:
            raise ValueError("Supply a workflow config or TDB files")
        return self


class GibbsRequest(GibbsSource):
    mode: Literal["gx", "gt"] = "gx"
    sublattices: list[list[str]] | None = None
    temperatures: list[float] = Field(min_length=1, max_length=501)
    pressure: float = Field(default=101325, gt=0)
    composition_start: dict[str, float] | None = None
    composition_end: dict[str, float] | None = None
    composition: dict[str, float] | None = None
    site_fractions: list[dict[str, float]] | None = None
    x_axis: str | None = None
    points: int = Field(default=101, ge=2, le=501)
    starts: int = Field(default=8, ge=2, le=32)
    allow_missing_ordered_endmembers: bool = False

    @field_validator("temperatures")
    @classmethod
    def valid_temperatures(cls, values):
        if any(t <= 0 for t in values) or len(set(values)) != len(values):
            raise ValueError("Temperatures must be unique positive Kelvin values")
        return sorted(values)

    @model_validator(mode="after")
    def curve_inputs(self):
        if self.mode == "gx":
            if self.composition_start is None or self.composition_end is None:
                raise ValueError("G-x requires composition_start and composition_end")
            if self.site_fractions is not None or self.composition is not None:
                raise ValueError("G-x optimizes site fractions; use composition_start/end")
            if len(self.temperatures) * self.points > 2000:
                raise ValueError("Use at most 2000 temperature/composition points per request")
        elif self.composition is None:
            raise ValueError("G-T requires a fixed overall composition")
        elif self.composition_start is not None or self.composition_end is not None:
            raise ValueError("G-T uses composition, not composition_start/end")
        return self
