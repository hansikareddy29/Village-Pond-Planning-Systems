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
    ./venv/bin/pip install -r requirements.txt
fi

echo "================================================================="
echo " Starting Village Pond Planning & Catchment Analysis API Server"
echo "================================================================="
echo " API Docs (Swagger): http://localhost:8000/docs"
echo " API Docs (ReDoc):   http://localhost:8000/redoc"
echo " Health Check:       http://localhost:8000/health"
echo " Primary Endpoint:   POST http://localhost:8000/analyzeContour"
echo "================================================================="

# Start FastAPI server using Python module invocation
./venv/bin/python -m uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
