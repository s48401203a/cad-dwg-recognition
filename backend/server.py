"""服务器启动入口与运行期状态。

目标：**只依赖仓库内被跟踪的文件**即可启动，不再依赖 `start-project.command`
（被 .gitignore 排除）或个人 `$HOME/.agents/skills` 下的脚本。

用法：
    python backend/server.py                 # 回环地址 + 自动挑选空闲端口
    python backend/server.py --port 8000
    python backend/server.py --lan           # 局域网模式（自动生成访问令牌）
    python backend/server.py --no-open       # 不自动打开浏览器

运行期状态写在 `.cad-runtime/server.json`（git 忽略），供 `stop.sh` / `start.sh` 与
前端读取。该文件包含端口、PID、访问令牌与运行时根目录。
"""

from __future__ import annotations

import argparse
import json
import os
import socket
import sys
import time
import webbrowser
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
ROOT_DIR = BASE_DIR.parent
RUNTIME_DIRNAME = ".cad-runtime"
DEFAULT_PORT_RANGE = (8000, 8020)


def runtime_dir() -> Path:
    override = os.environ.get("CAD_RUNTIME_STATE_DIR")
    return Path(override).expanduser() if override else ROOT_DIR / RUNTIME_DIRNAME


def state_path() -> Path:
    return runtime_dir() / "server.json"


def port_is_free(host: str, port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            sock.bind((host, port))
        except OSError:
            return False
    return True


def pick_port(host: str, preferred: int | None = None, port_range: tuple[int, int] = DEFAULT_PORT_RANGE) -> int:
    if preferred:
        if port_is_free(host, preferred):
            return preferred
        raise SystemExit(f"[server] 端口 {preferred} 已被占用")
    for port in range(port_range[0], port_range[1] + 1):
        if port_is_free(host, port):
            return port
    raise SystemExit(f"[server] {port_range[0]}-{port_range[1]} 内没有空闲端口")


def ping_health(host: str, port: int, timeout: float = 0.6) -> bool:
    import urllib.error
    import urllib.request

    probe_host = "127.0.0.1" if host in {"0.0.0.0", "::"} else host
    url = f"http://{probe_host}:{port}/api/health"
    try:
        with urllib.request.urlopen(url, timeout=timeout) as response:  # noqa: S310 (本机回环探活)
            return response.status == 200
    except (urllib.error.URLError, OSError):
        return False


def read_state() -> dict | None:
    path = state_path()
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None


def write_state(payload: dict) -> Path:
    path = state_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(tmp, path)
    return path


def clear_state() -> None:
    path = state_path()
    try:
        path.unlink()
    except OSError:
        pass


def running_state() -> dict | None:
    """返回仍然存活的运行实例状态（用于「已在运行则复用」）。"""
    state = read_state()
    if not state:
        return None
    host = str(state.get("host") or "127.0.0.1")
    port = state.get("port")
    if not port:
        return None
    if ping_health(host, int(port)):
        return state
    return None


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="CAD 3D preview server")
    parser.add_argument("--host", default=os.environ.get("CAD_HOST") or "127.0.0.1")
    parser.add_argument("--port", type=int, default=int(os.environ["CAD_PORT"]) if os.environ.get("CAD_PORT") else None)
    parser.add_argument("--lan", action="store_true", help="绑定局域网地址（必须带访问令牌）")
    parser.add_argument("--token", default=None, help="显式指定访问令牌")
    parser.add_argument("--no-open", action="store_true", help="不自动打开浏览器")
    parser.add_argument("--reload", action="store_true", help="开发模式热重载")
    parser.add_argument("--state-only", action="store_true", help="只写运行期状态并退出（供脚本查询）")
    parser.add_argument("--status", action="store_true", help="打印当前运行实例状态后退出")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)

    if args.status:
        state = running_state()
        if state:
            print(json.dumps(state, ensure_ascii=False))
            return 0
        print(json.dumps({"running": False}, ensure_ascii=False))
        return 1

    host = args.host
    if args.lan:
        os.environ["CAD_LAN_MODE"] = "1"
        host = host if host != "127.0.0.1" else "0.0.0.0"
    os.environ["CAD_HOST"] = host

    existing = running_state()
    if existing and not args.state_only:
        print(f"[server] 已有实例在运行: http://{existing.get('host')}:{existing.get('port')}")
        return 0

    from security import generate_token, load_access_policy, set_policy

    token = args.token or (os.environ.get("CAD_ACCESS_TOKEN") or "").strip() or None
    if args.lan and not token:
        token = generate_token()
        print(f"[security] 局域网模式：已生成访问令牌 {token}")
    if token:
        os.environ["CAD_ACCESS_TOKEN"] = token
    set_policy(None)
    try:
        policy = load_access_policy()
    except Exception as exc:  # AccessDenied
        print(f"[security] {exc}")
        return 2

    port = pick_port(host, args.port)
    url_host = "127.0.0.1" if host in {"0.0.0.0", "::"} else host
    access_url = f"http://{url_host}:{port}/"
    if token:
        access_url = f"{access_url}?token={token}"

    state = {
        "pid": os.getpid(),
        "host": host,
        "port": port,
        "url": access_url,
        "token": token,
        "lan": bool(policy.lan_enabled),
        "runtime_root": os.environ.get("CAD_RUNTIME_ROOT"),
        "python": sys.executable,
        "started_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
    }
    path = write_state(state)
    print(f"[server] {access_url}")
    print(f"[server] state: {path}")
    if args.state_only:
        return 0

    if not args.no_open:
        try:
            webbrowser.open(access_url)
        except Exception:
            pass

    try:
        import uvicorn
    except ImportError:
        print("[server] 缺少 uvicorn，请先安装依赖：pip install -r requirements.txt")
        return 3

    try:
        uvicorn.run(
            "main:app",
            host=host,
            port=port,
            reload=args.reload,
            app_dir=str(BASE_DIR),
            log_level=os.environ.get("CAD_LOG_LEVEL") or "info",
        )
    finally:
        current = read_state()
        if current and current.get("pid") == os.getpid():
            clear_state()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
