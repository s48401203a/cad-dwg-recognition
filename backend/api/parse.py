import asyncio
import inspect
import shutil
import uuid
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from api.projects import assert_project_allowed, create_project_meta, scoped_project_id
from log_hub import emit
from parser.dxf_reader import DxfReader
from semantic.rule_engine import RuleEngine
from storage import get_upload, is_project_archived, load_project, now_iso, save_project, write_json

router = APIRouter()


class ParseRequest(BaseModel):
    file_id: str
    project_id: str | None = None
    save_dir: str | None = None
    site_profiles: list[str] | None = None
    manual_main_frame: dict[str, Any] | None = None
    force_main_frame: bool | None = None


@router.get("/site-profiles")
async def get_site_profiles() -> dict:
    return RuleEngine.available_site_profiles()


@router.post("/parse")
async def parse_file(payload: ParseRequest) -> dict:
    try:
        site_profiles = RuleEngine.normalize_site_profiles(payload.site_profiles, require_explicit=True)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    record = get_upload(payload.file_id)
    if not record:
        raise HTTPException(status_code=404, detail="未找到上传文件，请先上传 DWG/DXF")
    dxf_path = Path(record["dxf_path"])
    if not dxf_path.exists():
        raise HTTPException(status_code=404, detail=f"DXF 文件不存在: {dxf_path}")

    semantic = await parse_dxf_semantic(
        dxf_path=dxf_path,
        source_record=record,
        site_profiles=site_profiles,
        manual_main_frame=payload.manual_main_frame,
        force_main_frame=payload.force_main_frame,
    )

    scope_id = scoped_project_id()
    if scope_id and payload.project_id and payload.project_id != scope_id:
        assert_project_allowed(payload.project_id)
    project_id = scope_id or payload.project_id
    if project_id:
        project = load_project(project_id, include_archived=True)
        if project and is_project_archived(project):
            raise HTTPException(status_code=409, detail="项目已归档，只能只读查看；请恢复后再解析")
        if not project:
            project = create_project_meta(Path(record["original_name"]).stem, payload.save_dir, project_id=project_id)
    else:
        project = create_project_meta(Path(record["original_name"]).stem, payload.save_dir)
        project_id = project["id"]
    project["site_profiles"] = site_profiles
    if payload.manual_main_frame is not None:
        project["manual_main_frame"] = payload.manual_main_frame

    project_dxf_path = materialize_upload_for_project(project, record, dxf_path)
    drawing = save_semantic_as_project_drawing(
        project=project,
        semantic=semantic,
        dxf_path=project_dxf_path,
        drawing_name=Path(record["original_name"]).stem,
        site_profiles=site_profiles,
    )
    await emit("INFO", "生成 semantic.json...")
    await emit("SUCCESS", f"存档到 {drawing['semantic_path']}")
    save_project(project)
    attach_project_parse_meta(semantic, project, drawing)
    await emit("INFO", "Three.js 场景构建中...")
    await emit("SUCCESS", "3D 预览已就绪")
    return semantic


async def parse_dxf_semantic(
    *,
    dxf_path: Path,
    source_record: dict[str, Any],
    site_profiles: list[str],
    manual_main_frame: dict[str, Any] | None = None,
    force_main_frame: bool | None = None,
) -> dict[str, Any]:
    await emit("INFO", "ezdxf 解析 DXF 中...")
    try:
        parsed = await asyncio.to_thread(DxfReader.read, dxf_path)
    except Exception as exc:
        await emit("ERROR", f"DXF 解析失败: {exc}")
        raise HTTPException(status_code=500, detail=str(exc)) from exc

    await emit("INFO", f"读取 {parsed['total_entities']} 个实体，{parsed.get('layer_count', 0)} 个图层")
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
) -> dict[str, Any]:
    draw_id = f"draw_{uuid.uuid4().hex[:10]}"
    save_root = Path(project["save_dir"])
    semantic_path = save_root / draw_id / "semantic.json"
    write_json(semantic_path, semantic)
    stats = semantic["stats"]
    drawing = {
        "id": draw_id,
        "name": drawing_name,
        "dxf_path": str(dxf_path),
        "semantic_path": str(semantic_path),
        "parsed_at": now_iso(),
        "stats": stats,
        "site_profiles": site_profiles,
    }
    existing = list(project.get("drawings", []))
    existing.append(drawing)
    project["drawings"] = existing
    project["current_drawing_id"] = draw_id
    project["updated_at"] = now_iso()
    return drawing


def materialize_upload_for_project(project: dict[str, Any], source_record: dict[str, Any], dxf_path: Path) -> Path:
    file_id = str(source_record.get("file_id") or "").strip()
    if not file_id:
        return dxf_path

    save_root = Path(project["save_dir"]).expanduser()
    source_root = save_root / "source" / "uploads" / file_id
    source_root.mkdir(parents=True, exist_ok=True)

    uploaded_path_value = source_record.get("uploaded_path")
    uploaded_path = Path(uploaded_path_value).expanduser() if uploaded_path_value else None
    target_uploaded: Path | None = None
    if uploaded_path and uploaded_path.exists():
        target_uploaded = source_root / uploaded_path.name
        copy_file_if_needed(uploaded_path, target_uploaded)
        source_record["uploaded_path"] = str(target_uploaded)

    target_dxf = source_root / dxf_path.name
    try:
        if target_uploaded and dxf_path.resolve() != target_uploaded.resolve():
            target_dxf = source_root / "converted" / dxf_path.name
    except OSError:
        if target_uploaded:
            target_dxf = source_root / "converted" / dxf_path.name

    if dxf_path.exists():
        copy_file_if_needed(dxf_path, target_dxf)
        source_record["dxf_path"] = str(target_dxf)
        return target_dxf
    return dxf_path


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
    site_profiles = drawing.get("site_profiles") or project.get("site_profiles") or semantic.get("site_profiles") or ["express"]
    semantic["project"] = {
        "id": project["id"],
        "name": project["name"],
        "save_dir": project["save_dir"],
        "status": project.get("status", "active"),
        "site_profiles": site_profiles,
        "drawing_id": drawing.get("id"),
        "current_drawing_id": project.get("current_drawing_id"),
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
