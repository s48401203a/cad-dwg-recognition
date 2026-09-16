from __future__ import annotations

import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PROJECTS = ROOT / "backend" / "projects"
PROJECTS_ARCHIVE = ROOT / "backend" / "projects-archive"


BASELINES = {
    "proj_28b9e82ca9": {
        "name": "南宁",
        "ap": 20,
        "fisheye": 36,
    },
    "proj_8a819c4756": {
        "name": "郴州",
        "ap": 3,
        "fisheye": 4,
        "dome": 1,
    },
    "proj_8b7ee04aa8": {
        "name": "广州",
        "ap": 10,
        "fisheye": 14,
        "dome": 2,
        "bullet_or_rear": 56,
    },
}


def load_current_semantic(project_id: str) -> dict:
    project_dir = PROJECTS / project_id
    if not (project_dir / "meta.json").exists():
        project_dir = PROJECTS_ARCHIVE / project_id
    meta_path = project_dir / "meta.json"
    if not meta_path.exists():
        raise AssertionError(f"缺少项目 meta.json: {project_id}")
    meta = json.loads(meta_path.read_text(encoding="utf-8"))
    drawing_id = meta.get("current_drawing_id")
    current_drawing = next((item for item in meta.get("drawings", []) if item.get("id") == drawing_id), None)
    semantic_value = current_drawing.get("semantic_path") if current_drawing else None
    semantic_path = Path(semantic_value) if semantic_value else project_dir / str(drawing_id) / "semantic.json"
    if not semantic_path.is_absolute():
        semantic_path = project_dir / semantic_path
    if not semantic_path.exists():
        raise AssertionError(f"缺少当前 semantic.json: {semantic_path}")
    return json.loads(semantic_path.read_text(encoding="utf-8"))


def count_devices(semantic: dict) -> dict[str, int]:
    counts = {"ap": 0, "fisheye": 0, "dome": 0, "bullet_or_rear": 0}
    for device in semantic.get("devices", []):
        device_type = device.get("type")
        if device_type == "network.ap":
            counts["ap"] += 1
        elif device_type == "security.camera.fisheye":
            counts["fisheye"] += 1
        elif device_type == "security.camera.dome":
            counts["dome"] += 1
        elif device_type in {"security.camera.bullet", "security.camera.rear"}:
            counts["bullet_or_rear"] += 1
    return counts


def main() -> None:
    failures: list[str] = []
    for project_id, expected in BASELINES.items():
        semantic = load_current_semantic(project_id)
        actual = count_devices(semantic)
        for key, expected_value in expected.items():
            if key == "name":
                continue
            if actual.get(key) != expected_value:
                failures.append(f"{expected['name']} {key}: actual={actual.get(key)} expected={expected_value}")
    if failures:
        raise AssertionError("; ".join(failures))
    print("历史基准数量回归通过")


if __name__ == "__main__":
    main()
