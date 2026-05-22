#!/bin/bash
source ./docker/entrypoints/common.sh

log_current_user
log_version_info
log "Starting development environment..."

cd /repo

mkdir -p /repo/log
rm /repo/log/for_web.log >/dev/null 2>&1
rm /repo/frontend/vite.config.ts.timestamp-*.mjs >/dev/null 2>&1

mkdir -p /config/beets
mkdir -p /config/beets-flask

# ------------------------------------------------------------------------------------ #
#                                     start backend                                    #
# ------------------------------------------------------------------------------------ #

# running the server from inside the backend dir makes imports and redis easier
cd /repo/backend

redis-server --daemonize yes


# blocking
python ./launch_db_init.py
python ./launch_redis_workers.py

# keeps running in the background
python ./launch_watchdog_worker.py &

redis-cli FLUSHALL


# generate types for the frontend (only done in dev mode)
python ./generate_types.py

python ./launch_fastapi.py &
fastapi_pid=$!

cd /repo/frontend

# Ensure local CLI binaries (like vite) exist before first dev run.
if [ ! -x /repo/frontend/node_modules/.bin/vite ]; then
    echo "vite binary missing, installing frontend dependencies ..."
    pnpm install --frozen-lockfile
fi

# pnpm run build:dev &  # use this for debugging with ios (no cors allowed)
pnpm run dev & # normal dev, port 5173
vite_pid=$!
sleep 3
if ! kill -0 $vite_pid 2>/dev/null; then
    echo "starting vite failed, will try to fix this by installing dependencies ..."
    pnpm install
    pnpm run dev &
fi

# Keep container tied to backend lifecycle.
wait $fastapi_pid



# if we need to debug the continaer without running the webserver:
# tail -f /dev/null
