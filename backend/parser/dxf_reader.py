"""DXF 读取：把模型空间实体规范化为「毫米坐标 + 可追溯几何」。

关键约定：
- 内部坐标统一为 **毫米**。单位来自 `$INSUNITS`；无单位(0)/未知码会被标记为
  `unit_unspecified=True`，不会被静默当成毫米，调用方可以提示用户显式选择。
- 支持显式单位覆盖：`read(path, unit="ft")` 或 `read(path, unit_scale_to_mm=304.8)`。
- LWPOLYLINE / POLYLINE 保留 bulge（凸度）与圆弧段信息：长度包含真实弧长与闭合边，
  预览可用 `geometry["segments"]` 画弧而不是画弦。
- ARC 弧长按 DXF 语义（逆时针 start→end，(end-start) mod 360）计算。
- 每个实体都带 `source_entity_id`（DXF handle），预览坐标可回溯原始实体。
"""

from __future__ import annotations

import contextlib
import io
from dataclasses import dataclass
from math import atan2, degrees
from pathlib import Path
from typing import Any

import ezdxf
from ezdxf.math import OCS

from parser.dxf_geometry import (
    arc_length,
    polyline_bounds,
    polyline_curve_points,
    polyline_length,
    polyline_segments,
)
from parser.dxf_units import DEFAULT_SCALE_TO_MM, available_units, resolve_unit

ZERO_TOLERANCE = 1e-9


@dataclass
class Bounds:
    min_x: float | None = None
    min_y: float | None = None
    max_x: float | None = None
    max_y: float | None = None

    def add(self, x: float, y: float) -> None:
        self.min_x = x if self.min_x is None else min(self.min_x, x)
        self.min_y = y if self.min_y is None else min(self.min_y, y)
        self.max_x = x if self.max_x is None else max(self.max_x, x)
        self.max_y = y if self.max_y is None else max(self.max_y, y)

    def add_box(self, min_x: float, min_y: float, max_x: float, max_y: float) -> None:
        self.add(min_x, min_y)
        self.add(max_x, max_y)

    def as_dict(self) -> dict[str, dict[str, float]]:
        if self.min_x is None:
            return {"min": {"x": 0.0, "y": 0.0}, "max": {"x": 0.0, "y": 0.0}}
        return {
            "min": {"x": self.min_x or 0.0, "y": self.min_y or 0.0},
            "max": {"x": self.max_x or 0.0, "y": self.max_y or 0.0},
        }


class DxfReader:
    supported_types = {"INSERT", "LINE", "LWPOLYLINE", "POLYLINE", "TEXT", "MTEXT", "DIMENSION", "CIRCLE", "ARC", "ELLIPSE"}

    @staticmethod
    def read(
        path: Path,
        *,
        unit: str | None = None,
        unit_scale_to_mm: float | None = None,
    ) -> dict[str, Any]:
        if not path.exists():
            raise FileNotFoundError(f"DXF 文件不存在: {path}")
        doc = ezdxf.readfile(path, errors="replace")
        raw_units = doc.header.get("$INSUNITS", 0)
        resolution = resolve_unit(raw_units, unit=unit, unit_scale_to_mm=unit_scale_to_mm)
        scale = float(resolution["unit_scale_to_mm"])
        modelspace = doc.modelspace()
        layer_colors = {str(layer.dxf.name): int(layer.dxf.color or 256) for layer in doc.layers}
        layer_linetypes = {str(layer.dxf.name): str(layer.dxf.linetype or "") for layer in doc.layers}
        bounds = Bounds()
        entities: list[dict[str, Any]] = []
        total = 0
        skipped_unsupported = 0

        for entity in modelspace:
            total += 1
            if entity.dxftype() not in DxfReader.supported_types:
                skipped_unsupported += 1
                continue
            normalized = DxfReader._normalize_entity(entity, scale, bounds, layer_colors, layer_linetypes)
            if normalized:
                entities.append(normalized)

        extents = bounds.as_dict()
        if bounds.min_x is None:
            header_bounds = DxfReader._header_bounds(doc, scale)
            if header_bounds:
                extents = header_bounds

        result: dict[str, Any] = {
            "path": str(path),
            "dxf_version": doc.dxfversion,
            "unit_code": resolution["unit_code"],
            "unit_name": resolution["unit_name"],
            "unit_scale_to_mm": scale,
            "unit_source": resolution["unit_source"],
            "unit_unspecified": bool(resolution["unit_unspecified"]),
            "unit_known": bool(resolution["unit_known"]),
            "unit_explicit": bool(resolution["explicit_unit"]),
            "header_unit_code": resolution["header_unit_code"],
            "header_unit_name": resolution["header_unit_name"],
            "available_units": available_units(),
            "layer_count": len(doc.layers),
            "layer_names": [layer.dxf.name for layer in doc.layers],
            "total_entities": total,
            "skipped_unsupported_entities": skipped_unsupported,
            "entities": entities,
            "extents": extents,
        }
        if resolution["unit_unspecified"]:
            header_code = resolution["header_unit_code"]
            if header_code in (0, None):
                reason = "图纸未声明单位（$INSUNITS=0），已按毫米 1:1 处理，请在解析时确认单位"
            else:
                reason = f"图纸单位码 {header_code} 无法识别，已按毫米 1:1 处理，请显式选择单位"
            result["unit_warning"] = reason
            result["unit_resolution"] = resolution
        return result

    # ------------------------------------------------------------ 基础工具

    @staticmethod
    def _pt(point: Any, scale: float) -> dict[str, float]:
        """把点坐标换到毫米。

        注意：实体若带非默认 OCS/Z 轴倾斜，其平面内长度仍需按 1:1 处理；
        这里只把 OCS 坐标映射到 WCS 平面（xy），用于位置展示与平面几何。
        """
        return {"x": float(point[0]) * scale, "y": float(point[1]) * scale}

    @staticmethod
    def _entity_ocs(entity: Any) -> tuple[OCS, float]:
        """返回实体的 OCS 与平面内长度补偿因子。

        - **翻转的 extrusion（z 分量为负）** 是镜像块展开的正常结果，必须真的按该 OCS
          做 OCS->WCS 变换，否则会丢掉插入点平移并把坐标整体取反。所以这里不丢弃它。
        - **倾斜的 extrusion（|z| < 1）** 会让 OCS 平面内的距离短于真实距离，
          用 1/|z| 补偿；z 分量接近 0（平面垂直于 XY）时无法表达平面几何，退化为恒等。
        """
        extrusion = (0.0, 0.0, 1.0)
        try:
            if entity.dxf.hasattr("extrusion"):
                raw = entity.dxf.get("extrusion")
                extrusion = (float(raw[0]), float(raw[1]), float(raw[2]))
        except Exception:
            extrusion = (0.0, 0.0, 1.0)
        z = extrusion[2]
        if abs(z) <= ZERO_TOLERANCE:
            return OCS(), 1.0
        try:
            ocs = OCS(extrusion)
        except Exception:
            return OCS(), 1.0
        return ocs, (abs(z) if abs(z) < 1.0 else 1.0)

    @staticmethod
    def _ocs_point(entity: Any, point: Any, scale: float) -> dict[str, float]:
        ocs, factor = DxfReader._entity_ocs(entity)
        wcs = ocs.to_wcs((float(point[0]), float(point[1]), 0.0))
        return {"x": (float(wcs.x) * scale) / factor, "y": (float(wcs.y) * scale) / factor}

    @staticmethod
    def _add_point(bounds: Bounds, point: dict[str, float]) -> None:
        bounds.add(point["x"], point["y"])

    @staticmethod
    def _aci_color(entity: Any) -> int:
        try:
            return int(getattr(entity.dxf, "color", 256) or 256)
        except Exception:
            return 256

    @staticmethod
    def _layer_color(entity: Any, layer_colors: dict[str, int]) -> int | None:
        layer = str(getattr(entity.dxf, "layer", ""))
        color = layer_colors.get(layer)
        return abs(int(color)) if color is not None else None

    @staticmethod
    def _effective_color(entity: Any, layer_colors: dict[str, int]) -> int:
        color = abs(DxfReader._aci_color(entity))
        if color in {0, 256}:
            layer_color = DxfReader._layer_color(entity, layer_colors)
            if layer_color:
                return layer_color
        return color

    @staticmethod
    def _true_color(entity: Any) -> int | None:
        try:
            if entity.dxf.hasattr("true_color"):
                return int(entity.dxf.true_color)
        except Exception:
            return None
        return None

    @staticmethod
    def _common(entity: Any, layer_colors: dict[str, int], layer_linetypes: dict[str, str]) -> dict[str, Any]:
        layer = str(entity.dxf.layer)
        data = {
            "source_entity_id": str(entity.dxf.handle),
            "entity_type": entity.dxftype(),
            "layer": layer,
            "linetype": str(getattr(entity.dxf, "linetype", "") or "BYLAYER"),
            "layer_linetype": str(layer_linetypes.get(layer, "") or ""),
            "color": DxfReader._aci_color(entity),
            "layer_color": DxfReader._layer_color(entity, layer_colors),
            "effective_color": DxfReader._effective_color(entity, layer_colors),
        }
        true_color = DxfReader._true_color(entity)
        if true_color is not None:
            data["true_color"] = true_color
        return data

    # ------------------------------------------------------------ 多段线

    @staticmethod
    def _polyline_vertices(entity: Any, scale: float, *, ocs: bool) -> tuple[list[dict[str, float]], list[float]]:
        """提取顶点与凸度；`ocs=True` 时按实体 OCS 变换到平面坐标。"""
        points: list[dict[str, float]] = []
        bulges: list[float] = []
        raw = list(entity.get_points("xyb"))
        for item in raw:
            x, y = float(item[0]), float(item[1])
            bulge = float(item[2]) if len(item) > 2 and item[2] is not None else 0.0
            if ocs:
                point = DxfReader._ocs_point(entity, (x, y), scale)
            else:
                point = {"x": x * scale, "y": y * scale}
            points.append(point)
            bulges.append(bulge)
        return points, bulges

    @staticmethod
    def _apply_polyline_geometry(
        data: dict[str, Any],
        points: list[dict[str, float]],
        bulges: list[float],
        closed: bool,
        bounds: Bounds,
    ) -> dict[str, Any]:
        segments = polyline_segments(points, bulges, closed)
        box = polyline_bounds(points, bulges, closed)
        if box:
            bounds.add_box(*box)
        geometry: dict[str, Any] = {
            "type": "Polygon" if closed else "LineString",
            "points": points,
            "closed": closed,
            "bulges": bulges,
            "segments": segments,
        }
        if any(bulges):
            geometry["curve_points"] = polyline_curve_points(points, bulges, closed)
        data["geometry"] = geometry
        data["cad_native_linear"] = True
        data["node_count"] = len(points)
        data["native_length_mm"] = polyline_length(points, bulges, closed)
        data["curve_length_mm"] = data["native_length_mm"]
        data["has_arc_segments"] = any(segment["kind"] == "arc" for segment in segments)
        return data

    @staticmethod
    def _with_linear_metrics(data: dict[str, Any], points: list[dict[str, float]]) -> dict[str, Any]:
        data["cad_native_linear"] = True
        data["node_count"] = len(points)
        data["native_length_mm"] = polyline_length(points, [0.0] * len(points), False)
        data["curve_length_mm"] = data["native_length_mm"]
        return data

    # ------------------------------------------------------------ 实体规范化

    @staticmethod
    def _normalize_entity(
        entity: Any,
        scale: float,
        bounds: Bounds,
        layer_colors: dict[str, int],
        layer_linetypes: dict[str, str],
    ) -> dict[str, Any] | None:
        data = DxfReader._common(entity, layer_colors, layer_linetypes)
        dxftype = entity.dxftype()

        if dxftype == "INSERT":
            position = DxfReader._ocs_point(entity, entity.dxf.insert, scale)
            DxfReader._add_point(bounds, position)
            attributes = {}
            for attrib in entity.attribs:
                attributes[str(attrib.dxf.tag)] = str(attrib.dxf.text)
            data.update(
                {
                    "block_name": str(entity.dxf.name),
                    "geometry": {"type": "Point", "position": position},
                    "rotation": float(getattr(entity.dxf, "rotation", 0.0) or 0.0),
                    "attributes": attributes,
                }
            )
            virtual_shapes = DxfReader._virtual_cad_shapes(entity, scale, layer_colors, layer_linetypes)
            if virtual_shapes:
                data["cad_virtual_shapes"] = virtual_shapes
            virtual_dimensions = DxfReader._virtual_cad_dimensions(entity, scale)
            if virtual_dimensions:
                data["cad_virtual_dimensions"] = virtual_dimensions
            return data

        if dxftype == "LINE":
            start = DxfReader._ocs_point(entity, entity.dxf.start, scale)
            end = DxfReader._ocs_point(entity, entity.dxf.end, scale)
            DxfReader._add_point(bounds, start)
            DxfReader._add_point(bounds, end)
            points = [start, end]
            data["geometry"] = {"type": "LineString", "points": points}
            return DxfReader._with_linear_metrics(data, points)

        if dxftype == "LWPOLYLINE":
            points, bulges = DxfReader._polyline_vertices(entity, scale, ocs=True)
            if not points:
                return None
            return DxfReader._apply_polyline_geometry(data, points, bulges, bool(entity.closed), bounds)

        if dxftype == "POLYLINE":
            try:
                points, bulges = DxfReader._polyline_vertices(entity, scale, ocs=True)
            except Exception:
                return None
            if not points:
                return None
            return DxfReader._apply_polyline_geometry(data, points, bulges, bool(entity.is_closed), bounds)

        if dxftype in {"TEXT", "MTEXT"}:
            insert = DxfReader._ocs_point(entity, entity.dxf.insert, scale)
            DxfReader._add_point(bounds, insert)
            if dxftype == "MTEXT":
                text = entity.plain_text()
            else:
                text = str(entity.dxf.text)
            data.update(
                {
                    "text": text.strip(),
                    "geometry": {"type": "Point", "position": insert},
                    "height": float(getattr(entity.dxf, "height", 0.0) or 0.0) * scale,
                    "rotation": float(getattr(entity.dxf, "rotation", 0.0) or 0.0),
                }
            )
            return data

        if dxftype == "DIMENSION":
            geometry = DxfReader._dimension_geometry(entity, scale)
            if not geometry:
                return None
            anchor = geometry["position"]
            DxfReader._add_point(bounds, anchor)
            data.update(
                {
                    "text": DxfReader._dimension_text(entity),
                    "measurement": DxfReader._dimension_measurement(entity, scale),
                    "geometry": {"type": "Point", "position": anchor},
                    "dimension_points": geometry.get("points", []),
                    "dimtype": int(getattr(entity.dxf, "dimtype", 0) or 0),
                }
            )
            return data

        if dxftype == "CIRCLE":
            center = DxfReader._ocs_point(entity, entity.dxf.center, scale)
            radius = float(entity.dxf.radius) * scale
            DxfReader._add_point(bounds, {"x": center["x"] - radius, "y": center["y"] - radius})
            DxfReader._add_point(bounds, {"x": center["x"] + radius, "y": center["y"] + radius})
            data["geometry"] = {
                "type": "Circle",
                "center": center,
                "radius": radius,
                "circumference_mm": 2.0 * 3.141592653589793 * radius,
            }
            return data

        if dxftype == "ARC":
            center = DxfReader._ocs_point(entity, entity.dxf.center, scale)
            radius = float(entity.dxf.radius) * scale
            start_angle = float(entity.dxf.start_angle)
            end_angle = float(entity.dxf.end_angle)
            from parser.dxf_geometry import arc_bounds

            DxfReader._add_box(bounds, arc_bounds(center, radius, start_angle, end_angle))
            data["geometry"] = {
                "type": "Arc",
                "center": center,
                "radius": radius,
                "start_angle": start_angle,
                "end_angle": end_angle,
                "length_mm": arc_length(radius, start_angle, end_angle),
            }
            data["native_length_mm"] = data["geometry"]["length_mm"]
            data["curve_length_mm"] = data["native_length_mm"]
            return data

        if dxftype == "ELLIPSE":
            ellipse = DxfReader._ellipse_geometry(entity, scale)
            if not ellipse:
                return None
            center = ellipse["center"]
            radius = max(float(ellipse["radius_major"]), float(ellipse["radius_minor"]))
            DxfReader._add_point(bounds, {"x": center["x"] - radius, "y": center["y"] - radius})
            DxfReader._add_point(bounds, {"x": center["x"] + radius, "y": center["y"] + radius})
            data["geometry"] = ellipse
            return data

        return None

    @staticmethod
    def _add_box(bounds: Bounds, box: tuple[float, float, float, float]) -> None:
        bounds.add_box(*box)

    # ------------------------------------------------------------ INSERT 虚拟几何

    @staticmethod
    def _virtual_cad_shapes(
        entity: Any,
        scale: float,
        layer_colors: dict[str, int],
        layer_linetypes: dict[str, str],
    ) -> list[dict[str, Any]]:
        role = DxfReader._insert_cad_role(str(entity.dxf.name))
        shapes: list[dict[str, Any]] = []
        try:
            with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
                virtual_entities = list(entity.virtual_entities())
        except Exception:
            return []
        if not role:
            role = DxfReader._virtual_cad_role(virtual_entities)
        if not role:
            return []
        for virtual in virtual_entities:
            # 虚拟实体已经过块变换（含旋转/镜像/非均匀缩放），因此按 WCS 处理，不再套 OCS。
            normalized = DxfReader._normalize_virtual_shape(virtual, scale, layer_colors, layer_linetypes, role)
            if normalized:
                shapes.append(normalized)
        return shapes

    @staticmethod
    def _virtual_cad_dimensions(entity: Any, scale: float) -> list[dict[str, Any]]:
        dimensions: list[dict[str, Any]] = []
        try:
            with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
                virtual_entities = list(entity.virtual_entities())
        except Exception:
            return dimensions

        for virtual in virtual_entities:
            if virtual.dxftype() != "DIMENSION":
                continue
            geometry = DxfReader._dimension_geometry(virtual, scale, ocs=False)
            if not geometry:
                continue
            dimensions.append(
                {
                    "source_kind": "insert_virtual_dimension",
                    "layer": str(getattr(virtual.dxf, "layer", "")),
                    "text": DxfReader._dimension_text(virtual),
                    "measurement": DxfReader._dimension_measurement(virtual, scale),
                    "geometry": {"type": "Point", "position": geometry["position"]},
                    "dimension_points": geometry.get("points", []),
                    "dimtype": int(getattr(virtual.dxf, "dimtype", 0) or 0),
                }
            )
        return dimensions

    @staticmethod
    def _dimension_text(entity: Any) -> str:
        raw_text = str(getattr(entity.dxf, "text", "") or "").strip()
        rendered: list[str] = []
        try:
            with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
                virtual_entities = list(entity.virtual_entities())
        except Exception:
            virtual_entities = []
        for virtual in virtual_entities:
            try:
                if virtual.dxftype() == "MTEXT":
                    text = str(virtual.plain_text()).strip()
                elif virtual.dxftype() == "TEXT":
                    text = str(virtual.dxf.text).strip()
                else:
                    continue
            except Exception:
                continue
            if text:
                rendered.append(text)
        if rendered:
            return " ".join(rendered)
        return raw_text.replace("<>", "").strip()

    @staticmethod
    def _dimension_measurement(entity: Any, scale: float) -> float | None:
        try:
            return float(entity.get_measurement()) * scale
        except Exception:
            return None

    @staticmethod
    def _dimension_geometry(entity: Any, scale: float, *, ocs: bool = True) -> dict[str, Any] | None:
        points: list[dict[str, float]] = []
        for name in ("defpoint", "defpoint2", "defpoint3", "defpoint4", "defpoint5", "text_midpoint"):
            try:
                if not entity.dxf.hasattr(name):
                    continue
                raw = getattr(entity.dxf, name)
                point = DxfReader._ocs_point(entity, raw, scale) if ocs else DxfReader._pt(raw, scale)
            except Exception:
                continue
            points.append(point)
        if not points:
            try:
                raw = entity.dxf.insert
                points.append(DxfReader._ocs_point(entity, raw, scale) if ocs else DxfReader._pt(raw, scale))
            except Exception:
                return None
        anchor = points[-1] if len(points) > 1 else points[0]
        return {"position": anchor, "points": points}

    @staticmethod
    def _insert_cad_role(block_name: str) -> str | None:
        upper = block_name.upper()
        if "AP" in upper or "无线" in block_name:
            return "ap_coverage"
        if "鱼眼" in block_name:
            return "fisheye_coverage"
        if "半球" in block_name:
            return "dome_coverage"
        if any(keyword in block_name for keyword in ("枪", "摄像头", "外围摄像")):
            return "camera_symbol"
        return None

    @staticmethod
    def _virtual_cad_role(virtual_entities: list[Any]) -> str | None:
        layers = {str(getattr(entity.dxf, "layer", "")) for entity in virtual_entities}
        if any("车位" in layer or "停车" in layer.upper() or "PARK" in layer.upper() for layer in layers):
            return "parking_space"
        if any("车" in layer for layer in layers) and DxfReader._virtual_entities_vehicle_footprint(virtual_entities):
            return "parking_space"
        return None

    @staticmethod
    def _virtual_entities_vehicle_footprint(virtual_entities: list[Any]) -> bool:
        points: list[tuple[float, float]] = []
        for entity in virtual_entities:
            try:
                dxftype = entity.dxftype()
                if dxftype == "LINE":
                    points.append((float(entity.dxf.start.x), float(entity.dxf.start.y)))
                    points.append((float(entity.dxf.end.x), float(entity.dxf.end.y)))
                elif dxftype == "LWPOLYLINE":
                    points.extend((float(item[0]), float(item[1])) for item in entity.get_points("xyb"))
                elif dxftype == "POLYLINE":
                    points.extend((float(point.x), float(point.y)) for point in entity.points())
                elif dxftype == "CIRCLE":
                    center = entity.dxf.center
                    radius = float(entity.dxf.radius)
                    points.append((float(center.x) - radius, float(center.y) - radius))
                    points.append((float(center.x) + radius, float(center.y) + radius))
                elif dxftype == "ARC":
                    center = entity.dxf.center
                    radius = float(entity.dxf.radius)
                    points.append((float(center.x) - radius, float(center.y) - radius))
                    points.append((float(center.x) + radius, float(center.y) + radius))
            except Exception:
                continue
        if len(points) < 4:
            return False
        width = max(point[0] for point in points) - min(point[0] for point in points)
        height = max(point[1] for point in points) - min(point[1] for point in points)
        long_dim = max(width, height)
        short_dim = min(width, height)
        return 10_000.0 <= long_dim <= 35_000.0 and 1_500.0 <= short_dim <= 6_000.0

    @staticmethod
    def _normalize_virtual_shape(
        entity: Any,
        scale: float,
        layer_colors: dict[str, int],
        layer_linetypes: dict[str, str],
        role: str,
    ) -> dict[str, Any] | None:
        dxftype = entity.dxftype()
        if dxftype not in {"LINE", "LWPOLYLINE", "POLYLINE", "CIRCLE", "ARC", "ELLIPSE"}:
            return None
        data = DxfReader._common(entity, layer_colors, layer_linetypes)
        data["source_kind"] = "insert_virtual_entity"
        data["cad_role"] = role

        if dxftype == "LINE":
            # LINE 的 start/end 按 DXF 规范属 WCS（镜像块展开后 ezdxf 已给出正确 WCS 值）
            points = [DxfReader._pt(entity.dxf.start, scale), DxfReader._pt(entity.dxf.end, scale)]
            data["geometry"] = {"type": "LineString", "points": points}
            return DxfReader._with_linear_metrics(data, points)
        if dxftype in {"LWPOLYLINE", "POLYLINE"}:
            # 关键：虚拟实体可能带着翻转的 extrusion（镜像/负缩放块的展开结果），
            # 此时 get_points("xyb") 给的是该实体 OCS 内的坐标，必须经 OCS->WCS 转换，
            # 否则插入点平移会丢失、坐标整体取反。
            points, bulges = DxfReader._polyline_vertices(entity, scale, ocs=True)
            if not points:
                return None
            closed = bool(entity.closed) if dxftype == "LWPOLYLINE" else bool(entity.is_closed)
            segments = polyline_segments(points, bulges, closed)
            geometry: dict[str, Any] = {
                "type": "Polygon" if closed else "LineString",
                "points": points,
                "closed": closed,
                "bulges": bulges,
                "segments": segments,
            }
            if any(bulges):
                geometry["curve_points"] = polyline_curve_points(points, bulges, closed)
            data["geometry"] = geometry
            data["cad_native_linear"] = True
            data["node_count"] = len(points)
            data["native_length_mm"] = polyline_length(points, bulges, closed)
            data["curve_length_mm"] = data["native_length_mm"]
            return data
        if dxftype == "CIRCLE":
            radius = float(entity.dxf.radius) * scale
            data["geometry"] = {
                "type": "Circle",
                # CIRCLE 的 center 属 OCS，镜像块展开后必须走 OCS->WCS
                "center": DxfReader._ocs_point(entity, entity.dxf.center, scale),
                "radius": radius,
                "circumference_mm": 2.0 * 3.141592653589793 * radius,
            }
            return data
        if dxftype == "ARC":
            center = DxfReader._ocs_point(entity, entity.dxf.center, scale)
            radius = float(entity.dxf.radius) * scale
            start_angle = float(entity.dxf.start_angle)
            end_angle = float(entity.dxf.end_angle)
            data["geometry"] = {
                "type": "Arc",
                "center": center,
                "radius": radius,
                "start_angle": start_angle,
                "end_angle": end_angle,
                "length_mm": arc_length(radius, start_angle, end_angle),
            }
            data["native_length_mm"] = data["geometry"]["length_mm"]
            data["curve_length_mm"] = data["native_length_mm"]
            return data
        if dxftype == "ELLIPSE":
            geometry = DxfReader._ellipse_geometry(entity, scale)
            if not geometry:
                return None
            data["geometry"] = geometry
            return data
        return None

    @staticmethod
    def _ellipse_geometry(entity: Any, scale: float) -> dict[str, Any] | None:
        try:
            center = DxfReader._ocs_point(entity, entity.dxf.center, scale)
            major_axis = entity.dxf.major_axis
            major = (float(major_axis[0]) ** 2 + float(major_axis[1]) ** 2) ** 0.5 * scale
            ratio = abs(float(entity.dxf.ratio or 1.0))
            minor = major * ratio
            rotation = (degrees(atan2(float(major_axis[1]), float(major_axis[0]))) + 360.0) % 360.0
        except Exception:
            return None
        return {
            "type": "Ellipse",
            "center": center,
            "radius_major": major,
            "radius_minor": minor,
            "ratio": ratio,
            "rotation": rotation,
        }

    @staticmethod
    def _header_bounds(doc: Any, scale: float) -> dict[str, dict[str, float]] | None:
        try:
            extmin = doc.header.get("$EXTMIN")
            extmax = doc.header.get("$EXTMAX")
            if extmin is None or extmax is None:
                return None
            return {
                "min": {"x": float(extmin[0]) * scale, "y": float(extmin[1]) * scale},
                "max": {"x": float(extmax[0]) * scale, "y": float(extmax[1]) * scale},
            }
        except Exception:
            return None


__all__ = ["Bounds", "DEFAULT_SCALE_TO_MM", "DxfReader"]
