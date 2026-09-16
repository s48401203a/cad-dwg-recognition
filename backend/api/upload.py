"""上传入口。

资源边界：
- 上传大小上限可配置（`CAD_MAX_UPLOAD_MB`，默认 512 MB），流式写入超过上限立即中止。
- 失败清理：任何阶段异常都会删除本次上传的临时目录，不在磁盘上留下半截文件。
- 只接受 DWG/DXF 扩展名，文件名经过收敛，杜绝路径穿越。
- 转换（DWG->DXF）是可选能力：缺少 ODA 时 DXF 上传照常可用，DWG 会明确报错。
"""

from __future__ import annotations

import asyncio
import os
import shutil
import time
import uuid
from pathlib import Path

import aiofiles
from fastapi import APIRouter, File, HTTPException, UploadFile

from log_hub import emit
from parser.dwg_converter import DwgConverter
from path_policy import sanitize_filename
from storage import UPLOAD_DIR, now_iso, register_upload

router = APIRouter()

DEFAULT_MAX_UPLOAD_MB = 512
CHUNK_SIZE = 1024 * 1024


def max_upload_bytes() -> int:
    raw = os.environ.get("CAD_MAX_UPLOAD_MB")
    try:
        megabytes = float(raw) if raw else DEFAULT_MAX_UPLOAD_MB
    except ValueError:
        megabytes = DEFAULT_MAX_UPLOAD_MB
    if megabytes <= 0:
        megabytes = DEFAULT_MAX_UPLOAD_MB
    return int(megabytes * 1024 * 1024)


@router.post("/upload")
async def upload_file(file: UploadFile = File(...)) -> dict:
    started = time.perf_counter()
    original_name = sanitize_filename(file.filename, fallback="drawing")
    suffix = Path(original_name).suffix.lower()
    if suffix not in {".dwg", ".dxf"}:
        raise HTTPException(status_code=400, detail="仅支持 DWG 或 DXF 文件")

    limit = max_upload_bytes()
    file_id = uuid.uuid4().hex
    file_dir = UPLOAD_DIR / file_id
    file_dir.mkdir(parents=True, exist_ok=True)
    upload_path = file_dir / original_name

    size = 0
    try:
        async with aiofiles.open(upload_path, "wb") as out:
            while chunk := await file.read(CHUNK_SIZE):
                size += len(chunk)
                if size > limit:
                    raise HTTPException(
                        status_code=413,
                        detail=f"文件超过上传上限 {limit // (1024 * 1024)} MB",
                    )
                await out.write(chunk)
        if size == 0:
            raise HTTPException(status_code=400, detail="上传文件为空")

        await emit("INFO", f"接收文件 {original_name} ({size / 1024 / 1024:.1f} MB)")

        converted = False
        dxf_path = upload_path
        message = "DXF 已上传，可直接解析"

        if suffix == ".dwg":
            if not DwgConverter.available():
                raise HTTPException(
                    status_code=503,
                    detail="未检测到 ODA File Converter，无法转换 DWG；DXF 图纸不受影响，可直接上传 DXF",
                )
            loop = asyncio.get_running_loop()

            def log_from_thread(message: str) -> None:
                loop.call_soon_threadsafe(asyncio.create_task, emit("INFO", message))

            try:
                dxf_path = await asyncio.to_thread(
                    DwgConverter.convert, upload_path, file_dir / "converted", log_from_thread
                )
            except Exception as exc:
                await emit("ERROR", f"DWG 转换失败: {exc}")
                raise HTTPException(status_code=500, detail=str(exc)) from exc
            converted = True
            message = "DWG 已转换为 DXF (ACAD2018)"
            await emit("SUCCESS", f"DWG 转换完成，耗时 {time.perf_counter() - started:.1f} 秒")
        else:
            await emit("SUCCESS", "DXF 上传完成，等待解析")
    except BaseException:
        # 失败清理：不留下半截文件或空目录
        shutil.rmtree(file_dir, ignore_errors=True)
        raise

    duration = round(time.perf_counter() - started, 2)
    record = {
        "file_id": file_id,
        "original_name": original_name,
        "format": suffix.lstrip("."),
        "uploaded_path": str(upload_path),
        "converted": converted,
        "dxf_path": str(dxf_path),
        "uploaded_at": now_iso(),
        "size_bytes": size,
    }
    register_upload(file_id, record)
    return {
        "file_id": file_id,
        "original_name": original_name,
        "format": suffix.lstrip("."),
        "converted": converted,
        "dxf_ready": True,
        "message": message,
        "duration_seconds": duration,
        "size_bytes": size,
        "max_upload_bytes": limit,
    }
