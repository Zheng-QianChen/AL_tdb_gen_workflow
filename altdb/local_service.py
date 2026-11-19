"""Serve until stopped in the console or by the owning launcher's stop file."""
import asyncio
import os
from pathlib import Path

import uvicorn
from app import app
from config import HOST, PORT


async def main():
    token = os.environ['AL_TDB_INSTANCE']
    stop = Path(os.environ['AL_TDB_STOP_FILE'])
    @app.get('/launcher-instance', include_in_schema=False)
    def instance():
        return {'id': token}
    server = uvicorn.Server(uvicorn.Config(app, host=HOST, port=PORT))
    task = asyncio.create_task(server.serve())
    while not task.done():
        if stop.is_file():
            server.should_exit = True
        await asyncio.wait([task], timeout=.25)
    await task


if __name__ == '__main__':
    asyncio.run(main())
