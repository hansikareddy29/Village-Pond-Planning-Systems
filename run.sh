#!/usr/bin/env bash
# Startup script for Village Pond Planning Backend API

set -e

DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" >/dev/null 2>&1 && pwd )"
cd "$DIR"

# Check if virtualenv exists, if not create one
if [ ! -d "venv" ]; then
    echo "Creating Python virtual environment in ./venv..."
    python3 -m venv --system-site-packages venv
    ./venv/bin/pip install --upgrade pip
fi

echo "Ensuring required packages are installed..."
./venv/bin/pip install -r requirements.txt

PORT="${PORT:-5000}"

echo "================================================================="
echo " Starting Village Pond Planning & Catchment Analysis API Server"
echo "================================================================="
echo " Server Host & Port: 0.0.0.0:${PORT}"
echo " Web GIS Dashboard:  http://localhost:${PORT}/"
echo " Observability GUI:  http://localhost:${PORT}/observability"
echo " Prometheus Metrics: http://localhost:${PORT}/metrics"
echo " API Documentation:  http://localhost:${PORT}/docs"
echo " Health Check:       http://localhost:${PORT}/health"
echo "================================================================="

# Start FastAPI server using Python module invocation
./venv/bin/python -m uvicorn app.main:app --host 0.0.0.0 --port "$PORT"

