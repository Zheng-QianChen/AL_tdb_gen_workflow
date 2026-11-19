"""Exercise the installed server transport, which TestClient bypasses."""
import os
from pathlib import Path
import socket
import subprocess
import sys
import time
from urllib.error import URLError
from urllib.request import urlopen

from websockets.sync.client import connect


def test_real_uvicorn_websocket(tmp_path):
    with socket.socket() as reservation:
        reservation.bind(('127.0.0.1', 0))
        port = reservation.getsockname()[1]
    env = {**os.environ, 'AL_TDB_DATA_DIR': str(tmp_path / 'data')}
    with (tmp_path / 'server.log').open('w+') as log:
        process = subprocess.Popen(
            [sys.executable, '-m', 'uvicorn', 'app:app', '--host', '127.0.0.1',
             '--port', str(port)], cwd=Path(__file__).resolve().parents[1],
            env=env, stdout=log, stderr=log)
        try:
            deadline = time.monotonic() + 60
            while True:
                try:
                    with urlopen(f'http://127.0.0.1:{port}/health', timeout=1) as response:
                        assert response.status == 200
                    break
                except (URLError, TimeoutError):
                    if process.poll() is not None or time.monotonic() >= deadline:
                        log.seek(0)
                        raise AssertionError(log.read())
                    time.sleep(.1)
            with connect(f'ws://127.0.0.1:{port}/ws', open_timeout=5) as client:
                client.send('{"action":"noop"}')
                assert client.ping().wait(5)
        finally:
            process.terminate()
            try:
                process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=10)
