from __future__ import annotations

import contextlib
import io
from dataclasses import dataclass
from math import atan2, degrees
from pathlib import Path
from typing import Any

import ezdxf

UNIT_SCALE = {0: 1.0, 1: 25.4, 4: 1.0, 5: 10.0, 6: 1000.0}


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

    def as_dict(self) -> dict[str, dict[str, float]]:
        if self.min_x is None:
            return {"min": {"x": 0.0, "y": 0.0}, "max": {"x": 10000.0, "y": 10000.0}}
        return {
            "min": {"x": self.min_x or 0.0, "y": self.min_y or 0.0},
            "max": {"x": self.max_x or 0.0, "y": self.max_y or 0.0},
        }


class DxfReader:
    supported_types = {"INSERT", "LINE", "LWPOLYLINE", "POLYLINE", "TEXT", "MTEXT", "DIMENSION", "CIRCLE", "ARC", "ELLIPSE"}

    @staticmethod
    def read(path: Path) -> dict[str, Any]:
        if not path.exists():
            raise FileNotFoundError(f"DXF 文件不存在: {path}")
        doc = ezdxf.readfile(path, errors="replace")
        units = int(doc.header.get("$INSUNITS", 4) or 4)
        scale = UNIT_SCALE.get(units, 1.0)
        modelspace = doc.modelspace()
        layer_colors = {str(layer.dxf.name): int(layer.dxf.color or 256) for layer in doc.layers}
        layer_linetypes = {str(layer.dxf.name): str(layer.dxf.linetype or "") for layer in doc.layers}
        bounds = Bounds()
        entities: list[dict[str, Any]] = []
        total = 0

        for entity in modelspace:
            total += 1
            if entity.dxftype() not in DxfReader.supported_types:
                continue
            normalized = DxfReader._normalize_entity(entity, scale, bounds, layer_colors, layer_linetypes)
            if normalized:
                entities.append(normalized)

        header_bounds = DxfReader._header_bounds(doc, scale)
        extents = bounds.as_dict()
        if extents["min"]["x"] == 0.0 and extents["max"]["x"] == 10000.0 and header_bounds:
            extents = header_bounds

        return {
            "path": str(path),
            "dxf_version": doc.dxfversion,
            "unit_code": units,
            "unit_scale_to_mm": scale,
            "layer_count": len(doc.layers),
            "layer_names": [layer.dxf.name for layer in doc.layers],
            "total_entities": total,
            "entities": entities,
            "extents": extents,
        }

    @staticmethod
    def _pt(point: Any, scale: float) -> dict[str, float]:
        return {"x": float(point[0]) * scale, "y": float(point[1]) * scale}

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

    @staticmethod
    def _linear_length(points: list[dict[str, float]]) -> float:
        total = 0.0
        for start, end in zip(points, points[1:]):
            total += ((end["x"] - start["x"]) ** 2 + (end["y"] - start["y"]) ** 2) ** 0.5
        return total

    @staticmethod
    def _with_linear_metrics(data: dict[str, Any], points: list[dict[str, float]]) -> dict[str, Any]:
        data["cad_native_linear"] = True
        data["node_count"] = len(points)
        data["native_length_mm"] = DxfReader._linear_length(points)
        return data

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
            position = DxfReader._pt(entity.dxf.insert, scale)
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
            start = DxfReader._pt(entity.dxf.start, scale)
            end = DxfReader._pt(entity.dxf.end, scale)
            DxfReader._add_point(bounds, start)
            DxfReader._add_point(bounds, end)
            points = [start, end]
            data["geometry"] = {"type": "LineString", "points": points}
            return DxfReader._with_linear_metrics(data, points)

        if dxftype == "LWPOLYLINE":
            points = [{"x": float(x) * scale, "y": float(y) * scale} for x, y in entity.get_points("xy")]
            if not points:
                return None
            for point in points:
                DxfReader._add_point(bounds, point)
            closed = bool(entity.closed)
            data["geometry"] = {
                "type": "Polygon" if closed else "LineString",
                "points": points,
                "closed": closed,
            }
            return DxfReader._with_linear_metrics(data, points)

        if dxftype == "POLYLINE":
            points = [{"x": float(point.x) * scale, "y": float(point.y) * scale} for point in entity.points()]
            if not points:
                return None
            for point in points:
                DxfReader._add_point(bounds, point)
            closed = bool(entity.is_closed)
            data["geometry"] = {
                "type": "Polygon" if closed else "LineString",
                "points": points,
                "closed": closed,
            }
            return DxfReader._with_linear_metrics(data, points)

        if dxftype in {"TEXT", "MTEXT"}:
            insert = DxfReader._pt(entity.dxf.insert, scale)
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
            center = DxfReader._pt(entity.dxf.center, scale)
            radius = float(entity.dxf.radius) * scale
            DxfReader._add_point(bounds, {"x": center["x"] - radius, "y": center["y"] - radius})
            DxfReader._add_point(bounds, {"x": center["x"] + radius, "y": center["y"] + radius})
            data["geometry"] = {"type": "Circle", "center": center, "radius": radius}
            return data

        if dxftype == "ARC":
            center = DxfReader._pt(entity.dxf.center, scale)
            radius = float(entity.dxf.radius) * scale
            DxfReader._add_point(bounds, {"x": center["x"] - radius, "y": center["y"] - radius})
            DxfReader._add_point(bounds, {"x": center["x"] + radius, "y": center["y"] + radius})
            data["geometry"] = {
                "type": "Arc",
                "center": center,
                "radius": radius,
                "start_angle": float(entity.dxf.start_angle),
                "end_angle": float(entity.dxf.end_angle),
            }
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
            geometry = DxfReader._dimension_geometry(virtual, scale)
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
    def _dimension_geometry(entity: Any, scale: float) -> dict[str, Any] | None:
        points: list[dict[str, float]] = []
        for name in ("defpoint", "defpoint2", "defpoint3", "defpoint4", "defpoint5", "text_midpoint"):
            try:
                if not entity.dxf.hasattr(name):
                    continue
                point = DxfReader._pt(getattr(entity.dxf, name), scale)
            except Exception:
                continue
            points.append(point)
        if not points:
            try:
                points.append(DxfReader._pt(entity.dxf.insert, scale))
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
                    points.extend((float(x), float(y)) for x, y in entity.get_points("xy"))
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
            points = [DxfReader._pt(entity.dxf.start, scale), DxfReader._pt(entity.dxf.end, scale)]
            data["geometry"] = {"type": "LineString", "points": points}
            return DxfReader._with_linear_metrics(data, points)
        if dxftype == "LWPOLYLINE":
            points = [{"x": float(x) * scale, "y": float(y) * scale} for x, y in entity.get_points("xy")]
            if not points:
                return None
            data["geometry"] = {"type": "Polygon" if entity.closed else "LineString", "points": points, "closed": bool(entity.closed)}
            return DxfReader._with_linear_metrics(data, points)
        if dxftype == "POLYLINE":
            points = [{"x": float(point.x) * scale, "y": float(point.y) * scale} for point in entity.points()]
            if not points:
                return None
            data["geometry"] = {"type": "Polygon" if entity.is_closed else "LineString", "points": points, "closed": bool(entity.is_closed)}
            return DxfReader._with_linear_metrics(data, points)
        if dxftype == "CIRCLE":
            data["geometry"] = {"type": "Circle", "center": DxfReader._pt(entity.dxf.center, scale), "radius": float(entity.dxf.radius) * scale}
            return data
        if dxftype == "ARC":
            data["geometry"] = {
                "type": "Arc",
                "center": DxfReader._pt(entity.dxf.center, scale),
                "radius": float(entity.dxf.radius) * scale,
                "start_angle": float(entity.dxf.start_angle),
                "end_angle": float(entity.dxf.end_angle),
            }
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
            center = DxfReader._pt(entity.dxf.center, scale)
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
