# -*- coding: utf-8 -*-
"""内置静态导出的回归测试。

数据全部是**自造的**合成 semantic（不读任何真实图纸 / semantic.json）：
- 运行时根目录通过 `CAD_RUNTIME_ROOT` 指到 tmp_path，再 reload storage（storage 在 import 时读环境变量），
  这样既能走真实的路径策略（allowed_roots_for_meta / drawing_semantic_path），又不会碰到 backend/projects。
"""
from __future__ import annotations

import importlib
import json
import re
import sys
from pathlib import Path
from typing import Any
from urllib.parse import quote

import pytest

ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

import exporting.static_export as static_export  # noqa: E402
import path_policy  # noqa: E402
import storage  # noqa: E402

PROJECT_ID = "proj_teststatic1"
DRAWING_ID = "draw_teststatic1"
OTHER_DRAWING_ID = "draw_teststatic2"
PROJECT_NAME = "静态导出测试项目"
DRAWING_NAME = "测试图纸-一层"
SEMANTIC_TAG = re.compile(r'<script type="application/json" id="cad-semantic">(.*?)</script>', re.S)


# ---------------------------------------------------------------- 夹具


def _reload_runtime_modules() -> None:
    """让 storage / static_export 重新读取 CAD_RUNTIME_ROOT。"""
    importlib.reload(storage)
    importlib.reload(static_export)


@pytest.fixture()
def runtime_root(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """隔离的运行时根目录（projects / projects-archive / uploads 都落在 tmp_path 下）。"""
    runtime = tmp_path / "runtime"
    monkeypatch.setenv("CAD_RUNTIME_ROOT", str(runtime))
    _reload_runtime_modules()
    try:
        yield runtime
    finally:
        monkeypatch.undo()
        _reload_runtime_modules()


# ---------------------------------------------------------------- 合成数据


def _semantic_payload(project_id: str, drawing_id: str, save_dir: Path, *, label: str = "枪机-01") -> dict[str, Any]:
    """纯合成语义数据：覆盖 point / Point / LineString / Polygon / Circle / Arc 六种几何。"""
    ring = [
        {"x": 0, "y": 0},
        {"x": 20000, "y": 0},
        {"x": 20000, "y": 10000},
        {"x": 0, "y": 10000},
    ]
    return {
        "schema_version": "test-synthetic-1",
        # 老工具会塞 save_dir，这里特意放进去，验证导出时必须被剥掉
        "project": {"id": project_id, "name": PROJECT_NAME, "save_dir": str(save_dir)},
        "drawing_meta": {
            "name": DRAWING_NAME,
            "source_file": str(save_dir / "secret-source" / "site-plan.dwg"),
            "modelspace_scale_to_mm": 1.0,
        },
        "extents": {"min": {"x": 0, "y": 0}, "max": {"x": 20000, "y": 10000}},
        "stats": {"total_entities": 12, "review_needed": 2},
        "structures": [
            {
                "id": "st1",
                "type": "building.wall",
                "original_layer": "WALL",
                "geometry": {"type": "LineString", "points": [{"x": 0, "y": 0}, {"x": 20000, "y": 0}]},
                "attributes": {"height_m": 8.0},
            },
            {
                "id": "st2",
                "type": "building.outline",
                "original_layer": "OUTLINE",
                "geometry": {"type": "Polygon", "closed": True, "points": ring},
                "attributes": {"height_m": 9.0},
            },
        ],
        "areas": [
            {
                "id": "ar1",
                "type": "area.warehouse.shell",
                "label": "测试仓库",
                "original_layer": "AREA",
                "geometry": {"type": "polygon", "closed": True, "points": ring},
            }
        ],
        "cables": [
            {
                "id": "cb1",
                "type": "cable.trunk",
                "label": "主干-01",
                "original_layer": "CABLE-TRUNK",
                "length_mm": 21000,
                "geometry": {"type": "LineString", "points": [{"x": 200, "y": 200}, {"x": 9000, "y": 200}, {"x": 9000, "y": 5000}]},
            },
            {
                "id": "cb2",
                "type": "cable.camera",
                "label": "枪机支线",
                "original_layer": "CABLE-CAM",
                "geometry": {"type": "Arc", "center": {"x": 1000, "y": 1000}, "radius": 500, "start_angle": 0, "end_angle": 90},
            },
        ],
        "devices": [
            {
                "id": "dv1",
                "type": "security.camera.bullet",
                "label": label,
                "original_layer": "CAM-BULLET",
                "geometry": {"type": "point", "position": {"x": 1000, "y": 1000}},
                "attributes": {"install_height_m": 6.0, "coverage_radius_m": 40},
            },
            {
                "id": "dv2",
                "type": "network.ap",
                "label": "AP-01",
                "original_layer": "AP",
                "geometry": {"type": "Point", "position": {"x": 4000, "y": 2500}},
                "attributes": {"install_height_m": 6.0},
            },
            {
                "id": "dv3",
                "type": "device.cabinet",
                "label": "机柜-01",
                "original_layer": "CABINET",
                "geometry": {"type": "Circle", "center": {"x": 6000, "y": 3000}, "radius": 300},
            },
        ],
        "fixtures": [
            {
                "id": "fx1",
                "type": "lighting.floodlight",
                "label": "射灯-01",
                "original_layer": "LIGHT",
                "geometry": {"type": "point", "position": {"x": 800, "y": 400}},
            }
        ],
        "office_objects": [],
        "parking_spaces": [],
        "annotations": [
            {"id": "an1", "type": "annotation.text", "label": "编号 A-01", "original_layer": "TEXT"},
        ],
        # 嵌在长文本里的绝对路径也必须被抹掉
        "quality": {"warnings": [f"参考图元来自 {save_dir / 'raw' / 'warn.dwg'}，请复核"]},
    }


def _write_semantic(path: Path, payload: dict[str, Any]) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    return path


def _canonical_semantic_path(runtime: Path, drawing_id: str = DRAWING_ID) -> Path:
    return runtime / "projects" / PROJECT_ID / "drawings" / drawing_id / "semantic.json"


def _build_meta(
    runtime: Path,
    *,
    write_semantic: bool = True,
    semantic_path_override: str | None = None,
    payload: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """构造合成项目 meta；save_dir 落在受管根目录内。"""
    save_dir = runtime / "projects" / PROJECT_ID
    canonical = _canonical_semantic_path(runtime)
    if write_semantic:
        _write_semantic(canonical, payload or _semantic_payload(PROJECT_ID, DRAWING_ID, save_dir))

    drawing: dict[str, Any] = {"id": DRAWING_ID, "name": DRAWING_NAME, "parsed_at": "2026-01-01T00:00:00"}
    if semantic_path_override is not None:
        drawing["semantic_path"] = semantic_path_override
    elif write_semantic:
        drawing["semantic_path"] = str(canonical)

    return {
        "id": PROJECT_ID,
        "name": PROJECT_NAME,
        "save_dir": str(save_dir),
        "status": "active",
        "created_at": "2026-01-01T00:00:00",
        "current_drawing_id": DRAWING_ID,
        "drawings": [drawing],
    }


def _embedded_payload(html: str) -> dict[str, Any]:
    match = SEMANTIC_TAG.search(html)
    assert match, "导出页面缺少 cad-semantic 内嵌数据"
    return json.loads(match.group(1))


def _export(meta: dict[str, Any], output_root: Path, **kwargs: Any) -> tuple[dict[str, Any], str]:
    result = static_export.export_single_project(meta, output_root=output_root, **kwargs)
    html = Path(result["path"]).read_text(encoding="utf-8")
    return result, html


# ---------------------------------------------------------------- 导出主流程


def test_export_writes_offline_viewer(runtime_root: Path, tmp_path: Path) -> None:
    meta = _build_meta(runtime_root)
    output_root = tmp_path / "out"

    result, html = _export(meta, output_root)
    html_path = Path(result["path"])

    assert html_path.is_file()
    assert html_path.stat().st_size > 0
    assert html_path.suffix == ".html"
    assert html_path.parent == (output_root / PROJECT_ID).resolve()
    assert result["bytes"] == result["size_bytes"] == html_path.stat().st_size
    assert result["drawing_id"] == DRAWING_ID
    assert result["project_id"] == PROJECT_ID
    assert result["file_name"] == html_path.name

    # 页头信息：项目名 / 图纸名 / 时间戳 / 只读声明 / 实体计数
    assert PROJECT_NAME in html
    assert DRAWING_NAME in html
    assert result["generated_at"] in html
    assert "只读静态快照" in html
    assert "<b>4</b>设备" in html  # 3 个 device + 1 个 fixture
    assert "<b>12</b>实体" in html

    # 内嵌数据可解析 + 计数正确
    payload = _embedded_payload(html)
    assert payload["project"]["id"] == PROJECT_ID
    assert payload["project"]["drawing_id"] == DRAWING_ID
    assert payload["stats"]["devices"] == 4
    assert payload["stats"]["cables"] == 2
    assert payload["stats"]["structures"] == 2
    assert payload["stats"]["areas"] == 1
    assert payload["stats"]["total_entities"] == 12
    assert len(payload["devices"]) == 3

    # 离线：不联网、不引用外部 CDN
    assert "http://" not in html
    assert "https://" not in html
    assert "cdn" not in html.lower()
    assert "three.module.js" in html
    assert '<script type="importmap">' in html

    # 占位符必须真的被替换掉（viewer 里读的就是这个 id）
    assert "readJson(\"cad-semantic\")" in html
    assert "__SEMANTIC_ID__" not in html
    assert "__THREE_BASE__" not in html
    assert "__SEMANTIC_JSON__" not in html

    # 原子写入：不留临时文件
    assert list(output_root.rglob("*.tmp")) == []


def test_export_never_embeds_local_absolute_paths(runtime_root: Path, tmp_path: Path) -> None:
    meta = _build_meta(runtime_root)
    save_dir = Path(meta["save_dir"])

    _result, html = _export(meta, tmp_path / "out")

    assert str(save_dir) not in html
    assert str(save_dir / "secret-source") not in html
    assert str(runtime_root) not in html
    assert str(tmp_path) not in html
    assert "已隐藏本地路径" in html  # 绝对路径被替换成占位串

    payload = _embedded_payload(html)
    # 路径类键整体剔除
    assert "save_dir" not in payload["project"]
    assert "source_file" not in payload["drawing_meta"]
    assert "save_dir" not in json.dumps(payload, ensure_ascii=False)
    # 嵌在长文本里的路径只保留末段文件名
    warning = payload["quality"]["warnings"][0]
    assert str(save_dir) not in warning
    assert "参考图元来自" in warning
    assert "<已隐藏本地路径>/warn.dwg" in warning


def test_export_uses_canonical_semantic_path(runtime_root: Path, tmp_path: Path) -> None:
    # 没有给 semantic_path，导出器应自己按规范位置找到 semantic.json
    meta = _build_meta(runtime_root)
    meta["drawings"][0].pop("semantic_path")

    result, _html = _export(meta, tmp_path / "out")
    assert Path(result["path"]).is_file()


def test_export_falls_back_to_stored_semantic_path_inside_roots(runtime_root: Path, tmp_path: Path) -> None:
    alt = runtime_root / "projects" / PROJECT_ID / "extra" / "semantic.json"
    _write_semantic(alt, _semantic_payload(PROJECT_ID, DRAWING_ID, runtime_root / "projects" / PROJECT_ID))
    meta = _build_meta(runtime_root, write_semantic=False, semantic_path_override=str(alt))
    assert path_policy.is_within_roots(alt, storage.allowed_roots_for_meta(meta))

    result, _html = _export(meta, tmp_path / "out")
    assert Path(result["path"]).is_file()
    assert result["drawing_id"] == DRAWING_ID


def test_export_picks_current_drawing_when_not_specified(runtime_root: Path, tmp_path: Path) -> None:
    meta = _build_meta(runtime_root)
    other_save_dir = runtime_root / "projects" / PROJECT_ID
    other_semantic = _canonical_semantic_path(runtime_root, OTHER_DRAWING_ID)
    _write_semantic(other_semantic, _semantic_payload(PROJECT_ID, OTHER_DRAWING_ID, other_save_dir))
    meta["drawings"].append(
        {"id": OTHER_DRAWING_ID, "name": "测试图纸-二层", "semantic_path": str(other_semantic), "parsed_at": "2026-01-02T00:00:00"}
    )
    meta["current_drawing_id"] = OTHER_DRAWING_ID

    result, _html = _export(meta, tmp_path / "out")

    # drawings[0] 是 DRAWING_ID，但 current_drawing_id 优先
    assert result["drawing_id"] == OTHER_DRAWING_ID
    assert OTHER_DRAWING_ID in result["file_name"]


def test_export_default_file_name_mentions_project_and_drawing(runtime_root: Path, tmp_path: Path) -> None:
    result, _html = _export(_build_meta(runtime_root), tmp_path / "out")
    assert result["file_name"].endswith(".html")
    assert PROJECT_NAME in result["file_name"]
    assert DRAWING_ID in result["file_name"]


def test_public_url_prefix_is_reflected(runtime_root: Path, tmp_path: Path) -> None:
    meta = _build_meta(runtime_root)

    for index, prefix in enumerate(("/exports/static-pages", "/share/cad/")):
        result, _html = _export(meta, tmp_path / f"out{index}", public_url_prefix=prefix)
        assert result["url"] == f"{prefix.rstrip('/')}/{PROJECT_ID}/{quote(result['file_name'])}"


def test_exporter_info_identifies_builtin() -> None:
    info = static_export.exporter_info()
    assert info["kind"] == "builtin"
    assert info["module"].endswith("exporting.static_export")


# ---------------------------------------------------------------- 拒绝路径 / 数据


def test_export_rejects_unknown_drawing_id(runtime_root: Path, tmp_path: Path) -> None:
    meta = _build_meta(runtime_root)

    with pytest.raises(FileNotFoundError) as captured:
        static_export.export_single_project(meta, output_root=tmp_path / "out", drawing_id="draw_missing")

    assert "draw_missing" in str(captured.value)
    assert not (tmp_path / "out").exists() or not list((tmp_path / "out").rglob("*.html"))


def test_export_rejects_malformed_drawing_id(runtime_root: Path, tmp_path: Path) -> None:
    meta = _build_meta(runtime_root)

    with pytest.raises(path_policy.PathPolicyError):
        static_export.export_single_project(meta, output_root=tmp_path / "out", drawing_id="../../etc/passwd")


def test_export_rejects_semantic_path_outside_allowed_roots(
    runtime_root: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    decoy_dir = tmp_path / "outside" / "decoy"
    decoy = _write_semantic(decoy_dir / "semantic.json", {"project": {"name": "诱饵"}, "devices": [{"id": "fake"}]})
    meta = _build_meta(runtime_root, write_semantic=False, semantic_path_override=str(decoy))
    assert not path_policy.is_within_roots(decoy, storage.allowed_roots_for_meta(meta))

    read_paths: list[Path] = []
    real_read = storage.read_json_strict

    def _spy(path: Path, default: Any = None, **kwargs: Any) -> Any:
        read_paths.append(Path(path))
        return real_read(path, default, **kwargs)

    monkeypatch.setattr(storage, "read_json_strict", _spy)

    with pytest.raises(FileNotFoundError):
        static_export.export_single_project(meta, output_root=tmp_path / "out")

    assert read_paths == [], f"越界 semantic 路径不得被读取: {read_paths}"


def test_export_rejects_corrupt_semantic_json(runtime_root: Path, tmp_path: Path) -> None:
    meta = _build_meta(runtime_root, write_semantic=False)
    corrupt = _canonical_semantic_path(runtime_root)
    corrupt.parent.mkdir(parents=True, exist_ok=True)
    corrupt.write_text('{"devices": [ {"id": "dv1",', encoding="utf-8")

    with pytest.raises(storage.CorruptJsonError):
        static_export.export_single_project(meta, output_root=tmp_path / "out")

    assert not list((tmp_path / "out").rglob("*.html"))


def test_export_rejects_empty_semantic_json(runtime_root: Path, tmp_path: Path) -> None:
    meta = _build_meta(runtime_root, write_semantic=False)
    empty = _canonical_semantic_path(runtime_root)
    empty.parent.mkdir(parents=True, exist_ok=True)
    empty.write_text("", encoding="utf-8")

    with pytest.raises(storage.StorageError) as captured:
        static_export.export_single_project(meta, output_root=tmp_path / "out")

    assert not isinstance(captured.value, storage.CorruptJsonError)
    assert DRAWING_ID in str(captured.value)


def test_export_requires_at_least_one_drawing(runtime_root: Path, tmp_path: Path) -> None:
    meta = _build_meta(runtime_root)
    meta["drawings"] = []

    with pytest.raises(FileNotFoundError) as captured:
        static_export.export_single_project(meta, output_root=tmp_path / "out")

    assert "图纸" in str(captured.value)


# ---------------------------------------------------------------- 输出路径逃逸


@pytest.mark.parametrize(
    ("evil_name", "expected_name"),
    [
        ("../../evil.html", "evil.html"),
        ("..\\..\\evil.html", "evil.html"),
        ("/absolute/evil.html", "evil.html"),
        ("..\\..\\..\\evil", "evil.html"),
    ],
)
def test_export_keeps_output_inside_root(runtime_root: Path, tmp_path: Path, evil_name: str, expected_name: str) -> None:
    meta = _build_meta(runtime_root)
    output_root = tmp_path / "out"

    result, _html = _export(meta, output_root, file_name=evil_name)
    target = Path(result["path"]).resolve()

    assert target.is_relative_to(output_root.resolve())
    assert target.name == expected_name
    assert target.is_file()
    assert list(output_root.rglob("*.html")) == [target]
    # 仓库外 / 上级目录都不能出现文件
    assert not (tmp_path / expected_name).exists()
    assert not (output_root.parent / expected_name).exists()


def test_export_keeps_output_inside_root_for_absolute_file_name(runtime_root: Path, tmp_path: Path) -> None:
    meta = _build_meta(runtime_root)
    output_root = tmp_path / "out"
    outside = tmp_path / "outside-abs-evil.html"

    result, _html = _export(meta, output_root, file_name=str(outside))

    target = Path(result["path"]).resolve()
    assert target.is_relative_to(output_root.resolve())
    assert target.name == "outside-abs-evil.html"
    assert not outside.exists()


# ---------------------------------------------------------------- three.js 前缀


def test_three_base_falls_back_outside_repo(tmp_path: Path) -> None:
    # tmp_path 在仓库之外：不能用相对路径（那会等于把主机绝对路径写进分享文件）
    assert static_export._three_base_for(tmp_path / "out") == "/vendor/three/"


def test_three_base_falls_back_when_vendored_missing(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(static_export, "THREE_VENDOR_DIR", tmp_path / "missing-three")
    assert static_export._three_base_for(ROOT / "exports") == "/vendor/three/"


def test_three_base_is_relative_inside_repo(tmp_path: Path) -> None:
    output_dir = ROOT / "exports" / "_pytest-static-export-probe" / PROJECT_ID
    base = static_export._three_base_for(output_dir)
    if base != "/vendor/three/":
        assert base.endswith("frontend/vendor/three/")
        assert not base.startswith("/")


# ---------------------------------------------------------------- 内嵌数据安全


def test_embedded_payload_cannot_break_out_of_script_tag(runtime_root: Path, tmp_path: Path) -> None:
    evil_label = '</script><script>alert("xss")</script>'
    payload = _semantic_payload(PROJECT_ID, DRAWING_ID, runtime_root / "projects" / PROJECT_ID, label=evil_label)
    meta = _build_meta(runtime_root, payload=payload)

    _result, html = _export(meta, tmp_path / "out")

    # 三个脚本标签 = importmap + 内嵌 JSON + viewer；内嵌数据里的 </script> 必须被转义
    assert html.count("</script>") == 3
    assert "\\u003c/script" in html
    parsed = _embedded_payload(html)
    labels = [device.get("label") for device in parsed["devices"]]
    assert evil_label in labels


def test_embedded_payload_keeps_geometry_and_layers(runtime_root: Path, tmp_path: Path) -> None:
    _result, html = _export(_build_meta(runtime_root), tmp_path / "out")
    payload = _embedded_payload(html)

    assert payload["structures"][0]["geometry"]["type"] == "LineString"
    assert payload["cables"][1]["geometry"]["type"] == "Arc"
    assert payload["devices"][2]["geometry"]["type"] == "Circle"
    layers = {item.get("original_layer") for item in payload["devices"]}
    assert {"CAM-BULLET", "AP", "CABINET"} <= layers
