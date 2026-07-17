import os
from pathlib import Path

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from api import parse, projects, replay, upload, visual_audit
from log_hub import broadcaster
from parser.dwg_converter import DwgConverter, find_oda_file_converter
from storage import LOG_DIR, PROJECTS_DIR, UPLOAD_DIR

BASE_DIR = Path(__file__).resolve().parent
FRONTEND_DIR = BASE_DIR.parent / "frontend"
EXPORTS_DIR = Path(os.environ["CAD_EXPORTS_DIR"]).expanduser() if os.environ.get("CAD_EXPORTS_DIR") else BASE_DIR.parent / "exports"

for directory in (UPLOAD_DIR, LOG_DIR, PROJECTS_DIR, EXPORTS_DIR):
    directory.mkdir(parents=True, exist_ok=True)

app = FastAPI(title="CAD 3D Preview Tool")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.middleware("http")
async def no_cache_frontend_assets(request, call_next):
    response = await call_next(request)
    path = request.url.path
    if path == "/" or path.endswith((".html", ".js", ".css")):
        response.headers["Cache-Control"] = "no-store, max-age=0"
        response.headers["Pragma"] = "no-cache"
    return response


@app.websocket("/ws/logs")
async def websocket_logs(ws: WebSocket) -> None:
    await broadcaster.connect(ws)
    try:
        while True:
            await ws.receive_text()
    except WebSocketDisconnect:
        broadcaster.disconnect(ws)


@app.get("/api/health")
async def health() -> dict:
    oda_path = find_oda_file_converter()
    return {
        "ok": True,
        "oda_available": DwgConverter.available(),
        "oda_path": str(oda_path) if oda_path else None,
        "uploads_dir": str(UPLOAD_DIR),
        "projects_dir": str(PROJECTS_DIR),
        "exports_dir": str(EXPORTS_DIR),
        "runtime_root": os.environ.get("CAD_RUNTIME_ROOT") or None,
        "scope_project_id": os.environ.get("CAD_SCOPE_PROJECT_ID") or None,
        "project_package_dir": os.environ.get("CAD_PROJECT_PACKAGE_DIR") or None,
        "project_rules_dir": os.environ.get("CAD_PROJECT_RULES_DIR") or None,
    }


app.include_router(upload.router, prefix="/api")
app.include_router(parse.router, prefix="/api")
app.include_router(projects.router, prefix="/api")
app.include_router(replay.router, prefix="/api")
app.include_router(visual_audit.router, prefix="/api")

app.mount("/exports", StaticFiles(directory=str(EXPORTS_DIR)), name="exports")

if FRONTEND_DIR.exists():
    app.mount("/", StaticFiles(directory=str(FRONTEND_DIR), html=True), name="frontend")
