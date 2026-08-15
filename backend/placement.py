"""Placement studio: catalog, default site, and override merge."""

from __future__ import annotations

import uuid
from copy import deepcopy
from pathlib import Path
from typing import Any

import yaml

from storage import now_iso, project_storage_dir, read_json, save_project, write_json

CATALOG_PATH = Path(__file__).resolve().parent / "config" / "model-catalog.yaml"
OVERRIDES_NAME = "model-overrides.json"
SCHEMA_VERSION = "1.1.11"


def load_catalog() -> dict[str, Any]:
    data = yaml.safe_load(CATALOG_PATH.read_text(encoding="utf-8")) or {}
    items = list(data.get("items") or [])
    return {
        "version": str(data.get("version") or "1.0"),
        "site_defaults": dict(data.get("site_defaults") or {}),
        "groups": list(data.get("groups") or []),
        "items": items,
        "by_id": {str(item.get("id")): item for item in items if item.get("id")},
    }


def overrides_path(meta: dict[str, Any]) -> Path:
    return project_storage_dir(meta) / "model-overrides" / OVERRIDES_NAME


def empty_overrides() -> dict[str, Any]:
    return {"version": 1, "site": {}, "instances": [], "circuits": []}


def load_overrides(meta: dict[str, Any]) -> dict[str, Any]:
    data = read_json(overrides_path(meta), empty_overrides())
    if not isinstance(data, dict):
        return empty_overrides()
    data.setdefault("version", 1)
    data.setdefault("site", {})
    data.setdefault("instances", [])
    data.setdefault("circuits", [])
    return data


def save_overrides(meta: dict[str, Any], payload: dict[str, Any]) -> dict[str, Any]:
    data = {
        "version": 1,
        "site": dict(payload.get("site") or {}),
        "instances": list(payload.get("instances") or []),
        "circuits": list(payload.get("circuits") or []),
    }
    write_json(overrides_path(meta), data)
    return data


def _site_box_mm(catalog: dict[str, Any], overrides: dict[str, Any]) -> tuple[float, float, float]:
    defaults = catalog.get("site_defaults") or {}
    site = overrides.get("site") or {}
    length_m = float(site.get("length_m") or defaults.get("length_m") or 80)
    width_m = float(site.get("width_m") or defaults.get("width_m") or 50)
    wall_h = float(site.get("wall_height_m") or defaults.get("wall_height_m") or 10.5)
    return length_m * 1000.0, width_m * 1000.0, wall_h


def default_semantic(meta: dict[str, Any], catalog: dict[str, Any] | None = None) -> dict[str, Any]:
    catalog = catalog or load_catalog()
    defaults = catalog.get("site_defaults") or {}
    length_mm, width_mm, wall_h = _site_box_mm(catalog, empty_overrides())
    half_x, half_y = length_mm / 2.0, width_mm / 2.0
    points = [
        {"x": -half_x, "y": -half_y},
        {"x": half_x, "y": -half_y},
        {"x": half_x, "y": half_y},
        {"x": -half_x, "y": half_y},
    ]
    return {
        "schema_version": SCHEMA_VERSION,
        "site_profiles": meta.get("site_profiles") or ["generic"],
        "drawing_meta": {
            "name": "摆放场景",
            "source": "placement_studio",
            "modelspace_scale_to_mm": 1.0,
            "modelspace_scale_source": "placement_default",
        },
        "site": {
            "site_type": "generic",
            "site_profiles": meta.get("site_profiles") or ["generic"],
            "dock_height_m": float(defaults.get("dock_height_m") or 1.2),
            "warehouse_floor_height_m": float(defaults.get("dock_height_m") or 1.2),
            "warehouse_wall_height_m": float(defaults.get("wall_height_m") or 10.5),
            "warehouse_roof_peak_height_m": float(defaults.get("roof_peak_height_m") or 12.6),
            "source": "placement_studio",
        },
        "stats": {},
        "devices": [],
        "cables": [],
        "structures": [],
        "areas": [
            {
                "id": "place_shell",
                "type": "area.warehouse.shell",
                "label": "试验场地",
                "geometry": {"type": "polygon", "closed": True, "points": points},
                "attributes": {"height_m": wall_h, "source": "placement_default"},
            }
        ],
        "office_objects": [],
        "parking_spaces": [],
        "fixtures": [],
        "annotations": [],
        "quality": {"warnings": []},
    }


def _instance_entity(item: dict[str, Any], catalog_item: dict[str, Any]) -> dict[str, Any]:
    attrs = {
        "catalog_id": catalog_item.get("id") or item.get("catalog_id"),
        "placement": True,
        "source_kind": "placement_studio",
        "mount": item.get("attributes", {}).get("mount") or catalog_item.get("mount"),
        "zone": item.get("attributes", {}).get("zone") or catalog_item.get("zone"),
        "install_height_m": item.get("attributes", {}).get("install_height_m", catalog_item.get("install_height_m")),
        "role": item.get("attributes", {}).get("role") or catalog_item.get("role"),
        "rack_units": item.get("attributes", {}).get("rack_units") or catalog_item.get("rack_units"),
        "top_edge_height_m": item.get("attributes", {}).get("top_edge_height_m") or catalog_item.get("top_edge_height_m"),
        "beam_length_m": catalog_item.get("beam_length_m"),
        "beam_angle_deg": catalog_item.get("beam_angle_deg"),
        "purpose": "placement",
    }
    user_attrs = item.get("attributes") or {}
    attrs.update({key: value for key, value in user_attrs.items() if value is not None})
    entity = {
        "id": item.get("id") or f"place_{uuid.uuid4().hex[:8]}",
        "type": item.get("type") or catalog_item.get("type"),
        "label": item.get("label") or catalog_item.get("label"),
        "confidence": 1.0,
        "geometry": deepcopy(item.get("geometry") or {}),
        "orientation": deepcopy(item.get("orientation") or {"angle_deg": 0}),
        "attributes": attrs,
    }
    coverage = item.get("coverage")
    if isinstance(coverage, dict) and coverage:
        entity["coverage"] = deepcopy(coverage)
    return entity


def merge_overrides(base: dict[str, Any], overrides: dict[str, Any], catalog: dict[str, Any] | None = None) -> dict[str, Any]:
    catalog = catalog or load_catalog()
    semantic = deepcopy(base)
    by_id = catalog.get("by_id") or {}
    devices: list[dict[str, Any]] = []
    fixtures: list[dict[str, Any]] = []
    cables: list[dict[str, Any]] = []
    offices: list[dict[str, Any]] = []
    parking: list[dict[str, Any]] = []
    structures: list[dict[str, Any]] = []
    for item in overrides.get("instances") or []:
        catalog_item = by_id.get(str(item.get("catalog_id") or "")) or {}
        kind = item.get("kind") or catalog_item.get("kind") or "device"
        entity = _instance_entity(item, catalog_item)
        if kind == "fixture":
            fixtures.append(entity)
        elif kind == "cable":
            cables.append(entity)
        elif kind == "office":
            offices.append(entity)
        elif kind == "parking":
            parking.append(entity)
        elif kind == "structure":
            structures.append(entity)
        else:
            devices.append(entity)

    length_mm, width_mm, wall_h = _site_box_mm(catalog, overrides)
    half_x, half_y = length_mm / 2.0, width_mm / 2.0
    semantic["areas"] = [
        {
            "id": "place_shell",
            "type": "area.warehouse.shell",
            "label": "试验场地",
            "geometry": {
                "type": "polygon",
                "closed": True,
                "points": [
                    {"x": -half_x, "y": -half_y},
                    {"x": half_x, "y": -half_y},
                    {"x": half_x, "y": half_y},
                    {"x": -half_x, "y": half_y},
                ],
            },
            "attributes": {"height_m": wall_h, "source": "placement_default"},
        }
    ]
    site = semantic.setdefault("site", {})
    site["warehouse_wall_height_m"] = wall_h
    if overrides.get("site", {}).get("length_m"):
        site["placement_length_m"] = overrides["site"]["length_m"]
    if overrides.get("site", {}).get("width_m"):
        site["placement_width_m"] = overrides["site"]["width_m"]

    semantic["devices"] = devices
    semantic["fixtures"] = fixtures
    semantic["cables"] = cables
    semantic["office_objects"] = offices
    semantic["parking_spaces"] = parking
    semantic["structures"] = structures
    semantic["stats"] = {
        "devices": len(devices),
        "fixtures": len(fixtures),
        "cables": len(cables),
        "office_objects": len(offices),
        "parking_spaces": len(parking),
        "structures": len(structures),
        "areas": 1,
    }
    return semantic


def apply_standard_heights(overrides: dict[str, Any], catalog: dict[str, Any] | None = None) -> dict[str, Any]:
    catalog = catalog or load_catalog()
    by_id = catalog.get("by_id") or {}
    for item in overrides.get("instances") or []:
        catalog_item = by_id.get(str(item.get("catalog_id") or "")) or {}
        if catalog_item.get("install_height_m") is None:
            continue
        attrs = dict(item.get("attributes") or {})
        attrs["install_height_m"] = catalog_item.get("install_height_m")
        if catalog_item.get("top_edge_height_m") is not None:
            attrs["top_edge_height_m"] = catalog_item.get("top_edge_height_m")
        item["attributes"] = attrs
    return overrides


def is_placement_project(meta: dict[str, Any] | None) -> bool:
    if not meta:
        return False
    if meta.get("placement_studio"):
        return True
    return "摆放试验场" in str(meta.get("name") or "")


def ensure_placement_scene(meta: dict[str, Any]) -> dict[str, Any]:
    if not is_placement_project(meta):
        return meta
    catalog = load_catalog()
    drawings = list(meta.get("drawings") or [])
    if not drawings:
        draw_id = f"draw_{uuid.uuid4().hex[:10]}"
        semantic_dir = project_storage_dir(meta) / draw_id
        semantic_dir.mkdir(parents=True, exist_ok=True)
        semantic_path = semantic_dir / "semantic.json"
        write_json(semantic_path, default_semantic(meta, catalog))
        drawing = {
            "id": draw_id,
            "name": "摆放场景",
            "semantic_path": str(semantic_path),
            "parsed_at": now_iso(),
            "site_profiles": meta.get("site_profiles") or ["generic"],
            "placement_studio": True,
        }
        meta["drawings"] = [drawing]
        meta["current_drawing_id"] = draw_id
    meta["placement_studio"] = True
    meta["updated_at"] = now_iso()
    save_project(meta)

    current_id = meta.get("current_drawing_id")
    drawing = next((item for item in meta.get("drawings") or [] if item.get("id") == current_id), None)
    if drawing is None:
        drawing = (meta.get("drawings") or [None])[0]
    if not drawing:
        return meta
    semantic_path = Path(drawing.get("semantic_path") or project_storage_dir(meta) / drawing["id"] / "semantic.json")
    base = read_json(semantic_path, None) or default_semantic(meta, catalog)
    studio = bool(drawing.get("placement_studio") or (base.get("drawing_meta") or {}).get("source") == "placement_studio")
    if studio:
        merged = merge_overrides(default_semantic(meta, catalog), load_overrides(meta), catalog)
        write_json(semantic_path, merged)
        drawing["semantic_path"] = str(semantic_path)
        drawing["placement_studio"] = True
        save_project(meta)
    return meta
