from __future__ import annotations

from typing import Iterable


def polygon_area(points: Iterable[dict[str, float]]) -> float:
    pts = list(points)
    if len(pts) < 3:
        return 0.0
    total = 0.0
    for idx, point in enumerate(pts):
        nxt = pts[(idx + 1) % len(pts)]
        total += point["x"] * nxt["y"] - nxt["x"] * point["y"]
    return abs(total) / 2.0


def line_length(points: Iterable[dict[str, float]]) -> float:
    pts = list(points)
    if len(pts) < 2:
        return 0.0
    length = 0.0
    for start, end in zip(pts, pts[1:]):
        length += ((end["x"] - start["x"]) ** 2 + (end["y"] - start["y"]) ** 2) ** 0.5
    return length


def center_of_points(points: Iterable[dict[str, float]]) -> dict[str, float]:
    pts = list(points)
    if not pts:
        return {"x": 0.0, "y": 0.0}
    return {
        "x": sum(point["x"] for point in pts) / len(pts),
        "y": sum(point["y"] for point in pts) / len(pts),
    }
