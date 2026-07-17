from __future__ import annotations

from math import cos, radians, sin
from pathlib import Path
from typing import Any
import warnings

import matplotlib

matplotlib.use("Agg")
from matplotlib import pyplot as plt
from matplotlib.patches import Ellipse

from parser.dxf_reader import DxfReader

plt.rcParams["font.sans-serif"] = ["Microsoft YaHei", "SimHei", "Arial Unicode MS", "DejaVu Sans"]
plt.rcParams["axes.unicode_minus"] = False
warnings.filterwarnings("ignore", message="Glyph .* missing from font")

ACI_COLORS = {
    1: "#ff3030",
    2: "#f3d52e",
    3: "#39dd52",
    4: "#30d7e8",
    5: "#4f7dff",
    6: "#ff38d4",
    7: "#d7dddd",
    8: "#777777",
    9: "#aaaaaa",
}


def capture_dxf_region(
    dxf_path: Path,
    region: dict[str, Any],
    output_path: Path,
    *,
    padding_ratio: float = 0.03,
    dpi: int = 170,
) -> dict[str, Any]:
    min_x = float(region["min_x"])
    max_x = float(region["max_x"])
    min_y = float(region["min_y"])
    max_y = float(region["max_y"])
    width = max(max_x - min_x, 1.0)
    height = max(max_y - min_y, 1.0)
    pad_x = width * padding_ratio
    pad_y = height * padding_ratio

    fig_width = min(max(width / max(height, 1.0) * 8.0, 6.0), 16.0)
    fig_height = min(max(height / max(width, 1.0) * fig_width, 5.0), 14.0)
    fig, ax = plt.subplots(figsize=(fig_width, fig_height), dpi=dpi)
    fig.patch.set_facecolor("#050705")
    ax.set_facecolor("#050705")
    ax.set_aspect("equal", adjustable="box")
    ax.set_xlim(min_x - pad_x, max_x + pad_x)
    ax.set_ylim(min_y - pad_y, max_y + pad_y)
    ax.axis("off")

    crop = {
        "min_x": min_x - pad_x,
        "min_y": min_y - pad_y,
        "max_x": max_x + pad_x,
        "max_y": max_y + pad_y,
    }
    parsed = DxfReader.read(dxf_path)
    rendered_entities = 0
    for entity in parsed.get("entities", []):
        rendered_entities += _draw_if_visible(ax, entity, crop)
        for virtual_shape in entity.get("cad_virtual_shapes") or []:
            rendered_entities += _draw_if_visible(ax, virtual_shape, crop, alpha=0.75)

    output_path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(output_path, dpi=dpi, facecolor=fig.get_facecolor(), bbox_inches="tight", pad_inches=0.02)
    plt.close(fig)
    return {
        "path": str(output_path),
        "size_bytes": output_path.stat().st_size if output_path.exists() else 0,
        "format": "png",
        "source_region": {
            "min_x": min_x,
            "min_y": min_y,
            "max_x": max_x,
            "max_y": max_y,
        },
        "rendered_entities": rendered_entities,
    }


def _draw_if_visible(ax: Any, entity: dict[str, Any], crop: dict[str, float], *, alpha: float = 0.95) -> int:
    bbox = _entity_bbox(entity)
    if not bbox or not _intersects(bbox, crop):
        return 0
    geometry = entity.get("geometry") or {}
    color = _entity_color(entity)
    geom_type = geometry.get("type")
    if geom_type in {"LineString", "Polygon"}:
        points = geometry.get("points") or []
        if len(points) < 2:
            return 0
        xs = [float(point["x"]) for point in points]
        ys = [float(point["y"]) for point in points]
        if geom_type == "Polygon" or geometry.get("closed"):
            xs.append(xs[0])
            ys.append(ys[0])
        ax.plot(xs, ys, color=color, linewidth=0.55, alpha=alpha)
        return 1
    if geom_type == "Circle":
        center = geometry.get("center") or {}
        circle = plt.Circle(
            (float(center.get("x", 0.0)), float(center.get("y", 0.0))),
            float(geometry.get("radius", 0.0)),
            fill=False,
            color=color,
            linewidth=0.55,
            alpha=alpha,
        )
        ax.add_patch(circle)
        return 1
    if geom_type == "Arc":
        points = _arc_points(geometry)
        if len(points) < 2:
            return 0
        ax.plot([point[0] for point in points], [point[1] for point in points], color=color, linewidth=0.55, alpha=alpha)
        return 1
    if geom_type == "Ellipse":
        center = geometry.get("center") or {}
        ellipse = Ellipse(
            (float(center.get("x", 0.0)), float(center.get("y", 0.0))),
            width=float(geometry.get("radius_major", 0.0)) * 2.0,
            height=float(geometry.get("radius_minor", 0.0)) * 2.0,
            angle=float(geometry.get("rotation", 0.0) or 0.0),
            fill=False,
            edgecolor=color,
            linewidth=0.55,
            alpha=alpha,
        )
        ax.add_patch(ellipse)
        return 1
    if geom_type == "Point":
        position = geometry.get("position") or {}
        x = float(position.get("x", 0.0))
        y = float(position.get("y", 0.0))
        text = str(entity.get("text") or "")
        if text:
            height = float(entity.get("height") or 0.0)
            fontsize = max(3.5, min(height / 650.0 if height else 5.0, 8.5))
            ax.text(x, y, text[:80], color=color, fontsize=fontsize, alpha=alpha, rotation=float(entity.get("rotation") or 0.0))
        else:
            ax.scatter([x], [y], s=5, c=color, alpha=alpha)
        return 1
    return 0


def _entity_bbox(entity: dict[str, Any]) -> dict[str, float] | None:
    geometry = entity.get("geometry") or {}
    geom_type = geometry.get("type")
    if geom_type in {"LineString", "Polygon"}:
        points = geometry.get("points") or []
        if not points:
            return None
        return {
            "min_x": min(float(point["x"]) for point in points),
            "max_x": max(float(point["x"]) for point in points),
            "min_y": min(float(point["y"]) for point in points),
            "max_y": max(float(point["y"]) for point in points),
        }
    if geom_type in {"Circle", "Arc"}:
        center = geometry.get("center") or {}
        radius = float(geometry.get("radius", 0.0) or 0.0)
        x = float(center.get("x", 0.0))
        y = float(center.get("y", 0.0))
        return {"min_x": x - radius, "max_x": x + radius, "min_y": y - radius, "max_y": y + radius}
    if geom_type == "Ellipse":
        center = geometry.get("center") or {}
        radius = max(float(geometry.get("radius_major", 0.0) or 0.0), float(geometry.get("radius_minor", 0.0) or 0.0))
        x = float(center.get("x", 0.0))
        y = float(center.get("y", 0.0))
        return {"min_x": x - radius, "max_x": x + radius, "min_y": y - radius, "max_y": y + radius}
    if geom_type == "Point":
        position = geometry.get("position") or {}
        x = float(position.get("x", 0.0))
        y = float(position.get("y", 0.0))
        pad = max(float(entity.get("height") or 0.0), 500.0)
        return {"min_x": x - pad, "max_x": x + pad, "min_y": y - pad, "max_y": y + pad}
    return None


def _intersects(bbox: dict[str, float], crop: dict[str, float]) -> bool:
    return not (
        bbox["max_x"] < crop["min_x"]
        or bbox["min_x"] > crop["max_x"]
        or bbox["max_y"] < crop["min_y"]
        or bbox["min_y"] > crop["max_y"]
    )


def _entity_color(entity: dict[str, Any]) -> str:
    true_color = entity.get("true_color")
    if isinstance(true_color, int) and true_color >= 0:
        return f"#{true_color & 0xFFFFFF:06x}"
    try:
        aci = abs(int(entity.get("effective_color") or entity.get("color") or 7))
    except (TypeError, ValueError):
        aci = 7
    return ACI_COLORS.get(aci, "#9fb2ad")


def _arc_points(geometry: dict[str, Any], steps: int = 48) -> list[tuple[float, float]]:
    center = geometry.get("center") or {}
    radius = float(geometry.get("radius", 0.0) or 0.0)
    start = float(geometry.get("start_angle", 0.0) or 0.0)
    end = float(geometry.get("end_angle", 0.0) or 0.0)
    if end < start:
        end += 360.0
    x = float(center.get("x", 0.0))
    y = float(center.get("y", 0.0))
    return [
        (x + cos(radians(start + (end - start) * index / steps)) * radius, y + sin(radians(start + (end - start) * index / steps)) * radius)
        for index in range(steps + 1)
    ]
