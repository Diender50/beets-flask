
#!/bin/sh
source ./common.sh

log_current_user
log_version_info

cd /repo

mkdir -p /repo/log
mkdir -p /config/beets
mkdir -p /config/beets-flask

# ------------------------------------------------------------------------------------ #
#                                     start backend                                    #
# ------------------------------------------------------------------------------------ #

# Ignore warnings for production builds
export PYTHONWARNINGS="ignore"

# running the server from inside the backend dir makes imports and redis easier
cd /repo/backend

redis-server --daemonize yes >/dev/null 2>&1


# blocking
python ./launch_db_init.py
python ./launch_redis_workers.py > /logs/redis_workers.log 2>&1

# keeps running in the background
python ./launch_watchdog_worker.py &

redis-cli FLUSHALL >/dev/null 2>&1

export IB_SERVER_CONFIG=prod

# Use uvicorn directly (no --reload) for production.
# socketio with AsyncRedisManager works with multiple workers via Redis pub/sub,
# but 1 worker is safer to avoid any in-process state issues.
uvicorn launch_fastapi:app \
    --host 0.0.0.0 \
    --port 5002 \
    --workers 1 \
    --log-level info \
    --no-access-log
