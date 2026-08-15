from __future__ import annotations

from collections import Counter
from typing import Any


DEVICE_FAMILY = {
    "security.camera.fisheye": "camera",
    "security.camera.dome": "camera",
    "security.camera.bullet": "camera",
    "security.camera.rear": "camera",
    "security.camera": "camera",
    "network.ap": "network",
    "network.switch": "network",
    "network.cabinet": "network",
    "network.outlet": "network",
    "power.distribution": "power",
    "power.panel": "power",
    "lighting.fixture": "lighting",
}


def count_by(items: list[dict[str, Any]], key: str = "type") -> dict[str, int]:
    counter: Counter[str] = Counter()
    for item in items or []:
        counter[str(item.get(key) or "unknown")] += 1
    return dict(sorted(counter.items(), key=lambda pair: (-pair[1], pair[0])))


def family_counts(devices: list[dict[str, Any]]) -> dict[str, int]:
    counter: Counter[str] = Counter()
    for device in devices or []:
        device_type = str(device.get("type") or "")
        family = DEVICE_FAMILY.get(device_type)
        if family is None:
            if device_type.startswith("security.camera"):
                family = "camera"
            elif device_type.startswith("network."):
                family = "network"
            elif device_type.startswith("power."):
                family = "power"
            elif device_type.startswith("lighting."):
                family = "lighting"
            else:
                family = "other"
        counter[family] += 1
    return dict(sorted(counter.items()))


def collect_metrics(semantic: dict[str, Any]) -> dict[str, Any]:
    devices = list(semantic.get("devices") or [])
    cables = list(semantic.get("cables") or [])
    structures = list(semantic.get("structures") or [])
    areas = list(semantic.get("areas") or [])
    stats = dict(semantic.get("stats") or {})
    quality = semantic.get("quality") or {}
    warnings = list(quality.get("warnings") or [])
    inferred = list(quality.get("inferred") or [])
    checklist = list(quality.get("render_checklist") or [])
    review_needed = sum(
        1
        for item in [*devices, *cables]
        if item.get("review_needed") or float(item.get("confidence") or 1) < 0.75
    )
    inferred_cables = sum(
        1
        for cable in cables
        if "infer" in str((cable.get("attributes") or {}).get("source_kind") or cable.get("route_source") or "")
    )
    render_ready = bool(devices or structures or areas)
    return {
        "schema_version": semantic.get("schema_version"),
        "site_profiles": list(semantic.get("site_profiles") or []),
        "stats": {
            "total_entities": stats.get("total_entities"),
            "devices": len(devices),
            "cables": len(cables),
            "cable_candidates": stats.get("cable_candidates") or len(semantic.get("cable_candidates") or []),
            "structures": len(structures),
            "areas": len(areas),
            "office_objects": stats.get("office_objects") or len(semantic.get("office_objects") or []),
            "parking_spaces": stats.get("parking_spaces") or len(semantic.get("parking_spaces") or []),
            "fixtures": stats.get("fixtures") or len(semantic.get("fixtures") or []),
            "frames": stats.get("frames") or len(semantic.get("frames") or []),
            "unknown": stats.get("unknown"),
            "review_needed": review_needed,
        },
        "devices_by_type": count_by(devices),
        "device_families": family_counts(devices),
        "cables_by_type": count_by(cables),
        "structures_by_type": count_by(structures),
        "areas_by_type": count_by(areas),
        "inferred_cables": inferred_cables,
        "warnings": warnings,
        "inferred": inferred,
        "checklist_missing": [item.get("label") for item in checklist if item.get("status") == "missing"],
        "checklist_extra": [item.get("label") for item in checklist if item.get("status") == "extra_detected"],
        "active_rule_sets": semantic.get("active_rule_sets") or quality.get("active_rule_sets") or [],
        "render_ready": render_ready,
        "has_strong_current": bool(
            family_counts(devices).get("power") or family_counts(devices).get("lighting")
        ),
        "source_file": (semantic.get("drawing_meta") or {}).get("source_file")
        or (semantic.get("drawing_meta") or {}).get("original_name"),
    }


def compare_targets(metrics: dict[str, Any], target: dict[str, Any] | None, label: str = "desired") -> dict[str, Any]:
    if not target:
        return {"enabled": False, "passed": True, "gaps": []}
    gaps: list[str] = []
    actual_types = metrics.get("devices_by_type") or {}
    for device_type, minimum in (target.get("devices_by_type") or {}).items():
        actual = int(actual_types.get(device_type) or 0)
        if actual < int(minimum):
            gaps.append(f"{device_type}: actual={actual} {label}>={minimum}")
    stats = metrics.get("stats") or {}
    if target.get("cables_min") is not None and int(stats.get("cables") or 0) < int(target["cables_min"]):
        gaps.append(f"cables: actual={stats.get('cables')} {label}>={target['cables_min']}")
    if target.get("structures_min") is not None and int(stats.get("structures") or 0) < int(target["structures_min"]):
        gaps.append(f"structures: actual={stats.get('structures')} {label}>={target['structures_min']}")
    if target.get("render_ready") and not metrics.get("render_ready"):
        gaps.append("render_ready: 3D 输入为空")
    return {"enabled": True, "passed": not gaps, "gaps": gaps}


def compare_desired(metrics: dict[str, Any], desired: dict[str, Any] | None) -> dict[str, Any]:
    return compare_targets(metrics, desired, "desired")
