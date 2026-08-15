#!/usr/bin/env bash
# 启动本项目 FastAPI 后端 + Vite HMR 预览。
# 用法:
#   ./start.sh           # 启动并打开 Vite 预览页
#   ./start.sh --no-open # 只启动不打开浏览器
#   VITE_PORT=5174 ./start.sh
set -euo pipefail

ROOT="$(cd "$(dirname "$0")" && pwd)"
OPEN_FLAG=()
for a in "$@"; do
    case "$a" in
        --no-open) OPEN_FLAG=(--no-open) ;;
    esac
done

backend_health_ok() {
    local port="$1"
    local body
    body="$(curl -fsS --connect-timeout 1 "http://127.0.0.1:${port}/api/health" 2>/dev/null || true)"
    [[ "$body" == *'"ok":true'* ]] || [[ "$body" == *'"ok": true'* ]]
}

ensure_backend() {
    local port_file="$ROOT/.runtime-macos/server.port"
    if [[ -f "$port_file" ]]; then
        local old_port
        old_port="$(tr -d '[:space:]' < "$port_file" || true)"
        if [[ -n "$old_port" ]] && backend_health_ok "$old_port"; then
            echo "[start] backend already running: http://127.0.0.1:${old_port}"
            return 0
        fi
    fi

    if [[ ! -x "$ROOT/start-project.command" ]]; then
        echo "[start] ERROR: missing start-project.command" >&2
        exit 1
    fi

    echo "[start] starting FastAPI backend..."
    NO_BROWSER=1 "$ROOT/start-project.command"
}

ensure_backend

PORT_FILE="$ROOT/.runtime-macos/server.port"
if [[ ! -f "$PORT_FILE" ]]; then
    echo "[start] ERROR: backend port file missing: $PORT_FILE" >&2
    exit 1
fi
BACKEND_PORT="$(tr -d '[:space:]' < "$PORT_FILE")"
if ! backend_health_ok "$BACKEND_PORT"; then
    echo "[start] ERROR: backend health check failed on port $BACKEND_PORT" >&2
    exit 1
fi
export CAD_API_TARGET="http://127.0.0.1:${BACKEND_PORT}"
echo "[start] backend API: $CAD_API_TARGET"
echo "$CAD_API_TARGET" > "$ROOT/.vite-api.target"

SHARED="$HOME/.agents/skills/vite-preview-auto/scripts/start-and-open.sh"
if [[ -f "$SHARED" ]]; then
    if [[ ${#OPEN_FLAG[@]} -gt 0 ]]; then
        exec bash "$SHARED" "${OPEN_FLAG[@]}" "$ROOT" "${VITE_PORT:-5173}"
    fi
    exec bash "$SHARED" "$ROOT" "${VITE_PORT:-5173}"
fi

PORT="${VITE_PORT:-5173}"
cd "$ROOT"
if [[ ! -d node_modules ]]; then
    npm install
fi
nohup npm run dev -- --host 127.0.0.1 --port "$PORT" >.vite-dev.log 2>&1 &
echo $! >.vite-dev.pid
URL="http://127.0.0.1:${PORT}"
echo "$URL" >.vite-dev.url
for _ in $(seq 1 60); do
    if curl -s -o /dev/null --connect-timeout 1 "$URL" 2>/dev/null; then
        break
    fi
    sleep 0.5
done
echo "[start] $URL  (API -> $CAD_API_TARGET)"
if [[ ${#OPEN_FLAG[@]} -eq 0 ]] && command -v open >/dev/null 2>&1; then
    open "$URL" || true
fi
