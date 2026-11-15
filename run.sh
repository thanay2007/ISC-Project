#!/usr/bin/env bash
set -e
cd -- "$(dirname -- "${BASH_SOURCE[0]}")"

case "${1:-}" in
    --local-database)
        export DATABASE_URL=sqlite:///./.verifex/verifex.sqlite3
        echo 'Using local SQLite at .verifex/verifex.sqlite3.'
        shift
        ;;
esac
if [[ $# -ne 0 ]]; then
    echo 'Usage: bash ./run.sh [--local-database]' >&2
    exit 2
fi

if [[ -f .venv/Scripts/python.exe ]]; then
    python=./.venv/Scripts/python.exe
elif [[ -x .venv/bin/python ]]; then
    python=./.venv/bin/python
else
    echo 'Python virtual environment missing. Follow the local setup in documentation/SETUP.md.' >&2
    exit 1
fi

if ! command -v npm >/dev/null || ! command -v node >/dev/null; then
    echo 'Node.js and npm are required. Install Node.js and reopen your terminal.' >&2
    exit 1
fi
if [[ ! -f frontend/node_modules/next/package.json ]]; then
    echo 'Frontend dependencies missing. Run npm --prefix frontend ci from the project folder.' >&2
    exit 1
fi
if [[ ! -f .env ]]; then
    "$python" backend/setup_env.py
fi
"$python" - <<'PY'
from backend.verifex.config import Settings
from backend.verifex.db import normalize_database_url

try:
    normalize_database_url(Settings().database_url)
except ValueError as error:
    raise SystemExit(str(error)) from None
PY

stop_service() {
    local pid=$1 windows_pid
    if [[ $OSTYPE == msys* ]]; then
        # Next.js and the Windows Python launcher can have native child processes.
        windows_pid=$(ps -p "$pid" | awk -v pid="$pid" '$1 == pid { print $4 }')
        if [[ $windows_pid =~ ^[0-9]+$ ]]; then
            taskkill.exe //PID "$windows_pid" //T //F >/dev/null 2>&1 || kill "$pid" 2>/dev/null || true
        fi
    else
        kill -TERM -- "-$pid" 2>/dev/null || true
    fi
}

cleanup() {
    local pid
    for pid in "${service_pids[@]}"; do
        stop_service "$pid"
    done
    wait "${service_pids[@]}" 2>/dev/null || true
}

service_pids=()
trap cleanup EXIT
trap 'exit 130' INT
trap 'exit 143' TERM
trap 'exit 129' HUP
# Give each service its own process group so the launcher can stop its workers.
set -m
"$python" -m uvicorn backend.verifex.main:app --host 127.0.0.1 --port 8000 </dev/null &
service_pids+=("$!")
(
    cd frontend
    exec npm run dev -- --hostname localhost --port 3000
) </dev/null &
service_pids+=("$!")

echo 'VERIFEX is starting at http://localhost:3000. Press Ctrl+C to stop both services.'
wait -n "${service_pids[@]}"
