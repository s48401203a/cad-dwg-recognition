import shutil
import uuid
import importlib.util
import os
import re
import socket
import subprocess
import sys
from pathlib import Path
from typing import Any
from urllib.parse import urlencode

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from semantic.rule_engine import RuleEngine
from storage import (
    archive_project as archive_project_record,
    delete_archived_project,
    discover_project_packages,
    import_project_package,
    is_project_archived,
    list_projects,
    load_project,
    now_iso,
    project_storage_dir,
    read_json,
    restore_project as restore_project_record,
    save_project,
)

router = APIRouter()
ROOT_DIR = Path(__file__).resolve().parents[2]
STATIC_EXPORT_TOOL = ROOT_DIR / "tools" / "export_static_landing_pages.py"
_exports_root = Path(os.environ["CAD_EXPORTS_DIR"]).expanduser() if os.environ.get("CAD_EXPORTS_DIR") else ROOT_DIR / "exports"
STATIC_EXPORT_DIR = Path(os.environ["CAD_STATIC_EXPORT_DIR"]).expanduser() if os.environ.get("CAD_STATIC_EXPORT_DIR") else _exports_root / "static-pages"
SHARE_CONFIG_PATH = ROOT_DIR / "frontend" / "share-config.js"
CURRENT_SCHEMA_VERSION = "1.1.11"
ARCHIVE_SNAPSHOT_DIRNAME = "__archive_snapshot__"
LOCAL_SHARE_HOSTS = {"127.0.0.1", "localhost", "0.0.0.0", "::1", "[::1]"}


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


class ProjectReparse(BaseModel):
    drawing_id: str | None = None
    site_profiles: list[str] | None = None
    manual_main_frame: dict[str, Any] | None = None
    force_main_frame: dict[str, Any] | bool | None = None
    bbox: dict[str, Any] | None = None


def scoped_project_id() -> str | None:
    value = os.environ.get("CAD_SCOPE_PROJECT_ID")
    return value.strip() if value and value.strip() else None


def assert_project_allowed(project_id: str) -> None:
    scope_id = scoped_project_id()
    if scope_id and project_id != scope_id:
        raise HTTPException(status_code=404, detail="当前服务已锁定到单项目，不能访问其他项目")


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
    if not STATIC_EXPORT_TOOL.exists():
        raise HTTPException(status_code=500, detail="静态导出工具不存在")
    spec = importlib.util.spec_from_file_location("export_static_landing_pages", STATIC_EXPORT_TOOL)
    if spec is None or spec.loader is None:
        raise HTTPException(status_code=500, detail="静态导出工具加载失败")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def resolve_semantic_path(meta: dict[str, Any], drawing: dict[str, Any]) -> Path | None:
    semantic_path = drawing.get("semantic_path")
    if semantic_path:
        path = Path(semantic_path)
        if path.exists():
            return path

    drawing_id = drawing.get("id")
    if not drawing_id:
        return None

    local_path = project_storage_dir(meta) / drawing_id / "semantic.json"
    if local_path.exists():
        drawing["semantic_path"] = str(local_path)
        return local_path

    save_dir = meta.get("save_dir")
    if save_dir:
        save_path = Path(save_dir) / drawing_id / "semantic.json"
        if save_path.exists():
            return save_path

    return None


def create_project_meta(name: str, save_dir: str | None = None, project_id: str | None = None) -> dict[str, Any]:
    pid = project_id or f"proj_{uuid.uuid4().hex[:10]}"
    from storage import project_dir

    target_dir = Path(save_dir).expanduser() if save_dir else project_dir(pid)
    target_dir.mkdir(parents=True, exist_ok=True)
    meta = {
        "id": pid,
        "name": name.strip() or pid,
        "save_dir": str(target_dir),
        "status": "active",
        "created_at": now_iso(),
        "updated_at": now_iso(),
        "current_drawing_id": None,
        "drawings": [],
    }
    save_project(meta)
    return meta


@router.get("/projects")
async def get_projects(include_archived: bool = False, scope_project_id: str | None = None) -> list[dict[str, Any]]:
    scope_project_id = scoped_project_id() or scope_project_id
    if scope_project_id:
        project = load_project(scope_project_id, include_archived=True)
        return [project] if project else []
    return list_projects(include_archived=include_archived)


@router.get("/project-packages")
async def get_project_packages() -> list[dict[str, Any]]:
    return discover_project_packages()


@router.post("/project-packages/import")
async def import_package(payload: ProjectPackageImport) -> dict[str, Any]:
    if scoped_project_id():
        raise HTTPException(status_code=403, detail="当前服务已锁定到单项目，不能导入其他项目包")
    try:
        return import_project_package(payload.path)
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
        meta["site_profiles"] = payload.site_profiles
        save_project(meta)
    return meta


@router.get("/projects/{project_id}")
async def get_project(project_id: str) -> dict[str, Any]:
    assert_project_allowed(project_id)
    meta = load_project(project_id, include_archived=True)
    if not meta:
        raise HTTPException(status_code=404, detail="项目不存在")
    return meta


@router.post("/projects/{project_id}/drawings")
async def add_drawing(project_id: str, payload: DrawingAdd) -> dict[str, Any]:
    assert_project_allowed(project_id)
    meta = load_project(project_id, include_archived=True)
    if not meta:
        raise HTTPException(status_code=404, detail="项目不存在")
    ensure_project_active(meta)
    drawing = payload.drawing
    if not drawing.get("id"):
        drawing["id"] = f"draw_{uuid.uuid4().hex[:10]}"
    meta.setdefault("drawings", []).append(drawing)
    meta["current_drawing_id"] = drawing["id"]
    meta["updated_at"] = now_iso()
    save_project(meta)
    return meta


@router.post("/projects/{project_id}/reparse")
async def reparse_project(project_id: str, payload: ProjectReparse) -> dict[str, Any]:
    assert_project_allowed(project_id)
    meta = load_project(project_id, include_archived=True)
    if not meta:
        raise HTTPException(status_code=404, detail="项目不存在")
    ensure_project_active(meta)

    current = current_project_drawing(meta)
    if not current:
        raise HTTPException(status_code=404, detail="项目没有当前图纸，无法重新解析")
    dxf_path_value = current.get("dxf_path")
    if not dxf_path_value:
        raise HTTPException(status_code=400, detail="当前图纸缺少 dxf_path，无法重新解析")
    dxf_path = Path(dxf_path_value)
    if not dxf_path.exists():
        raise HTTPException(status_code=404, detail=f"DXF 文件不存在: {dxf_path}")

    try:
        site_profiles = RuleEngine.normalize_site_profiles(
            current.get("site_profiles") or meta.get("site_profiles"),
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
    )
    meta["site_profiles"] = site_profiles
    drawing = save_semantic_as_project_drawing(
        project=meta,
        semantic=semantic,
        dxf_path=dxf_path,
        drawing_name=str(current.get("name") or dxf_path.stem),
        site_profiles=site_profiles,
    )
    from log_hub import emit

    await emit("INFO", "生成 semantic.json...")
    await emit("SUCCESS", f"存档到 {drawing['semantic_path']}")
    save_project(meta)
    attach_project_parse_meta(semantic, meta, drawing)
    return semantic


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
    if normalized_bounds["max_x"] <= normalized_bounds["min_x"] or normalized_bounds["max_y"] <= normalized_bounds["min_y"]:
        return None
    return {"kind": str(value.get("kind") or "manual"), "bounds": normalized_bounds}


@router.delete("/projects/{project_id}")
async def delete_project(project_id: str, confirm: str | None = None) -> dict[str, Any]:
    assert_project_allowed(project_id)
    meta = load_project(project_id, include_archived=True)
    if not meta:
        raise HTTPException(status_code=404, detail="项目不存在")
    if not is_project_archived(meta):
        raise HTTPException(status_code=409, detail="只能删除已归档项目，请先归档再删除")
    if confirm != project_id:
        raise HTTPException(status_code=400, detail="删除归档项目需要二次确认，请提交 confirm=项目ID")
    backup_path = delete_archived_project(project_id)
    return {"deleted": True, "backup_path": str(backup_path)}


@router.post("/projects/{project_id}/archive")
async def archive_project(project_id: str) -> dict[str, Any]:
    assert_project_allowed(project_id)
    meta = load_project(project_id, include_archived=True)
    if not meta:
        raise HTTPException(status_code=404, detail="项目不存在")
    if is_project_archived(meta):
        return meta

    snapshot_info = _generate_archive_snapshot(meta)

    try:
        archived = archive_project_record(project_id)
    except FileExistsError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc

    if snapshot_info:
        archived = _persist_archive_snapshot(archived, snapshot_info)
    return archived


@router.post("/projects/{project_id}/restore")
async def restore_project(project_id: str) -> dict[str, Any]:
    assert_project_allowed(project_id)
    meta = load_project(project_id, include_archived=True)
    if not meta:
        raise HTTPException(status_code=404, detail="项目不存在")
    if not is_project_archived(meta):
        return meta
    try:
        return restore_project_record(project_id)
    except FileExistsError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


def _generate_archive_snapshot(meta: dict[str, Any]) -> dict[str, Any] | None:
    current = current_project_drawing(meta)
    if not current:
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
        dest_html = snapshot_dir / src_html.name
        try:
            shutil.copy2(src_html, dest_html)
            snapshot["archived_html_path"] = str(dest_html)
        except OSError:
            pass
    meta["archive_snapshot"] = snapshot
    save_project(meta)
    return meta


async def _refresh_outdated_drawing(meta: dict[str, Any]) -> dict[str, Any] | None:
    """已弃用：恢复时自动 reparse 会因主图选择不稳定而破坏原始解析结果。
    现在恢复=纯目录还原，semantic.json 不动。"""
    return None


@router.get("/projects/{project_id}/export")
async def export_project(
    project_id: str,
    drawing_id: str | None = None,
    include_all_drawings: bool = False,
) -> JSONResponse:
    assert_project_allowed(project_id)
    meta = load_project(project_id, include_archived=True)
    if not meta:
        raise HTTPException(status_code=404, detail="项目不存在")
    drawings = meta.get("drawings", [])
    current = current_project_drawing(meta)
    current_id = meta.get("current_drawing_id")
    selected = next((drawing for drawing in drawings if drawing.get("id") == drawing_id), None) if drawing_id else current
    if drawing_id and selected is None:
        raise HTTPException(status_code=404, detail="指定图纸不存在")
    if selected and not include_all_drawings:
        semantic_path = resolve_semantic_path(meta, selected)
        semantic = read_json(semantic_path, None) if semantic_path else None
        if semantic is None:
            raise HTTPException(status_code=404, detail="图纸语义数据不存在")
        attach_project_export_meta(semantic, meta, selected)
        save_project(meta)
        return JSONResponse(semantic)

    exported = []
    for drawing in drawings:
        semantic_path = resolve_semantic_path(meta, drawing)
        if semantic_path:
            semantic = read_json(semantic_path, None)
            if semantic is not None:
                attach_project_export_meta(semantic, meta, drawing)
                exported.append(semantic)
    save_project(meta)
    if current_id:
        exported.sort(key=lambda item: 0 if item.get("project", {}).get("drawing_id") == current_id else 1)
    return JSONResponse({"project": meta, "current_drawing_id": current_id, "drawings": exported})


@router.post("/projects/{project_id}/export-static")
async def export_project_static(project_id: str, payload: StaticExportCreate | None = None) -> dict[str, Any]:
    assert_project_allowed(project_id)
    meta = load_project(project_id, include_archived=True)
    if not meta:
        raise HTTPException(status_code=404, detail="项目不存在")
    ensure_project_active(meta)
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
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"静态导出失败: {exc}") from exc


@router.get("/projects/{project_id}/share-link")
async def project_share_link(project_id: str, request: Request, drawing_id: str | None = None) -> dict[str, Any]:
    assert_project_allowed(project_id)
    meta = load_project(project_id, include_archived=True)
    if not meta:
        raise HTTPException(status_code=404, detail="项目不存在")
    ensure_project_active(meta)
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
        params = {"project": project_id}
        if selected_drawing_id:
            params["drawing"] = str(selected_drawing_id)
        return {
            "url": f"{origin}{result['url']}",
            "app_url": f"{origin}/?{urlencode(params)}",
            "origin": origin,
            "project_id": project_id,
            "drawing_id": str(selected_drawing_id) if selected_drawing_id else None,
            "size_bytes": export_path.stat().st_size,
            "file_name": result.get("file_name"),
            "path": result.get("path"),
        }
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"分享链接生成失败: {exc}") from exc


@router.post("/projects/{project_id}/open-folder")
async def open_project_folder(project_id: str) -> dict[str, Any]:
    assert_project_allowed(project_id)
    meta = load_project(project_id, include_archived=True)
    if not meta:
        raise HTTPException(status_code=404, detail="项目不存在")
    folder = Path(str(meta.get("save_dir") or "")).expanduser()
    if not folder.exists() or not folder.is_dir():
        raise HTTPException(status_code=404, detail=f"项目目录不存在: {folder}")
    open_local_path(folder)
    return {"opened": True, "path": str(folder), "kind": "folder"}


@router.post("/projects/{project_id}/open-source-file")
async def open_project_source_file(project_id: str, payload: LocalOpenRequest | None = None) -> dict[str, Any]:
    assert_project_allowed(project_id)
    meta = load_project(project_id, include_archived=True)
    if not meta:
        raise HTTPException(status_code=404, detail="项目不存在")
    drawing = selected_project_drawing(meta, payload.drawing_id if payload else None)
    if not drawing:
        raise HTTPException(status_code=404, detail="当前项目没有可打开的图纸")
    source_path = resolve_drawing_source_path(meta, drawing)
    if not source_path or not source_path.exists():
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
    drawings = meta.get("drawings", [])
    current_id = meta.get("current_drawing_id")
    current = next((drawing for drawing in drawings if drawing.get("id") == current_id), None)
    if current is None and drawings:
        current = sorted(drawings, key=lambda item: item.get("parsed_at", ""), reverse=True)[0]
        meta["current_drawing_id"] = current.get("id")
    return current


def resolve_drawing_source_path(meta: dict[str, Any], drawing: dict[str, Any]) -> Path | None:
    direct_keys = ("source_path", "uploaded_path", "original_path", "dwg_path")
    for key in direct_keys:
        path = resolve_project_relative_path(meta, drawing.get(key))
        if path and path.exists():
            return path

    dxf_path = resolve_project_relative_path(meta, drawing.get("dxf_path"))
    if not dxf_path:
        return None

    if dxf_path.exists() and dxf_path.parent.name.lower() == "converted":
        upload_dir = dxf_path.parent.parent
        original = first_existing_source_file(upload_dir, exclude={dxf_path.resolve()})
        if original:
            return original

    if dxf_path.exists():
        return dxf_path
    return None


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


def resolve_project_relative_path(meta: dict[str, Any], value: Any) -> Path | None:
    if not value:
        return None
    path = Path(str(value)).expanduser()
    if path.is_absolute():
        return path
    roots = [
        Path(str(meta.get("save_dir") or "")).expanduser(),
        Path(str(meta.get("package_dir") or "")).expanduser(),
        project_storage_dir(meta),
    ]
    for root in roots:
        if not str(root):
            continue
        candidate = root / path
        if candidate.exists():
            return candidate
    return roots[0] / path if roots and str(roots[0]) else path


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
    semantic.setdefault("site_profiles", meta.get("site_profiles") or semantic.get("site_profiles") or ["express"])
    model_bindings = load_project_model_bindings(meta)
    semantic["project"] = {
        "id": meta["id"],
        "name": meta["name"],
        "save_dir": meta["save_dir"],
        "status": meta.get("status", "active"),
        "site_profiles": semantic.get("site_profiles") or ["express"],
        "drawing_id": drawing.get("id"),
        "current_drawing_id": meta.get("current_drawing_id"),
        "drawings": meta.get("drawings", []),
        "model_bindings": model_bindings,
        "model_binding_path": meta.get("model_binding_path"),
        "model_bindings_locked": bool(meta.get("model_bindings_locked") or model_bindings),
        "model_binding_updated_at": meta.get("model_binding_updated_at"),
    }


def load_project_model_bindings(meta: dict[str, Any]) -> dict[str, Any]:
    binding_value = meta.get("model_binding_path")
    candidates: list[Path] = []
    if binding_value:
        binding_path = Path(str(binding_value))
        if binding_path.is_absolute():
            candidates.append(binding_path)
        package_dir = meta.get("package_dir")
        if package_dir:
            candidates.append(Path(package_dir) / binding_path)
        save_dir = meta.get("save_dir")
        if save_dir:
            candidates.append(Path(save_dir) / binding_path)
    save_dir = meta.get("save_dir")
    if save_dir:
        candidates.append(Path(save_dir) / "model-overrides" / "model-bindings.json")
    candidates.append(project_storage_dir(meta) / "model-overrides" / "model-bindings.json")
    for candidate in candidates:
        if candidate.exists():
            data = read_json(candidate, {})
            if isinstance(data, dict):
                return data
    return {}
