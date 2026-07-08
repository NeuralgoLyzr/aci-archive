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

# Bind address/port is only configurable via env vars in on-prem mode;
# otherwise this matches the original hardcoded 0.0.0.0:8000.
BIND_HOST="0.0.0.0"
BIND_PORT="8000"
if [ "$(echo "${IS_ONPREM_DEPLOYMENT:-false}" | tr '[:upper:]' '[:lower:]')" = "true" ]; then
    BIND_HOST="${HOST:-0.0.0.0}"
    BIND_PORT="${PORT:-8000}"
fi

# Start the application
exec uvicorn aci.server.main:app --proxy-headers --forwarded-allow-ips=* --host "$BIND_HOST" --port "$BIND_PORT" --no-access-log
