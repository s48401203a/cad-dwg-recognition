#!/usr/bin/env bash
# 启动 CAD 读取器（自包含，只依赖仓库内被跟踪的文件）。
#
# 用法:
#   ./start.sh                 # 回环地址 + 自动挑端口 + 自动打开浏览器
#   ./start.sh --no-open       # 不打开浏览器
#   ./start.sh --port 8000     # 指定端口
#   ./start.sh --lan           # 局域网模式（自动生成访问令牌，必须显式开启）
#   ./start.sh --vite          # 额外启动 Vite 开发预览（需要 Node.js）
#
# 说明:
# - 页面由 FastAPI 直接提供（原生 JS + Three.js，无构建步骤），因此默认不需要 Node。
# - 不依赖 start-project.command、$HOME/.agents/skills 或其它本机脚本。
# - 首次运行会自动创建 .venv 并安装 requirements.txt。
set -euo pipefail

ROOT="$(cd "$(dirname "$0")" && pwd)"
cd "$ROOT"

OPEN_ARGS=()
SERVER_ARGS=()
USE_VITE=0
for arg in "$@"; do
    case "$arg" in
        --no-open) OPEN_ARGS+=(--no-open) ;;
        --lan) SERVER_ARGS+=(--lan) ;;
        --reload) SERVER_ARGS+=(--reload) ;;
        --vite) USE_VITE=1 ;;
        --port) SERVER_ARGS+=(--port) ;;
        [0-9]*) SERVER_ARGS+=("$arg") ;;
        *) SERVER_ARGS+=("$arg") ;;
    esac
done

PYTHON_BIN="${CAD_PYTHON:-}"
if [[ -z "$PYTHON_BIN" ]]; then
    for candidate in "$ROOT/.venv/bin/python" "$ROOT/.venv-macos/bin/python"; do
        if [[ -x "$candidate" ]]; then PYTHON_BIN="$candidate"; break; fi
    done
fi

if [[ -z "$PYTHON_BIN" ]]; then
    echo "[start] 未找到虚拟环境，正在创建 .venv ..."
    BASE_PYTHON="$(command -v python3 || true)"
    if [[ -z "$BASE_PYTHON" ]]; then
        echo "[start] 缺少 python3，请先安装 Python 3.10+" >&2
        exit 1
    fi
    "$BASE_PYTHON" -m venv "$ROOT/.venv"
    PYTHON_BIN="$ROOT/.venv/bin/python"
    echo "[start] 安装依赖（requirements.txt）..."
    "$PYTHON_BIN" -m pip install --upgrade pip >/dev/null
    "$PYTHON_BIN" -m pip install -r "$ROOT/requirements.txt"
fi

if ! "$PYTHON_BIN" -c "import fastapi, uvicorn, ezdxf" >/dev/null 2>&1; then
    echo "[start] 依赖不完整，正在安装 requirements.txt ..."
    "$PYTHON_BIN" -m pip install -r "$ROOT/requirements.txt"
fi

# 已在运行则直接复用（避免重复起进程、端口漂移）
if STATE_JSON="$("$PYTHON_BIN" "$ROOT/backend/server.py" --status 2>/dev/null)"; then
    URL="$("$PYTHON_BIN" -c 'import json,sys; print(json.loads(sys.argv[1]).get("url",""))' "$STATE_JSON")"
    if [[ -n "$URL" ]]; then
        echo "[start] 后端已在运行: $URL"
        if [[ $USE_VITE -eq 0 ]]; then
            if [[ ${#OPEN_ARGS[@]} -eq 0 ]] && command -v open >/dev/null 2>&1; then open "$URL" || true; fi
            exit 0
        fi
    fi
fi

echo "[start] 启动 FastAPI（原生 JS + Three.js 前端由后端直接提供）..."
if [[ $USE_VITE -eq 1 ]]; then
    "$PYTHON_BIN" "$ROOT/backend/server.py" "${OPEN_ARGS[@]}" "${SERVER_ARGS[@]}" --no-open &
    BACKEND_PID=$!
    # 等待后端就绪并取回端口
    for _ in $(seq 1 60); do
        if STATE_JSON="$("$PYTHON_BIN" "$ROOT/backend/server.py" --status 2>/dev/null)"; then break; fi
        sleep 0.5
    done
    CAD_API_TARGET="$("$PYTHON_BIN" -c 'import json,sys; print(json.loads(sys.argv[1]).get("url","").rstrip("/"))' "$STATE_JSON" 2>/dev/null || true)"
    export CAD_API_TARGET
    echo "[start] backend API: ${CAD_API_TARGET:-unknown}"

    if [[ ! -d "$ROOT/node_modules" ]]; then
        echo "[start] 安装 Vite 依赖（npm install）..."
        (cd "$ROOT" && npm install)
    fi
    VITE_PORT="${VITE_PORT:-5173}"
    echo "$CAD_API_TARGET" > "$ROOT/.vite-api.target"
    nohup npm run dev --prefix "$ROOT" -- --host 127.0.0.1 --port "$VITE_PORT" >"$ROOT/.vite-dev.log" 2>&1 &
    echo $! > "$ROOT/.vite-dev.pid"
    VITE_URL="http://127.0.0.1:${VITE_PORT}"
    echo "$VITE_URL" > "$ROOT/.vite-dev.url"
    for _ in $(seq 1 60); do
        if curl -s -o /dev/null --connect-timeout 1 "$VITE_URL" 2>/dev/null; then break; fi
        sleep 0.5
    done
    echo "[start] $VITE_URL  (API -> $CAD_API_TARGET)"
    if [[ ${#OPEN_ARGS[@]} -eq 0 ]] && command -v open >/dev/null 2>&1; then open "$VITE_URL" || true; fi
    wait "$BACKEND_PID"
else
    exec "$PYTHON_BIN" "$ROOT/backend/server.py" "${OPEN_ARGS[@]}" "${SERVER_ARGS[@]}"
fi
