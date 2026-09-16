"""块引用（INSERT）变换测试。

覆盖范围：
- 用 ezdxf 自己展开 `virtual_entities()`，逐点校验旋转 90°、镜像（xscale=-1）、
  非均匀缩放（3×1）与两层嵌套后的坐标是否与手算一致。
- 校验 `DxfReader` 输出的 INSERT 记录：`block_name` / `geometry.position` / `rotation` /
  `source_entity_id`（必须等于 DXF handle）。
- 记录并断言实现的真实限制与**缺陷**（本轮不改 `dxf_reader.py`，只如实断言现状）：
  1. `cad_virtual_shapes` 只对**块名命中 CAD 角色**（或虚拟实体像车位）的块引用生成；
     `方块`/`内块`/`嵌套块` 这类名字拿不到虚拟几何（不是缺陷，是设计）。
  2. 嵌套块里的虚拟几何是 INSERT，`_normalize_virtual_shape` 会跳过它，
     因此**两层嵌套的几何不会被展开**（`cad_virtual_shapes` 为空）。
  3. **缺陷**：镜像（负缩放）块的角色虚拟几何坐标整体错位（插入点丢失）。
  4. **缺陷**：非均匀缩放（xscale=3, yscale=1）块的角色虚拟几何丢了 x 方向缩放与插入点。
     3 与 4 的根因相同：负缩放/非均匀缩放展开后虚拟实体的 `extrusion` 被翻转，
     `get_points("xyb")` 返回的是 OCS 坐标，而 `_normalize_virtual_shape` 直接当 WCS 用。

所有夹具都是代码生成的临时文件（tmp_path），不读取任何真实客户图纸。
"""

from __future__ import annotations

import math
from pathlib import Path
from typing import Any

import ezdxf
import pytest

from parser.dxf_reader import DxfReader
from tests.synthetic import (
    _new_doc,
    build_block_transform_fixture,
    build_nested_role_block_fixture,
    build_role_block_fixture,
    build_role_block_unrotated_fixture,
    write_dxf,
)

# 块内正方形（边长 2、以原点为中心）的角点
SQUARE_CORNERS = [(-1.0, -1.0), (1.0, -1.0), (1.0, 1.0), (-1.0, 1.0)]


def _role_block_with(insert_at: tuple[float, float], **insert_attribs: Any):
    """构造「块名命中角色」的图纸，块内是与 synthetic 里一致的方块 + 90° 弧。"""
    doc = _new_doc(4)
    block = doc.blocks.new(name="摄像头-方块")
    block.add_lwpolyline([(-1, -1), (1, -1), (1, 1), (-1, 1)], close=True)
    block.add_arc((0, 0), 0.5, 0, 90)
    attribs = {"layer": "监控"}
    attribs.update(insert_attribs)
    doc.modelspace().add_blockref("摄像头-方块", insert_at, dxfattribs=attribs)
    return doc


def build_role_block_fixture_mirrored():
    """角色块 + xscale=-1（镜像）、插入点 (2000, 0)。"""
    return _role_block_with((2000.0, 0.0), xscale=-1.0)


def _doc(path: Path) -> ezdxf.document.Drawing:
    return ezdxf.readfile(path)


def _virtual_points(insert, *, recurse: bool = False) -> list[tuple[float, float]]:
    """把一个块引用展开成 **WCS** (x, y) 点表。

    LWPOLYLINE 必须用 `vertices_in_wcs()`：镜像/非均匀缩放的展开会让 `extrusion`
    变成 (0,0,-1)，此时 `get_points("xyb")` 返回的是 OCS 坐标（见本文件底部的缺陷用例）。
    """
    points: list[tuple[float, float]] = []
    for virtual in insert.virtual_entities():
        if virtual.dxftype() == "LWPOLYLINE":
            points.extend((round(float(vertex.x), 9), round(float(vertex.y), 9)) for vertex in virtual.vertices_in_wcs())
        elif virtual.dxftype() == "LINE":
            points.append((float(virtual.dxf.start.x), float(virtual.dxf.start.y)))
            points.append((float(virtual.dxf.end.x), float(virtual.dxf.end.y)))
        elif virtual.dxftype() == "INSERT" and recurse:
            points.extend(_virtual_points(virtual, recurse=True))
    return points


def _insert_by_name(path: Path, block_name: str, index: int = 0):
    inserts = [entity for entity in _doc(path).modelspace().query("INSERT") if entity.dxf.name == block_name]
    assert len(inserts) > index, f"未找到第 {index} 个 {block_name} 块引用"
    return inserts[index]


def _reader_insert(path: Path) -> dict:
    result = DxfReader.read(path)
    inserts = [entity for entity in result["entities"] if entity["entity_type"] == "INSERT"]
    assert len(inserts) == 1, f"期望恰好 1 个 INSERT，实际 {len(inserts)}"
    return inserts[0]


def _reader_polygon_points(insert_record: dict) -> list[tuple[float, float]]:
    polygon = next(
        shape for shape in insert_record["cad_virtual_shapes"] if shape["geometry"]["type"] == "Polygon"
    )
    return [(point["x"], point["y"]) for point in polygon["geometry"]["points"]]


def _bounds(points: list[tuple[float, float]]) -> tuple[float, float, float, float]:
    xs = [point[0] for point in points]
    ys = [point[1] for point in points]
    return min(xs), min(ys), max(xs), max(ys)


# --------------------------------------------------------------- ezdxf 变换矩阵核对


def test_block_transform_fixture_places_four_inserts(tmp_path: Path):
    """夹具本身：4 个块引用，位置正确（1000/2000/3000/4000）。"""
    path = write_dxf(tmp_path / "blocks.dxf", build_block_transform_fixture())
    inserts = list(_doc(path).modelspace().query("INSERT"))

    assert [(entity.dxf.name, float(entity.dxf.insert.x)) for entity in inserts] == [
        ("方块", 1000.0),
        ("方块", 2000.0),
        ("方块", 3000.0),
        ("嵌套块", 4000.0),
    ]


def test_rotation_90_transforms_square_corners(tmp_path: Path):
    """旋转 90°：块内 (±1, ±1) 必须变成 (1000±1, ∓1) —— 手算 (-y, x) 旋转。"""
    path = write_dxf(tmp_path / "rot.dxf", build_block_transform_fixture())
    insert = _insert_by_name(path, "方块", 0)
    assert float(insert.dxf.rotation) == 90.0

    points = _virtual_points(insert)
    assert len(points) == 4
    expected = [(-y + 1000.0, x + 0.0) for x, y in SQUARE_CORNERS]
    for point, want in zip(points, expected):
        assert point[0] == pytest.approx(want[0], abs=1e-9)
        assert point[1] == pytest.approx(want[1], abs=1e-9)

    # 旋转不改变尺寸（包围盒仍是 2×2）
    min_x, min_y, max_x, max_y = _bounds(points)
    assert (max_x - min_x, max_y - min_y) == (pytest.approx(2.0, abs=1e-9), pytest.approx(2.0, abs=1e-9))


def test_mirror_xscale_minus_one_transforms_square_corners(tmp_path: Path):
    """镜像（xscale=-1）：世界坐标 = 插入点 ± 1（2000 - x），y 不变。"""
    path = write_dxf(tmp_path / "mirror.dxf", build_block_transform_fixture())
    insert = _insert_by_name(path, "方块", 1)
    assert float(insert.dxf.xscale) == -1.0

    points = _virtual_points(insert)
    expected = [(2000.0 - x, 0.0 + y) for x, y in SQUARE_CORNERS]
    for point, want in zip(points, expected):
        assert point[0] == pytest.approx(want[0], abs=1e-9)
        assert point[1] == pytest.approx(want[1], abs=1e-9)

    min_x, _, max_x, _ = _bounds(points)
    assert (min_x, max_x) == (pytest.approx(1999.0, abs=1e-9), pytest.approx(2001.0, abs=1e-9))


def test_non_uniform_scale_3x1_transforms_square_corners(tmp_path: Path):
    """非均匀缩放 3×1：x 方向拉长到 6，y 方向保持 2。"""
    path = write_dxf(tmp_path / "nuscale.dxf", build_block_transform_fixture())
    insert = _insert_by_name(path, "方块", 2)
    assert float(insert.dxf.xscale) == 3.0 and float(insert.dxf.yscale) == 1.0

    points = _virtual_points(insert)
    expected = [(3000.0 + 3.0 * x, 0.0 + 1.0 * y) for x, y in SQUARE_CORNERS]
    for point, want in zip(points, expected):
        assert point[0] == pytest.approx(want[0], abs=1e-9)
        assert point[1] == pytest.approx(want[1], abs=1e-9)

    min_x, min_y, max_x, max_y = _bounds(points)
    assert (max_x - min_x, max_y - min_y) == (pytest.approx(6.0, abs=1e-9), pytest.approx(2.0, abs=1e-9))


def test_two_level_nesting_expands_to_expected_coordinates(tmp_path: Path):
    """两层嵌套（嵌套块 → 内块 → 方块）：递归展开后坐标必须落在 (4000±1, ±1)。

    ezdxf 的 `virtual_entities()` 只展开一层，因此这里自己递归展开一层来核对最终几何。
    """
    path = write_dxf(tmp_path / "nested.dxf", build_block_transform_fixture())
    outer = _insert_by_name(path, "嵌套块")
    assert float(outer.dxf.insert.x) == 4000.0

    first_level = list(outer.virtual_entities())
    assert [entity.dxftype() for entity in first_level] == ["INSERT"]
    assert first_level[0].dxf.name == "内块"

    points = _virtual_points(outer, recurse=True)
    assert len(points) == 4
    expected = [(4000.0 + x, 0.0 + y) for x, y in SQUARE_CORNERS]
    for point, want in zip(points, expected):
        assert point[0] == pytest.approx(want[0], abs=1e-9)
        assert point[1] == pytest.approx(want[1], abs=1e-9)


def test_combined_rotation_and_mirror_world_coordinates(tmp_path: Path):
    """旋转 + 镜像组合：xscale=-1、rotation=90、插入点 (2000,0) 的世界坐标必须是 2000±1 / ∓1。"""
    path = write_dxf(tmp_path / "rot_mirror.dxf", _role_block_with((2000.0, 0.0), xscale=-1.0, rotation=90.0))
    insert = _insert_by_name(path, "摄像头-方块")
    points = _virtual_points(insert)
    min_x, min_y, max_x, max_y = _bounds(points)
    assert (min_x, max_x) == (pytest.approx(1999.0, abs=1e-9), pytest.approx(2001.0, abs=1e-9))
    assert (min_y, max_y) == (pytest.approx(-1.0, abs=1e-9), pytest.approx(1.0, abs=1e-9))


# --------------------------------------------------------------- DxfReader 的 INSERT 记录


def test_reader_insert_records_have_position_rotation_and_handle(tmp_path: Path):
    """INSERT 记录必须带正确的 position / rotation / block_name / source_entity_id。"""
    path = write_dxf(tmp_path / "reader_blocks.dxf", build_block_transform_fixture())
    result = DxfReader.read(path)

    inserts = [entity for entity in result["entities"] if entity["entity_type"] == "INSERT"]
    assert len(inserts) == 4

    # source_entity_id 必须与 DXF handle 一一对应（可回溯原始实体）
    doc = _doc(path)
    handles = {str(entity.dxf.handle) for entity in doc.modelspace().query("INSERT")}
    assert {entity["source_entity_id"] for entity in inserts} == handles

    expected = [
        ("方块", 1000.0, 0.0, 90.0),
        ("方块", 2000.0, 0.0, 0.0),
        ("方块", 3000.0, 0.0, 0.0),
        ("嵌套块", 4000.0, 0.0, 0.0),
    ]
    for entity, (block_name, x, y, rotation) in zip(inserts, expected):
        assert entity["block_name"] == block_name
        assert entity["geometry"]["type"] == "Point"
        assert entity["geometry"]["position"] == {"x": x, "y": y}
        assert entity["rotation"] == pytest.approx(rotation, abs=1e-12)
        assert entity["attributes"] == {}


def test_reader_insert_position_matches_dxf_handle_values(tmp_path: Path):
    """逐字段比对：读取器的 position/rotation/block_name 必须等于 ezdxf 读到的原值。"""
    path = write_dxf(tmp_path / "reader_fields.dxf", build_block_transform_fixture())
    result = DxfReader.read(path)
    doc = _doc(path)

    by_handle = {entity["source_entity_id"]: entity for entity in result["entities"]}
    for dxf_insert in doc.modelspace().query("INSERT"):
        record = by_handle[str(dxf_insert.dxf.handle)]
        assert record["block_name"] == str(dxf_insert.dxf.name)
        assert record["geometry"]["position"]["x"] == pytest.approx(float(dxf_insert.dxf.insert.x), abs=1e-12)
        assert record["geometry"]["position"]["y"] == pytest.approx(float(dxf_insert.dxf.insert.y), abs=1e-12)
        assert record["rotation"] == pytest.approx(float(dxf_insert.dxf.rotation or 0.0), abs=1e-12)


def test_block_transform_fixture_has_no_virtual_shapes_because_names_do_not_match_roles(tmp_path: Path):
    """记录设计行为：非角色块名（方块/内块/嵌套块）不会产出 `cad_virtual_shapes`。

    `_insert_cad_role` 只认含 AP / 无线 / 鱼眼 / 半球 / 枪 / 摄像头 / 外围摄像 的块名，
    且 `_virtual_cad_role` 只在虚拟实体的图层像车位时才兜底。
    这些块引用图层是「墙」，虚拟实体图层是「0」，所以 role 为 None → 字段缺失。
    """
    path = write_dxf(tmp_path / "no_virtual.dxf", build_block_transform_fixture())
    result = DxfReader.read(path)

    inserts = [entity for entity in result["entities"] if entity["entity_type"] == "INSERT"]
    assert len(inserts) == 4
    for entity in inserts:
        assert "cad_virtual_shapes" not in entity, f"{entity['block_name']} 不应有虚拟几何"

    # 对照：ezdxf 自己能把这些块的几何展开出来（说明读不到不是图纸的问题，而是角色过滤）
    assert len(_virtual_points(_insert_by_name(path, "方块", 0))) == 4


def test_nested_block_geometry_is_not_expanded_by_reader(tmp_path: Path):
    """记录限制：两层嵌套的虚拟几何是 INSERT，读取器跳过 → `cad_virtual_shapes` 为空。

    这条同时排除了「块名没命中角色」这个解释：这里外层块名含「摄像头」，
    role 是命中的（见正例用例），但虚拟实体是 INSERT，
    `_normalize_virtual_shape` 只处理 LINE/LWPOLYLINE/POLYLINE/CIRCLE/ARC/ELLIPSE，
    于是返回 None，最终没有任何 shape 被收集。
    """
    path = write_dxf(tmp_path / "nested_role.dxf", build_nested_role_block_fixture())
    result = DxfReader.read(path)

    inserts = [entity for entity in result["entities"] if entity["entity_type"] == "INSERT"]
    assert len(inserts) == 1
    assert inserts[0]["block_name"] == "内层摄像头"
    assert "cad_virtual_shapes" not in inserts[0]

    # 证明确实是「一层展开得到 INSERT」导致的，而不是图纸里没有几何
    outer = _insert_by_name(path, "内层摄像头")
    assert [entity.dxftype() for entity in outer.virtual_entities()] == ["INSERT"]
    assert len(_virtual_points(outer, recurse=True)) == 4


# --------------------------------------------------------------- 角色命中时的虚拟几何（正确路径）


def test_role_block_produces_virtual_shapes_with_rotation_applied(tmp_path: Path):
    """块名命中角色（摄像头）+ 旋转 90°：虚拟几何正确（平移与旋转都不翻转 extrusion）。"""
    path = write_dxf(tmp_path / "role.dxf", build_role_block_fixture())
    insert = _reader_insert(path)

    assert insert["block_name"] == "摄像头-方块"
    assert insert["geometry"]["position"] == {"x": 1000.0, "y": 0.0}
    assert insert["rotation"] == pytest.approx(90.0, abs=1e-12)
    assert insert["source_entity_id"] == str(_insert_by_name(path, "摄像头-方块").dxf.handle)

    shapes = insert["cad_virtual_shapes"]
    assert len(shapes) == 2
    assert {shape["geometry"]["type"] for shape in shapes} == {"Polygon", "Arc"}
    for shape in shapes:
        assert shape["source_kind"] == "insert_virtual_entity"
        assert shape["cad_role"] == "camera_symbol"

    points = _reader_polygon_points(insert)
    assert _bounds(points) == (
        pytest.approx(999.0, abs=1e-9),
        pytest.approx(-1.0, abs=1e-9),
        pytest.approx(1001.0, abs=1e-9),
        pytest.approx(1.0, abs=1e-9),
    )
    polygon = next(shape for shape in shapes if shape["geometry"]["type"] == "Polygon")
    assert polygon["geometry"]["closed"] is True
    assert polygon["native_length_mm"] == pytest.approx(8.0, rel=1e-12)

    # 半径 0.5 的 90° 弧：旋转后 90°→180°，弧长仍是 π/4
    arc = next(shape for shape in shapes if shape["geometry"]["type"] == "Arc")
    assert arc["geometry"]["radius"] == pytest.approx(0.5, rel=1e-12)
    assert arc["geometry"]["length_mm"] == pytest.approx(math.pi / 4.0, rel=1e-12)
    assert arc["native_length_mm"] == arc["geometry"]["length_mm"]


def test_role_block_without_rotation_keeps_block_local_offsets(tmp_path: Path):
    """不旋转时，虚拟几何坐标必须等于「块内坐标 + 插入点」，便于逐点核对变换链。"""
    path = write_dxf(tmp_path / "role_plain.dxf", build_role_block_unrotated_fixture())
    insert = _reader_insert(path)

    assert insert["geometry"]["position"] == {"x": 0.0, "y": 0.0}
    assert insert["rotation"] == 0.0

    points = _reader_polygon_points(insert)
    expected = [(x + 0.0, y + 0.0) for x, y in SQUARE_CORNERS]
    for point, want in zip(points, expected):
        assert point[0] == pytest.approx(want[0], abs=1e-9)
        assert point[1] == pytest.approx(want[1], abs=1e-9)


# --------------------------------------------------------------- 缺陷：反射 / 非均匀缩放


def test_negative_scale_flips_virtual_entity_extrusion_and_ocs_points(tmp_path: Path):
    """机制说明：镜像块展开后虚拟实体的 `extrusion` 变成 (0,0,-1)，
    `get_points("xyb")` 返回的是相对新 OCS 的坐标，必须用 `vertices_in_wcs()` 才是世界坐标。

    这是下面两个「读取器镜像 / 非均匀缩放坐标错误」用例的根因说明。
    """
    path = write_dxf(tmp_path / "mirror_mech.dxf", build_block_transform_fixture())
    insert = _insert_by_name(path, "方块", 1)

    virtual = list(insert.virtual_entities())[0]
    assert tuple(virtual.dxf.extrusion) == (0.0, 0.0, -1.0)

    ocs_points = [(round(float(item[0]), 9), round(float(item[1]), 9)) for item in virtual.get_points("xyb")]
    wcs_points = [(round(float(vertex.x), 9), round(float(vertex.y), 9)) for vertex in virtual.vertices_in_wcs()]
    assert ocs_points != wcs_points, "OCS 与 WCS 必须不同，否则说明 ezdxf 行为已变"

    min_x, _, max_x, _ = _bounds(wcs_points)
    assert (min_x, max_x) == (pytest.approx(1999.0, abs=1e-9), pytest.approx(2001.0, abs=1e-9))
    # OCS 版本丢了插入点：落在原点另一侧
    assert max(point[0] for point in ocs_points) == pytest.approx(-1999.0, abs=1e-9)


def test_reader_mirrored_block_virtual_shape_keeps_insert_translation(tmp_path: Path):
    """✅ 回归：镜像块（xscale=-1）的虚拟几何必须保留插入点平移。

    历史缺陷：镜像展开出的虚拟实体 `extrusion=(0,0,-1)`，`get_points("xyb")` 返回的是
    该 OCS 内的坐标（即 x 取反、平移丢失）。修复方式是在 `_normalize_virtual_shape` 中
    对 LWPOLYLINE/POLYLINE 做真实的 OCS->WCS 变换。
    """
    path = write_dxf(tmp_path / "mirror_role.dxf", build_role_block_fixture_mirrored())
    insert = _reader_insert(path)

    assert insert["geometry"]["position"] == {"x": 2000.0, "y": 0.0}, "INSERT 位置本身是对的"
    points = _reader_polygon_points(insert)
    min_x, min_y, max_x, max_y = _bounds(points)

    assert (min_x, max_x) == (pytest.approx(1999.0, abs=1e-9), pytest.approx(2001.0, abs=1e-9))
    assert (min_y, max_y) == (pytest.approx(-1.0, abs=1e-9), pytest.approx(1.0, abs=1e-9))
    assert (max_x - min_x, max_y - min_y) == (pytest.approx(2.0, abs=1e-9), pytest.approx(2.0, abs=1e-9))
    # 与 ezdxf 的世界坐标逐点一致（顶点顺序可能不同）
    wcs_points = _virtual_points(_insert_by_name(path, "摄像头-方块"))
    assert sorted(_bounds(wcs_points)) == pytest.approx(sorted(_bounds(points)), abs=1e-9)


def test_reader_mirrored_block_matches_wcs_bounds_exactly(tmp_path: Path):
    """✅ 回归：镜像块任意插入点下，读取器包围盒都等于 ezdxf 的 WCS 包围盒。"""
    origin_path = write_dxf(tmp_path / "mirror_origin.dxf", _role_block_with((0.0, 0.0), xscale=-1.0))
    origin_points = _reader_polygon_points(_reader_insert(origin_path))
    origin_wcs = _virtual_points(_insert_by_name(origin_path, "摄像头-方块"))
    assert sorted(origin_points) == pytest.approx(sorted(origin_wcs), abs=1e-9)

    moved_path = write_dxf(tmp_path / "mirror_moved.dxf", _role_block_with((2000.0, 0.0), xscale=-1.0))
    moved_points = _reader_polygon_points(_reader_insert(moved_path))
    moved_wcs = _virtual_points(_insert_by_name(moved_path, "摄像头-方块"))
    assert _bounds(moved_points) == pytest.approx(_bounds(moved_wcs), abs=1e-9)
    assert _bounds(moved_points)[0] == pytest.approx(1999.0, abs=1e-9)


def test_reader_mirrored_block_arc_center_follows_insert(tmp_path: Path):
    """✅ 回归：镜像块的圆弧圆心必须落在插入点处（曾被放到 -3000）。"""
    path = write_dxf(tmp_path / "mirror_arc.dxf", _role_block_with((3000.0, 0.0), xscale=-1.0))
    insert = _reader_insert(path)

    arc = next(shape for shape in insert["cad_virtual_shapes"] if shape["geometry"]["type"] == "Arc")
    assert arc["geometry"]["center"] == {"x": 3000.0, "y": 0.0}
    # 半径与弧长不受镜像影响
    assert arc["geometry"]["radius"] == pytest.approx(0.5, rel=1e-12)
    assert arc["geometry"]["length_mm"] == pytest.approx(math.pi / 4.0, rel=1e-12)


def test_reader_non_uniform_scaled_block_virtual_shapes_are_correct(tmp_path: Path):
    """对照组（非缺陷）：非均匀缩放（xscale=3、yscale=1）的角色虚拟几何坐标**正确**。

    期望与实测一致：多边形 x ∈ [2997, 3003]（宽 6）、y ∈ [-1, 1]（高 2）；
    原本半径 0.5 的弧被 ezdxf 展开成椭圆（major 1.5、ratio 1/3），读取器按 Ellipse 输出。
    """
    path = write_dxf(tmp_path / "nuscale_role.dxf", _role_block_with((3000.0, 0.0), xscale=3.0, yscale=1.0))
    insert = _reader_insert(path)

    assert insert["geometry"]["position"] == {"x": 3000.0, "y": 0.0}
    points = _reader_polygon_points(insert)
    min_x, min_y, max_x, max_y = _bounds(points)
    assert (min_x, max_x) == (pytest.approx(2997.0, abs=1e-9), pytest.approx(3003.0, abs=1e-9))
    assert (min_y, max_y) == (pytest.approx(-1.0, abs=1e-9), pytest.approx(1.0, abs=1e-9))
    assert (max_x - min_x, max_y - min_y) == (pytest.approx(6.0, abs=1e-9), pytest.approx(2.0, abs=1e-9))

    # 非均匀缩放会让 ezdxf 把 ARC 展开成 ELLIPSE，读取器走 `_ellipse_geometry`
    ellipse = next(shape for shape in insert["cad_virtual_shapes"] if shape["geometry"]["type"] == "Ellipse")
    assert ellipse["geometry"]["center"] == {"x": 3000.0, "y": 0.0}
    assert ellipse["geometry"]["radius_major"] == pytest.approx(1.5, rel=1e-12)
    assert ellipse["geometry"]["radius_minor"] == pytest.approx(0.5, rel=1e-12)
    assert ellipse["geometry"]["ratio"] == pytest.approx(1.0 / 3.0, rel=1e-12)


def test_reader_uniform_scaled_and_rotated_virtual_shapes_are_correct(tmp_path: Path):
    """对照组：平移 / 旋转 90° 这些**没有**翻转 extrusion 的情况，读取器坐标正确。"""
    path = write_dxf(tmp_path / "role_rot.dxf", build_role_block_fixture())
    insert = _reader_insert(path)
    points = _reader_polygon_points(insert)
    # 旋转 90° 后：x ∈ [999, 1001]，y ∈ [-1, 1]
    assert _bounds(points) == (
        pytest.approx(999.0, abs=1e-9),
        pytest.approx(-1.0, abs=1e-9),
        pytest.approx(1001.0, abs=1e-9),
        pytest.approx(1.0, abs=1e-9),
    )
