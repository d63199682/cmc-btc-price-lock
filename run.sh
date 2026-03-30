#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"
python -m uvicorn app.main:APP --reload --host 0.0.0.0 --port 8000
