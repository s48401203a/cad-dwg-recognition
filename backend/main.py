"""FastAPI 应用装配：路由、访问控制中间件、静态资源与 WebSocket。

安全默认值：
- 默认只绑定/服务回环地址；请求的 `Host` 必须是回环地址或显式配置的主机。
- 浏览器来源必须是同源或显式配置的开发来源（`CAD_DEV_ORIGINS`）。
- 配置了访问令牌时，写操作与管理接口需要令牌；只读预览接口保持开放。
- `/exports` 只挂载导出根目录，不做目录穿越；未启用任何能力时也不会暴露本地路径。

启动入口：`python backend/main.py [--host H] [--port P] [--lan]`，
或用仓库根目录的 `start.sh` / `start-project.ps1`（自动挑选空闲端口）。
"""

from __future__ import annotations

import asyncio
import os
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from api import parse, projects, replay, upload, visual_audit
from log_hub import broadcaster
from log_retention import enforce_log_budget, log_retention_loop
from parser.dwg_converter import DwgConverter, find_oda_file_converter
from security import AccessDenied, check_request, check_websocket, current_policy, generate_token
from storage import LOG_DIR, PROJECTS_DIR, UPLOAD_DIR

BASE_DIR = Path(__file__).resolve().parent
FRONTEND_DIR = BASE_DIR.parent / "frontend"
EXPORTS_DIR = Path(os.environ["CAD_EXPORTS_DIR"]).expanduser() if os.environ.get("CAD_EXPORTS_DIR") else BASE_DIR.parent / "exports"

for directory in (UPLOAD_DIR, LOG_DIR, PROJECTS_DIR, EXPORTS_DIR):
    directory.mkdir(parents=True, exist_ok=True)


@asynccontextmanager
async def lifespan(_app: FastAPI):
    enforce_log_budget()
    retention_task = asyncio.create_task(log_retention_loop())
    try:
        yield
    finally:
        retention_task.cancel()
        try:
            await retention_task
        except asyncio.CancelledError:
            pass


app = FastAPI(title="CAD 3D Preview Tool", lifespan=lifespan)


def _configure_cors(app_instance: FastAPI) -> None:
    """CORS 只允许同源与显式配置的开发来源，不再对所有 Origin 放开。

    默认：本机页面（同源）+ Vite 开发代理端口。生产/局域网场景需要
    `CAD_DEV_ORIGINS` 显式列出允许的来源。
    """
    policy = current_policy()
    origins = sorted(policy.dev_origins)
    if not origins:
        return
    app_instance.add_middleware(
        CORSMiddleware,
        allow_origins=origins,
        allow_credentials=True,
        allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
        allow_headers=["Authorization", "Content-Type", "X-CAD-Token"],
    )


_configure_cors(app)


@app.middleware("http")
async def enforce_access_policy(request: Request, call_next):
    """统一访问控制：Host / Origin / 令牌。"""
    try:
        check_request(
            method=request.method,
            path=request.url.path,
            headers=request.headers,
            query_token=request.query_params.get("token"),
            cookies=request.cookies,
        )
    except AccessDenied as exc:
        return JSONResponse(
            status_code=exc.status_code,
            content={"detail": str(exc), "code": exc.code},
        )
    return await call_next(request)


@app.middleware("http")
async def no_cache_frontend_assets(request: Request, call_next):
    response = await call_next(request)
    path = request.url.path
    if path == "/" or path.endswith((".html", ".js", ".css")):
        response.headers["Cache-Control"] = "no-store, max-age=0"
        response.headers["Pragma"] = "no-cache"
    return response


@app.websocket("/ws/logs")
async def websocket_logs(ws: WebSocket) -> None:
    try:
        check_websocket(
            path="/ws/logs",
            headers=ws.headers,
            query_token=ws.query_params.get("token"),
            cookies=ws.cookies,
        )
    except AccessDenied as exc:
        await ws.close(code=1008, reason=str(exc)[:120])
        return
    await broadcaster.connect(ws)
    try:
        while True:
            await ws.receive_text()
    except WebSocketDisconnect:
        broadcaster.disconnect(ws)


@app.get("/api/health")
async def health() -> dict:
    oda_path = find_oda_file_converter()
    from capabilities import capability_report

    policy = current_policy()
    return {
        "ok": True,
        "oda_available": DwgConverter.available(),
        "oda_path": str(oda_path) if oda_path else None,
        "runtime_root": os.environ.get("CAD_RUNTIME_ROOT") or None,
        "scope_project_id": os.environ.get("CAD_SCOPE_PROJECT_ID") or None,
        "access": policy.describe(),
        "capabilities": capability_report()["capabilities"],
    }


app.include_router(upload.router, prefix="/api")
app.include_router(parse.router, prefix="/api")
app.include_router(projects.router, prefix="/api")
app.include_router(replay.router, prefix="/api")
app.include_router(visual_audit.router, prefix="/api")

app.mount("/exports", StaticFiles(directory=str(EXPORTS_DIR)), name="exports")

if FRONTEND_DIR.exists():
    app.mount("/", StaticFiles(directory=str(FRONTEND_DIR), html=True), name="frontend")


def main(argv: list[str] | None = None) -> int:
    """CLI 启动入口。

    在导入应用模块之前先确定监听地址与令牌，避免以「无鉴权的非回环绑定」启动。
    """
    import argparse

    import uvicorn

    parser = argparse.ArgumentParser(description="CAD 3D preview server")
    parser.add_argument("--host", default=os.environ.get("CAD_HOST") or "127.0.0.1")
    parser.add_argument("--port", type=int, default=int(os.environ.get("CAD_PORT") or 8000))
    parser.add_argument("--lan", action="store_true", help="绑定局域网地址（必须带访问令牌）")
    parser.add_argument("--token", default=None, help="显式指定访问令牌")
    parser.add_argument("--reload", action="store_true")
    args = parser.parse_args(argv)

    os.environ["CAD_HOST"] = args.host
    if args.lan:
        os.environ["CAD_LAN_MODE"] = "1"
        os.environ["CAD_HOST"] = args.host if args.host != "127.0.0.1" else "0.0.0.0"
    if args.token:
        os.environ["CAD_ACCESS_TOKEN"] = args.token

    from security import load_access_policy, set_policy

    set_policy(None)
    lan_mode = os.environ.get("CAD_LAN_MODE") in {"1", "true", "yes", "on"}
    if lan_mode and not (os.environ.get("CAD_ACCESS_TOKEN") or "").strip():
        token = generate_token()
        os.environ["CAD_ACCESS_TOKEN"] = token
        print(f"[security] 局域网模式已启用，已生成访问令牌: {token}")
        print(f"[security] 浏览器打开 http://<本机IP>:{args.port}/?token={token}")
    set_policy(None)
    try:
        policy = load_access_policy()
    except AccessDenied as exc:
        print(f"[security] {exc}")
        return 2
    if policy.token_required and not policy.token:
        print("[security] 已要求访问令牌但未配置 CAD_ACCESS_TOKEN，拒绝启动")
        return 2

    uvicorn.run(
        "main:app",
        host=policy.host,
        port=args.port,
        reload=args.reload,
        app_dir=str(BASE_DIR),
        log_level=os.environ.get("CAD_LOG_LEVEL") or "info",
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
