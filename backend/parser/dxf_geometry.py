"""DXF 曲线几何：多段线 bulge、闭合边、圆弧长度与包围盒。

为什么需要独立模块：
- 只按顶点连直线会低估长度（半圆被算成弦长），并让预览把弧画成弦。
- 闭合多段线容易漏掉最后一段（首尾相连那条边）。
- 单位换算、长度统计、预览离散化都需要同一份几何事实。

本模块只依赖数学库，便于单测；返回的 `segments` 结构可供前端做曲线渲染。
"""

from __future__ import annotations

from math import acos, atan, atan2, ceil, cos, degrees, hypot, pi, radians, sin, tan
from typing import Any

Point = dict[str, float]


def polyline_segments(points: list[Point], bulges: list[float], closed: bool) -> list[dict[str, Any]]:
    """把多段线拆成线段/圆弧段描述。

    `bulges[i]` 描述从 `points[i]` 到 `points[i+1]` 的凸度；`closed=True` 时会额外
    生成首尾闭合段（其 bulge 取最后一个顶点的凸度）。
    """
    count = len(points)
    if count < 2:
        return []
    segments: list[dict[str, Any]] = []
    pair_count = count if closed else count - 1
    for index in range(pair_count):
        start = points[index]
        end = points[(index + 1) % count]
        bulge = float(bulges[index]) if index < len(bulges) and bulges[index] is not None else 0.0
        segment = segment_geometry(start, end, bulge)
        segment["index"] = index
        segments.append(segment)
    return segments


def segment_geometry(start: Point, end: Point, bulge: float) -> dict[str, Any]:
    """单段的几何描述。bulge 为 0 时是直线段。"""
    chord = hypot(end["x"] - start["x"], end["y"] - start["y"])
    if not bulge or chord <= 0.0:
        return {
            "kind": "line",
            "start": {"x": start["x"], "y": start["y"]},
            "end": {"x": end["x"], "y": end["y"]},
            "bulge": float(bulge or 0.0),
            "length_mm": chord,
        }
    arc = bulge_to_arc(start, end, bulge)
    return {
        "kind": "arc",
        "start": {"x": start["x"], "y": start["y"]},
        "end": {"x": end["x"], "y": end["y"]},
        "bulge": float(bulge),
        "center": {"x": arc["center"][0], "y": arc["center"][1]},
        "radius": arc["radius"],
        "start_angle": arc["start_angle"],
        "end_angle": arc["end_angle"],
        "sweep_deg": arc["sweep_deg"],
        "counter_clockwise": arc["counter_clockwise"],
        "length_mm": arc["length_mm"],
    }


def bulge_to_arc(start: Point, end: Point, bulge: float) -> dict[str, Any]:
    """凸度 -> 圆弧参数。

    bulge = tan(圆心角/4)，正值表示逆时针。返回圆心、半径、起止角与弧长。
    """
    chord = hypot(end["x"] - start["x"], end["y"] - start["y"])
    if chord <= 0.0:
        return {
            "center": (start["x"], start["y"]),
            "radius": 0.0,
            "start_angle": 0.0,
            "end_angle": 0.0,
            "sweep_deg": 0.0,
            "counter_clockwise": bulge > 0,
            "length_mm": 0.0,
        }

    sweep = 4.0 * atan(float(bulge))  # 有符号圆心角
    half = abs(sweep) / 2.0
    radius = chord / (2.0 * sin(half)) if abs(sin(half)) > 1e-12 else float("inf")
    # 圆心到弦的带符号垂距。由 R = chord/(2·sin(θ/2)) 与 R - d = chord/(2·tan(θ/2))
    # 得 d = -chord/(2·tan(θ/2))，法线取弦逆时针旋转 90°。
    tangent = tan(half)
    offset = -chord / (2.0 * tangent) if abs(tangent) > 1e-12 else 0.0
    if sweep < 0:
        offset = -offset
    ux = (end["x"] - start["x"]) / chord
    uy = (end["y"] - start["y"]) / chord
    nx, ny = -uy, ux
    center_x = (start["x"] + end["x"]) / 2.0 + nx * offset
    center_y = (start["y"] + end["y"]) / 2.0 + ny * offset

    start_angle = degrees(atan2(start["y"] - center_y, start["x"] - center_x)) % 360.0
    end_angle = degrees(atan2(end["y"] - center_y, end["x"] - center_x)) % 360.0
    return {
        "center": (center_x, center_y),
        "radius": radius,
        "start_angle": start_angle,
        "end_angle": end_angle,
        "sweep_deg": degrees(sweep),
        "counter_clockwise": bulge > 0,
        "length_mm": abs(sweep) * radius,
    }


def discretize_arc(
    center: tuple[float, float] | Point,
    radius: float,
    start_angle: float,
    sweep_deg: float,
    *,
    max_sagitta_mm: float = 5.0,
    min_segments: int = 2,
    max_segments: int = 256,
) -> list[Point]:
    """把圆弧离散为折线点（含端点），弦高误差不超过 `max_sagitta_mm`。"""
    if radius <= 0.0 or abs(sweep_deg) < 1e-9:
        return []
    cx, cy = _center_pair(center)
    sweep_rad = abs(radians(sweep_deg))
    if max_sagitta_mm <= 0.0 or max_sagitta_mm >= radius:
        steps = min_segments
    else:
        # sagitta = r(1-cos(theta/2)) -> theta = 2*acos(1 - s/r)
        ratio = max(-1.0, min(1.0, 1.0 - max_sagitta_mm / radius))
        theta = 2.0 * acos(ratio)
        steps = int(ceil(sweep_rad / theta)) if theta > 1e-9 else max_segments
    steps = max(min_segments, min(max_segments, steps))
    sign = 1.0 if sweep_deg >= 0 else -1.0
    start_rad = radians(start_angle)
    points: list[Point] = []
    for index in range(steps + 1):
        angle = start_rad + sign * sweep_rad * (index / steps)
        points.append({"x": cx + radius * cos(angle), "y": cy + radius * sin(angle)})
    return points


def _center_pair(center: Any) -> tuple[float, float]:
    if isinstance(center, dict):
        return float(center["x"]), float(center["y"])
    return float(center[0]), float(center[1])


def bulge_arc_points(start: Point, end: Point, bulge: float, *, max_sagitta_mm: float = 5.0) -> list[Point]:
    """单段圆弧的离散点（含起点与终点）。"""
    arc = bulge_to_arc(start, end, bulge)
    if arc["radius"] <= 0.0 or abs(arc["sweep_deg"]) < 1e-9:
        return [{"x": start["x"], "y": start["y"]}, {"x": end["x"], "y": end["y"]}]
    interior = discretize_arc(arc["center"], arc["radius"], arc["start_angle"], arc["sweep_deg"], max_sagitta_mm=max_sagitta_mm)
    if not interior:
        return [{"x": start["x"], "y": start["y"]}, {"x": end["x"], "y": end["y"]}]
    interior[0] = {"x": start["x"], "y": start["y"]}
    interior[-1] = {"x": end["x"], "y": end["y"]}
    return interior


def polyline_curve_points(points: list[Point], bulges: list[float], closed: bool, *, max_sagitta_mm: float = 5.0) -> list[Point]:
    """完整离散折线：直线段保留端点，圆弧段按弦高误差细分。"""
    if len(points) < 2:
        return list(points)
    result: list[Point] = [{"x": points[0]["x"], "y": points[0]["y"]}]
    count = len(points)
    pair_count = count if closed else count - 1
    for index in range(pair_count):
        start = points[index]
        end = points[(index + 1) % count]
        bulge = float(bulges[index]) if index < len(bulges) and bulges[index] is not None else 0.0
        if bulge:
            result.extend(bulge_arc_points(start, end, bulge, max_sagitta_mm=max_sagitta_mm)[1:])
        else:
            candidate = {"x": end["x"], "y": end["y"]}
            # 闭合折线的最后一段会回到首点：不要产生重复的收尾点
            if closed and index == pair_count - 1 and result and result[0] == candidate:
                continue
            result.append(candidate)
    return result


def polyline_length(points: list[Point], bulges: list[float], closed: bool) -> float:
    """折线总长：包含圆弧段真实弧长与闭合边。"""
    if len(points) < 2:
        return 0.0
    count = len(points)
    pair_count = count if closed else count - 1
    total = 0.0
    for index in range(pair_count):
        start = points[index]
        end = points[(index + 1) % count]
        bulge = float(bulges[index]) if index < len(bulges) and bulges[index] is not None else 0.0
        total += segment_geometry(start, end, bulge)["length_mm"]
    return total


def arc_length(radius: float, start_angle: float, end_angle: float) -> float:
    """DXF ARC 的弧长。

    DXF 的 ARC 角度按逆时针从起点到终点，因此扫掠角 = (end - start) mod 360，
    不能被当成「较小的那个夹角」（否则 270° 的弧会被算成 90°）。
    """
    sweep = arc_sweep_deg(start_angle, end_angle)
    return abs(radians(sweep)) * float(radius)


def arc_sweep_deg(start_angle: float, end_angle: float) -> float:
    """从 start 逆时针到 end 的扫掠角，取值 (0, 360]。"""
    delta = (float(end_angle) - float(start_angle)) % 360.0
    return delta if delta != 0.0 else 360.0


def arc_bounds(center: Point, radius: float, start_angle: float, end_angle: float) -> tuple[float, float, float, float]:
    """圆弧包围盒：按扇形端点 + 落在弧内的象限点计算。"""
    cx, cy = center["x"], center["y"]
    sweep = arc_sweep_deg(start_angle, end_angle)
    candidates = [
        (cx + radius * cos(radians(start_angle)), cy + radius * sin(radians(start_angle))),
        (cx + radius * cos(radians(end_angle)), cy + radius * sin(radians(end_angle))),
    ]
    for quadrant in (0.0, 90.0, 180.0, 270.0):
        if _angle_in_sweep(quadrant, start_angle, sweep):
            candidates.append((cx + radius * cos(radians(quadrant)), cy + radius * sin(radians(quadrant))))
    xs = [point[0] for point in candidates]
    ys = [point[1] for point in candidates]
    return min(xs), min(ys), max(xs), max(ys)


def _angle_in_sweep(angle: float, start_angle: float, sweep: float) -> bool:
    if sweep >= 0:
        delta = (angle - start_angle) % 360.0
        return delta <= sweep + 1e-9
    delta = (start_angle - angle) % 360.0
    return delta <= abs(sweep) + 1e-9


def bulge_segment_bounds(start: Point, end: Point, bulge: float) -> tuple[float, float, float, float] | None:
    """圆弧段的包围盒（bulge 为 0 时返回 None，由调用方按直线处理）。"""
    if not bulge:
        return None
    arc = bulge_to_arc(start, end, bulge)
    if arc["radius"] <= 0.0 or arc["radius"] != arc["radius"]:
        return None
    center = {"x": arc["center"][0], "y": arc["center"][1]}
    if arc["sweep_deg"] >= 0:
        return arc_bounds(center, arc["radius"], arc["start_angle"], arc["start_angle"] + arc["sweep_deg"])
    # 顺时针弧：镜像为等价的逆时针表示再做包围盒
    return arc_bounds(center, arc["radius"], arc["start_angle"] + arc["sweep_deg"], arc["start_angle"])


def polyline_bounds(points: list[Point], bulges: list[float], closed: bool) -> tuple[float, float, float, float] | None:
    """折线包围盒：直线段取端点，圆弧段取真实弧包围盒。"""
    if not points:
        return None
    xs = [point["x"] for point in points]
    ys = [point["y"] for point in points]
    min_x, max_x = min(xs), max(xs)
    min_y, max_y = min(ys), max(ys)
    count = len(points)
    pair_count = count if closed else count - 1
    for index in range(pair_count):
        start = points[index]
        end = points[(index + 1) % count]
        bulge = float(bulges[index]) if index < len(bulges) and bulges[index] is not None else 0.0
        bounds = bulge_segment_bounds(start, end, bulge)
        if not bounds:
            continue
        min_x = min(min_x, bounds[0])
        min_y = min(min_y, bounds[1])
        max_x = max(max_x, bounds[2])
        max_y = max(max_y, bounds[3])
    return min_x, min_y, max_x, max_y


__all__ = [
    "arc_bounds",
    "arc_sweep_deg",
    "arc_length",
    "bulge_arc_points",
    "bulge_segment_bounds",
    "bulge_to_arc",
    "discretize_arc",
    "polyline_bounds",
    "polyline_curve_points",
    "polyline_length",
    "polyline_segments",
    "segment_geometry",
]
