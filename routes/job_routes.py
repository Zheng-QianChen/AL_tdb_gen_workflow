"""Browser entry points for preparing and submitting an FP round with DPDispatcher."""
import os
from hashlib import sha256
from pathlib import Path
from urllib.parse import urlsplit

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from config import BASE_DATA_DIR, RUN_DIR, STATIC_DIR, safe_name
from routes.tdb_routes import compute
from src import fp, hpc_monitor
from src.run_lock import RunBusyError
from src.workflow import status

job_router = APIRouter()


def run_file(name):
    return RUN_DIR / safe_name(name)


def profile_directory():
    path = Path(os.environ.get('AL_TDB_MACHINE_DIR', Path.home() / '.altdb' / 'machines')).resolve()
    if path.is_relative_to(BASE_DATA_DIR) or BASE_DATA_DIR.is_relative_to(path):
        raise ValueError('Choose a machine profile directory separate from run data')
    return path


def profile_file(name):
    root = profile_directory()
    path = (root / safe_name(name)).resolve()
    if not path.is_relative_to(root) or path.suffix.lower() != '.json' or not path.is_file():
        raise ValueError('Choose an installed DPDispatcher machine profile')
    return path


@job_router.get('/jobs')
def jobs_page():
    return FileResponse(STATIC_DIR / 'jobs.html')


@job_router.get('/api/jobs/options')
def options():
    try:
        root = profile_directory()
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    return {'runs': sorted(p.name for p in RUN_DIR.glob('*.json') if p.is_file()),
            'machines': sorted(p.name for p in root.glob('*.json') if p.is_file() and p.resolve().is_relative_to(root)),
            'profile_directory': str(root)}


@job_router.get('/api/jobs/monitor')
def monitor():
    return hpc_monitor.snapshot()


@job_router.get('/api/jobs/state')
def job_state(config: str):
    try:
        state = status(run_file(config))
    except (ValueError, OSError, KeyError) as exc:
        raise HTTPException(422, str(exc)) from exc
    return {key: state.get(key) for key in ('phase', 'iteration', 'status', 'results_ready', 'dispatch', 'collection')}


class JobRequest(BaseModel):
    config: str
    machine: str = ''
    iteration: int = Field(ge=0)
    confirmation: str = ''


def run_action(action, data):
    config = run_file(data.config)
    state = status(config)
    if state['iteration'] != data.iteration or state['status'] != 'waiting':
        raise ValueError('This round changed. Refresh the run before continuing.')
    if state.get('results_ready'):
        raise ValueError('Results for this round are already available')
    dispatch_state = (state.get('dispatch') or {}).get('status')
    if action == 'submit' and dispatch_state in {'submitted', 'finished', 'interrupted_or_failed'}:
        raise ValueError('This round already has a submission. Refresh and use the recovery action.')
    if action == 'recover' and dispatch_state not in {'submitted', 'interrupted_or_failed'}:
        raise ValueError('There is no pending submission to recover')
    if action == 'collect':
        return fp.collect(config, iteration=data.iteration)
    machine = profile_file(data.machine)
    if action == 'plan':
        fp.prepare(config, machine)
    plan = fp.dispatch(config, machine, dry_run=True, iteration=data.iteration)
    manifest = Path(plan['directory']) / 'manifest.json'
    token = sha256(manifest.read_bytes()).hexdigest()
    if action == 'plan':
        return {**plan, 'confirmation': token, 'iteration': data.iteration}
    if data.confirmation != token:
        raise ValueError('Preview this prepared batch before submitting')
    return fp.dispatch(config, machine, wait=(action == 'recover'), iteration=data.iteration)


@job_router.post('/api/jobs/{action}')
async def job_action(action: str, data: JobRequest, request: Request):
    if action not in {'plan', 'submit', 'recover', 'collect'}:
        raise HTTPException(404, 'Unknown job action')
    origin = request.headers.get('origin')
    if request.url.hostname not in {'127.0.0.1', 'localhost', '::1', 'testserver'} or (
            origin and urlsplit(origin).netloc != request.headers.get('host')):
        raise HTTPException(403, 'Use the local server window to submit jobs')
    try:
        return await compute(request, run_action, action, data)
    except RunBusyError as exc:
        raise HTTPException(409, str(exc)) from exc
