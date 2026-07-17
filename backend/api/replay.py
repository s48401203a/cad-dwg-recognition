# -*- coding: utf-8 -*-
"""Replay 编排器 HTTP 路由。

提供 3 个端点：
- POST /api/replay/start    异步触发编排（subprocess 启 python -m orchestrator.replay_runner）
- GET  /api/replay/status   查询当前进度（轮询 metrics.json）
- GET  /api/replay/report   返回最新 HTML 报告

设计上不在 FastAPI 进程内直接 import & 跑 Playwright，避免 asyncio 嵌套与浏览器进程管理复杂度。
"""
from __future__ import annotations

import json
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

from fastapi import APIRouter, BackgroundTasks, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel

from log_hub import broadcaster

router = APIRouter()

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent  # CAD dwg识别/
ORCHESTRATOR_OUT = PROJECT_ROOT / "output" / "replay"
METRICS_PATH = ORCHESTRATOR_OUT / "metrics.json"
REPORT_PATH = ORCHESTRATOR_OUT / "report.html"
REPLAY_CONFIG_PATH = PROJECT_ROOT / "orchestrator" / "replay_config.yaml"


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


def _job_id_now() -> str:
    return time.strftime("replay_%Y%m%d_%H%M%S")


def _layer_total() -> int:
    try:
        import yaml

        cfg = yaml.safe_load(REPLAY_CONFIG_PATH.read_text(encoding="utf-8")) or {}
        return len(cfg.get("layer_order") or []) or 17
    except Exception:
        return 17


def _start_subprocess(
    project_id: str,
    drawing_id: str,
    dry_run: bool,
    headless: bool,
    backend_url: str | None = None,
) -> subprocess.Popen:
    """启 python -m orchestrator.replay_runner。"""
    cmd = [
        sys.executable, "-m", "orchestrator.replay_runner",
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
        env={**__import__("os").environ, "PYTHONIOENCODING": "utf-8"},
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


@router.post("/replay/start")
async def start_replay(body: ReplayStartBody, background_tasks: BackgroundTasks) -> dict[str, Any]:
    if _state["running"]:
        raise HTTPException(409, f"已有 replay 在运行: job_id={_state['job_id']}")

    job_id = _job_id_now()
    try:
        proc = _start_subprocess(body.project_id, body.drawing_id, body.dry_run, body.headless, body.backend_url)
    except Exception as e:
        raise HTTPException(500, f"启动子进程失败: {e}")

    _state.update({
        "running": True,
        "job_id": job_id,
        "process": proc,
        "project_id": body.project_id,
        "drawing_id": body.drawing_id,
        "started_at": time.time(),
        "finished_at": None,
        "exit_code": None,
    })
    background_tasks.add_task(_watch_process_finish)
    await broadcaster.broadcast({
        "level": "INFO",
        "message": f"replay 任务已启动: job_id={job_id}, project={body.project_id}, drawing={body.drawing_id}",
    })
    return {
        "started": True,
        "job_id": job_id,
        "project_id": body.project_id,
        "drawing_id": body.drawing_id,
        "dry_run": body.dry_run,
    }


@router.get("/replay/status")
async def replay_status() -> dict[str, Any]:
    """轻量状态：是否在跑 + 进度（从 metrics.json 计算）。"""
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
    if not REPORT_PATH.exists():
        raise HTTPException(404, "报告还未生成。先调用 /api/replay/start 跑一次。")
    return FileResponse(str(REPORT_PATH), media_type="text/html")


@router.get("/replay/metrics")
async def replay_metrics() -> dict[str, Any]:
    if not METRICS_PATH.exists():
        raise HTTPException(404, "metrics.json 还没生成")
    return json.loads(METRICS_PATH.read_text(encoding="utf-8"))


@router.get("/replay/log")
async def replay_log(tail: int = 200) -> dict[str, Any]:
    """读 runner.log 末尾若干行，用于 Web 端查看实时日志。"""
    log_path = ORCHESTRATOR_OUT / "runner.log"
    if not log_path.exists():
        return {"lines": []}
    try:
        lines = log_path.read_text(encoding="utf-8", errors="replace").splitlines()
        return {"lines": lines[-tail:]}
    except Exception as e:
        raise HTTPException(500, f"读日志失败: {e}")
