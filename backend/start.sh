#!/bin/bash

# If SERVER_ENVIRONMENT is local, use mock PropelAuth
if [ "$SERVER_ENVIRONMENT" = "local" ]; then
    echo "Using mock PropelAuth for local environment"
    cp /workdir/mock/propelauth_fastapi_mock.py /workdir/.venv/lib/python3.12/site-packages/propelauth_fastapi/__init__.py
fi

# Wait for database to be ready (if using external DB)
echo "Waiting for database to be ready..."
sleep 5

# Skip all seeding scripts - they will be handled by the auto-seeding system
echo "🚀 Skipping manual seeding - using auto-seeding system instead"

# Start the application
# UVICORN_WORKERS is optional (default 1). Each worker gets its own DB pool, so
# keep UVICORN_WORKERS * (DB_POOL_SIZE + DB_MAX_OVERFLOW) < Postgres max_connections.
exec uvicorn aci.server.main:app --proxy-headers --forwarded-allow-ips=* --host 0.0.0.0 --port 8000 --no-access-log --workers "${UVICORN_WORKERS:-1}"
