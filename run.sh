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

PORT="${PORT:-5000}"

echo "================================================================="
echo " Starting Village Pond Planning & Catchment Analysis API Server"
echo "================================================================="
echo " Container Port:     $PORT"
echo " External Host Port: 5250 (Mapped from Container Port 5000)"
echo " Interactive Docs:   http://localhost:${PORT}/docs"
echo " Evaluator Docs:     http://10.1.75.79:5250/docs"
echo " Health Check:       http://10.1.75.79:5250/health"
echo " Primary Endpoint:   POST http://10.1.75.79:5250/analyzeContour"
echo "================================================================="

# Start FastAPI server using Python module invocation
./venv/bin/python -m uvicorn app.main:app --host 0.0.0.0 --port "$PORT" --reload
