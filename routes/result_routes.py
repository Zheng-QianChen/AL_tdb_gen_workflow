"""Local result ledger: inspect evidence and create attributed revisions."""
from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import FileResponse
from pydantic import BaseModel, ConfigDict, Field

from config import BASE_DATA_DIR, RUN_DIR, STATIC_DIR, resolve_data_path
from src.result_records import (
    ResultConflictError, list_attempts, list_results, result_detail, revise_result,
)

result_router = APIRouter()


def config_path(value):
    """Only expose configurations inside this application's data root."""
    try:
        if not value or not str(value).strip():
            raise ValueError("Choose a run configuration")
        path = Path(value)
        if not path.is_absolute() and len(path.parts) == 1:
            path = RUN_DIR / (value if value.endswith('.json') else value + '.json')
        else:
            path = resolve_data_path(value)
        path = path.resolve()
        if not path.is_relative_to(BASE_DATA_DIR) or path.suffix.lower() != '.json':
            raise ValueError("Configuration must be a JSON file inside the data directory")
        if not path.is_file():
            raise FileNotFoundError("Run configuration not found")
        return path
    except FileNotFoundError as exc:
        raise HTTPException(404, detail=str(exc)) from exc
    except (ValueError, OSError) as exc:
        raise HTTPException(422, detail=str(exc)) from exc


def call_result(function, *args, **kwargs):
    try:
        return function(*args, **kwargs)
    except ResultConflictError as exc:
        raise HTTPException(409, detail=str(exc)) from exc
    except (FileNotFoundError, KeyError) as exc:
        raise HTTPException(404, detail=str(exc)) from exc
    except (ValueError, OSError) as exc:
        raise HTTPException(422, detail=str(exc)) from exc


@result_router.get('/results')
def page():
    return FileResponse(STATIC_DIR / 'results.html')


@result_router.get('/api/results/configs')
def configs():
    return {'configs': [p.name for p in sorted(RUN_DIR.glob('*.json'))
                        if p.resolve().is_relative_to(BASE_DATA_DIR)]}


@result_router.get('/api/results')
def records(config: str, iteration: Annotated[int | None, Query(ge=0)] = None):
    return call_result(list_results, config_path(config), iteration=iteration)


@result_router.get('/api/results/attempts')
def attempts(config: str, iteration: Annotated[int | None, Query(ge=0)] = None):
    return call_result(list_attempts, config_path(config), iteration=iteration)


@result_router.get('/api/results/{record_id}')
def detail(record_id: str, config: str):
    return call_result(result_detail, config_path(config), record_id)


class Amendment(BaseModel):
    model_config = ConfigDict(extra='forbid')
    expected_revision: int = Field(ge=0)
    actor: str = Field(min_length=1, max_length=200)
    reason: str = Field(min_length=1, max_length=4000)
    energy_ev_cell: float | None = Field(default=None, allow_inf_nan=False)
    note: str | None = Field(default=None, max_length=10000)


@result_router.patch('/api/results/{record_id}')
def amend(record_id: str, config: str, body: Amendment):
    changes = body.model_dump(include={'energy_ev_cell', 'note'}, exclude_unset=True)
    if not changes or any(value is None for value in changes.values()):
        raise HTTPException(422, detail='Provide a finite energy or a text note')
    return call_result(revise_result, config_path(config), record_id,
                       changes=changes, actor=body.actor, reason=body.reason,
                       expected_revision=body.expected_revision)
