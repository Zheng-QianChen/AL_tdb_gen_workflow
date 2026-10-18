"""Validated task inputs shared by the API and checkpoint runner."""
import json
from typing import Literal
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from config import resolve_data_path, safe_name


def parse_hyperparameters(value):
    if value is None or value == "":
        return {}
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except json.JSONDecodeError as exc:
            raise ValueError("ML_hyper_parameters must be a JSON object") from exc
    if not isinstance(value, dict):
        raise ValueError("ML_hyper_parameters must be a JSON object")
    return value


class Reference(BaseModel):
    file: str
    index_name: str = "symbol"
    col_name: str


class Descriptor(BaseModel):
    index_name: str = "symbol"
    col_name: list[str] = Field(min_length=1)


class SublatticeSettings(BaseModel):
    model_config = ConfigDict(extra="allow")
    site_holder: list[str]
    sublattice_number: int = Field(ge=1)
    occup_atoms_in_tdb: list[float]
    comp: list[list[str]]
    Atom_ref: Reference

    @model_validator(mode="after")
    def check_sites(self):
        from src.thermodynamics import site_fractions
        count = self.sublattice_number
        if any(len(values) != count for values in (self.site_holder, self.occup_atoms_in_tdb, self.comp)):
            raise ValueError("Sublattice fields must match sublattice_number")
        if len(set(self.site_holder)) != count or any(len(s) != 1 or not "A" <= s <= "Z" for s in self.site_holder):
            raise ValueError("site_holder must contain distinct uppercase letters A-Z")
        if any(not group or len(set(group)) != len(group) for group in self.comp):
            raise ValueError("Each sublattice needs unique non-empty constituents")
        if any(not e.isalpha() or not e.isupper() for group in self.comp for e in group):
            raise ValueError("Use uppercase element symbols")
        site_fractions(self.occup_atoms_in_tdb)
        return self


class QueryCounts(BaseModel):
    near_hall: int = Field(default=5, ge=0)
    unstable: int = Field(default=0, ge=0)
    random: int = Field(default=5, ge=0)

    @model_validator(mode="after")
    def positive_budget(self):
        if self.near_hall + self.unstable + self.random == 0:
            raise ValueError("At least one query count must be positive")
        return self


class ALSettings(BaseModel):
    model_config = ConfigDict(extra="allow")
    ML_model: Literal["gbr", "rf", "lr", "ridge", "lasso", "knn", "svr", "mlp", "dt", "xgb", "catboost"] = "gbr"
    ML_style: Literal["flat", "stack"] = "flat"
    descriptor: dict[str, Descriptor]
    ML_hyper_parameters: dict = Field(default_factory=dict)
    normalizer: Literal["Zscore", "mmscale"] = "Zscore"
    eigen_weight: list[float] = Field(default_factory=list)
    quest: QueryCounts = Field(default_factory=QueryCounts)
    generate_DFT_path: str
    calced_DFT_path: str
    pkl_phase_path: str
    pkl_show_control: str = "high"

    @field_validator("ML_hyper_parameters", mode="before")
    @classmethod
    def parse_parameters(cls, value):
        return parse_hyperparameters(value)

    @field_validator("descriptor")
    @classmethod
    def nonempty_descriptors(cls, value):
        if not value:
            raise ValueError("At least one descriptor table is required")
        return value


class TaskConfig(BaseModel):
    model_config = ConfigDict(extra="allow")
    phase_name: str
    record_path: str
    structure_file: str
    structure_out_file: str
    structure_convert_to_primitive: str = "no"
    init_random_n: int = Field(default=5, ge=1)
    random_seed: int = 42
    tdb_model: SublatticeSettings
    AL_set: ALSettings

    @model_validator(mode="before")
    @classmethod
    def legacy_phase_name(cls, value):
        if isinstance(value, dict) and "phase_name" not in value and "PHASE_NAME" in value:
            value = {**value, "phase_name": value["PHASE_NAME"]}
        return value

    @model_validator(mode="after")
    def validate_paths(self):
        safe_name(self.phase_name)
        for path in [self.record_path, self.structure_file, self.structure_out_file,
                     self.tdb_model.Atom_ref.file, *self.AL_set.descriptor,
                     self.AL_set.generate_DFT_path, self.AL_set.calced_DFT_path,
                     self.AL_set.pkl_phase_path]:
            resolve_data_path(path)
        return self
