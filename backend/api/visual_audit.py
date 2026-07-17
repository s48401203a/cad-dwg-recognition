from __future__ import annotations

from pathlib import Path
import os
from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from api.projects import resolve_semantic_path
from capture.dxf_region_renderer import capture_dxf_region
from storage import load_project, now_iso, read_json, write_json

router = APIRouter()
ROOT_DIR = Path(__file__).resolve().parents[2]
_exports_root = Path(os.environ["CAD_EXPORTS_DIR"]).expanduser() if os.environ.get("CAD_EXPORTS_DIR") else ROOT_DIR / "exports"
VISUAL_AUDIT_DIR = Path(os.environ["CAD_VISUAL_AUDIT_DIR"]).expanduser() if os.environ.get("CAD_VISUAL_AUDIT_DIR") else _exports_root / "visual-audit"


class VisualAuditCaptureRequest(BaseModel):
    drawing_id: str | None = None
    module_kinds: list[str] | None = None
    force: bool = False


@router.post("/projects/{project_id}/visual-audit/capture")
async def capture_visual_audit(project_id: str, payload: VisualAuditCaptureRequest | None = None) -> dict[str, Any]:
    meta = load_project(project_id)
    if not meta:
        raise HTTPException(status_code=404, detail="项目不存在")
    selected_drawing_id = (payload.drawing_id if payload else None) or meta.get("current_drawing_id")
    drawing = next((item for item in meta.get("drawings", []) if item.get("id") == selected_drawing_id), None)
    if not drawing:
        raise HTTPException(status_code=404, detail="图纸不存在")
    dxf_path = Path(str(drawing.get("dxf_path") or ""))
    if not dxf_path.exists():
        raise HTTPException(status_code=404, detail=f"DXF 文件不存在: {dxf_path}")
    semantic_path = resolve_semantic_path(meta, drawing)
    if not semantic_path:
        raise HTTPException(status_code=404, detail="semantic.json 不存在")
    semantic = read_json(semantic_path, None)
    if not semantic:
        raise HTTPException(status_code=404, detail="semantic.json 读取失败")

    module_filter = set(payload.module_kinds or []) if payload and payload.module_kinds else None
    modules = semantic.get("quality", {}).get("system_module_analysis", {}).get("modules", [])
    output_root = VISUAL_AUDIT_DIR / project_id / str(selected_drawing_id)
    captured: list[dict[str, Any]] = []
    generated_at = now_iso()
    for module in modules:
        kind = str(module.get("kind") or "module")
        if module_filter and kind not in module_filter:
            continue
        region = module.get("screenshot_region")
        if not region:
            continue
        existing = module.get("screenshot_asset") or {}
        existing_path = Path(str(existing.get("path") or ""))
        if existing_path.exists() and not (payload and payload.force):
            captured.append(existing)
            continue
        file_name = f"{_safe_name(kind)}.png"
        output_path = output_root / file_name
        asset = capture_dxf_region(dxf_path, region, output_path)
        asset.update(
            {
                "url": f"/exports/visual-audit/{project_id}/{selected_drawing_id}/{file_name}",
                "generated_at": generated_at,
                "module_kind": kind,
                "module_label": module.get("label"),
            }
        )
        module["screenshot_asset"] = asset
        captured.append(asset)

    manifest = {
        "project_id": project_id,
        "drawing_id": selected_drawing_id,
        "generated_at": generated_at,
        "captured": captured,
    }
    write_json(output_root / "manifest.json", manifest)
    _update_visual_audit_items(semantic, captured)
    write_json(semantic_path, semantic)
    return {
        "project_id": project_id,
        "drawing_id": selected_drawing_id,
        "captured": captured,
        "semantic_path": str(semantic_path),
        "manifest_path": str(output_root / "manifest.json"),
    }


def _update_visual_audit_items(semantic: dict[str, Any], captured: list[dict[str, Any]]) -> None:
    asset_by_kind = {str(asset.get("module_kind")): asset for asset in captured if asset.get("module_kind")}
    visual = semantic.setdefault("quality", {}).setdefault("visual_audit", {})
    items = visual.setdefault("items", [])
    for item in items:
        if item.get("category") != "system_module_screenshot":
            continue
        kind = str(item.get("source_key") or "")
        asset = asset_by_kind.get(kind)
        if not asset:
            continue
        item["status"] = "captured"
        item["screenshot_asset"] = asset
        item["reason"] = "已生成 CAD 模块截图，待视觉核验"
    visual["requires_screenshot_capture"] = any(
        item.get("category") == "system_module_screenshot" and item.get("status") != "captured"
        for item in items
    )
    visual["item_count"] = len(items)
    visual["status"] = "pending" if items else "ok"


def _safe_name(value: str) -> str:
    return "".join(ch if ch.isalnum() or ch in {"-", "_"} else "_" for ch in value)[:60] or "module"
