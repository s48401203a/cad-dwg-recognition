#!/usr/bin/env bash
# 停止本项目 Vite 预览；默认同时停止本项目 FastAPI。
# 用法:
#   ./stop.sh
#   ./stop.sh --vite-only
set -euo pipefail

ROOT="$(cd "$(dirname "$0")" && pwd)"
STOP_BACKEND=1
for a in "$@"; do
    case "$a" in
        --vite-only) STOP_BACKEND=0 ;;
    esac
done

SHARED="$HOME/.agents/skills/vite-preview-auto/scripts/stop-dev.sh"
if [[ -f "$SHARED" ]]; then
    bash "$SHARED" "$ROOT" "${VITE_PORT:-5173}" || true
else
    if [[ -f "$ROOT/.vite-dev.pid" ]]; then
        pid="$(cat "$ROOT/.vite-dev.pid" 2>/dev/null || true)"
        [[ -n "$pid" ]] && kill "$pid" 2>/dev/null || true
        rm -f "$ROOT/.vite-dev.pid"
    fi
    PORT="${VITE_PORT:-5173}"
    if command -v lsof >/dev/null 2>&1; then
        lsof -tiTCP:"$PORT" -sTCP:LISTEN 2>/dev/null | xargs kill 2>/dev/null || true
    fi
    rm -f "$ROOT/.vite-dev.url"
    echo "[stop] vite done"
fi

rm -f "$ROOT/.vite-api.target"

if [[ "$STOP_BACKEND" -eq 1 && -x "$ROOT/stop-project.command" ]]; then
    echo "[stop] stopping FastAPI backend..."
    "$ROOT/stop-project.command" || true
fi
