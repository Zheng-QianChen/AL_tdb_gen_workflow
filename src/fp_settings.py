"""Compute environment, intentionally separate from the scientific task config."""
from pathlib import Path
from typing import Literal
from pydantic import BaseModel, ConfigDict, Field, model_validator
from config import safe_name


class FPSettings(BaseModel):
    model_config = ConfigDict(extra="forbid")
    command: str = Field(min_length=1)
    machine: dict
    resources: dict
    input_files: dict[str, str]
    potcars: dict[str, str]
    backward_files: list[str] = Field(default_factory=lambda: ["OUTCAR", "CONTCAR", "vasprun.xml"])
    result_format: Literal["vasp/outcar", "vasp/xml", "deepmd/npy"] = "vasp/outcar"
    result_file: str = "OUTCAR"
    check_interval: int = Field(default=30, ge=1)

    @model_validator(mode="after")
    def validate_environment(self):
        if self.machine.get("batch_type") not in {"Slurm", "Shell"}:
            raise ValueError("This adapter supports Slurm and Shell")
        if not self.machine.get("context_type") or not self.machine.get("remote_root"):
            raise ValueError("machine needs context_type and remote_root")
        if "INCAR" not in self.input_files:
            raise ValueError("input_files must provide INCAR")
        for name in [*self.input_files, *self.backward_files, self.result_file]:
            if safe_name(name) != name:
                raise ValueError("Use simple, unchanged task-local filenames")
        if {"POSCAR", "POTCAR"} & set(self.input_files):
            raise ValueError("POSCAR is generated and POTCAR is assembled from potcars")
        if set(self.backward_files) & (set(self.input_files) | {"POSCAR", "POTCAR"}):
            raise ValueError("backward_files must not overwrite prepared inputs")
        if self.result_file in self.input_files or self.result_file in {"POSCAR", "POTCAR"}:
            raise ValueError("Result must not overwrite an input")
        if self.result_file not in self.backward_files:
            raise ValueError("backward_files must include result_file")
        if any(int(self.resources.get(key, 0)) < 1 for key in ("number_node", "cpu_per_node", "group_size")):
            raise ValueError("resources needs positive number_node, cpu_per_node and group_size")
        return self


def load_machine(path):
    path = Path(path).expanduser().resolve()
    settings = FPSettings.model_validate_json(path.read_text(encoding="utf-8"))
    return path, settings


def source_file(machine_path, value):
    value = Path(value).expanduser()
    path = value if value.is_absolute() else machine_path.parent / value
    path = path.resolve()
    if not path.is_file():
        raise ValueError(f"Input file does not exist: {path}")
    return path
