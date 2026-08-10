#!/bin/sh
# ASGI rather than WSGI so the same process serves both HTTP and the realtime
# websocket route. Sync Django views keep working - they run in a threadpool -
# and dropping back to habits.wsgi is a safe rollback that only costs realtime.
#
# uvicorn_worker is the maintained home of this worker class; the old
# uvicorn.workers module still exists but is deprecated and due for removal.
gunicorn --bind 0.0.0.0:3000 --workers 3 -k uvicorn_worker.UvicornWorker habits.asgi:application
