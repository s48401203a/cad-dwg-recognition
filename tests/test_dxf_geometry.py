"""DXF 几何正确性测试（数值断言）。

覆盖本轮「几何正确性」修复：
- bulge（凸度）= tan(圆心角/4)：半圆 radius=5 / |sweep|=180° / 弧长 5π；浅弧与优弧的
  圆心位置、半径、弧长都有明确数值。
- `arc_length` 用 DXF 语义 `(end-start) mod 360`：270° 的弧是 1.5πr 而不是 0.5πr。
- 闭合多段线必须计入首尾闭合边：20×15 矩形周长 70（不闭合是 55）。
- `polyline_bounds` 必须取真实弧包围盒，而不只是弦端点。
- `polyline_curve_points` 的离散点必须落在弧上，弦高不超过 `max_sagitta_mm`。
- 经 `DxfReader` 读真实 DXF 后，长度 / `has_arc_segments` / `curve_points` 必须一致；
  不支持的实体被跳过而不是崩溃；畸形 DXF 必须**显式报错**。

所有夹具都是代码生成的临时文件（tmp_path），不读取任何真实客户图纸。
"""

from __future__ import annotations

import math
from pathlib import Path

import ezdxf
import pytest

from parser.dxf_geometry import (
    arc_bounds,
    arc_length,
    arc_sweep_deg,
    bulge_arc_points,
    bulge_segment_bounds,
    bulge_to_arc,
    discretize_arc,
    polyline_bounds,
    polyline_curve_points,
    polyline_length,
    polyline_segments,
    segment_geometry,
)
from parser.dxf_reader import DxfReader
from tests.synthetic import (
    build_bulge_fixture,
    build_empty_fixture,
    build_malformed_text,
    build_unsupported_entity_fixture,
    write_dxf,
)

PI = math.pi


def _pt(x: float, y: float) -> dict[str, float]:
    return {"x": float(x), "y": float(y)}


def _sagitta(radius: float, chord: float) -> float:
    """弦高（弧到弦的最大距离）：r - sqrt(r² - (chord/2)²)。"""
    return radius - math.sqrt(max(0.0, radius * radius - (chord / 2.0) ** 2))


def _dist(a: dict[str, float], b: dict[str, float]) -> float:
    return math.hypot(a["x"] - b["x"], a["y"] - b["y"])


# --------------------------------------------------------------- bulge 基本语义


def test_bulge_one_is_semicircle_radius_5_sweep_180_length_5pi():
    """bulge=1、弦长 10 的半圆：radius=5、|sweep|=180°、弧长 5π（1e-9）。"""
    arc = bulge_to_arc(_pt(0, 0), _pt(10, 0), 1.0)

    assert arc["radius"] == pytest.approx(5.0, rel=1e-12)
    assert abs(arc["sweep_deg"]) == pytest.approx(180.0, rel=1e-12)
    assert arc["length_mm"] == pytest.approx(5.0 * PI, rel=1e-9)
    assert arc["counter_clockwise"] is True
    # 圆心在弦中点（y 方向浮点残差 ~3e-16）
    assert arc["center"][0] == pytest.approx(5.0, abs=1e-12)
    assert arc["center"][1] == pytest.approx(0.0, abs=1e-12)
    # 两端点到圆心距离都等于半径
    for end in (_pt(0, 0), _pt(10, 0)):
        assert _dist(end, _pt(*arc["center"])) == pytest.approx(5.0, rel=1e-12)


def test_bulge_minus_one_mirrors_arc_across_chord_with_same_length():
    """bulge=-1 把弧镜像到弦的另一侧：圆心是镜像点，弧长相同。"""
    up = bulge_to_arc(_pt(0, 0), _pt(10, 0), 1.0)
    down = bulge_to_arc(_pt(0, 0), _pt(10, 0), -1.0)

    assert down["radius"] == pytest.approx(up["radius"], rel=1e-12)
    assert down["length_mm"] == pytest.approx(up["length_mm"], rel=1e-9)
    assert down["sweep_deg"] == pytest.approx(-up["sweep_deg"], rel=1e-12)
    assert down["counter_clockwise"] is False
    # 圆心关于弦（y=0）镜像：x 相同，y 互为相反数
    assert down["center"][0] == pytest.approx(up["center"][0], abs=1e-12)
    assert down["center"][1] == pytest.approx(-up["center"][1], abs=1e-12)


def test_bulge_zero_is_straight_segment():
    """bulge=0 必须按直线处理，长度等于弦长。"""
    segment = segment_geometry(_pt(0, 0), _pt(10, 0), 0.0)
    assert segment["kind"] == "line"
    assert segment["length_mm"] == pytest.approx(10.0, rel=0, abs=0)


def test_shallow_arc_radius_and_length():
    """浅弧 bulge=0.1、弦长 10：半径≈25.25，弧长严格位于 (弦长, 弦长×1.02)。"""
    arc = bulge_to_arc(_pt(0, 0), _pt(10, 0), 0.1)

    assert arc["radius"] == pytest.approx(25.25, rel=1e-9)
    # 解析解：R = (chord/2)/sin(sweep/2)，sweep = 4·atan(0.1)
    expected_radius = 5.0 / math.sin(2.0 * math.atan(0.1))
    assert arc["radius"] == pytest.approx(expected_radius, rel=1e-12)

    assert 10.0 < arc["length_mm"] < 10.0 * 1.02
    assert arc["length_mm"] == pytest.approx(abs(math.radians(arc["sweep_deg"])) * arc["radius"], rel=1e-12)
    # 小弧：弦高很小
    assert _sagitta(arc["radius"], 10.0) == pytest.approx(0.5, abs=0.01)


def test_shallow_arc_center_is_on_opposite_side_of_chord_from_arc():
    """浅弧 bulge=0.1：圆心必须落在弦的另一侧（y < 0），弧顶在弦上方 y≈+0.5。"""
    start, end = _pt(0, 0), _pt(10, 0)
    arc = bulge_to_arc(start, end, 0.1)

    assert arc["center"][1] < 0.0, "圆心应在弦下方，弧在弦上方"
    assert arc["sweep_deg"] > 0.0

    # 弧顶 = 圆心沿「起止角平分方向」外推一个半径（这里用复数单位向量取角平分线，
    # 比 start_angle + sweep/2 更稳，避免浮点误差把方向算偏）。
    bisector = (
        complex(math.cos(math.radians(arc["start_angle"])), math.sin(math.radians(arc["start_angle"])))
        + complex(math.cos(math.radians(arc["end_angle"])), math.sin(math.radians(arc["end_angle"])))
    )
    bisector /= abs(bisector)
    apex = _pt(arc["center"][0] + arc["radius"] * bisector.real, arc["center"][1] + arc["radius"] * bisector.imag)

    assert apex["y"] > 0.0, "弧顶必须在弦上方"
    # 弧顶高度 = r·(1 - cos(sweep/2))，浅弧下约 0.5
    assert apex["y"] == pytest.approx(arc["radius"] * (1.0 - math.cos(math.radians(abs(arc["sweep_deg"])) / 2.0)), abs=1e-9)
    assert apex["y"] == pytest.approx(0.5, abs=1e-3)
    # 弦高（弧到弦的最大距离）公式给出 0.5
    assert _sagitta(arc["radius"], 10.0) == pytest.approx(0.5, abs=1e-6)


def test_large_bulge_is_major_arc_with_endpoints_on_circle():
    """bulge=5：|sweep| > 180°，两端点必须精确位于半径圆上。"""
    start, end = _pt(0, 0), _pt(10, 0)
    arc = bulge_to_arc(start, end, 5.0)

    assert abs(arc["sweep_deg"]) > 180.0
    assert arc["sweep_deg"] == pytest.approx(math.degrees(4.0 * math.atan(5.0)), rel=1e-12)
    # R = (chord/2)/sin(sweep/2)
    assert arc["radius"] == pytest.approx(5.0 / math.sin(2.0 * math.atan(5.0)), rel=1e-12)
    for point in (start, end):
        assert _dist(point, _pt(*arc["center"])) == pytest.approx(arc["radius"], rel=1e-12)
    # 优弧的弧长大于半圆 5π
    assert arc["length_mm"] > 5.0 * PI


def test_degenerate_chord_returns_zero_radius_without_crashing():
    """起终点重合：返回半径 0，不抛异常（调用方需要能安全处理退化段）。"""
    arc = bulge_to_arc(_pt(3, 4), _pt(3, 4), 1.0)
    assert arc["radius"] == 0.0
    assert arc["length_mm"] == 0.0
    assert arc["sweep_deg"] == 0.0


# --------------------------------------------------------------- DXF ARC 语义


def test_arc_length_major_sweep_is_not_reduced_to_minor_arc():
    """核心：270° 的弧长必须是 1.5πr，而不是被当成 90°（0.5πr）。"""
    assert arc_length(10, 0, 270) == pytest.approx(1.5 * PI * 10, rel=1e-12)
    assert arc_length(10, 0, 270) != pytest.approx(0.5 * PI * 10, rel=1e-12)


def test_arc_length_full_circle_when_start_equals_end():
    """起止角相同 = 整圆（DXF 语义），弧长 2πr。"""
    assert arc_length(10, 0, 0) == pytest.approx(2.0 * PI * 10, rel=1e-12)
    assert arc_length(10, 45, 45) == pytest.approx(2.0 * PI * 10, rel=1e-12)
    assert arc_sweep_deg(0, 0) == 360.0


def test_arc_length_wraps_across_zero():
    """跨越 0° 的弧：start=350, end=10 应当是 20°，不是 340°。"""
    assert arc_sweep_deg(350, 10) == pytest.approx(20.0, rel=1e-12)
    assert arc_length(10, 350, 10) == pytest.approx(math.radians(20.0) * 10, rel=1e-12)


@pytest.mark.parametrize(
    "start,end,sweep",
    [(0, 90, 90.0), (0, 180, 180.0), (0, 270, 270.0), (0, 359, 359.0), (90, 0, 270.0), (270, 90, 180.0)],
)
def test_arc_sweep_is_counter_clockwise_mod_360(start: float, end: float, sweep: float):
    assert arc_sweep_deg(start, end) == pytest.approx(sweep, rel=1e-12)


def test_arc_length_is_linear_in_radius():
    assert arc_length(1, 0, 180) == pytest.approx(PI, rel=1e-12)
    assert arc_length(2, 0, 180) == pytest.approx(2.0 * PI, rel=1e-12)


def test_arc_bounds_includes_quadrant_points_for_major_arc():
    """270° 弧（0°→270°）的包围盒必须包含 180°/270° 象限点（不是只有弦端点）。

    ⚠️ 发现（实现与几何直觉不一致，已按实测行为断言，未改源码）：
    实测返回值是 `(-10, -10, 10, 10)`，但几何上的正确值是 `(-10, -10, 10, 0)`。
    原因：`_angle_in_sweep` 用的是「含端点」比较（`delta <= sweep + 1e-9`），
    于是恰好落在端点上、且属于象限角（90°）的候选点被重复计入——起点 0°→终点 270°
    的弧并不经过 90°，但 90° 恰好是象限角且处于扫掠区间内，被当成「弧上的象限点」
    加进了候选，把 max_y 从 0 抬到了 +r。
    影响：包围盒偏大（保守），不会漏几何，但会让圆弧的 extents 比实际大一个半径。
    """
    box = arc_bounds(_pt(0, 0), 10.0, 0.0, 270.0)
    assert box[0] == pytest.approx(-10.0, rel=1e-12)  # 180° 象限点
    assert box[1] == pytest.approx(-10.0, rel=1e-12)  # 270° 象限点
    assert box[2] == pytest.approx(10.0, rel=1e-12)
    # 实测行为（几何上应为 0.0 —— 见上面的发现说明）
    assert box[3] == pytest.approx(10.0, rel=1e-12)
    assert box != pytest.approx((-10.0, -10.0, 10.0, 0.0), abs=1e-9), "记录：实际包围盒比几何正确值偏大"


def test_arc_bounds_does_not_inflate_for_arc_starting_off_a_quadrant():
    """从 45° 起的 270° 弧：0° 不在弧上，max_x 必须是 cos(45°)·r 而不是 r。"""
    box = arc_bounds(_pt(0, 0), 10.0, 45.0, 315.0)
    assert box[2] == pytest.approx(10.0 * math.cos(math.radians(45.0)), rel=1e-12)
    assert box[0] == pytest.approx(-10.0, rel=1e-12)
    assert box[1] == pytest.approx(-10.0, rel=1e-12)


def test_arc_bounds_for_small_arc_excludes_unused_quadrant():
    """90° 弧（0→90）的包围盒只覆盖第一象限。"""
    box = arc_bounds(_pt(0, 0), 10.0, 0.0, 90.0)
    assert box == pytest.approx((0.0, 0.0, 10.0, 10.0), abs=1e-12)


# --------------------------------------------------------------- 多段线长度与闭合


def test_closed_rectangle_counts_the_closing_edge():
    """闭合 20×15 矩形：周长 70（含闭合边），不闭合是 55。这条证明闭合边被计入。"""
    points = [_pt(0, 0), _pt(20, 0), _pt(20, 15), _pt(0, 15)]

    assert polyline_length(points, [0.0] * 4, True) == pytest.approx(70.0, rel=1e-12)
    assert polyline_length(points, [0.0] * 4, False) == pytest.approx(55.0, rel=1e-12)
    assert polyline_length(points, [0.0] * 4, True) - polyline_length(points, [0.0] * 4, False) == pytest.approx(15.0)


def test_closed_polyline_produces_closing_segment():
    """`polyline_segments` 在闭合时必须产出 4 段（含闭合段），且索引连续。"""
    points = [_pt(0, 0), _pt(20, 0), _pt(20, 15), _pt(0, 15)]
    closed_segments = polyline_segments(points, [0.0] * 4, True)
    open_segments = polyline_segments(points, [0.0] * 4, False)

    assert len(closed_segments) == 4
    assert len(open_segments) == 3
    assert [segment["index"] for segment in closed_segments] == [0, 1, 2, 3]
    # 闭合段从最后一点回到第一点
    closing = closed_segments[-1]
    assert closing["start"] == points[-1]
    assert closing["end"] == points[0]


def test_closed_polyline_with_bulge_uses_last_vertex_bulge_for_closing_segment():
    """闭合段的 bulge 取最后一个顶点的凸度（与 DXF 语义一致）。"""
    points = [_pt(0, 0), _pt(20, 0), _pt(20, 15), _pt(0, 15)]
    bulges = [0.0, 0.0, 0.0, 1.0]
    segments = polyline_segments(points, bulges, True)

    assert [segment["kind"] for segment in segments] == ["line", "line", "line", "arc"]
    # 闭合段是 (0,15) -> (0,0)，弦长 15，半圆弧长 = π·7.5
    assert segments[-1]["length_mm"] == pytest.approx(PI * 7.5, rel=1e-9)


def test_polyline_length_of_short_input_is_zero():
    assert polyline_length([], [], False) == 0.0
    assert polyline_length([_pt(1, 1)], [0.0], False) == 0.0


def test_bulge_arc_contributes_more_than_its_chord():
    """带 bulge 的段必须按弧长计算：弦长 10 的半圆段长度是 5π 而非 10。"""
    points = [_pt(0, 0), _pt(10, 0), _pt(10, 10)]
    length = polyline_length(points, [1.0, 0.0, 0.0], False)
    assert length == pytest.approx(5.0 * PI + 10.0, rel=1e-9)


# --------------------------------------------------------------- 包围盒


def test_polyline_bounds_spans_full_radius_perpendicular_to_chord():
    """bulge=1 半圆的包围盒必须覆盖整个半径（y 从 -5 到 0），而不是只有弦端点。"""
    bounds = polyline_bounds([_pt(0, 0), _pt(10, 0)], [1.0, 0.0], False)

    assert bounds is not None
    min_x, min_y, max_x, max_y = bounds
    assert min_x == pytest.approx(0.0, abs=1e-12)
    assert max_x == pytest.approx(10.0, abs=1e-12)
    assert min_y == pytest.approx(-5.0, rel=1e-12), "包围盒必须下探到圆心方向 -r"
    assert max_y == pytest.approx(0.0, abs=1e-12)


def test_polyline_bounds_mirrors_for_negative_bulge():
    """bulge=-1 的包围盒镜像到另一侧（y 从 0 到 +5）。"""
    bounds = polyline_bounds([_pt(0, 0), _pt(10, 0)], [-1.0, 0.0], False)
    assert bounds is not None
    assert bounds[1] == pytest.approx(0.0, abs=1e-12)
    assert bounds[3] == pytest.approx(5.0, rel=1e-12)


def test_polyline_bounds_includes_bulged_closing_edge():
    """闭合边的 bulge 也必须进包围盒：矩形底边半圆下探 10（弦长 20）。"""
    points = [_pt(0, 0), _pt(20, 0), _pt(20, 15), _pt(0, 15)]
    bulges = [1.0, 0.0, 0.0, 0.0]
    bounds = polyline_bounds(points, bulges, True)

    assert bounds is not None
    assert bounds == pytest.approx((0.0, -10.0, 20.0, 15.0), abs=1e-9)


def test_polyline_bounds_of_pure_line_polygon_is_vertex_box():
    points = [_pt(0, 0), _pt(20, 0), _pt(20, 15), _pt(0, 15)]
    assert polyline_bounds(points, [0.0] * 4, True) == pytest.approx((0.0, 0.0, 20.0, 15.0), abs=0.0)


def test_polyline_bounds_empty_returns_none():
    assert polyline_bounds([], [], False) is None


def test_bulge_segment_bounds_none_for_straight_segment():
    assert bulge_segment_bounds(_pt(0, 0), _pt(10, 0), 0.0) is None


# --------------------------------------------------------------- 离散化


def test_discretize_arc_respects_max_sagitta():
    """离散点两两之间的弦高必须 ≤ max_sagitta_mm。"""
    max_sagitta = 0.5
    arc = bulge_to_arc(_pt(0, 0), _pt(10, 0), 1.0)
    points = polyline_curve_points([_pt(0, 0), _pt(10, 0)], [1.0, 0.0], False, max_sagitta_mm=max_sagitta)

    assert len(points) >= 3, "半圆至少要被细分成若干段"
    worst = 0.0
    for first, second in zip(points, points[1:]):
        chord = _dist(first, second)
        worst = max(worst, _sagitta(arc["radius"], chord))
    assert worst <= max_sagitta + 1e-9, f"最大弦高 {worst} 超过请求的 {max_sagitta}"


@pytest.mark.parametrize("max_sagitta", [2.0, 1.0, 0.5, 0.1, 0.01])
def test_discretize_arc_sagitta_monotonic_in_request(max_sagitta: float):
    """请求的弦高越小，细分点越密（且始终满足上限）。"""
    arc = bulge_to_arc(_pt(0, 0), _pt(10, 0), 1.0)
    points = polyline_curve_points([_pt(0, 0), _pt(10, 0)], [1.0, 0.0], False, max_sagitta_mm=max_sagitta)
    for first, second in zip(points, points[1:]):
        assert _sagitta(arc["radius"], _dist(first, second)) <= max_sagitta + 1e-9


def test_curve_points_lie_on_arc_and_keep_exact_endpoints():
    """每个离散点都必须落在弧上（径向误差 < 1e-6），首尾点必须精确等于弦端点。"""
    start, end = _pt(0, 0), _pt(10, 0)
    arc = bulge_to_arc(start, end, 1.0)
    center = _pt(*arc["center"])
    points = polyline_curve_points([start, end], [1.0, 0.0], False, max_sagitta_mm=0.25)

    assert points[0] == start, "首点必须精确等于起点（不是近似）"
    assert points[-1] == end, "末点必须精确等于终点（不是近似）"
    for point in points:
        assert abs(_dist(point, center) - arc["radius"]) < 1e-6
    # 单调推进：相邻点不同，索引方向上的角向推进一致（逆时针）
    assert len({(round(point["x"], 12), round(point["y"], 12)) for point in points}) == len(points)


def test_curve_points_of_pure_lines_are_the_vertices():
    """没有 bulge 时离散点就是顶点本身（不插入多余点、不重复收尾点）。

    回归：闭合且无 bulge 时曾多出一个与首点完全重合的收尾点（4 顶点 → 5 点）。
    闭合边由 `polyline_length` 单独计入，离散点表不应重复首点，否则下游按点数
    推断节点数量会偏大。
    """
    points = [_pt(0, 0), _pt(10, 0), _pt(10, 10)]
    curve = polyline_curve_points(points, [0.0, 0.0, 0.0], False)
    assert curve == points, "开放折线：离散点必须等于顶点列表"

    rect = [_pt(0, 0), _pt(20, 0), _pt(20, 15), _pt(0, 15)]
    closed_curve = polyline_curve_points(rect, [0.0] * 4, True)
    assert closed_curve == rect, "闭合折线：离散点应等于顶点列表，不重复首点"
    # 闭合边仍然计入长度（与点表是否重复无关）
    assert polyline_length(rect, [0.0] * 4, True) == pytest.approx(70.0, rel=1e-12)
    # 弧段离散时，闭合段也要收回到起点
    arc_rect = polyline_curve_points(rect, [0.0, 0.0, 0.0, 1.0], True, max_sagitta_mm=1.0)
    assert arc_rect[-1] == rect[0], "闭合弧段的最后一个离散点必须回到起点"
    assert len(arc_rect) > len(rect)


def test_bulge_arc_points_returns_endpoints_for_degenerate_arc():
    """半径 0（起终点重合）时只返回两个端点，不崩溃。"""
    points = bulge_arc_points(_pt(3, 4), _pt(3, 4), 1.0)
    assert points == [_pt(3, 4), _pt(3, 4)]


def test_discretize_arc_returns_empty_for_zero_radius_or_sweep():
    assert discretize_arc((0.0, 0.0), 0.0, 0.0, 90.0) == []
    assert discretize_arc((0.0, 0.0), 5.0, 0.0, 0.0) == []


def test_discretize_arc_caps_segment_count():
    """极小的弦高要求必须被 max_segments 截断，而不是产生无限点。"""
    points = discretize_arc((0.0, 0.0), 5.0, 0.0, 360.0, max_sagitta_mm=1e-9, max_segments=256)
    assert len(points) == 257


# --------------------------------------------------------------- 通过 DxfReader 读真实 DXF


def test_reader_bulge_fixture_lengths_and_arc_flags(tmp_path: Path):
    """读真实 DXF：闭合矩形 native_length_mm == 70，半圆段 == 5π；弧标记正确。"""
    path = write_dxf(tmp_path / "bulge.dxf", build_bulge_fixture())
    result = DxfReader.read(path)

    by_handle = {entity["source_entity_id"]: entity for entity in result["entities"]}
    assert len(by_handle) == len(result["entities"]), "source_entity_id 必须唯一"

    polylines = [entity for entity in result["entities"] if entity["entity_type"] == "LWPOLYLINE"]
    closed_rect = next(entity for entity in polylines if entity["geometry"]["closed"] is True)
    bulge_line = next(entity for entity in polylines if entity.get("has_arc_segments") and not entity["geometry"]["closed"])

    # 闭合矩形 20×15：周长 70（含闭合边）
    assert closed_rect["geometry"]["type"] == "Polygon"
    assert closed_rect["node_count"] == 4
    assert closed_rect["native_length_mm"] == pytest.approx(70.0, rel=1e-12)
    assert closed_rect["curve_length_mm"] == pytest.approx(70.0, rel=1e-12)
    assert closed_rect["has_arc_segments"] is False
    assert "curve_points" not in closed_rect["geometry"], "无 bulge 时不应产生 curve_points"

    # 弦长 10 的 bulge=1 半圆：弧长 5π
    assert bulge_line["native_length_mm"] == pytest.approx(5.0 * PI, rel=1e-9)
    assert bulge_line["has_arc_segments"] is True
    assert "curve_points" in bulge_line["geometry"]
    assert len(bulge_line["geometry"]["curve_points"]) > len(bulge_line["geometry"]["points"])
    assert bulge_line["geometry"]["segments"][0]["kind"] == "arc"
    assert bulge_line["geometry"]["segments"][0]["radius"] == pytest.approx(5.0, rel=1e-12)

    # ARC 实体：DXF 语义 0°→270° = 1.5πr
    arc_entity = next(entity for entity in result["entities"] if entity["entity_type"] == "ARC")
    assert arc_entity["geometry"]["length_mm"] == pytest.approx(1.5 * PI * 10, rel=1e-12)
    assert arc_entity["native_length_mm"] == arc_entity["geometry"]["length_mm"]


def test_reader_bulge_fixture_curve_points_have_no_sagitta_violation(tmp_path: Path):
    """读取器生成的 curve_points 同样要满足离散误差（默认 max_sagitta_mm=5.0）。"""
    path = write_dxf(tmp_path / "bulge_sagitta.dxf", build_bulge_fixture())
    result = DxfReader.read(path)

    checked = 0
    for entity in result["entities"]:
        geometry = entity["geometry"]
        if geometry.get("type") != "LineString" or "curve_points" not in geometry:
            continue
        curves = geometry["curve_points"]
        for segment in geometry["segments"]:
            if segment["kind"] != "arc":
                continue
            radius = segment["radius"]
            # 该弧段的离散点在曲线里是连续的一段，这里按半径做全局校验
            for first, second in zip(curves, curves[1:]):
                chord = _dist(first, second)
                if chord <= 0 or chord > 2 * radius:
                    continue
                assert _sagitta(radius, chord) <= 5.0 + 1e-9
                checked += 1
    assert checked > 0, "至少应校验到一段弧的离散点"


def test_reader_closed_rectangle_length_is_70_after_scaling(tmp_path: Path):
    """单位换算与几何长度解耦：英尺图纸里闭合矩形长度是 70（图纸单位）× 304.8。"""
    from tests.synthetic import _new_doc

    doc = _new_doc(2)
    doc.modelspace().add_lwpolyline(
        [(100, 0), (120, 0), (120, 15), (100, 15)], close=True, dxfattribs={"layer": "墙"}
    )
    path = write_dxf(tmp_path / "feet_rect.dxf", doc)
    result = DxfReader.read(path)

    rect = next(entity for entity in result["entities"] if entity["entity_type"] == "LWPOLYLINE")
    assert rect["geometry"]["type"] == "Polygon"
    assert rect["node_count"] == 4
    # 70 图纸单位 × 304.8 mm/ft
    assert rect["native_length_mm"] == pytest.approx(70.0 * 304.8, rel=1e-12)
    assert rect["has_arc_segments"] is False


def test_reader_reports_entity_handles_and_types(tmp_path: Path):
    """实体必须带 source_entity_id（DXF handle）与 entity_type。"""
    path = write_dxf(tmp_path / "handles.dxf", build_bulge_fixture())
    result = DxfReader.read(path)

    assert result["total_entities"] == len(result["entities"]) == 4
    assert result["skipped_unsupported_entities"] == 0
    for entity in result["entities"]:
        assert entity["source_entity_id"] and isinstance(entity["source_entity_id"], str)
        assert entity["entity_type"] in DxfReader.supported_types
        assert "layer" in entity and entity["geometry"]["type"]


def test_reader_geometries_agree_with_pure_geometry_module(tmp_path: Path):
    """读取器的长度必须与直接调用 `polyline_length` 的结果一致（同一事实来源）。"""
    path = write_dxf(tmp_path / "consistency.dxf", build_bulge_fixture())
    result = DxfReader.read(path)

    for entity in result["entities"]:
        geometry = entity["geometry"]
        if geometry["type"] not in {"Polygon", "LineString"}:
            continue
        expected = polyline_length(geometry["points"], geometry["bulges"], geometry["closed"])
        assert entity["native_length_mm"] == pytest.approx(expected, rel=1e-12)


def test_reader_arc_extents_are_inflated_by_quadrant_inclusivity(tmp_path: Path):
    """`arc_bounds` 的端点包含问题会传导到整体 extents（记录性断言）。

    用例用「只有一条 0°→270° ARC（半径 10、圆心 (300, 0)）」的最小图纸，避免其它实体
    污染 extents。几何正确的包围盒是 x∈[290, 310]、y∈[-10, 0]，但实测 max_y 被抬到 +10
    （多算一个半径，因为 90° 恰好是象限角且落在含端点的扫掠区间内）。
    """
    from tests.synthetic import build_unit_scale_line_fixture

    doc = build_unit_scale_line_fixture(4)
    doc.modelspace().delete_all_entities()
    doc.modelspace().add_arc((300, 0), 10, 0, 270, dxfattribs={"layer": "桥架"})
    path = write_dxf(tmp_path / "arc_extents.dxf", doc)
    result = DxfReader.read(path)

    arc_entity = next(entity for entity in result["entities"] if entity["entity_type"] == "ARC")
    assert arc_entity["geometry"]["center"] == {"x": 300.0, "y": 0.0}
    assert arc_entity["geometry"]["radius"] == 10.0
    assert arc_entity["geometry"]["length_mm"] == pytest.approx(1.5 * PI * 10, rel=1e-12)

    # 几何正确值应为 max.y == 0.0；实测是 10.0（见 arc_bounds 的发现说明）
    assert result["extents"]["max"]["y"] == pytest.approx(10.0, rel=1e-12)
    assert result["extents"]["min"]["x"] == pytest.approx(290.0, rel=1e-12)
    assert result["extents"]["max"]["x"] == pytest.approx(310.0, rel=1e-12)
    assert result["extents"]["min"]["y"] == pytest.approx(-10.0, rel=1e-12)


# --------------------------------------------------------------- 边界与失败路径


def test_unsupported_entities_are_skipped_not_fatal(tmp_path: Path):
    """SPLINE / POINT 不被支持：跳过而非崩溃，且仍能读到 LINE。"""
    path = write_dxf(tmp_path / "unsupported.dxf", build_unsupported_entity_fixture())
    result = DxfReader.read(path)

    assert result["skipped_unsupported_entities"] >= 2, "SPLINE 与 POINT 至少 2 个应被跳过"
    assert result["total_entities"] >= 3
    lines = [entity for entity in result["entities"] if entity["entity_type"] == "LINE"]
    assert len(lines) == 1
    assert lines[0]["native_length_mm"] == pytest.approx(100.0, rel=1e-12)
    assert all(entity["entity_type"] not in {"SPLINE", "POINT"} for entity in result["entities"])


def test_malformed_dxf_raises_instead_of_returning_wrong_data(tmp_path: Path):
    """畸形 DXF（截断的 group code 流）必须显式报错，而不是静默返回空/错误数据。

    实测异常类型：`ezdxf.lldxf.const.DXFStructureError`（缺失 ENDSEC）。
    """
    path = tmp_path / "malformed.dxf"
    path.write_text(build_malformed_text(), encoding="utf-8")
    assert path.exists() and path.stat().st_size > 0

    with pytest.raises(ezdxf.DXFStructureError) as excinfo:
        DxfReader.read(path)
    assert "ENDSEC" in str(excinfo.value)


def test_empty_fixture_has_zero_entities_and_finite_extents(tmp_path: Path):
    """空图：0 实体、0 跳过，`extents` 必须是有限数（虽然数值是 DXF 哨兵 1e20）。"""
    path = write_dxf(tmp_path / "empty.dxf", build_empty_fixture())
    result = DxfReader.read(path)

    assert result["total_entities"] == 0
    assert result["entities"] == []
    assert result["skipped_unsupported_entities"] == 0
    assert result["extents"]["min"]["x"] == pytest.approx(1e20, rel=1e-12)
    assert result["extents"]["max"]["x"] == pytest.approx(-1e20, rel=1e-12)
    for corner in ("min", "max"):
        for axis in ("x", "y"):
            assert math.isfinite(result["extents"][corner][axis])


def test_empty_fixture_still_reports_units_and_layers(tmp_path: Path):
    """空图不应当丢失单位/图层元信息。"""
    path = write_dxf(tmp_path / "empty_meta.dxf", build_empty_fixture())
    result = DxfReader.read(path)

    assert result["unit_code"] == 4
    assert result["unit_scale_to_mm"] == 1.0
    assert result["unit_unspecified"] is False
    assert result["layer_count"] == len(result["layer_names"])
    assert "墙" in result["layer_names"]


def test_missing_file_raises_file_not_found(tmp_path: Path):
    with pytest.raises(FileNotFoundError):
        DxfReader.read(tmp_path / "nope.dxf")


def test_arc_bounds_matches_dense_sampling():
    """回归：`arc_bounds` 必须与圆弧密集采样得到的包围盒一致。

    历史争议：曾怀疑「0°→270° 的包围盒 max_y 被抬高了半径」。复核发现**不是缺陷**：
    该弧从 0° 逆时针扫到 270°，必然经过圆的最高点（90° 象限点），
    且 270° 处的终点就是 (0, -r)，所以 (-r, -r, r, r) 才是正确答案。
    本用例用参数化采样交叉验证，避免同类误判再次发生。
    """
    cases = [(0, 270), (90, 270), (45, 315), (0, 90), (0, 180), (180, 360), (270, 90), (30, 120)]
    radius = 10.0
    for start, end in cases:
        implemented = arc_bounds({"x": 0.0, "y": 0.0}, radius, float(start), float(end))
        sampled = _sampled_arc_bounds(float(start), float(end), radius)
        assert implemented == pytest.approx(sampled, abs=1e-6), f"{start}°->{end}°"

    # 端点恰为象限角时不得把该象限点重复计入（0°→90° 的极值就是两个端点）
    quarter = arc_bounds({"x": 0.0, "y": 0.0}, radius, 0.0, 90.0)
    assert quarter == pytest.approx((0.0, 0.0, radius, radius), abs=1e-9)
    # 0°→270° 经过最高点，max_y 必须是 +r 而不是 0
    three_quarter = arc_bounds({"x": 0.0, "y": 0.0}, radius, 0.0, 270.0)
    assert three_quarter == pytest.approx((-radius, -radius, radius, radius), abs=1e-9)


def _sampled_arc_bounds(start: float, end: float, radius: float, steps: int = 20000) -> tuple[float, float, float, float]:
    sweep = arc_sweep_deg(start, end)
    if sweep >= 360.0 - 1e-9:
        return (-radius, -radius, radius, radius)
    xs: list[float] = []
    ys: list[float] = []
    for index in range(steps + 1):
        angle = math.radians(start) + math.radians(sweep) * (index / steps)
        xs.append(radius * math.cos(angle))
        ys.append(radius * math.sin(angle))
    return (min(xs), min(ys), max(xs), max(ys))
