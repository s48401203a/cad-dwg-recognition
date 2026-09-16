"""解析入口：DXF -> semantic.json。

本模块负责：
- 把上传记录里的 DXF 复制进项目受管目录（来源文件与转换文件分开保存）。
- 调用 `DxfReader` 读取（含单位解析与显式单位覆盖）。
- 调用规则引擎生成语义模型。
- 把 semantic.json 写到服务端规范位置 `<项目存储>/drawings/<drawing_id>/semantic.json`。
- 限制同时进行的解析与 DWG 转换数量，避免内存/CPU 被单个请求打满。

客户端不参与任何路径决定：`file_id` 与 `project_id` 都由服务端查表解析。
"""

from __future__ import annotations

import asyncio
import inspect
import os
import shutil
import uuid
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from api.projects import assert_project_allowed, create_project_meta, load_project_or_404, scoped_project_id, save_project_or_409
from log_hub import emit
from parser.dxf_reader import DxfReader
from parser.dxf_units import normalize_unit_selection
from path_policy import PathPolicyError, is_safe_id, resolve_within_roots
from semantic.rule_engine import RuleEngine
from storage import (
    RevisionConflict,
    allowed_roots_for_meta,
    drawing_semantic_path,
    get_upload,
    is_project_archived,
    load_project,
    now_iso,
    save_project,
    update_upload,
    write_json,
)

router = APIRouter()

#: 解析并发上限。规则引擎是 CPU 密集的纯 Python，超过 CPU 核数不会更快，只会更慢。
_PARSE_CONCURRENCY = max(1, int(os.environ.get("CAD_PARSE_CONCURRENCY") or max(1, (os.cpu_count() or 2) // 2)))
_parse_semaphore: asyncio.Semaphore | None = None
_semaphore_guard = asyncio.Lock()


async def _parse_slot() -> asyncio.Semaphore:
    global _parse_semaphore
    async with _semaphore_guard:
        if _parse_semaphore is None:
            _parse_semaphore = asyncio.Semaphore(_PARSE_CONCURRENCY)
        return _parse_semaphore


class ParseRequest(BaseModel):
    file_id: str
    project_id: str | None = None
    save_dir: str | None = None
    site_profiles: list[str] | None = None
    manual_main_frame: dict[str, Any] | None = None
    force_main_frame: bool | None = None
    unit: str | None = None
    unit_scale_to_mm: float | None = None
    revision: int | str | None = None


@router.get("/site-profiles")
async def get_site_profiles() -> dict:
    return RuleEngine.available_site_profiles()


@router.get("/units")
async def get_units() -> dict:
    """可选单位列表，供前端在图纸未声明单位时提示用户显式选择。"""
    from parser.dxf_units import available_units

    return {"units": available_units()}


@router.post("/parse")
async def parse_file(payload: ParseRequest) -> dict:
    try:
        site_profiles = RuleEngine.normalize_site_profiles(payload.site_profiles, require_explicit=True)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    if not is_safe_id(payload.file_id):
        raise HTTPException(status_code=400, detail="file_id 非法")

    record = get_upload(payload.file_id)
    if not record:
        raise HTTPException(status_code=404, detail="未找到上传文件，请先上传 DWG/DXF")
    dxf_path = resolve_upload_path(record)

    unit_options = None
    if payload.unit or payload.unit_scale_to_mm is not None:
        try:
            unit_options = normalize_unit_selection(payload.unit, payload.unit_scale_to_mm)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    scope_id = scoped_project_id()
    if scope_id and payload.project_id and payload.project_id != scope_id:
        assert_project_allowed(payload.project_id)
    project_id = scope_id or payload.project_id
    if project_id:
        project = load_project_or_404(project_id)
        if is_project_archived(project):
            raise HTTPException(status_code=409, detail="项目已归档，只能只读查看；请恢复后再解析")
        expected_revision = payload.revision
    else:
        project = create_project_meta(Path(record["original_name"]).stem, payload.save_dir)
        expected_revision = None

    semantic = await parse_dxf_semantic(
        dxf_path=dxf_path,
        source_record=record,
        site_profiles=site_profiles,
        manual_main_frame=payload.manual_main_frame,
        force_main_frame=payload.force_main_frame,
        unit_override=unit_options,
    )

    project["site_profiles"] = site_profiles
    if payload.manual_main_frame is not None:
        project["manual_main_frame"] = payload.manual_main_frame

    project_dxf_path = materialize_upload_for_project(project, record, dxf_path)
    # 注意：save_semantic_as_project_drawing 内部完成「读最新 meta -> 追加图纸 -> 写回」，
    # 并把结果同步回 project。这里**不能**再调用一次 save_project(project)，否则会用
    # 内存中的旧副本覆盖并发写入的其他修改。
    drawing = save_semantic_as_project_drawing(
        project=project,
        semantic=semantic,
        dxf_path=project_dxf_path,
        drawing_name=Path(record["original_name"]).stem,
        site_profiles=site_profiles,
        expected_revision=expected_revision,
    )
    await emit("INFO", "生成 semantic.json...")
    await emit("SUCCESS", f"已存档图纸 {drawing['id']}")
    attach_project_parse_meta(semantic, project, drawing)
    await emit("INFO", "Three.js 场景构建中...")
    await emit("SUCCESS", "3D 预览已就绪")
    return semantic


def resolve_upload_path(record: dict[str, Any]) -> Path:
    """从上传记录解析 DXF 路径，只允许落在上传目录内。"""
    value = record.get("dxf_path")
    if not value:
        raise HTTPException(status_code=400, detail="上传记录缺少 dxf_path")
    from storage import UPLOAD_DIR

    try:
        path = resolve_within_roots(value, [UPLOAD_DIR], label="上传 DXF 文件")
    except PathPolicyError as exc:
        raise HTTPException(status_code=400, detail=f"上传文件路径被拒绝：{exc}") from exc
    if not path.exists():
        raise HTTPException(status_code=404, detail="DXF 文件不存在，请重新上传")
    return path


async def parse_dxf_semantic(
    *,
    dxf_path: Path,
    source_record: dict[str, Any],
    site_profiles: list[str],
    manual_main_frame: dict[str, Any] | None = None,
    force_main_frame: bool | None = None,
    unit_override: dict[str, Any] | None = None,
) -> dict[str, Any]:
    await emit("INFO", "ezdxf 解析 DXF 中...")
    semaphore = await _parse_slot()
    if semaphore.locked():
        await emit("INFO", f"解析任务排队中（并发上限 {_PARSE_CONCURRENCY}）")
    async with semaphore:
        try:
            parsed = await asyncio.to_thread(DxfReader.read, dxf_path, **(unit_override or {}))
        except Exception as exc:
            await emit("ERROR", f"DXF 解析失败: {exc}")
            raise HTTPException(status_code=500, detail=str(exc)) from exc

        if parsed.get("unit_warning"):
            await emit("WARNING", parsed["unit_warning"])
        await emit(
            "INFO",
            f"读取 {parsed['total_entities']} 个实体，{parsed.get('layer_count', 0)} 个图层"
            f"（单位 {parsed.get('unit_name') or '未知'}，1:1 -> {parsed.get('unit_scale_to_mm')} mm）",
        )
        for layer_name, count in _candidate_line_layers(parsed):
            await emit("INFO", f"图层 [{layer_name}]: {count} 条线段（疑似弱电线路，请确认）")
        await emit("INFO", "规则引擎识别中...")
        source_record["parsed_at"] = now_iso()
        source_record["site_profiles"] = site_profiles
        engine = _create_rule_engine(
            site_profiles=site_profiles,
            manual_main_frame=manual_main_frame,
            force_main_frame=force_main_frame,
        )
        semantic = await asyncio.to_thread(engine.build_semantic, parsed, source_record)
    semantic["site_profiles"] = site_profiles
    semantic["unit_resolution"] = {
        "unit_code": parsed.get("unit_code"),
        "unit_name": parsed.get("unit_name"),
        "unit_scale_to_mm": parsed.get("unit_scale_to_mm"),
        "unit_source": parsed.get("unit_source"),
        "unit_unspecified": parsed.get("unit_unspecified"),
        "header_unit_code": parsed.get("header_unit_code"),
        "warning": parsed.get("unit_warning"),
    }
    stats = semantic["stats"]
    await emit(
        "SUCCESS",
        f"识别完成 -> 设备 {stats['devices']} 个，线路 {stats['cables']} 条，建筑结构 {stats.get('structures', 0)} 条",
    )
    if stats.get("cable_candidates"):
        await emit("WARNING", f"发现 {stats['cable_candidates']} 条数字图层候选线，未自动归类为弱电线路")
    checklist = semantic.get("quality", {}).get("render_checklist", [])
    missing = [item for item in checklist if item.get("status") == "missing"]
    extra = [item for item in checklist if item.get("status") == "extra_detected"]
    if missing:
        await emit("WARNING", "清单校验缺失: " + "、".join(str(item.get("label")) for item in missing))
    if extra:
        details = "、".join(f"{item.get('label')}({item.get('actual')}/{item.get('expected')})" for item in extra)
        await emit("WARNING", f"清单数量超出图纸预期或预期未声明: {details}")
    if not missing and not extra:
        await emit("SUCCESS", "清单校验通过，关键图例均已生成")
    else:
        await emit("INFO", "清单校验已输出复核项，请查看质量审计和待审核列表")
    return semantic


def _create_rule_engine(
    *,
    site_profiles: list[str],
    manual_main_frame: dict[str, Any] | None = None,
    force_main_frame: bool | None = None,
) -> RuleEngine:
    kwargs: dict[str, Any] = {"site_profiles": site_profiles}
    if manual_main_frame is not None:
        kwargs["manual_main_frame"] = manual_main_frame
    if force_main_frame is not None:
        kwargs["force_main_frame"] = force_main_frame
    signature = inspect.signature(RuleEngine)
    if any(param.kind == inspect.Parameter.VAR_KEYWORD for param in signature.parameters.values()):
        return RuleEngine(**kwargs)
    return RuleEngine(**{key: value for key, value in kwargs.items() if key in signature.parameters})


def save_semantic_as_project_drawing(
    *,
    project: dict[str, Any],
    semantic: dict[str, Any],
    dxf_path: Path,
    drawing_name: str,
    site_profiles: list[str],
    expected_revision: Any = None,
) -> dict[str, Any]:
    """写 semantic.json 并把图纸记录追加进项目。

    - semantic.json 写到服务端规范位置，路径由服务端计算。
    - 整个「读项目 -> 追加图纸 -> 写项目」在项目文件锁内完成，并发不丢图纸。
    - 传入 expected_revision 时做乐观并发校验（旧版本保存返回 409）。
    """
    draw_id = f"draw_{uuid.uuid4().hex[:10]}"
    project_id = str(project["id"])
    semantic_path = drawing_semantic_path(project_id, draw_id, archived=is_project_archived(project))
    write_json(semantic_path, semantic)
    stats = semantic["stats"]
    drawing = {
        "id": draw_id,
        "name": drawing_name,
        "parsed_at": now_iso(),
        "stats": stats,
        "site_profiles": site_profiles,
    }
    try:
        resolved_dxf = str(dxf_path)
    except OSError:
        resolved_dxf = None
    if resolved_dxf:
        drawing["dxf_path"] = resolved_dxf
    drawing["semantic_path"] = str(semantic_path)

    # 用最新磁盘状态重建，避免并发写入互相覆盖
    fresh = load_project(project_id, include_archived=True) or project
    existing = [item for item in fresh.get("drawings", []) if isinstance(item, dict)]
    existing.append(drawing)
    fresh["drawings"] = existing
    fresh["current_drawing_id"] = draw_id
    fresh["updated_at"] = now_iso()
    fresh["site_profiles"] = site_profiles
    for key in ("manual_main_frame", "name", "status", "created_at", "placement_studio", "model_binding_path"):
        if key in project:
            fresh[key] = project[key]
    saved = save_project_or_409(fresh, expected_revision=expected_revision)
    project.clear()
    project.update(saved)
    return drawing


def materialize_upload_for_project(project: dict[str, Any], source_record: dict[str, Any], dxf_path: Path) -> Path:
    """把上传文件复制进项目受管目录，返回项目内的 DXF 路径。

    同时把上传索引里的路径改写到项目内副本，避免依赖上传临时目录长期存在。
    """
    file_id = str(source_record.get("file_id") or "").strip()
    if not file_id or not is_safe_id(file_id):
        return dxf_path

    save_root = Path(project["save_dir"]).expanduser()
    source_root = save_root / "source" / "uploads" / file_id
    source_root.mkdir(parents=True, exist_ok=True)

    uploaded_path = resolve_upload_reference(source_record.get("uploaded_path"))
    target_uploaded: Path | None = None
    if uploaded_path and uploaded_path.exists():
        target_uploaded = source_root / uploaded_path.name
        copy_file_if_needed(uploaded_path, target_uploaded)

    target_dxf = source_root / dxf_path.name
    try:
        if target_uploaded and dxf_path.resolve() != target_uploaded.resolve():
            target_dxf = source_root / "converted" / dxf_path.name
    except OSError:
        if target_uploaded:
            target_dxf = source_root / "converted" / dxf_path.name

    if dxf_path.exists():
        copy_file_if_needed(dxf_path, target_dxf)
        update_upload(
            file_id,
            lambda record: record.update(
                {
                    "dxf_path": str(target_dxf),
                    "uploaded_path": str(target_uploaded) if target_uploaded else record.get("uploaded_path"),
                }
            ),
        )
        source_record["dxf_path"] = str(target_dxf)
        if target_uploaded:
            source_record["uploaded_path"] = str(target_uploaded)
        return target_dxf
    return dxf_path


def resolve_upload_reference(value: Any) -> Path | None:
    if not value:
        return None
    from storage import UPLOAD_DIR

    try:
        return resolve_within_roots(value, [UPLOAD_DIR], label="上传原始文件")
    except PathPolicyError:
        return None


def copy_file_if_needed(source: Path, target: Path) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    try:
        if source.resolve() == target.resolve():
            return
    except OSError:
        pass
    if target.exists() and target.stat().st_size == source.stat().st_size:
        return
    shutil.copy2(source, target)


def attach_project_parse_meta(semantic: dict[str, Any], project: dict[str, Any], drawing: dict[str, Any]) -> None:
    site_profiles = drawing.get("site_profiles") or project.get("site_profiles") or semantic.get("site_profiles") or ["generic"]
    semantic["project"] = {
        "id": project["id"],
        "name": project["name"],
        "status": project.get("status", "active"),
        "site_profiles": site_profiles,
        "drawing_id": drawing.get("id"),
        "current_drawing_id": project.get("current_drawing_id"),
        "revision": project.get("revision"),
    }


def _candidate_line_layers(parsed: dict) -> list[tuple[str, int]]:
    layer_names = [str(layer) for layer in parsed.get("layer_names", []) if str(layer).isdigit()]
    reports: list[tuple[str, int]] = []
    for layer_name in layer_names[:20]:
        count = sum(
            1
            for entity in parsed.get("entities", [])
            if entity.get("layer") == layer_name and entity.get("entity_type") in {"LINE", "LWPOLYLINE", "POLYLINE"}
        )
        if count > 20:
            reports.append((layer_name, count))
    return reports[:10]
