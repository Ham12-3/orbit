"""Local dev server, restarted on code changes by `watchfiles app.dev.serve app`.

Not `uvicorn --reload`: on Windows its reloader stops the worker with CTRL_C_EVENT, which never
arrives when uvicorn runs under `concurrently`, so reloads hang. watchfiles terminates the process.
"""

import uvicorn

DEV_HOST = "127.0.0.1"
DEV_PORT = 8000


def serve() -> None:
    uvicorn.run("app.main:create_app", factory=True, host=DEV_HOST, port=DEV_PORT)
