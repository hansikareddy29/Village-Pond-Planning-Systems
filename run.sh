#!/usr/bin/env bash
# Startup script for Village Pond Planning Backend API

set -e

DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" >/dev/null 2>&1 && pwd )"
cd "$DIR"

# Check if virtualenv exists, if not create one
if [ ! -d "venv" ]; then
    echo "Creating Python virtual environment in ./venv..."
    python3 -m venv venv
    ./venv/bin/pip install --upgrade pip
    ./venv/bin/pip install -r requirements.txt
fi

echo "================================================================="
echo " Starting Village Pond Planning & Catchment Analysis API Server"
echo "================================================================="
echo " API Docs:    http://localhost:8000/docs"
echo " Redoc:       http://localhost:8000/redoc"
echo " Web UI:      http://localhost:8000/"
echo " Endpoints:   POST http://localhost:8000/analyzeContour"
echo "              POST http://localhost:8000/findCatchment"
echo "================================================================="

./venv/bin/uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload

