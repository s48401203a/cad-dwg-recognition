#!/usr/bin/env bash
# 停止 CAD 读取器（自包含）。
#
# 用法:
#   ./stop.sh              # 停止后端；若曾用 --vite 启动，也停止 Vite
#   ./stop.sh --vite-only  # 只停 Vite
#   ./stop.sh --force      # 状态文件缺失时按端口范围兜底查找
set -euo pipefail

ROOT="$(cd "$(dirname "$0")" && pwd)"
cd "$ROOT"

STOP_BACKEND=1
FORCE=0
for arg in "$@"; do
    case "$arg" in
        --vite-only) STOP_BACKEND=0 ;;
        --force) FORCE=1 ;;
    esac
done

stop_vite() {
    if [[ -f "$ROOT/.vite-dev.pid" ]]; then
        pid="$(cat "$ROOT/.vite-dev.pid" 2>/dev/null || true)"
        if [[ -n "$pid" ]]; then kill "$pid" 2>/dev/null || true; fi
        rm -f "$ROOT/.vite-dev.pid"
    fi
    VITE_PORT="${VITE_PORT:-5173}"
    if command -v lsof >/dev/null 2>&1; then
        lsof -tiTCP:"$VITE_PORT" -sTCP:LISTEN 2>/dev/null | xargs -r kill 2>/dev/null || true
    fi
    rm -f "$ROOT/.vite-dev.url" "$ROOT/.vite-api.target"
    echo "[stop] vite 已停止"
}

if [[ "$STOP_BACKEND" -eq 0 ]]; then
    stop_vite
    exit 0
fi

PYTHON_BIN="${CAD_PYTHON:-}"
if [[ -z "$PYTHON_BIN" ]]; then
    for candidate in "$ROOT/.venv/bin/python" "$ROOT/.venv-macos/bin/python" "$(command -v python3 || true)"; do
        if [[ -n "$candidate" && -x "$candidate" ]]; then PYTHON_BIN="$candidate"; break; fi
    done
fi

STATE_FILE="$ROOT/.cad-runtime/server.json"
STOPPED=0

if [[ -f "$STATE_FILE" && -n "$PYTHON_BIN" ]]; then
    mapfile -t STATE < <("$PYTHON_BIN" - "$STATE_FILE" <<'PY'
import json, sys
try:
    data = json.load(open(sys.argv[1], encoding="utf-8"))
except Exception:
    raise SystemExit(0)
print(data.get("pid") or "")
print(data.get("port") or "")
print(data.get("host") or "")
PY
)
    PID="${STATE[0]:-}"
    PORT="${STATE[1]:-}"
    if [[ -n "$PID" ]]; then
        if kill "$PID" 2>/dev/null; then
            echo "[stop] 已停止后端 pid=$PID"
            STOPPED=1
        fi
    fi
    if [[ "$STOPPED" -eq 0 && -n "$PORT" && "$FORCE" -eq 1 ]] && command -v lsof >/dev/null 2>&1; then
        lsof -tiTCP:"$PORT" -sTCP:LISTEN 2>/dev/null | xargs -r kill 2>/dev/null || true
        echo "[stop] 已按端口停止后端 port=$PORT"
        STOPPED=1
    fi
fi

if [[ "$STOPPED" -eq 0 ]]; then
    if [[ "$FORCE" -eq 1 ]] && command -v lsof >/dev/null 2>&1; then
        for port in $(seq 8000 8020); do
            pids="$(lsof -tiTCP:"$port" -sTCP:LISTEN 2>/dev/null || true)"
            if [[ -n "$pids" ]]; then
                echo "$pids" | xargs -r kill 2>/dev/null || true
                echo "[stop] 已按端口范围停止 pid(s)=$pids port=$port"
                STOPPED=1
            fi
        done
    fi
fi

if [[ "$STOPPED" -eq 0 ]]; then
    echo "[stop] 未发现正在运行的后端实例（可加 --force 按 8000-8020 端口兜底）"
fi

rm -f "$STATE_FILE"
stop_vite
