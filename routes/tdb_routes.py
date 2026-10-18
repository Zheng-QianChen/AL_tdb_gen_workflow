"""TDB export and task-scoped sublattice analysis."""
import asyncio
from functools import partial
from pathlib import Path
import re

from fastapi import APIRouter, Body, HTTPException, Request
from pydantic import BaseModel, Field

from config import BASE_DATA_DIR, RUN_DIR, resolve_data_path, safe_name
from src.main_process.al_worker import ALRunner
from src.main_process.subl_model_assess import subl_assess
from src.gibbs_settings import GibbsRequest, GibbsSource
from src.gibbs_compare import GibbsComparisonRequest
import src.generate as generate

tdb_router = APIRouter()


@tdb_router.post("/gibbs/reference-template")
async def gibbs_reference_template(request: Request, result: str = Body(embed=True)):
    from src.gibbs_compare import prepare_reference
    report = await compute(request, prepare_reference, result)
    report["urls"] = {key: "/get_data_file/" + Path(value).resolve().relative_to(BASE_DATA_DIR).as_posix()
                      for key, value in report["files"].items()}
    return report


@tdb_router.post("/gibbs/compare")
async def gibbs_compare(request: Request, data: GibbsComparisonRequest):
    from src.gibbs_compare import run_comparison
    report = await compute(request, run_comparison, data)
    report["urls"] = {key: "/get_data_file/" + Path(value).resolve().relative_to(BASE_DATA_DIR).as_posix()
                      for key, value in report["files"].items()}
    return report


@tdb_router.post("/gibbs/options")
async def gibbs_options(request: Request, data: GibbsSource):
    from src.gibbs import source_options
    return await compute(request, source_options, data)


@tdb_router.post("/gibbs/calculate")
async def gibbs_calculate(request: Request, data: GibbsRequest):
    from src.gibbs import run_curve
    result = await compute(request, run_curve, data)
    result["urls"] = {key: "/get_data_file/" + Path(value).resolve().relative_to(BASE_DATA_DIR).as_posix()
                      for key, value in result["files"].items()}
    return result


def assessment(request, task_id):
    assessments = request.app.state.manager.assessments
    if task_id is None and len(assessments) == 1:
        return next(iter(assessments.values()))
    if task_id not in assessments:
        raise HTTPException(409, "Generate a TDB first and specify its task_id")
    return assessments[task_id]


async def compute(request, function, *args, **kwargs):
    try:
        return await asyncio.get_running_loop().run_in_executor(
            request.app.state.manager.executor, partial(function, *args, **kwargs))
    except (ValueError, OSError, KeyError, ImportError) as exc:
        raise HTTPException(422, str(exc)) from exc


def model_from_filename(value):
    if not re.fullmatch(r"[1-9][0-9]*(?:_[A-Z]+)+\.csv", value):
        raise HTTPException(422, "Expected a model filename such as 2_A_B_A.csv")
    count, *sites = Path(value).stem.split("_")
    labels = list(dict.fromkeys(sites))
    if len(labels) != int(count) or labels != [chr(65 + i) for i in range(int(count))]:
        raise HTTPException(422, "Model labels must introduce A, B, C in order")
    return [int(count), ":".join(sites)]


class TdbGenerationRequest(BaseModel):
    user: str = "guest"
    mask: float = Field(default=5, ge=0, allow_inf_nan=False)
    input_file_path: str = "input"


@tdb_router.post("/generate_tdb")
async def generate_tdb(request: Request, data: TdbGenerationRequest):
    try:
        user = safe_name(data.user or "guest")
        config_name = safe_name(data.input_file_path or "input")
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    task_id = f"{user}_{config_name}"
    config_path = RUN_DIR / f"{config_name}.json"
    reader = ALRunner(task_id, config_path)
    result = await compute(request, reader.output_tdb_file, user, data.mask)
    analyzer = await compute(request, subl_assess,
        input_data_file=result["input_data"],
        vasp_ml_data_path=result["file_path"] / result["file_name_csv"],
        record_path=result["file_path"])
    request.app.state.manager.assessments[task_id] = analyzer
    return {"success": True, "task_id": task_id,
            "file_path": str(result["file_path"] / result["file_name_tdb"]),
            "sublatticeNumber": len(analyzer.site_weight)}


@tdb_router.post("/analyze_models")
async def analyze_models(request: Request, choosen: list[int] = Body(...), task_id: str | None = None):
    analyzer = assessment(request, task_id)
    if not choosen or any(value < 1 or value > len(analyzer.site_weight) for value in choosen):
        raise HTTPException(422, "Choose valid sublattice counts")
    await compute(request, analyzer.get_model_result_raw, choosen)
    return {"success": True, "message": "Model analysis completed"}


@tdb_router.post("/plot_base_analyze_models")
async def plot_base_analyze_models(request: Request, task_id: str | None = None):
    result = await compute(request, assessment(request, task_id).plot_model_result_raw)
    return {"success": True, **{
        key: "/get_data_file/" + Path(result[key]).resolve().relative_to(BASE_DATA_DIR).as_posix()
        for key in ("plot_file", "score_file")}}


class ElementGroupsRequest(BaseModel):
    selected_model: str


@tdb_router.post("/get_element_groups")
async def get_element_groups(request: Request, data: ElementGroupsRequest, task_id: str | None = None):
    analyzer = assessment(request, task_id)
    model = model_from_filename(data.selected_model)
    if len(model[1].split(":")) != len(analyzer.site_weight):
        raise HTTPException(422, "Model does not match this task's sublattices")
    groups = generate.get_model_site_elements(model=model, elements=analyzer.site_elements)
    return {"success": True, "element_groups": groups}


class FilterSubmitRequest(BaseModel):
    selected_model: str
    analys: list[list[str]]
    need_del: list[list[str]]
    fix: list[list[str]]


@tdb_router.post("/submit_filtered_elements")
async def submit_filtered_elements(request: Request, data: FilterSubmitRequest, task_id: str | None = None):
    analyzer = assessment(request, task_id)
    model = model_from_filename(data.selected_model)
    allowed = generate.get_model_site_elements(model=model, elements=analyzer.site_elements)
    if any(len(groups) != len(allowed) for groups in (data.analys, data.need_del, data.fix)):
        raise HTTPException(422, "Element groups do not match the selected model")
    for allowed_site, a, d, f in zip(allowed, data.analys, data.need_del, data.fix):
        groups = [set(a), set(d), set(f)]
        if (set.union(*groups) != set(allowed_site)
                or groups[0] & groups[1] or groups[0] & groups[2] or groups[1] & groups[2]
                or not (groups[0] | groups[2])):
            raise HTTPException(422, "Assign each allowed element to exactly one group; retain a constituent per site")
    analyzer.element_filter = data.model_dump()
    return {"success": True, "message": "Element choices saved for this task; use Export to write the database"}


class AmodelTdbGenerateRequest(BaseModel):
    output_path: str
    selected_model: dict
    element_groups: list[list[str]]
    include_metrics: bool = True
    file_format: str = "tdb"


@tdb_router.post("/tdb_generate_model_assessed")
async def tdb_generate_model_assessed(request: Request, data: AmodelTdbGenerateRequest, task_id: str | None = None):
    analyzer = assessment(request, task_id)
    model = model_from_filename(str(data.selected_model.get("model_name", "")))
    if len(model[1].split(":")) != len(analyzer.site_weight):
        raise HTTPException(422, "Model does not match this task")
    allowed = generate.get_model_site_elements(model=model, elements=analyzer.site_elements)
    if len(data.element_groups) != len(allowed) or any(
            not group or not set(group) <= set(site) or len(set(group)) != len(group)
            for group, site in zip(data.element_groups, allowed)):
        raise HTTPException(422, "Invalid export constituents")
    if data.file_format.lower().lstrip(".") != "tdb":
        raise HTTPException(422, "Only TDB export is supported")
    try:
        destination = resolve_data_path(data.output_path)
    except ValueError as exc:
        raise HTTPException(403, str(exc)) from exc
    exported = await compute(request, analyzer.output_all_tdb_file_assessed,
                  candidate_model=[model], site_elements=data.element_groups, tor=5,
                  save_path=destination)
    return {"success": True, "message": "Assessed TDB exported", "output_path": str(destination),
            "tdb_files": [str(path) for path in exported], "phase": analyzer.input_data["phase_name"]}
