"""Placement studio: catalog, default site, and override merge.

人工摆放结果与规则推断结果分开存储：本模块只处理「人工 overrides」，
解析生成的 semantic.json 由规则引擎负责。重新解析不会清空 overrides。
"""

from __future__ import annotations

import uuid
from copy import deepcopy
from math import isfinite
from pathlib import Path
from typing import Any

import yaml

from path_policy import PathPolicyError, is_safe_id, resolve_within_roots
from storage import (
    allowed_roots_for_meta,
    file_lock,
    now_iso,
    project_storage_dir,
    read_json,
    read_json_strict,
    save_project,
    write_json,
)

CATALOG_PATH = Path(__file__).resolve().parent / "config" / "model-catalog.yaml"
OVERRIDES_NAME = "model-overrides.json"
SCHEMA_VERSION = "1.1.11"

#: 摆放试验场的**通用占位值**：仅在没有任何场地数值配置时用于生成试验场地壳，
#: 不代表任何真实场地取值。真实数值应由本机私有配置（site_values）提供。
PLACEHOLDER_WALL_HEIGHT_M = 6.0
PLACEHOLDER_ROOF_PEAK_HEIGHT_M = 7.0
PLACEHOLDER_DOCK_HEIGHT_M = 1.2
SITE_VALUE_KEYS = {
    "wall_height_m": "warehouse_wall_height_m",
    "roof_peak_height_m": "warehouse_roof_peak_height_m",
    "dock_height_m": "dock_height_m",
}


def _site_number(defaults: dict, key: str, placeholder: float) -> tuple[float, str]:
    """场地数值优先级：本机私有配置 > 调用方传入 > 通用占位值。

    第二项是来源标记，便于前端与审计区分"真实配置"与"占位"。
    """
    from semantic.site_adaptations import load_site_adaptations

    configured = load_site_adaptations().value(SITE_VALUE_KEYS.get(key, key))
    if configured is not None:
        return float(configured), "private_config"
    raw = defaults.get(key)
    if raw is not None:
        return float(raw), "catalog"
    return float(placeholder), "placeholder_default"

#: override 实例允许的类型分类。
INSTANCE_KINDS = {"device", "fixture", "cable", "office", "parking", "structure"}
#: 线路端点数量下限/上限，防止畸形数据进入渲染层。
MIN_CIRCUIT_POINTS = 2
MAX_CIRCUIT_POINTS = 512
MAX_INSTANCES = 5000


class OverrideValidationError(ValueError):
    """人工 overrides 未通过校验。`detail` 指出具体字段。"""

    def __init__(self, detail: str) -> None:
        super().__init__(f"人工覆盖数据非法: {detail}")
        self.detail = detail


class RevisionConflict(RuntimeError):
    """乐观并发冲突：调用方持有旧 revision。"""

    def __init__(self, expected: Any, actual: Any) -> None:
        self.expected = expected
        self.actual = actual
        super().__init__(f"摆放数据已被其他会话修改（期望 revision={expected!r}，当前 revision={actual!r}），请刷新后重试")


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
    return {"version": 1, "revision": 0, "site": {}, "instances": [], "circuits": []}


def load_overrides(meta: dict[str, Any]) -> dict[str, Any]:
    path = overrides_path(meta)
    if not path.exists():
        return empty_overrides()
    # 损坏时明确报错（read_json_strict 会先隔离原文件），不能静默当空数据。
    data = read_json_strict(path, None)
    if not isinstance(data, dict):
        return empty_overrides()
    data.setdefault("version", 1)
    data.setdefault("revision", 0)
    data.setdefault("site", {})
    data.setdefault("instances", [])
    data.setdefault("circuits", [])
    return data


def save_overrides(meta: dict[str, Any], payload: dict[str, Any], *, expected_revision: Any = None) -> dict[str, Any]:
    """保存人工 overrides。

    - 写入前做严格校验（实例 ID、类型、有限数值、尺寸、线路端点）。
    - 原子写入，且整个「读旧 revision -> 校验 -> 写」在文件锁内完成。
    - 传入 expected_revision 时做乐观并发校验，旧版本保存抛 RevisionConflict。
    """
    path = overrides_path(meta)
    normalized = validate_overrides(payload)
    with file_lock(path):
        current = read_json(path, None)
        current_revision = _normalize_revision((current or {}).get("revision") if isinstance(current, dict) else None)
        if expected_revision is not None:
            wanted = _normalize_revision(expected_revision)
            if current is not None and wanted != current_revision:
                raise RevisionConflict(wanted, current_revision)
        normalized["revision"] = current_revision + 1
        write_json(path, normalized)
    return normalized


def _normalize_revision(value: Any) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def validate_overrides(payload: dict[str, Any]) -> dict[str, Any]:
    """严格校验人工覆盖数据结构，拒绝 NaN/无穷/非法 ID/无效线路端点。"""
    if not isinstance(payload, dict):
        raise OverrideValidationError("根节点必须是对象")
    site = payload.get("site") or {}
    if not isinstance(site, dict):
        raise OverrideValidationError("site 必须是对象")
    clean_site = _validate_site(site)

    instances_raw = payload.get("instances") or []
    if not isinstance(instances_raw, list):
        raise OverrideValidationError("instances 必须是数组")
    if len(instances_raw) > MAX_INSTANCES:
        raise OverrideValidationError(f"instances 数量超限（{len(instances_raw)} > {MAX_INSTANCES}）")
    instances = [_validate_instance(item, index) for index, item in enumerate(instances_raw)]

    circuits_raw = payload.get("circuits") or []
    if not isinstance(circuits_raw, list):
        raise OverrideValidationError("circuits 必须是数组")
    circuits = [_validate_circuit(item, index) for index, item in enumerate(circuits_raw)]

    return {"version": 1, "site": clean_site, "instances": instances, "circuits": circuits}


def _validate_site(site: dict[str, Any]) -> dict[str, Any]:
    clean: dict[str, Any] = {}
    numeric_fields = {"length_m", "width_m", "wall_height_m", "dock_height_m", "roof_peak_height_m"}
    for key, value in site.items():
        if not isinstance(key, str) or len(key) > 64:
            raise OverrideValidationError("site 含非法键")
        if key in numeric_fields:
            clean[key] = _finite_number(value, f"site.{key}", minimum=0.0)
        elif isinstance(value, (str, bool, int, float)) or value is None:
            clean[key] = value
        else:
            raise OverrideValidationError(f"site.{key} 类型非法")
    return clean


def _validate_instance(item: Any, index: int) -> dict[str, Any]:
    if not isinstance(item, dict):
        raise OverrideValidationError(f"instances[{index}] 必须是对象")
    instance_id = item.get("id")
    if not is_safe_id(instance_id):
        raise OverrideValidationError(
            f"instances[{index}].id 非法：只允许字母、数字、下划线和连字符（1-64 字符），"
            "不能包含路径分隔符或上级引用"
        )
    catalog_id = item.get("catalog_id")
    if catalog_id is not None and (not isinstance(catalog_id, str) or len(catalog_id) > 120):
        raise OverrideValidationError(f"instances[{index}].catalog_id 非法")
    kind = item.get("kind")
    if kind is not None and str(kind) not in INSTANCE_KINDS:
        raise OverrideValidationError(f"instances[{index}].kind 非法: {kind}（可用: {', '.join(sorted(INSTANCE_KINDS))}）")
    instance_type = item.get("type")
    if instance_type is not None and (not isinstance(instance_type, str) or len(instance_type) > 120):
        raise OverrideValidationError(f"instances[{index}].type 非法")

    clean: dict[str, Any] = {
        "id": instance_id.strip(),
        "catalog_id": catalog_id,
        "kind": str(kind) if kind is not None else None,
        "type": instance_type,
        "label": item.get("label") if isinstance(item.get("label"), str) else None,
    }
    geometry = item.get("geometry")
    if geometry is not None:
        clean["geometry"] = _validate_geometry(geometry, f"instances[{index}].geometry")
    orientation = item.get("orientation")
    if orientation is not None:
        clean["orientation"] = _validate_orientation(orientation, f"instances[{index}].orientation")
    attributes = item.get("attributes")
    if attributes is not None:
        clean["attributes"] = _validate_attributes(attributes, f"instances[{index}].attributes")
    coverage = item.get("coverage")
    if isinstance(coverage, dict):
        clean["coverage"] = _validate_attributes(coverage, f"instances[{index}].coverage")
    return {key: value for key, value in clean.items() if value is not None}


def _validate_geometry(geometry: Any, field: str) -> dict[str, Any]:
    if not isinstance(geometry, dict):
        raise OverrideValidationError(f"{field} 必须是对象")
    geometry_type = str(geometry.get("type") or "").strip().lower()
    result: dict[str, Any] = {"type": geometry.get("type")}
    if geometry_type in {"point", "circle"}:
        position = geometry.get("position") or geometry.get("center")
        result["position"] = _validate_point(position, f"{field}.position")
        if geometry_type == "circle":
            if geometry.get("radius") is not None:
                result["radius"] = _finite_number(geometry["radius"], f"{field}.radius", minimum=0.0)
    elif geometry_type in {"linestring", "polygon", "polyline"}:
        points = geometry.get("points")
        if not isinstance(points, list) or len(points) < 2:
            raise OverrideValidationError(f"{field}.points 至少需要 2 个点")
        if len(points) > MAX_CIRCUIT_POINTS:
            raise OverrideValidationError(f"{field}.points 超限（{len(points)} > {MAX_CIRCUIT_POINTS}）")
        result["points"] = [_validate_point(point, f"{field}.points[{index}]") for index, point in enumerate(points)]
        result["closed"] = bool(geometry.get("closed"))
    else:
        # 未知类型：只保留有限数值字段，避免畸形数据进入渲染层
        for key, value in geometry.items():
            if isinstance(value, (int, float)) and not isinstance(value, bool):
                result[key] = _finite_number(value, f"{field}.{key}")
    return result


def _validate_point(point: Any, field: str) -> dict[str, float]:
    if not isinstance(point, dict):
        raise OverrideValidationError(f"{field} 必须是 {{x, y}} 对象")
    return {
        "x": _finite_number(point.get("x"), f"{field}.x"),
        "y": _finite_number(point.get("y"), f"{field}.y"),
    }


def _validate_orientation(orientation: Any, field: str) -> dict[str, Any]:
    if not isinstance(orientation, dict):
        raise OverrideValidationError(f"{field} 必须是对象")
    result: dict[str, Any] = {}
    if orientation.get("angle_deg") is not None:
        result["angle_deg"] = _finite_number(orientation["angle_deg"], f"{field}.angle_deg")
    for key in ("direction", "facing"):
        if isinstance(orientation.get(key), str):
            result[key] = orientation[key]
    return result


def _validate_attributes(attributes: Any, field: str) -> dict[str, Any]:
    if not isinstance(attributes, dict):
        raise OverrideValidationError(f"{field} 必须是对象")
    clean: dict[str, Any] = {}
    for key, value in attributes.items():
        if not isinstance(key, str) or len(key) > 64:
            raise OverrideValidationError(f"{field} 含非法键")
        if value is None or isinstance(value, (str, bool)):
            clean[key] = value
        elif isinstance(value, (int, float)):
            clean[key] = _finite_number(value, f"{field}.{key}")
        elif isinstance(value, dict):
            clean[key] = _validate_attributes(value, f"{field}.{key}")
        else:
            raise OverrideValidationError(f"{field}.{key} 类型非法")
    return clean


def _validate_circuit(item: Any, index: int) -> dict[str, Any]:
    if not isinstance(item, dict):
        raise OverrideValidationError(f"circuits[{index}] 必须是对象")
    circuit_id = item.get("id")
    if circuit_id is not None and not is_safe_id(circuit_id):
        raise OverrideValidationError(f"circuits[{index}].id 非法")
    points = item.get("points")
    if points is None:
        geometry = item.get("geometry") or {}
        points = geometry.get("points") if isinstance(geometry, dict) else None
    if not isinstance(points, list) or len(points) < MIN_CIRCUIT_POINTS:
        raise OverrideValidationError(f"circuits[{index}] 至少需要 {MIN_CIRCUIT_POINTS} 个端点")
    if len(points) > MAX_CIRCUIT_POINTS:
        raise OverrideValidationError(f"circuits[{index}].points 超限（{len(points)} > {MAX_CIRCUIT_POINTS}）")
    return {
        "id": circuit_id,
        "points": [_validate_point(point, f"circuits[{index}].points[{point_index}]") for point_index, point in enumerate(points)],
        "label": item.get("label") if isinstance(item.get("label"), str) else None,
    }


def _finite_number(value: Any, field: str, *, minimum: float | None = None) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise OverrideValidationError(f"{field} 必须是数字")
    numeric = float(value)
    if not isfinite(numeric):
        raise OverrideValidationError(f"{field} 必须是有限数字（不允许 NaN/Infinity）")
    if minimum is not None and numeric < minimum:
        raise OverrideValidationError(f"{field} 不能小于 {minimum}")
    return numeric


def _site_box_mm(catalog: dict[str, Any], overrides: dict[str, Any]) -> tuple[float, float, float]:
    defaults = catalog.get("site_defaults") or {}
    site = overrides.get("site") or {}
    length_m = float(site.get("length_m") or defaults.get("length_m") or 80)
    width_m = float(site.get("width_m") or defaults.get("width_m") or 50)
    wall_h, _source = _site_number({**defaults, **site}, "wall_height_m", PLACEHOLDER_WALL_HEIGHT_M)
    return length_m * 1000.0, width_m * 1000.0, wall_h


def _placement_site_attrs(defaults: dict[str, Any]) -> dict[str, Any]:
    dock, dock_source = _site_number(defaults, "dock_height_m", PLACEHOLDER_DOCK_HEIGHT_M)
    wall, wall_source = _site_number(defaults, "wall_height_m", PLACEHOLDER_WALL_HEIGHT_M)
    peak, peak_source = _site_number(defaults, "roof_peak_height_m", PLACEHOLDER_ROOF_PEAK_HEIGHT_M)
    return {
        "dock_height_m": dock,
        "warehouse_floor_height_m": dock,
        "warehouse_wall_height_m": wall,
        "warehouse_roof_peak_height_m": peak,
        "height_source": {
            "dock_height_m": dock_source,
            "warehouse_wall_height_m": wall_source,
            "warehouse_roof_peak_height_m": peak_source,
        },
    }


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
            **_placement_site_attrs(defaults),
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
        try:
            overrides = validate_overrides(load_overrides(meta))
        except OverrideValidationError:
            # 已损坏或被人工改坏的数据：保留原文件，不覆盖，仅跳过合并。
            return meta
        merged = merge_overrides(default_semantic(meta, catalog), overrides, catalog)
        merged["revision"] = overrides.get("revision", 0)
        write_json(semantic_path, merged)
        drawing["semantic_path"] = str(semantic_path)
        drawing["placement_studio"] = True
        save_project(meta)
    return meta
