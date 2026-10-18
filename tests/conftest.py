import os
from pathlib import Path
import tempfile
import pytest

# Set before importing app/config. Never write in a user's real run directory.
root = Path(__file__).resolve().parents[1] / ".test-data"
root.mkdir(exist_ok=True)
os.environ["AL_TDB_DATA_DIR"] = tempfile.mkdtemp(prefix="session-", dir=root)
os.environ["MPLCONFIGDIR"] = str(root / "matplotlib")


@pytest.fixture
def demo():
    from examples.demo import prepare_demo
    return prepare_demo()


@pytest.fixture
def phase(demo):
    from src.main_process.al_worker import ALRunner
    from src.settings import TaskConfig
    path, data = demo
    runner = ALRunner("test", path)
    runner.data = TaskConfig.model_validate(data).model_dump()
    runner.phase = runner.init_process(runner.data)
    runner.process = 1
    return runner
