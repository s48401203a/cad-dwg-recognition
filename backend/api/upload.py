import asyncio
import time
import uuid
from pathlib import Path

import aiofiles
from fastapi import APIRouter, File, HTTPException, UploadFile

from log_hub import emit
from parser.dwg_converter import DwgConverter
from storage import UPLOAD_DIR, now_iso, register_upload

router = APIRouter()


@router.post("/upload")
async def upload_file(file: UploadFile = File(...)) -> dict:
    started = time.perf_counter()
    original_name = Path(file.filename or "drawing").name
    suffix = Path(original_name).suffix.lower()
    if suffix not in {".dwg", ".dxf"}:
        raise HTTPException(status_code=400, detail="仅支持 DWG 或 DXF 文件")

    file_id = uuid.uuid4().hex
    file_dir = UPLOAD_DIR / file_id
    file_dir.mkdir(parents=True, exist_ok=True)
    upload_path = file_dir / original_name

    size = 0
    async with aiofiles.open(upload_path, "wb") as out:
        while chunk := await file.read(1024 * 1024):
            size += len(chunk)
            await out.write(chunk)

    await emit("INFO", f"接收文件 {original_name} ({size / 1024 / 1024:.1f} MB)")

    converted = False
    dxf_path = upload_path
    message = "DXF 已上传，可直接解析"

    if suffix == ".dwg":
        loop = asyncio.get_running_loop()

        def log_from_thread(message: str) -> None:
            loop.call_soon_threadsafe(asyncio.create_task, emit("INFO", message))

        try:
            dxf_path = await asyncio.to_thread(DwgConverter.convert, upload_path, file_dir / "converted", log_from_thread)
            converted = True
            message = "DWG 已转换为 DXF (ACAD2018)"
            await emit("SUCCESS", f"DWG 转换完成，耗时 {time.perf_counter() - started:.1f} 秒")
        except Exception as exc:
            await emit("ERROR", f"DWG 转换失败: {exc}")
            raise HTTPException(status_code=500, detail=str(exc)) from exc
    else:
        await emit("SUCCESS", "DXF 上传完成，等待解析")

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
        "dxf_path": str(dxf_path),
        "message": message,
        "duration_seconds": duration,
    }
