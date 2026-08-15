from __future__ import annotations

import re
from typing import Any

BAISHI_LABEL = re.compile(r"^(CW|KW|GX|YY|BG|OA|WH|WW|CD)-?\d{1,3}$", re.I)


def _labels(semantic: dict[str, Any]) -> list[str]:
    labels: list[str] = []
    for key in ("devices", "cables", "fixtures", "parking_spaces"):
        for item in semantic.get(key) or []:
            label = str(item.get("label") or "")
            if label:
                labels.append(label)
    return labels


def analyze_specificity(semantic: dict[str, Any]) -> dict[str, Any]:
    hits: list[dict[str, Any]] = []
    profiles = [str(item) for item in (semantic.get("site_profiles") or [])]
    if "express" in profiles:
        hits.append({"id": "profile_express", "weight": 0.15, "detail": "默认快运 profile"})
    if "supply_chain" in profiles:
        hits.append({"id": "profile_supply_chain", "weight": 0.15, "detail": "供应链 profile"})

    rule_sets = semantic.get("active_rule_sets") or (semantic.get("quality") or {}).get("active_rule_sets") or []
    if any("gatehouse" in str(item.get("id") or item) for item in rule_sets):
        hits.append({"id": "gatehouse_ruleset", "weight": 0.25, "detail": "炮楼确认规则被激活"})

    parking = semantic.get("parking_spaces") or []
    if parking:
        hits.append({"id": "parking_inferred", "weight": 0.15, "detail": f"推断车位 {len(parking)}"})

    fixtures = semantic.get("fixtures") or []
    if fixtures:
        hits.append({"id": "spotlight_fixtures", "weight": 0.10, "detail": f"射灯 {len(fixtures)}"})

    baishi_labels = [label for label in _labels(semantic) if BAISHI_LABEL.match(re.sub(r"\s+", "", label))]
    if baishi_labels:
        hits.append(
            {
                "id": "baishi_label_prefixes",
                "weight": 0.20,
                "detail": f"百世风格编号 {len(baishi_labels)} 个，例 {baishi_labels[:4]}",
            }
        )

    areas = semantic.get("areas") or []
    if any(str(area.get("type") or "") == "area.warehouse.shell" for area in areas):
        hits.append({"id": "warehouse_shell", "weight": 0.08, "detail": "仓库外壳推断"})

    site = semantic.get("site") or {}
    if site.get("warehouse_wall_height_m") or site.get("dock_height_m"):
        hits.append({"id": "warehouse_site_defaults", "weight": 0.07, "detail": "仓库层高/月台高度默认值"})

    score = min(1.0, round(sum(item["weight"] for item in hits), 3))
    return {
        "score": score,
        "level": "high" if score >= 0.55 else "medium" if score >= 0.25 else "low",
        "hits": hits,
    }
