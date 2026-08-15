from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from placement import apply_standard_heights, default_semantic, is_placement_project, load_catalog, merge_overrides  # noqa: E402


def test_catalog_has_ap_and_breaker() -> None:
    catalog = load_catalog()
    ids = set(catalog["by_id"])
    assert "network.ap.warehouse" in ids
    assert "lighting.floodlight" in ids
    assert "power.breaker" in ids
    assert "security.camera.dome" in ids
    assert "office.workstation" in ids
    assert catalog["by_id"]["network.ap.warehouse"]["install_height_m"] == 6.0


def test_merge_places_devices_and_shell() -> None:
    catalog = load_catalog()
    meta = {"id": "proj_test", "name": "t", "site_profiles": ["generic"]}
    overrides = {
        "site": {"length_m": 40, "width_m": 20},
        "instances": [
            {
                "id": "ap1",
                "catalog_id": "network.ap.warehouse",
                "type": "network.ap",
                "kind": "device",
                "label": "AP-01",
                "geometry": {"type": "point", "position": {"x": 0, "y": 0}},
                "attributes": {"install_height_m": 6.0},
            },
            {
                "id": "sl1",
                "catalog_id": "lighting.floodlight",
                "type": "lighting.floodlight",
                "kind": "fixture",
                "label": "SL-01",
                "geometry": {"type": "point", "position": {"x": 1000, "y": 0}},
                "attributes": {"install_height_m": 3.0},
            },
        ],
        "circuits": [],
    }
    merged = merge_overrides(default_semantic(meta, catalog), overrides, catalog)
    assert len(merged["devices"]) == 1
    assert merged["devices"][0]["attributes"]["install_height_m"] == 6.0
    assert len(merged["fixtures"]) == 1
    assert merged["areas"][0]["type"] == "area.warehouse.shell"


def test_apply_standard_heights_resets_user_change() -> None:
    data = {
        "instances": [
            {
                "catalog_id": "network.ap.warehouse",
                "attributes": {"install_height_m": 2.0},
            }
        ]
    }
    apply_standard_heights(data)
    assert data["instances"][0]["attributes"]["install_height_m"] == 6.0


def test_only_studio_name_is_placement_project() -> None:
    assert is_placement_project({"name": "模型摆放试验场", "drawings": []})
    assert is_placement_project({"name": "场地A", "placement_studio": True})
    assert not is_placement_project({"name": "场地A-平面图", "drawings": [{"id": "x"}]})
