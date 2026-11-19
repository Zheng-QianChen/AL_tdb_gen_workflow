"""Web and CLI share the same CALPHAD fitting implementation."""
from pathlib import Path
from fastapi import APIRouter, Request
from config import BASE_DATA_DIR
from routes.tdb_routes import compute
from src.parameter_fit_settings import ParameterFitRequest

parameter_fit_router = APIRouter()


@parameter_fit_router.post('/parameter-fit/demo')
async def demo(request: Request):
    from examples.parameter_fit_demo import prepare_demo
    return await compute(request,prepare_demo)


@parameter_fit_router.post('/parameter-fit/calculate')
async def calculate(request: Request, data: ParameterFitRequest):
    from src.parameter_fit import run_fit
    result = await compute(request,run_fit,data)
    result['urls'] = {key:'/get_data_file/'+Path(path).resolve().relative_to(BASE_DATA_DIR).as_posix()
                      for key,path in result['files'].items()}
    return result
