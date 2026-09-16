from __future__ import annotations

from pathlib import Path
import os
from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from api.projects import current_project_drawing, load_project_or_404, require_valid_drawing_id, resolve_drawing_dxf_path, resolve_semantic_path
from capture.dxf_region_renderer import capture_dxf_region
from path_policy import PathPolicyError, resolve_within_roots
from storage import now_iso, read_json, read_json_strict, write_json

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
    from capabilities import capability

    info = capability("visual_audit")
    if not info.get("available"):
        raise HTTPException(
            status_code=503,
            detail=f"视觉审计截图不可用：{info.get('reason') or '未安装截图依赖'}",
            headers={"X-CAD-Capability": "visual_audit"},
        )
    meta = load_project_or_404(project_id)
    drawing_id = payload.drawing_id if payload else None
    if drawing_id:
        require_valid_drawing_id(drawing_id)
    drawing = current_project_drawing(meta) if not drawing_id else next(
        (item for item in meta.get("drawings", []) if isinstance(item, dict) and item.get("id") == drawing_id), None
    )
    if not drawing:
        raise HTTPException(status_code=404, detail="图纸不存在")
    selected_drawing_id = str(drawing.get("id") or "")

    dxf_path = resolve_drawing_dxf_path(meta, drawing)
    if not dxf_path:
        raise HTTPException(status_code=404, detail="图纸缺少可用的 DXF 文件")
    semantic_path = resolve_semantic_path(meta, drawing)
    if not semantic_path:
        raise HTTPException(status_code=404, detail="semantic.json 不存在")
    semantic = read_semantic_or_400(semantic_path)

    module_filter = set(payload.module_kinds or []) if payload and payload.module_kinds else None
    modules = semantic.get("quality", {}).get("system_module_analysis", {}).get("modules", [])
    try:
        output_root = resolve_within_roots(
            VISUAL_AUDIT_DIR / str(meta["id"]) / selected_drawing_id,
            [VISUAL_AUDIT_DIR],
            label="视觉审计输出目录",
        )
    except PathPolicyError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
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
        try:
            existing_ok = existing_path.exists() and resolve_within_roots(existing_path, [VISUAL_AUDIT_DIR], label="截图") is not None
        except PathPolicyError:
            existing_ok = False
        if existing_ok and not (payload and payload.force):
            captured.append(existing)
            continue
        file_name = f"{_safe_name(kind)}.png"
        output_path = output_root / file_name
        asset = capture_dxf_region(dxf_path, region, output_path)
        asset.update(
            {
                "url": f"/exports/visual-audit/{meta['id']}/{selected_drawing_id}/{file_name}",
                "generated_at": generated_at,
                "module_kind": kind,
                "module_label": module.get("label"),
            }
        )
        module["screenshot_asset"] = asset
        captured.append(asset)

    manifest = {
        "project_id": meta["id"],
        "drawing_id": selected_drawing_id,
        "generated_at": generated_at,
        "captured": captured,
    }
    write_json(output_root / "manifest.json", manifest)
    _update_visual_audit_items(semantic, captured)
    write_json(semantic_path, semantic)
    return {
        "project_id": meta["id"],
        "drawing_id": selected_drawing_id,
        "captured": captured,
        "manifest_path": str(output_root / "manifest.json"),
    }


def read_semantic_or_400(path: Path) -> dict[str, Any]:
    try:
        semantic = read_json_strict(path, None)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"semantic.json 读取失败: {exc}") from exc
    if not isinstance(semantic, dict) or not semantic:
        raise HTTPException(status_code=404, detail="semantic.json 读取失败")
    return semantic


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
