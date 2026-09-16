"""Replay 编排器 HTTP 路由。

提供 4 个端点：
- POST /api/replay/start    异步触发编排（subprocess 启 python -m orchestrator.replay_runner）
- GET  /api/replay/status   查询当前进度（轮询 metrics.json）
- GET  /api/replay/report   返回最新 HTML 报告
- GET  /api/replay/metrics  返回结构化指标

可用性：replay 依赖 `orchestrator` 包与 Playwright。`orchestrator/` **不在公开仓库内**，
因此干净检出下该能力默认不可用：所有端点返回 503 + 明确原因，不会给出「看起来能用、
点下去必然失败」的入口。若本地部署了 orchestrator，可通过 `CAD_ENABLE_REPLAY=1` 打开，
或把 `CAD_REPLAY_RUNNER` 指向自定义 runner 模块。

设计上不在 FastAPI 进程内直接 import & 跑 Playwright，避免 asyncio 嵌套与浏览器进程管理复杂度。
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from fastapi import APIRouter, BackgroundTasks, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel

from capabilities import CapabilityUnavailable, capability
from log_hub import broadcaster
from path_policy import PathPolicyError, validate_drawing_id, validate_project_id

router = APIRouter()

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent  # CAD dwg识别/
_replay_output = os.environ.get("CAD_REPLAY_OUTPUT_DIR")
ORCHESTRATOR_OUT = Path(_replay_output).expanduser() if _replay_output else PROJECT_ROOT / "output" / "replay"
METRICS_PATH = ORCHESTRATOR_OUT / "metrics.json"
REPORT_PATH = ORCHESTRATOR_OUT / "report.html"
REPLAY_CONFIG_PATH = PROJECT_ROOT / "orchestrator" / "replay_config.yaml"
REPORT_TAIL_LINES = 400


# 进程状态（in-memory，多 worker 部署时需换成持久化）
_state: dict[str, Any] = {
    "running": False,
    "job_id": None,
    "process": None,
    "project_id": None,
    "drawing_id": None,
    "started_at": None,
    "finished_at": None,
    "exit_code": None,
    "log_tail": [],
}


class ReplayStartBody(BaseModel):
    project_id: str
    drawing_id: str
    dry_run: bool = False
    headless: bool = True
    backend_url: str | None = None


def replay_runner_module() -> str:
    return os.environ.get("CAD_REPLAY_RUNNER") or "orchestrator.replay_runner"


def require_replay() -> None:
    info = capability("replay")
    if not info.get("available"):
        raise HTTPException(
            status_code=503,
            detail=f"逐图层 replay 不可用：{info.get('reason') or '未安装 orchestrator / Playwright'}",
            headers={"X-CAD-Capability": "replay"},
        )


def _job_id_now() -> str:
    return time.strftime("replay_%Y%m%d_%H%M%S")


def _layer_total() -> int:
    try:
        import yaml

        cfg = yaml.safe_load(REPLAY_CONFIG_PATH.read_text(encoding="utf-8")) or {}
        return len(cfg.get("layer_order") or []) or 17
    except Exception:
        return 17


def _validate_backend_url(value: str | None) -> str | None:
    """只允许回环地址，避免把本机请求引到任意主机（SSRF）。"""
    if not value:
        return None
    parsed = urlsplit(value)
    host = (parsed.hostname or "").lower()
    if parsed.scheme not in {"http", "https"} or host not in {"127.0.0.1", "localhost", "::1"}:
        raise HTTPException(status_code=400, detail="backend_url 只允许指向本机回环地址")
    return value.rstrip("/")


def _start_subprocess(
    project_id: str,
    drawing_id: str,
    dry_run: bool,
    headless: bool,
    backend_url: str | None = None,
) -> subprocess.Popen:
    """启 python -m <runner>。"""
    cmd = [
        sys.executable, "-m", replay_runner_module(),
        "--project", project_id,
        "--drawing", drawing_id,
    ]
    if dry_run:
        cmd.append("--dry-run")
    if not headless:
        cmd.append("--no-headless")
    if backend_url:
        cmd.extend(["--backend-url", backend_url])

    log_path = ORCHESTRATOR_OUT / "runner.log"
    log_path.parent.mkdir(parents=True, exist_ok=True)
    log_fp = open(log_path, "w", encoding="utf-8")

    proc = subprocess.Popen(
        cmd,
        cwd=str(PROJECT_ROOT),
        stdout=log_fp, stderr=subprocess.STDOUT,
        env={**os.environ, "PYTHONIOENCODING": "utf-8"},
    )
    return proc


async def _watch_process_finish() -> None:
    """后台轮询子进程退出码。"""
    if not _state["process"]:
        return
    proc: subprocess.Popen = _state["process"]
    while proc.poll() is None:
        await __import__("asyncio").sleep(2)
    _state["running"] = False
    _state["finished_at"] = time.time()
    _state["exit_code"] = proc.returncode
    try:
        await broadcaster.broadcast({
            "level": "SUCCESS" if proc.returncode == 0 else "ERROR",
            "message": f"replay 任务 {_state['job_id']} 退出 code={proc.returncode}",
        })
    except Exception:
        pass


@router.get("/replay/capability")
async def replay_capability() -> dict[str, Any]:
    """前端用它决定是否显示 replay 入口。"""
    info = capability("replay")
    return {"capability": "replay", **info}


@router.post("/replay/start")
async def start_replay(body: ReplayStartBody, background_tasks: BackgroundTasks) -> dict[str, Any]:
    require_replay()
    if _state["running"]:
        raise HTTPException(409, f"已有 replay 在运行: job_id={_state['job_id']}")
    try:
        project_id = validate_project_id(body.project_id)
        drawing_id = validate_drawing_id(body.drawing_id)
    except PathPolicyError as exc:
        raise HTTPException(400, str(exc)) from exc
    backend_url = _validate_backend_url(body.backend_url)

    job_id = _job_id_now()
    try:
        proc = _start_subprocess(project_id, drawing_id, body.dry_run, body.headless, backend_url)
    except Exception as e:
        raise HTTPException(500, f"启动子进程失败: {e}")

    _state.update({
        "running": True,
        "job_id": job_id,
        "process": proc,
        "project_id": project_id,
        "drawing_id": drawing_id,
        "started_at": time.time(),
        "finished_at": None,
        "exit_code": None,
    })
    background_tasks.add_task(_watch_process_finish)
    await broadcaster.broadcast({
        "level": "INFO",
        "message": f"replay 任务已启动: job_id={job_id}, project={project_id}, drawing={drawing_id}",
    })
    return {
        "started": True,
        "job_id": job_id,
        "project_id": project_id,
        "drawing_id": drawing_id,
        "dry_run": body.dry_run,
    }


@router.get("/replay/status")
async def replay_status() -> dict[str, Any]:
    """轻量状态：是否在跑 + 进度（从 metrics.json 计算）。"""
    info = capability("replay")
    progress = None
    if METRICS_PATH.exists():
        try:
            metrics = json.loads(METRICS_PATH.read_text(encoding="utf-8"))
            done = len(metrics.get("results", []))
            n_pass = sum(1 for r in metrics["results"] if r.get("overall_pass"))
            progress = {
                "done": done,
                "total": _layer_total(),
                "n_pass": n_pass,
                "duration_s": metrics.get("duration_s"),
                "project_name": metrics.get("project_name"),
            }
        except Exception:
            pass

    return {
        "available": bool(info.get("available")),
        "unavailable_reason": None if info.get("available") else info.get("reason"),
        "running": _state["running"],
        "job_id": _state["job_id"],
        "project_id": _state["project_id"],
        "drawing_id": _state["drawing_id"],
        "started_at": _state["started_at"],
        "finished_at": _state["finished_at"],
        "exit_code": _state["exit_code"],
        "progress": progress,
        "report_available": REPORT_PATH.exists(),
    }


@router.get("/replay/report")
async def replay_report():
    require_replay()
    if not REPORT_PATH.exists():
        raise HTTPException(404, "报告还未生成。先调用 /api/replay/start 跑一次。")
    return FileResponse(str(REPORT_PATH), media_type="text/html")


@router.get("/replay/metrics")
async def replay_metrics() -> dict[str, Any]:
    if not METRICS_PATH.exists():
        raise HTTPException(404, "metrics.json 还没生成")
    try:
        return json.loads(METRICS_PATH.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise HTTPException(500, f"metrics.json 损坏: {exc}") from exc


@router.get("/replay/log")
async def replay_log(tail: int = 200) -> dict[str, Any]:
    """读 runner.log 末尾若干行，用于 Web 端查看实时日志。"""
    log_path = ORCHESTRATOR_OUT / "runner.log"
    if not log_path.exists():
        return {"lines": []}
    try:
        lines = log_path.read_text(encoding="utf-8", errors="replace").splitlines()
        return {"lines": lines[-max(1, min(tail, REPORT_TAIL_LINES)):]}
    except Exception as e:
        raise HTTPException(500, f"读日志失败: {e}")
