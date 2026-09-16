"""项目、图纸、导出与本地打开相关 API。

安全约定（与 `path_policy` / `security` 配套）：
- 客户端只提交 **ID**。任何文件路径都由服务端解析，并校验落在允许根目录内。
- 图纸记录里的路径字段不接受客户端覆盖；新增图纸时会被显式剥离。
- 导出、归档快照、打开文件、项目包导入共用同一套允许根目录与校验。
- 不具备的能力（静态导出、replay）返回明确的 503 + capability 信息，而不是必然失败的 500。
"""

from __future__ import annotations

import os
import re
import socket
import subprocess
import sys
import uuid
from math import isfinite
from pathlib import Path
from typing import Any
from urllib.parse import urlencode

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from path_policy import (
    PathPolicyError,
    is_safe_id,
    sanitize_filename,
    validate_drawing_id,
    validate_project_id,
    resolve_within_roots,
)
from semantic.rule_engine import RuleEngine
from storage import (
    CorruptJsonError,
    PROJECT_PACKAGES_DIR,
    RevisionConflict,
    StorageError,
    allowed_roots_for_meta,
    archive_project as archive_project_record,
    delete_archived_project,
    discover_project_packages,
    drawing_semantic_path,
    import_project_package,
    is_project_archived,
    list_projects,
    load_project,
    now_iso,
    project_dir,
    project_storage_dir,
    read_json,
    restore_project as restore_project_record,
    save_project,
)

router = APIRouter()
ROOT_DIR = Path(__file__).resolve().parents[2]
_exports_root = Path(os.environ["CAD_EXPORTS_DIR"]).expanduser() if os.environ.get("CAD_EXPORTS_DIR") else ROOT_DIR / "exports"
STATIC_EXPORT_DIR = Path(os.environ["CAD_STATIC_EXPORT_DIR"]).expanduser() if os.environ.get("CAD_STATIC_EXPORT_DIR") else _exports_root / "static-pages"
SHARE_CONFIG_PATH = ROOT_DIR / "frontend" / "share-config.js"
CURRENT_SCHEMA_VERSION = "1.1.11"
ARCHIVE_SNAPSHOT_DIRNAME = "__archive_snapshot__"
LOCAL_SHARE_HOSTS = {"127.0.0.1", "localhost", "0.0.0.0", "::1", "[::1]"}

_MAX_NAME_LENGTH = 200
_MAX_SAVE_DIR_LENGTH = 512

# 新增图纸时允许客户端提供的字段白名单（不含任何路径字段）。
DRAWING_CLIENT_FIELDS = {
    "id",
    "name",
    "site_profiles",
    "parsed_at",
    "stats",
    "placement_studio",
    "kind",
    "note",
}
DRAWING_PATH_FIELDS = {
    "semantic_path",
    "dxf_path",
    "source_path",
    "uploaded_path",
    "original_path",
    "dwg_path",
    "save_dir",
    "package_dir",
}


class ProjectCreate(BaseModel):
    name: str
    save_dir: str | None = None
    site_profiles: list[str] | None = None


class ProjectPackageImport(BaseModel):
    path: str


class DrawingAdd(BaseModel):
    drawing: dict[str, Any]


class StaticExportCreate(BaseModel):
    drawing_id: str | None = None
    file_name: str | None = None


class LocalOpenRequest(BaseModel):
    drawing_id: str | None = None


class PlacementOverridesBody(BaseModel):
    site: dict[str, Any] | None = None
    instances: list[dict[str, Any]] | None = None
    circuits: list[dict[str, Any]] | None = None
    apply_standard_heights: bool = False
    revision: int | str | None = None


class ProjectReparse(BaseModel):
    drawing_id: str | None = None
    site_profiles: list[str] | None = None
    manual_main_frame: dict[str, Any] | None = None
    force_main_frame: dict[str, Any] | bool | None = None
    bbox: dict[str, Any] | None = None
    unit: str | None = None
    unit_scale_to_mm: float | None = None
    revision: int | str | None = None


def scoped_project_id() -> str | None:
    value = os.environ.get("CAD_SCOPE_PROJECT_ID")
    return value.strip() if value and value.strip() else None


def assert_project_allowed(project_id: str) -> None:
    scope_id = scoped_project_id()
    if scope_id and project_id != scope_id:
        raise HTTPException(status_code=404, detail="当前服务已锁定到单项目，不能访问其他项目")


def require_valid_project_id(project_id: str) -> str:
    try:
        return validate_project_id(project_id)
    except PathPolicyError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


def require_valid_drawing_id(drawing_id: str) -> str:
    try:
        return validate_drawing_id(drawing_id)
    except PathPolicyError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


def load_project_or_404(project_id: str, *, include_archived: bool = True) -> dict[str, Any]:
    safe_id = require_valid_project_id(project_id)
    assert_project_allowed(safe_id)
    try:
        meta = load_project(safe_id, include_archived=include_archived)
    except CorruptJsonError as exc:
        raise HTTPException(
            status_code=500,
            detail=f"项目元数据损坏，已隔离原文件，可从隔离副本恢复：{exc.quarantine_path or exc.path}",
        ) from exc
    if not meta:
        raise HTTPException(status_code=404, detail="项目不存在")
    return meta


def save_project_or_409(meta: dict[str, Any], *, expected_revision: Any = None) -> dict[str, Any]:
    try:
        return save_project(meta, expected_revision=expected_revision)
    except RevisionConflict as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except PathPolicyError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except StorageError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


# ---------------------------------------------------------------- 能力


def _capabilities():
    from capabilities import CapabilityUnavailable, capability

    return CapabilityUnavailable, capability


def require_capability(name: str, *, status_code: int = 503) -> None:
    cap_unavailable, capability = _capabilities()
    info = capability(name)
    if not info.get("available"):
        raise HTTPException(
            status_code=status_code,
            detail=f"能力不可用（{name}）：{info.get('reason') or '未安装所需组件'}",
            headers={"X-CAD-Capability": name},
        )


def detect_lan_ip() -> str:
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
            sock.connect(("8.8.8.8", 80))
            return sock.getsockname()[0]
    except OSError:
        try:
            return socket.gethostbyname(socket.gethostname())
        except OSError:
            return "127.0.0.1"


def request_share_origin(request: Request) -> str:
    host = request.url.hostname
    if not host and request.client:
        host = request.client.host
    host = host or "127.0.0.1"
    if host in LOCAL_SHARE_HOSTS:
        host = configured_share_host() or detect_lan_ip()
    if ":" in host and not host.startswith("["):
        host = f"[{host}]"
    netloc = f"{host}:{request.url.port}" if request.url.port else host
    return f"{request.url.scheme}://{netloc}"


def configured_share_host() -> str | None:
    try:
        text = SHARE_CONFIG_PATH.read_text(encoding="utf-8")
    except OSError:
        return None
    match = re.search(r"\bhost\s*:\s*['\"]([^'\"]+)['\"]", text)
    if not match:
        return None
    host = match.group(1).strip()
    if not host or host in LOCAL_SHARE_HOSTS:
        return None
    return host


def load_static_export_tool():
    """优先使用外部导出工具（`CAD_STATIC_EXPORT_TOOL`），否则用仓库内置通用导出。"""
    configured = os.environ.get("CAD_STATIC_EXPORT_TOOL")
    if configured:
        tool_path = Path(configured).expanduser()
        if tool_path.exists():
            import importlib.util

            spec = importlib.util.spec_from_file_location("export_static_landing_pages", tool_path)
            if spec is None or spec.loader is None:
                raise HTTPException(status_code=500, detail="静态导出工具加载失败")
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
            return module
    from exporting import static_export

    return static_export


# ---------------------------------------------------------------- 图纸路径解析


def resolve_semantic_path(meta: dict[str, Any], drawing: dict[str, Any]) -> Path | None:
    """解析图纸的 semantic.json 路径。

    优先级：受管规范位置 -> 记录里已校验过的路径 -> 历史本地布局。
    记录里越界或非法的路径会被剔除，绝不读取。
    """
    drawing_id = drawing.get("id")
    if not is_safe_id(str(drawing_id or "")):
        return None
    project_id = str(meta.get("id") or "")
    if not is_safe_id(project_id):
        return None

    archived = is_project_archived(meta)
    canonical = drawing_semantic_path(project_id, str(drawing_id), archived=archived)
    if canonical.exists():
        drawing["semantic_path"] = str(canonical)
        return canonical

    # 历史布局：<project_storage_dir>/<drawing_id>/semantic.json
    legacy = project_storage_dir(meta) / str(drawing_id) / "semantic.json"
    if legacy.exists() and legacy.is_file():
        drawing["semantic_path"] = str(legacy)
        return legacy

    roots = allowed_roots_for_meta(meta)
    stored = drawing.get("semantic_path")
    if stored:
        try:
            candidate = resolve_within_roots(stored, roots, label="图纸 semantic.json")
        except PathPolicyError:
            # 历史记录里的越界/非法路径：剔除并继续找规范位置，不读取。
            drawing.pop("semantic_path", None)
        else:
            if candidate.exists() and candidate.is_file():
                drawing["semantic_path"] = str(candidate)
                return candidate
            drawing.pop("semantic_path", None)

    save_dir = meta.get("save_dir")
    if save_dir:
        try:
            save_root = resolve_within_roots(save_dir, roots, label="项目 save_dir")
        except PathPolicyError:
            return None
        candidate = save_root / str(drawing_id) / "semantic.json"
        try:
            resolved = resolve_within_roots(candidate, roots, label="图纸 semantic.json")
        except PathPolicyError:
            return None
        if resolved.exists() and resolved.is_file():
            drawing["semantic_path"] = str(resolved)
            return resolved
    return None


def require_semantic_path(meta: dict[str, Any], drawing: dict[str, Any]) -> Path:
    path = resolve_semantic_path(meta, drawing)
    if not path:
        raise HTTPException(status_code=404, detail="图纸语义数据不存在，请先解析该图纸")
    return path


def resolve_drawing_dxf_path(meta: dict[str, Any], drawing: dict[str, Any]) -> Path | None:
    """解析图纸对应的 DXF 路径，越界一律拒绝。"""
    roots = allowed_roots_for_meta(meta)
    for key in ("dxf_path", "source_path", "uploaded_path"):
        value = drawing.get(key)
        if not value:
            continue
        try:
            candidate = resolve_within_roots(value, roots, label=f"图纸 {key}")
        except PathPolicyError:
            continue
        if candidate.exists() and candidate.is_file():
            return candidate
    return None


def resolve_drawing_source_path(meta: dict[str, Any], drawing: dict[str, Any]) -> Path | None:
    """打开"原始文件"时使用的路径：优先原始 DWG/DXF，其次转换后的 DXF。"""
    roots = allowed_roots_for_meta(meta)
    for key in ("source_path", "uploaded_path", "original_path", "dwg_path"):
        value = drawing.get(key)
        if not value:
            continue
        try:
            candidate = resolve_within_roots(value, roots, label=f"图纸 {key}")
        except PathPolicyError:
            continue
        if candidate.exists() and candidate.is_file():
            return candidate

    dxf_path = resolve_drawing_dxf_path(meta, drawing)
    if not dxf_path:
        return None
    if dxf_path.parent.name.lower() == "converted":
        original = first_existing_source_file(dxf_path.parent.parent, exclude={dxf_path.resolve()})
        if original:
            return original
    return dxf_path


def first_existing_source_file(folder: Path, exclude: set[Path] | None = None) -> Path | None:
    exclude = exclude or set()
    for pattern in ("*.dwg", "*.DWG", "*.dxf", "*.DXF"):
        for candidate in sorted(folder.glob(pattern)):
            try:
                if candidate.resolve() in exclude:
                    continue
            except OSError:
                pass
            if candidate.exists() and candidate.is_file():
                return candidate
    return None


def resolve_managed_save_dir(value: Any, *, project_id: str | None = None) -> Path | None:
    """把客户端提交的 save_dir 收敛为受管目录。

    - 为空：用项目规范目录。
    - 相对路径：相对受管根目录（projects / project-packages）解析。
    - 绝对路径：必须已经位于受管根目录内，否则拒绝。
    """
    text = str(value or "").strip()
    if not text:
        return None
    if len(text) > _MAX_SAVE_DIR_LENGTH:
        raise HTTPException(status_code=400, detail="save_dir 过长")
    roots = [project_dir(project_id)] if project_id else [ROOT_DIR / "projects", PROJECT_PACKAGES_DIR]
    try:
        return resolve_within_roots(text, roots, label="save_dir")
    except PathPolicyError as exc:
        raise HTTPException(
            status_code=400,
            detail=f"save_dir 必须位于受管项目目录内，不能指向任意本机路径：{exc}",
        ) from exc


def sanitize_drawing_payload(drawing: dict[str, Any], *, new_id: str) -> dict[str, Any]:
    """校验并收敛客户端提交的图纸记录。

    路径字段（semantic_path / dxf_path / ...）会被显式剥离并丢弃：图纸落盘位置
    只能由服务端的解析流程写入。非法字段或非法类型直接 400。
    """
    if not isinstance(drawing, dict):
        raise HTTPException(status_code=400, detail="drawing 必须是对象")
    dropped_paths = sorted(key for key in drawing if key in DRAWING_PATH_FIELDS)
    unexpected = sorted(key for key in drawing if key not in DRAWING_CLIENT_FIELDS and key not in DRAWING_PATH_FIELDS and not key.startswith("_"))
    if unexpected:
        raise HTTPException(
            status_code=400,
            detail=f"图纸记录包含不允许的字段: {', '.join(unexpected)}；路径字段必须由服务端在解析时写入",
        )

    payload: dict[str, Any] = {"id": new_id}
    name = drawing.get("name")
    if name is not None:
        payload["name"] = sanitize_filename(name, fallback=new_id)
    site_profiles = drawing.get("site_profiles")
    if site_profiles is not None:
        try:
            payload["site_profiles"] = RuleEngine.normalize_site_profiles(list(site_profiles), require_explicit=False)
        except (TypeError, ValueError) as exc:
            raise HTTPException(status_code=400, detail=f"site_profiles 非法: {exc}") from exc
    parsed_at = drawing.get("parsed_at")
    if parsed_at is not None:
        payload["parsed_at"] = str(parsed_at)[:64]
    stats = drawing.get("stats")
    if stats is not None:
        payload["stats"] = _sanitize_stats(stats)
    if drawing.get("placement_studio"):
        payload["placement_studio"] = True
    if drawing.get("kind"):
        payload["kind"] = str(drawing["kind"])[:32]
    if drawing.get("note"):
        payload["note"] = str(drawing["note"])[:200]
    if dropped_paths:
        payload["_ignored_client_paths"] = dropped_paths
    return payload


def _sanitize_stats(stats: Any) -> dict[str, float]:
    if not isinstance(stats, dict):
        raise HTTPException(status_code=400, detail="stats 必须是对象")
    cleaned: dict[str, float] = {}
    for key, value in stats.items():
        if not isinstance(key, str) or len(key) > 64:
            raise HTTPException(status_code=400, detail="stats 含非法键")
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise HTTPException(status_code=400, detail=f"stats.{key} 必须是有限数字")
        if not isfinite(float(value)):
            raise HTTPException(status_code=400, detail=f"stats.{key} 必须是有限数字")
        cleaned[key] = float(value)
    return cleaned


def create_project_meta(name: str, save_dir: str | None = None, project_id: str | None = None) -> dict[str, Any]:
    pid = project_id or f"proj_{uuid.uuid4().hex[:10]}"
    pid = require_valid_project_id(pid)
    clean_name = str(name or "").strip()[:_MAX_NAME_LENGTH] or pid
    managed_save_dir = resolve_managed_save_dir(save_dir, project_id=pid)
    target_dir = managed_save_dir or project_dir(pid)
    target_dir.mkdir(parents=True, exist_ok=True)
    meta = {
        "id": pid,
        "name": clean_name,
        "save_dir": str(target_dir),
        "status": "active",
        "created_at": now_iso(),
        "updated_at": now_iso(),
        "current_drawing_id": None,
        "drawings": [],
        "revision": 0,
    }
    save_project(meta)
    return meta


# ---------------------------------------------------------------- 路由


@router.get("/projects")
async def get_projects(include_archived: bool = False, scope_project_id: str | None = None) -> list[dict[str, Any]]:
    scope_project_id = scoped_project_id() or scope_project_id
    if scope_project_id:
        require_valid_project_id(scope_project_id)
        assert_project_allowed(scope_project_id)
        project = load_project(scope_project_id, include_archived=True)
        return [project] if project else []
    return list_projects(include_archived=include_archived)


@router.get("/project-packages")
async def get_project_packages() -> list[dict[str, Any]]:
    """只读列出已登记的项目包；不返回任意路径内容。"""
    packages = []
    for meta in discover_project_packages():
        packages.append(
            {
                "id": meta.get("id"),
                "name": meta.get("name"),
                "status": meta.get("status"),
                "created_at": meta.get("created_at"),
                "updated_at": meta.get("updated_at"),
                "drawing_count": len(meta.get("drawings") or []),
                "site_profiles": meta.get("site_profiles") or [],
            }
        )
    return packages


@router.post("/project-packages/import")
async def import_package(payload: ProjectPackageImport) -> dict[str, Any]:
    """导入项目包。

    只接受 **已登记项目包根目录内** 的相对路径；绝对路径、`..`、符号链接越界一律拒绝。
    """
    if scoped_project_id():
        raise HTTPException(status_code=403, detail="当前服务已锁定到单项目，不能导入其他项目包")
    raw = str(payload.path or "").strip()
    if not raw:
        raise HTTPException(status_code=400, detail="path 不能为空")
    if len(raw) > _MAX_SAVE_DIR_LENGTH:
        raise HTTPException(status_code=400, detail="path 过长")
    try:
        return import_project_package(raw)
    except PathPolicyError as exc:
        raise HTTPException(status_code=400, detail=f"项目包路径被拒绝：{exc}") from exc
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except OSError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/projects")
async def create_project(payload: ProjectCreate) -> dict[str, Any]:
    if scoped_project_id():
        raise HTTPException(status_code=403, detail="当前服务已锁定到单项目，不能新建其他项目")
    meta = create_project_meta(payload.name, payload.save_dir)
    if payload.site_profiles:
        try:
            meta["site_profiles"] = RuleEngine.normalize_site_profiles(payload.site_profiles, require_explicit=False)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        meta = save_project_or_409(meta)
    return meta


@router.get("/model-catalog")
async def get_model_catalog() -> dict[str, Any]:
    from placement import load_catalog

    catalog = load_catalog()
    return {
        "version": catalog["version"],
        "site_defaults": catalog["site_defaults"],
        "groups": catalog.get("groups") or [],
        "items": catalog["items"],
    }


@router.post("/projects/{project_id}/placement/ensure")
async def ensure_placement(project_id: str) -> dict[str, Any]:
    meta = load_project_or_404(project_id)
    ensure_project_active(meta)
    from placement import ensure_placement_scene, is_placement_project

    if not is_placement_project(meta):
        raise HTTPException(status_code=403, detail="该项目不是摆放试验场，不能初始化摆放场景")
    return ensure_placement_scene(meta)


@router.get("/projects/{project_id}/model-overrides")
async def get_model_overrides(project_id: str) -> dict[str, Any]:
    meta = load_project_or_404(project_id)
    from placement import load_overrides

    return load_overrides(meta)


@router.put("/projects/{project_id}/model-overrides")
async def put_model_overrides(project_id: str, payload: PlacementOverridesBody) -> dict[str, Any]:
    meta = load_project_or_404(project_id)
    ensure_project_active(meta)
    from placement import OverrideValidationError
    from placement import RevisionConflict as PlacementRevisionConflict
    from placement import apply_standard_heights, ensure_placement_scene, is_placement_project, save_overrides

    if not is_placement_project(meta):
        raise HTTPException(status_code=403, detail="该项目不是摆放试验场，不能写入模型覆盖")

    data = {
        "site": payload.site or {},
        "instances": payload.instances or [],
        "circuits": payload.circuits or [],
    }
    if payload.apply_standard_heights:
        data = apply_standard_heights(data)
    try:
        saved = save_overrides(meta, data, expected_revision=payload.revision)
    except PlacementRevisionConflict as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except OverrideValidationError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except PathPolicyError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    ensure_placement_scene(meta)
    return saved


@router.get("/projects/{project_id}")
async def get_project(project_id: str) -> dict[str, Any]:
    return load_project_or_404(project_id)


@router.post("/projects/{project_id}/drawings")
async def add_drawing(project_id: str, payload: DrawingAdd) -> dict[str, Any]:
    meta = load_project_or_404(project_id)
    ensure_project_active(meta)
    drawing = sanitize_drawing_payload(payload.drawing, new_id=f"draw_{uuid.uuid4().hex[:10]}")
    ignored = drawing.pop("_ignored_client_paths", [])
    meta.setdefault("drawings", []).append(drawing)
    meta["current_drawing_id"] = drawing["id"]
    meta["updated_at"] = now_iso()
    saved = save_project_or_409(meta)
    if ignored:
        saved = {**saved, "ignored_client_path_fields": ignored}
    return saved


@router.post("/projects/{project_id}/reparse")
async def reparse_project(project_id: str, payload: ProjectReparse) -> dict[str, Any]:
    meta = load_project_or_404(project_id)
    ensure_project_active(meta)

    current = current_project_drawing(meta)
    if not current:
        raise HTTPException(status_code=404, detail="项目没有当前图纸，无法重新解析")
    if payload.drawing_id:
        selected = selected_project_drawing(meta, require_valid_drawing_id(payload.drawing_id))
        if not selected:
            raise HTTPException(status_code=404, detail="指定图纸不存在")
        current = selected
    dxf_path = resolve_drawing_dxf_path(meta, current)
    if not dxf_path:
        raise HTTPException(status_code=404, detail="当前图纸缺少可用的 DXF 文件，无法重新解析")

    try:
        site_profiles = RuleEngine.normalize_site_profiles(
            payload.site_profiles or current.get("site_profiles") or meta.get("site_profiles"),
            require_explicit=True,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    payload_fields = getattr(payload, "model_fields_set", getattr(payload, "__fields_set__", set()))
    manual_main_frame = resolve_manual_main_frame(payload, payload_fields, meta)
    if {"manual_main_frame", "force_main_frame", "bbox"} & set(payload_fields):
        if manual_main_frame is None:
            meta.pop("manual_main_frame", None)
        else:
            meta["manual_main_frame"] = manual_main_frame

    unit_options = normalize_unit_options(payload)

    from api.parse import attach_project_parse_meta, parse_dxf_semantic, save_semantic_as_project_drawing

    semantic = await parse_dxf_semantic(
        dxf_path=dxf_path,
        source_record={
            "dxf_path": str(dxf_path),
            "original_name": current.get("name") or dxf_path.name,
            "site_profiles": site_profiles,
        },
        site_profiles=site_profiles,
        manual_main_frame=manual_main_frame,
        force_main_frame=bool(manual_main_frame),
        unit_override=unit_options,
    )
    meta["site_profiles"] = site_profiles
    # 重新解析只新增图纸记录，人工摆放 overrides 保持不变。
    drawing = save_semantic_as_project_drawing(
        project=meta,
        semantic=semantic,
        dxf_path=dxf_path,
        drawing_name=str(current.get("name") or dxf_path.stem),
        site_profiles=site_profiles,
        expected_revision=payload.revision,
    )
    from log_hub import emit

    await emit("INFO", "生成 semantic.json...")
    await emit("SUCCESS", f"已存档图纸 {drawing['id']}")
    attach_project_parse_meta(semantic, meta, drawing)
    return semantic


def normalize_unit_options(payload: ProjectReparse) -> dict[str, Any] | None:
    """把客户端显式单位选择转为 DxfReader 选项；未提供返回 None。"""
    unit = (payload.unit or "").strip() or None
    scale = payload.unit_scale_to_mm
    if unit is None and scale is None:
        return None
    from parser.dxf_units import normalize_unit_selection

    try:
        return normalize_unit_selection(unit, scale)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


def resolve_manual_main_frame(
    payload: ProjectReparse,
    payload_fields: set[str],
    meta: dict[str, Any],
) -> dict[str, Any] | None:
    if "manual_main_frame" in payload_fields:
        return normalize_manual_frame_payload(payload.manual_main_frame)
    if "force_main_frame" in payload_fields:
        forced = payload.force_main_frame
        if isinstance(forced, dict):
            return normalize_manual_frame_payload(forced)
        if forced is False:
            return None
    if "bbox" in payload_fields:
        return normalize_manual_frame_payload({"bbox": payload.bbox, "kind": "manual"})
    return normalize_manual_frame_payload(meta.get("manual_main_frame"))


def normalize_manual_frame_payload(value: dict[str, Any] | None) -> dict[str, Any] | None:
    if not isinstance(value, dict):
        return None
    bounds = value.get("bounds") if isinstance(value.get("bounds"), dict) else value.get("bbox")
    if not isinstance(bounds, dict):
        bounds = value
    try:
        normalized_bounds = {
            "min_x": float(bounds["min_x"]),
            "min_y": float(bounds["min_y"]),
            "max_x": float(bounds["max_x"]),
            "max_y": float(bounds["max_y"]),
        }
    except (KeyError, TypeError, ValueError):
        return None
    if not all(isfinite(item) for item in normalized_bounds.values()):
        return None
    if normalized_bounds["max_x"] <= normalized_bounds["min_x"] or normalized_bounds["max_y"] <= normalized_bounds["min_y"]:
        return None
    return {"kind": str(value.get("kind") or "manual"), "bounds": normalized_bounds}


@router.delete("/projects/{project_id}")
async def delete_project(project_id: str, confirm: str | None = None) -> dict[str, Any]:
    meta = load_project_or_404(project_id)
    if not is_project_archived(meta):
        raise HTTPException(status_code=409, detail="只能删除已归档项目，请先归档再删除")
    if confirm != meta["id"]:
        raise HTTPException(status_code=400, detail="删除归档项目需要二次确认，请提交 confirm=项目ID")
    backup_path = delete_archived_project(meta["id"])
    return {"deleted": True, "backup_path": str(backup_path)}


@router.post("/projects/{project_id}/archive")
async def archive_project(project_id: str) -> dict[str, Any]:
    meta = load_project_or_404(project_id)
    if is_project_archived(meta):
        return meta

    snapshot_info = _generate_archive_snapshot(meta)

    try:
        archived = archive_project_record(meta["id"])
    except RevisionConflict as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except (FileExistsError, StorageError) as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc

    if snapshot_info:
        archived = _persist_archive_snapshot(archived, snapshot_info)
    return archived


@router.post("/projects/{project_id}/restore")
async def restore_project(project_id: str) -> dict[str, Any]:
    meta = load_project_or_404(project_id)
    if not is_project_archived(meta):
        return meta
    try:
        return restore_project_record(meta["id"])
    except (FileExistsError, StorageError) as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


def _generate_archive_snapshot(meta: dict[str, Any]) -> dict[str, Any] | None:
    """归档快照是可选能力：能力不可用时归档照常进行，只是没有静态快照。"""
    current = current_project_drawing(meta)
    if not current:
        return None
    try:
        require_capability("static_export")
    except HTTPException:
        return None
    semantic_path = resolve_semantic_path(meta, current)
    if not semantic_path or not semantic_path.exists():
        return None
    try:
        exporter = load_static_export_tool()
        result = exporter.export_single_project(
            meta,
            output_root=STATIC_EXPORT_DIR,
            drawing_id=current.get("id"),
            file_name=f"{meta.get('name') or meta['id']}-archive.html",
            public_url_prefix="/exports/static-pages",
        )
        export_path = Path(result.get("path", ""))
        if not export_path.exists() or export_path.stat().st_size <= 0:
            return None
        return {
            "html_path": str(export_path),
            "html_dir": str(export_path.parent),
            "file_name": result.get("file_name"),
            "url": result.get("url"),
            "size_bytes": export_path.stat().st_size,
            "drawing_id": current.get("id"),
            "generated_at": now_iso(),
        }
    except Exception:
        return None


def _persist_archive_snapshot(meta: dict[str, Any], snapshot: dict[str, Any]) -> dict[str, Any]:
    project_root = project_storage_dir(meta)
    snapshot_dir = project_root / ARCHIVE_SNAPSHOT_DIRNAME
    snapshot_dir.mkdir(parents=True, exist_ok=True)
    src_html = Path(snapshot["html_path"])
    if src_html.exists():
        import shutil

        dest_html = snapshot_dir / src_html.name
        try:
            shutil.copy2(src_html, dest_html)
            snapshot["archived_html_path"] = str(dest_html)
        except OSError:
            pass
    meta["archive_snapshot"] = snapshot
    save_project(meta)
    return meta


@router.get("/projects/{project_id}/export")
async def export_project(
    project_id: str,
    drawing_id: str | None = None,
    include_all_drawings: bool = False,
) -> JSONResponse:
    meta = load_project_or_404(project_id)
    if drawing_id:
        require_valid_drawing_id(drawing_id)
    drawings = meta.get("drawings", [])
    current = current_project_drawing(meta)
    current_id = meta.get("current_drawing_id")
    selected = next((drawing for drawing in drawings if drawing.get("id") == drawing_id), None) if drawing_id else current
    if drawing_id and selected is None:
        raise HTTPException(status_code=404, detail="指定图纸不存在")
    if selected and not include_all_drawings:
        semantic_path = require_semantic_path(meta, selected)
        semantic = read_semantic_or_400(semantic_path)
        attach_project_export_meta(semantic, meta, selected)
        save_project(meta)
        return JSONResponse(semantic)

    exported = []
    for drawing in drawings:
        semantic_path = resolve_semantic_path(meta, drawing)
        if not semantic_path:
            continue
        try:
            semantic = read_semantic_or_400(semantic_path)
        except HTTPException:
            continue
        attach_project_export_meta(semantic, meta, drawing)
        exported.append(semantic)
    save_project(meta)
    if current_id:
        exported.sort(key=lambda item: 0 if item.get("project", {}).get("drawing_id") == current_id else 1)
    return JSONResponse({"project": meta, "current_drawing_id": current_id, "drawings": exported})


def read_semantic_or_400(path: Path) -> dict[str, Any]:
    try:
        semantic = read_json(path, None)
    except CorruptJsonError as exc:
        raise HTTPException(
            status_code=500,
            detail=f"semantic.json 损坏，已隔离原文件：{exc.quarantine_path or exc.path}",
        ) from exc
    if not isinstance(semantic, dict) or not semantic:
        raise HTTPException(status_code=404, detail="图纸语义数据不存在")
    return semantic


@router.post("/projects/{project_id}/export-static")
async def export_project_static(project_id: str, payload: StaticExportCreate | None = None) -> dict[str, Any]:
    meta = load_project_or_404(project_id)
    ensure_project_active(meta)
    require_capability("static_export")
    if payload and payload.drawing_id:
        require_valid_drawing_id(payload.drawing_id)
    try:
        exporter = load_static_export_tool()
        result = exporter.export_single_project(
            meta,
            output_root=STATIC_EXPORT_DIR,
            drawing_id=payload.drawing_id if payload else None,
            file_name=payload.file_name if payload else None,
            public_url_prefix="/exports/static-pages",
        )
        export_path = Path(result.get("path", ""))
        if not export_path.exists():
            raise ValueError(f"静态导出文件不存在: {export_path}")
        size_bytes = export_path.stat().st_size
        if size_bytes <= 0:
            raise ValueError(f"静态导出文件为空: {export_path}")
        result["size_bytes"] = size_bytes
        return result
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except CorruptJsonError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"静态导出失败: {exc}") from exc


@router.get("/projects/{project_id}/share-link")
async def project_share_link(project_id: str, request: Request, drawing_id: str | None = None) -> dict[str, Any]:
    meta = load_project_or_404(project_id)
    ensure_project_active(meta)
    require_capability("share_link")
    if drawing_id:
        require_valid_drawing_id(drawing_id)
    selected_drawing_id = drawing_id or meta.get("current_drawing_id")
    origin = request_share_origin(request)
    try:
        exporter = load_static_export_tool()
        result = exporter.export_single_project(
            meta,
            output_root=STATIC_EXPORT_DIR,
            drawing_id=str(selected_drawing_id) if selected_drawing_id else None,
            file_name=f"{meta.get('name') or project_id}-share.html",
            public_url_prefix="/exports/static-pages",
        )
        export_path = Path(result.get("path", ""))
        if not export_path.exists() or export_path.stat().st_size <= 0:
            raise ValueError(f"静态分享页面生成失败: {export_path}")
        params = {"project": meta["id"]}
        if selected_drawing_id:
            params["drawing"] = str(selected_drawing_id)
        return {
            "url": f"{origin}{result['url']}",
            "app_url": f"{origin}/?{urlencode(params)}",
            "origin": origin,
            "project_id": meta["id"],
            "drawing_id": str(selected_drawing_id) if selected_drawing_id else None,
            "size_bytes": export_path.stat().st_size,
            "file_name": result.get("file_name"),
            "path": result.get("path"),
        }
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"分享链接生成失败: {exc}") from exc


@router.post("/projects/{project_id}/open-folder")
async def open_project_folder(project_id: str) -> dict[str, Any]:
    meta = load_project_or_404(project_id)
    roots = allowed_roots_for_meta(meta)
    folder_value = meta.get("save_dir") or str(project_storage_dir(meta))
    try:
        folder = resolve_within_roots(folder_value, roots, label="项目目录", must_exist=True)
    except PathPolicyError as exc:
        raise HTTPException(status_code=404, detail=f"项目目录不可用或被拒绝：{exc}") from exc
    if not folder.is_dir():
        raise HTTPException(status_code=404, detail=f"项目目录不存在: {folder}")
    open_local_path(folder)
    return {"opened": True, "path": str(folder), "kind": "folder"}


@router.post("/projects/{project_id}/open-source-file")
async def open_project_source_file(project_id: str, payload: LocalOpenRequest | None = None) -> dict[str, Any]:
    meta = load_project_or_404(project_id)
    drawing_id = payload.drawing_id if payload else None
    if drawing_id:
        require_valid_drawing_id(drawing_id)
    drawing = selected_project_drawing(meta, drawing_id)
    if not drawing:
        raise HTTPException(status_code=404, detail="当前项目没有可打开的图纸")
    source_path = resolve_drawing_source_path(meta, drawing)
    if not source_path:
        raise HTTPException(status_code=404, detail="未找到当前图纸对应的本地 DWG/DXF 文件")
    open_local_path(source_path)
    return {"opened": True, "path": str(source_path), "kind": "source_file", "drawing_id": drawing.get("id")}


def ensure_project_active(meta: dict[str, Any]) -> None:
    if is_project_archived(meta):
        raise HTTPException(status_code=409, detail="项目已归档，只允许只读查看；请恢复后再解析、导出或分享")


def selected_project_drawing(meta: dict[str, Any], drawing_id: str | None = None) -> dict[str, Any] | None:
    drawings = meta.get("drawings", [])
    if drawing_id:
        return next((drawing for drawing in drawings if drawing.get("id") == drawing_id), None)
    return current_project_drawing(meta)


def current_project_drawing(meta: dict[str, Any]) -> dict[str, Any] | None:
    drawings = [item for item in meta.get("drawings", []) if isinstance(item, dict)]
    current_id = meta.get("current_drawing_id")
    current = next((drawing for drawing in drawings if drawing.get("id") == current_id), None)
    if current is None and drawings:
        current = sorted(drawings, key=lambda item: item.get("parsed_at", ""), reverse=True)[0]
        meta["current_drawing_id"] = current.get("id")
    return current


def open_local_path(path: Path) -> None:
    try:
        if sys.platform == "darwin":
            subprocess.Popen(["open", str(path)])
        elif os.name == "nt":
            os.startfile(str(path))  # type: ignore[attr-defined]
        else:
            subprocess.Popen(["xdg-open", str(path)])
    except OSError as exc:
        raise HTTPException(status_code=500, detail=f"无法打开本地路径: {exc}") from exc


def attach_project_export_meta(semantic: dict[str, Any], meta: dict[str, Any], drawing: dict[str, Any]) -> None:
    semantic.setdefault("site_profiles", meta.get("site_profiles") or semantic.get("site_profiles") or ["generic"])
    model_bindings = load_project_model_bindings(meta)
    semantic["project"] = {
        "id": meta["id"],
        "name": meta["name"],
        "status": meta.get("status", "active"),
        "site_profiles": semantic.get("site_profiles") or ["generic"],
        "drawing_id": drawing.get("id"),
        "current_drawing_id": meta.get("current_drawing_id"),
        "drawings": [_public_drawing(drawing_item) for drawing_item in meta.get("drawings", []) if isinstance(drawing_item, dict)],
        "model_bindings": model_bindings,
        "model_binding_path": meta.get("model_binding_path"),
        "model_bindings_locked": bool(meta.get("model_bindings_locked") or model_bindings),
        "model_binding_updated_at": meta.get("model_binding_updated_at"),
        "revision": meta.get("revision"),
    }


def _public_drawing(drawing: dict[str, Any]) -> dict[str, Any]:
    """对外返回的图纸记录：不含本机绝对路径。"""
    return {
        key: value
        for key, value in drawing.items()
        if key not in DRAWING_PATH_FIELDS and key != "_ignored_client_paths"
    }


def load_project_model_bindings(meta: dict[str, Any]) -> dict[str, Any]:
    roots = allowed_roots_for_meta(meta)
    candidates: list[Any] = []
    binding_value = meta.get("model_binding_path")
    if binding_value:
        candidates.append(binding_value)
        package_dir = meta.get("package_dir")
        if package_dir:
            candidates.append(Path(str(package_dir)) / str(binding_value))
        save_dir = meta.get("save_dir")
        if save_dir:
            candidates.append(Path(str(save_dir)) / str(binding_value))
    save_dir = meta.get("save_dir")
    if save_dir:
        candidates.append(Path(str(save_dir)) / "model-overrides" / "model-bindings.json")
    candidates.append(project_storage_dir(meta) / "model-overrides" / "model-bindings.json")
    for candidate in candidates:
        try:
            resolved = resolve_within_roots(candidate, roots, label="模型绑定文件")
        except PathPolicyError:
            continue
        if resolved.exists() and resolved.is_file():
            data = read_json(resolved, {})
            if isinstance(data, dict):
                return data
    return {}
