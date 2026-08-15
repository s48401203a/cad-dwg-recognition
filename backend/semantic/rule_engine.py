from __future__ import annotations

import re
import os
from collections import Counter, defaultdict
from copy import deepcopy
from math import atan2, ceil, cos, degrees, hypot, log, radians, sin
from pathlib import Path
from typing import Any

import yaml

from semantic.geometry_utils import line_length

DEFAULT_CONFIG_DIR = Path(__file__).resolve().parents[1] / "config"
PROJECT_RULES_DIR = Path(os.environ["CAD_PROJECT_RULES_DIR"]).expanduser() if os.environ.get("CAD_PROJECT_RULES_DIR") else None


def _project_rule_path(name: str, default: Path) -> Path:
    if PROJECT_RULES_DIR:
        candidate = PROJECT_RULES_DIR / name
        if candidate.exists():
            return candidate
    return default


DEFAULT_MAPPING = _project_rule_path("mapping.yaml", DEFAULT_CONFIG_DIR / "mapping.yaml")
DEFAULT_STANDARDS = _project_rule_path("company_standards.yaml", DEFAULT_CONFIG_DIR / "company_standards.yaml")
DEFAULT_LAYER_RENDER_STANDARDS = _project_rule_path("layer_render_standards.yaml", DEFAULT_CONFIG_DIR / "layer_render_standards.yaml")
DEFAULT_PROFILES_DIR = _project_rule_path("profiles", DEFAULT_CONFIG_DIR / "profiles")
PARAMETER_BLOCK_KEYWORDS = (
    "参数",
    "图例",
    "说明",
    "表格",
    "TITLE",
    "LEGEND",
    "车尾设备",
    "摄像头参数",
    "6mm枪型摄像头",
    "设备编号",
    "新块",
    "2.8mm半球摄像头",
)
PARKING_LAYER_KEYWORDS = ("PARK", "停车", "车位", "货车卸货")

PLAN_COPY_START_X_MM = 2_939_888.0
PLAN_COPY_OFFSET_X_MM = 178_200.0
PLAN_COPY_COUNT = 4
PLAN_MIN_Y_MM = -1_055_000.0
PLAN_MAX_Y_MM = -760_000.0
TRAY_LABEL_TOLERANCE_MM = 2_000.0
TRAY_MIN_SEGMENT_MM = 5_000.0
DOCK_HEIGHT_M = 1.2
WAREHOUSE_WALL_HEIGHT_M = 10.5
WAREHOUSE_ROOF_PEAK_HEIGHT_M = 12.6
POWER_EQUIPMENT_SERVICE_CLEARANCE_M = 0.15
POWER_EQUIPMENT_SERVICE_CHANNEL_M = 0.30
POWER_EQUIPMENT_MIN_CENTER_SPACING_MM = 1_500.0
POWER_EQUIPMENT_WALL_CLEARANCE_M = 0.15
OFFICE_SECOND_FLOOR_ELEVATION_M = 5.5
OFFICE_ROOM_HEIGHT_M = 4.8
OFFICE_CONTAINER_ROOM_HEIGHT_M = 3.0
OFFICE_BBOX_PAD_MM = 1_500.0
GATEHOUSE_FOOTPRINT_PAD_MM = 500.0
GATEHOUSE_DETAIL_WIDTH_MM = 12_450.0
GATEHOUSE_DETAIL_DEPTH_MM = 13_750.0
GATEHOUSE_DETAIL_DIM_TOLERANCE_MM = 1_800.0
GATEHOUSE_MAIN_PLAN_SEARCH_RADIUS_X_MM = 12_000.0
GATEHOUSE_MAIN_PLAN_SEARCH_RADIUS_Y_MM = 12_000.0
GATEHOUSE_MAIN_PLAN_LONG_WALL_MIN_MM = 3_500.0
GATEHOUSE_MAIN_PLAN_PROTRUSION_CLIP_MM = 2_500.0
OFFICE_FOOTPRINT_PAD_MM = 3_500.0
OFFICE_FLOOR_MATCH_PAD_MM = 2_500.0
OFFICE_SEARCH_RADIUS_X_MM = 20_000.0
OFFICE_SEARCH_RADIUS_Y_MM = 12_000.0
OFFICE_ADJACENT_DOCK_PAD_X_MM = 12_000.0
OFFICE_ADJACENT_DOCK_PAD_Y_MM = 25_000.0
OFFICE_AUXILIARY_LINETYPE_TOKENS = ("DASH", "DOTE", "DOT", "HIDDEN", "CENTER", "PHANTOM")
OFFICE_WORKSTATION_BLOCKS = {"2_CR-G650F4KFN68-W"}
OFFICE_MEETING_ROOM_KEYWORDS = ("洽谈室", "会议室")
OFFICE_MEETING_TABLE_SEARCH_RADIUS_MM = 6_000.0
OFFICE_MEETING_TABLE_RADIUS_MIN_MM = 350.0
OFFICE_MEETING_TABLE_RADIUS_MAX_MM = 1_400.0
OFFICE_MEETING_TABLE_OVERLAP_PAD_MM = 650.0
OFFICE_MEETING_TABLE_OVERLAP_SEAT_TYPES = {"office.training_seat", "office.workstation_seat", "office.workstation"}
GATEHOUSE_CONFIRMED_RULESET_ID = "gatehouse_confirmed_v1"
GATEHOUSE_CONFIRMED_RULESET_NAME = "炮楼确认规则"
GENERIC_GATEHOUSE_TOWER_KEY = "generic_gatehouse"
GENERIC_GATEHOUSE_TOWER_LABEL = "办公炮楼"
GENERIC_GATEHOUSE_MAX_FOOTPRINT_SPAN_MM = 22_000.0
GENERIC_GATEHOUSE_MIN_FOOTPRINT_SPAN_MM = 8_000.0
GENERIC_GATEHOUSE_SEED_PAD_MM = 1_000.0
GATEHOUSE_CONFIRMED_LAYOUT_REPLACED_TYPES = {
    "office.workstation",
    "office.workstation_seat",
    "office.training_seat",
    "office.desk_row",
    "office.l_desk",
    "office.meeting_table",
    "office.stair",
    "office.stairwell",
}
OFFICE_GEOMETRY_LAYERS = {
    "A-砼墙",
    "A-SECT-墙体",
    "A-SECT-隔墙",
    "A-SECT-幕墙",
    "A-SECT-门窗",
    "A-SECT-门窗(防火)",
    "A-SECT-楼梯",
    "A-SECT-钢柱",
    "WALL-填充墙(厚)",
    "D&W-墙洞",
    "D&W-门窗编号",
    "D&W-门窗编号-01",
    "D&W-门、提升门、冷库保温门",
    "FURN-厨卫",
    "TK",
    "STRS-楼梯、台阶、坡道",
    "STRS-楼梯、台阶、坡道、升降平台、月台、救援平台",
}
OFFICE_PARTITION_LAYERS = {
    "A-砼墙",
    "A-SECT-墙体",
    "A-SECT-隔墙",
    "A-SECT-幕墙",
    "A-SECT-门窗",
    "A-SECT-门窗(防火)",
    "A-SECT-楼梯",
    "WALL-填充墙(厚)",
    "D&W-墙洞",
    "D&W-门、提升门、冷库保温门",
}
REFERENCE_REGION_KEYWORDS = (
    "施工工艺",
    "工艺要求",
    "安装示意",
    "悬挂方案",
    "正面示意图",
    "侧面示意图",
    "剖面示意图",
    "立面图",
    "图示说明",
)
SYSTEM_VIEW_KEYWORDS = (
    "配电图",
    "电缆示意图",
    "级联线路示意图",
    "网络示意图",
    "网络&广播示意图",
    "网络广播示意图",
    "监控示意图",
    "机柜链路示意图",
    "机柜&射灯电路示意图",
    "机柜射灯电路示意图",
)
DEMOLITION_IGNORE_KEYWORDS = (
    "设备拆除",
    "老场地拆除",
    "旧场地拆除",
    "原场地拆除",
    "老库拆除",
    "旧库拆除",
    "老场地",
    "旧场地",
    "原场地",
    "老库",
    "旧库",
    "拆旧",
    "拆除",
)
PROCESS_NOTE_KEYWORDS = ("施工工艺", "工艺要求", "弱电项目施工工艺要求")
REMOVAL_NOTE_KEYWORDS = (
    "老场地设备拆除",
    "旧场地设备拆除",
    "原场地设备拆除",
    "老库设备拆除",
    "旧库设备拆除",
    "设备拆除清单",
)
REMOVAL_NOTE_STOP_KEYWORDS = ("图示说明", "本期规划")
REFERENCE_DETAIL_PAD_MM = (50_000.0, 22_000.0)
REFERENCE_NOTE_PAD_MM = (8_000.0, 5_000.0)
DEMOLITION_IGNORE_PAD_MM = (25_000.0, 12_000.0)
DEMOLITION_IGNORE_MAX_HIT_RATIO = 0.20
DEMOLITION_IGNORE_MAX_HIT_COUNT = 2500
DEMOLITION_IGNORE_SOURCE_ONLY = "source_text_only"
SMALL_SCALE_ROUTE_MIN_LENGTH_MM = 20.0
SMALL_SCALE_ROUTE_LAYER_FALLBACKS = {
    "A-REDL": ("cable.security", 0.58),
    "A-REDL-GREEN": ("cable.network", 0.58),
}
FALLBACK_STRUCTURE_LAYER_RULES = (
    {
        "type": "building.rack",
        "layers": ("货架规划",),
        "entity_types": {"LINE", "LWPOLYLINE", "POLYLINE"},
        "confidence": 0.62,
    },
    {
        "type": "building.road",
        "layers": ("A-ROAD", "A-ROAD-CENTER", "A-ROAD-RED", "改造修改-道口"),
        "entity_types": {"LINE", "LWPOLYLINE", "POLYLINE"},
        "confidence": 0.64,
    },
    {
        "type": "building.wall",
        "layers": ("WALL", "改造修改-墙", "厂房图", "00-原始墙体", "围墙", "1轮廓实线层"),
        "entity_types": {"LINE", "LWPOLYLINE", "POLYLINE"},
        "confidence": 0.66,
    },
    {
        "type": "building.zone",
        "layers": ("改造修改-区域", "SPACE", "仓库规划"),
        "entity_types": {"LINE", "LWPOLYLINE", "POLYLINE"},
        "confidence": 0.58,
    },
)
SYSTEM_VIEW_REL_BOUNDS_MM = {
    "min_x": -45_000.0,
    "max_x": 45_000.0,
    "min_y": -55_000.0,
    "max_y": -5_000.0,
}
SYSTEM_VIEW_REL_BOUNDS_BY_KIND_MM = {
    "cable": {
        "min_x": -45_000.0,
        "max_x": 45_000.0,
        "min_y": -55_000.0,
        "max_y": -5_000.0,
    },
    "network": {
        "min_x": -45_000.0,
        "max_x": 45_000.0,
        "min_y": -55_000.0,
        "max_y": -5_000.0,
    },
    "cascade": {
        "min_x": -45_000.0,
        "max_x": 45_000.0,
        "min_y": -55_000.0,
        "max_y": -5_000.0,
    },
    "network_broadcast": {
        "min_x": -45_000.0,
        "max_x": 45_000.0,
        "min_y": -55_000.0,
        "max_y": -5_000.0,
    },
    "cabinet_link": {
        "min_x": -45_000.0,
        "max_x": 45_000.0,
        "min_y": -55_000.0,
        "max_y": -5_000.0,
    },
    "cabinet_spotlight_power": {
        "min_x": -45_000.0,
        "max_x": 45_000.0,
        "min_y": -55_000.0,
        "max_y": -5_000.0,
    },
}
AP_LABEL_PREFIX_PATTERN = r"(?:BFR|BGL)(?:-[A-Z0-9]+){1,2}-(?:BG|CD)-AP-"
AP_LABEL_PATTERN = re.compile(rf"{AP_LABEL_PREFIX_PATTERN}\d{{1,3}}", re.IGNORECASE)
AP_LABEL_RANGE_PATTERN = re.compile(rf"({AP_LABEL_PREFIX_PATTERN})(\d{{1,3}})(?:[~～](\d{{1,3}}))?(?=$|[^A-Z0-9~～])", re.IGNORECASE)
AP_LAYOUT_SPACING_FACTOR = 0.55
DOME_COVERAGE_SECTOR_ANGLE_DEG = 90.0
AP_LAYOUT_RADIUS_LIMITS_M = {
    "office": {"min": 4.0, "max": 8.0, "fallback": 6.0},
    "warehouse": {"min": 8.0, "max": 16.0, "fallback": 14.0},
}
NATIVE_CABLE_GEOMETRY_TYPES = {"LineString", "Polygon"}
NATIVE_CABLE_ENTITY_TYPES = {"LINE", "LWPOLYLINE", "POLYLINE"}
NATIVE_CABLE_MIN_LENGTH_MM = 500.0
DEVICE_CABLE_PARENT_KEYWORDS = (
    "枪机距离5500",
    "新6mm枪型摄像头",
    "鱼眼摄像头",
    "无线AP",
    "办公AP",
    "办公半球",
    "枪型摄像头",
    "摄像头",
    "半球",
    "鱼眼",
    "AP",
)
DEVICE_CABLE_CAD_ROLES = {
    "camera_symbol",
    "ap_symbol",
    "fisheye_symbol",
    "dome_symbol",
    "coverage_arc",
    "coverage_fan",
    "ap_coverage",
    "fisheye_coverage",
    "dome_coverage",
}
DEVICE_CABLE_LAYER_KEYWORDS = (
    "IT弱电规划-摄像机",
    "IT弱电规划-AP",
    "摄像机",
    "摄像头",
    "鱼眼",
    "半球",
    "无线AP",
)
SYSTEM_VIEW_ALIGNMENT_LAYERS = {
    "WALL",
    "改造修改-墙",
    "改造修改-区域",
    "SPACE",
}
SYSTEM_VIEW_ALIGNMENT_MIN_POINTS = 40
SYSTEM_VIEW_ALIGNMENT_MAX_ADJUST_X_MM = 150_000.0
SYSTEM_VIEW_ALIGNMENT_MAX_ADJUST_Y_MM = 80_000.0
SYSTEM_VIEW_ALIGNMENT_BUCKET_MM = 500.0
SYSTEM_VIEW_ALIGNMENT_MIN_MATCHES = 24
KW_REAR_CAMERA_MIN_NUMBER = 21
KW_REAR_CAMERA_MAX_NUMBER = 120
SUPPLY_CHAIN_RACK_DOWNLIGHT_CAMERA_RANGES = {"WH": ((33, 54),)}
SUPPLY_CHAIN_RACK_CAMERA_ORIENTATION_RULES = (
    ("WH", 33, 38, 180.0),
    ("WH", 39, 42, 0.0),
    ("WH", 43, 48, 270.0),
    ("WH", 49, 54, 90.0),
)
SUPPLY_CHAIN_RACK_LAYERS = ("货架规划", "大货架", "새솥방뺍")
SUPPLY_CHAIN_RACK_INSERT_BLOCKS = ("TP", "A$C", "ZW$")
PROJECT_REAR_CAMERA_TAIL_GAP_RULES = (
    ("GX", 1, 52, 0.0, 3_500.0),
    ("GX", 53, 102, 180.0, 4_500.0),
    ("CW", 1, 20, 270.0, 5_500.0),
)


class RuleEngine:
    def __init__(
        self,
        mapping_path: Path = DEFAULT_MAPPING,
        standards_path: Path = DEFAULT_STANDARDS,
        layer_render_standards_path: Path = DEFAULT_LAYER_RENDER_STANDARDS,
        profiles_dir: Path = DEFAULT_PROFILES_DIR,
        site_profiles: list[str] | None = None,
        manual_main_frame: dict[str, Any] | None = None,
    ) -> None:
        self.mapping_path = mapping_path
        self.profiles_dir = profiles_dir
        self.site_profiles = self.normalize_site_profiles(site_profiles, require_explicit=False, profiles_dir=profiles_dir)
        self.manual_main_frame = manual_main_frame
        self.profile_configs = self._load_selected_profile_configs(self.site_profiles, profiles_dir)
        self.rules = self._merge_profile_rules(yaml.safe_load(mapping_path.read_text(encoding="utf-8")))
        base_standards = yaml.safe_load(standards_path.read_text(encoding="utf-8")) if standards_path.exists() else {}
        self.standards = self._merge_profile_standards(base_standards)
        self.layer_render_standards_path = layer_render_standards_path
        self.layer_render_standards = (
            yaml.safe_load(layer_render_standards_path.read_text(encoding="utf-8"))
            if layer_render_standards_path.exists()
            else {}
        )
        self.plan_windows: list[dict[str, float]] = []
        self.ignored_regions: list[dict[str, Any]] = []
        self.reference_regions: list[dict[str, Any]] = []
        self.system_views: list[dict[str, Any]] = []
        self.frames: list[dict[str, Any]] = []
        self.base_view: dict[str, Any] | None = None
        self.canonical_views: list[dict[str, Any]] = []
        self.modelspace_scale_to_mm = 1.0
        self.modelspace_scale_source = "dxf_unit_header"
        self._modelspace_scale_infer_source = "dxf_unit_header"
        self.source_record: dict[str, Any] = {}
        self.suppressed_inferences: list[dict[str, Any]] = []

    def _promote_native_cables(self, candidates: list[dict[str, Any]]) -> list[dict[str, Any]]:
        promoted: list[dict[str, Any]] = []
        for item in candidates:
            cable_type = str(item.get("type") or "")
            if not cable_type.startswith("cable."):
                continue
            if cable_type == "cable.unknown" and float(item.get("confidence") or 0) < 0.5:
                continue
            if not (item.get("geometry") or {}).get("points"):
                continue
            clone = deepcopy(item)
            clone["route_source"] = "cad_polyline"
            clone.pop("pending_promotion", None)
            attrs = dict(clone.get("attributes") or {})
            attrs["source_kind"] = attrs.get("source_kind") or "cad_native_line"
            attrs["promoted"] = True
            clone["attributes"] = attrs
            if float(clone.get("confidence") or 0) >= 0.75 and cable_type != "cable.unknown":
                clone["review_needed"] = False
            promoted.append(clone)
        return promoted

    def _is_generic_mode(self) -> bool:
        profiles = {str(item) for item in (self.site_profiles or [])}
        if profiles & {"express", "supply_chain"}:
            return False
        return "generic" in profiles or not profiles

    def _uses_site_layout_inferences(self) -> bool:
        return bool({str(item) for item in (self.site_profiles or [])} & {"express", "supply_chain"})

    @classmethod
    def available_site_profiles(cls, profiles_dir: Path = DEFAULT_PROFILES_DIR) -> dict[str, Any]:
        index_path = profiles_dir / "_index.yaml"
        if not index_path.exists():
            return {"version": "0", "profiles": []}
        index = yaml.safe_load(index_path.read_text(encoding="utf-8")) or {}
        profiles = []
        for item in index.get("profiles", []):
            profile_id = item.get("id")
            config_path = profiles_dir / str(item.get("file") or "")
            config = yaml.safe_load(config_path.read_text(encoding="utf-8")) if config_path.exists() else {}
            profiles.append({**item, **{k: v for k, v in config.items() if k in {"display_name", "description", "site_type"}}})
        return {"version": index.get("version"), "profiles": profiles}

    @classmethod
    def normalize_site_profiles(
        cls,
        site_profiles: list[str] | None,
        require_explicit: bool = False,
        profiles_dir: Path = DEFAULT_PROFILES_DIR,
    ) -> list[str]:
        if not site_profiles:
            site_profiles = ["generic"]
        registry = cls.available_site_profiles(profiles_dir)
        allowed = {str(item.get("id")) for item in registry.get("profiles", []) if item.get("id")}
        if not allowed:
            allowed = {"generic", "express", "supply_chain"}
        normalized: list[str] = []
        for profile in site_profiles:
            profile_id = str(profile or "").strip()
            if not profile_id:
                continue
            if profile_id not in allowed:
                raise ValueError(f"未知场地类型 profile: {profile_id}")
            if profile_id not in normalized:
                normalized.append(profile_id)
        if require_explicit and not normalized:
            raise ValueError("请选择至少一个场地类型 profile 后再解析")
        return normalized or ["generic"]

    def _normalize_modelspace_units(self, parsed: dict[str, Any]) -> dict[str, Any]:
        scale = self._infer_modelspace_scale_to_mm(parsed.get("entities", []))
        self.modelspace_scale_to_mm = scale
        self.modelspace_scale_source = self._modelspace_scale_infer_source if scale != 1.0 else "dxf_unit_header"
        if scale == 1.0:
            return parsed

        scaled = deepcopy(parsed)
        for entity in scaled.get("entities", []):
            self._scale_entity_geometry(entity, scale)
            for virtual_shape in entity.get("cad_virtual_shapes") or []:
                self._scale_entity_geometry(virtual_shape, scale)
        if scaled.get("extents"):
            scaled["extents"] = self._scale_extents(scaled["extents"], scale)
        scaled["modelspace_scale_to_mm"] = scale
        return scaled

    def _infer_modelspace_scale_to_mm(self, entities: list[dict[str, Any]]) -> float:
        self._modelspace_scale_infer_source = "dxf_unit_header"
        area_scale = self._infer_modelspace_scale_from_area_labels(entities)
        if area_scale:
            self._modelspace_scale_infer_source = "area_label_closed_region"
            return area_scale

        xs: list[float] = []
        ys: list[float] = []
        dimension_evidence = 0
        for entity in entities:
            layer = str(entity.get("layer") or "")
            block_name = str(entity.get("block_name") or "")
            text = str(entity.get("text") or "")
            if self._has_dimension_evidence(layer, block_name, text):
                dimension_evidence += 1
            if not self._is_operational_scale_seed(layer, block_name, text):
                continue
            for point in self._geometry_points(entity.get("geometry") or {}):
                xs.append(float(point["x"]))
                ys.append(float(point["y"]))

        if len(xs) < 100:
            return 1.0
        max_span = max(self._robust_span(xs), self._robust_span(ys))
        if 500.0 <= max_span <= 5_000.0 and dimension_evidence >= 2:
            self._modelspace_scale_infer_source = "operational_layer_span"
            return 100.0
        if 5_000.0 < max_span <= 15_000.0 and dimension_evidence >= 2:
            self._modelspace_scale_infer_source = "operational_layer_span"
            return 10.0
        return 1.0

    def _infer_modelspace_scale_from_area_labels(self, entities: list[dict[str, Any]]) -> float | None:
        labels: list[dict[str, Any]] = []
        for entity in entities:
            if entity.get("entity_type") not in {"TEXT", "MTEXT"}:
                continue
            text = str(entity.get("text") or "")
            match = re.search(r"([0-9]{2,6}(?:\.[0-9]+)?)\s*(?:㎡|m2\^?|M2\^?)", text)
            if not match:
                continue
            position = entity.get("geometry", {}).get("position")
            if not position:
                continue
            value_m2 = float(match.group(1))
            if 20.0 <= value_m2 <= 100_000.0:
                labels.append({"position": position, "value_m2": value_m2})
        if len(labels) < 3:
            return None

        polygons: list[dict[str, Any]] = []
        for entity in entities:
            if entity.get("entity_type") not in {"LWPOLYLINE", "POLYLINE"}:
                continue
            geometry = entity.get("geometry") or {}
            points = self._normalized_polygon_points(geometry.get("points") or [])
            if len(points) < 4 or not (geometry.get("closed") or geometry.get("type") == "Polygon"):
                continue
            layer = str(entity.get("layer") or "")
            if not self._is_area_scale_polygon_layer(layer):
                continue
            bbox = self._points_bbox(points)
            raw_area = self._polygon_points_area(points)
            if not bbox or raw_area <= 1.0:
                continue
            polygons.append(
                {
                    "bbox": bbox,
                    "area": raw_area,
                    "center": self._bbox_center(bbox),
                }
            )
        if len(polygons) < 3:
            return None

        candidates = (1.0, 10.0, 100.0, 1000.0)
        support: dict[float, int] = {scale: 0 for scale in candidates}
        error_sum: dict[float, float] = {scale: 0.0 for scale in candidates}
        for label in labels:
            point = label["position"]
            nearby = [
                polygon
                for polygon in polygons
                if self._point_in_bounds(point, polygon["bbox"], pad_mm=25.0)
                or (
                    abs(float(point["x"]) - polygon["center"]["x"]) <= 120.0
                    and abs(float(point["y"]) - polygon["center"]["y"]) <= 120.0
                )
            ]
            if not nearby:
                continue
            for scale in candidates:
                best_error = min(
                    abs(log(max((polygon["area"] * scale * scale / 1_000_000.0) / label["value_m2"], 1e-9)))
                    for polygon in nearby
                )
                if best_error <= 0.28:
                    support[scale] += 1
                    error_sum[scale] += best_error

        ranked = sorted(candidates, key=lambda scale: (support[scale], -error_sum[scale]), reverse=True)
        best = ranked[0]
        runner_up = ranked[1]
        if support[best] >= 3 and support[best] >= support[runner_up] + 2:
            return best
        return None

    @staticmethod
    def _is_area_scale_polygon_layer(layer: str) -> bool:
        return any(keyword in layer for keyword in ("改造修改-区域", "改造修改-墙", "改造修改-道口", "SPACE"))

    @staticmethod
    def _has_dimension_evidence(*values: str) -> bool:
        text = " ".join(str(value) for value in values)
        return bool(re.search(r"\d{4,6}\s*[xX×]\s*\d{4,6}|距离\s*\d{4,6}|\b\d{4,6}\s*(?:mm|MM|毫米|米)?\b", text))

    @staticmethod
    def _is_operational_scale_seed(layer: str, block_name: str, text: str) -> bool:
        combined = f"{layer} {block_name} {text}".upper()
        keywords = (
            "货架",
            "改造修改",
            "S_SURFACE",
            "A-PKNG",
            "A-ROAD",
            "WALL",
            "枪机",
            "摄像",
            "车尾",
            "鱼眼",
            "无线AP",
            " AP",
            "CW-",
            "YY-",
            "WH-",
            "WW-",
            "CD-",
            "机柜",
            "提升门",
        )
        return any(keyword.upper() in combined for keyword in keywords)

    @staticmethod
    def _geometry_points(geometry: dict[str, Any]) -> list[dict[str, float]]:
        points: list[dict[str, float]] = []
        if isinstance(geometry.get("position"), dict):
            points.append(geometry["position"])
        if isinstance(geometry.get("center"), dict):
            points.append(geometry["center"])
        points.extend(point for point in geometry.get("points") or [] if isinstance(point, dict))
        return points

    @staticmethod
    def _robust_span(values: list[float]) -> float:
        if not values:
            return 0.0
        ordered = sorted(values)
        if len(ordered) < 20:
            return ordered[-1] - ordered[0]
        low = ordered[int((len(ordered) - 1) * 0.05)]
        high = ordered[int((len(ordered) - 1) * 0.95)]
        return high - low

    @classmethod
    def _scale_entity_geometry(cls, entity: dict[str, Any], scale: float) -> None:
        geometry = entity.get("geometry")
        if isinstance(geometry, dict):
            cls._scale_geometry(geometry, scale)
        for key in ("height", "native_length_mm", "length_mm"):
            if isinstance(entity.get(key), (int, float)):
                entity[key] = float(entity[key]) * scale

    @classmethod
    def _scale_geometry(cls, geometry: dict[str, Any], scale: float) -> None:
        for key in ("position", "center"):
            point = geometry.get(key)
            if isinstance(point, dict):
                point["x"] = float(point["x"]) * scale
                point["y"] = float(point["y"]) * scale
        for point in geometry.get("points") or []:
            if isinstance(point, dict):
                point["x"] = float(point["x"]) * scale
                point["y"] = float(point["y"]) * scale
        for key in ("radius", "rx", "ry", "radius_major", "radius_minor"):
            if isinstance(geometry.get(key), (int, float)):
                geometry[key] = float(geometry[key]) * scale

    @staticmethod
    def _scale_extents(extents: dict[str, Any], scale: float) -> dict[str, Any]:
        scaled = deepcopy(extents)
        for side in ("min", "max"):
            point = scaled.get(side)
            if isinstance(point, dict):
                point["x"] = float(point.get("x", 0.0)) * scale
                point["y"] = float(point.get("y", 0.0)) * scale
        return scaled

    def _load_selected_profile_configs(self, site_profiles: list[str], profiles_dir: Path) -> list[dict[str, Any]]:
        registry = self.available_site_profiles(profiles_dir)
        by_id = {str(item.get("id")): item for item in registry.get("profiles", [])}
        configs: list[dict[str, Any]] = []
        for profile_id in site_profiles:
            file_name = by_id.get(profile_id, {}).get("file")
            if not file_name:
                continue
            path = profiles_dir / str(file_name)
            if path.exists():
                configs.append(yaml.safe_load(path.read_text(encoding="utf-8")) or {})
        return configs

    def _merge_profile_rules(self, rules: dict[str, Any]) -> dict[str, Any]:
        merged = deepcopy(rules or {})
        for config in self.profile_configs:
            self._deep_merge(merged, config.get("rule_overrides") or {})
        return merged

    def _merge_profile_standards(self, standards: dict[str, Any]) -> dict[str, Any]:
        merged = deepcopy(standards or {})
        for config in self.profile_configs:
            self._deep_merge(merged, config.get("standards_overrides") or {})
        merged.setdefault("site_profiles", self.site_profiles)
        return merged

    @staticmethod
    def _deep_merge(target: dict[str, Any], source: dict[str, Any]) -> dict[str, Any]:
        for key, value in source.items():
            if isinstance(value, dict) and isinstance(target.get(key), dict):
                RuleEngine._deep_merge(target[key], value)
            else:
                target[key] = deepcopy(value)
        return target

    def _filter_project_device_exclusions(self, devices: list[dict[str, Any]]) -> list[dict[str, Any]]:
        rules = self.rules.get("device_exclusions") or []
        if not isinstance(rules, list) or not rules:
            return devices
        kept: list[dict[str, Any]] = []
        suppressed: Counter[str] = Counter()
        for device in devices:
            matched_reason = self._device_exclusion_reason(device, rules)
            if matched_reason:
                suppressed[matched_reason] += 1
                continue
            kept.append(device)
        for reason, count in suppressed.items():
            self._record_suppressed_inference("project_device_exclusion", count, reason)
        return kept

    def _filter_project_cable_exclusions(self, cables: list[dict[str, Any]]) -> list[dict[str, Any]]:
        rules = self.rules.get("cable_exclusions") or []
        if not isinstance(rules, list) or not rules:
            return cables
        kept: list[dict[str, Any]] = []
        suppressed: Counter[str] = Counter()
        for cable in cables:
            matched_reason = self._cable_exclusion_reason(cable, rules)
            if matched_reason:
                suppressed[matched_reason] += 1
                continue
            kept.append(cable)
        for reason, count in suppressed.items():
            self._record_suppressed_inference("project_cable_exclusion", count, reason)
        return kept

    def _device_exclusion_reason(self, device: dict[str, Any], rules: list[dict[str, Any]]) -> str | None:
        attrs = device.get("attributes") or {}
        values = {
            "type": device.get("type"),
            "label": device.get("label"),
            "original_layer": device.get("original_layer"),
            "original_block_name": device.get("original_block_name"),
            "merged_from_system_view": attrs.get("merged_from_system_view"),
            "matched_rule": attrs.get("matched_rule"),
            "matched_source": attrs.get("matched_source"),
        }
        for rule in rules:
            if not isinstance(rule, dict):
                continue
            checks = rule.get("match") if isinstance(rule.get("match"), dict) else rule
            if all(
                self._device_exclusion_value_matches(values.get(key), expected)
                for key, expected in checks.items()
                if key not in {"reason", "match"}
            ):
                return str(rule.get("reason") or "项目本地规则排除设备")
        return None

    def _cable_exclusion_reason(self, cable: dict[str, Any], rules: list[dict[str, Any]]) -> str | None:
        attrs = cable.get("attributes") or {}
        values = {
            "id": cable.get("id"),
            "type": cable.get("type"),
            "label": cable.get("label"),
            "source_entity_id": cable.get("source_entity_id"),
            "original_layer": cable.get("original_layer"),
            "source_kind": attrs.get("source_kind"),
            "layer_role": attrs.get("layer_role"),
            "source_text": attrs.get("source_text"),
        }
        for rule in rules:
            if not isinstance(rule, dict):
                continue
            checks = rule.get("match") if isinstance(rule.get("match"), dict) else rule
            if all(
                self._device_exclusion_value_matches(values.get(key), expected)
                for key, expected in checks.items()
                if key not in {"reason", "match"}
            ):
                return str(rule.get("reason") or "项目本地规则排除线路")
        return None

    @staticmethod
    def _device_exclusion_value_matches(value: Any, expected: Any) -> bool:
        if isinstance(expected, list):
            return any(RuleEngine._device_exclusion_value_matches(value, item) for item in expected)
        if expected is None:
            return value is None
        return str(value or "") == str(expected)

    def classify(self, entity: dict[str, Any]) -> dict[str, Any] | None:
        entity_type = entity.get("entity_type")
        block_name = str(entity.get("block_name", ""))
        if entity_type == "INSERT" and self._is_parameter_block(block_name):
            return None

        if entity_type == "INSERT":
            match = self._match_rule(block_name, self.rules.get("block_rules", {}), "block")
            if match:
                return match

        layer = str(entity.get("layer", ""))
        match = self._match_rule(layer, self.rules.get("layer_rules", {}), "layer")
        if match:
            return match

        text = str(entity.get("text", ""))
        if text:
            match = self._match_rule(text, self.rules.get("text_rules", {}), "text")
            if match:
                return match

        return None

    def build_semantic(self, parsed: dict[str, Any], source: dict[str, Any]) -> dict[str, Any]:
        self.source_record = source or {}
        self.suppressed_inferences = []
        parsed = self._normalize_modelspace_units(parsed)
        self.frames = self._infer_frames(parsed["entities"])
        self.base_view = self._select_base_view(self.frames)
        self.system_views = self._infer_system_views(parsed["entities"])
        self._refine_system_view_alignment(parsed["entities"])
        self.canonical_views = self._infer_canonical_views()
        self.reference_regions = [
            *self._infer_reference_regions(parsed["entities"]),
            *self._reference_regions_from_frames(),
        ]
        self.ignored_regions = self._infer_ignored_regions(parsed["entities"])
        self.plan_windows = self._infer_plan_windows(parsed["entities"])
        process_notes = self._extract_process_notes(parsed["entities"])
        removal_notes = self._extract_removal_notes(parsed["entities"])
        analysis_entities = [entity for entity in parsed["entities"] if not self._is_entity_ignored(entity)]
        model_entities = [entity for entity in analysis_entities if not self._is_entity_reference(entity)]
        label_counts: defaultdict[str, int] = defaultdict(int)
        devices: list[dict[str, Any]] = []
        label_devices: list[dict[str, Any]] = []
        cables: list[dict[str, Any]] = []
        cable_candidates: list[dict[str, Any]] = []
        recognized: set[str] = set()

        for entity in model_entities:
            text_devices = self._devices_from_text_label(entity)
            if text_devices:
                accepted_text_devices = 0
                for text_device in text_devices:
                    position = text_device.get("geometry", {}).get("position")
                    if position and not self._is_model_point(position):
                        continue
                    label_devices.append(text_device)
                    accepted_text_devices += 1
                if not accepted_text_devices:
                    continue
                recognized.add(entity["source_entity_id"])
                continue

            classification = self.classify(entity)
            if not classification:
                native_classification = self._native_cable_classification(entity)
                if native_classification:
                    cable_candidates.append(
                        self._cable(
                            entity,
                            native_classification,
                            candidate=True,
                            source_kind_override="cad_native_line",
                            cad_role_override="cable_native",
                        )
                    )
                    recognized.add(entity["source_entity_id"])
                continue

            semantic_type = classification["type"]
            confidence = float(classification["confidence"])

            if self._is_device_type(semantic_type) and entity.get("geometry", {}).get("type") in {"Point", "Circle"}:
                position = entity.get("geometry", {}).get("position")
                if position and not self._is_model_device_point(position, entity, semantic_type):
                    continue
                devices.append(self._device(entity, classification, label_counts))
                recognized.add(entity["source_entity_id"])
            elif semantic_type.startswith("cable.") and entity.get("geometry", {}).get("type") in {"LineString", "Arc", "Polygon"}:
                native_classification = self._native_cable_classification(entity)
                if native_classification:
                    cable_candidates.append(
                        self._cable(
                            entity,
                            native_classification,
                            candidate=True,
                            source_kind_override="cad_native_line",
                            cad_role_override="cable_native",
                        )
                    )
                else:
                    cable_candidates.append(self._cable(entity, classification, candidate=True))
                recognized.add(entity["source_entity_id"])

        cable_candidates.extend(self._virtual_cable_candidates(model_entities))

        if label_devices:
            devices = self._merge_authoritative_label_devices(devices, label_devices)

        expected = self._expected_inventory(model_entities)
        if self._system_views_are_title_fallback_only():
            fallback_ap_count = self._expected_ap_quantity_note_count(parsed["entities"])
            if fallback_ap_count:
                expected["ap"] = fallback_ap_count
        expected_sources = self._expected_inventory_sources(model_entities, expected)
        office_model = self._infer_office_model(model_entities)
        if self._is_generic_mode():
            cables.extend(self._promote_native_cables(cable_candidates))
        else:
            cables.extend(self._infer_tray_cables(model_entities))
        devices = [self._fold_item_geometry(device) for device in devices]
        devices = self._filter_project_device_exclusions(devices)
        cables = self._dedup_linear_items([self._fold_item_geometry(cable) for cable in cables])
        devices = self._dedup_devices(devices, threshold_mm=1500)
        devices = self._dedup_camera_label_symbol_devices(devices)
        devices = self._dedup_fisheye_label_symbol_devices(devices, expected)
        devices = self._dedup_ap_label_symbol_devices(devices, expected)
        devices = self._dedup_expected_label_devices(devices, expected)
        devices = self._filter_no_main_plan_rear_symbol_copies(devices)
        devices = self._filter_parameter_camera_symbol_duplicates(devices)
        self._repair_duplicate_ap_labels(devices, parsed["entities"])
        if not self._is_generic_mode():
            devices.extend(self._infer_missing_expected_ap_devices(devices, parsed["entities"], office_model))
        devices = [self._normalize_office_device(device, office_model) for device in devices]
        devices = self._dedup_cabinet_labels(devices)
        devices = self._filter_secondary_system_view_cabinets(devices)
        if not self._is_generic_mode():
            devices = self._ensure_ups_battery_cabinet(devices)
        self._apply_power_equipment_clearance(devices)
        self._apply_camera_parameter_notes(devices, parsed["entities"])
        self._annotate_cabinets(devices)
        if self._uses_site_layout_inferences():
            cables.extend(self._infer_cabinet_links(devices))
            cables.extend(self._infer_office_device_links(devices))
            cables.extend(self._infer_single_cabinet_device_links(devices))
        cables = self._dedup_linear_items(cables)
        self._renumber_generated_labels(devices)
        self._apply_cad_coverage_overlays(devices, model_entities)
        self._apply_supply_chain_downlight_camera_symbols(devices, model_entities)
        self._apply_manual_supply_chain_downlight_cameras(devices)
        self._apply_camera_parameter_notes(devices, parsed["entities"])
        self._adjust_ap_coverage_from_layout(devices)
        structures = self._dedup_linear_items([self._fold_item_geometry(item) for item in self._extract_structures(model_entities)])
        structures = self._dedup_linear_items([self._normalize_office_structure(item, office_model) for item in structures])
        structures = self._filter_structure_reference_copies(structures)
        site = self._site_metadata(analysis_entities)
        areas = self._infer_areas(model_entities, office_model)
        shell_area = self._infer_warehouse_shell(structures, devices)
        if (
            not shell_area
            and not self._is_generic_mode()
            and not (self.base_view and self.base_view.get("no_main_plan_mode"))
        ):
            shell_area = self._infer_operational_shell(devices)
        if shell_area:
            areas.insert(0, shell_area)
        self._orient_site_bullet_cameras(devices, shell_area, model_entities)
        if self._uses_site_layout_inferences():
            parking_spaces, fixtures = self._infer_tail_dock_objects(devices, structures, office_model, shell_area, model_entities)
            parking_spaces, fixtures = self._suppress_unanchored_tail_dock_inferences(parking_spaces, fixtures)
            parking_spaces = self._apply_project_rear_camera_tail_gap_to_parking_spaces(parking_spaces)
            self._orient_bullet_cameras_by_cad_parking(devices, parking_spaces)
            cables.extend(self._infer_cabinet_power_cables(devices))
            cables.extend(self._infer_spotlight_cables(fixtures, devices))
        else:
            parking_spaces, fixtures = [], []
        cables = self._dedup_linear_items(cables)
        cables = self._filter_project_cable_exclusions(cables)
        cable_candidates = self._dedup_linear_items(
            [self._fold_item_geometry(candidate) for candidate in cable_candidates]
        )
        cable_candidates, cable_candidate_filtered_out = self._filter_cable_candidates(cable_candidates)
        self._annotate_cable_native_matches(cables, cable_candidates)
        self._annotate_parallel_cable_bundles(cables)
        self._adjust_shell_for_cad_parking_boundary(areas, parking_spaces, devices)
        structures = self._filter_structures_to_warehouse_subject(structures, shell_area, parking_spaces)
        areas.extend(self._infer_dock_operation_areas(parking_spaces, shell_area, site))
        office_objects = self._filter_renderable_office_objects(office_model.get("objects", []))
        active_rule_sets = self._active_gatehouse_rule_sets(office_model, office_objects)
        review_needed = sum(1 for item in [*devices, *cables] if item.get("review_needed") or float(item.get("confidence", 1.0)) < 0.75)
        ignored_entity_count = len(parsed["entities"]) - len(analysis_entities)
        reference_entity_count = len(analysis_entities) - len(model_entities)
        model_extents = self._semantic_model_extents(devices, cables, structures, areas, office_objects, parking_spaces, fixtures)
        cable_candidate_summary = self._cable_candidate_summary(cable_candidates, cable_candidate_filtered_out)

        stats = {
            "total_entities": parsed["total_entities"],
            "devices": len(devices),
            "cables": len(cables),
            "cable_candidates": len(cable_candidates),
            "cable_candidates_filtered_out": len(cable_candidate_filtered_out),
            "structures": len(structures),
            "areas": len(areas),
            "office_objects": len(office_objects),
            "parking_spaces": len(parking_spaces),
            "fixtures": len(fixtures),
            "annotations": 0,
            "unknown": max(parsed["total_entities"] - len(recognized), 0),
            "review_needed": review_needed,
            "ignored_regions": len(self.ignored_regions),
            "ignored_entities": ignored_entity_count,
            "reference_regions": len(self.reference_regions),
            "reference_entities": reference_entity_count,
            "process_notes": len(process_notes),
            "removal_notes": len(removal_notes),
            "cable_candidate_summary": cable_candidate_summary,
            "frames": len(self.frames),
            "canonical_views": len(self.canonical_views),
        }
        quality = self._quality_diagnostics(
            stats,
            devices=devices,
            cables=cables,
            structures=structures,
            areas=areas,
            shell_area=shell_area,
            office_model=office_model,
            parking_spaces=parking_spaces,
            fixtures=fixtures,
            expected=expected,
            expected_sources=expected_sources,
            cable_candidate_summary=cable_candidate_summary,
        )
        quality["frame_partition"] = self._frame_partition_quality(devices)
        if active_rule_sets:
            quality["active_rule_sets"] = active_rule_sets
        quality["layer_rule_audit"] = self._layer_rule_audit(
            parsed["entities"],
            analysis_entities,
            devices=devices,
            cables=cables,
            structures=structures,
            areas=areas,
            parking_spaces=parking_spaces,
            fixtures=fixtures,
        )

        return {
            "schema_version": "1.1.11",
            "site_profiles": self.site_profiles,
            "drawing_meta": {
                "source_file": Path(source["dxf_path"]).name,
                "source_dwg": source["original_name"] if source.get("format") == "dwg" else None,
                "original_name": source.get("original_name"),
                "converted_from_dwg": bool(source.get("converted")),
                "dxf_version": parsed["dxf_version"],
                "parsed_at": source.get("parsed_at"),
                "extents": model_extents or parsed["extents"],
                "raw_extents": parsed["extents"],
                "extents_source": "semantic_model_bounds_outlier_filtered" if model_extents else "dxf_raw_bounds",
                "unit": "mm",
                "unit_scale_to_mm": parsed.get("unit_scale_to_mm"),
                "modelspace_scale_to_mm": self.modelspace_scale_to_mm,
                "modelspace_scale_source": self.modelspace_scale_source,
                "layers": parsed.get("layer_count", 0),
                "ignored_regions": self.ignored_regions,
                "reference_regions": self.reference_regions,
                "system_views": self.system_views,
                "frames": self.frames,
                "base_view": self.base_view,
                "canonical_views": self.canonical_views,
            },
            "coordinate_system": {
                "unit": "mm",
                "scale_to_meters": 0.001,
                "three_js_mapping": "x->x, y->-z, elevation per type",
            },
            "site": site,
            "stats": stats,
            "quality": quality,
            "active_rule_sets": active_rule_sets,
            "parse_capabilities": self._parse_capability_summary(),
            "frames": self.frames,
            "base_view": self.base_view,
            "canonical_views": self.canonical_views,
            "no_main_plan_mode": bool(self.base_view and self.base_view.get("kind") != "main_plan"),
            "process_notes": process_notes,
            "removal_notes": removal_notes,
            "devices": devices,
            "cables": cables,
            "cable_candidates": cable_candidates[:500],
            "cable_candidate_filtered_out": cable_candidate_filtered_out[:1000],
            "cable_candidate_summary": cable_candidate_summary,
            "structures": structures[:3000],
            "areas": areas,
            "office_objects": office_objects,
            "parking_spaces": parking_spaces,
            "fixtures": fixtures,
            "annotations": [],
        }

    def _extract_structures(self, entities: list[dict[str, Any]]) -> list[dict[str, Any]]:
        structures: list[dict[str, Any]] = []
        structure_rules = self.rules.get("structure_rules", {})
        for entity in entities:
            entity_type = entity.get("entity_type")
            if entity_type not in {"LINE", "LWPOLYLINE", "POLYLINE", "CIRCLE", "INSERT"}:
                continue
            geometry = entity.get("geometry")
            anchor = self._geometry_anchor(geometry or {})
            if not anchor:
                continue
            if not self._is_generic_mode() and self._plan_copy_index(anchor) is None:
                continue
            layer = str(entity.get("layer", ""))
            main_outline = self._main_plan_outline_structure(entity, layer, entity_type, geometry or {})
            if main_outline:
                structures.append(main_outline)
                continue
            supply_chain_rack = self._supply_chain_rack_structure(entity, layer, entity_type, geometry or {})
            if supply_chain_rack:
                structures.append(supply_chain_rack)
                continue
            fallback_structure = self._fallback_structure_classification(layer, entity_type)
            for structure_type, config in structure_rules.items():
                allowed_types = set(config.get("entity_types", []))
                if entity_type not in allowed_types:
                    continue
                if not self._layer_matches(layer, config.get("layers", [])):
                    continue
                structures.append(
                    {
                        "id": f"struct_{entity['source_entity_id']}",
                        "type": structure_type,
                        "layer": layer,
                        "source_entity_id": entity["source_entity_id"],
                        "confidence": float(config.get("confidence", 0.85)),
                        "geometry": geometry,
                    }
                )
                break
            else:
                if fallback_structure:
                    structures.append(
                        {
                            "id": f"struct_{entity['source_entity_id']}",
                            "type": fallback_structure["type"],
                            "layer": layer,
                            "source_entity_id": entity["source_entity_id"],
                            "confidence": fallback_structure["confidence"],
                            "geometry": geometry,
                            "attributes": {
                                "source_kind": "fallback_structure_layer",
                                "matched_layer": fallback_structure["matched_layer"],
                                "review_needed": True,
                            },
                        }
                    )
        return structures

    def _green_roof_layer_wall_structure(
        self,
        entity: dict[str, Any],
        layer: str,
        entity_type: str,
        geometry: dict[str, Any],
    ) -> dict[str, Any] | None:
        if entity_type not in {"LINE", "LWPOLYLINE", "POLYLINE"}:
            return None
        if not (layer.startswith("W-") and any(token in layer for token in ("屋", "塁"))):
            return None
        if int(entity.get("effective_color") or entity.get("color") or 0) != 3:
            return None
        anchor = self._geometry_anchor(geometry)
        if not anchor or not self._system_view_for_point(anchor):
            return None
        points = geometry.get("points") or []
        if len(points) < 2 or line_length(points) < 2_000.0:
            return None
        return {
            "id": f"struct_{entity['source_entity_id']}",
            "type": "building.wall",
            "layer": layer,
            "source_entity_id": entity["source_entity_id"],
            "confidence": 0.84,
            "geometry": geometry,
            "attributes": {
                "source_kind": "cad_green_roof_layer_wall",
                "matched_layer": layer,
                "matched_color": "green",
                "evidence": "现场图纸确认：W-屋面绿色多段线为墙/分隔墙边界",
            },
        }

    def _supply_chain_rack_structure(
        self,
        entity: dict[str, Any],
        layer: str,
        entity_type: str,
        geometry: dict[str, Any],
    ) -> dict[str, Any] | None:
        if "supply_chain" not in self.site_profiles:
            return None
        if not any(token in layer for token in SUPPLY_CHAIN_RACK_LAYERS):
            return None
        if entity_type in {"LWPOLYLINE", "POLYLINE", "LINE"}:
            return {
                "id": f"struct_{entity['source_entity_id']}",
                "type": "building.rack",
                "layer": layer,
                "source_entity_id": entity["source_entity_id"],
                "confidence": 0.82,
                "geometry": geometry,
                "attributes": {
                    "source_kind": "supply_chain_rack_geometry",
                    "matched_layer": layer,
                    "render_role": "rack_outline",
                },
            }
        if entity_type != "INSERT":
            return None
        block_name = str(entity.get("block_name") or "")
        compact_block = block_name.upper()
        if not any(token in compact_block for token in SUPPLY_CHAIN_RACK_INSERT_BLOCKS):
            return None
        position = (geometry or {}).get("position")
        if not position:
            return None
        is_pallet = compact_block.startswith("TP")
        return {
            "id": f"struct_{entity['source_entity_id']}",
            "type": "building.rack",
            "layer": layer,
            "source_entity_id": entity["source_entity_id"],
            "confidence": 0.86,
            "geometry": {"type": "Point", "position": position},
            "attributes": {
                "source_kind": "supply_chain_rack_insert",
                "matched_layer": layer,
                "block_name": block_name,
                "rotation_deg": float(entity.get("rotation") or 0.0),
                "render_role": "pallet_ground_stack" if is_pallet else "rack_unit",
                "width_m": 1.2 if is_pallet else 1.1,
                "depth_m": 1.0 if is_pallet else 1.2,
                "height_m": 0.22 if is_pallet else 2.2,
            },
        }

    def _main_plan_outline_structure(
        self,
        entity: dict[str, Any],
        layer: str,
        entity_type: str,
        geometry: dict[str, Any],
    ) -> dict[str, Any] | None:
        if entity_type not in {"LWPOLYLINE", "POLYLINE"}:
            return None
        if not self._is_warehouse_outline_layer(layer):
            return None
        if not (geometry.get("closed") or geometry.get("type") == "Polygon"):
            return None
        bounds = (self.base_view or {}).get("bounds") or {}
        if not bounds:
            return None
        points = self._normalized_polygon_points(geometry.get("points") or [])
        if len(points) < 4:
            return None
        bbox = self._points_bbox(points)
        if not bbox:
            return None
        span_x = bbox["max_x"] - bbox["min_x"]
        span_y = bbox["max_y"] - bbox["min_y"]
        if span_x < 30_000.0 or span_y < 25_000.0:
            return None
        if float(entity.get("native_length_mm") or line_length(points)) < 80_000.0:
            return None
        axis_stats = self._axis_aligned_polyline_stats(points, closed=True)
        if axis_stats["total_length"] <= 0.0 or axis_stats["off_axis_ratio"] > 0.18:
            return None
        overlap = self._bbox_overlap_area(bbox, bounds)
        if overlap / max(self._bbox_area(bbox), 1.0) < 0.92:
            return None
        base_span_x = float(bounds.get("max_x", 0.0) or 0.0) - float(bounds.get("min_x", 0.0) or 0.0)
        base_span_y = float(bounds.get("max_y", 0.0) or 0.0) - float(bounds.get("min_y", 0.0) or 0.0)
        base_area = max(base_span_x * base_span_y, 1.0)
        if (span_x * span_y) / base_area > 0.60:
            return None
        frame_like = (
            span_x >= base_span_x * 0.92
            and span_y >= base_span_y * 0.92
            and abs(bbox["min_x"] - float(bounds.get("min_x", 0.0))) <= max(base_span_x * 0.03, 5_000.0)
            and abs(bbox["max_x"] - float(bounds.get("max_x", 0.0))) <= max(base_span_x * 0.03, 5_000.0)
        )
        if frame_like:
            return None
        return {
            "id": f"struct_{entity['source_entity_id']}",
            "type": "building.outline",
            "layer": layer,
            "source_entity_id": entity["source_entity_id"],
            "confidence": 0.84,
            "geometry": geometry,
            "attributes": {
                "source_kind": "warehouse_wall_outline",
                "matched_layer": layer,
                "role": "warehouse_subject_outline",
                "review_needed": False,
            },
        }

    @staticmethod
    def _is_warehouse_outline_layer(layer: str) -> bool:
        normalized = str(layer or "").upper()
        exact_blacklist = {"A-ROAD-RED", "0"}
        if normalized in exact_blacklist:
            return False
        blacklist = ("ROAD", "道路", "红线", "车位", "PARK", "租赁", "三方", "园区")
        if any(keyword.upper() in normalized for keyword in blacklist):
            return False
        keywords = (
            "WALL",
            "WALL_OUT",
            "BUILDING_OUTLINE",
            "A-WALL",
            "仓库轮廓",
            "建筑轮廓",
            "外墙",
            "墙体",
        )
        return any(keyword.upper() in normalized for keyword in keywords)

    @staticmethod
    def _fallback_structure_classification(layer: str, entity_type: str) -> dict[str, Any] | None:
        for config in FALLBACK_STRUCTURE_LAYER_RULES:
            if entity_type not in config["entity_types"]:
                continue
            matched_layer = next((candidate for candidate in config["layers"] if layer == candidate or candidate in layer), None)
            if not matched_layer:
                continue
            return {
                "type": config["type"],
                "confidence": float(config["confidence"]),
                "matched_layer": matched_layer,
            }
        return None

    @staticmethod
    def _layer_matches(layer: str, candidates: list[str]) -> bool:
        return any(layer == candidate or candidate in layer for candidate in candidates)

    @staticmethod
    def _dedup_devices(devices: list[dict[str, Any]], threshold_mm: float = 1500) -> list[dict[str, Any]]:
        kept: list[dict[str, Any]] = []
        for device in devices:
            pos = device.get("geometry", {}).get("position")
            if not pos:
                kept.append(device)
                continue
            duplicate = False
            for existing in kept:
                if existing.get("type") != device.get("type"):
                    continue
                label = RuleEngine._short_label_key(str(device.get("label", "")))
                existing_label = RuleEngine._short_label_key(str(existing.get("label", "")))
                if label and existing_label and label != existing_label:
                    continue
                ex_pos = existing.get("geometry", {}).get("position")
                if not ex_pos:
                    continue
                distance = ((pos["x"] - ex_pos["x"]) ** 2 + (pos["y"] - ex_pos["y"]) ** 2) ** 0.5
                if distance < threshold_mm:
                    duplicate = True
                    break
            if not duplicate:
                kept.append(device)
        return kept

    @staticmethod
    def _dedup_camera_label_symbol_devices(devices: list[dict[str, Any]]) -> list[dict[str, Any]]:
        label_devices = [
            device
            for device in devices
            if RuleEngine._is_camera_text_label_device(device)
            and device.get("geometry", {}).get("position")
        ]
        if not label_devices:
            return devices

        kept: list[dict[str, Any]] = []
        for device in devices:
            if not RuleEngine._is_camera_symbol_device(device):
                kept.append(device)
                continue

            pos = device.get("geometry", {}).get("position")
            if not pos:
                kept.append(device)
                continue

            duplicate_label = RuleEngine._nearest_duplicate_camera_label(device, label_devices)
            if not duplicate_label:
                kept.append(device)
                continue

            label, distance = duplicate_label
            radius = RuleEngine._camera_label_symbol_dedup_radius(device, label)
            if distance <= radius:
                RuleEngine._merge_duplicate_device_attrs(label, device)
                attrs = label.setdefault("attributes", {})
                attrs["dedup_source"] = attrs.get("dedup_source") or "camera_label_authoritative_over_symbol_block"
                continue

            kept.append(device)
        return kept

    @staticmethod
    def _is_camera_text_label_device(device: dict[str, Any]) -> bool:
        device_type = str(device.get("type") or "")
        if not device_type.startswith("security.camera"):
            return False
        source_kind = (device.get("attributes") or {}).get("source_kind")
        if source_kind not in {"text_label", "text_label_range"}:
            return False
        label = RuleEngine._short_label_key(str(device.get("label") or ""))
        return bool(label and not re.fullmatch(r"C-?\d{1,4}", label))

    @staticmethod
    def _is_camera_symbol_device(device: dict[str, Any]) -> bool:
        device_type = str(device.get("type") or "")
        if not device_type.startswith("security.camera"):
            return False
        source_kind = (device.get("attributes") or {}).get("source_kind")
        if source_kind in {"text_label", "text_label_range"}:
            return False
        block_name = str(device.get("original_block_name") or "")
        upper_block = block_name.upper()
        attrs = device.get("attributes") or {}
        matched_source = str(attrs.get("matched_source") or "")
        return (
            matched_source == "block"
            or any(keyword in block_name for keyword in ("摄像", "摄像头", "鱼眼", "半球", "枪机", "枪型"))
            or any(keyword in upper_block for keyword in ("CAMERA", "CCTV", "IPC", "DOME", "BULLET", "FISHEYE"))
        )

    @staticmethod
    def _nearest_duplicate_camera_label(
        symbol_device: dict[str, Any],
        label_devices: list[dict[str, Any]],
    ) -> tuple[dict[str, Any], float] | None:
        pos = symbol_device.get("geometry", {}).get("position") or {}
        nearest: tuple[dict[str, Any], float] | None = None
        for label in label_devices:
            if not RuleEngine._camera_label_can_replace_symbol(symbol_device, label):
                continue
            label_pos = label.get("geometry", {}).get("position") or {}
            distance = hypot(pos["x"] - label_pos["x"], pos["y"] - label_pos["y"])
            if nearest is None or distance < nearest[1]:
                nearest = (label, distance)
        return nearest

    @staticmethod
    def _camera_label_can_replace_symbol(symbol_device: dict[str, Any], label_device: dict[str, Any]) -> bool:
        symbol_type = str(symbol_device.get("type") or "")
        label_type = str(label_device.get("type") or "")
        if not symbol_type.startswith("security.camera") or not label_type.startswith("security.camera"):
            return False
        if symbol_type == label_type:
            return True
        if symbol_type == "security.camera":
            return True
        return symbol_type in {"security.camera.bullet", "security.camera.rear"} and label_type in {
            "security.camera.bullet",
            "security.camera.rear",
        }

    @staticmethod
    def _camera_label_symbol_dedup_radius(symbol_device: dict[str, Any], label_device: dict[str, Any]) -> float:
        symbol_type = str(symbol_device.get("type") or "")
        label_type = str(label_device.get("type") or "")
        if symbol_type == "security.camera" and label_type.startswith("security.camera"):
            return 2_200.0
        return 1_500.0

    @staticmethod
    def _dedup_expected_label_devices(devices: list[dict[str, Any]], expected: dict[str, int]) -> list[dict[str, Any]]:
        type_expected = {
            "security.camera.fisheye": int(expected.get("fisheye", 0) or 0),
            "security.camera.dome": int(expected.get("dome_camera", 0) or 0),
            "network.ap": int(expected.get("ap", 0) or 0),
            "security.camera.rear": int(expected.get("rear_camera", 0) or 0),
        }
        current_counts: defaultdict[str, int] = defaultdict(int)
        for device in devices:
            current_counts[str(device.get("type", ""))] += 1

        seen_labels: set[tuple[str, str]] = set()
        kept: list[dict[str, Any]] = []
        for device in devices:
            device_type = str(device.get("type", ""))
            expected_count = type_expected.get(device_type, 0)
            label = re.sub(r"\s+", "", str(device.get("label", "")).upper())
            key = (device_type, label)
            if expected_count and current_counts[device_type] > expected_count and label and key in seen_labels:
                current_counts[device_type] -= 1
                continue
            seen_labels.add(key)
            kept.append(device)
        return kept

    def _filter_no_main_plan_rear_symbol_copies(self, devices: list[dict[str, Any]]) -> list[dict[str, Any]]:
        if not self._is_no_main_plan_mode():
            return devices
        authoritative_rear_labels = [
            device
            for device in devices
            if device.get("type") == "security.camera.rear"
            and self._is_rear_camera_label(str(device.get("label") or ""))
            and (device.get("attributes") or {}).get("source_kind") in {"text_label", "text_label_range"}
        ]
        if len(authoritative_rear_labels) < 8:
            return devices
        kept: list[dict[str, Any]] = []
        suppressed = 0
        for device in devices:
            attrs = device.get("attributes") or {}
            if (
                device.get("type") == "security.camera.rear"
                and attrs.get("matched_source") == "block"
                and attrs.get("merged_from_plan_copy") is not None
                and "车尾摄像头" in str(device.get("original_block_name") or "")
            ):
                suppressed += 1
                continue
            kept.append(device)
        if suppressed:
            self._record_suppressed_inference(
                "no_main_plan_rear_symbol_copy",
                suppressed,
                "无主平面模式下已有 CW/GX/KW 文本编号车尾摄像头时，忽略平移副本中的通用车尾摄像头块，避免重复生成 C-xxx 设备",
            )
        return kept

    def _filter_parameter_camera_symbol_duplicates(self, devices: list[dict[str, Any]]) -> list[dict[str, Any]]:
        authoritative_camera_labels = [
            device
            for device in devices
            if str(device.get("type") or "") in {"security.camera.bullet", "security.camera.rear"}
            and (device.get("attributes") or {}).get("source_kind") in {"text_label", "text_label_range"}
            and self._short_label_key(str(device.get("label") or ""))
        ]
        if len(authoritative_camera_labels) < 8:
            return devices
        kept: list[dict[str, Any]] = []
        suppressed = 0
        for device in devices:
            attrs = device.get("attributes") or {}
            block_name = str(device.get("original_block_name") or "")
            if (
                str(device.get("type") or "") in {"security.camera.bullet", "security.camera.rear"}
                and attrs.get("matched_source") == "block"
                and attrs.get("source_kind") not in {"text_label", "text_label_range"}
                and (self._is_parameter_block(block_name) or "距离" in block_name)
            ):
                suppressed += 1
                continue
            kept.append(device)
        if suppressed:
            self._record_suppressed_inference(
                "parameter_camera_symbol_duplicate",
                suppressed,
                "已有文本编号摄像头时，距离/参数类摄像头块只作为覆盖和安装参数证据，不额外生成 C-xxx 摄像头设备",
            )
        return kept

    @staticmethod
    def _dedup_fisheye_label_symbol_devices(devices: list[dict[str, Any]], expected: dict[str, int]) -> list[dict[str, Any]]:
        expected_fisheye = int(expected.get("fisheye", 0) or 0)
        if expected_fisheye <= 0:
            return devices

        fisheye_devices = [device for device in devices if device.get("type") == "security.camera.fisheye"]
        if len(fisheye_devices) <= expected_fisheye:
            return devices

        label_devices = [
            device
            for device in fisheye_devices
            if (device.get("attributes") or {}).get("source_kind") == "text_label"
            and re.fullmatch(r"YY-?\d{1,3}", re.sub(r"\s+", "", str(device.get("label", "")).upper()))
        ]
        symbol_devices = [
            device
            for device in fisheye_devices
            if (device.get("attributes") or {}).get("source_kind") != "text_label"
            and "鱼眼" in str(device.get("original_block_name") or "")
        ]
        if len(label_devices) < expected_fisheye or not symbol_devices:
            return devices

        label_ids = {id(device) for device in label_devices}
        symbol_ids = {id(device) for device in symbol_devices}
        kept: list[dict[str, Any]] = []
        label_kept = 0
        symbol_dropped = 0
        for device in devices:
            if id(device) in symbol_ids:
                symbol_dropped += 1
                continue
            if id(device) in label_ids:
                if label_kept >= expected_fisheye:
                    continue
                attrs = device.setdefault("attributes", {})
                attrs["deduped_symbol_fisheye_count"] = len(symbol_devices)
                attrs["dedup_source"] = "yy_label_authoritative_over_fisheye_symbol_blocks"
                label_kept += 1
            kept.append(device)
        if symbol_dropped:
            for device in kept:
                if device.get("type") == "security.camera.fisheye" and (device.get("attributes") or {}).get("source_kind") == "text_label":
                    device.setdefault("attributes", {})["deduped_symbol_fisheye_count"] = symbol_dropped
        return kept

    @staticmethod
    def _dedup_ap_label_symbol_devices(devices: list[dict[str, Any]], expected: dict[str, int]) -> list[dict[str, Any]]:
        expected_ap = int(expected.get("ap", 0) or 0)
        if expected_ap <= 0:
            return devices

        ap_devices = [device for device in devices if device.get("type") == "network.ap"]
        if len(ap_devices) <= expected_ap:
            return devices

        label_devices = [
            device
            for device in ap_devices
            if (device.get("attributes") or {}).get("source_kind") in {"text_label", "text_label_range"}
            and AP_LABEL_PATTERN.fullmatch(re.sub(r"\s+", "", str(device.get("label", "")).upper()))
        ]
        symbol_devices = [
            device
            for device in ap_devices
            if (device.get("attributes") or {}).get("source_kind") not in {"text_label", "text_label_range"}
            and "无线AP" in str(device.get("original_block_name") or "")
        ]
        if len(label_devices) < expected_ap or not symbol_devices:
            return devices

        label_ids = {id(device) for device in label_devices}
        symbol_ids = {id(device) for device in symbol_devices}
        symbol_dropped = 0
        kept: list[dict[str, Any]] = []
        for device in devices:
            if id(device) in symbol_ids:
                symbol_dropped += 1
                continue
            if id(device) in label_ids:
                attrs = device.setdefault("attributes", {})
                attrs["deduped_symbol_ap_count"] = len(symbol_devices)
                attrs["dedup_source"] = "ap_label_authoritative_over_wireless_ap_symbol_blocks"
            kept.append(device)
        if symbol_dropped:
            for device in kept:
                if device.get("type") == "network.ap" and id(device) in label_ids:
                    device.setdefault("attributes", {})["deduped_symbol_ap_count"] = symbol_dropped
        return kept

    @staticmethod
    def _merge_authoritative_label_devices(
        devices: list[dict[str, Any]],
        label_devices: list[dict[str, Any]],
        threshold_mm: float = 1500.0,
    ) -> list[dict[str, Any]]:
        """Prefer CAD text labels only for nearby duplicate symbol devices."""
        label_authoritative_types = {
            "security.camera",
            "security.camera.rear",
            "security.camera.fisheye",
            "security.camera.bullet",
            "security.camera.dome",
            "network.ap",
        }
        label_positions = [
            (label.get("type"), label.get("geometry", {}).get("position"))
            for label in label_devices
            if label.get("type") in label_authoritative_types and label.get("geometry", {}).get("position")
        ]
        kept: list[dict[str, Any]] = []
        for device in devices:
            device_type = device.get("type")
            position = device.get("geometry", {}).get("position")
            if device_type not in label_authoritative_types or not position:
                kept.append(device)
                continue
            duplicate_label = any(
                label_type == device_type
                and label_position
                and hypot(position["x"] - label_position["x"], position["y"] - label_position["y"]) <= threshold_mm
                for label_type, label_position in label_positions
            )
            if not duplicate_label:
                kept.append(device)
        kept.extend(label_devices)
        return kept

    @staticmethod
    def _label_key(label: str) -> str:
        return re.sub(r"\s+", "", str(label or "").upper())

    @staticmethod
    def _cabinet_dedup_priority(device: dict[str, Any]) -> int:
        attrs = device.get("attributes") or {}
        role = str(attrs.get("cabinet_role") or "")
        if role in {"ups_power", "ups_battery"}:
            return 0
        if int(attrs.get("rack_units") or 0) == 42:
            return 0
        source_view = str(attrs.get("merged_from_system_view") or "")
        if source_view in {"monitor", "network_broadcast"}:
            return 1
        if source_view in {"cabinet_link", "cabinet_spotlight_power"}:
            return 3
        if source_view:
            return 2
        return 2

    @staticmethod
    def _merge_duplicate_device_attrs(target: dict[str, Any], duplicate: dict[str, Any]) -> None:
        attrs = target.setdefault("attributes", {})
        duplicate_attrs = duplicate.get("attributes") or {}
        source_ids = attrs.setdefault("deduped_source_entity_ids", [])
        duplicate_id = duplicate.get("source_entity_id") or duplicate.get("id")
        if duplicate_id and duplicate_id not in source_ids:
            source_ids.append(duplicate_id)
        views = attrs.setdefault("deduped_system_views", [])
        for view in (attrs.get("merged_from_system_view"), duplicate_attrs.get("merged_from_system_view")):
            if view and view not in views:
                views.append(view)
        labels = attrs.setdefault("deduped_labels", [])
        duplicate_label = duplicate.get("label")
        if duplicate_label and duplicate_label not in labels:
            labels.append(duplicate_label)
        attrs["deduped_duplicate_count"] = int(attrs.get("deduped_duplicate_count") or 0) + 1

    def _dedup_cabinet_labels(self, devices: list[dict[str, Any]]) -> list[dict[str, Any]]:
        kept: list[dict[str, Any]] = []
        for device in devices:
            if device.get("type") != "network.cabinet":
                kept.append(device)
                continue
            label = self._label_key(str(device.get("label") or ""))
            pos = device.get("geometry", {}).get("position")
            if not label or not pos:
                kept.append(device)
                continue

            duplicate_index: int | None = None
            for index, existing in enumerate(kept):
                if existing.get("type") != "network.cabinet" or self._label_key(str(existing.get("label") or "")) != label:
                    continue
                existing_pos = existing.get("geometry", {}).get("position")
                if not existing_pos:
                    continue
                distance = self._distance(pos, existing_pos)
                source_view = str((device.get("attributes") or {}).get("merged_from_system_view") or "")
                existing_view = str((existing.get("attributes") or {}).get("merged_from_system_view") or "")
                threshold = 5_000.0 if (source_view or existing_view) else 2_500.0
                if distance <= threshold:
                    duplicate_index = index
                    break

            if duplicate_index is None:
                kept.append(device)
                continue

            existing = kept[duplicate_index]
            if self._cabinet_dedup_priority(device) < self._cabinet_dedup_priority(existing):
                self._merge_duplicate_device_attrs(device, existing)
                kept[duplicate_index] = device
            else:
                self._merge_duplicate_device_attrs(existing, device)
        return kept

    def _filter_secondary_system_view_cabinets(self, devices: list[dict[str, Any]]) -> list[dict[str, Any]]:
        if not (self.base_view and self.base_view.get("no_main_plan_mode") and self.base_view.get("kind") == "monitor"):
            return devices
        monitor_cabinets = [
            device
            for device in devices
            if device.get("type") == "network.cabinet"
            and str((device.get("attributes") or {}).get("merged_from_system_view") or "monitor") == "monitor"
        ]
        if not monitor_cabinets:
            return devices
        filtered: list[dict[str, Any]] = []
        for device in devices:
            if device.get("type") != "network.cabinet":
                filtered.append(device)
                continue
            source_view = str((device.get("attributes") or {}).get("merged_from_system_view") or "")
            if source_view in {"network_broadcast", "network"} and self._is_distinct_network_cabinet(device):
                filtered.append(device)
                continue
            if source_view in {"network_broadcast", "network", "cabinet_link", "cabinet_spotlight_power"} and self._duplicates_monitor_cabinet(device, monitor_cabinets):
                continue
            filtered.append(device)
        return filtered

    @staticmethod
    def _cabinet_identity_text(device: dict[str, Any]) -> str:
        attrs = device.get("attributes") or {}
        return re.sub(r"\s+", "", f"{device.get('label') or ''}{attrs.get('source_text') or ''}".upper())

    @classmethod
    def _is_distinct_network_cabinet(cls, device: dict[str, Any]) -> bool:
        text = cls._cabinet_identity_text(device)
        return any(keyword in text for keyword in ("网络挂墙", "广播机柜", "网络机柜"))

    @classmethod
    def _duplicates_monitor_cabinet(cls, device: dict[str, Any], monitor_cabinets: list[dict[str, Any]]) -> bool:
        label = cls._label_key(str(device.get("label") or ""))
        pos = device.get("geometry", {}).get("position")
        text = cls._cabinet_identity_text(device)
        for monitor in monitor_cabinets:
            monitor_label = cls._label_key(str(monitor.get("label") or ""))
            monitor_pos = monitor.get("geometry", {}).get("position")
            if label and monitor_label and label == monitor_label:
                return True
            if not pos or not monitor_pos:
                continue
            monitor_text = cls._cabinet_identity_text(monitor)
            same_family = ("监控挂墙" in text and "监控挂墙" in monitor_text) or ("42U机柜" in text and "42U机柜" in monitor_text)
            if same_family and cls._distance(pos, monitor_pos) <= 5_000.0:
                return True
        return False

    def _ensure_ups_battery_cabinet(self, devices: list[dict[str, Any]]) -> list[dict[str, Any]]:
        if self._system_views_are_title_fallback_only():
            return devices
        if self._primary_ups_battery_device(devices):
            return devices
        ups = self._primary_ups_device(devices)
        if not ups or not ups.get("geometry", {}).get("position"):
            return devices
        ups_pos = ups["geometry"]["position"]
        core = self._primary_power_room_core_cabinet(devices, ups)
        direction = self._power_equipment_layout_direction(core, ups)
        battery_pos = {
            "x": float(ups_pos["x"]) + direction["x"] * POWER_EQUIPMENT_MIN_CENTER_SPACING_MM,
            "y": float(ups_pos["y"]) + direction["y"] * POWER_EQUIPMENT_MIN_CENTER_SPACING_MM,
        }
        ups_attrs = ups.get("attributes") or {}
        battery_attrs = {
            **{key: ups_attrs[key] for key in ("zone", "tower", "tower_label", "level", "floor_label", "floor_elevation_m", "room_height_m", "source_floor_bbox", "target_floor_bbox", "target_device_bbox") if key in ups_attrs},
            **self._device_attributes("network.cabinet", "UPS电池柜"),
            "source_kind": "ups_battery_cabinet_inferred",
            "source_device_id": ups.get("id"),
            "source_label": ups.get("label"),
            "maintenance_clearance_m": POWER_EQUIPMENT_SERVICE_CLEARANCE_M,
            "wall_clearance_m": POWER_EQUIPMENT_WALL_CLEARANCE_M,
            "service_channel_to_ups_m": POWER_EQUIPMENT_SERVICE_CHANNEL_M,
            "position_source": "weak_current_power_room_service_clearance_rule",
            "installation_constraint": "floor_power_equipment_keep_service_clearance_and_no_wall_contact",
        }
        battery = {
            "id": f"dev_inferred_ups_battery_{ups.get('source_entity_id') or ups.get('id')}",
            "type": "network.cabinet",
            "label": "UPS电池柜",
            "source_entity_id": f"{ups.get('source_entity_id') or ups.get('id')}_UPS_BATTERY",
            "original_layer": ups.get("original_layer"),
            "original_block_name": "弱电工艺补点",
            "confidence": 0.82,
            "review_needed": False,
            "geometry": {"type": "Point", "position": battery_pos},
            "orientation": dict(ups.get("orientation") or {"angle_deg": 0.0}),
            "coverage": {},
            "attributes": battery_attrs,
        }
        return [*devices, battery]

    @staticmethod
    def _primary_power_room_core_cabinet(devices: list[dict[str, Any]], ups: dict[str, Any]) -> dict[str, Any] | None:
        ups_pos = ups.get("geometry", {}).get("position")
        candidates = [
            device
            for device in devices
            if device.get("type") == "network.cabinet"
            and device is not ups
            and int((device.get("attributes") or {}).get("rack_units") or 0) == 42
            and device.get("geometry", {}).get("position")
        ]
        if not candidates or not ups_pos:
            return None
        return min(candidates, key=lambda item: RuleEngine._distance(ups_pos, item["geometry"]["position"]))

    @staticmethod
    def _power_equipment_layout_direction(core: dict[str, Any] | None, ups: dict[str, Any]) -> dict[str, float]:
        ups_pos = ups.get("geometry", {}).get("position") or {}
        core_pos = core.get("geometry", {}).get("position") if core else None
        if core_pos:
            dx = float(ups_pos.get("x", 0.0)) - float(core_pos.get("x", 0.0))
            dy = float(ups_pos.get("y", 0.0)) - float(core_pos.get("y", 0.0))
            if abs(dx) < 600.0 and abs(dy) >= 900.0:
                bbox = (ups.get("attributes") or {}).get("target_floor_bbox") or (core.get("attributes") or {}).get("target_floor_bbox") or {}
                if bbox:
                    left_clearance = float(core_pos.get("x", 0.0)) - float(bbox.get("min_x", core_pos.get("x", 0.0)))
                    right_clearance = float(bbox.get("max_x", core_pos.get("x", 0.0))) - float(core_pos.get("x", 0.0))
                    if max(left_clearance, right_clearance) >= POWER_EQUIPMENT_MIN_CENTER_SPACING_MM * 2:
                        return {"x": -1.0 if left_clearance >= right_clearance else 1.0, "y": 0.0}
            length = hypot(dx, dy)
            if length >= 1.0:
                return {"x": dx / length, "y": dy / length}
        return {"x": 1.0, "y": 0.0}

    @staticmethod
    def _power_equipment_needs_lateral_reseat(core: dict[str, Any] | None, ups: dict[str, Any], direction: dict[str, float]) -> bool:
        if not core or abs(float(direction.get("x", 0.0))) < 0.9:
            return False
        core_pos = core.get("geometry", {}).get("position") or {}
        ups_pos = ups.get("geometry", {}).get("position") or {}
        dx = abs(float(ups_pos.get("x", 0.0)) - float(core_pos.get("x", 0.0)))
        dy = abs(float(ups_pos.get("y", 0.0)) - float(core_pos.get("y", 0.0)))
        return dx < 600.0 and dy >= 900.0

    def _apply_power_equipment_clearance(self, devices: list[dict[str, Any]]) -> None:
        ups = self._primary_ups_device(devices)
        if not ups or not ups.get("geometry", {}).get("position"):
            return
        core = self._primary_power_room_core_cabinet(devices, ups)
        direction = self._power_equipment_layout_direction(core, ups)
        ups_reseated = False
        ups_attrs = ups.setdefault("attributes", {})
        ups_attrs.update(
            {
                "maintenance_clearance_m": POWER_EQUIPMENT_SERVICE_CLEARANCE_M,
                "wall_clearance_m": POWER_EQUIPMENT_WALL_CLEARANCE_M,
                "service_channel_to_core_m": POWER_EQUIPMENT_SERVICE_CHANNEL_M,
                "position_source": ups_attrs.get("position_source") or "cad_label_with_service_clearance_check",
                "installation_constraint": "floor_power_equipment_keep_service_clearance_and_no_wall_contact",
            }
        )
        if core and core.get("geometry", {}).get("position"):
            core_attrs = core.setdefault("attributes", {})
            core_attrs.setdefault("maintenance_clearance_m", POWER_EQUIPMENT_SERVICE_CLEARANCE_M)
            core_attrs.setdefault("wall_clearance_m", POWER_EQUIPMENT_WALL_CLEARANCE_M)
            core_attrs.setdefault("service_channel_to_ups_m", POWER_EQUIPMENT_SERVICE_CHANNEL_M)
            core_attrs.setdefault("installation_constraint", "floor_cabinet_keep_service_clearance_and_no_wall_contact")
            core_pos = core["geometry"]["position"]
            ups_pos = ups["geometry"]["position"]
            if (
                self._distance(core_pos, ups_pos) <= POWER_EQUIPMENT_MIN_CENTER_SPACING_MM
                or self._power_equipment_needs_lateral_reseat(core, ups, direction)
            ):
                ups["geometry"]["position"] = {
                    "x": float(core_pos["x"]) + direction["x"] * POWER_EQUIPMENT_MIN_CENTER_SPACING_MM,
                    "y": float(core_pos["y"]) + direction["y"] * POWER_EQUIPMENT_MIN_CENTER_SPACING_MM,
                }
                ups_attrs["position_adjustment_source"] = "weak_current_power_room_same_room_lateral_service_channel"
                ups_reseated = True
        battery = self._primary_ups_battery_device(devices)
        if battery and battery is not ups:
            battery_attrs = battery.setdefault("attributes", {})
            battery_attrs.update(
                {
                    "maintenance_clearance_m": POWER_EQUIPMENT_SERVICE_CLEARANCE_M,
                    "wall_clearance_m": POWER_EQUIPMENT_WALL_CLEARANCE_M,
                    "service_channel_to_ups_m": POWER_EQUIPMENT_SERVICE_CHANNEL_M,
                    "installation_constraint": "floor_power_equipment_keep_service_clearance_and_no_wall_contact",
                }
            )
            battery_pos = battery.get("geometry", {}).get("position")
            ups_pos = ups.get("geometry", {}).get("position")
            if battery_pos and ups_pos and (ups_reseated or self._distance(battery_pos, ups_pos) <= POWER_EQUIPMENT_MIN_CENTER_SPACING_MM):
                battery["geometry"]["position"] = {
                    "x": float(ups_pos["x"]) + direction["x"] * POWER_EQUIPMENT_MIN_CENTER_SPACING_MM,
                    "y": float(ups_pos["y"]) + direction["y"] * POWER_EQUIPMENT_MIN_CENTER_SPACING_MM,
                }
                battery_attrs["position_adjustment_source"] = "weak_current_power_room_same_room_lateral_service_channel"

    def _repair_duplicate_ap_labels(self, devices: list[dict[str, Any]], entities: list[dict[str, Any]]) -> None:
        expected_labels = self._expected_ap_labels(entities)
        if not expected_labels:
            return
        actual_labels = [
            re.sub(r"\s+", "", str(device.get("label", "")).upper())
            for device in devices
            if device.get("type") == "network.ap"
        ]
        missing = [label for label in expected_labels if label not in actual_labels]
        if not missing:
            return
        seen: set[str] = set()
        for device in devices:
            if device.get("type") != "network.ap":
                continue
            label = re.sub(r"\s+", "", str(device.get("label", "")).upper())
            if label not in seen:
                seen.add(label)
                continue
            corrected_label = missing.pop(0)
            attrs = device.setdefault("attributes", {})
            attrs["label_corrected_from"] = device.get("label")
            attrs["label_correction_source"] = "expected_ap_range"
            attrs["source_text_original"] = attrs.get("source_text") or device.get("label")
            attrs["source_text"] = corrected_label
            attrs["source_kind"] = "expected_ap_label_repaired"
            attrs.update(self._device_attributes("network.ap", corrected_label))
            device["label"] = corrected_label
            first_range_end = self._first_expected_ap_range_end(entities, corrected_label)
            if self._system_views_are_title_fallback_only() and first_range_end and self._ap_label_number(corrected_label) > first_range_end:
                device["review_needed"] = True
                device["confidence"] = min(float(device.get("confidence", 1.0) or 1.0), 0.62)
            if not missing:
                return

    def _infer_missing_expected_devices(
        self,
        devices: list[dict[str, Any]],
        entities: list[dict[str, Any]],
        office_model: dict[str, Any],
    ) -> list[dict[str, Any]]:
        text = "\n".join(str(entity.get("text") or "") for entity in entities if entity.get("entity_type") in {"TEXT", "MTEXT"})
        compact = re.sub(r"\s+", "", text.upper())
        existing_labels = {self._short_label_key(str(device.get("label", ""))) for device in devices}
        missing_domes = [
            label
            for label in sorted(self._expected_short_label_set(compact, ("OA", "BG")))
            if self._short_label_key(label) not in existing_labels
        ]
        missing_aps = [
            label
            for label in self._expected_ap_labels(entities)
            if self._short_label_key(label) not in existing_labels
        ]
        missing_cameras = [
            label
            for label in sorted(self._expected_short_label_set(compact, ("CW", "CD", "WH", "WW", "KW")))
            if self._short_label_key(label) not in existing_labels
        ]
        inferred: list[dict[str, Any]] = []
        for index, label in enumerate(missing_domes, start=1):
            position = self._inferred_office_device_position(devices, office_model, index, len(missing_domes))
            if not position:
                continue
            inferred.append(
                {
                    "id": f"dev_expected_{label.replace('-', '_')}",
                    "type": "security.camera.dome",
                    "label": label,
                    "source_entity_id": f"expected:{label}",
                    "original_layer": "图示说明/网络清单",
                    "original_block_name": "清单补点",
                    "confidence": 0.62,
                    "review_needed": True,
                    "geometry": {"type": "Point", "position": position},
                    "orientation": {"angle_deg": 0.0},
                    "coverage": self._coverage_for("security.camera.dome"),
                    "attributes": {
                        "source_kind": "expected_inventory_inferred",
                        "source": "图纸清单存在编号，但主平面未找到同名文字点位；按办公室已有半球/AP分布补入待复核点",
                        **self._device_attributes("security.camera.dome", label),
                    },
                }
            )
        for index, label in enumerate(missing_aps[:5], start=1):
            position = self._inferred_missing_label_position(devices, label, office_model, index, len(missing_aps))
            if not position:
                continue
            inferred.append(
                {
                    "id": f"dev_expected_{self._safe_id(label)}",
                    "type": "network.ap",
                    "label": label,
                    "source_entity_id": f"expected:{label}",
                    "original_layer": "系统示意图/网络清单",
                    "original_block_name": "清单补点",
                    "confidence": 0.62,
                    "review_needed": True,
                    "geometry": {"type": "Point", "position": position},
                    "orientation": {"angle_deg": 0.0},
                    "coverage": self._coverage_for("network.ap"),
                    "attributes": {
                        "source_kind": "expected_inventory_inferred",
                        "source": "图纸清单存在AP编号，但主平面未找到同名文字点位；按同类点位分布补入待复核点",
                        **self._device_attributes("network.ap", label),
                    },
                }
            )
        for index, label in enumerate(missing_cameras[:5], start=1):
            position = self._inferred_missing_label_position(devices, label, office_model, index, len(missing_cameras))
            if not position:
                continue
            device_type = "security.camera.rear" if self._is_rear_camera_label(label) else "security.camera.bullet"
            inferred.append(
                {
                    "id": f"dev_expected_{self._safe_id(label)}",
                    "type": device_type,
                    "label": label,
                    "source_entity_id": f"expected:{label}",
                    "original_layer": "系统示意图/监控清单",
                    "original_block_name": "清单补点",
                    "confidence": 0.62,
                    "review_needed": True,
                    "geometry": {"type": "Point", "position": position},
                    "orientation": {"angle_deg": 0.0},
                    "coverage": self._coverage_for(device_type),
                    "attributes": {
                        "source_kind": "expected_inventory_inferred",
                        "source": "图纸清单存在摄像头编号，但主平面未找到同名文字点位；按同编号段点位插值补入待复核点",
                        **self._device_attributes(device_type, label),
                    },
                }
            )
        return inferred

    def _infer_missing_expected_ap_devices(
        self,
        devices: list[dict[str, Any]],
        entities: list[dict[str, Any]],
        office_model: dict[str, Any],
    ) -> list[dict[str, Any]]:
        if not self._is_no_main_plan_mode() or not self._system_views_are_title_fallback_only():
            return []
        existing_labels = {self._short_label_key(str(device.get("label", ""))) for device in devices}
        missing_aps = [
            label
            for label in self._expected_ap_labels(entities)
            if self._short_label_key(label) not in existing_labels
        ]
        site_ap_max = self._expected_site_ap_max_number(entities)
        if site_ap_max:
            missing_aps = [
                label
                for label in missing_aps
                if "-CD-AP-" not in label.upper() or self._ap_label_number(label) <= site_ap_max
            ]
        inferred: list[dict[str, Any]] = []
        for index, label in enumerate(missing_aps[:5], start=1):
            position = self._inferred_missing_label_position(devices, label, office_model, index, len(missing_aps))
            if not position:
                continue
            inferred.append(
                {
                    "id": f"dev_expected_{self._safe_id(label)}",
                    "type": "network.ap",
                    "label": label,
                    "source_entity_id": f"expected:{label}",
                    "original_layer": "系统示意图/网络清单",
                    "original_block_name": "清单补点",
                    "confidence": 0.62,
                    "review_needed": True,
                    "geometry": {"type": "Point", "position": position},
                    "orientation": {"angle_deg": 0.0},
                    "coverage": self._coverage_for("network.ap"),
                    "attributes": {
                        "source_kind": "expected_inventory_inferred",
                        "source": "无主平面且系统框仅由标题兜底时，清单存在AP编号但点位未落到可靠主图；按同编号段点位插值补入待复核点",
                        **self._device_attributes("network.ap", label),
                    },
                }
            )
        return inferred

    @staticmethod
    def _ap_label_number(label: str) -> int:
        match = re.search(r"-AP-0*(\d{1,3})$", str(label or "").upper())
        return int(match.group(1)) if match else 0

    @staticmethod
    def _expected_site_ap_max_number(entities: list[dict[str, Any]]) -> int | None:
        text = "\n".join(str(entity.get("text") or "") for entity in entities if entity.get("entity_type") in {"TEXT", "MTEXT"})
        compact = re.sub(r"\s+", "", text.upper())
        patterns = (
            r"AP[：:]?\d{1,3}台[（(]场地(\d{1,3})台",
            r"场地AP[（(]?编号[：:]?BFR-[A-Z0-9-]+-AP-0*1[~～]0*(\d{1,3})",
        )
        values: list[int] = []
        for pattern in patterns:
            values.extend(int(match.group(1)) for match in re.finditer(pattern, compact))
        return max(values) if values else None

    def _expected_ap_quantity_note_count(self, entities: list[dict[str, Any]]) -> int:
        text = "\n".join(str(entity.get("text") or "") for entity in entities if entity.get("entity_type") in {"TEXT", "MTEXT"})
        compact = re.sub(r"\s+", "", text.upper())
        return self._expected_count_from_patterns(
            compact,
            [
                r"(?:无线)?AP(?:共计)?[:：]?(\d{1,3})(?:台|个)",
                r"(\d{1,3})个(?:场地|办公)?无线AP",
            ],
        )

    @staticmethod
    def _first_expected_ap_range_end(entities: list[dict[str, Any]], label: str) -> int | None:
        label_text = str(label or "").upper()
        prefix_match = re.match(r"(.+-AP-)0*\d{1,3}$", label_text)
        if not prefix_match:
            return None
        prefix = prefix_match.group(1)
        for entity in entities:
            if entity.get("entity_type") not in {"TEXT", "MTEXT"}:
                continue
            compact = re.sub(r"\s+", "", str(entity.get("text") or "").upper())
            for match in AP_LABEL_RANGE_PATTERN.finditer(compact):
                if match.group(1).upper() != prefix or not match.group(3):
                    continue
                return int(match.group(3))
        return None

    @staticmethod
    def _safe_id(label: str) -> str:
        return re.sub(r"[^A-Za-z0-9]+", "_", label).strip("_").lower()

    def _inferred_missing_label_position(
        self,
        devices: list[dict[str, Any]],
        label: str,
        office_model: dict[str, Any],
        index: int,
        total_missing: int,
    ) -> dict[str, float] | None:
        match = re.fullmatch(r"(.+-)(\d{1,3})", label)
        if match:
            root = match.group(1)
            number = int(match.group(2))
            same_series: list[tuple[int, dict[str, float]]] = []
            for device in devices:
                candidate_label = re.sub(r"\s+", "", str(device.get("label", "")).upper())
                candidate_match = re.fullmatch(r"(.+-)(\d{1,3})", candidate_label)
                position = device.get("geometry", {}).get("position")
                if candidate_match and candidate_match.group(1) == root and position:
                    same_series.append((int(candidate_match.group(2)), position))
            before = max((item for item in same_series if item[0] < number), default=None, key=lambda item: item[0])
            after = min((item for item in same_series if item[0] > number), default=None, key=lambda item: item[0])
            if before and after and after[0] != before[0]:
                ratio = (number - before[0]) / (after[0] - before[0])
                return {
                    "x": before[1]["x"] + (after[1]["x"] - before[1]["x"]) * ratio,
                    "y": before[1]["y"] + (after[1]["y"] - before[1]["y"]) * ratio,
                }
            anchor = before or after
            if anchor:
                direction = 1 if before else -1
                return {"x": anchor[1]["x"], "y": anchor[1]["y"] + direction * 1_500.0 * index}
        return self._inferred_office_device_position(devices, office_model, index, total_missing)

    def _inferred_office_device_position(
        self,
        devices: list[dict[str, Any]],
        office_model: dict[str, Any],
        index: int,
        total_missing: int,
    ) -> dict[str, float] | None:
        office_bbox = self._office_union_bbox(office_model)
        reference_positions = [
            device["geometry"]["position"]
            for device in devices
            if device.get("type") in {"security.camera.dome", "network.ap"}
            and device.get("geometry", {}).get("position")
            and (not office_bbox or self._point_in_bbox(device["geometry"]["position"], office_bbox, 12_000.0))
        ]
        dome_positions = [
            device["geometry"]["position"]
            for device in devices
            if device.get("type") == "security.camera.dome" and device.get("geometry", {}).get("position")
        ]
        if office_bbox:
            x = (office_bbox["min_x"] + office_bbox["max_x"]) / 2.0
            y_slots = total_missing + len(dome_positions) + 1
            y = office_bbox["max_y"] - (office_bbox["max_y"] - office_bbox["min_y"]) * (len(dome_positions) + index) / max(y_slots, 1)
            if reference_positions:
                x = sum(point["x"] for point in reference_positions) / len(reference_positions)
            return {
                "x": min(max(x, office_bbox["min_x"] + 1500.0), office_bbox["max_x"] - 1500.0),
                "y": min(max(y, office_bbox["min_y"] + 1500.0), office_bbox["max_y"] - 1500.0),
            }
        if dome_positions:
            sorted_y = sorted(point["y"] for point in dome_positions)
            gaps = [abs(right - left) for left, right in zip(sorted_y, sorted_y[1:]) if abs(right - left) > 1000.0]
            gap = sorted(gaps)[len(gaps) // 2] if gaps else 12_000.0
            return {
                "x": sum(point["x"] for point in dome_positions) / len(dome_positions),
                "y": min(sorted_y) - gap * index,
            }
        return None

    @staticmethod
    def _office_union_bbox(office_model: dict[str, Any]) -> dict[str, float] | None:
        bboxes = [
            floor.get("target_bbox") or floor.get("source_bbox")
            for floor in office_model.get("floors", [])
            if floor.get("target_bbox") or floor.get("source_bbox")
        ]
        if not bboxes:
            return None
        return {
            "min_x": min(bbox["min_x"] for bbox in bboxes),
            "min_y": min(bbox["min_y"] for bbox in bboxes),
            "max_x": max(bbox["max_x"] for bbox in bboxes),
            "max_y": max(bbox["max_y"] for bbox in bboxes),
        }

    @staticmethod
    def _expected_short_labels(text: str, prefixes: tuple[str, ...]) -> list[str]:
        labels: list[str] = []
        seen: set[str] = set()
        prefix_pattern = "|".join(re.escape(prefix) for prefix in prefixes)
        for match in re.finditer(rf"({prefix_pattern})-?(\d{{1,3}})~(\d{{1,3}})", text):
            prefix = match.group(1)
            start = int(match.group(2))
            end = int(match.group(3))
            width = max(2, len(match.group(2)), len(match.group(3)))
            if end < start or end - start > 200:
                continue
            for number in range(start, end + 1):
                label = f"{prefix}-{number:0{width}d}"
                if label in seen:
                    continue
                seen.add(label)
                labels.append(label)
        return labels

    @staticmethod
    def _expected_short_label_set(text: str, prefixes: tuple[str, ...]) -> set[str]:
        labels = set(RuleEngine._expected_short_labels(text, prefixes))
        prefix_pattern = "|".join(re.escape(prefix) for prefix in prefixes)
        for match in re.finditer(rf"({prefix_pattern})-?(\d{{1,3}})(?!\d)", text):
                labels.add(f"{match.group(1)}-{int(match.group(2)):02d}")
        return labels

    @staticmethod
    def _short_label_key(label: str) -> str:
        compact = re.sub(r"\s+", "", str(label or "").upper())
        match = re.fullmatch(r"(CW|KW|GX|CD|WH|WW|YY|OA|BG)-?0*(\d{1,3})", compact)
        if match:
            return f"{match.group(1)}-{int(match.group(2)):02d}"
        return compact

    @staticmethod
    def _expected_ap_labels(entities: list[dict[str, Any]]) -> list[str]:
        labels: list[str] = []
        seen: set[str] = set()
        for entity in entities:
            if entity.get("entity_type") not in {"TEXT", "MTEXT"}:
                continue
            compact = re.sub(r"\s+", "", str(entity.get("text") or "").upper())
            for match in AP_LABEL_RANGE_PATTERN.finditer(compact):
                prefix = match.group(1)
                start = int(match.group(2))
                end = int(match.group(3) or match.group(2))
                width = max(len(match.group(2)), len(match.group(3) or match.group(2)))
                if end < start or end - start > 100:
                    continue
                for number in range(start, end + 1):
                    label = f"{prefix}{number:0{width}d}"
                    if label in seen:
                        continue
                    seen.add(label)
                    labels.append(label)
        return labels

    def _devices_from_text_label(self, entity: dict[str, Any]) -> list[dict[str, Any]]:
        if entity.get("entity_type") not in {"TEXT", "MTEXT"}:
            return []
        raw_text = str(entity.get("text", "")).strip()
        text = re.sub(r"\s+", "", raw_text.upper())
        position = entity.get("geometry", {}).get("position")
        range_match = AP_LABEL_RANGE_PATTERN.fullmatch(text)
        if range_match and range_match.group(3) and position and len(text) <= 42:
            prefix = range_match.group(1)
            start = int(range_match.group(2))
            end = int(range_match.group(3))
            width = max(len(range_match.group(2)), len(range_match.group(3)))
            if end < start or end - start > 10:
                return []
            count = end - start + 1
            devices: list[dict[str, Any]] = []
            for index, number in enumerate(range(start, end + 1)):
                label = f"{prefix}{number:0{width}d}"
                item_position = dict(position)
                item_position["x"] = float(item_position.get("x", 0.0)) + (index - (count - 1) / 2.0) * 2200.0
                attrs = self._device_attributes("network.ap", label)
                attrs.update(
                    {
                        "source_kind": "text_label_range",
                        "source_label_entity_id": entity["source_entity_id"],
                        "source_block_id": None,
                        "source_text": raw_text,
                        "expanded_from_label_range": raw_text,
                        "expanded_label_index": index + 1,
                        "expanded_label_count": count,
                    }
                )
                devices.append(
                    {
                        "id": f"dev_label_{entity['source_entity_id']}_{number:0{width}d}",
                        "type": "network.ap",
                        "label": label,
                        "source_entity_id": f"{entity['source_entity_id']}:{label}",
                        "original_layer": entity.get("layer"),
                        "original_block_name": "文字编号",
                        "confidence": 0.96,
                        "review_needed": False,
                        "geometry": {"type": "Point", "position": item_position},
                        "orientation": {"angle_deg": 0.0},
                        "coverage": self._coverage_for("network.ap"),
                        "attributes": attrs,
                    }
                )
            return devices

        device = self._device_from_text_label(entity)
        return [device] if device else []

    def _renumber_generated_labels(self, devices: list[dict[str, Any]]) -> None:
        counts: defaultdict[str, int] = defaultdict(int)
        for device in devices:
            prefix = self._label_prefix(str(device.get("type", "")))
            label = str(device.get("label", ""))
            if not label.startswith(f"{prefix}-"):
                continue
            counts[prefix] += 1
            device["label"] = f"{prefix}-{counts[prefix]:03d}"

    @staticmethod
    def _is_parameter_block(block_name: str) -> bool:
        upper = block_name.upper()
        return any(keyword.upper() in upper for keyword in PARAMETER_BLOCK_KEYWORDS)

    @staticmethod
    def _is_device_type(semantic_type: str) -> bool:
        return semantic_type.startswith(("security.camera", "network.", "power.", "lighting."))

    @staticmethod
    def _camera_label_number(label: str, prefix: str) -> int | None:
        match = re.fullmatch(rf"{re.escape(prefix)}-?(\d{{1,3}})", re.sub(r"\s+", "", str(label or "").upper()))
        if not match:
            return None
        return int(match.group(1))

    @classmethod
    def _is_rear_camera_label(cls, label: str) -> bool:
        compact = re.sub(r"\s+", "", str(label or "").upper())
        if cls._camera_label_number(compact, "CW") is not None:
            return True
        if cls._camera_label_number(compact, "GX") is not None:
            return True
        kw_number = cls._camera_label_number(compact, "KW")
        return kw_number is not None and KW_REAR_CAMERA_MIN_NUMBER <= kw_number <= KW_REAR_CAMERA_MAX_NUMBER

    def _device_from_text_label(self, entity: dict[str, Any]) -> dict[str, Any] | None:
        if entity.get("entity_type") not in {"TEXT", "MTEXT"}:
            return None
        raw_text = str(entity.get("text", "")).strip()
        text = re.sub(r"\s+", "", raw_text.upper())
        if not text or len(text) > 42:
            return None

        semantic_type: str | None = None
        label = raw_text.strip()
        confidence = 0.98
        orientation = 0.0

        cw_match = re.fullmatch(r"CW-(\d{1,3})", text)
        gx_match = re.fullmatch(r"GX-?(\d{1,3})", text)
        kw_match = re.fullmatch(r"KW-?(\d{1,3})", text)
        yy_match = re.fullmatch(r"YY-?(\d{1,3})", text)
        if cw_match:
            semantic_type = "security.camera.rear"
            orientation = 270.0 if int(cw_match.group(1)) <= 40 else 90.0
            label = f"CW-{int(cw_match.group(1)):02d}"

        elif gx_match:
            semantic_type = "security.camera.rear"
            label = f"GX-{int(gx_match.group(1)):02d}"
            confidence = 0.96

        elif kw_match:
            kw_number = int(kw_match.group(1))
            semantic_type = (
                "security.camera.rear"
                if KW_REAR_CAMERA_MIN_NUMBER <= kw_number <= KW_REAR_CAMERA_MAX_NUMBER
                else "security.camera.bullet"
            )
            label = f"KW-{kw_number:02d}"
            confidence = 0.95 if semantic_type == "security.camera.rear" else 0.92

        elif yy_match:
            semantic_type = "security.camera.fisheye"
            label = f"YY-{int(yy_match.group(1)):02d}"

        elif re.fullmatch(r"(WH|WW|CD)-\d{1,3}", text):
            semantic_type = "security.camera.bullet"
            confidence = 0.92

        elif re.fullmatch(r"OA-\d{1,3}", text):
            semantic_type = "security.camera.dome"
            confidence = 0.95

        elif re.fullmatch(r"BG-\d{1,3}", text):
            semantic_type = "security.camera.dome"
            confidence = 0.95

        elif AP_LABEL_PATTERN.fullmatch(text):
            semantic_type = "network.ap"

        elif re.fullmatch(r"(?:\d{1,2}KVA)?UPS(?:电源|控制主机|主机|电池|电池柜|电池组合主机)?|(?:UPS)?电池柜", text):
            semantic_type = "network.cabinet"
            confidence = 0.90
            if "电池" in text and "柜" not in label:
                label = f"{label}柜"

        elif re.fullmatch(r"(\d{1,2}U)?机柜\d{0,2}|(监控|网络|弱电).{0,4}机柜\d{0,2}", text) and len(text) <= 16:
            semantic_type = "network.cabinet"
            confidence = 0.88

        if not semantic_type:
            return None

        position = entity.get("geometry", {}).get("position")
        if not position:
            return None
        if semantic_type == "network.cabinet" and self._plan_copy_index(position) is None:
            return None
        return {
            "id": f"dev_label_{entity['source_entity_id']}",
            "type": semantic_type,
            "label": label,
            "source_entity_id": entity["source_entity_id"],
            "original_layer": entity.get("layer"),
            "original_block_name": "文字编号",
            "confidence": confidence,
            "review_needed": confidence < 0.75,
            "geometry": {"type": "Point", "position": position},
            "orientation": {"angle_deg": orientation},
            "coverage": self._coverage_for(semantic_type),
            "attributes": {
                "source_kind": "text_label",
                "source_label_entity_id": entity["source_entity_id"],
                "source_block_id": None,
                "source_text": raw_text,
                **self._device_attributes(semantic_type, raw_text),
            },
        }

    @staticmethod
    def _device_attributes(semantic_type: str, raw_text: str) -> dict[str, Any]:
        text = re.sub(r"\s+", "", raw_text.upper())
        if semantic_type == "network.cabinet":
            if "UPS" in text or "电池柜" in text:
                is_battery = "电池" in raw_text
                return {
                    "rack_units": 22 if is_battery else 12,
                    "mount": "floor",
                    "top_edge_height_m": None,
                    "cabinet_role": "ups_battery" if is_battery else "ups_power",
                    "equipment_class": "UPS电池柜" if is_battery else "UPS电源",
                    "power_equipment": True,
                }
            rack_units = RuleEngine._rack_units_from_text(text)
            if not rack_units and ("监控挂墙" in raw_text or "网络挂墙" in raw_text):
                rack_units = 12
            return {
                "rack_units": rack_units or 12,
                "mount": "wall" if "挂墙" in raw_text else "floor",
                "top_edge_height_m": 3.5 if "挂墙" in raw_text else None,
            }
        if semantic_type == "network.ap":
            return {
                "zone": "office" if "-BG-" in text else "warehouse",
                "mount": "ceiling" if "-BG-" in text else "suspended",
                "install_height_m": 3.2 if "-BG-" in text else 6.0,
                "coverage_render_style": "projected_volume_cone",
                "coverage_animation": "wifi_ripple",
                "coverage_visual_source": "cad_radius_or_layout_default",
            }
        if semantic_type == "security.camera.fisheye":
            return {
                "mount": "suspended",
                "install_height_m": 5.0,
                "coverage_render_style": "projected_volume_cone",
                "coverage_visual_source": "cad_radius_or_default",
            }
        if semantic_type == "security.camera.dome":
            return {
                "zone": "office",
                "mount": "ceiling",
                "lens_mm": 2.8,
                "install_height_m": 3.0,
                "coverage_render_style": "projected_volume_cone",
                "coverage_visual_source": "cad_radius_or_default",
            }
        if semantic_type == "security.camera.rear":
            return {"mount": "suspended", "install_height_m": 2.8}
        if semantic_type == "security.camera.bullet":
            if text.startswith("BG-"):
                return {"zone": "office", "mount": "wall", "lens_mm": 6.0, "install_height_m": 3.5}
            if text.startswith("WW-"):
                return {"mount": "wall", "install_height_m": 4.5}
            return {"mount": "wall", "install_height_m": 3.5}
        return {}

    @staticmethod
    def _rack_units_from_text(text: str) -> int | None:
        units_match = re.search(r"(\d{1,2})U", re.sub(r"\s+", "", str(text).upper()))
        return int(units_match.group(1)) if units_match else None

    @staticmethod
    def _annotate_cabinets(devices: list[dict[str, Any]]) -> None:
        for device in devices:
            if device.get("type") != "network.cabinet":
                continue
            attrs = device.setdefault("attributes", {})
            if attrs.get("rack_units"):
                continue
            source_text = str(attrs.get("source_text") or device.get("label") or "")
            attrs.update(RuleEngine._device_attributes("network.cabinet", source_text))

    @staticmethod
    def _is_power_cabinet(device: dict[str, Any]) -> bool:
        if device.get("type") != "network.cabinet":
            return False
        attrs = device.get("attributes") or {}
        label = re.sub(r"\s+", "", str(device.get("label") or "").upper())
        return str(attrs.get("cabinet_role") or "") in {"ups_power", "ups_battery"} or "UPS" in label

    @staticmethod
    def _is_ups_power(device: dict[str, Any]) -> bool:
        if device.get("type") != "network.cabinet":
            return False
        attrs = device.get("attributes") or {}
        label = re.sub(r"\s+", "", str(device.get("label") or "").upper())
        return str(attrs.get("cabinet_role") or "") == "ups_power" or ("UPS" in label and "电池" not in label)

    @staticmethod
    def _is_ups_battery(device: dict[str, Any]) -> bool:
        if device.get("type") != "network.cabinet":
            return False
        attrs = device.get("attributes") or {}
        label = re.sub(r"\s+", "", str(device.get("label") or "").upper())
        return str(attrs.get("cabinet_role") or "") == "ups_battery" or ("UPS" in label and "电池" in label)

    @staticmethod
    def _primary_ups_device(devices: list[dict[str, Any]]) -> dict[str, Any] | None:
        candidates = [device for device in devices if RuleEngine._is_ups_power(device) and device.get("geometry", {}).get("position")]
        if not candidates:
            return None
        return min(candidates, key=lambda item: str(item.get("label") or ""))

    @staticmethod
    def _primary_ups_battery_device(devices: list[dict[str, Any]]) -> dict[str, Any] | None:
        candidates = [device for device in devices if RuleEngine._is_ups_battery(device) and device.get("geometry", {}).get("position")]
        if not candidates:
            return None
        return min(candidates, key=lambda item: str(item.get("label") or ""))

    def _infer_cabinet_links(self, devices: list[dict[str, Any]]) -> list[dict[str, Any]]:
        cabinets = [
            device
            for device in devices
            if device.get("type") == "network.cabinet"
            and device.get("geometry", {}).get("position")
            and not self._is_power_cabinet(device)
        ]
        if len(cabinets) < 2:
            return []
        if not self._system_view_alignment_allows_cable_inference("cabinet_link"):
            self._record_suppressed_inference(
                "cabinet_link_fallback",
                max(len(cabinets) - 1, 0),
                "无可靠主平面且机柜链路示意图未能按图框对齐时不自动连成真实弱电线路",
            )
            return []
        core = next((cabinet for cabinet in cabinets if cabinet.get("attributes", {}).get("rack_units") == 42), None)
        if not core:
            core = min(cabinets, key=lambda item: item["geometry"]["position"]["y"])
        core_pos = core["geometry"]["position"]
        convergence_point = self._core_convergence_point(core)
        links: list[dict[str, Any]] = []
        for cabinet in cabinets:
            if cabinet is core:
                continue
            pos = cabinet["geometry"]["position"]
            media = self._cabinet_link_media(cabinet)
            output_type = self._cabinet_link_output_type(media)
            layer_role = self._cabinet_link_layer_role()
            source_entry_height = self._cabinet_entry_height(cabinet)
            target_entry_height = self._cabinet_entry_height(core)
            route_height = max(source_entry_height, target_entry_height, 2.8)
            points = self._converged_route_to_core(pos, core_pos, convergence_point)
            links.append(
                {
                    "id": f"cable_cabinet_{len(links) + 1:03d}",
                    "type": output_type,
                    "source_entity_id": f"{cabinet['source_entity_id']}->{core['source_entity_id']}",
                    "original_layer": "机柜链路示意图",
                    "confidence": 0.82,
                    "review_needed": False,
                    "geometry": {"type": "LineString", "points": points},
                    "length_mm": line_length(points),
                    "attributes": {
                        "source_kind": "cabinet_link_inferred",
                        "layer_role": layer_role,
                        "media": "多模光纤" if media == "fiber" else "六类线",
                        "media_role": "fiber" if media == "fiber" else "network",
                        "source_device_id": cabinet["id"],
                        "source_label": cabinet.get("label"),
                        "target_device_id": core["id"],
                        "target_label": core.get("label"),
                        "height_m": route_height,
                        "source_entry_height_m": source_entry_height,
                        "target_entry_height_m": target_entry_height,
                        "terminates_inside_cabinet": True,
                        "route_policy": "converge_to_42u_cabinet_zone",
                        "convergence_point": convergence_point,
                    },
                }
        )
        return links

    def _cabinet_link_config(self) -> dict[str, Any]:
        config = self.rules.get("cabinet_link_inference")
        return config if isinstance(config, dict) else {}

    def _cabinet_link_output_type(self, media: str) -> str:
        config = self._cabinet_link_config()
        cable_type = config.get("cable_type")
        if cable_type:
            return str(cable_type)
        return "cable.fiber" if media == "fiber" else "cable.network"

    def _cabinet_link_layer_role(self) -> str:
        config = self._cabinet_link_config()
        layer_role = config.get("layer_role")
        return str(layer_role) if layer_role else "weak_current"

    @staticmethod
    def _cabinet_entry_height(cabinet: dict[str, Any]) -> float:
        attrs = cabinet.get("attributes", {})
        rack_units = int(attrs.get("rack_units") or 12)
        if attrs.get("mount") == "wall" and attrs.get("top_edge_height_m"):
            return max(float(attrs["top_edge_height_m"]) - 0.28, 0.6)
        height_by_units = {
            42: 2.05,
            22: 1.08,
            12: 0.64,
            9: 0.50,
        }
        return max(height_by_units.get(rack_units, 0.7) - 0.18, 0.35)

    @staticmethod
    def _cabinet_link_media(cabinet: dict[str, Any]) -> str:
        text = str(cabinet.get("label") or "") + str(cabinet.get("attributes", {}).get("source_text") or "")
        if "监控挂墙" in text and not text.endswith("01"):
            return "fiber"
        if "网络挂墙" in text and ("02" in text or "03" in text):
            return "fiber"
        return "cat6"

    def _infer_cabinet_power_cables(self, devices: list[dict[str, Any]]) -> list[dict[str, Any]]:
        cabinets = [
            device
            for device in devices
            if device.get("type") == "network.cabinet"
            and device.get("geometry", {}).get("position")
            and not self._is_power_cabinet(device)
        ]
        ups = self._primary_ups_device(devices)
        if not cabinets or not ups:
            return []
        if not self._system_view_alignment_allows_cable_inference("cabinet_spotlight_power"):
            self._record_suppressed_inference(
                "cabinet_power_fallback",
                len(cabinets),
                "无可靠主平面且机柜&射灯电缆示意图未能按图框对齐时不生成机柜电缆路线",
            )
            return []
        ups_pos = ups["geometry"]["position"]
        convergence_point = self._core_convergence_point(ups)
        links: list[dict[str, Any]] = []
        for cabinet in cabinets:
            if cabinet is ups:
                continue
            pos = cabinet["geometry"]["position"]
            source_entry_height = self._cabinet_entry_height(cabinet)
            target_entry_height = self._cabinet_entry_height(ups)
            route_height = max(source_entry_height, target_entry_height, 2.8)
            points = self._converged_route_to_core(pos, ups_pos, convergence_point)
            links.append(
                {
                    "id": f"cable_cabinet_power_{len(links) + 1:03d}",
                    "type": "cable.cabinet_power",
                    "source_entity_id": f"{cabinet['source_entity_id']}=>{ups['source_entity_id']}",
                    "original_layer": "机柜&射灯电缆示意图",
                    "confidence": 0.80,
                    "review_needed": False,
                    "geometry": {"type": "LineString", "points": points},
                    "length_mm": line_length(points),
                    "attributes": {
                        "source_kind": "cabinet_power_inferred",
                        "layer_role": "cabinet_cable",
                        "media": "机柜供电/综合电缆",
                        "source_device_id": cabinet["id"],
                        "source_label": cabinet.get("label"),
                        "target_device_id": ups["id"],
                        "target_label": ups.get("label"),
                        "height_m": route_height,
                        "source_entry_height_m": source_entry_height,
                        "target_entry_height_m": target_entry_height,
                        "terminates_inside_cabinet": True,
                        "route_policy": "converge_to_ups_power_zone",
                        "convergence_point": convergence_point,
                    },
                }
            )
        battery = self._primary_ups_battery_device(devices)
        if battery and battery is not ups:
            battery_pos = battery["geometry"]["position"]
            points = self._orthogonal_route(ups_pos, battery_pos)
            links.append(
                {
                    "id": f"cable_cabinet_power_{len(links) + 1:03d}",
                    "type": "cable.cabinet_power",
                    "source_entity_id": f"{ups['source_entity_id']}=>{battery['source_entity_id']}",
                    "original_layer": "UPS电池连接",
                    "confidence": 0.86,
                    "review_needed": False,
                    "geometry": {"type": "LineString", "points": points},
                    "length_mm": line_length(points),
                    "attributes": {
                        "source_kind": "ups_battery_link_inferred",
                        "layer_role": "cabinet_cable",
                        "media": "UPS电池连接线",
                        "source_device_id": ups["id"],
                        "source_label": ups.get("label"),
                        "target_device_id": battery["id"],
                        "target_label": battery.get("label"),
                        "height_m": max(self._cabinet_entry_height(ups), self._cabinet_entry_height(battery), 0.8),
                        "source_entry_height_m": self._cabinet_entry_height(ups),
                        "target_entry_height_m": self._cabinet_entry_height(battery),
                        "terminates_inside_cabinet": True,
                        "route_policy": "ups_to_battery_cabinet",
                    },
                }
            )
        return links

    def _infer_spotlight_cables(self, fixtures: list[dict[str, Any]], devices: list[dict[str, Any]]) -> list[dict[str, Any]]:
        fallback_cabinets = [
            device
            for device in devices
            if device.get("type") == "network.cabinet"
            and device.get("geometry", {}).get("position")
            and not self._is_power_cabinet(device)
        ]
        if not fixtures:
            return []
        preferred_target = self._primary_ups_battery_device(devices) or self._primary_ups_device(devices)
        if not preferred_target and not fallback_cabinets:
            return []
        if len(fixtures) >= 24 and preferred_target and not self._system_views_are_title_fallback_only():
            return self._infer_grouped_spotlight_cables(fixtures, preferred_target)
        links: list[dict[str, Any]] = []
        for fixture in fixtures:
            pos = fixture.get("geometry", {}).get("position")
            if not pos:
                continue
            target = preferred_target or min(fallback_cabinets, key=lambda item: self._distance(pos, item["geometry"]["position"]))
            target_pos = target["geometry"]["position"]
            install_height = float(fixture.get("attributes", {}).get("install_height_m") or 3.0)
            target_height = max(self._cabinet_entry_height(target), 1.2)
            route_height = max(install_height, target_height)
            route_policy = "spotlight_power_to_nearest_cabinet_fallback"
            if self._is_ups_battery(target):
                route_policy = "direct_to_ups_battery_cabinet"
                points = self._orthogonal_route(pos, target_pos)
            elif self._is_ups_power(target):
                route_policy = "direct_to_ups_power_zone"
                points = self._orthogonal_route(pos, target_pos)
            else:
                points = self._orthogonal_route(pos, target_pos)
            links.append(
                {
                    "id": f"cable_spotlight_{len(links) + 1:03d}",
                    "type": "cable.spotlight_power",
                    "source_entity_id": f"{fixture['source_entity_id']}=>{target['source_entity_id']}",
                    "original_layer": "射灯电缆示意图",
                    "confidence": 0.74,
                    "review_needed": False,
                    "geometry": {"type": "LineString", "points": points},
                    "length_mm": line_length(points),
                    "attributes": {
                        "source_kind": "spotlight_power_inferred",
                        "layer_role": "spotlight_cable",
                        "media": "射灯电源线",
                        "source_fixture_id": fixture["id"],
                        "source_label": fixture.get("label"),
                        "target_device_id": target["id"],
                        "target_label": target.get("label"),
                        "height_m": route_height,
                        "source_entry_height_m": install_height,
                        "target_entry_height_m": target_height,
                        "terminates_inside_cabinet": True,
                        "route_policy": route_policy,
                    },
                }
            )
        return links

    def _infer_grouped_spotlight_cables(self, fixtures: list[dict[str, Any]], target: dict[str, Any]) -> list[dict[str, Any]]:
        target_pos = target.get("geometry", {}).get("position")
        if not target_pos:
            return []
        grouped: defaultdict[int, list[dict[str, Any]]] = defaultdict(list)
        for fixture in fixtures:
            pos = fixture.get("geometry", {}).get("position")
            if not pos:
                continue
            angle = int(round(float(fixture.get("orientation", {}).get("angle_deg", 0.0) or 0.0) / 90.0) * 90) % 360
            grouped[angle].append(fixture)

        links: list[dict[str, Any]] = []
        target_height = max(self._cabinet_entry_height(target), 1.2)
        target_is_battery = self._is_ups_battery(target)
        route_policy = "grouped_spotlight_power_to_ups_battery" if target_is_battery else "grouped_spotlight_power_to_ups_power"
        for angle, group in sorted(grouped.items()):
            if len(group) < 4:
                links.extend(self._infer_spotlight_cables(group, [target]))
                continue
            positions = [fixture["geometry"]["position"] for fixture in group]
            install_height = max(float((fixture.get("attributes") or {}).get("install_height_m") or 3.0) for fixture in group)
            route_height = max(install_height, target_height)
            source_labels = [str(fixture.get("label") or fixture.get("id") or "") for fixture in group]
            source_ids = [str(fixture.get("source_entity_id") or fixture.get("id") or "") for fixture in group]
            if angle in {0, 180}:
                y = sum(float(point["y"]) for point in positions) / len(positions)
                start = {"x": min(float(point["x"]) for point in positions), "y": y}
                end = {"x": max(float(point["x"]) for point in positions), "y": y}
            else:
                x = sum(float(point["x"]) for point in positions) / len(positions)
                start = {"x": x, "y": min(float(point["y"]) for point in positions)}
                end = {"x": x, "y": max(float(point["y"]) for point in positions)}

            trunk_points = [start, end]
            links.append(
                {
                    "id": f"cable_spotlight_trunk_{len(links) + 1:03d}",
                    "type": "cable.spotlight_power",
                    "source_entity_id": "+".join(source_ids[:6]),
                    "original_layer": "射灯电缆示意图",
                    "confidence": 0.78,
                    "review_needed": False,
                    "geometry": {"type": "LineString", "points": trunk_points},
                    "length_mm": line_length(trunk_points),
                    "attributes": {
                        "source_kind": "spotlight_power_grouped_inferred",
                        "layer_role": "spotlight_cable",
                        "media": "射灯电源线",
                        "source_label": self._label_range_summary(source_labels),
                        "target_device_id": target["id"],
                        "target_label": target.get("label"),
                        "height_m": route_height,
                        "source_entry_height_m": install_height,
                        "target_entry_height_m": target_height,
                        "terminates_inside_cabinet": False,
                        "route_policy": f"{route_policy}_trunk",
                        "grouped_fixture_count": len(group),
                    },
                }
            )

            feeder_start = start if self._distance(start, target_pos) <= self._distance(end, target_pos) else end
            feeder_points = self._orthogonal_route(feeder_start, target_pos)
            links.append(
                {
                    "id": f"cable_spotlight_feeder_{len(links) + 1:03d}",
                    "type": "cable.spotlight_power",
                    "source_entity_id": f"{'+'.join(source_ids[:3])}=>{target['source_entity_id']}",
                    "original_layer": "射灯电缆示意图",
                    "confidence": 0.76,
                    "review_needed": False,
                    "geometry": {"type": "LineString", "points": feeder_points},
                    "length_mm": line_length(feeder_points),
                    "attributes": {
                        "source_kind": "spotlight_power_grouped_inferred",
                        "layer_role": "spotlight_cable",
                        "media": "射灯电源线",
                        "source_label": self._label_range_summary(source_labels),
                        "target_device_id": target["id"],
                        "target_label": target.get("label"),
                        "height_m": route_height,
                        "source_entry_height_m": install_height,
                        "target_entry_height_m": target_height,
                        "terminates_inside_cabinet": True,
                        "route_policy": f"{route_policy}_feeder",
                        "grouped_fixture_count": len(group),
                    },
                }
            )
        return links

    @staticmethod
    def _label_range_summary(labels: list[str]) -> str:
        clean = [label for label in labels if label]
        if not clean:
            return ""
        if len(clean) == 1:
            return clean[0]
        return f"{clean[0]}~{clean[-1]}"

    @staticmethod
    def _annotate_parallel_cable_bundles(cables: list[dict[str, Any]]) -> None:
        bundles: defaultdict[tuple[Any, ...], list[dict[str, Any]]] = defaultdict(list)
        for cable in cables:
            attrs = cable.get("attributes", {})
            if attrs.get("route_policy") not in {"converge_to_42u_cabinet_zone", "converge_to_ups_power_zone", "converge_to_ups_battery_cabinet"}:
                continue
            convergence = attrs.get("convergence_point") or {}
            if convergence.get("x") is None or convergence.get("y") is None:
                continue
            key = (
                attrs.get("layer_role") or cable.get("type"),
                attrs.get("target_device_id") or attrs.get("target_label"),
                round(float(convergence["x"]), 1),
                round(float(convergence["y"]), 1),
            )
            bundles[key].append(cable)

        for key, items in bundles.items():
            if len(items) < 2:
                continue
            bundle_id = "bundle_" + "_".join(str(part).replace(" ", "_").replace("\n", "_") for part in key)
            ordered = sorted(items, key=lambda item: str(item.get("id") or item.get("source_entity_id") or ""))
            total = len(ordered)
            media_counts = Counter(str(item.get("attributes", {}).get("media") or item.get("type") or "unknown") for item in ordered)
            for index, item in enumerate(ordered, start=1):
                attrs = item.setdefault("attributes", {})
                attrs.update(
                    {
                        "bundle_id": bundle_id,
                        "bundle_role": "converged_parallel_routes",
                        "bundle_count": total,
                        "parallel_index": index,
                        "parallel_total": total,
                        "parallel_scope": "same_layer_role_same_equipment_convergence",
                        "parallel_media_counts": dict(media_counts),
                    }
                )

    @staticmethod
    def _orthogonal_route(start: dict[str, float], end: dict[str, float]) -> list[dict[str, float]]:
        mid_y = (start["y"] + end["y"]) / 2.0
        return [
            {"x": start["x"], "y": start["y"]},
            {"x": start["x"], "y": mid_y},
            {"x": end["x"], "y": mid_y},
            {"x": end["x"], "y": end["y"]},
        ]

    def _converged_route_to_core(
        self,
        start: dict[str, float],
        core_pos: dict[str, float],
        convergence_point: dict[str, float] | None = None,
    ) -> list[dict[str, float]]:
        convergence = convergence_point or self._default_convergence_point(core_pos)
        route = [
            {"x": start["x"], "y": start["y"]},
            {"x": start["x"], "y": convergence["y"]},
            {"x": convergence["x"], "y": convergence["y"]},
            {"x": core_pos["x"], "y": convergence["y"]},
            {"x": core_pos["x"], "y": core_pos["y"]},
        ]
        return self._dedup_route_points(route)

    @staticmethod
    def _default_convergence_point(core_pos: dict[str, float]) -> dict[str, float]:
        return {"x": float(core_pos["x"]) + 8_000.0, "y": float(core_pos["y"]) + 5_000.0}

    @staticmethod
    def _core_convergence_point(core: dict[str, Any]) -> dict[str, float]:
        core_pos = core.get("geometry", {}).get("position") or {}
        attrs = core.get("attributes") or {}
        bbox = attrs.get("target_floor_bbox") or attrs.get("source_floor_bbox") or attrs.get("cad_geometry_bbox") or {}
        if bbox:
            return {
                "x": min(
                    float(bbox.get("max_x", core_pos.get("x", 0.0))) - 1_500.0,
                    max(float(bbox.get("min_x", core_pos.get("x", 0.0))) + 1_500.0, float(core_pos.get("x", 0.0)) + 3_000.0),
                ),
                "y": min(
                    float(bbox.get("max_y", core_pos.get("y", 0.0))) - 1_500.0,
                    max(float(bbox.get("min_y", core_pos.get("y", 0.0))) + 1_500.0, float(core_pos.get("y", 0.0)) + 3_000.0),
                ),
            }
        return RuleEngine._default_convergence_point(core_pos)

    @staticmethod
    def _dedup_route_points(points: list[dict[str, float]]) -> list[dict[str, float]]:
        deduped: list[dict[str, float]] = []
        for point in points:
            if deduped and abs(deduped[-1]["x"] - point["x"]) < 1.0 and abs(deduped[-1]["y"] - point["y"]) < 1.0:
                continue
            deduped.append(point)
        return deduped

    def _site_metadata(self, entities: list[dict[str, Any]]) -> dict[str, Any]:
        site_defaults = self.standards.get("site", {})
        heights = self._infer_warehouse_heights(entities)
        site_type = "mixed" if len(self.site_profiles) > 1 else self.site_profiles[0]
        if self._is_generic_mode():
            return {
                "site_type": site_defaults.get("site_type") or "generic",
                "site_profiles": self.site_profiles,
                "source": "generic_cad_layers",
            }
        return {
            "site_type": site_type if len(self.site_profiles) > 1 else site_defaults.get("site_type") or site_type,
            "site_profiles": self.site_profiles,
            "dock_height_m": float(site_defaults.get("dock_height_m", DOCK_HEIGHT_M)),
            "warehouse_floor_height_m": float(site_defaults.get("warehouse_floor_height_m", DOCK_HEIGHT_M)),
            "yard_ground_elevation_m": float(site_defaults.get("yard_ground_elevation_m", 0.0)),
            "warehouse_wall_height_m": heights.get("warehouse_wall_height_m", float(site_defaults.get("warehouse_wall_height_m", WAREHOUSE_WALL_HEIGHT_M))),
            "warehouse_roof_peak_height_m": heights.get("warehouse_roof_peak_height_m", float(site_defaults.get("warehouse_roof_peak_height_m", WAREHOUSE_ROOF_PEAK_HEIGHT_M))),
            "tail_camera_to_vehicle_gap_m": float(self.standards.get("dock", {}).get("camera_to_vehicle_tail_gap_m", 5.0)),
            "vehicle_wall_clearance_m": float(self.standards.get("dock", {}).get("vehicle_wall_clearance_m", 0.6)),
            "source": "用户验收反馈 + 施工工艺图高度标注 + 公司标准图例",
            "vehicle_standard": "4.2M箱式货车 / 9.6M箱式货车 / 17.5M集卡挂车 / 61尺集卡",
        }

    @staticmethod
    def _infer_warehouse_heights(entities: list[dict[str, Any]]) -> dict[str, float]:
        values: set[float] = set()
        for entity in entities:
            if entity.get("entity_type") not in {"TEXT", "MTEXT"}:
                continue
            text = str(entity.get("text", "")).strip()
            if re.fullmatch(r"\d{1,2}\.\d{3}", text):
                try:
                    value = float(text)
                except ValueError:
                    continue
                if 8.0 <= value <= 14.0:
                    values.add(value)
        heights: dict[str, float] = {}
        if values:
            lower = min(values, key=lambda item: abs(item - 10.5))
            peak = min(values, key=lambda item: abs(item - 12.6))
            if 9.0 <= lower <= 11.5:
                heights["warehouse_wall_height_m"] = lower
            if peak >= lower:
                heights["warehouse_roof_peak_height_m"] = peak
        return heights

    def _infer_warehouse_shell(self, structures: list[dict[str, Any]], devices: list[dict[str, Any]] | None = None) -> dict[str, Any] | None:
        outline = self._best_warehouse_outline(structures, devices or [])
        if outline:
            return self._polygon_area(
                "area_warehouse_shell",
                "area.warehouse.shell",
                "仓库外墙",
                outline["points"],
                {
                    "height_m": float(self.standards.get("site", {}).get("warehouse_wall_height_m", WAREHOUSE_WALL_HEIGHT_M)),
                    "roof_peak_height_m": float(self.standards.get("site", {}).get("warehouse_roof_peak_height_m", WAREHOUSE_ROOF_PEAK_HEIGHT_M)),
                    "source": "优先采用基准主平面的闭合建筑轮廓线；办公夹层、系统图框、标题框和非基准系统视图结构不参与仓库外墙",
                    "source_structure_id": outline.get("source_structure_id"),
                    "source_layer": outline.get("source_layer"),
                },
            )

        dock_layout_shell = self._infer_dock_layout_subject_shell(structures, devices or [])
        if dock_layout_shell:
            return dock_layout_shell

        points = self._warehouse_shell_points(structures, {"building.wall", "building.outline"})
        if len(points) < 4:
            points = self._warehouse_shell_points(structures, {"building.wall", "building.outline", "building.platform"})
        if len(points) < 4:
            points = []
            for structure in structures:
                if structure.get("type") not in {"building.wall", "building.outline", "building.platform"}:
                    continue
                geometry = structure.get("geometry", {})
                points.extend(geometry.get("points") or [])
        if len(points) < 4:
            return None
        min_x = min(point["x"] for point in points)
        max_x = max(point["x"] for point in points)
        min_y = min(point["y"] for point in points)
        max_y = max(point["y"] for point in points)
        if max_x - min_x < 20_000 or max_y - min_y < 20_000:
            return None
        return self._rect_area(
            "area_warehouse_shell",
            "area.warehouse.shell",
            "仓库外墙",
            min_x,
            min_y,
            max_x,
            max_y,
            {
                "height_m": float(self.standards.get("site", {}).get("warehouse_wall_height_m", WAREHOUSE_WALL_HEIGHT_M)),
                "roof_peak_height_m": float(self.standards.get("site", {}).get("warehouse_roof_peak_height_m", WAREHOUSE_ROOF_PEAK_HEIGHT_M)),
                "source": "基准主平面墙体/轮廓/月台图层外包络，停车位、办公夹层、系统图框和标题框不参与仓库外墙包络",
            },
        )

    def _warehouse_shell_points(self, structures: list[dict[str, Any]], allowed_types: set[str]) -> list[dict[str, float]]:
        points: list[dict[str, float]] = []
        for structure in structures:
            if not self._is_warehouse_shell_structure_candidate(structure, allowed_types):
                continue
            geometry = structure.get("geometry", {})
            points.extend(geometry.get("points") or [])
        return points

    def _is_warehouse_shell_structure_candidate(self, structure: dict[str, Any], allowed_types: set[str]) -> bool:
        if structure.get("type") not in allowed_types:
            return False
        attrs = structure.get("attributes") or {}
        if attrs.get("source_kind") == "office_floor_structure" or attrs.get("floor_label") or attrs.get("level"):
            return False
        if attrs.get("merged_from_system_view"):
            return False
        layer = str(structure.get("original_layer") or structure.get("layer") or "")
        if self._is_parking_layer(layer):
            return False
        return True

    def _best_warehouse_outline(self, structures: list[dict[str, Any]], devices: list[dict[str, Any]]) -> dict[str, Any] | None:
        device_points = [
            device["geometry"]["position"]
            for device in devices
            if device.get("geometry", {}).get("position")
            and device.get("type") in {"network.ap", "network.cabinet", "security.camera.fisheye", "security.camera.dome", "security.camera.bullet", "security.camera.rear"}
        ]
        candidates: list[dict[str, Any]] = []
        for structure in structures:
            if not self._is_warehouse_shell_structure_candidate(structure, {"building.outline"}):
                continue
            geometry = structure.get("geometry") or {}
            points = self._normalized_polygon_points(geometry.get("points") or [])
            if len(points) < 4:
                continue
            bbox = self._points_bbox(points)
            if not bbox:
                continue
            span_x = bbox["max_x"] - bbox["min_x"]
            span_y = bbox["max_y"] - bbox["min_y"]
            if span_x < 20_000.0 or span_y < 20_000.0:
                continue
            if span_x > 900_000.0 or span_y > 700_000.0:
                continue
            if not (geometry.get("closed") or geometry.get("type") == "Polygon"):
                continue
            if self._is_system_frame_bbox(structure, bbox):
                continue
            layer = str(structure.get("layer") or structure.get("original_layer") or "")
            if not self._is_warehouse_outline_layer(layer):
                continue
            axis_stats = self._axis_aligned_polyline_stats(points, closed=True)
            if axis_stats["total_length"] <= 0.0 or axis_stats["off_axis_ratio"] > 0.18:
                continue
            bounds = (self.base_view or {}).get("bounds") or {}
            if bounds and (span_x * span_y) / max(self._bbox_area(bounds), 1.0) > 0.60:
                continue
            attrs = structure.get("attributes") or {}
            layer_weight = 2.0 if attrs.get("source_kind") == "warehouse_wall_outline" else 1.0
            if any(keyword in layer for keyword in ("建筑轮廓", "轮廓线", "A-FLOR-ROOF")):
                layer_weight = max(layer_weight, 2.0)
            contained = self._point_bbox_count(device_points, bbox, pad_mm=6_000.0)
            area = span_x * span_y
            score = area * layer_weight + contained * 80_000_000.0
            candidates.append(
                {
                    "score": score,
                    "points": points,
                    "source_structure_id": structure.get("id"),
                    "source_layer": layer,
                    "bbox": bbox,
                }
            )
        if not candidates:
            return None
        return max(candidates, key=lambda item: item["score"])

    def _infer_dock_layout_subject_shell(self, structures: list[dict[str, Any]], devices: list[dict[str, Any]]) -> dict[str, Any] | None:
        rear_cameras = [
            device
            for device in devices
            if device.get("type") == "security.camera.rear" and device.get("geometry", {}).get("position")
        ]
        if len(rear_cameras) < 8:
            return None

        vertical_clusters: list[dict[str, Any]] = []
        for cluster in self._cluster_devices_by_axis(rear_cameras, "x", tolerance_mm=3400.0):
            positions = [device["geometry"]["position"] for device in cluster]
            span_y = max(point["y"] for point in positions) - min(point["y"] for point in positions)
            if len(cluster) < 4 or span_y < 20_000.0:
                continue
            avg_x = sum(point["x"] for point in positions) / len(positions)
            vertical_clusters.append({"cluster": cluster, "avg_x": avg_x, "span_y": span_y})
        vertical_clusters.sort(key=lambda item: item["avg_x"])
        if len(vertical_clusters) < 2:
            return None

        left_cluster = vertical_clusters[0]
        right_cluster = vertical_clusters[-1]
        if float(right_cluster["avg_x"]) - float(left_cluster["avg_x"]) < 45_000.0:
            return None

        subject_positions = [
            device["geometry"]["position"]
            for cluster_info in (left_cluster, right_cluster)
            for device in cluster_info["cluster"]
        ]
        min_camera_y = min(point["y"] for point in subject_positions)
        max_camera_y = max(point["y"] for point in subject_positions)

        left_x = self._subject_vertical_boundary_x(
            structures,
            target_x=float(left_cluster["avg_x"]),
            min_y=min_camera_y,
            max_y=max_camera_y,
        )
        right_x = self._subject_vertical_boundary_x(
            structures,
            target_x=float(right_cluster["avg_x"]),
            min_y=min_camera_y,
            max_y=max_camera_y,
        )
        left_x = left_x if left_x is not None else float(left_cluster["avg_x"])
        right_x = right_x if right_x is not None else float(right_cluster["avg_x"])
        if right_x - left_x < 45_000.0:
            left_x = float(left_cluster["avg_x"])
            right_x = float(right_cluster["avg_x"])
        if right_x - left_x < 45_000.0:
            return None

        bottom_y = self._subject_horizontal_boundary_y(
            structures,
            left_x=left_x,
            right_x=right_x,
            target_y=min_camera_y,
            side="bottom",
        )
        top_y = self._subject_horizontal_boundary_y(
            structures,
            left_x=left_x,
            right_x=right_x,
            target_y=max_camera_y,
            side="top",
        )
        bottom_y = bottom_y if bottom_y is not None else min_camera_y - 12_000.0
        top_y = top_y if top_y is not None else max_camera_y + 12_000.0
        if top_y - bottom_y < 60_000.0:
            return None

        shell_area = self._rect_area(
            "area_warehouse_shell",
            "area.warehouse.shell",
            "仓库外墙",
            left_x,
            bottom_y,
            right_x,
            top_y,
            {
                "height_m": float(self.standards.get("site", {}).get("warehouse_wall_height_m", WAREHOUSE_WALL_HEIGHT_M)),
                "roof_peak_height_m": float(self.standards.get("site", {}).get("warehouse_roof_peak_height_m", WAREHOUSE_ROOF_PEAK_HEIGHT_M)),
                "source": "基于左右车尾摄像头队列和主体墙/区域/道口边界线推断仓库主体；道路红线、园区外圈、车位阵列外缘和第三方租赁区不参与外墙",
                "inferred_from": "dock_layout_subject",
                "left_camera_count": len(left_cluster["cluster"]),
                "right_camera_count": len(right_cluster["cluster"]),
                "left_boundary_x": round(left_x, 3),
                "right_boundary_x": round(right_x, 3),
                "bottom_boundary_y": round(bottom_y, 3),
                "top_boundary_y": round(top_y, 3),
                "wall_blacklist": ["A-ROAD-RED", "page_outer_box", "parking_array_outer", "third_party_zone"],
            },
        )
        shell_area["confidence"] = 0.84
        return shell_area

    def _subject_vertical_boundary_x(
        self,
        structures: list[dict[str, Any]],
        *,
        target_x: float,
        min_y: float,
        max_y: float,
    ) -> float | None:
        candidates: dict[int, dict[str, float]] = {}
        search_min_y = min_y - 14_000.0
        search_max_y = max_y + 14_000.0
        for structure in structures:
            if not self._is_subject_boundary_structure(structure):
                continue
            points = structure.get("geometry", {}).get("points") or []
            for start, end in self._iter_structure_segments(points, bool(structure.get("geometry", {}).get("closed"))):
                dx = abs(float(start["x"]) - float(end["x"]))
                dy = abs(float(start["y"]) - float(end["y"]))
                if dx > 250.0 or dy < 6_000.0:
                    continue
                seg_min_y = min(float(start["y"]), float(end["y"]))
                seg_max_y = max(float(start["y"]), float(end["y"]))
                overlap = min(seg_max_y, search_max_y) - max(seg_min_y, search_min_y)
                if overlap < 3_000.0:
                    continue
                x = (float(start["x"]) + float(end["x"])) / 2.0
                distance = abs(x - target_x)
                if distance > 10_000.0:
                    continue
                bucket = round(x / 500.0)
                stat = candidates.setdefault(bucket, {"x_sum": 0.0, "length": 0.0, "count": 0.0, "distance": distance})
                stat["x_sum"] += x * overlap
                stat["length"] += overlap
                stat["count"] += 1.0
                stat["distance"] = min(stat["distance"], distance)
        if not candidates:
            return None
        best = max(candidates.values(), key=lambda item: (item["length"] - item["distance"] * 8.0, item["count"]))
        if best["length"] <= 0.0:
            return None
        return best["x_sum"] / best["length"]

    def _subject_horizontal_boundary_y(
        self,
        structures: list[dict[str, Any]],
        *,
        left_x: float,
        right_x: float,
        target_y: float,
        side: str,
    ) -> float | None:
        candidates: dict[int, dict[str, float]] = {}
        width = max(right_x - left_x, 1.0)
        for structure in structures:
            if not self._is_subject_boundary_structure(structure):
                continue
            points = structure.get("geometry", {}).get("points") or []
            for start, end in self._iter_structure_segments(points, bool(structure.get("geometry", {}).get("closed"))):
                dx = abs(float(start["x"]) - float(end["x"]))
                dy = abs(float(start["y"]) - float(end["y"]))
                if dy > 250.0 or dx < width * 0.35:
                    continue
                y = (float(start["y"]) + float(end["y"])) / 2.0
                distance = abs(y - target_y)
                if distance > 38_000.0:
                    continue
                if side == "top" and y < target_y - 6_000.0:
                    continue
                if side == "bottom" and y > target_y + 6_000.0:
                    continue
                seg_min_x = min(float(start["x"]), float(end["x"]))
                seg_max_x = max(float(start["x"]), float(end["x"]))
                overlap = min(seg_max_x, right_x + 12_000.0) - max(seg_min_x, left_x - 12_000.0)
                if overlap < width * 0.35:
                    continue
                bucket = round(y / 500.0)
                stat = candidates.setdefault(bucket, {"y_sum": 0.0, "length": 0.0, "count": 0.0, "distance": distance})
                stat["y_sum"] += y * overlap
                stat["length"] += overlap
                stat["count"] += 1.0
                stat["distance"] = min(stat["distance"], distance)
        if not candidates:
            return None
        best = max(candidates.values(), key=lambda item: (item["length"] - item["distance"] * 1.5, item["count"]))
        if best["length"] <= 0.0:
            return None
        return best["y_sum"] / best["length"]

    def _is_subject_boundary_structure(self, structure: dict[str, Any]) -> bool:
        if structure.get("type") not in {"building.wall", "building.zone", "building.road", "building.platform", "building.outline"}:
            return False
        attrs = structure.get("attributes") or {}
        if attrs.get("merged_from_system_view"):
            return False
        layer = str(structure.get("original_layer") or structure.get("layer") or "")
        if layer.upper() in {"A-ROAD-RED", "0"}:
            return False
        if self._is_parking_layer(layer):
            return False
        return True

    @staticmethod
    def _iter_structure_segments(points: list[dict[str, float]], closed: bool = False) -> list[tuple[dict[str, float], dict[str, float]]]:
        valid_points = [
            {"x": float(point["x"]), "y": float(point["y"])}
            for point in points
            if isinstance(point, dict) and point.get("x") is not None and point.get("y") is not None
        ]
        segments = list(zip(valid_points, valid_points[1:]))
        if closed and len(valid_points) > 2:
            segments.append((valid_points[-1], valid_points[0]))
        return segments

    def _filter_structure_reference_copies(self, structures: list[dict[str, Any]]) -> list[dict[str, Any]]:
        if not self.system_views:
            return [structure for structure in structures if not self._is_system_frame_structure(structure)]
        canonical_kind = self._canonical_system_view_kind()
        filtered: list[dict[str, Any]] = []
        for structure in structures:
            attrs = structure.get("attributes") or {}
            kind = attrs.get("merged_from_system_view")
            if kind and kind != canonical_kind:
                continue
            if self._is_system_frame_structure(structure):
                continue
            filtered.append(structure)
        return filtered

    def _filter_structures_to_warehouse_subject(
        self,
        structures: list[dict[str, Any]],
        shell_area: dict[str, Any] | None,
        parking_spaces: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        shell_points = shell_area.get("geometry", {}).get("points") if shell_area else None
        shell_bbox = self._points_bbox(shell_points or [])
        if not shell_bbox:
            return structures

        focus_points = list(shell_points or [])
        for space in parking_spaces:
            focus_points.extend(space.get("geometry", {}).get("points") or [])
        focus_bbox = self._points_bbox(focus_points)
        if not focus_bbox:
            return structures

        pad = 18_000.0
        focus_bounds = {
            "min_x": focus_bbox["min_x"] - pad,
            "min_y": focus_bbox["min_y"] - pad,
            "max_x": focus_bbox["max_x"] + pad,
            "max_y": focus_bbox["max_y"] + pad,
        }
        focus_span_x = max(focus_bounds["max_x"] - focus_bounds["min_x"], 1.0)
        focus_span_y = max(focus_bounds["max_y"] - focus_bounds["min_y"], 1.0)
        filtered: list[dict[str, Any]] = []
        removed: Counter[str] = Counter()

        for structure in structures:
            points = self._geometry_points(structure.get("geometry") or {})
            bbox = self._points_bbox(points)
            if self._is_blacklisted_outer_site_structure(structure, bbox, shell_bbox):
                removed["outer_site_boundary"] += 1
                continue
            if not bbox:
                filtered.append(structure)
                continue
            if not self._bbox_intersects(bbox, focus_bounds):
                removed["outside_subject_focus"] += 1
                continue
            if self._is_internal_dock_reference_structure(structure, bbox, shell_points or []):
                removed["internal_dock_reference_line"] += 1
                continue
            if self._is_internal_dock_cutout_wall(structure, bbox, shell_area):
                removed["internal_dock_cutout_wall"] += 1
                continue

            span_x = bbox["max_x"] - bbox["min_x"]
            span_y = bbox["max_y"] - bbox["min_y"]
            if structure.get("type") == "building.road" and (span_x > focus_span_x * 1.25 or span_y > focus_span_y * 1.25):
                center = self._bbox_center(bbox)
                if not self._point_in_bounds(center, focus_bounds):
                    removed["oversized_road_reference"] += 1
                    continue
            filtered.append(structure)

        if removed:
            attrs = shell_area.setdefault("attributes", {}) if shell_area else {}
            attrs["structure_focus_filter"] = {
                "rule": "warehouse_subject_only",
                "removed_count": int(sum(removed.values())),
                "removed_by_reason": dict(sorted(removed.items())),
                "focus_bounds": {key: round(float(value), 3) for key, value in focus_bounds.items()},
            }
        return filtered

    def _is_internal_dock_reference_structure(
        self,
        structure: dict[str, Any],
        bbox: dict[str, float],
        shell_points: list[dict[str, float]],
    ) -> bool:
        if structure.get("type") != "building.road" or len(shell_points) < 3:
            return False
        attrs = structure.get("attributes") or {}
        layer = str(attrs.get("matched_layer") or structure.get("original_layer") or structure.get("layer") or "")
        if attrs.get("source_kind") != "fallback_structure_layer":
            return False
        if not any(token in layer for token in ("道口", "车位", "停车")):
            return False
        center = self._bbox_center(bbox)
        return self._point_in_polygon(center, shell_points)

    @staticmethod
    def _point_in_polygon(point: dict[str, float], polygon: list[dict[str, float]]) -> bool:
        x = float(point.get("x", 0.0))
        y = float(point.get("y", 0.0))
        inside = False
        j = len(polygon) - 1
        for i, current in enumerate(polygon):
            previous = polygon[j]
            xi = float(current.get("x", 0.0))
            yi = float(current.get("y", 0.0))
            xj = float(previous.get("x", 0.0))
            yj = float(previous.get("y", 0.0))
            if (yi > y) != (yj > y):
                intersect_x = (xj - xi) * (y - yi) / ((yj - yi) or 1e-9) + xi
                if x < intersect_x:
                    inside = not inside
            j = i
        return inside

    def _is_internal_dock_cutout_wall(
        self,
        structure: dict[str, Any],
        bbox: dict[str, float],
        shell_area: dict[str, Any] | None,
    ) -> bool:
        if structure.get("type") != "building.wall":
            return False
        shell_attrs = shell_area.get("attributes", {}) if shell_area else {}
        cutout = shell_attrs.get("internal_dock_cutout") if isinstance(shell_attrs, dict) else None
        dock_bbox = cutout.get("dock_bbox") if isinstance(cutout, dict) else None
        if not isinstance(dock_bbox, dict):
            return False
        attrs = structure.get("attributes") or {}
        layer = str(attrs.get("matched_layer") or structure.get("original_layer") or structure.get("layer") or "")
        if attrs.get("source_kind") != "fallback_structure_layer" and "墙" not in layer:
            return False
        pad_x = 2_500.0
        pad_y = 2_500.0
        expanded = {
            "min_x": float(dock_bbox["min_x"]) - pad_x,
            "min_y": float(dock_bbox["min_y"]) - pad_y,
            "max_x": float(dock_bbox["max_x"]) + pad_x,
            "max_y": float(dock_bbox["max_y"]) + pad_y,
        }
        if not self._bbox_intersects(bbox, expanded):
            return False
        center = self._bbox_center(bbox)
        if self._point_in_bounds(center, expanded):
            return True
        overlap_x = min(float(bbox["max_x"]), expanded["max_x"]) - max(float(bbox["min_x"]), expanded["min_x"])
        overlap_y = min(float(bbox["max_y"]), expanded["max_y"]) - max(float(bbox["min_y"]), expanded["min_y"])
        return overlap_x > 2_000.0 and overlap_y > 2_000.0

    def _is_blacklisted_outer_site_structure(
        self,
        structure: dict[str, Any],
        bbox: dict[str, float] | None,
        shell_bbox: dict[str, float],
    ) -> bool:
        layer = str(structure.get("original_layer") or structure.get("layer") or "")
        layer_upper = layer.upper()
        attrs = structure.get("attributes") or {}
        if layer_upper == "A-ROAD-RED" or attrs.get("source_kind") == "main_plan_large_outline":
            return True
        if not bbox:
            return False
        span_x = bbox["max_x"] - bbox["min_x"]
        span_y = bbox["max_y"] - bbox["min_y"]
        shell_span_x = max(shell_bbox["max_x"] - shell_bbox["min_x"], 1.0)
        shell_span_y = max(shell_bbox["max_y"] - shell_bbox["min_y"], 1.0)
        oversized = span_x > shell_span_x * 1.35 or span_y > shell_span_y * 1.35
        if structure.get("type") == "building.outline" and oversized and not self._is_warehouse_outline_layer(layer):
            return True
        if layer_upper == "0" and oversized:
            return True
        return False

    def _canonical_system_view_kind(self) -> str | None:
        if self.base_view and self.base_view.get("kind") == "main_plan":
            return None
        for view in self.system_views:
            if abs(float(view.get("offset_x", 0.0) or 0.0)) < 1.0 and abs(float(view.get("offset_y", 0.0) or 0.0)) < 1.0:
                return str(view.get("kind") or "")
        monitor = next((view for view in self.system_views if view.get("kind") == "monitor"), None)
        if monitor:
            return "monitor"
        return str(self.system_views[0].get("kind") or "") if self.system_views else None

    def _is_system_frame_structure(self, structure: dict[str, Any]) -> bool:
        layer = str(structure.get("layer") or structure.get("original_layer") or "")
        if any(keyword.lower() in layer.lower() for keyword in ("图框", "图签", "title", "border", "sheet", "viewport")):
            return True
        bbox = self._structure_bbox(structure)
        if not bbox:
            return False
        return self._is_system_frame_bbox(structure, bbox)

    def _is_system_frame_bbox(self, structure: dict[str, Any], bbox: dict[str, float]) -> bool:
        attrs = structure.get("attributes") or {}
        kind = attrs.get("merged_from_system_view")
        if not kind:
            return False
        view = next((item for item in self.system_views if item.get("kind") == kind), None)
        if not view:
            return False
        raw_bbox = {
            "min_x": bbox["min_x"] + float(attrs.get("merge_offset_x_mm", 0.0) or 0.0),
            "max_x": bbox["max_x"] + float(attrs.get("merge_offset_x_mm", 0.0) or 0.0),
            "min_y": bbox["min_y"] + float(attrs.get("merge_offset_y_mm", 0.0) or 0.0),
            "max_y": bbox["max_y"] + float(attrs.get("merge_offset_y_mm", 0.0) or 0.0),
        }
        view_bounds = view.get("bounds") or {}
        span_x = raw_bbox["max_x"] - raw_bbox["min_x"]
        span_y = raw_bbox["max_y"] - raw_bbox["min_y"]
        view_span_x = float(view_bounds.get("max_x", 0.0) or 0.0) - float(view_bounds.get("min_x", 0.0) or 0.0)
        view_span_y = float(view_bounds.get("max_y", 0.0) or 0.0) - float(view_bounds.get("min_y", 0.0) or 0.0)
        if view_span_x <= 0 or view_span_y <= 0:
            return False
        near_left = abs(raw_bbox["min_x"] - float(view_bounds.get("min_x", 0.0))) <= 2_500.0
        near_right = abs(raw_bbox["max_x"] - float(view_bounds.get("max_x", 0.0))) <= 2_500.0
        near_bottom = abs(raw_bbox["min_y"] - float(view_bounds.get("min_y", 0.0))) <= 2_500.0
        near_top = abs(raw_bbox["max_y"] - float(view_bounds.get("max_y", 0.0))) <= 2_500.0
        is_large_frame = span_x >= view_span_x * 0.75 or span_y >= view_span_y * 0.75
        return is_large_frame and (near_left or near_right or near_bottom or near_top)

    @staticmethod
    def _normalized_polygon_points(points: list[dict[str, float]]) -> list[dict[str, float]]:
        if len(points) < 2:
            return points
        normalized = [dict(point) for point in points]
        first = normalized[0]
        last = normalized[-1]
        if abs(float(first["x"]) - float(last["x"])) <= 1.0 and abs(float(first["y"]) - float(last["y"])) <= 1.0:
            normalized = normalized[:-1]
        return normalized

    @staticmethod
    def _axis_aligned_polyline_stats(points: list[dict[str, float]], closed: bool = False) -> dict[str, float]:
        segments = list(zip(points, points[1:]))
        if closed and len(points) > 2:
            segments.append((points[-1], points[0]))
        total = 0.0
        axis_length = 0.0
        horizontal_length = 0.0
        vertical_length = 0.0
        off_axis_length = 0.0
        for start, end in segments:
            dx = abs(float(end["x"]) - float(start["x"]))
            dy = abs(float(end["y"]) - float(start["y"]))
            length = (dx * dx + dy * dy) ** 0.5
            if length <= 1.0:
                continue
            total += length
            if dy <= 200.0:
                horizontal_length += length
                axis_length += length
            elif dx <= 200.0:
                vertical_length += length
                axis_length += length
            else:
                off_axis_length += length
        return {
            "total_length": total,
            "axis_length": axis_length,
            "horizontal_length": horizontal_length,
            "vertical_length": vertical_length,
            "off_axis_length": off_axis_length,
            "off_axis_ratio": off_axis_length / total if total > 0.0 else 1.0,
        }

    @staticmethod
    def _points_bbox(points: list[dict[str, float]]) -> dict[str, float] | None:
        if not points:
            return None
        return {
            "min_x": min(float(point["x"]) for point in points),
            "min_y": min(float(point["y"]) for point in points),
            "max_x": max(float(point["x"]) for point in points),
            "max_y": max(float(point["y"]) for point in points),
        }

    @staticmethod
    def _polygon_points_area(points: list[dict[str, float]]) -> float:
        if len(points) < 3:
            return 0.0
        total = 0.0
        closed = [*points, points[0]]
        for start, end in zip(closed, closed[1:]):
            total += float(start["x"]) * float(end["y"]) - float(end["x"]) * float(start["y"])
        return abs(total) / 2.0

    @staticmethod
    def _structure_bbox(structure: dict[str, Any]) -> dict[str, float] | None:
        geometry = structure.get("geometry") or {}
        points = geometry.get("points") or []
        if points:
            return RuleEngine._points_bbox(points)
        center = geometry.get("center")
        radius = float(geometry.get("radius", 0.0) or 0.0)
        if center:
            return {
                "min_x": float(center["x"]) - radius,
                "min_y": float(center["y"]) - radius,
                "max_x": float(center["x"]) + radius,
                "max_y": float(center["y"]) + radius,
            }
        return None

    def _semantic_model_extents(self, *collections: list[dict[str, Any]]) -> dict[str, dict[str, float]] | None:
        points: list[dict[str, float]] = []
        for collection in collections:
            for item in collection or []:
                points.extend(self._geometry_points(item.get("geometry") or {}))
        filtered = self._filter_extent_outliers(points)
        bbox = self._points_bbox(filtered)
        if not bbox:
            return None
        pad = 5_000.0
        return {
            "min": {"x": round(bbox["min_x"] - pad, 3), "y": round(bbox["min_y"] - pad, 3)},
            "max": {"x": round(bbox["max_x"] + pad, 3), "y": round(bbox["max_y"] + pad, 3)},
        }

    @staticmethod
    def _filter_extent_outliers(points: list[dict[str, float]]) -> list[dict[str, float]]:
        clean = [
            {"x": float(point["x"]), "y": float(point["y"])}
            for point in points
            if point.get("x") is not None and point.get("y") is not None
        ]
        if len(clean) < 12:
            return clean
        xs = sorted(point["x"] for point in clean)
        ys = sorted(point["y"] for point in clean)

        def percentile(values: list[float], ratio: float) -> float:
            index = min(max(round((len(values) - 1) * ratio), 0), len(values) - 1)
            return values[index]

        q1_x, q3_x = percentile(xs, 0.25), percentile(xs, 0.75)
        q1_y, q3_y = percentile(ys, 0.25), percentile(ys, 0.75)
        iqr_x = max(q3_x - q1_x, 1.0)
        iqr_y = max(q3_y - q1_y, 1.0)
        margin_x = max(iqr_x * 8.0, 80_000.0)
        margin_y = max(iqr_y * 8.0, 80_000.0)
        min_x, max_x = q1_x - margin_x, q3_x + margin_x
        min_y, max_y = q1_y - margin_y, q3_y + margin_y
        filtered = [point for point in clean if min_x <= point["x"] <= max_x and min_y <= point["y"] <= max_y]
        return filtered if len(filtered) >= max(4, int(len(clean) * 0.5)) else clean

    @staticmethod
    def _point_bbox_count(points: list[dict[str, float]], bbox: dict[str, float], pad_mm: float = 0.0) -> int:
        return sum(
            1
            for point in points
            if bbox["min_x"] - pad_mm <= float(point["x"]) <= bbox["max_x"] + pad_mm
            and bbox["min_y"] - pad_mm <= float(point["y"]) <= bbox["max_y"] + pad_mm
        )

    def _infer_operational_shell(self, devices: list[dict[str, Any]]) -> dict[str, Any] | None:
        points = [
            device["geometry"]["position"]
            for device in devices
            if device.get("type") in {"network.ap", "network.cabinet", "security.camera.rear", "security.camera.fisheye", "security.camera.bullet", "security.camera.dome"}
            and device.get("geometry", {}).get("position")
        ]
        if len(points) < 4:
            return None
        min_x = min(point["x"] for point in points)
        max_x = max(point["x"] for point in points)
        min_y = min(point["y"] for point in points)
        max_y = max(point["y"] for point in points)
        span_x = max_x - min_x
        span_y = max_y - min_y
        if span_x < 20_000.0 or span_y < 20_000.0:
            return None
        pad_x = max(span_x * 0.08, 12_000.0)
        pad_y = max(span_y * 0.08, 12_000.0)
        return self._rect_area(
            "area_warehouse_shell",
            "area.warehouse.shell",
            "仓库外墙",
            min_x - pad_x,
            min_y - pad_y,
            max_x + pad_x,
            max_y + pad_y,
            {
                "height_m": float(self.standards.get("site", {}).get("warehouse_wall_height_m", WAREHOUSE_WALL_HEIGHT_M)),
                "roof_peak_height_m": float(self.standards.get("site", {}).get("warehouse_roof_peak_height_m", WAREHOUSE_ROOF_PEAK_HEIGHT_M)),
                "source": "有效平面设备/机柜分布包络推断；施工工艺和安装详图不参与仓库外墙包络",
                "inferred_from": "operational_devices",
            },
        )

    def _adjust_shell_for_cad_parking_boundary(
        self,
        areas: list[dict[str, Any]],
        parking_spaces: list[dict[str, Any]],
        devices: list[dict[str, Any]],
    ) -> None:
        shell = next((area for area in areas if area.get("type") == "area.warehouse.shell"), None)
        if not shell:
            return
        shell_points = shell.get("geometry", {}).get("points") or []
        shell_bbox = self._points_bbox(shell_points)
        if not shell_bbox:
            return
        shell_center_x = (shell_bbox["min_x"] + shell_bbox["max_x"]) / 2.0
        shell_center_y = (shell_bbox["min_y"] + shell_bbox["max_y"]) / 2.0
        side_spaces: dict[str, list[dict[str, Any]]] = {"top": [], "bottom": [], "left": [], "right": []}
        for space in parking_spaces:
            attrs = space.get("attributes") or {}
            if attrs.get("source_kind") != "cad_parking_block":
                continue
            points = space.get("geometry", {}).get("points") or []
            bbox = self._points_bbox(points)
            if not bbox:
                continue
            angle = self._snap_cardinal_angle(float(space.get("orientation", {}).get("angle_deg", 0.0) or 0.0), tolerance_deg=3.0)
            center_x = (bbox["min_x"] + bbox["max_x"]) / 2.0
            center_y = (bbox["min_y"] + bbox["max_y"]) / 2.0
            if abs(angle - 180.0) <= 1.0 and center_y > shell_center_y:
                side_spaces["top"].append(space)
            elif angle <= 1.0 and center_y < shell_center_y:
                side_spaces["bottom"].append(space)
            elif abs(angle - 90.0) <= 1.0 and center_x > shell_center_x:
                side_spaces["right"].append(space)
            elif abs(angle - 270.0) <= 1.0 and center_x < shell_center_x:
                side_spaces["left"].append(space)

        adjustments: dict[str, float] = {}
        side_support: dict[str, int] = {}
        max_adjust_mm = 30_000.0
        min_support = 2
        for side, spaces in side_spaces.items():
            if len(spaces) < min_support:
                continue
            bounds = [self._points_bbox(space.get("geometry", {}).get("points") or []) for space in spaces]
            bounds = [bbox for bbox in bounds if bbox]
            if len(bounds) < min_support:
                continue
            if side == "top":
                value = min(float(bbox["min_y"]) for bbox in bounds) - 1000.0
                if shell_center_y < value < shell_bbox["max_y"] - 1000.0 and abs(shell_bbox["max_y"] - value) <= max_adjust_mm:
                    adjustments[side] = value
            elif side == "bottom":
                value = max(float(bbox["max_y"]) for bbox in bounds) + 1000.0
                if shell_bbox["min_y"] + 1000.0 < value < shell_center_y and abs(value - shell_bbox["min_y"]) <= max_adjust_mm:
                    adjustments[side] = value
            elif side == "right":
                value = min(float(bbox["min_x"]) for bbox in bounds) - 1000.0
                if shell_center_x < value < shell_bbox["max_x"] - 1000.0 and abs(shell_bbox["max_x"] - value) <= max_adjust_mm:
                    adjustments[side] = value
            elif side == "left":
                value = max(float(bbox["max_x"]) for bbox in bounds) + 1000.0
                if shell_bbox["min_x"] + 1000.0 < value < shell_center_x and abs(value - shell_bbox["min_x"]) <= max_adjust_mm:
                    adjustments[side] = value
            if side in adjustments:
                side_support[side] = len(bounds)

        if not adjustments:
            self._carve_shell_for_internal_dock_spaces(shell, parking_spaces, shell_bbox, devices)
            return
        adjusted_points: list[dict[str, float]] = []
        for point in shell_points:
            if point.get("x") is None or point.get("y") is None:
                continue
            x = float(point["x"])
            y = float(point["y"])
            if "left" in adjustments:
                x = max(x, adjustments["left"])
            if "right" in adjustments:
                x = min(x, adjustments["right"])
            if "bottom" in adjustments:
                y = max(y, adjustments["bottom"])
            if "top" in adjustments:
                y = min(y, adjustments["top"])
            adjusted_points.append({**point, "x": x, "y": y})
        shell["geometry"] = {**shell.get("geometry", {}), "points": adjusted_points}
        attrs = shell.setdefault("attributes", {})
        attrs["solid_wall_adjusted_for_cad_parking"] = True
        attrs["original_shell_bbox"] = {key: round(float(value), 3) for key, value in shell_bbox.items()}
        attrs["adjusted_sides"] = sorted(adjustments)
        attrs["cad_parking_adjustments"] = {
            side: {
                "adjusted_boundary": round(value, 3),
                "support_count": side_support.get(side, 0),
                "rule": "cad_parking_block_outside_shell_boundary",
            }
            for side, value in sorted(adjustments.items())
        }
        if "top" in adjustments:
            attrs["original_top_y"] = round(shell_bbox["max_y"], 3)
            attrs["adjusted_top_y"] = round(adjustments["top"], 3)
        if "right" in adjustments:
            attrs["original_right_x"] = round(shell_bbox["max_x"], 3)
            attrs["adjusted_right_x"] = round(adjustments["right"], 3)
        if "bottom" in adjustments:
            attrs["original_bottom_y"] = round(shell_bbox["min_y"], 3)
            attrs["adjusted_bottom_y"] = round(adjustments["bottom"], 3)
        if "left" in adjustments:
            attrs["original_left_x"] = round(shell_bbox["min_x"], 3)
            attrs["adjusted_left_x"] = round(adjustments["left"], 3)
        attrs["adjustment_source"] = "CAD 车位块显示车辆在外侧，3D 实墙按车位/月台边界四向收口，建筑轮廓线作为外包络参考"
        self._carve_shell_for_internal_dock_spaces(shell, parking_spaces, shell_bbox, devices)

    def _carve_shell_for_internal_dock_spaces(
        self,
        shell: dict[str, Any],
        parking_spaces: list[dict[str, Any]],
        original_shell_bbox: dict[str, float],
        devices: list[dict[str, Any]] | None = None,
    ) -> bool:
        shell_points = shell.get("geometry", {}).get("points") or []
        shell_bbox = self._points_bbox(shell_points)
        if not shell_bbox:
            return False
        shell_span_x = shell_bbox["max_x"] - shell_bbox["min_x"]
        shell_span_y = shell_bbox["max_y"] - shell_bbox["min_y"]
        if shell_span_x < 45_000.0 or shell_span_y < 60_000.0:
            return False

        internal_spaces: list[dict[str, Any]] = []
        for space in parking_spaces:
            attrs = space.get("attributes") or {}
            source_kind = attrs.get("source_kind")
            if source_kind not in {"tail_camera_inferred", "cad_parking_block"}:
                continue
            label = str(attrs.get("paired_camera_label") or space.get("label") or "")
            if not label.upper().startswith("KW-") or not self._is_rear_camera_label(label):
                continue
            points = space.get("geometry", {}).get("points") or []
            bbox = self._points_bbox(points)
            if not bbox:
                continue
            center_x = (bbox["min_x"] + bbox["max_x"]) / 2.0
            center_y = (bbox["min_y"] + bbox["max_y"]) / 2.0
            if not (
                shell_bbox["min_x"] - 2500.0 <= center_x <= shell_bbox["max_x"] + 2500.0
                and shell_bbox["min_y"] - 2500.0 <= center_y <= shell_bbox["max_y"] + 2500.0
            ):
                continue
            internal_spaces.append(space)
        if len(internal_spaces) < 8:
            return False

        dock_points = [
            point
            for space in internal_spaces
            for point in (space.get("geometry", {}).get("points") or [])
            if point.get("x") is not None and point.get("y") is not None
        ]
        dock_bbox = self._points_bbox(dock_points)
        if not dock_bbox:
            return False
        dock_span_x = dock_bbox["max_x"] - dock_bbox["min_x"]
        dock_span_y = dock_bbox["max_y"] - dock_bbox["min_y"]
        if dock_span_x < shell_span_x * 0.25 or dock_span_y < 4_000.0:
            return False

        distances = {
            "left": dock_bbox["min_x"] - shell_bbox["min_x"],
            "right": shell_bbox["max_x"] - dock_bbox["max_x"],
            "bottom": dock_bbox["min_y"] - shell_bbox["min_y"],
            "top": shell_bbox["max_y"] - dock_bbox["max_y"],
        }
        cut_side = min(distances, key=distances.get)
        if distances[cut_side] > 38_000.0:
            return False
        if cut_side in {"left", "right"} and dock_span_x > dock_span_y * 2.8:
            attrs = shell.setdefault("attributes", {})
            attrs["internal_dock_cutout_skipped"] = {
                "reason": "kw_dock_band_is_horizontal_not_side_wall_notch",
                "candidate_side": cut_side,
                "support_count": len(internal_spaces),
                "dock_bbox": {key: round(float(value), 3) for key, value in dock_bbox.items()},
            }
            return False
        if cut_side in {"bottom", "top"} and dock_span_y > dock_span_x * 2.8:
            attrs = shell.setdefault("attributes", {})
            attrs["internal_dock_cutout_skipped"] = {
                "reason": "kw_dock_band_is_vertical_not_top_bottom_notch",
                "candidate_side": cut_side,
                "support_count": len(internal_spaces),
                "dock_bbox": {key: round(float(value), 3) for key, value in dock_bbox.items()},
            }
            return False

        protected_types = {
            "network.ap",
            "network.cabinet",
            "security.camera",
            "security.camera.fisheye",
            "security.camera.dome",
            "security.camera.bullet",
        }
        protected_devices = [
            device
            for device in devices or []
            if device.get("type") in protected_types
            and device.get("geometry", {}).get("position")
            and self._point_in_bbox(device["geometry"]["position"], dock_bbox, 1_500.0)
        ]
        if len(protected_devices) >= 12:
            attrs = shell.setdefault("attributes", {})
            attrs["internal_dock_cutout_skipped"] = {
                "reason": "candidate_cutout_contains_warehouse_devices",
                "candidate_side": cut_side,
                "support_count": len(internal_spaces),
                "protected_device_count": len(protected_devices),
                "protected_device_types": dict(Counter(str(device.get("type") or "") for device in protected_devices)),
                "dock_bbox": {key: round(float(value), 3) for key, value in dock_bbox.items()},
            }
            return False

        connector = max(min(shell_span_x, shell_span_y) * 0.035, 6_000.0)
        pad_x = 1_500.0
        pad_y = 1_200.0
        min_x = shell_bbox["min_x"]
        max_x = shell_bbox["max_x"]
        min_y = shell_bbox["min_y"]
        max_y = shell_bbox["max_y"]
        points: list[dict[str, float]]
        if cut_side == "right":
            cut_x = max(min_x + connector, min(dock_bbox["min_x"] - pad_x, max_x - connector))
            cut_y1 = max(min_y + connector, dock_bbox["min_y"] - pad_y)
            cut_y2 = min(max_y - connector, dock_bbox["max_y"] + pad_y)
            if cut_y2 - cut_y1 < 5_000.0 or max_x - cut_x < 12_000.0:
                return False
            points = [
                {"x": min_x, "y": min_y},
                {"x": max_x, "y": min_y},
                {"x": max_x, "y": cut_y1},
                {"x": cut_x, "y": cut_y1},
                {"x": cut_x, "y": cut_y2},
                {"x": max_x, "y": cut_y2},
                {"x": max_x, "y": max_y},
                {"x": min_x, "y": max_y},
            ]
        elif cut_side == "left":
            cut_x = min(max_x - connector, max(dock_bbox["max_x"] + pad_x, min_x + connector))
            cut_y1 = max(min_y + connector, dock_bbox["min_y"] - pad_y)
            cut_y2 = min(max_y - connector, dock_bbox["max_y"] + pad_y)
            if cut_y2 - cut_y1 < 5_000.0 or cut_x - min_x < 12_000.0:
                return False
            points = [
                {"x": min_x, "y": min_y},
                {"x": max_x, "y": min_y},
                {"x": max_x, "y": max_y},
                {"x": min_x, "y": max_y},
                {"x": min_x, "y": cut_y2},
                {"x": cut_x, "y": cut_y2},
                {"x": cut_x, "y": cut_y1},
                {"x": min_x, "y": cut_y1},
            ]
        elif cut_side == "bottom":
            cut_y = min(max_y - connector, max(dock_bbox["max_y"] + pad_y, min_y + connector))
            cut_x1 = max(min_x + connector, dock_bbox["min_x"] - pad_x)
            cut_x2 = min(max_x - connector, dock_bbox["max_x"] + pad_x)
            if cut_x2 - cut_x1 < 12_000.0 or cut_y - min_y < 12_000.0:
                return False
            points = [
                {"x": min_x, "y": min_y},
                {"x": cut_x1, "y": min_y},
                {"x": cut_x1, "y": cut_y},
                {"x": cut_x2, "y": cut_y},
                {"x": cut_x2, "y": min_y},
                {"x": max_x, "y": min_y},
                {"x": max_x, "y": max_y},
                {"x": min_x, "y": max_y},
            ]
        else:
            cut_y = max(min_y + connector, min(dock_bbox["min_y"] - pad_y, max_y - connector))
            cut_x1 = max(min_x + connector, dock_bbox["min_x"] - pad_x)
            cut_x2 = min(max_x - connector, dock_bbox["max_x"] + pad_x)
            if cut_x2 - cut_x1 < 12_000.0 or max_y - cut_y < 12_000.0:
                return False
            points = [
                {"x": min_x, "y": min_y},
                {"x": max_x, "y": min_y},
                {"x": max_x, "y": max_y},
                {"x": cut_x2, "y": max_y},
                {"x": cut_x2, "y": cut_y},
                {"x": cut_x1, "y": cut_y},
                {"x": cut_x1, "y": max_y},
                {"x": min_x, "y": max_y},
            ]

        shell["geometry"] = {**shell.get("geometry", {}), "type": "Polygon", "closed": True, "points": points}
        attrs = shell.setdefault("attributes", {})
        attrs["solid_wall_cut_for_internal_dock"] = True
        attrs.setdefault("original_shell_bbox", {key: round(float(value), 3) for key, value in original_shell_bbox.items()})
        attrs["internal_dock_cutout"] = {
            "rule": "kw21_106_internal_tail_dock_notch",
            "side": cut_side,
            "support_count": len(internal_spaces),
            "dock_bbox": {key: round(float(value), 3) for key, value in dock_bbox.items()},
            "shell_bbox_before_cut": {key: round(float(value), 3) for key, value in shell_bbox.items()},
        }
        attrs["source"] = (
            f"{attrs.get('source', '')}；KW21-106 为中间凹区车尾枪机，"
            "其车位/车辆所在带状区域从外墙实体中裁出，不再按矩形外包络生成穿越凹区的墙"
        )
        return True

    def _infer_tail_dock_objects(
        self,
        devices: list[dict[str, Any]],
        structures: list[dict[str, Any]] | None = None,
        office_model: dict[str, Any] | None = None,
        shell_area: dict[str, Any] | None = None,
        entities: list[dict[str, Any]] | None = None,
    ) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
        rear_cameras = sorted(
            [device for device in devices if device.get("type") == "security.camera.rear" and device.get("geometry", {}).get("position")],
            key=lambda item: self._rear_camera_number(str(item.get("label", ""))),
        )
        if not rear_cameras:
            return [], []

        templates = self._vehicle_template_sequence(len(rear_cameras))
        light_standard = self.standards.get("lighting", {}).get("tail_floodlight", {})
        dock_standard = self.standards.get("dock", {})
        tail_gap_mm = float(dock_standard.get("camera_to_vehicle_tail_gap_m", 5.0)) * 1000.0
        wall_clearance_mm = float(dock_standard.get("vehicle_wall_clearance_m", 0.6)) * 1000.0
        vehicle_ground_elevation_m = float(self.standards.get("site", {}).get("yard_ground_elevation_m", 0.0))
        dock_deck_height_m = float(self.standards.get("site", {}).get("dock_height_m", DOCK_HEIGHT_M))
        parking_guides = self._parking_guide_points(structures or [])
        self._orient_rear_cameras_by_dock_layout(rear_cameras, shell_area)
        dock_walls = self._dock_wall_x_by_side(rear_cameras, structures or [], shell_area)
        cad_parking_spaces, cad_paired_camera_ids = self._parking_spaces_from_cad_groups(
            rear_cameras,
            entities or [],
            shell_area,
            vehicle_ground_elevation_m,
            dock_deck_height_m,
        )
        layer_parking_spaces = self._parking_spaces_from_parking_layer_structures(
            structures or [],
            shell_area,
            vehicle_ground_elevation_m,
            dock_deck_height_m,
        )
        authoritative_layer_parking = (
            len(layer_parking_spaces) >= 12
            and len(layer_parking_spaces) >= max(len(cad_parking_spaces) + 8, int(len(cad_parking_spaces) * 1.5))
        )
        parking_spaces: list[dict[str, Any]] = []
        fixtures: list[dict[str, Any]] = []
        for index, (camera, template) in enumerate(zip(rear_cameras, templates), start=1):
            pos = camera["geometry"]["position"]
            camera_key = str(camera.get("id") or camera.get("source_entity_id") or "")
            template = self._vehicle_template_for_camera(camera, template, office_model)
            camera_tail_gap_mm = self._tail_gap_for_camera(camera, tail_gap_mm)
            camera_tail_gap_source = self._tail_gap_source_for_camera(camera)
            angle = float(camera.get("orientation", {}).get("angle_deg", 0.0) or 0.0)
            direction_hint = None
            orientation_source = str(camera.get("attributes", {}).get("orientation_source") or "")
            if orientation_source != "dock_layout_cluster" and not orientation_source.startswith("cad_camera_symbol"):
                direction_hint = self._infer_rear_camera_direction_from_parking(camera, parking_guides, template, camera_tail_gap_mm)
            if direction_hint:
                angle = float(direction_hint["angle_deg"])
                camera.setdefault("orientation", {})["angle_deg"] = angle
                camera_attributes = camera.setdefault("attributes", {})
                camera_attributes["orientation_source"] = direction_hint["source"]
                camera_attributes["orientation_confidence"] = direction_hint["confidence"]
                camera_attributes["orientation_support_points"] = direction_hint["support_points"]
            direction = self._direction_from_angle(angle)
            width_mm = float(template["width_m"]) * 1000.0
            length_mm = float(template["length_m"]) * 1000.0
            raw_tail = {"x": pos["x"] + direction["x"] * camera_tail_gap_mm, "y": pos["y"] + direction["y"] * camera_tail_gap_mm}
            tail, wall_adjustment = self._adjust_vehicle_tail_for_wall(raw_tail, pos, direction, dock_walls, wall_clearance_mm)
            tail, wall_adjustment = self._limit_vehicle_wall_adjustment(
                raw_tail,
                tail,
                pos,
                wall_adjustment,
                camera_tail_gap_mm,
                camera,
            )
            actual_tail_gap_mm = self._distance(pos, tail)
            center = {
                "x": tail["x"] + direction["x"] * (length_mm / 2.0),
                "y": tail["y"] + direction["y"] * (length_mm / 2.0),
            }
            polygon = self._oriented_rect(center, direction, length_mm, width_mm)
            camera_label = str(camera.get("label", f"CW-{index:02d}"))
            if camera_key not in cad_paired_camera_ids:
                parking_spaces.append(
                    {
                        "id": f"parking_{camera_label.replace('-', '_')}",
                        "type": "parking.truck_bay",
                        "label": f"{camera_label} 车位",
                        "confidence": 0.76,
                        "geometry": {"type": "Polygon", "closed": True, "points": polygon},
                        "orientation": {"angle_deg": angle},
                        "attributes": {
                            "source_kind": "tail_camera_inferred",
                            "paired_camera_id": camera.get("id"),
                            "paired_camera_label": camera_label,
                            "vehicle_type": template["id"],
                            "vehicle_template_id": template["id"],
                            "vehicle_label": template["label"],
                            "vehicle_length_m": template["length_m"],
                            "vehicle_width_m": template["width_m"],
                            "vehicle_height_m": template["height_m"],
                            "vehicle_source_rule": template.get("source_rule", "legend_ratio"),
                            "standard_camera_to_tail_gap_m": camera_tail_gap_mm / 1000.0,
                            "camera_to_tail_gap_m": round(actual_tail_gap_mm / 1000.0, 3),
                            "camera_to_tail_gap_source": camera_tail_gap_source,
                            "tail_position": tail,
                            "dock_wall_avoidance": wall_adjustment,
                            "vehicle_ground_elevation_m": vehicle_ground_elevation_m,
                            "dock_deck_height_m": dock_deck_height_m,
                            "head_direction": "outward",
                            "tail_faces": "warehouse",
                            "source": "施工工艺图：车尾摄像头/射灯与车辆尾部间距；未匹配到 CAD 车位块时回退推断",
                        },
                    }
                )

            if camera_key in cad_paired_camera_ids:
                continue

            fixtures.append(
                {
                    "id": f"fixture_tail_{camera_label.replace('-', '_')}",
                    "type": "lighting.floodlight",
                    "label": f"{light_standard.get('label_prefix', 'SL')}-{camera_label}",
                    "source_entity_id": camera.get("source_entity_id"),
                    "original_layer": "车尾射灯标准",
                    "confidence": 0.80,
                    "geometry": {"type": "Point", "position": {"x": float(pos["x"]), "y": float(pos["y"])}},
                    "orientation": {"angle_deg": angle},
                    "attributes": {
                        "source_kind": "tail_camera_pair_inferred",
                        "paired_camera_id": camera.get("id"),
                        "paired_camera_label": camera_label,
                        "shared_mount_with_camera": True,
                        "mount_position_source": "paired_camera_position",
                        "mount_offset_m": 0.0,
                        "install_height_m": float(light_standard.get("install_height_m", 3.0)),
                        "beam_length_m": float(light_standard.get("beam_length_m", 7.5)),
                        "beam_angle_deg": float(light_standard.get("beam_angle_deg", 36)),
                        "purpose": light_standard.get("purpose", "车尾摄像头补光"),
                    },
                }
            )
        fixtures.extend(self._fixtures_from_cad_parking_spaces(cad_parking_spaces, light_standard))
        if authoritative_layer_parking:
            self._record_suppressed_inference(
                "partial_cad_parking_blocks",
                len(cad_parking_spaces),
                "停车位图层提供了更完整的车位阵列，局部 CAD 车位块仅作为摄像头/射灯配对证据，不再决定车辆数量",
            )
            return [*layer_parking_spaces, *parking_spaces], fixtures
        return [*cad_parking_spaces, *layer_parking_spaces, *parking_spaces], fixtures

    def _suppress_unanchored_tail_dock_inferences(
        self,
        parking_spaces: list[dict[str, Any]],
        fixtures: list[dict[str, Any]],
    ) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
        if not self._is_no_main_plan_mode():
            return parking_spaces, fixtures
        cad_spaces = [
            space
            for space in parking_spaces
            if (space.get("attributes") or {}).get("source_kind") == "cad_parking_block"
        ]
        inferred_spaces = [
            space
            for space in parking_spaces
            if (space.get("attributes") or {}).get("source_kind") == "tail_camera_inferred"
        ]
        if not inferred_spaces:
            return parking_spaces, fixtures
        if cad_spaces and len(parking_spaces) >= max(len(cad_spaces) * 1.5, len(cad_spaces) + 8):
            reliable_cad_spaces = [
                space
                for space in cad_spaces
                if self._is_rear_camera_label(str((space.get("attributes") or {}).get("paired_camera_label") or ""))
            ]
            dropped_cad_ids = {str(space.get("id") or "") for space in cad_spaces if space not in reliable_cad_spaces}
            if dropped_cad_ids:
                parking_spaces = [space for space in parking_spaces if str(space.get("id") or "") not in dropped_cad_ids]
                fixtures = [
                    fixture
                    for fixture in fixtures
                    if str((fixture.get("attributes") or {}).get("paired_parking_id") or "") not in dropped_cad_ids
                ]
                self._record_suppressed_inference(
                    "unpaired_cad_parking_blocks",
                    len(dropped_cad_ids),
                    "无主平面模式下仅保留能绑定车尾摄像头编号的 CAD 车位块，未绑定编号的局部车位块作为参考而不生成车位/射灯",
                )
            self._record_suppressed_inference(
                "partial_cad_parking_blocks",
                len(cad_spaces),
                "无主平面模式下 CAD 车位块只覆盖局部月台，保留 CAD 车位与其余车尾摄像头推断车位，避免把完整车尾清单缩减为局部 CAD 车位",
            )
            return parking_spaces, fixtures
        filtered_fixtures = [
            fixture
            for fixture in fixtures
            if (fixture.get("attributes") or {}).get("source_kind") != "tail_camera_pair_inferred"
        ]
        self._record_suppressed_inference(
            "tail_camera_dock_fallback",
            len(inferred_spaces),
            "无可靠主平面/CAD车位块时不把车尾摄像头工艺说明扩展成真实车位、车辆、射灯和月台地面",
        )
        return cad_spaces, filtered_fixtures

    def _is_no_main_plan_mode(self) -> bool:
        return bool(self.base_view and self.base_view.get("no_main_plan_mode"))

    def _system_views_are_title_fallback_only(self) -> bool:
        system_frames = [frame for frame in self.frames if frame.get("kind") == "system_view"]
        return bool(system_frames) and all(str(frame.get("source") or "") == "title_anchor_fallback" for frame in system_frames)

    def _system_view_alignment_allows_cable_inference(self, required_kind: str) -> bool:
        if not self._is_no_main_plan_mode():
            return True
        base = self.base_view or {}
        base_bounds = base.get("bounds") if isinstance(base.get("bounds"), dict) else None
        if base.get("kind") == required_kind and base_bounds:
            return True
        if self._system_views_are_title_fallback_only():
            return any(
                str(view.get("kind") or "") == required_kind and isinstance(view.get("bounds"), dict)
                for view in self.system_views
            )
        if base.get("kind") != "monitor" or not base_bounds:
            return False
        required_view = next(
            (
                view
                for view in self.system_views
                if str(view.get("kind") or "") == required_kind and isinstance(view.get("bounds"), dict)
            ),
            None,
        )
        if not required_view:
            return False
        view_bounds = required_view["bounds"]
        base_width = max(float(base_bounds.get("max_x", 0.0)) - float(base_bounds.get("min_x", 0.0)), 1.0)
        base_height = max(float(base_bounds.get("max_y", 0.0)) - float(base_bounds.get("min_y", 0.0)), 1.0)
        view_width = max(float(view_bounds.get("max_x", 0.0)) - float(view_bounds.get("min_x", 0.0)), 1.0)
        view_height = max(float(view_bounds.get("max_y", 0.0)) - float(view_bounds.get("min_y", 0.0)), 1.0)
        width_ratio = abs(view_width - base_width) / base_width
        height_ratio = abs(view_height - base_height) / base_height
        if width_ratio > 0.05 or height_ratio > 0.05:
            return False
        return required_view.get("base_origin") is not None and required_view.get("origin") is not None

    def _record_suppressed_inference(self, kind: str, count: int, reason: str) -> None:
        if count <= 0:
            return
        for item in self.suppressed_inferences:
            if item.get("kind") == kind and item.get("reason") == reason:
                item["count"] = int(item.get("count", 0) or 0) + count
                return
        self.suppressed_inferences.append({"kind": kind, "count": count, "reason": reason})

    def _fixtures_from_cad_parking_spaces(
        self,
        spaces: list[dict[str, Any]],
        light_standard: dict[str, Any],
    ) -> list[dict[str, Any]]:
        fixtures: list[dict[str, Any]] = []
        for index, space in enumerate(spaces, start=1):
            attrs = space.get("attributes") or {}
            if attrs.get("source_kind") != "cad_parking_block":
                continue
            bbox = self._points_bbox(space.get("geometry", {}).get("points") or [])
            paired_camera_position = attrs.get("paired_camera_position") if attrs.get("paired_camera_id") else None
            mount_position = paired_camera_position or attrs.get("tail_position") or (self._bbox_center(bbox) if bbox else None)
            if not mount_position:
                continue
            angle = float(space.get("orientation", {}).get("angle_deg", 0.0) or 0.0)
            if paired_camera_position:
                mount_position = paired_camera_position
            mount_position_source = "paired_camera_position" if paired_camera_position else "tail_position"
            fixtures.append(
                {
                    "id": f"fixture_cad_parking_{index:03d}",
                    "type": "lighting.floodlight",
                    "label": f"{light_standard.get('label_prefix', 'SL')}-CAD-{index:03d}",
                    "source_entity_id": attrs.get("source_entity_id"),
                    "original_layer": attrs.get("source_layer") or "CAD车位射灯",
                    "confidence": 0.78,
                    "geometry": {"type": "Point", "position": {"x": float(mount_position["x"]), "y": float(mount_position["y"])}},
                    "orientation": {"angle_deg": angle},
                    "attributes": {
                        "source_kind": "cad_parking_tail_spotlight_inferred",
                        "paired_parking_id": space.get("id"),
                        "paired_parking_label": space.get("label"),
                        "paired_camera_id": attrs.get("paired_camera_id"),
                        "paired_camera_label": attrs.get("paired_camera_label"),
                        "shared_mount_with_camera": bool(attrs.get("paired_camera_id")),
                        "mount_position_source": mount_position_source,
                        "mount_offset_m": 0.0,
                        "install_height_m": float(light_standard.get("install_height_m", 3.0)),
                        "beam_length_m": float(light_standard.get("beam_length_m", 7.5)),
                        "beam_angle_deg": float(light_standard.get("beam_angle_deg", 36)),
                        "purpose": light_standard.get("purpose", "车尾摄像头补光"),
                        "source": (
                            "CAD 车位已配对车尾监控时，射灯与车尾枪机落在同一安装直线上"
                            if paired_camera_position
                            else "CAD 车位块已读出但未配到车尾监控，按车尾月台位置回退生成射灯"
                        ),
                    },
                }
            )
        return fixtures

    @staticmethod
    def _tail_gap_for_camera(camera: dict[str, Any], default_gap_mm: float) -> float:
        attrs = camera.get("attributes") or {}
        source = str(attrs.get("tail_camera_to_vehicle_gap_source") or "")
        if source not in {"cad_camera_symbol_block_name", "cad_local_dimension", "cad_text_note"}:
            return default_gap_mm
        try:
            gap_m = float(attrs.get("tail_camera_to_vehicle_gap_m"))
        except (TypeError, ValueError):
            return default_gap_mm
        if 1.0 <= gap_m <= 12.0:
            return gap_m * 1000.0
        return default_gap_mm

    @staticmethod
    def _tail_gap_source_for_camera(camera: dict[str, Any]) -> str:
        source = str((camera.get("attributes") or {}).get("tail_camera_to_vehicle_gap_source") or "")
        if source in {"cad_camera_symbol_block_name", "cad_local_dimension", "cad_text_note"}:
            return source
        return "company_standard"

    def _apply_project_rear_camera_tail_gap_rule(self, camera: dict[str, Any], lane: dict[str, Any]) -> float | None:
        rule = self._project_rear_camera_tail_gap_rule(str(camera.get("label") or ""), float(lane.get("angle_deg", 0.0) or 0.0))
        if not rule:
            return None
        prefix, start, end, _angle, gap_mm = rule
        attrs = camera.setdefault("attributes", {})
        previous_gap = attrs.get("tail_camera_to_vehicle_gap_m")
        previous_source = attrs.get("tail_camera_to_vehicle_gap_source")
        if previous_gap is not None and previous_source:
            attrs.setdefault("tail_camera_to_vehicle_gap_note_m", previous_gap)
            attrs.setdefault("tail_camera_to_vehicle_gap_note_source", previous_source)
        attrs["tail_camera_to_vehicle_gap_m"] = round(gap_mm / 1000.0, 3)
        attrs["tail_camera_to_vehicle_gap_source"] = "cad_local_dimension"
        attrs["tail_camera_to_vehicle_gap_rule"] = "project_rear_camera_row_dimension"
        attrs["tail_camera_to_vehicle_gap_rule_evidence"] = (
            f"项目图纸车尾安装距离：{prefix}-{start:02d}~{prefix}-{end:02d} "
            f"{gap_mm / 1000.0:g}m"
        )
        return gap_mm

    def _project_rear_camera_tail_gap_rule(self, label: str, lane_angle: float) -> tuple[str, int, int, float, float] | None:
        if not self._is_project_specific_context():
            return None
        normalized_label = re.sub(r"\s+", "", str(label or "").upper())
        normalized_angle = float(lane_angle or 0.0) % 360.0
        for prefix, start, end, angle, gap_mm in PROJECT_REAR_CAMERA_TAIL_GAP_RULES:
            number = self._camera_label_number(normalized_label, prefix)
            if number is None or not (start <= number <= end):
                continue
            if self._angular_distance(normalized_angle, angle) <= 12.0:
                return prefix, start, end, angle, gap_mm
        return None

    def _apply_project_rear_camera_tail_gap_to_parking_spaces(
        self,
        parking_spaces: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        if not parking_spaces or not self._is_project_specific_context():
            return parking_spaces
        for space in parking_spaces:
            attrs = space.get("attributes") or {}
            label = str(attrs.get("paired_camera_label") or space.get("label") or "")
            angle = float(space.get("orientation", {}).get("angle_deg", 0.0) or 0.0)
            rule = self._project_rear_camera_tail_gap_rule(label, angle)
            camera_position = attrs.get("paired_camera_position")
            old_tail = attrs.get("tail_position")
            points = space.get("geometry", {}).get("points") or []
            if not rule or not camera_position or not old_tail or not points:
                continue
            prefix, start, end, _angle, gap_mm = rule
            direction = self._direction_from_angle(angle)
            new_tail = {
                "x": float(camera_position["x"]) + direction["x"] * gap_mm,
                "y": float(camera_position["y"]) + direction["y"] * gap_mm,
            }
            delta = {
                "x": new_tail["x"] - float(old_tail["x"]),
                "y": new_tail["y"] - float(old_tail["y"]),
            }
            if abs(delta["x"]) < 0.001 and abs(delta["y"]) < 0.001:
                attrs["standard_camera_to_tail_gap_m"] = round(gap_mm / 1000.0, 3)
                attrs["camera_to_tail_gap_source"] = "cad_local_dimension"
                continue
            space["geometry"]["points"] = [
                {"x": float(point["x"]) + delta["x"], "y": float(point["y"]) + delta["y"]}
                for point in points
                if "x" in point and "y" in point
            ]
            attrs.setdefault("cad_tail_position_before_gap_rule", old_tail)
            attrs.setdefault("cad_camera_to_tail_gap_before_rule_m", attrs.get("camera_to_tail_gap_m"))
            attrs["tail_position"] = new_tail
            attrs["camera_to_tail_gap_m"] = round(gap_mm / 1000.0, 3)
            attrs["standard_camera_to_tail_gap_m"] = round(gap_mm / 1000.0, 3)
            attrs["camera_to_tail_gap_source"] = "cad_local_dimension"
            attrs["vehicle_position_adjustment_source"] = "project_rear_camera_row_dimension"
            attrs["vehicle_position_adjustment_evidence"] = (
                f"项目图纸车尾安装距离：{prefix}-{start:02d}~{prefix}-{end:02d} "
                f"{gap_mm / 1000.0:g}m，车辆模型跟随车位几何整体平移"
            )
        return parking_spaces

    @staticmethod
    def _is_project_specific_context() -> bool:
        return os.environ.get("CAD_ENABLE_PROJECT_SPECIFIC_RULES", "").strip().lower() in {"1", "true", "yes"}

    def _rebuild_cad_parking_lane_from_tail(
        self,
        lane: dict[str, Any],
        tail_position: dict[str, float],
    ) -> None:
        direction = self._direction_from_angle(float(lane.get("angle_deg", 0.0) or 0.0))
        length_mm = float(lane.get("length_mm") or 0.0)
        width_mm = float(lane.get("width_mm") or 0.0)
        if length_mm <= 0.0 or width_mm <= 0.0:
            return
        center = {
            "x": float(tail_position["x"]) + direction["x"] * (length_mm / 2.0),
            "y": float(tail_position["y"]) + direction["y"] * (length_mm / 2.0),
        }
        lane["tail_position"] = {"x": float(tail_position["x"]), "y": float(tail_position["y"])}
        lane["center"] = center
        lane["points"] = self._oriented_rect(center, direction, length_mm, width_mm)

    def _parking_spaces_from_cad_groups(
        self,
        rear_cameras: list[dict[str, Any]],
        entities: list[dict[str, Any]],
        shell_area: dict[str, Any] | None,
        vehicle_ground_elevation_m: float,
        dock_deck_height_m: float,
    ) -> tuple[list[dict[str, Any]], set[str]]:
        groups = self._cad_parking_group_candidates(entities, shell_area)
        if not groups:
            return [], set()

        lanes: list[dict[str, Any]] = []
        for group in groups:
            lanes.extend(self._split_cad_parking_group(group, shell_area))
        if not lanes:
            return [], set()

        paired = self._pair_cad_parking_lanes(lanes, rear_cameras)
        paired_camera_ids = {
            str(match["camera"].get("id") or match["camera"].get("source_entity_id") or "")
            for match in paired.values()
            if match.get("camera")
        }
        self._snap_paired_rear_cameras_to_cad_parking_mount_lines(lanes, paired)
        spaces: list[dict[str, Any]] = []
        for index, lane in enumerate(lanes, start=1):
            match = paired.get(lane["id"])
            camera = match.get("camera") if match else None
            camera_label = str(camera.get("label")) if camera else f"CAD-{index:02d}"
            cad_length_m = round(float(lane["length_mm"]) / 1000.0, 3)
            cad_width_m = round(float(lane["width_mm"]) / 1000.0, 3)
            template = self._vehicle_template_for_cad_parking_lane(lane)
            attrs: dict[str, Any] = {
                "source_kind": "cad_parking_block",
                "source_entity_id": lane["source_entity_id"],
                "source_layer": lane["source_layer"],
                "source_block_name": lane["source_block_name"],
                "lane_index": lane["lane_index"],
                "lane_count": lane["lane_count"],
                "vehicle_type": template["id"],
                "vehicle_template_id": template["id"],
                "vehicle_label": template["label"],
                "vehicle_length_m": template["length_m"],
                "vehicle_width_m": template["width_m"],
                "vehicle_height_m": template["height_m"],
                "vehicle_source_rule": template.get("source_rule", "cad_parking_block_vehicle_normalized"),
                "cad_parking_bbox_length_m": cad_length_m,
                "cad_parking_bbox_width_m": cad_width_m,
                "vehicle_ground_elevation_m": vehicle_ground_elevation_m,
                "dock_deck_height_m": dock_deck_height_m,
                "head_direction": "outward",
                "tail_faces": "warehouse",
                "tail_position": lane["tail_position"],
                "source_shape_entity_id": lane.get("source_shape_entity_id"),
                "split_rule": lane.get("split_rule", "cad_group_width_fallback"),
                "source": (
                    "CAD 匿名车位块内部独立长车位轮廓读取，按块内真实车位数量生成"
                    if lane.get("split_rule") == "cad_inner_lane_geometry"
                    else "CAD 匿名车位块内部车位图层读取，未找到独立长车位轮廓时按组宽兜底拆分"
                ),
            }
            if camera:
                camera_position = camera.get("geometry", {}).get("position") or {}
                camera.setdefault("orientation", {})["angle_deg"] = float(lane["angle_deg"])
                camera_attrs = camera.setdefault("attributes", {})
                camera_attrs["orientation_source"] = "paired_cad_parking_lane"
                camera_attrs["orientation_confidence"] = 0.92
                camera_attrs["orientation_support"] = lane["id"]
                self._apply_project_rear_camera_tail_gap_rule(camera, lane)
                camera_tail_gap_mm = self._tail_gap_for_camera(camera, float(match["distance_mm"]))
                camera_tail_gap_source = self._tail_gap_source_for_camera(camera)
                previous_tail = dict(lane["tail_position"])
                previous_gap_mm = float(match["distance_mm"])
                if "x" in camera_position and "y" in camera_position:
                    direction = self._direction_from_angle(float(lane["angle_deg"]))
                    corrected_tail = {
                        "x": float(camera_position["x"]) + direction["x"] * camera_tail_gap_mm,
                        "y": float(camera_position["y"]) + direction["y"] * camera_tail_gap_mm,
                    }
                    self._rebuild_cad_parking_lane_from_tail(lane, corrected_tail)
                    match["distance_mm"] = self._distance(camera_position, lane["tail_position"])
                    attrs["tail_position"] = lane["tail_position"]
                    attrs["cad_tail_position_before_gap_rule"] = previous_tail
                    attrs["cad_camera_to_tail_gap_before_rule_m"] = round(previous_gap_mm / 1000.0, 3)
                attrs.update(
                    {
                        "paired_camera_id": camera.get("id"),
                        "paired_camera_label": camera.get("label"),
                        "paired_camera_position": {
                            "x": float(camera_position["x"]),
                            "y": float(camera_position["y"]),
                        } if "x" in camera_position and "y" in camera_position else None,
                        "camera_to_tail_gap_m": round(float(match["distance_mm"]) / 1000.0, 3),
                        "standard_camera_to_tail_gap_m": round(camera_tail_gap_mm / 1000.0, 3),
                        "camera_to_tail_gap_source": camera_tail_gap_source,
                    }
                )
            spaces.append(
                {
                    "id": f"parking_cad_{lane['source_entity_id']}_{lane['lane_index']}",
                    "type": "parking.truck_bay",
                    "label": f"{camera_label} 车位",
                    "confidence": 0.92 if camera else 0.84,
                    "geometry": {"type": "Polygon", "closed": True, "points": lane["points"]},
                    "orientation": {"angle_deg": lane["angle_deg"]},
                    "attributes": attrs,
                }
            )
        return spaces, paired_camera_ids

    def _parking_spaces_from_parking_layer_structures(
        self,
        structures: list[dict[str, Any]],
        shell_area: dict[str, Any] | None,
        vehicle_ground_elevation_m: float,
        dock_deck_height_m: float,
    ) -> list[dict[str, Any]]:
        shell_bbox = self._points_bbox(shell_area.get("geometry", {}).get("points") or []) if shell_area else None
        if not shell_bbox:
            return []
        lines: list[dict[str, Any]] = []
        pad = 40_000.0
        for structure in structures:
            layer = str(structure.get("layer") or "")
            if not self._is_parking_layer(layer):
                continue
            points = structure.get("geometry", {}).get("points") or []
            if len(points) != 2:
                continue
            p1, p2 = points
            try:
                x0 = min(float(p1["x"]), float(p2["x"]))
                x1 = max(float(p1["x"]), float(p2["x"]))
                y0 = min(float(p1["y"]), float(p2["y"]))
                y1 = max(float(p1["y"]), float(p2["y"]))
            except (TypeError, ValueError, KeyError):
                continue
            center = {"x": (x0 + x1) / 2.0, "y": (y0 + y1) / 2.0}
            if not self._point_in_bbox(center, shell_bbox, pad):
                continue
            lines.append(
                {
                    "x0": x0,
                    "x1": x1,
                    "y0": y0,
                    "y1": y1,
                    "dx": x1 - x0,
                    "dy": y1 - y0,
                    "layer": layer,
                    "source_entity_id": structure.get("source_entity_id"),
                }
            )
        if not lines:
            return []

        tolerance = 180.0
        long_vertical = [line for line in lines if line["dx"] <= 80.0 and 10_000.0 <= line["dy"] <= 25_000.0]
        long_horizontal = [line for line in lines if line["dy"] <= 80.0 and 10_000.0 <= line["dx"] <= 25_000.0]
        short_vertical = [line for line in lines if line["dx"] <= 80.0 and 1_800.0 <= line["dy"] <= 6_500.0]
        short_horizontal = [line for line in lines if line["dy"] <= 80.0 and 1_800.0 <= line["dx"] <= 6_500.0]

        def has_short_horizontal(x0: float, x1: float, y: float) -> bool:
            return any(
                abs(line["y0"] - y) <= tolerance
                and abs(line["x0"] - x0) <= tolerance
                and abs(line["x1"] - x1) <= tolerance
                for line in short_horizontal
            )

        def has_short_vertical(x: float, y0: float, y1: float) -> bool:
            return any(
                abs(line["x0"] - x) <= tolerance
                and abs(line["y0"] - y0) <= tolerance
                and abs(line["y1"] - y1) <= tolerance
                for line in short_vertical
            )

        lanes: list[dict[str, Any]] = []
        seen: set[tuple[int, int, int, int]] = set()

        def add_lane(x0: float, y0: float, x1: float, y1: float, source_ids: list[Any], source_layer: str, split_on_x: bool) -> None:
            key = (round(x0 / 250.0), round(y0 / 250.0), round(x1 / 250.0), round(y1 / 250.0))
            if key in seen:
                return
            seen.add(key)
            center = {"x": (x0 + x1) / 2.0, "y": (y0 + y1) / 2.0}
            group = {
                "center_x": center["x"],
                "center_y": center["y"],
                "shell_center_x": (shell_bbox["min_x"] + shell_bbox["max_x"]) / 2.0,
                "shell_center_y": (shell_bbox["min_y"] + shell_bbox["max_y"]) / 2.0,
            }
            angle = self._cad_parking_group_angle(group, split_on_x, shell_area)
            direction = self._direction_from_angle(angle)
            length_mm = (y1 - y0) if split_on_x else (x1 - x0)
            width_mm = (x1 - x0) if split_on_x else (y1 - y0)
            lanes.append(
                {
                    "source_entity_id": "+".join(str(item) for item in source_ids if item),
                    "source_layer": source_layer,
                    "lane_index": 0,
                    "lane_count": 0,
                    "points": [
                        {"x": x0, "y": y0},
                        {"x": x1, "y": y0},
                        {"x": x1, "y": y1},
                        {"x": x0, "y": y1},
                    ],
                    "center": center,
                    "tail_position": {
                        "x": center["x"] - direction["x"] * (length_mm / 2.0),
                        "y": center["y"] - direction["y"] * (length_mm / 2.0),
                    },
                    "length_mm": length_mm,
                    "width_mm": width_mm,
                    "angle_deg": angle,
                }
            )

        for index, first in enumerate(long_vertical):
            for second in long_vertical[index + 1:]:
                if abs(first["y0"] - second["y0"]) > tolerance or abs(first["y1"] - second["y1"]) > tolerance:
                    continue
                x0, x1 = sorted([first["x0"], second["x0"]])
                if not 1_800.0 <= x1 - x0 <= 6_500.0:
                    continue
                if not (has_short_horizontal(x0, x1, first["y0"]) and has_short_horizontal(x0, x1, first["y1"])):
                    continue
                add_lane(
                    x0,
                    (first["y0"] + second["y0"]) / 2.0,
                    x1,
                    (first["y1"] + second["y1"]) / 2.0,
                    [first.get("source_entity_id"), second.get("source_entity_id")],
                    first.get("layer") or second.get("layer") or "PARK-停车位",
                    True,
                )

        for index, first in enumerate(long_horizontal):
            for second in long_horizontal[index + 1:]:
                if abs(first["x0"] - second["x0"]) > tolerance or abs(first["x1"] - second["x1"]) > tolerance:
                    continue
                y0, y1 = sorted([first["y0"], second["y0"]])
                if not 1_800.0 <= y1 - y0 <= 6_500.0:
                    continue
                if not (has_short_vertical(first["x0"], y0, y1) and has_short_vertical(first["x1"], y0, y1)):
                    continue
                add_lane(
                    (first["x0"] + second["x0"]) / 2.0,
                    y0,
                    (first["x1"] + second["x1"]) / 2.0,
                    y1,
                    [first.get("source_entity_id"), second.get("source_entity_id")],
                    first.get("layer") or second.get("layer") or "PARK-停车位",
                    False,
                )

        if not lanes:
            return []
        lanes.sort(key=lambda lane: (round(float(lane["angle_deg"]) % 360.0), lane["center"]["y"], lane["center"]["x"]))
        spaces: list[dict[str, Any]] = []
        for index, lane in enumerate(lanes, start=1):
            lane["lane_index"] = index
            lane["lane_count"] = len(lanes)
            template = self._vehicle_template_for_cad_parking_lane(lane)
            spaces.append(
                {
                    "id": f"parking_layer_{index:03d}",
                    "type": "parking.truck_bay",
                    "label": f"车位-{index:02d}",
                    "confidence": 0.88,
                    "geometry": {"type": "Polygon", "closed": True, "points": lane["points"]},
                    "orientation": {"angle_deg": lane["angle_deg"]},
                    "attributes": {
                        "source_kind": "parking_layer_linework",
                        "source_entity_id": lane["source_entity_id"],
                        "source_layer": lane["source_layer"],
                        "lane_index": index,
                        "lane_count": len(lanes),
                        "vehicle_type": template["id"],
                        "vehicle_template_id": template["id"],
                        "vehicle_label": template["label"],
                        "vehicle_length_m": template["length_m"],
                        "vehicle_width_m": template["width_m"],
                        "vehicle_height_m": template["height_m"],
                        "vehicle_source_rule": "parking_layer_linework_vehicle_normalized",
                        "cad_parking_bbox_length_m": round(float(lane["length_mm"]) / 1000.0, 3),
                        "cad_parking_bbox_width_m": round(float(lane["width_mm"]) / 1000.0, 3),
                        "vehicle_ground_elevation_m": vehicle_ground_elevation_m,
                        "dock_deck_height_m": dock_deck_height_m,
                        "head_direction": "outward",
                        "tail_faces": "warehouse",
                        "tail_position": lane["tail_position"],
                        "source": "停车位图层矩形线框识别，按真实车位线生成车辆模型",
                    },
                }
            )
        return spaces

    def _vehicle_template_for_cad_parking_lane(self, lane: dict[str, Any]) -> dict[str, Any]:
        length_m = float(lane.get("length_mm") or 0.0) / 1000.0
        template = self._vehicle_template_by_id("semi_trailer_17_5") or self._vehicle_template_by_id("container_61ft")
        if length_m < 16.0:
            template = self._vehicle_template_by_id("box_9_6") or template
        if not template:
            template = {
                "id": "container_61ft",
                "label": "61尺 集卡",
                "length_m": 18.6,
                "width_m": 2.5,
                "height_m": 4.1,
            }
        template = dict(template)
        template["source_rule"] = "cad_parking_block_vehicle_normalized"
        return template

    def _orient_bullet_cameras_by_cad_parking(self, devices: list[dict[str, Any]], parking_spaces: list[dict[str, Any]]) -> None:
        cad_spaces = [
            space
            for space in parking_spaces
            if (space.get("attributes") or {}).get("source_kind") == "cad_parking_block"
            and space.get("geometry", {}).get("points")
        ]
        if not cad_spaces:
            return
        row_specs: list[dict[str, Any]] = []
        for angle in (0.0, 180.0):
            row_spaces = [
                space for space in cad_spaces
                if abs(float(space.get("orientation", {}).get("angle_deg", 0.0) or 0.0) - angle) <= 1.0
            ]
            if not row_spaces:
                continue
            xs: list[float] = []
            tail_ys: list[float] = []
            for space in row_spaces:
                for point in space.get("geometry", {}).get("points") or []:
                    xs.append(float(point["x"]))
                tail = (space.get("attributes") or {}).get("tail_position")
                if tail:
                    tail_ys.append(float(tail["y"]))
            if not xs or not tail_ys:
                continue
            row_specs.append(
                {
                    "angle": angle,
                    "min_x": min(xs) - 4500.0,
                    "max_x": max(xs) + 4500.0,
                    "tail_y": self._median(tail_ys),
                }
            )
        if not row_specs:
            return
        for device in devices:
            if device.get("type") != "security.camera.bullet":
                continue
            label = str(device.get("label") or "").upper()
            if label.startswith(("CD-", "WW-")):
                continue
            attrs = device.get("attributes") or {}
            orientation_source = str(attrs.get("orientation_source") or "")
            if orientation_source.startswith("cad_camera_symbol") or orientation_source.startswith("cad_cd_wall_camera"):
                continue
            pos = device.get("geometry", {}).get("position") or {}
            if not pos:
                continue
            x = float(pos["x"])
            y = float(pos["y"])
            for spec in row_specs:
                if spec["min_x"] <= x <= spec["max_x"] and abs(y - spec["tail_y"]) <= 6000.0:
                    device.setdefault("orientation", {})["angle_deg"] = spec["angle"]
                    attrs = device.setdefault("attributes", {})
                    attrs["orientation_source"] = "cad_parking_dock_edge_row"
                    attrs["orientation_confidence"] = 0.9
                    attrs["orientation_support"] = "matched_top_bottom_cad_parking_tail_row"
                    break

    def _cad_parking_group_candidates(
        self,
        entities: list[dict[str, Any]],
        shell_area: dict[str, Any] | None,
    ) -> list[dict[str, Any]]:
        shell = self._shell_wall_by_side(shell_area)
        base_bounds = self.base_view.get("bounds") if isinstance(self.base_view, dict) else None
        shell_center_x = (shell["left"] + shell["right"]) / 2.0 if shell else (
            (float(base_bounds["min_x"]) + float(base_bounds["max_x"])) / 2.0 if base_bounds else 0.0
        )
        shell_center_y = (shell["bottom"] + shell["top"]) / 2.0 if shell else (
            (float(base_bounds["min_y"]) + float(base_bounds["max_y"])) / 2.0 if base_bounds else 0.0
        )
        candidates: list[dict[str, Any]] = []
        seen: set[tuple[int, int, int, int]] = set()
        canonical_kind = self._canonical_system_view_kind() if self.system_views else None
        for entity in entities:
            parent_layer = str(entity.get("layer") or "").upper()
            if any(token in parent_layer for token in ("DIM", "ANNO", "AXIS")):
                continue
            shapes = [
                shape
                for shape in (entity.get("cad_virtual_shapes") or [])
                if shape.get("cad_role") == "parking_space"
            ]
            if not shapes:
                continue
            anchor = self._geometry_anchor(entity.get("geometry") or {})
            fold = self._fold_offset_for_point(anchor) if anchor else None
            if not anchor or (not self._is_model_point(anchor) and not fold):
                continue
            if canonical_kind and fold and fold.get("system_view") and fold.get("system_view") != canonical_kind:
                continue
            points: list[dict[str, float]] = []
            shape_lanes: list[dict[str, Any]] = []
            for shape in shapes:
                folded_geometry, _fold = self._fold_geometry(shape.get("geometry") or {})
                shape_points = self._geometry_points(folded_geometry)
                points.extend(shape_points)
                lane_bbox = self._points_bbox(shape_points)
                if not lane_bbox:
                    continue
                lane_width = lane_bbox["max_x"] - lane_bbox["min_x"]
                lane_height = lane_bbox["max_y"] - lane_bbox["min_y"]
                lane_long_dim = max(lane_width, lane_height)
                lane_short_dim = min(lane_width, lane_height)
                if 12_000.0 <= lane_long_dim <= 18_500.0 and 2_400.0 <= lane_short_dim <= 4_800.0:
                    shape_lanes.append(
                        {
                            "source_entity_id": shape.get("source_entity_id") or entity.get("source_entity_id"),
                            "source_layer": shape.get("layer"),
                            "bbox": lane_bbox,
                            "center_x": (lane_bbox["min_x"] + lane_bbox["max_x"]) / 2.0,
                            "center_y": (lane_bbox["min_y"] + lane_bbox["max_y"]) / 2.0,
                            "length_mm": lane_long_dim,
                            "width_mm": lane_short_dim,
                            "long_axis": "y" if lane_height >= lane_width else "x",
                        }
                    )
            bbox = self._points_bbox(points)
            if not bbox:
                continue
            width = bbox["max_x"] - bbox["min_x"]
            height = bbox["max_y"] - bbox["min_y"]
            long_dim = max(width, height)
            short_dim = min(width, height)
            is_single_vehicle_bay = 10_000.0 <= long_dim <= 35_000.0 and 2_000.0 <= short_dim <= 5_500.0
            is_multi_lane_group = 12_000.0 <= long_dim <= 18_500.0 and 6_000.0 <= short_dim <= 9_500.0
            if not (shape_lanes or is_single_vehicle_bay or is_multi_lane_group):
                continue
            center_x = (bbox["min_x"] + bbox["max_x"]) / 2.0
            center_y = (bbox["min_y"] + bbox["max_y"]) / 2.0
            if shell and not (
                shell["left"] - 30_000.0 <= center_x <= shell["right"] + 30_000.0
                and shell["bottom"] - 30_000.0 <= center_y <= shell["top"] + 30_000.0
            ):
                continue
            key = (round(bbox["min_x"] / 500.0), round(bbox["min_y"] / 500.0), round(bbox["max_x"] / 500.0), round(bbox["max_y"] / 500.0))
            if key in seen:
                continue
            seen.add(key)
            candidates.append(
                {
                    "source_entity_id": entity.get("source_entity_id"),
                    "source_layer": entity.get("layer"),
                    "source_block_name": entity.get("block_name"),
                    "bbox": bbox,
                    "center_x": center_x,
                    "center_y": center_y,
                    "shell_center_x": shell_center_x,
                    "shell_center_y": shell_center_y,
                    "shape_lanes": shape_lanes,
                }
            )
        return sorted(candidates, key=lambda item: (item["center_y"], item["center_x"]))

    @staticmethod
    def _geometry_points(geometry: dict[str, Any]) -> list[dict[str, float]]:
        if not geometry:
            return []
        if geometry.get("points"):
            return [{"x": float(point["x"]), "y": float(point["y"])} for point in geometry.get("points") or [] if point.get("x") is not None and point.get("y") is not None]
        if geometry.get("position"):
            point = geometry["position"]
            return [{"x": float(point["x"]), "y": float(point["y"])}]
        if geometry.get("center"):
            center = geometry["center"]
            radius = float(geometry.get("radius") or geometry.get("radius_major") or 0.0)
            return [
                {"x": float(center["x"]) - radius, "y": float(center["y"]) - radius},
                {"x": float(center["x"]) + radius, "y": float(center["y"]) + radius},
            ]
        return []

    def _split_cad_parking_group(self, group: dict[str, Any], shell_area: dict[str, Any] | None) -> list[dict[str, Any]]:
        shape_lanes = group.get("shape_lanes") or []
        if shape_lanes:
            return self._cad_parking_lanes_from_shape_lanes(group, shape_lanes, shell_area)

        bbox = group["bbox"]
        width = bbox["max_x"] - bbox["min_x"]
        height = bbox["max_y"] - bbox["min_y"]
        split_on_x = height >= width
        short_dim = width if split_on_x else height
        long_dim = max(width, height)
        is_single_vehicle_bay = 10_000.0 <= long_dim <= 35_000.0 and 2_000.0 <= short_dim <= 5_500.0
        lane_count = 1 if is_single_vehicle_bay else max(1, min(6, round(short_dim / 2600.0)))
        lane_width = short_dim / lane_count
        angle = self._cad_parking_group_angle(group, split_on_x, shell_area)
        direction = self._direction_from_angle(angle)
        lanes: list[dict[str, Any]] = []
        for lane_index in range(lane_count):
            if split_on_x:
                x0 = bbox["min_x"] + lane_width * lane_index
                x1 = bbox["min_x"] + lane_width * (lane_index + 1)
                y0 = bbox["min_y"]
                y1 = bbox["max_y"]
            else:
                x0 = bbox["min_x"]
                x1 = bbox["max_x"]
                y0 = bbox["min_y"] + lane_width * lane_index
                y1 = bbox["min_y"] + lane_width * (lane_index + 1)
            points = [
                {"x": x0, "y": y0},
                {"x": x1, "y": y0},
                {"x": x1, "y": y1},
                {"x": x0, "y": y1},
            ]
            center = {"x": (x0 + x1) / 2.0, "y": (y0 + y1) / 2.0}
            length_mm = height if split_on_x else width
            width_mm = lane_width
            tail_position = {
                "x": center["x"] - direction["x"] * (length_mm / 2.0),
                "y": center["y"] - direction["y"] * (length_mm / 2.0),
            }
            lanes.append(
                {
                    "id": f"{group['source_entity_id']}:{lane_index + 1}",
                    "source_entity_id": group["source_entity_id"],
                    "source_layer": group.get("source_layer"),
                    "source_block_name": group.get("source_block_name"),
                    "lane_index": lane_index + 1,
                    "lane_count": lane_count,
                    "points": points,
                    "center": center,
                    "tail_position": tail_position,
                    "length_mm": length_mm,
                    "width_mm": width_mm,
                    "angle_deg": angle,
                }
            )
        return lanes

    def _cad_parking_lanes_from_shape_lanes(
        self,
        group: dict[str, Any],
        shape_lanes: list[dict[str, Any]],
        shell_area: dict[str, Any] | None,
    ) -> list[dict[str, Any]]:
        first = shape_lanes[0]
        split_on_x = first.get("long_axis") == "y"
        ordered = sorted(shape_lanes, key=lambda item: (item["center_x"], item["center_y"]) if split_on_x else (item["center_y"], item["center_x"]))
        lane_count = len(ordered)
        lanes: list[dict[str, Any]] = []
        for lane_index, lane_shape in enumerate(ordered, start=1):
            bbox = lane_shape["bbox"]
            width = bbox["max_x"] - bbox["min_x"]
            height = bbox["max_y"] - bbox["min_y"]
            split_on_x = height >= width
            angle = self._cad_parking_group_angle(
                {
                    **group,
                    "center_x": lane_shape["center_x"],
                    "center_y": lane_shape["center_y"],
                },
                split_on_x,
                shell_area,
            )
            direction = self._direction_from_angle(angle)
            points = [
                {"x": bbox["min_x"], "y": bbox["min_y"]},
                {"x": bbox["max_x"], "y": bbox["min_y"]},
                {"x": bbox["max_x"], "y": bbox["max_y"]},
                {"x": bbox["min_x"], "y": bbox["max_y"]},
            ]
            center = {"x": lane_shape["center_x"], "y": lane_shape["center_y"]}
            length_mm = max(width, height)
            width_mm = min(width, height)
            tail_position = {
                "x": center["x"] - direction["x"] * (length_mm / 2.0),
                "y": center["y"] - direction["y"] * (length_mm / 2.0),
            }
            lanes.append(
                {
                    "id": f"{group['source_entity_id']}:{lane_index}",
                    "source_entity_id": group["source_entity_id"],
                    "source_layer": lane_shape.get("source_layer") or group.get("source_layer"),
                    "source_block_name": group.get("source_block_name"),
                    "source_shape_entity_id": lane_shape.get("source_entity_id"),
                    "lane_index": lane_index,
                    "lane_count": lane_count,
                    "points": points,
                    "center": center,
                    "tail_position": tail_position,
                    "length_mm": length_mm,
                    "width_mm": width_mm,
                    "angle_deg": angle,
                    "split_rule": "cad_inner_lane_geometry",
                }
            )
        return lanes

    def _cad_parking_group_angle(self, group: dict[str, Any], split_on_x: bool, shell_area: dict[str, Any] | None) -> float:
        shell = self._shell_wall_by_side(shell_area)
        center_x = group["center_x"]
        center_y = group["center_y"]
        shell_center_x = (shell["left"] + shell["right"]) / 2.0 if shell else group.get("shell_center_x", center_x)
        shell_center_y = (shell["bottom"] + shell["top"]) / 2.0 if shell else group.get("shell_center_y", center_y)
        if split_on_x:
            return 180.0 if center_y >= shell_center_y else 0.0
        return 90.0 if center_x >= shell_center_x else 270.0

    def _snap_paired_rear_cameras_to_cad_parking_mount_lines(
        self,
        lanes: list[dict[str, Any]],
        paired: dict[str, dict[str, Any]],
    ) -> None:
        rows: defaultdict[float, list[dict[str, Any]]] = defaultdict(list)
        for lane in lanes:
            match = paired.get(str(lane.get("id") or ""))
            camera = match.get("camera") if match else None
            pos = camera.get("geometry", {}).get("position") if camera else None
            tail = lane.get("tail_position")
            if not pos or not tail:
                continue
            angle = round(float(lane.get("angle_deg", 0.0) or 0.0) % 360.0, 1)
            direction = self._direction_from_angle(angle)
            dx = float(pos["x"]) - float(tail["x"])
            dy = float(pos["y"]) - float(tail["y"])
            gap_mm = -(dx * direction["x"] + dy * direction["y"])
            if 1_000.0 <= gap_mm <= 9_000.0:
                rows[angle].append({"lane": lane, "match": match, "gap_mm": gap_mm})

        for angle, row in rows.items():
            if len(row) < 4:
                continue
            gap_mm = self._dominant_mount_line_gap([item["gap_mm"] for item in row])
            if gap_mm <= 0.0:
                continue
            direction = self._direction_from_angle(angle)
            perp = {"x": -direction["y"], "y": direction["x"]}
            proposed: list[dict[str, Any]] = []
            for item in row:
                lane = item["lane"]
                match = item["match"]
                camera = match.get("camera")
                if not camera:
                    continue
                pos = camera.get("geometry", {}).get("position") or {}
                tail = lane.get("tail_position") or {}
                if not pos or not tail:
                    continue
                dx = float(pos["x"]) - float(tail["x"])
                dy = float(pos["y"]) - float(tail["y"])
                lateral_mm = 0.0
                snapped = {
                    "x": float(tail["x"]) - direction["x"] * gap_mm + perp["x"] * lateral_mm,
                    "y": float(tail["y"]) - direction["y"] * gap_mm + perp["y"] * lateral_mm,
                }
                proposed.append({"camera": camera, "match": match, "tail": tail, "pos": pos, "snapped": snapped, "lateral_mm": lateral_mm})
            if not proposed:
                continue
            if angle in {0.0, 180.0}:
                mount_axis = self._dominant_axis_value([item["snapped"]["y"] for item in proposed], bucket_mm=500.0)
                for item in proposed:
                    item["snapped"]["y"] = mount_axis
            elif angle in {90.0, 270.0}:
                mount_axis = self._dominant_axis_value([item["snapped"]["x"] for item in proposed], bucket_mm=500.0)
                for item in proposed:
                    item["snapped"]["x"] = mount_axis
            for item in proposed:
                camera = item["camera"]
                match = item["match"]
                pos = item["pos"]
                tail = item["tail"]
                snapped = item["snapped"]
                lateral_mm = item["lateral_mm"]
                moved_mm = self._distance(pos, snapped)
                if moved_mm <= 1.0:
                    continue
                camera["geometry"] = {**camera.get("geometry", {}), "type": "Point", "position": snapped}
                attrs = camera.setdefault("attributes", {})
                attrs.setdefault("position_before_mount_line_snap", {"x": float(pos["x"]), "y": float(pos["y"])})
                attrs["position_source"] = "cad_parking_tail_mount_line"
                attrs["position_adjustment_source"] = "cad_parking_tail_mount_line"
                attrs["cad_mount_line_gap_m"] = round(gap_mm / 1000.0, 3)
                attrs["cad_mount_line_lateral_offset_m"] = round(lateral_mm / 1000.0, 3)
                attrs["position_adjustment_m"] = round(moved_mm / 1000.0, 3)
                attrs["orientation_target"] = self._target_from_angle(snapped, float(camera.get("orientation", {}).get("angle_deg", angle) or angle))
                match["distance_mm"] = self._distance(snapped, tail)

    @staticmethod
    def _dominant_mount_line_gap(values: list[float]) -> float:
        valid = [float(value) for value in values if 1_000.0 <= float(value) <= 9_000.0]
        if not valid:
            return 0.0
        buckets: defaultdict[float, list[float]] = defaultdict(list)
        for value in valid:
            buckets[round(value / 500.0) * 500.0].append(value)
        top_count = max(len(items) for items in buckets.values())
        top_buckets = [bucket for bucket, items in buckets.items() if len(items) == top_count]
        bucket = max(top_buckets)
        return sum(buckets[bucket]) / len(buckets[bucket])

    def _pair_cad_parking_lanes(
        self,
        lanes: list[dict[str, Any]],
        rear_cameras: list[dict[str, Any]],
    ) -> dict[str, dict[str, Any]]:
        unused = [camera for camera in rear_cameras if camera.get("geometry", {}).get("position")]
        paired: dict[str, dict[str, Any]] = {}
        for lane in sorted(lanes, key=lambda item: (item["tail_position"]["y"], item["tail_position"]["x"])):
            tail = lane["tail_position"]
            angle = float(lane["angle_deg"])
            direction = self._direction_from_angle(angle)
            perp = {"x": -direction["y"], "y": direction["x"]}
            best: tuple[float, dict[str, Any], float] | None = None
            for camera in unused:
                pos = camera["geometry"]["position"]
                dx = tail["x"] - pos["x"]
                dy = tail["y"] - pos["y"]
                along = dx * direction["x"] + dy * direction["y"]
                lateral = abs(dx * perp["x"] + dy * perp["y"])
                distance = (dx * dx + dy * dy) ** 0.5
                if along < -1500.0 or along > 14_000.0:
                    continue
                if lateral > max(float(lane["width_mm"]) * 0.95, 1800.0):
                    continue
                score = distance + lateral * 1.5
                if best is None or score < best[0]:
                    best = (score, camera, distance)
            if best:
                _score, camera, distance = best
                paired[lane["id"]] = {"camera": camera, "distance_mm": distance}
                unused = [item for item in unused if item is not camera]
        remaining_lanes = [lane for lane in lanes if lane["id"] not in paired]
        for lane in sorted(remaining_lanes, key=lambda item: (item["tail_position"]["y"], item["tail_position"]["x"])):
            tail = lane["tail_position"]
            best: tuple[float, dict[str, Any], float] | None = None
            for camera in unused:
                label = str(camera.get("label") or "")
                if not self._is_rear_camera_label(label):
                    continue
                pos = camera["geometry"]["position"]
                dx = tail["x"] - pos["x"]
                dy = tail["y"] - pos["y"]
                distance = (dx * dx + dy * dy) ** 0.5
                if distance > 15_000.0 or abs(dx) > 12_000.0 or abs(dy) > 9_000.0:
                    continue
                score = distance + abs(dy) * 0.35
                if best is None or score < best[0]:
                    best = (score, camera, distance)
            if best:
                _score, camera, distance = best
                paired[lane["id"]] = {"camera": camera, "distance_mm": distance}
                unused = [item for item in unused if item is not camera]
        return paired

    def _orient_rear_cameras_by_dock_layout(
        self,
        rear_cameras: list[dict[str, Any]],
        shell_area: dict[str, Any] | None,
    ) -> None:
        if not rear_cameras:
            return
        shell_walls = self._shell_wall_by_side(shell_area)
        if not shell_walls:
            return
        center_x = (shell_walls["left"] + shell_walls["right"]) / 2.0
        center_y = (shell_walls["bottom"] + shell_walls["top"]) / 2.0
        assigned: set[str] = set()
        self._orient_cw_side_camera_rows(rear_cameras, assigned, shell_walls, center_x)
        rear_cameras = [
            device
            for device in rear_cameras
            if str(device.get("id") or device.get("source_entity_id")) in assigned
            or not str(device.get("attributes", {}).get("orientation_source") or "").startswith("cad_camera_symbol")
        ]
        if not rear_cameras:
            return
        self._orient_kw_rear_camera_rows(rear_cameras, assigned)

        vertical_clusters: list[dict[str, Any]] = []
        for cluster in self._cluster_devices_by_axis(rear_cameras, "x", tolerance_mm=3400.0):
            cluster = [device for device in cluster if str(device.get("id") or device.get("source_entity_id")) not in assigned]
            if len(cluster) < 4:
                continue
            positions = [device["geometry"]["position"] for device in cluster]
            span_y = max(point["y"] for point in positions) - min(point["y"] for point in positions)
            if len(cluster) < 4 or span_y < 10_000.0:
                continue
            avg_x = sum(point["x"] for point in positions) / len(positions)
            vertical_clusters.append({"cluster": cluster, "avg_x": avg_x, "span_y": span_y})
        vertical_clusters.sort(key=lambda item: item["avg_x"])
        split_index = len(vertical_clusters) / 2.0
        for cluster_index, cluster_info in enumerate(vertical_clusters):
            avg_x = float(cluster_info["avg_x"])
            if len(vertical_clusters) >= 2:
                angle = 270.0 if cluster_index < split_index else 90.0
            else:
                angle = 270.0 if avg_x < center_x else 90.0
            cluster = cluster_info["cluster"]
            for device in cluster:
                self._set_rear_camera_orientation(device, angle, "dock_layout_cluster", len(cluster))
                assigned.add(str(device.get("id") or device.get("source_entity_id")))

        for cluster in self._cluster_devices_by_axis(rear_cameras, "y", tolerance_mm=3600.0):
            unassigned = [device for device in cluster if str(device.get("id") or device.get("source_entity_id")) not in assigned]
            if len(unassigned) < 4:
                continue
            positions = [device["geometry"]["position"] for device in unassigned]
            span_x = max(point["x"] for point in positions) - min(point["x"] for point in positions)
            if span_x < 10_000.0:
                continue
            avg_y = sum(point["y"] for point in positions) / len(positions)
            angle = 180.0 if avg_y >= center_y else 0.0
            for device in unassigned:
                self._set_rear_camera_orientation(device, angle, "dock_layout_cluster", len(unassigned))
                assigned.add(str(device.get("id") or device.get("source_entity_id")))

        for device in rear_cameras:
            key = str(device.get("id") or device.get("source_entity_id"))
            if key in assigned:
                continue
            pos = device.get("geometry", {}).get("position")
            if not pos:
                continue
            distances = {
                270.0: abs(pos["x"] - shell_walls["left"]),
                90.0: abs(pos["x"] - shell_walls["right"]),
                0.0: abs(pos["y"] - shell_walls["bottom"]),
                180.0: abs(pos["y"] - shell_walls["top"]),
            }
            angle = min(distances, key=distances.get)
            if distances[angle] <= 35_000.0:
                self._set_rear_camera_orientation(device, angle, "dock_layout_nearest_wall", 1)

    def _orient_cw_side_camera_rows(
        self,
        rear_cameras: list[dict[str, Any]],
        assigned: set[str],
        shell_walls: dict[str, float],
        center_x: float,
    ) -> None:
        cw_cameras: list[dict[str, Any]] = []
        for device in rear_cameras:
            label = str(device.get("label") or "")
            if self._camera_label_number(label, "CW") is None:
                continue
            if not device.get("geometry", {}).get("position"):
                continue
            cw_cameras.append(device)
        if len(cw_cameras) < 8:
            return

        for cluster in self._cluster_devices_by_axis(cw_cameras, "x", tolerance_mm=3400.0):
            positions = [device["geometry"]["position"] for device in cluster]
            span_y = max(point["y"] for point in positions) - min(point["y"] for point in positions)
            if len(cluster) < 5 or span_y < 18_000.0:
                continue
            avg_x = sum(point["x"] for point in positions) / len(positions)
            nearest_wall_distance = min(abs(avg_x - shell_walls["left"]), abs(avg_x - shell_walls["right"]))
            if nearest_wall_distance > 12_000.0:
                continue
            angle = 270.0 if avg_x <= center_x else 90.0
            mount_x = self._dominant_axis_value([float(point["x"]) for point in positions], bucket_mm=500.0)
            for device in cluster:
                key = str(device.get("id") or device.get("source_entity_id"))
                self._set_rear_camera_orientation(device, angle, "cw_side_dock_row", len(cluster))
                pos = device.get("geometry", {}).get("position") or {}
                if mount_x and pos and abs(float(pos["x"]) - mount_x) > 1.0:
                    original = {"x": float(pos["x"]), "y": float(pos["y"])}
                    snapped = {"x": mount_x, "y": float(pos["y"])}
                    device["geometry"] = {**device.get("geometry", {}), "type": "Point", "position": snapped}
                    attrs = device.setdefault("attributes", {})
                    attrs.setdefault("position_before_mount_line_snap", original)
                    attrs["position_source"] = "cw_side_dock_mount_line"
                    attrs["position_adjustment_source"] = "cw_side_dock_mount_line"
                    attrs["position_adjustment_m"] = round(self._distance(original, snapped) / 1000.0, 3)
                assigned.add(key)

    def _orient_kw_rear_camera_rows(self, rear_cameras: list[dict[str, Any]], assigned: set[str]) -> None:
        kw_cameras: list[dict[str, Any]] = []
        for device in rear_cameras:
            label = str(device.get("label") or "")
            number = self._camera_label_number(label, "KW")
            if number is None or not (21 <= number <= 106):
                continue
            if str((device.get("attributes") or {}).get("orientation_source") or "").startswith("cad_camera_symbol"):
                continue
            kw_cameras.append(device)
        if len(kw_cameras) < 8:
            return

        row_clusters: list[dict[str, Any]] = []
        for cluster in self._cluster_devices_by_axis(kw_cameras, "y", tolerance_mm=3600.0):
            positions = [device["geometry"]["position"] for device in cluster]
            span_x = max(point["x"] for point in positions) - min(point["x"] for point in positions)
            if len(cluster) < 4 or span_x < 10_000.0:
                continue
            avg_y = sum(point["y"] for point in positions) / len(positions)
            row_clusters.append({"cluster": cluster, "avg_y": avg_y, "span_x": span_x})
        if len(row_clusters) < 2:
            return

        row_clusters.sort(key=lambda item: float(item["avg_y"]), reverse=True)
        for row_index, row in enumerate(row_clusters):
            angle = 0.0 if row_index % 2 == 0 else 180.0
            cluster = row["cluster"]
            for device in cluster:
                self._set_rear_camera_orientation(device, angle, "kw_dock_row_pair", len(cluster))
                assigned.add(str(device.get("id") or device.get("source_entity_id")))

    @staticmethod
    def _cluster_devices_by_axis(devices: list[dict[str, Any]], axis: str, tolerance_mm: float) -> list[list[dict[str, Any]]]:
        positioned = [device for device in devices if device.get("geometry", {}).get("position")]
        positioned.sort(key=lambda device: float(device["geometry"]["position"][axis]))
        clusters: list[list[dict[str, Any]]] = []
        current: list[dict[str, Any]] = []
        current_value: float | None = None
        for device in positioned:
            value = float(device["geometry"]["position"][axis])
            if current_value is None or abs(value - current_value) <= tolerance_mm:
                current.append(device)
                current_value = sum(float(item["geometry"]["position"][axis]) for item in current) / len(current)
                continue
            clusters.append(current)
            current = [device]
            current_value = value
        if current:
            clusters.append(current)
        return clusters

    @staticmethod
    def _set_rear_camera_orientation(device: dict[str, Any], angle: float, source: str, support_points: int) -> None:
        device.setdefault("orientation", {})["angle_deg"] = angle
        attrs = device.setdefault("attributes", {})
        attrs["orientation_source"] = source
        attrs["orientation_confidence"] = 0.9 if source in {"dock_layout_cluster", "cw_side_dock_row", "kw_dock_row_pair"} else 0.78
        attrs["orientation_support_points"] = support_points

    @staticmethod
    def _dominant_axis_value(values: list[float], bucket_mm: float = 500.0) -> float:
        valid = [float(value) for value in values]
        if not valid:
            return 0.0
        buckets: defaultdict[float, list[float]] = defaultdict(list)
        for value in valid:
            buckets[round(value / bucket_mm) * bucket_mm].append(value)
        top_count = max(len(items) for items in buckets.values())
        top_buckets = [bucket for bucket, items in buckets.items() if len(items) == top_count]
        bucket = max(top_buckets)
        return sum(buckets[bucket]) / len(buckets[bucket])

    @staticmethod
    def _is_parking_layer(layer: str) -> bool:
        normalized = str(layer).upper()
        return any(keyword.upper() in normalized for keyword in PARKING_LAYER_KEYWORDS)

    def _parking_guide_points(self, structures: list[dict[str, Any]]) -> list[dict[str, Any]]:
        guides: list[dict[str, Any]] = []
        seen: set[tuple[int, int]] = set()
        for structure in structures:
            layer = str(structure.get("original_layer") or structure.get("layer") or "")
            if not self._is_parking_layer(layer):
                continue
            points = structure.get("geometry", {}).get("points") or []
            if len(points) < 2:
                continue
            source_entity_id = structure.get("source_entity_id")

            def add_point(point: dict[str, Any]) -> None:
                if point.get("x") is None or point.get("y") is None:
                    return
                x = float(point["x"])
                y = float(point["y"])
                key = (round(x / 250.0), round(y / 250.0))
                if key in seen:
                    return
                seen.add(key)
                guides.append({"x": x, "y": y, "layer": layer, "source_entity_id": source_entity_id})

            for point in points:
                add_point(point)
            for start, end in zip(points, points[1:]):
                if start.get("x") is None or start.get("y") is None or end.get("x") is None or end.get("y") is None:
                    continue
                add_point({"x": (float(start["x"]) + float(end["x"])) / 2.0, "y": (float(start["y"]) + float(end["y"])) / 2.0})
        return guides

    def _infer_rear_camera_direction_from_parking(
        self,
        camera: dict[str, Any],
        guide_points: list[dict[str, Any]],
        template: dict[str, Any],
        tail_gap_mm: float,
    ) -> dict[str, Any] | None:
        pos = camera.get("geometry", {}).get("position")
        if not pos or not guide_points:
            return None
        vehicle_width_mm = float(template.get("width_m", 2.5)) * 1000.0
        vehicle_length_mm = float(template.get("length_m", 9.6)) * 1000.0
        lateral_limit = max(3200.0, vehicle_width_mm * 1.45)
        min_along = 1000.0
        max_along = max(45000.0, tail_gap_mm + vehicle_length_mm + 15000.0)
        candidates: list[dict[str, Any]] = []
        for angle in (0.0, 90.0, 180.0, 270.0):
            direction = self._direction_from_angle(angle)
            perp = {"x": -direction["y"], "y": direction["x"]}
            hits: list[dict[str, float]] = []
            for guide in guide_points:
                dx = float(guide["x"]) - float(pos["x"])
                dy = float(guide["y"]) - float(pos["y"])
                along = dx * direction["x"] + dy * direction["y"]
                if along < min_along or along > max_along:
                    continue
                lateral = abs(dx * perp["x"] + dy * perp["y"])
                if lateral > lateral_limit:
                    continue
                hits.append({"along": along, "lateral": lateral})
            if not hits:
                continue
            nearest = min(hits, key=lambda item: (item["lateral"], item["along"]))
            score = len(hits) * 1000.0 - nearest["lateral"] * 0.35 - nearest["along"] * 0.02
            candidates.append(
                {
                    "angle_deg": angle,
                    "hit_count": len(hits),
                    "nearest_along": nearest["along"],
                    "nearest_lateral": nearest["lateral"],
                    "score": score,
                }
            )
        if not candidates:
            return None
        best = max(candidates, key=lambda item: item["score"])
        if best["hit_count"] < 2:
            return None
        confidence = 0.86 if best["nearest_lateral"] <= vehicle_width_mm else 0.78
        return {
            "angle_deg": best["angle_deg"],
            "confidence": confidence,
            "support_points": best["hit_count"],
            "source": "cad_parking_layer_direction",
        }

    def _dock_wall_x_by_side(
        self,
        rear_cameras: list[dict[str, Any]],
        structures: list[dict[str, Any]],
        shell_area: dict[str, Any] | None = None,
    ) -> dict[str, float]:
        side_cameras: dict[str, list[dict[str, float]]] = {"left": [], "right": []}
        shell_walls = self._shell_wall_by_side(shell_area)
        for camera in rear_cameras:
            pos = camera.get("geometry", {}).get("position")
            if not pos:
                continue
            direction = self._direction_from_angle(float(camera.get("orientation", {}).get("angle_deg", 0.0) or 0.0))
            if direction["x"] < -0.5:
                side_cameras["left"].append(pos)
            elif direction["x"] > 0.5:
                side_cameras["right"].append(pos)

        walls: dict[str, float] = {}
        for side, cameras in side_cameras.items():
            if not cameras:
                continue
            camera_x = sum(point["x"] for point in cameras) / len(cameras)
            min_y = min(point["y"] for point in cameras) - 8000.0
            max_y = max(point["y"] for point in cameras) + 8000.0
            candidates: dict[int, dict[str, float]] = {}
            for structure in structures:
                if structure.get("type") not in {"building.wall", "building.platform"}:
                    continue
                points = structure.get("geometry", {}).get("points") or []
                for start, end in zip(points, points[1:]):
                    dx = abs(float(start["x"]) - float(end["x"]))
                    dy = abs(float(start["y"]) - float(end["y"]))
                    if dx > 150.0 or dy < 4000.0:
                        continue
                    seg_min_y = min(float(start["y"]), float(end["y"]))
                    seg_max_y = max(float(start["y"]), float(end["y"]))
                    if seg_max_y < min_y or seg_min_y > max_y:
                        continue
                    x = (float(start["x"]) + float(end["x"])) / 2.0
                    if side == "left" and x >= camera_x:
                        continue
                    if side == "right" and x <= camera_x:
                        continue
                    bucket = round(x / 500.0)
                    stat = candidates.setdefault(bucket, {"x_sum": 0.0, "length": 0.0, "count": 0.0})
                    stat["x_sum"] += x * dy
                    stat["length"] += dy
                    stat["count"] += 1.0
            if not candidates:
                if side in shell_walls:
                    walls[side] = shell_walls[side]
                continue
            best = max(candidates.values(), key=lambda item: (item["length"], item["count"]))
            if best["length"] > 0:
                detected_wall = best["x_sum"] / best["length"]
                if side in shell_walls and abs(detected_wall - shell_walls[side]) > 15_000.0:
                    walls[side] = shell_walls[side]
                    continue
                if side == "left" and side in shell_walls:
                    walls[side] = min(detected_wall, shell_walls[side])
                elif side == "right" and side in shell_walls:
                    walls[side] = max(detected_wall, shell_walls[side])
                else:
                    walls[side] = detected_wall
        for side, wall_x in shell_walls.items():
            walls.setdefault(side, wall_x)
        return walls

    @staticmethod
    def _shell_wall_x_by_side(shell_area: dict[str, Any] | None) -> dict[str, float]:
        walls = RuleEngine._shell_wall_by_side(shell_area)
        return {side: walls[side] for side in ("left", "right") if side in walls}

    @staticmethod
    def _shell_wall_by_side(shell_area: dict[str, Any] | None) -> dict[str, float]:
        points = shell_area.get("geometry", {}).get("points") if shell_area else None
        if not points:
            return {}
        xs = [float(point["x"]) for point in points if point.get("x") is not None]
        ys = [float(point["y"]) for point in points if point.get("y") is not None]
        if not xs or not ys:
            return {}
        return {"left": min(xs), "right": max(xs), "bottom": min(ys), "top": max(ys)}

    @staticmethod
    def _adjust_vehicle_tail_for_wall(
        tail: dict[str, float],
        camera_pos: dict[str, float],
        direction: dict[str, float],
        dock_walls: dict[str, float],
        clearance_mm: float,
    ) -> tuple[dict[str, float], dict[str, Any]]:
        adjusted_tail = dict(tail)
        adjustment: dict[str, Any] = {"adjusted": False}
        if direction["x"] > 0.5 and "right" in dock_walls:
            wall_x = dock_walls["right"]
            min_tail_x = wall_x + clearance_mm
            if adjusted_tail["x"] < min_tail_x:
                adjusted_tail["x"] = min_tail_x
                adjustment = {
                    "adjusted": True,
                    "side": "right",
                    "wall_x": wall_x,
                    "clearance_m": clearance_mm / 1000.0,
                    "reason": "vehicle_tail_outside_warehouse_wall",
                }
        elif direction["x"] < -0.5 and "left" in dock_walls:
            wall_x = dock_walls["left"]
            max_tail_x = wall_x - clearance_mm
            if adjusted_tail["x"] > max_tail_x:
                adjusted_tail["x"] = max_tail_x
                adjustment = {
                    "adjusted": True,
                    "side": "left",
                    "wall_x": wall_x,
                    "clearance_m": clearance_mm / 1000.0,
                    "reason": "vehicle_tail_outside_warehouse_wall",
                }
        elif direction["y"] > 0.5 and "top" in dock_walls:
            wall_y = dock_walls["top"]
            min_tail_y = wall_y + clearance_mm
            if adjusted_tail["y"] < min_tail_y:
                adjusted_tail["y"] = min_tail_y
                adjustment = {
                    "adjusted": True,
                    "side": "top",
                    "wall_y": wall_y,
                    "clearance_m": clearance_mm / 1000.0,
                    "reason": "vehicle_tail_outside_warehouse_wall",
                }
        elif direction["y"] < -0.5 and "bottom" in dock_walls:
            wall_y = dock_walls["bottom"]
            max_tail_y = wall_y - clearance_mm
            if adjusted_tail["y"] > max_tail_y:
                adjusted_tail["y"] = max_tail_y
                adjustment = {
                    "adjusted": True,
                    "side": "bottom",
                    "wall_y": wall_y,
                    "clearance_m": clearance_mm / 1000.0,
                    "reason": "vehicle_tail_outside_warehouse_wall",
                }
        if adjustment.get("adjusted"):
            adjustment["camera_to_tail_gap_m"] = round(RuleEngine._distance(camera_pos, adjusted_tail) / 1000.0, 3)
        return adjusted_tail, adjustment

    @staticmethod
    def _limit_vehicle_wall_adjustment(
        raw_tail: dict[str, float],
        adjusted_tail: dict[str, float],
        camera_pos: dict[str, float],
        adjustment: dict[str, Any],
        standard_tail_gap_mm: float,
        camera: dict[str, Any],
    ) -> tuple[dict[str, float], dict[str, Any]]:
        if not adjustment.get("adjusted"):
            return adjusted_tail, adjustment

        adjusted_gap_mm = RuleEngine._distance(camera_pos, adjusted_tail)
        max_allowed_gap_mm = max(standard_tail_gap_mm * 1.55, standard_tail_gap_mm + 3000.0)
        if adjusted_gap_mm <= max_allowed_gap_mm:
            return adjusted_tail, adjustment

        camera_attributes = camera.get("attributes", {}) if isinstance(camera, dict) else {}
        skipped_adjustment = dict(adjustment)
        skipped_adjustment.update(
            {
                "adjusted": False,
                "skipped": True,
                "reason": "wall_avoidance_exceeds_cad_tail_gap",
                "standard_camera_to_tail_gap_m": round(standard_tail_gap_mm / 1000.0, 3),
                "rejected_camera_to_tail_gap_m": round(adjusted_gap_mm / 1000.0, 3),
                "orientation_source": camera_attributes.get("orientation_source"),
            }
        )
        return dict(raw_tail), skipped_adjustment

    def _infer_dock_operation_areas(
        self,
        parking_spaces: list[dict[str, Any]],
        shell_area: dict[str, Any] | None,
        site: dict[str, Any],
    ) -> list[dict[str, Any]]:
        if not parking_spaces:
            return []
        points = [
            point
            for space in parking_spaces
            for point in (space.get("geometry", {}).get("points") or [])
            if point.get("x") is not None and point.get("y") is not None
        ]
        if len(points) < 4:
            return []
        min_x = min(point["x"] for point in points)
        max_x = max(point["x"] for point in points)
        min_y = min(point["y"] for point in points)
        max_y = max(point["y"] for point in points)
        pad_x = 3500.0
        pad_y = 2500.0
        yard_elevation = float(site.get("yard_ground_elevation_m", 0.0))
        dock_height = float(site.get("dock_height_m", DOCK_HEIGHT_M))
        areas = [
            self._rect_area(
                "area_truck_yard",
                "area.parking_yard",
                "车辆停靠地面",
                min_x - pad_x,
                min_y - pad_y,
                max_x + pad_x,
                max_y + pad_y,
                {
                    "floor_elevation_m": yard_elevation,
                    "absolute_elevation": True,
                    "source": "按车尾摄像头与车辆模板自动生成，车辆地面低于仓库月台",
                    "render_as_scope": True,
                    "render_solid": False,
                    "show_label": False,
                },
            )
        ]

        shell_walls = self._shell_wall_by_side(shell_area)
        side_ranges: dict[str, list[float]] = {"left": [], "right": [], "bottom": [], "top": []}
        for space in parking_spaces:
            angle = float(space.get("orientation", {}).get("angle_deg", 0.0) or 0.0)
            direction = self._direction_from_angle(angle)
            if direction["x"] > 0.5:
                side = "right"
                axis = "y"
            elif direction["x"] < -0.5:
                side = "left"
                axis = "y"
            elif direction["y"] > 0.5:
                side = "top"
                axis = "x"
            elif direction["y"] < -0.5:
                side = "bottom"
                axis = "x"
            else:
                side = None
                axis = "y"
            if not side:
                continue
            for point in space.get("geometry", {}).get("points") or []:
                side_ranges[side].append(float(point[axis]))

        for side, values in side_ranges.items():
            if not values or side not in shell_walls:
                continue
            wall = shell_walls[side]
            strip_depth = float(self.standards.get("dock", {}).get("platform_strip_depth_m", 3.0)) * 1000.0
            if side == "left":
                x1, y1, x2, y2 = wall - strip_depth, min(values) - pad_y, wall, max(values) + pad_y
            elif side == "right":
                x1, y1, x2, y2 = wall, min(values) - pad_y, wall + strip_depth, max(values) + pad_y
            elif side == "bottom":
                x1, y1, x2, y2 = min(values) - pad_x, wall - strip_depth, max(values) + pad_x, wall
            else:
                x1, y1, x2, y2 = min(values) - pad_x, wall, max(values) + pad_x, wall + strip_depth
            areas.append(
                self._rect_area(
                    f"area_dock_platform_{side}",
                    "area.dock_platform",
                    "月台装卸面",
                    min(x1, x2),
                    min(y1, y2),
                    max(x1, x2),
                    max(y1, y2),
                    {
                        "floor_elevation_m": dock_height,
                        "height_m": dock_height,
                        "absolute_elevation": True,
                        "side": side,
                        "source": "按仓库外墙和车位队列推断月台面，月台表面与库内地面同高",
                    },
                )
            )
        return areas

    def _quality_diagnostics(
        self,
        stats: dict[str, Any],
        *,
        devices: list[dict[str, Any]],
        cables: list[dict[str, Any]],
        structures: list[dict[str, Any]],
        areas: list[dict[str, Any]],
        shell_area: dict[str, Any] | None,
        office_model: dict[str, Any],
        parking_spaces: list[dict[str, Any]],
        fixtures: list[dict[str, Any]],
        expected: dict[str, int],
        expected_sources: dict[str, Any],
        cable_candidate_summary: dict[str, Any],
    ) -> dict[str, Any]:
        warnings: list[str] = []
        inferred: list[str] = []
        checks = self._render_checklist(
            devices=devices,
            cables=cables,
            areas=areas,
            shell_area=shell_area,
            parking_spaces=parking_spaces,
            fixtures=fixtures,
            expected=expected,
        )
        coverage_audit = self._coverage_audit(devices)
        layer_switch_modules = self._layer_switch_modules(
            devices=devices,
            cables=cables,
            structures=structures,
            areas=areas,
            parking_spaces=parking_spaces,
            fixtures=fixtures,
        )
        system_module_analysis = self._system_module_analysis(
            devices=devices,
            cables=cables,
            structures=structures,
            areas=areas,
            parking_spaces=parking_spaces,
            fixtures=fixtures,
            expected=expected,
        )
        visual_audit = self._visual_audit(
            checks=checks,
            coverage_audit=coverage_audit,
            system_module_analysis=system_module_analysis,
            devices=devices,
            cables=cables,
            areas=areas,
            office_model=office_model,
            cable_candidate_summary=cable_candidate_summary,
        )
        if self.plan_windows:
            inferred.append("动态识别主平面窗口")
        if shell_area and shell_area.get("attributes", {}).get("source"):
            inferred.append("仓库外墙/轮廓外包络")
        else:
            warnings.append("未形成仓库外墙区域，3D 建筑感会不足")
        if parking_spaces:
            inferred.append("车尾摄像头驱动车位、车辆、射灯和月台地面")
        for item in self.suppressed_inferences:
            warnings.append(
                f"已抑制低置信兜底生成: {item.get('reason')}（{item.get('count')} 项）"
            )
        if office_model.get("floors"):
            inferred.append("办公室一层/夹层叠放")
        elif any("办公室" in str(area.get("label", "")) for area in areas):
            inferred.append("办公室范围兜底识别")
        if not cables:
            warnings.append("未识别或推断弱电线路")
        else:
            cad_route_count = sum(1 for item in cables if item.get("route_source") == "cad_polyline")
            if cad_route_count < len(cables) * 0.5:
                warnings.append(
                    f"{cad_route_count}/{len(cables)} 条线路来自 CAD 原始线层，其余线路仍来自推断，需要继续读取图纸线层校准"
                )
            else:
                inferred.append(f"{cad_route_count}/{len(cables)} 条线路已匹配 CAD 原始线层")
        if cable_candidate_summary.get("kept", cable_candidate_summary.get("total", 0)) > 0:
            warnings.append(
                f"已保留 {cable_candidate_summary.get('kept')} 条 CAD 线缆候选，需与推断线路做路径合并后再转为正式线路"
            )
        if stats.get("devices", 0) == 0:
            warnings.append("未识别弱电设备")
        if stats.get("structures", 0) < 20:
            warnings.append("建筑/结构线较少，可能需要补充图层映射")
        missing = [item["label"] for item in checks if item["status"] == "missing"]
        if missing:
            warnings.append("关键清单未渲染: " + "、".join(missing))
        extra = [item for item in checks if item.get("status") == "extra_detected"]
        if extra:
            details = [
                f"{item.get('label')} actual={item.get('actual')} expected={item.get('expected')}"
                for item in extra
            ]
            warnings.append("图纸预期清单与实际识别数量不一致: " + "；".join(details))
        return {
            "profile": "weak_current_warehouse_3d",
            "target": "web_upload_parse_to_3d_model",
            "plan_windows": self.plan_windows,
            "reference_regions": self.reference_regions,
            "ignored_regions": self.ignored_regions,
            "expected_inventory": expected,
            "expected_inventory_sources": expected_sources,
            "cable_candidate_summary": cable_candidate_summary,
            "render_checklist": checks,
            "coverage_audit": coverage_audit,
            "layer_switch_modules": layer_switch_modules,
            "system_module_analysis": system_module_analysis,
            "visual_audit": visual_audit,
            "layer_render_standard": self._parse_capability_summary(),
            "inferred_features": inferred,
            "warnings": warnings,
        }

    def _parse_capability_summary(self) -> dict[str, Any]:
        standards = self.layer_render_standards or {}
        modules = standards.get("module_standards") or {}
        return {
            "source": str(self.layer_render_standards_path),
            "version": standards.get("version"),
            "status": standards.get("status"),
            "site_profiles": self.site_profiles,
            "profile_configs": [
                {
                    "id": config.get("id"),
                    "site_type": config.get("site_type"),
                    "display_name": config.get("display_name"),
                }
                for config in self.profile_configs
            ],
            "scope": standards.get("scope", {}),
            "integration_contract": standards.get("integration_contract", {}),
            "historical_baselines": standards.get("historical_baselines", {}),
            "module_count": len(modules),
            "modules": sorted(modules.keys()),
            "module_standards": modules,
            "system_view_merge": standards.get("system_view_merge", {}),
            "quality_contract": standards.get("quality_contract", {}),
        }

    def _layer_rule_audit(
        self,
        entities: list[dict[str, Any]],
        analysis_entities: list[dict[str, Any]],
        devices: list[dict[str, Any]],
        cables: list[dict[str, Any]],
        structures: list[dict[str, Any]],
        areas: list[dict[str, Any]],
        parking_spaces: list[dict[str, Any]],
        fixtures: list[dict[str, Any]],
    ) -> dict[str, Any]:
        analysis_ids = {str(entity.get("source_entity_id")) for entity in analysis_entities if entity.get("source_entity_id")}
        layer_stats: dict[str, dict[str, Any]] = {}

        def stat_for(layer: str) -> dict[str, Any]:
            layer_key = layer or "<empty>"
            if layer_key not in layer_stats:
                layer_stats[layer_key] = {
                    "layer": layer_key,
                    "total_entities": 0,
                    "analysis_entities": 0,
                    "ignored_entities": 0,
                    "reference_entities": 0,
                    "entity_types": Counter(),
                    "rule_matches": Counter(),
                    "generated": Counter(),
                    "semantic_types": Counter(),
                }
            return layer_stats[layer_key]

        for entity in entities:
            layer = str(entity.get("layer") or "")
            stat = stat_for(layer)
            stat["total_entities"] += 1
            stat["entity_types"][str(entity.get("entity_type") or "UNKNOWN")] += 1
            source_id = str(entity.get("source_entity_id") or "")
            if source_id in analysis_ids:
                stat["analysis_entities"] += 1
            elif self._is_entity_ignored(entity):
                stat["ignored_entities"] += 1
            elif self._is_entity_reference(entity):
                stat["reference_entities"] += 1

            classification = self.classify(entity)
            if classification:
                stat["rule_matches"][str(classification.get("type") or "unknown")] += 1
            native = self._native_cable_classification(entity)
            if native:
                stat["rule_matches"][str(native.get("type") or "cable.native")] += 1

        def add_generated(items: list[dict[str, Any]], category: str) -> None:
            for item in items:
                attrs = item.get("attributes") or {}
                layer = str(item.get("original_layer") or item.get("layer") or attrs.get("source_layer") or attrs.get("original_layer") or "")
                stat = stat_for(layer)
                stat["generated"][category] += 1
                stat["semantic_types"][str(item.get("type") or category)] += 1

        add_generated(devices, "devices")
        add_generated(cables, "cables")
        add_generated(structures, "structures")
        add_generated(areas, "areas")
        add_generated(parking_spaces, "parking_spaces")
        add_generated(fixtures, "fixtures")

        layers: list[dict[str, Any]] = []
        for stat in layer_stats.values():
            total = int(stat["total_entities"])
            generated_total = sum(stat["generated"].values())
            rule_match_total = sum(stat["rule_matches"].values())
            ignored = int(stat["ignored_entities"])
            layers.append(
                {
                    "layer": stat["layer"],
                    "total_entities": total,
                    "analysis_entities": int(stat["analysis_entities"]),
                    "ignored_entities": ignored,
                    "ignored_ratio": round(ignored / max(total, 1), 4),
                    "reference_entities": int(stat["reference_entities"]),
                    "entity_types": dict(stat["entity_types"].most_common(8)),
                    "rule_matches": dict(stat["rule_matches"].most_common(8)),
                    "generated": dict(stat["generated"]),
                    "semantic_types": dict(stat["semantic_types"].most_common(8)),
                    "status": self._layer_audit_status(total, ignored, rule_match_total, generated_total),
                }
            )

        layers.sort(key=lambda item: item["total_entities"], reverse=True)
        ineffective = [
            layer
            for layer in layers
            if sum(layer.get("rule_matches", {}).values()) > 0 and sum(layer.get("generated", {}).values()) == 0
        ][:40]
        high_ignored = [layer for layer in layers if layer["ignored_ratio"] >= 0.5 and layer["total_entities"] >= 20][:40]
        effective = [layer for layer in layers if sum(layer.get("generated", {}).values()) > 0][:40]
        return {
            "version": "0.2",
            "summary": {
                "layer_count": len(layers),
                "effective_layer_count": len(effective),
                "ineffective_rule_layer_count": len(ineffective),
                "high_ignored_layer_count": len(high_ignored),
                "modelspace_scale_to_mm": self.modelspace_scale_to_mm,
                "modelspace_scale_source": self.modelspace_scale_source,
            },
            "top_layers": layers[:80],
            "effective_layers": effective,
            "ineffective_rule_layers": ineffective,
            "high_ignored_layers": high_ignored,
        }

    @staticmethod
    def _layer_audit_status(total: int, ignored: int, rule_matches: int, generated: int) -> str:
        if generated > 0:
            return "effective"
        if ignored / max(total, 1) >= 0.5 and total >= 20:
            return "blocked_by_ignore"
        if rule_matches > 0:
            return "matched_but_not_generated"
        return "no_rule_match"

    def _expected_inventory(self, entities: list[dict[str, Any]]) -> dict[str, int]:
        text = "\n".join(str(entity.get("text") or "") for entity in entities if entity.get("entity_type") in {"TEXT", "MTEXT"})
        compact = re.sub(r"\s+", "", text.upper())
        ap_labels = self._expected_ap_labels(entities)
        ap_explicit_count = self._expected_count_from_patterns(
            compact,
            [
                r"(?:无线)?AP(?:共计)?[:：]?(\d{1,3})(?:台|个)",
                r"(\d{1,3})个(?:场地|办公)?无线AP",
            ],
        )
        fisheye_count = len(self._expected_short_label_set(compact, ("YY",)))
        bg_count = len(self._expected_short_label_set(compact, ("BG",)))
        oa_count = len(self._expected_short_label_set(compact, ("OA",)))
        dome_count = oa_count + bg_count
        camera_count = len(self._expected_short_label_set(compact, ("CW", "GX", "CD", "WH", "WW", "KW")))
        return {
            "ap": len(ap_labels) or ap_explicit_count,
            "fisheye": fisheye_count or self._expected_count_from_patterns(compact, [r"YY-\d{1,3}~(\d{1,3})", r"(\d{1,3})个鱼眼"]),
            "dome_camera": dome_count,
            "rear_camera": camera_count or self._expected_count_from_patterns(compact, [r"CW-\d{1,3}~(\d{1,3})", r"(\d{1,3})台枪型摄像头"]),
            "spotlight": self._expected_count_from_patterns(compact, [r"射灯[:：]?(\d{1,3})(?:台|个)", r"配(\d{1,3})个射灯"]),
            "cabinet": self._expected_count_from_patterns(compact, [r"(?:\d{1,3})U机柜[:：]?(\d{1,3})台", r"机柜[:：]?(\d{1,3})台"]),
        }

    def _expected_inventory_sources(self, entities: list[dict[str, Any]], expected: dict[str, int]) -> dict[str, Any]:
        text = "\n".join(str(entity.get("text") or "") for entity in entities if entity.get("entity_type") in {"TEXT", "MTEXT"})
        compact = re.sub(r"\s+", "", text.upper())
        ap_labels = self._expected_ap_labels(entities)
        sources: dict[str, Any] = {}
        configs = {
            "ap": {
                "label_prefixes": ("AP",),
                "source_when_found": "cad_ap_label_range_or_label_text",
                "evidence": ap_labels[:20],
            },
            "fisheye": {
                "label_prefixes": ("YY",),
                "source_when_found": "cad_fisheye_label_range_or_label_text",
            },
            "dome_camera": {
                "label_prefixes": ("BG", "OA"),
                "source_when_found": "cad_dome_label_text",
            },
            "rear_camera": {
                "label_prefixes": ("CW", "GX", "CD", "WH", "WW", "KW"),
                "source_when_found": "cad_camera_label_range_or_label_text",
            },
            "spotlight": {
                "patterns": (r"射灯[:：]?(\d{1,3})(?:台|个)", r"配(\d{1,3})个射灯"),
                "source_when_found": "cad_quantity_note",
            },
            "cabinet": {
                "patterns": (r"(?:\d{1,3})U机柜[:：]?(\d{1,3})台", r"机柜[:：]?(\d{1,3})台"),
                "source_when_found": "cad_quantity_note",
            },
        }
        for key, config in configs.items():
            count = int(expected.get(key, 0) or 0)
            evidence = list(config.get("evidence") or [])
            for prefix in config.get("label_prefixes", ()):
                evidence.extend(self._expected_label_evidence(compact, str(prefix)))
            for pattern in config.get("patterns", ()):
                evidence.extend(match.group(0)[:80] for match in re.finditer(str(pattern), compact))
            sources[key] = {
                "expected": count,
                "source_kind": config["source_when_found"] if count > 0 else "not_declared_in_expected_inventory",
                "evidence": evidence[:24],
                "confidence": 0.82 if count > 0 and evidence else (0.6 if count > 0 else 0.4),
            }
        return sources

    @staticmethod
    def _expected_count_from_patterns(text: str, patterns: list[str]) -> int:
        values: list[int] = []
        for pattern in patterns:
            for match in re.finditer(pattern, text):
                groups = [group for group in match.groups() if group is not None]
                if not groups:
                    continue
                try:
                    values.append(max(int(group) for group in groups))
                except ValueError:
                    continue
        return max(values, default=0)

    @staticmethod
    def _expected_label_evidence(text: str, prefix: str) -> list[str]:
        evidence: list[str] = []
        for match in re.finditer(rf"{re.escape(prefix)}-?\d{{1,3}}(?:~\d{{1,3}})?", text):
            evidence.append(match.group(0))
        return evidence

    @staticmethod
    def _expected_unique_label_count(text: str, prefixes: tuple[str, ...]) -> int:
        labels: set[str] = set()
        prefix_pattern = "|".join(re.escape(prefix) for prefix in prefixes)
        for match in re.finditer(rf"({prefix_pattern})-?(\d{{1,3}})~(\d{{1,3}})", text):
            prefix = match.group(1)
            start = int(match.group(2))
            end = int(match.group(3))
            if end < start or end - start > 200:
                continue
            for number in range(start, end + 1):
                labels.add(f"{prefix}-{number:02d}")
        return len(labels)

    def _apply_camera_parameter_notes(self, devices: list[dict[str, Any]], entities: list[dict[str, Any]]) -> None:
        parameter_map = self._camera_parameter_map(entities)
        if not parameter_map:
            return
        for device in devices:
            label = re.sub(r"\s+", "", str(device.get("label", "")).upper())
            params = parameter_map.get(label) or parameter_map.get(self._short_label_key(label))
            if not params:
                continue
            attrs = device.setdefault("attributes", {})
            existing_gap_source = str(attrs.get("tail_camera_to_vehicle_gap_source") or "")
            existing_gap_m = attrs.get("tail_camera_to_vehicle_gap_m")
            note_gap_m = params.get("tail_camera_to_vehicle_gap_m") if params.get("tail_camera_to_vehicle_gap_source") == "cad_text_note" else None
            attrs.update(params)
            if existing_gap_source == "cad_local_dimension" and existing_gap_m is not None:
                attrs["tail_camera_to_vehicle_gap_m"] = existing_gap_m
                attrs["tail_camera_to_vehicle_gap_source"] = existing_gap_source
                attrs["tail_camera_to_vehicle_gap_note_m"] = note_gap_m
                attrs["tail_camera_to_vehicle_gap_note_source"] = params.get("tail_camera_to_vehicle_gap_source")
            elif note_gap_m is not None:
                if existing_gap_m is not None and existing_gap_source:
                    attrs["tail_camera_to_vehicle_gap_cad_evidence_m"] = existing_gap_m
                    attrs["tail_camera_to_vehicle_gap_cad_evidence_source"] = existing_gap_source
                attrs["tail_camera_to_vehicle_gap_m"] = note_gap_m
                attrs["tail_camera_to_vehicle_gap_source"] = "cad_text_note"
            pixel_wan = attrs.get("pixel_wan")
            if pixel_wan is not None:
                attrs["pixel_label"] = f"{pixel_wan:g}万" if isinstance(pixel_wan, float) else f"{pixel_wan}万"
            if device.get("type") == "security.camera.fisheye":
                attrs.setdefault("camera_form", "鱼眼摄像头")
            elif device.get("type") == "security.camera.dome":
                attrs.setdefault("camera_form", "半球摄像头")
            elif str(device.get("type") or "").startswith("security.camera"):
                attrs.setdefault("camera_form", "枪型摄像头")

            distance_m = float(attrs.get("infrared_distance_m") or attrs.get("coverage_distance_m") or 0.0)
            if distance_m > 0.0:
                attrs["coverage_distance_m"] = distance_m
                attrs["coverage_distance_source"] = attrs.get("parameter_source", "cad_text_note")
            if label.startswith("BG-") and device.get("type") == "security.camera.dome":
                attrs["zone"] = "office"
                attrs["mount"] = "ceiling"

    def _camera_parameter_map(self, entities: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
        result: dict[str, dict[str, Any]] = {}
        for entity in entities:
            if entity.get("entity_type") not in {"TEXT", "MTEXT"}:
                continue
            text = str(entity.get("text") or "")
            if not text or not re.search(r"(摄像头|监控|鱼眼|半球|枪型)", text):
                continue
            for params in self._camera_parameters_from_text(text):
                labels = params.pop("labels")
                for label in labels:
                    result[label] = dict(params)
                    result[self._short_label_key(label)] = dict(params)
        return result

    def _camera_parameters_from_text(self, text: str) -> list[dict[str, Any]]:
        entries: list[dict[str, Any]] = []
        fragments: list[str] = []
        for line in text.splitlines():
            fragments.extend(part for part in re.split(r"[；;。]", line) if part.strip())
        for fragment in fragments:
            normalized = re.sub(r"\s+", "", fragment.upper())
            for match in re.finditer(r"([A-Z]{2})-?(\d{1,3})~(\d{1,3})号?[^；;。]*?(?:摄像头|监控)[^；;。]*", normalized):
                prefix, start_text, end_text = match.group(1), match.group(2), match.group(3)
                start = int(start_text)
                end = int(end_text)
                if end < start or end - start > 200:
                    continue
                segment = match.group(0)
                params = self._camera_parameter_attrs(segment)
                if not params:
                    continue
                width = max(2, len(start_text), len(end_text))
                params["labels"] = [f"{prefix}-{number:0{width}d}" for number in range(start, end + 1)]
                entries.append(params)
        return entries

    @staticmethod
    def _camera_parameter_attrs(text: str) -> dict[str, Any]:
        attrs: dict[str, Any] = {"parameter_source": "cad_text_note", "parameter_source_text": text[:160]}
        lens_match = re.search(r"(\d+(?:\.\d+)?)MM镜头", text)
        if lens_match:
            attrs["lens_mm"] = float(lens_match.group(1))
        infrared_match = re.search(r"(\d+(?:\.\d+)?)(?:米|M)红外", text)
        if infrared_match:
            attrs["infrared_distance_m"] = float(infrared_match.group(1))
        tail_gap_match = re.search(r"距(?:车尾|车辆尾部|车厢尾部)(?:约)?(\d+(?:\.\d+)?)(?:米|M)", text)
        if tail_gap_match:
            attrs["tail_camera_to_vehicle_gap_m"] = float(tail_gap_match.group(1))
            attrs["tail_camera_to_vehicle_gap_source"] = "cad_text_note"
        pixel_match = re.search(r"(\d+(?:\.\d+)?)万像素", text)
        if pixel_match:
            pixel_wan = float(pixel_match.group(1))
            attrs["pixel_wan"] = int(pixel_wan) if pixel_wan.is_integer() else pixel_wan
            attrs["megapixels"] = round(pixel_wan / 100.0, 2)

        parts: list[str] = []
        if attrs.get("lens_mm") is not None:
            parts.append(f"{attrs['lens_mm']:g}mm")
        if attrs.get("infrared_distance_m") is not None:
            parts.append(f"{attrs['infrared_distance_m']:g}m")
        if attrs.get("tail_camera_to_vehicle_gap_m") is not None:
            parts.append(f"tail{attrs['tail_camera_to_vehicle_gap_m']:g}m")
        if attrs.get("pixel_wan") is not None:
            parts.append(f"{attrs['pixel_wan']:g}W")
        if parts:
            attrs["parameter_signature"] = "/".join(parts)
        return attrs if len(attrs) > 2 else {}

    def _render_checklist(
        self,
        *,
        devices: list[dict[str, Any]],
        cables: list[dict[str, Any]],
        areas: list[dict[str, Any]],
        shell_area: dict[str, Any] | None,
        parking_spaces: list[dict[str, Any]],
        fixtures: list[dict[str, Any]],
        expected: dict[str, int],
    ) -> list[dict[str, Any]]:
        def count_devices(predicate: Any) -> int:
            return sum(1 for device in devices if predicate(device))

        cable_roles = [str(cable.get("attributes", {}).get("layer_role", "")) for cable in cables]
        non_bullet_camera_types = {"security.camera.fisheye", "security.camera.dome"}
        bullet_predicate = lambda d: str(d.get("type", "")).startswith("security.camera") and d.get("type") not in non_bullet_camera_types
        ap_count = count_devices(lambda d: d.get("type") == "network.ap")
        fisheye_count = count_devices(lambda d: d.get("type") == "security.camera.fisheye")
        dome_count = count_devices(lambda d: d.get("type") == "security.camera.dome")
        bullet_count = count_devices(bullet_predicate)
        if self._is_generic_mode():
            items = [
                ("cameras", "摄像头", count_devices(lambda d: str(d.get("type", "")).startswith("security.camera")), 0, "observed"),
                ("aps", "无线AP设备", ap_count, 0, "observed"),
                ("cabinets", "机柜设备", count_devices(lambda d: d.get("type") == "network.cabinet"), 0, "observed"),
                ("power", "配电设备", count_devices(lambda d: str(d.get("type", "")).startswith("power.")), 0, "observed"),
                ("lighting", "照明设备", count_devices(lambda d: str(d.get("type", "")).startswith("lighting.")), 0, "observed"),
                ("cables", "线路", len(cables), 0, "observed"),
            ]
        else:
            items = [
            ("warehouse_shell", "仓库主体", 1 if shell_area else 0, 1, "minimum"),
            ("cameras_fisheye", "鱼眼设备", fisheye_count, expected.get("fisheye", 0), "inventory"),
            ("coverage_fisheye", "鱼眼覆盖", count_devices(lambda d: d.get("type") == "security.camera.fisheye" and self._has_radius_coverage(d)), expected.get("fisheye", 0), "inventory"),
            ("cameras_dome", "半球设备", dome_count, expected.get("dome_camera", 0), "inventory"),
            ("coverage_dome", "半球覆盖", count_devices(lambda d: d.get("type") == "security.camera.dome" and (self._has_fan_coverage(d) or self._has_radius_coverage(d))), expected.get("dome_camera", 0), "inventory"),
            ("aps", "无线AP设备", ap_count, expected.get("ap", 0), "inventory"),
            ("coverage_ap", "无线AP覆盖", count_devices(lambda d: d.get("type") == "network.ap" and self._has_radius_coverage(d)), expected.get("ap", 0), "inventory"),
            ("cameras_bullet", "枪机/车尾摄像头设备", bullet_count, expected.get("rear_camera", 0), "inventory"),
            ("coverage_bullet", "枪机/车尾摄像头覆盖", count_devices(lambda d: bullet_predicate(d) and self._has_fan_coverage(d)), expected.get("rear_camera", 0), "inventory"),
            ("camera_orientation", "枪机安装方向", count_devices(lambda d: bullet_predicate(d) and d.get("orientation", {}).get("angle_deg") is not None), expected.get("rear_camera", 0), "inventory"),
            ("cabinets", "机柜设备", count_devices(lambda d: d.get("type") == "network.cabinet"), expected.get("cabinet", 0), "inventory"),
            ("weak_current_cables", "弱电线路/级联", len([c for c in cables if c.get("type") in {"cable.network", "cable.security", "cable.fiber", "cable.trunk"}]), 1, "minimum"),
            ("cabinet_cables", "机柜电缆", cable_roles.count("cabinet_cable"), 1, "minimum"),
            ("spotlight_cables", "射灯电缆", cable_roles.count("spotlight_cable"), expected.get("spotlight", 0), "inventory"),
            ("spotlights", "射灯", len(fixtures), expected.get("spotlight", 0), "inventory"),
            ("dock_parking", "车辆/月台", len(parking_spaces), 1, "minimum"),
            ("areas", "区域/办公室", len(areas), 1, "minimum"),
        ]
        checklist: list[dict[str, Any]] = []
        for key, label, actual, expected_count, mode in items:
            expected_value = int(expected_count or 0)
            if mode == "observed":
                status = "ok"
                required = 0
            else:
                required = expected_value if mode == "inventory" else max(expected_value, 1)
                if actual < required:
                    status = "missing"
                elif mode == "inventory" and actual > expected_value:
                    status = "extra_detected"
                else:
                    status = "ok"
            checklist.append(
                {
                    "key": key,
                    "label": label,
                    "actual": actual,
                    "expected": expected_value,
                    "required_min": required,
                    "check_mode": mode,
                    "status": status,
                }
            )
        return checklist

    def _coverage_audit(self, devices: list[dict[str, Any]]) -> dict[str, Any]:
        groups = [
            (
                "ap",
                "AP覆盖",
                lambda d: d.get("type") == "network.ap",
                self._has_radius_coverage,
            ),
            (
                "fisheye",
                "鱼眼覆盖",
                lambda d: d.get("type") == "security.camera.fisheye",
                self._has_radius_coverage,
            ),
            (
                "dome",
                "半球覆盖",
                lambda d: d.get("type") == "security.camera.dome",
                lambda d: self._has_fan_coverage(d) or self._has_radius_coverage(d),
            ),
            (
                "bullet",
                "枪机/车尾摄像头覆盖",
                lambda d: str(d.get("type", "")).startswith("security.camera")
                and d.get("type") not in {"security.camera.fisheye", "security.camera.dome"},
                self._has_fan_coverage,
            ),
        ]
        audit_groups: list[dict[str, Any]] = []
        for key, label, predicate, coverage_predicate in groups:
            items = [device for device in devices if predicate(device)]
            missing_coverage = [self._item_label(device) for device in items if not coverage_predicate(device)]
            missing_position = [self._item_label(device) for device in items if not device.get("geometry", {}).get("position")]
            source_counts = Counter(self._coverage_source(device) for device in items)
            fallback_coverage = [
                {
                    "id": device.get("id"),
                    "label": self._item_label(device),
                    "coverage_source": self._coverage_source(device),
                    "orientation_source": device.get("attributes", {}).get("orientation_source"),
                }
                for device in items
                if self._is_fallback_coverage_source(self._coverage_source(device))
            ]
            missing_orientation = [
                self._item_label(device)
                for device in items
                if key in {"bullet", "dome"} and device.get("orientation", {}).get("angle_deg") is None
            ]
            heights = sorted(
                {
                    round(float(device.get("attributes", {}).get("install_height_m")), 3)
                    for device in items
                    if device.get("attributes", {}).get("install_height_m") is not None
                }
            )
            angles = sorted(
                {
                    round(float(device.get("orientation", {}).get("angle_deg")), 3)
                    for device in items
                    if device.get("orientation", {}).get("angle_deg") is not None
                }
            )
            audit_groups.append(
                {
                    "key": key,
                    "label": label,
                    "total": len(items),
                    "with_coverage": len(items) - len(missing_coverage),
                    "missing_coverage": missing_coverage,
                    "missing_position": missing_position,
                    "missing_orientation": missing_orientation,
                    "coverage_source_distribution": dict(sorted(source_counts.items())),
                    "fallback_coverage": fallback_coverage,
                    "install_heights_m": heights,
                    "orientation_angles_deg": angles[:120],
                }
            )
        return {"groups": audit_groups}

    @staticmethod
    def _coverage_source(device: dict[str, Any]) -> str:
        attrs = device.get("attributes") or {}
        coverage = device.get("coverage") or {}
        source = attrs.get("coverage_source") or coverage.get("source") or attrs.get("coverage_radius_source")
        return str(source or "unspecified")

    @staticmethod
    def _is_fallback_coverage_source(source: str) -> bool:
        source = str(source or "").lower()
        return (
            not source
            or source == "unspecified"
            or source.endswith("_uniform")
            or "fallback" in source
            or "inferred" in source
            or "company_standard" in source
        )

    def _visual_audit(
        self,
        *,
        checks: list[dict[str, Any]],
        coverage_audit: dict[str, Any],
        system_module_analysis: dict[str, Any],
        devices: list[dict[str, Any]],
        cables: list[dict[str, Any]],
        areas: list[dict[str, Any]],
        office_model: dict[str, Any],
        cable_candidate_summary: dict[str, Any],
    ) -> dict[str, Any]:
        items: list[dict[str, Any]] = []
        for check in checks:
            if check.get("status") == "ok":
                continue
            items.append(
                {
                    "category": "render_checklist",
                    "severity": "warning",
                    "status": check.get("status"),
                    "label": check.get("label"),
                    "reason": f"actual={check.get('actual')} expected={check.get('expected')} required_min={check.get('required_min')}",
                    "source_key": check.get("key"),
                }
            )

        for group in coverage_audit.get("groups", []):
            for fallback in group.get("fallback_coverage", []):
                items.append(
                    {
                        "category": "coverage_fallback",
                        "severity": "warning",
                        "status": "review_needed",
                        "label": fallback.get("label"),
                        "object_id": fallback.get("id"),
                        "reason": f"{group.get('label')} 使用 {fallback.get('coverage_source')}，需要对照 CAD 覆盖线复核",
                        "source_key": group.get("key"),
                    }
                )

        inferred_cable_count = sum(1 for cable in cables if cable.get("route_source") != "cad_polyline")
        if inferred_cable_count:
            source_counts = Counter(str(cable.get("route_source") or "unspecified") for cable in cables)
            items.append(
                {
                    "category": "cable_source",
                    "severity": "warning",
                    "status": "cad_route_needed",
                    "label": "弱电/机柜/射灯线路",
                    "reason": f"{len(cables) - inferred_cable_count}/{len(cables)} 条线路来自 CAD 原始线层，其余需优先读取 CAD 线层/桥架/线槽后合并",
                    "source_distribution": dict(sorted(source_counts.items())),
                }
            )
        if cable_candidate_summary.get("kept", cable_candidate_summary.get("total", 0)):
            items.append(
                {
                    "category": "cable_cad_candidates",
                    "severity": "info",
                    "status": "candidate_routes_detected",
                    "label": "CAD 线缆候选",
                    "reason": "已从可靠 CAD 原生线层读取到线路候选，当前仅审计不替换推断线路",
                    "summary": cable_candidate_summary,
                }
            )

        for area in areas:
            attrs = area.get("attributes") or {}
            if attrs.get("render_as_scope") or attrs.get("wall_geometry_reliable") is False:
                items.append(
                    {
                        "category": "office_or_area_scope",
                        "severity": "info",
                        "status": "geometry_scope_only",
                        "label": area.get("label"),
                        "object_id": area.get("id"),
                        "reason": "区域由文本种子或范围兜底生成，未确认可靠墙线",
                        "footprint_source": attrs.get("footprint_source"),
                    }
                )

        for module in system_module_analysis.get("modules", []):
            if not module.get("screenshot_region"):
                continue
            items.append(
                {
                    "category": "system_module_screenshot",
                    "severity": "info",
                    "status": "pending_capture",
                    "label": module.get("label"),
                    "source_key": module.get("kind"),
                    "reason": "已有 CAD 截图区域计划，Web/工具端尚未生成模块 PNG 和视觉核验结果",
                    "screenshot_region": module.get("screenshot_region"),
                    "canonical_offset": module.get("canonical_offset"),
                }
            )

        review_devices = [
            device
            for device in devices
            if device.get("review_needed") or float(device.get("confidence", 1.0) or 1.0) < 0.75
        ]
        for device in review_devices[:80]:
            attrs = device.get("attributes") or {}
            items.append(
                {
                    "category": "device_review",
                    "severity": "warning",
                    "status": "review_needed",
                    "label": self._item_label(device),
                    "object_id": device.get("id"),
                    "reason": attrs.get("review_reason") or "设备置信度较低或被规则标记复核",
                    "source_kind": attrs.get("source_kind"),
                    "coverage_source": attrs.get("coverage_source"),
                }
            )

        return {
            "status": "pending" if items else "ok",
            "item_count": len(items),
            "requires_screenshot_capture": any(item.get("category") == "system_module_screenshot" for item in items),
            "office_wall_geometry_reliable": all(
                floor.get("wall_geometry_reliable") is not False for floor in office_model.get("floors", [])
            ),
            "items": items[:240],
        }

    def _layer_switch_modules(
        self,
        *,
        devices: list[dict[str, Any]],
        cables: list[dict[str, Any]],
        structures: list[dict[str, Any]],
        areas: list[dict[str, Any]],
        parking_spaces: list[dict[str, Any]],
        fixtures: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        ap_devices = [device for device in devices if device.get("type") == "network.ap"]
        fisheye_devices = [device for device in devices if device.get("type") == "security.camera.fisheye"]
        dome_devices = [device for device in devices if device.get("type") == "security.camera.dome"]
        bullet_devices = [
            device
            for device in devices
            if str(device.get("type", "")).startswith("security.camera") and device.get("type") not in {"security.camera.fisheye", "security.camera.dome"}
        ]
        cabinet_devices = [device for device in devices if device.get("type") == "network.cabinet"]
        weak_cables = [cable for cable in cables if cable.get("type") in {"cable.network", "cable.security", "cable.fiber", "cable.trunk"}]
        cabinet_cables = [cable for cable in cables if cable.get("attributes", {}).get("layer_role") == "cabinet_cable"]
        spotlight_cables = [cable for cable in cables if cable.get("attributes", {}).get("layer_role") == "spotlight_cable"]
        labels_count = len(devices) + len(areas) + len(parking_spaces) + len(fixtures)
        return [
            {
                "key": "shell",
                "label": "仓库建筑",
                "contains": ["仓库外墙", "护墙", "建筑轮廓", "柱网", "月台", "办公室/夹层区域"],
                "semantic_types": ["building.wall", "building.column", "building.outline", "area.*"],
                "actual": len(structures) + len(areas),
            },
            {
                "key": "vehicles",
                "label": "车辆月台",
                "contains": ["车位线", "车辆模型", "车辆停靠地面", "月台装卸面"],
                "semantic_types": ["parking.space", "vehicle.*", "area.parking_yard", "area.dock_platform"],
                "actual": len(parking_spaces),
            },
            {
                "key": "spotlights",
                "label": "车尾射灯",
                "contains": ["射灯设备", "射灯照射覆盖范围"],
                "semantic_types": ["fixture.spotlight"],
                "actual": len(fixtures),
            },
            {
                "key": "device.ap",
                "label": "AP 设备",
                "contains": ["无线 AP", "办公 AP"],
                "semantic_types": ["network.ap"],
                "actual": len(ap_devices),
            },
            {
                "key": "coverage.ap",
                "label": "AP 覆盖",
                "contains": ["AP 圆形覆盖范围"],
                "semantic_types": ["network.ap.coverage"],
                "actual": sum(1 for device in ap_devices if self._has_radius_coverage(device)),
            },
            {
                "key": "device.fisheye",
                "label": "鱼眼设备",
                "contains": ["鱼眼"],
                "semantic_types": ["security.camera.fisheye"],
                "actual": len(fisheye_devices),
            },
            {
                "key": "coverage.fisheye",
                "label": "鱼眼覆盖",
                "contains": ["鱼眼圆形覆盖范围"],
                "semantic_types": ["security.camera.fisheye.coverage"],
                "actual": sum(1 for device in fisheye_devices if self._has_radius_coverage(device)),
            },
            {
                "key": "device.dome",
                "label": "半球设备",
                "contains": ["半球", "办公半球"],
                "semantic_types": ["security.camera.dome"],
                "actual": len(dome_devices),
            },
            {
                "key": "coverage.dome",
                "label": "半球覆盖",
                "contains": ["半球图纸线条覆盖范围", "半球圆形覆盖范围"],
                "semantic_types": ["security.camera.dome.coverage"],
                "actual": sum(1 for device in dome_devices if self._has_fan_coverage(device) or self._has_radius_coverage(device)),
            },
            {
                "key": "device.bullet",
                "label": "枪机设备",
                "contains": ["枪机", "车尾摄像头", "墙装枪机"],
                "semantic_types": ["security.camera.bullet", "security.camera.rear"],
                "actual": len(bullet_devices),
            },
            {
                "key": "coverage.bullet",
                "label": "枪机覆盖",
                "contains": ["枪机扇形覆盖范围", "车尾摄像头扇形覆盖范围"],
                "semantic_types": ["security.camera.bullet.coverage", "security.camera.rear.coverage"],
                "actual": sum(1 for device in bullet_devices if self._has_fan_coverage(device)),
            },
            {
                "key": "device.cabinet",
                "label": "机柜设备",
                "contains": ["42U 机柜", "监控挂墙机柜", "网络挂墙机柜", "UPS电源", "UPS电池柜"],
                "semantic_types": ["network.cabinet"],
                "actual": len(cabinet_devices),
            },
            {
                "key": "cables",
                "label": "弱电线路",
                "contains": ["监控线路", "网络线路", "桥架主干", "机柜级联线路"],
                "semantic_types": ["cable.network", "cable.security", "cable.fiber", "cable.trunk"],
                "actual": len(weak_cables),
            },
            {
                "key": "cables.cabinet",
                "label": "机柜电缆",
                "contains": ["机柜供电/综合电缆"],
                "semantic_types": ["cable.power.cabinet"],
                "actual": len(cabinet_cables),
            },
            {
                "key": "cables.spotlight",
                "label": "射灯电缆",
                "contains": ["射灯供电/控制电缆"],
                "semantic_types": ["cable.power.spotlight"],
                "actual": len(spotlight_cables),
            },
            {
                "key": "labels",
                "label": "对象标签",
                "contains": ["设备编号", "区域名", "机柜名", "车位/车辆编号"],
                "semantic_types": ["label.*"],
                "actual": labels_count,
            },
        ]

    def _system_module_analysis(
        self,
        *,
        devices: list[dict[str, Any]],
        cables: list[dict[str, Any]],
        structures: list[dict[str, Any]],
        areas: list[dict[str, Any]],
        parking_spaces: list[dict[str, Any]],
        fixtures: list[dict[str, Any]],
        expected: dict[str, int],
    ) -> dict[str, Any]:
        modules: list[dict[str, Any]] = []
        for view in self.system_views:
            kind = str(view.get("kind") or "")
            direct_devices = self._items_from_system_view(devices, kind)
            direct_cables = self._items_from_system_view(cables, kind)
            direct_structures = self._items_from_system_view(structures, kind)
            module_devices = direct_devices
            module_cables = direct_cables
            module_structures = direct_structures
            module_parking_spaces: list[dict[str, Any]] = []
            module_fixtures: list[dict[str, Any]] = []
            if kind == "monitor":
                module_parking_spaces = parking_spaces
                module_fixtures = fixtures
            elif kind in {"cable", "cabinet_spotlight_power"}:
                module_cables = self._unique_items(
                    [
                        *direct_cables,
                        *[
                            cable
                            for cable in cables
                            if cable.get("attributes", {}).get("layer_role") in {"cabinet_cable", "spotlight_cable"}
                        ],
                    ]
                )
                module_fixtures = fixtures
            elif kind in {"cascade", "cabinet_link"}:
                module_cables = self._unique_items(
                    [
                        *direct_cables,
                        *[
                            cable
                            for cable in cables
                            if cable.get("type") in {"cable.network", "cable.security", "cable.fiber", "cable.trunk"}
                        ],
                    ]
                )
            counts = self._semantic_module_counts(
                devices=module_devices,
                cables=module_cables,
                structures=module_structures,
                areas=[],
                parking_spaces=module_parking_spaces,
                fixtures=module_fixtures,
            )
            direct_counts = self._semantic_module_counts(
                devices=direct_devices,
                cables=direct_cables,
                structures=direct_structures,
                areas=[],
                parking_spaces=[],
                fixtures=[],
            )
            modules.append(
                {
                    "kind": kind,
                    "label": self._system_view_label(kind),
                    "source_text": view.get("source_text"),
                    "coordinate_space": "raw_cad_mm",
                    "screenshot_region": view.get("bounds"),
                    "origin": view.get("origin"),
                    "canonical_offset": {"x_mm": view.get("offset_x", 0.0), "y_mm": view.get("offset_y", 0.0)},
                    "model_action": "read_and_merge_to_base_site",
                    "required_analysis": self._system_required_analysis(kind),
                    "direct_source_counts": direct_counts,
                    "counts": counts,
                    "status": self._system_module_status(kind, counts, expected),
                }
            )

        reference_capture_plan = [
            {
                "kind": str(region.get("type") or "reference"),
                "source_text": region.get("source_text"),
                "coordinate_space": "raw_cad_mm",
                "screenshot_region": region.get("bounds"),
                "model_action": "read_parameters_only_no_direct_model",
                "required_analysis": ["安装高度", "悬挂方式", "安装距离", "材料/工艺要求", "配电/线缆参数"],
            }
            for region in self.reference_regions
        ]
        return {
            "purpose": "按系统模块自动截图、分析、叠合并校验最终3D渲染对象",
            "coordinate_rule": "screenshot_region 使用原始CAD坐标；canonical_offset 用于叠合到基准监控/主平面坐标",
            "modules": modules,
            "reference_capture_plan": reference_capture_plan,
            "combined_model": {
                "label": "叠合后的最终3D模型",
                "counts": self._semantic_module_counts(
                    devices=devices,
                    cables=cables,
                    structures=structures,
                    areas=areas,
                    parking_spaces=parking_spaces,
                    fixtures=fixtures,
                ),
                "expected_inventory": expected,
            },
        }

    @staticmethod
    def _items_from_system_view(items: list[dict[str, Any]], kind: str) -> list[dict[str, Any]]:
        return [item for item in items if item.get("attributes", {}).get("merged_from_system_view") == kind]

    @staticmethod
    def _unique_items(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
        unique: list[dict[str, Any]] = []
        seen: set[str] = set()
        for item in items:
            key = str(item.get("id") or item.get("source_entity_id") or id(item))
            if key in seen:
                continue
            seen.add(key)
            unique.append(item)
        return unique

    def _semantic_module_counts(
        self,
        *,
        devices: list[dict[str, Any]],
        cables: list[dict[str, Any]],
        structures: list[dict[str, Any]],
        areas: list[dict[str, Any]],
        parking_spaces: list[dict[str, Any]],
        fixtures: list[dict[str, Any]],
    ) -> dict[str, Any]:
        device_type_counts = Counter(str(device.get("type") or "unknown") for device in devices)
        cable_type_counts = Counter(str(cable.get("type") or "unknown") for cable in cables)
        cable_role_counts = Counter(str(cable.get("attributes", {}).get("layer_role") or "-") for cable in cables)
        bullet_devices = [
            device
            for device in devices
            if str(device.get("type", "")).startswith("security.camera") and device.get("type") not in {"security.camera.fisheye", "security.camera.dome"}
        ]
        fisheye_devices = [device for device in devices if device.get("type") == "security.camera.fisheye"]
        dome_devices = [device for device in devices if device.get("type") == "security.camera.dome"]
        ap_devices = [device for device in devices if device.get("type") == "network.ap"]
        return {
            "devices_total": len(devices),
            "devices_by_type": dict(device_type_counts),
            "ap": len(ap_devices),
            "ap_coverage": sum(1 for device in ap_devices if self._has_radius_coverage(device)),
            "fisheye": len(fisheye_devices),
            "fisheye_coverage": sum(1 for device in fisheye_devices if self._has_radius_coverage(device)),
            "dome": len(dome_devices),
            "dome_coverage": sum(1 for device in dome_devices if self._has_fan_coverage(device) or self._has_radius_coverage(device)),
            "bullet_or_rear": len(bullet_devices),
            "bullet_or_rear_coverage": sum(1 for device in bullet_devices if self._has_fan_coverage(device)),
            "cabinets": device_type_counts.get("network.cabinet", 0),
            "cables_total": len(cables),
            "cables_by_type": dict(cable_type_counts),
            "cables_by_role": dict(cable_role_counts),
            "structures": len(structures),
            "areas": len(areas),
            "parking_spaces": len(parking_spaces),
            "fixtures": len(fixtures),
        }

    @staticmethod
    def _system_view_label(kind: str) -> str:
        return {
            "monitor": "监控示意图",
            "network": "网络示意图",
            "network_broadcast": "网络&广播示意图",
            "cable": "电缆/配电示意图",
            "cascade": "级联线路示意图",
            "cabinet_link": "机柜链路示意图",
            "cabinet_spotlight_power": "机柜&射灯电路示意图",
        }.get(kind, kind or "系统视图")

    @staticmethod
    def _system_required_analysis(kind: str) -> list[str]:
        common = ["设备编号", "安装坐标", "安装高度", "覆盖范围", "图层来源", "缺失/待复核项"]
        if kind == "monitor":
            return common + ["鱼眼", "半球", "枪机/车尾摄像头", "枪机扇形覆盖", "射灯", "监控机柜", "月台/车位方向"]
        if kind in {"network", "network_broadcast"}:
            return common + ["无线AP", "办公AP", "AP圆形覆盖", "网络机柜", "网络点位/线路", "广播音柱/广播机柜"]
        if kind in {"cable", "cabinet_spotlight_power"}:
            return common + ["机柜电缆", "射灯电缆", "配电参数", "线缆路径"]
        if kind in {"cascade", "cabinet_link"}:
            return common + ["机柜级联线路", "弱电主干", "级联方向"]
        return common

    @staticmethod
    def _system_module_status(kind: str, counts: dict[str, Any], expected: dict[str, int]) -> str:
        if kind in {"network", "network_broadcast"} and int(expected.get("ap", 0) or 0) > 0 and int(counts.get("ap", 0) or 0) == 0:
            return "needs_review"
        if kind == "monitor" and int(counts.get("fisheye", 0) or 0) + int(counts.get("dome", 0) or 0) + int(counts.get("bullet_or_rear", 0) or 0) == 0:
            return "needs_review"
        if kind in {"cable", "cabinet_spotlight_power"} and int(counts.get("cables_total", 0) or 0) == 0:
            return "needs_review"
        if kind in {"cascade", "cabinet_link"} and int(counts.get("cables_total", 0) or 0) == 0:
            return "needs_review"
        return "ok"

    @staticmethod
    def _item_label(item: dict[str, Any]) -> str:
        return str(item.get("label") or item.get("id") or item.get("source_entity_id") or "-")

    @staticmethod
    def _has_radius_coverage(device: dict[str, Any]) -> bool:
        coverage = device.get("coverage") or {}
        return float(coverage.get("radius_m") or 0.0) > 0.0

    @staticmethod
    def _has_fan_coverage(device: dict[str, Any]) -> bool:
        coverage = device.get("coverage") or {}
        return float(coverage.get("length_m") or 0.0) > 0.0 and float(coverage.get("angle_deg") or 0.0) > 0.0

    @staticmethod
    def _distance(start: dict[str, float], end: dict[str, float]) -> float:
        dx = float(end["x"]) - float(start["x"])
        dy = float(end["y"]) - float(start["y"])
        return (dx * dx + dy * dy) ** 0.5

    def _apply_cad_coverage_overlays(self, devices: list[dict[str, Any]], entities: list[dict[str, Any]]) -> None:
        circle_candidates = self._cad_circle_coverage_candidates(entities)
        self._apply_uniform_cad_radius_coverage(
            devices,
            circle_candidates,
            target_types={"network.ap"},
            roles={"ap_coverage"},
            source_label="cad_circle",
        )
        self._apply_uniform_cad_radius_coverage(
            devices,
            circle_candidates,
            target_types={"security.camera.fisheye"},
            roles={"fisheye_coverage"},
            source_label="cad_circle",
        )
        self._apply_uniform_cad_radius_coverage(
            devices,
            circle_candidates,
            target_types={"security.camera.dome"},
            roles={"dome_coverage"},
            source_label="cad_circle",
        )
        self._apply_cad_dome_coverage(devices, self._cad_dome_fan_candidates(entities))
        camera_fans = self._cad_camera_fan_candidates(entities)
        self._apply_cad_camera_fans(devices, camera_fans)
        self._apply_cd_wall_camera_fans(devices, camera_fans)

    def _apply_uniform_cad_radius_coverage(
        self,
        devices: list[dict[str, Any]],
        candidates: list[dict[str, Any]],
        *,
        target_types: set[str],
        roles: set[str],
        source_label: str,
    ) -> None:
        targets = [device for device in devices if device.get("type") in target_types and device.get("geometry", {}).get("position")]
        role_candidates = [candidate for candidate in candidates if candidate.get("role") in roles]
        if not targets or not role_candidates:
            return

        matches: dict[int, dict[str, Any]] = {}
        matched_radii: list[float] = []
        for index, device in enumerate(targets):
            match = self._nearest_cad_circle(device, role_candidates)
            if not match:
                continue
            matches[index] = match
            matched_radii.append(float(match["radius_mm"]) / 1000.0)
            pos = device.get("geometry", {}).get("position") or {}
            attrs = device.setdefault("attributes", {})
            attrs["label_anchor"] = {"x": pos["x"], "y": pos["y"]}
            attrs["position_source"] = "cad_coverage_circle_center"
            attrs["coverage_circle_source_entity_id"] = match.get("source_entity_id")
            device["geometry"] = {
                **device.get("geometry", {}),
                "type": "Point",
                "position": {"x": match["center"]["x"], "y": match["center"]["y"]},
            }

        if not matched_radii:
            return

        radius_m = round(self._dominant_sample([float(candidate["radius_mm"]) / 1000.0 for candidate in role_candidates]), 1)
        for device in targets:
            attrs = device.setdefault("attributes", {})
            current = float((device.get("coverage") or {}).get("radius_m") or 0.0)
            coverage = {**(device.get("coverage") or {})}
            coverage["radius_m"] = radius_m
            device["coverage"] = coverage
            attrs["coverage_radius_source"] = source_label
            attrs["coverage_radius_samples"] = len(role_candidates)
            if current > 0.0 and abs(current - radius_m) > 0.01:
                attrs["coverage_radius_previous_m"] = round(current, 3)

    def _cad_circle_coverage_candidates(self, entities: list[dict[str, Any]]) -> list[dict[str, Any]]:
        candidates: list[dict[str, Any]] = []
        for entity in entities:
            base_role = self._cad_entity_role(entity)
            shapes = entity.get("cad_virtual_shapes") or []
            if not shapes and entity.get("geometry", {}).get("type") in {"Circle", "Ellipse", "Polygon"}:
                shapes = [entity]
            for shape in shapes:
                role = str(shape.get("cad_role") or base_role or "")
                if role not in {"ap_coverage", "fisheye_coverage", "dome_coverage"}:
                    continue
                if not self._is_red_cad_shape(shape):
                    continue
                candidate = self._circle_candidate_from_geometry(shape.get("geometry") or {})
                if not candidate:
                    continue
                folded_geometry, _fold = self._fold_geometry(
                    {"type": "Circle", "center": candidate["center"], "radius": candidate["radius_mm"]}
                )
                center = folded_geometry.get("center")
                if not center:
                    continue
                candidates.append(
                    {
                        "role": role,
                        "center": center,
                        "radius_mm": candidate["radius_mm"],
                        "source_entity_id": shape.get("source_entity_id") or entity.get("source_entity_id"),
                        "source_block_name": entity.get("block_name"),
                    }
                )
        return candidates

    @staticmethod
    def _cad_entity_role(entity: dict[str, Any]) -> str | None:
        block_name = str(entity.get("block_name") or "")
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
    def _is_red_cad_shape(shape: dict[str, Any]) -> bool:
        if int(shape.get("effective_color") or 0) == 1:
            return True
        true_color = shape.get("true_color")
        if true_color is None:
            return False
        red = (int(true_color) >> 16) & 0xFF
        green = (int(true_color) >> 8) & 0xFF
        blue = int(true_color) & 0xFF
        return red >= 180 and green <= 80 and blue <= 80

    def _circle_candidate_from_geometry(self, geometry: dict[str, Any]) -> dict[str, Any] | None:
        geometry_type = geometry.get("type")
        if geometry_type == "Circle":
            center = geometry.get("center")
            radius = float(geometry.get("radius") or 0.0)
        elif geometry_type == "Ellipse":
            center = geometry.get("center")
            radius_major = float(geometry.get("radius_major") or 0.0)
            radius_minor = float(geometry.get("radius_minor") or 0.0)
            if not radius_major or not radius_minor:
                return None
            radius = (radius_major + radius_minor) / 2.0
        elif geometry_type == "Polygon":
            points = geometry.get("points") or []
            bbox = self._points_bbox(points)
            if not bbox:
                return None
            width = bbox["max_x"] - bbox["min_x"]
            height = bbox["max_y"] - bbox["min_y"]
            if min(width, height) <= 0.0 or max(width, height) / min(width, height) > 1.35:
                return None
            center = self._bbox_center(bbox)
            radius = (width + height) / 4.0
        else:
            return None
        if not center or radius < 5_000.0 or radius > 80_000.0:
            return None
        return {"center": {"x": float(center["x"]), "y": float(center["y"])}, "radius_mm": radius}

    def _nearest_cad_circle(self, device: dict[str, Any], candidates: list[dict[str, Any]]) -> dict[str, Any] | None:
        pos = device.get("geometry", {}).get("position")
        if not pos:
            return None
        nearest = min(candidates, key=lambda candidate: self._distance(pos, candidate["center"]), default=None)
        if not nearest:
            return None
        distance = self._distance(pos, nearest["center"])
        radius = float(nearest.get("radius_mm") or 0.0)
        if distance > max(3_000.0, min(radius * 0.35, 8_000.0)):
            return None
        return nearest

    def _apply_cad_dome_coverage(self, devices: list[dict[str, Any]], candidates: list[dict[str, Any]]) -> None:
        domes = [
            device
            for device in devices
            if device.get("type") == "security.camera.dome" and device.get("geometry", {}).get("position")
        ]
        if not domes or not candidates:
            return
        used: set[int] = set()
        matches: list[tuple[dict[str, Any], dict[str, Any]]] = []
        for device in domes:
            pos = device.get("geometry", {}).get("position") or {}
            ranked = sorted(
                (
                    (self._distance(pos, candidate["origin"]), index, candidate)
                    for index, candidate in enumerate(candidates)
                    if index not in used
                ),
                key=lambda item: item[0],
            )
            if not ranked:
                continue
            distance, index, candidate = ranked[0]
            if distance > max(3_000.0, min(float(candidate.get("length_mm") or 0.0) * 0.35, 6_000.0)):
                continue
            used.add(index)
            matches.append((device, candidate))

        for device, candidate in matches:
            pos = device.get("geometry", {}).get("position") or {}
            length_m = round(float(candidate["length_mm"]) / 1000.0, 1)
            angle_deg = round(float(candidate.get("sector_angle_deg") or DOME_COVERAGE_SECTOR_ANGLE_DEG), 1)
            angle = round(float(candidate["angle_deg"]), 3)
            coverage = {**(device.get("coverage") or {})}
            coverage.pop("radius_m", None)
            coverage["length_m"] = length_m
            coverage["angle_deg"] = angle_deg
            device["coverage"] = coverage

            attrs = device.setdefault("attributes", {})
            attrs["label_anchor"] = {"x": pos["x"], "y": pos["y"]}
            attrs["position_source"] = "cad_dome_symbol_red_fan"
            attrs["orientation_source"] = "cad_dome_symbol_red_fan"
            attrs["orientation_confidence"] = 0.94
            attrs["coverage_source"] = "cad_dome_symbol_red_fan"
            attrs["coverage_angle_rule"] = "dome_two_boundary_edges_90deg"
            attrs["coverage_angle_source"] = "半球覆盖两条边按 90° 规则生成"
            attrs["raw_coverage_angle_deg"] = round(float(candidate.get("raw_sector_angle_deg") or angle_deg), 1)
            attrs["coverage_samples"] = len(matches)
            attrs["camera_symbol_source_entity_id"] = candidate.get("source_entity_id")
            attrs["camera_symbol_block_name"] = candidate.get("source_block_name")
            attrs.pop("coverage_radius_source", None)
            attrs.pop("coverage_length_source", None)
            device["geometry"] = {
                **device.get("geometry", {}),
                "type": "Point",
                "position": {"x": candidate["origin"]["x"], "y": candidate["origin"]["y"]},
            }
            device.setdefault("orientation", {})["angle_deg"] = angle
            attrs["orientation_target"] = self._target_from_angle(candidate["origin"], angle, float(candidate["length_mm"]))

    def _apply_cad_camera_fans(self, devices: list[dict[str, Any]], candidates: list[dict[str, Any]]) -> None:
        cameras = [
            device
            for device in devices
            if device.get("type") in {"security.camera.bullet", "security.camera.rear"}
            and device.get("geometry", {}).get("position")
        ]
        if not cameras or not candidates:
            return
        used: set[int] = set()
        matches: list[tuple[dict[str, Any], dict[str, Any]]] = []
        for device in cameras:
            pos = device.get("geometry", {}).get("position") or {}
            ranked = sorted(
                ((self._distance(pos, candidate["origin"]), index, candidate) for index, candidate in enumerate(candidates) if index not in used),
                key=lambda item: item[0],
            )
            if not ranked:
                continue
            distance, index, candidate = ranked[0]
            if distance > max(5_000.0, min(float(candidate.get("length_mm") or 0.0) * 0.28, 9_000.0)):
                continue
            used.add(index)
            matches.append((device, candidate))

        if not matches:
            return

        length_m = round(self._dominant_sample([float(candidate["length_mm"]) / 1000.0 for _device, candidate in matches]), 1)
        angle_deg = round(self._dominant_sample([float(candidate["sector_angle_deg"]) for _device, candidate in matches]), 1)
        matched_device_ids = {id(device) for device, _candidate in matches}
        for device in cameras:
            current = device.get("coverage") or self._coverage_for(str(device.get("type") or "security.camera.bullet"))
            device["coverage"] = {**current, "length_m": length_m, "angle_deg": angle_deg}
            attrs = device.setdefault("attributes", {})
            attrs.setdefault("coverage_source", "cad_camera_symbol_red_fan_uniform")
            attrs["coverage_samples"] = len(matches)
            if id(device) not in matched_device_ids and attrs.get("coverage_source") == "cad_camera_symbol_red_fan_uniform":
                attrs["coverage_review_needed"] = True
                attrs["review_reason"] = "未一对一匹配到独立 CAD 红色扇形，暂用同项目 CAD 扇形主样本兜底"
                device["review_needed"] = True
                device["confidence"] = min(float(device.get("confidence", 1.0) or 1.0), 0.74)
        for device, candidate in matches:
            pos = device.get("geometry", {}).get("position") or {}
            attrs = device.setdefault("attributes", {})
            attrs["label_anchor"] = {"x": pos["x"], "y": pos["y"]}
            attrs["position_source"] = "cad_camera_symbol_red_fan"
            attrs["orientation_source"] = "cad_camera_symbol_red_fan"
            attrs["orientation_confidence"] = 0.94
            attrs["coverage_source"] = "cad_camera_symbol_red_fan"
            attrs["coverage_samples"] = len(matches)
            attrs["camera_symbol_source_entity_id"] = candidate.get("source_entity_id")
            attrs["camera_symbol_block_name"] = candidate.get("source_block_name")
            if candidate.get("tail_gap_mm"):
                attrs["tail_camera_to_vehicle_gap_m"] = round(float(candidate["tail_gap_mm"]) / 1000.0, 3)
                attrs["tail_camera_to_vehicle_gap_source"] = "cad_camera_symbol_block_name"
            if candidate.get("symbol_dimension_mm"):
                attrs["camera_symbol_dimension_m"] = round(float(candidate["symbol_dimension_mm"]) / 1000.0, 3)
                attrs["camera_symbol_dimension_source"] = "cad_virtual_dimension"
            device["geometry"] = {
                **device.get("geometry", {}),
                "type": "Point",
                "position": {"x": candidate["origin"]["x"], "y": candidate["origin"]["y"]},
            }
            angle = round(float(candidate["angle_deg"]), 3)
            device.setdefault("orientation", {})["angle_deg"] = angle
            attrs["orientation_target"] = self._target_from_angle(candidate["origin"], angle, length_m * 1000.0)

    def _apply_cd_wall_camera_fans(self, devices: list[dict[str, Any]], candidates: list[dict[str, Any]]) -> None:
        if not candidates:
            return
        used: set[int] = set()
        matched: set[int] = set()
        cd_devices = [
            device
            for device in devices
            if device.get("type") == "security.camera.bullet"
            and str(device.get("label") or "").upper().startswith(("CD-", "WW-"))
            and device.get("geometry", {}).get("position")
        ]
        for device in sorted(cd_devices, key=lambda item: str(item.get("label") or "")):
            pos = device.get("geometry", {}).get("position") or {}
            ranked = sorted(
                (
                    (self._distance(pos, candidate["origin"]), index, candidate)
                    for index, candidate in enumerate(candidates)
                    if index not in used
                ),
                key=lambda item: item[0],
            )
            if not ranked:
                continue
            distance, index, candidate = ranked[0]
            if distance > max(3_500.0, min(float(candidate.get("length_mm") or 0.0) * 0.22, 5_000.0)):
                continue
            used.add(index)
            matched.add(id(device))
            length_m = round(float(candidate["length_mm"]) / 1000.0, 1)
            angle = round(float(candidate["angle_deg"]), 3)
            sector_angle = round(float(candidate["sector_angle_deg"]), 1)
            device["geometry"] = {
                **device.get("geometry", {}),
                "type": "Point",
                "position": {"x": candidate["origin"]["x"], "y": candidate["origin"]["y"]},
            }
            device["coverage"] = {
                **(device.get("coverage") or self._coverage_for(str(device.get("type") or "security.camera.bullet"))),
                "length_m": length_m,
                "angle_deg": sector_angle,
            }
            device.setdefault("orientation", {})["angle_deg"] = angle
            attrs = device.setdefault("attributes", {})
            attrs["position_source"] = "cad_cd_wall_camera_red_fan"
            attrs["orientation_source"] = "cad_cd_wall_camera_red_fan"
            attrs["orientation_confidence"] = 0.96
            attrs["coverage_source"] = "cad_cd_wall_camera_red_fan"
            attrs["coverage_samples"] = 1
            attrs["camera_symbol_source_entity_id"] = candidate.get("source_entity_id")
            attrs["camera_symbol_block_name"] = candidate.get("source_block_name")
            attrs["camera_symbol_match_distance_m"] = round(distance / 1000.0, 3)
            attrs["orientation_target"] = self._target_from_angle(candidate["origin"], angle, float(candidate["length_mm"]))
            attrs.pop("coverage_review_needed", None)
            if attrs.get("review_reason") == "未一对一匹配到独立 CAD 红色扇形，暂用同项目 CAD 扇形主样本兜底":
                attrs.pop("review_reason", None)

        for device in cd_devices:
            if id(device) in matched:
                continue
            attrs = device.setdefault("attributes", {})
            if attrs.get("coverage_source") == "cad_camera_symbol_red_fan_uniform":
                attrs["coverage_disabled"] = True
                attrs["coverage_source"] = "missing_cd_wall_camera_red_fan"
                attrs["orientation_source"] = "missing_cd_wall_camera_red_fan"
                attrs["orientation_confidence"] = 0.0
                attrs.pop("orientation_target", None)
                attrs["review_reason"] = "CD/WW 墙面枪机未匹配到独立 CAD 红色扇形，禁止使用统一样本生成覆盖角度"
                device["review_needed"] = True

    def _apply_supply_chain_downlight_camera_symbols(self, devices: list[dict[str, Any]], entities: list[dict[str, Any]]) -> None:
        if "supply_chain" not in self.site_profiles:
            return
        candidates = self._cad_camera_body_candidates(entities)
        if not candidates:
            return
        target_devices = [
            device
            for device in devices
            if device.get("type") in {"security.camera.bullet", "security.camera.rear"}
            and self._is_manual_supply_chain_downlight_label(str(device.get("label") or ""))
            and device.get("geometry", {}).get("position")
        ]
        if not target_devices:
            return

        def label_number(device: dict[str, Any]) -> int:
            return self._camera_label_number(str(device.get("label") or ""), "WH") or 0

        used: set[int] = set()
        for device in sorted(target_devices, key=label_number):
            pos = device.get("geometry", {}).get("position") or {}
            ranked = sorted(
                (
                    (self._distance(pos, candidate["origin"]), index, candidate)
                    for index, candidate in enumerate(candidates)
                    if index not in used
                ),
                key=lambda item: item[0],
            )
            if not ranked:
                continue
            distance, index, candidate = ranked[0]
            if distance > 6_500.0:
                continue
            used.add(index)
            attrs = device.setdefault("attributes", {})
            attrs["label_anchor"] = {"x": pos["x"], "y": pos["y"]}
            attrs["position_source"] = "cad_camera_symbol_body_no_coverage"
            attrs["orientation_source"] = "cad_camera_symbol_body_no_coverage"
            attrs["orientation_confidence"] = 0.93
            attrs["camera_symbol_source_entity_id"] = candidate.get("source_entity_id")
            attrs["camera_symbol_block_name"] = candidate.get("source_block_name")
            attrs["camera_symbol_match_distance_m"] = round(distance / 1000.0, 3)
            attrs["supply_chain_pair_layout_source"] = "cad_camera_symbol_body_nearest_label"
            device["geometry"] = {
                **device.get("geometry", {}),
                "type": "Point",
                "position": {"x": candidate["origin"]["x"], "y": candidate["origin"]["y"]},
            }
            angle = round(float(candidate["angle_deg"]), 3)
            device.setdefault("orientation", {})["angle_deg"] = angle
            attrs["orientation_target"] = self._target_from_angle(candidate["origin"], angle, 1800.0)

    def _apply_manual_supply_chain_downlight_cameras(self, devices: list[dict[str, Any]]) -> None:
        if "supply_chain" not in self.site_profiles:
            return
        for device in devices:
            if device.get("type") not in {"security.camera.bullet", "security.camera.rear"}:
                continue
            label = str(device.get("label") or "")
            if not self._is_manual_supply_chain_downlight_label(label):
                continue
            device["coverage"] = {"disabled": True, "source": "manual_supply_chain_rack_downlight_no_render"}

            attrs = device.setdefault("attributes", {})
            attrs["coverage_disabled"] = True
            attrs["coverage_source"] = "manual_supply_chain_rack_downlight_no_render"
            attrs["coverage_visual_source"] = "user_confirmed_downlight_no_cad_extension_line"
            attrs["coverage_render_style"] = "none"
            attrs["coverage_note"] = "用户确认供应链货架区该组 WH 枪机朝地面照射，3D 中不生成水平覆盖范围"
            angle = self._manual_supply_chain_camera_angle(label)
            orientation_source = str(attrs.get("orientation_source") or "")
            if angle is not None and not orientation_source.startswith("cad_camera_symbol_body"):
                device.setdefault("orientation", {})["angle_deg"] = angle
                attrs["orientation_source"] = "manual_supply_chain_rack_camera_symbol_direction"
                attrs["orientation_confidence"] = 0.9
            attrs.pop("coverage_review_needed", None)
            if attrs.get("review_reason") == "未一对一匹配到独立 CAD 红色扇形，暂用同项目 CAD 扇形主样本兜底":
                attrs.pop("review_reason", None)
                device["review_needed"] = False
                device["confidence"] = max(float(device.get("confidence", 0.0) or 0.0), 0.88)

    @classmethod
    def _is_manual_supply_chain_downlight_label(cls, label: str) -> bool:
        compact = re.sub(r"\s+", "", str(label or "").upper())
        for prefix, ranges in SUPPLY_CHAIN_RACK_DOWNLIGHT_CAMERA_RANGES.items():
            number = cls._camera_label_number(compact, prefix)
            if number is None:
                continue
            if any(start <= number <= end for start, end in ranges):
                return True
        return False

    @classmethod
    def _manual_supply_chain_camera_angle(cls, label: str) -> float | None:
        compact = re.sub(r"\s+", "", str(label or "").upper())
        for prefix, start, end, angle in SUPPLY_CHAIN_RACK_CAMERA_ORIENTATION_RULES:
            number = cls._camera_label_number(compact, prefix)
            if number is not None and start <= number <= end:
                return angle
        return None

    def _cad_camera_fan_candidates(self, entities: list[dict[str, Any]]) -> list[dict[str, Any]]:
        candidates: list[dict[str, Any]] = []
        for entity in entities:
            if self._cad_entity_role(entity) != "camera_symbol":
                continue
            candidate = self._fan_candidate_from_shapes(entity)
            if candidate:
                candidates.append(candidate)
        return candidates

    def _cad_camera_body_candidates(self, entities: list[dict[str, Any]]) -> list[dict[str, Any]]:
        candidates: list[dict[str, Any]] = []
        for entity in entities:
            if self._cad_entity_role(entity) != "camera_symbol":
                continue
            candidate = self._camera_body_candidate_from_shapes(entity)
            if candidate:
                candidates.append(candidate)
        return candidates

    def _camera_body_candidate_from_shapes(self, entity: dict[str, Any]) -> dict[str, Any] | None:
        shapes = [shape for shape in (entity.get("cad_virtual_shapes") or []) if self._is_red_cad_shape(shape)]
        points: list[dict[str, float]] = []
        segments: list[dict[str, float]] = []
        for shape in shapes:
            geometry, _fold = self._fold_geometry(shape.get("geometry") or {})
            geometry_type = geometry.get("type")
            if geometry_type == "LineString":
                line_points = geometry.get("points") or []
                if len(line_points) < 2:
                    continue
                start = line_points[0]
                end = line_points[-1]
                length = self._distance(start, end)
                if 150.0 <= length <= 6_000.0:
                    points.extend([start, end])
                    segments.append(
                        {
                            "length": length,
                            "angle_deg": self._angle_from_vector(
                                float(end["x"]) - float(start["x"]),
                                float(end["y"]) - float(start["y"]),
                            ),
                        }
                    )
            elif geometry_type == "Circle":
                radius = float(geometry.get("radius") or 0.0)
                center = geometry.get("center") or {}
                if 40.0 <= radius <= 3_000.0 and center.get("x") is not None and center.get("y") is not None:
                    points.extend(
                        [
                            {"x": float(center["x"]) - radius, "y": float(center["y"]) - radius},
                            {"x": float(center["x"]) + radius, "y": float(center["y"]) + radius},
                        ]
                    )
        if len(points) < 2 or not segments:
            return None
        bbox = self._points_bbox(points)
        if not bbox:
            return None
        span_x = float(bbox["max_x"] - bbox["min_x"])
        span_y = float(bbox["max_y"] - bbox["min_y"])
        if max(span_x, span_y) > 7_500.0 or min(span_x, span_y) < 120.0:
            return None
        ranked_segments = sorted(segments, key=lambda item: float(item["length"]), reverse=True)[:4]
        angle_deg = self._mean_direction_angle([float(item["angle_deg"]) for item in ranked_segments])
        return {
            "origin": {
                "x": (float(bbox["min_x"]) + float(bbox["max_x"])) / 2.0,
                "y": (float(bbox["min_y"]) + float(bbox["max_y"])) / 2.0,
            },
            "angle_deg": angle_deg,
            "source_entity_id": entity.get("source_entity_id"),
            "source_block_name": entity.get("block_name"),
            "bbox": bbox,
        }

    def _cad_dome_fan_candidates(self, entities: list[dict[str, Any]]) -> list[dict[str, Any]]:
        candidates: list[dict[str, Any]] = []
        for entity in entities:
            if self._cad_entity_role(entity) != "dome_coverage":
                continue
            candidate = self._dome_fan_candidate_from_shapes(entity)
            if candidate:
                candidates.append(candidate)
        return candidates

    def _dome_fan_candidate_from_shapes(self, entity: dict[str, Any]) -> dict[str, Any] | None:
        shapes = [shape for shape in (entity.get("cad_virtual_shapes") or []) if self._is_red_cad_shape(shape)]
        long_lines: list[dict[str, Any]] = []
        arc_angles: list[float] = []
        for shape in shapes:
            geometry, _fold = self._fold_geometry(shape.get("geometry") or {})
            if geometry.get("type") == "LineString":
                points = geometry.get("points") or []
                if len(points) < 2:
                    continue
                start = points[0]
                end = points[-1]
                length = self._distance(start, end)
                if length >= 5_000.0:
                    long_lines.append(
                        {
                            "start": start,
                            "end": end,
                            "length": length,
                            "angle_deg": self._angle_from_vector(float(end["x"]) - float(start["x"]), float(end["y"]) - float(start["y"])),
                        }
                    )
            elif geometry.get("type") == "Arc":
                radius = float(geometry.get("radius") or 0.0)
                if radius >= 5_000.0:
                    span = self._angular_distance(float(geometry.get("start_angle") or 0.0), float(geometry.get("end_angle") or 0.0))
                    if 15.0 <= span <= 120.0:
                        arc_angles.append(span)
        if not long_lines:
            return None

        ranked = sorted(long_lines, key=lambda item: item["length"], reverse=True)[:2]
        origin = {
            "x": sum(float(item["start"]["x"]) for item in ranked) / len(ranked),
            "y": sum(float(item["start"]["y"]) for item in ranked) / len(ranked),
        }
        angle_deg = self._mean_direction_angle([float(item["angle_deg"]) for item in ranked])
        raw_sector_angle = self._median(arc_angles) if arc_angles else self._angular_distance(
            float(ranked[0]["angle_deg"]),
            float(ranked[-1]["angle_deg"]),
        )
        if raw_sector_angle < 15.0 or raw_sector_angle > 120.0:
            raw_sector_angle = DOME_COVERAGE_SECTOR_ANGLE_DEG
        length_mm = self._median([float(item["length"]) for item in ranked])
        return {
            "origin": origin,
            "angle_deg": angle_deg,
            "sector_angle_deg": DOME_COVERAGE_SECTOR_ANGLE_DEG,
            "raw_sector_angle_deg": raw_sector_angle,
            "length_mm": length_mm,
            "source_entity_id": entity.get("source_entity_id"),
            "source_block_name": entity.get("block_name"),
        }

    def _fan_candidate_from_shapes(self, entity: dict[str, Any]) -> dict[str, Any] | None:
        shapes = [shape for shape in (entity.get("cad_virtual_shapes") or []) if self._is_red_cad_shape(shape)]
        long_lines: list[dict[str, Any]] = []
        arc_radii: list[float] = []
        for shape in shapes:
            geometry = shape.get("geometry") or {}
            if geometry.get("type") == "LineString":
                points = geometry.get("points") or []
                if len(points) < 2:
                    continue
                length = self._distance(points[0], points[-1])
                if length >= 5_000.0:
                    long_lines.append({"points": [points[0], points[-1]], "length": length})
            elif geometry.get("type") == "Arc":
                radius = float(geometry.get("radius") or 0.0)
                if radius >= 5_000.0:
                    arc_radii.append(radius)
        if len(long_lines) < 2:
            return None
        first, second = sorted(long_lines, key=lambda item: item["length"], reverse=True)[:2]
        origin_a, far_a, origin_b, far_b = self._paired_fan_line_endpoints(first["points"], second["points"])
        raw_angle_a = self._angle_from_vector(float(far_a["x"]) - float(origin_a["x"]), float(far_a["y"]) - float(origin_a["y"]))
        raw_angle_b = self._angle_from_vector(float(far_b["x"]) - float(origin_b["x"]), float(far_b["y"]) - float(origin_b["y"]))
        sector_angle = self._angular_distance(raw_angle_a, raw_angle_b)
        if sector_angle < 15.0 or sector_angle > 120.0:
            return None
        raw_origin = {"x": (float(origin_a["x"]) + float(origin_b["x"])) / 2.0, "y": (float(origin_a["y"]) + float(origin_b["y"])) / 2.0}
        origin, _fold_index = self._fold_point(raw_origin)
        length = self._median(arc_radii) if arc_radii else (float(first["length"]) + float(second["length"])) / 2.0
        tail_gap_mm = self._tail_gap_from_camera_block_name(str(entity.get("block_name") or ""))
        dimension_values: list[float] = []
        for item in entity.get("cad_virtual_dimensions") or []:
            raw_measurement = float(item.get("measurement") or 0.0)
            measurement_mm = raw_measurement * 1000.0 if 1.0 <= raw_measurement <= 12.0 else raw_measurement
            if 1_000.0 <= measurement_mm <= 12_000.0:
                dimension_values.append(measurement_mm)
        return {
            "origin": origin,
            "angle_deg": self._mean_direction_angle([raw_angle_a, raw_angle_b]),
            "sector_angle_deg": sector_angle,
            "length_mm": length,
            "source_entity_id": entity.get("source_entity_id"),
            "source_block_name": entity.get("block_name"),
            "tail_gap_mm": tail_gap_mm,
            "symbol_dimension_mm": self._median(dimension_values) if dimension_values else None,
        }

    @staticmethod
    def _tail_gap_from_camera_block_name(block_name: str) -> float | None:
        compact = re.sub(r"\s+", "", str(block_name or "").upper())
        match = re.search(r"(?:距离|距车尾|车尾)(\d{3,5})", compact)
        if not match:
            return None
        value = float(match.group(1))
        if 1_000.0 <= value <= 12_000.0:
            return value
        return None

    @staticmethod
    def _paired_fan_line_endpoints(
        first: list[dict[str, float]],
        second: list[dict[str, float]],
    ) -> tuple[dict[str, float], dict[str, float], dict[str, float], dict[str, float]]:
        pairs = [
            (first[0], first[1], second[0], second[1]),
            (first[0], first[1], second[1], second[0]),
            (first[1], first[0], second[0], second[1]),
            (first[1], first[0], second[1], second[0]),
        ]
        return min(pairs, key=lambda item: RuleEngine._distance(item[0], item[2]))

    @staticmethod
    def _angular_distance(left: float, right: float) -> float:
        return abs((left - right + 180.0) % 360.0 - 180.0)

    @staticmethod
    def _mean_direction_angle(angles: list[float]) -> float:
        if not angles:
            return 0.0
        dx = sum(sin(radians(angle)) for angle in angles)
        dy = sum(-cos(radians(angle)) for angle in angles)
        return (degrees(atan2(dx, -dy)) + 360.0) % 360.0

    @staticmethod
    def _median(values: list[float]) -> float:
        ordered = sorted(float(value) for value in values)
        if not ordered:
            return 0.0
        middle = len(ordered) // 2
        if len(ordered) % 2:
            return ordered[middle]
        return (ordered[middle - 1] + ordered[middle]) / 2.0

    @staticmethod
    def _dominant_sample(values: list[float]) -> float:
        ordered = [float(value) for value in values if float(value) > 0.0]
        if not ordered:
            return 0.0
        buckets = Counter(round(value, 1) for value in ordered)
        top_count = max(buckets.values())
        top_values = [value for value, count in buckets.items() if count == top_count]
        if len(top_values) == 1:
            return top_values[0]
        return max(top_values)

    def _vehicle_template_for_camera(
        self,
        camera: dict[str, Any],
        default_template: dict[str, Any],
        office_model: dict[str, Any] | None,
    ) -> dict[str, Any]:
        kw_short_box_template = self._kw_short_box_template_for_camera(camera)
        if kw_short_box_template:
            return kw_short_box_template
        cw_template = self._cw_side_dock_template_for_camera(camera)
        if cw_template:
            return cw_template

        pos = camera.get("geometry", {}).get("position")
        if not pos or not office_model or not office_model.get("floors"):
            return default_template
        angle = float(camera.get("orientation", {}).get("angle_deg", 0.0) or 0.0)
        direction = self._direction_from_angle(angle)
        if abs(direction["x"]) <= 0.5 or not self._is_office_adjacent_dock_camera(pos, office_model):
            return default_template
        template = self._vehicle_template_by_id("semi_trailer_17_5") or self._vehicle_template_by_id("container_61ft")
        if not template:
            return default_template
        template = dict(template)
        template["source_rule"] = "office_adjacent_trailer"
        return template

    def _cw_side_dock_template_for_camera(self, camera: dict[str, Any]) -> dict[str, Any] | None:
        if self._camera_label_number(str(camera.get("label") or ""), "CW") is None:
            return None
        template = self._vehicle_template_by_id("box_9_6")
        if not template:
            return None
        template = dict(template)
        template["source_rule"] = "cw_side_dock_uniform_box_9_6"
        return template

    def _kw_short_box_template_for_camera(self, camera: dict[str, Any]) -> dict[str, Any] | None:
        kw_number = self._camera_label_number(str(camera.get("label") or ""), "KW")
        if kw_number is None or not (KW_REAR_CAMERA_MIN_NUMBER <= kw_number <= KW_REAR_CAMERA_MAX_NUMBER):
            return None
        template = self._vehicle_template_by_id("box_4_2")
        if not template:
            return None
        template = dict(template)
        template["source_rule"] = "cad_legend_kw_4_2m_box_dock"
        return template

    def _is_office_adjacent_dock_camera(self, pos: dict[str, float], office_model: dict[str, Any]) -> bool:
        for floor in office_model.get("floors", []):
            if floor.get("level") != 1:
                continue
            bbox = floor.get("target_bbox") or {}
            if not bbox:
                continue
            within_x = bbox["min_x"] - OFFICE_ADJACENT_DOCK_PAD_X_MM <= pos["x"] <= bbox["max_x"] + OFFICE_ADJACENT_DOCK_PAD_X_MM
            above_office = bbox["max_y"] - OFFICE_FLOOR_MATCH_PAD_MM <= pos["y"] <= bbox["max_y"] + OFFICE_ADJACENT_DOCK_PAD_Y_MM
            if within_x and above_office:
                return True
        return False

    def _vehicle_template_by_id(self, template_id: str) -> dict[str, Any] | None:
        template = self.standards.get("vehicles", {}).get(template_id)
        if not template or not template.get("length_m") or not template.get("width_m"):
            return None
        return {"id": template_id, **template}

    def _vehicle_template_sequence(self, count: int) -> list[dict[str, Any]]:
        standards = self.standards.get("vehicles", {})
        if not standards:
            standards = {
                "box_4_2": {"label": "4.2M 箱式货车", "legend_count": 86, "length_m": 4.2, "width_m": 2.05, "height_m": 2.65},
                "box_9_6": {"label": "9.6M 箱式货车", "legend_count": 65, "length_m": 9.6, "width_m": 2.45, "height_m": 3.65},
                "container_61ft": {"label": "61尺 集卡", "legend_count": 59, "length_m": 18.6, "width_m": 2.5, "height_m": 4.1},
            }
        ordered = [
            {"id": key, **value}
            for key, value in standards.items()
            if value.get("length_m") and value.get("width_m") and not value.get("standard_only")
        ]
        if not ordered:
            ordered = [
                {"id": "box_4_2", "label": "4.2M 箱式货车", "legend_count": 86, "length_m": 4.2, "width_m": 2.05, "height_m": 2.65},
                {"id": "box_9_6", "label": "9.6M 箱式货车", "legend_count": 65, "length_m": 9.6, "width_m": 2.45, "height_m": 3.65},
                {"id": "container_61ft", "label": "61尺 集卡", "legend_count": 59, "length_m": 18.6, "width_m": 2.5, "height_m": 4.1},
            ]
        total_weight = sum(float(item.get("legend_count", 1)) for item in ordered) or len(ordered)
        sequence: list[dict[str, Any]] = []
        remaining = count
        for idx, item in enumerate(ordered):
            if idx == len(ordered) - 1:
                item_count = remaining
            else:
                item_count = int(round(count * float(item.get("legend_count", 1)) / total_weight))
                item_count = max(0, min(item_count, remaining))
            sequence.extend([item] * item_count)
            remaining -= item_count
        while len(sequence) < count:
            sequence.append(ordered[-1])
        return sequence[:count]

    @staticmethod
    def _rear_camera_number(label: str) -> int:
        match = re.search(r"(\d+)", label)
        return int(match.group(1)) if match else 9999

    @staticmethod
    def _direction_from_angle(angle_deg: float) -> dict[str, float]:
        angle = radians(angle_deg)
        return {"x": sin(angle), "y": -cos(angle)}

    @staticmethod
    def _angle_from_vector(dx: float, dy: float) -> float:
        return (degrees(atan2(dx, -dy)) + 360.0) % 360.0

    @staticmethod
    def _snap_cardinal_angle(angle_deg: float, tolerance_deg: float = 18.0) -> float:
        for candidate in (0.0, 90.0, 180.0, 270.0):
            delta = abs((angle_deg - candidate + 180.0) % 360.0 - 180.0)
            if delta <= tolerance_deg:
                return candidate
        return angle_deg

    @staticmethod
    def _target_from_angle(origin: dict[str, float], angle_deg: float, distance_mm: float = 30_000.0) -> dict[str, float]:
        angle = radians(angle_deg)
        return {
            "x": float(origin["x"]) + sin(angle) * distance_mm,
            "y": float(origin["y"]) - cos(angle) * distance_mm,
        }

    def _orient_site_bullet_cameras(
        self,
        devices: list[dict[str, Any]],
        shell_area: dict[str, Any] | None,
        entities: list[dict[str, Any]],
    ) -> None:
        if not shell_area:
            return
        shell_center = self._geometry_anchor(shell_area.get("geometry", {}))
        if not shell_center:
            return
        shell_bbox = self._points_bbox(shell_area.get("geometry", {}).get("points") or [])
        for device in devices:
            if device.get("type") != "security.camera.bullet":
                continue
            label = str(device.get("label") or "").upper()
            if not (label.startswith("CD-") or label.startswith("WW-")):
                continue
            pos = device.get("geometry", {}).get("position")
            if not pos:
                continue
            attrs = device.setdefault("attributes", {})
            orientation_source = str(attrs.get("orientation_source") or "")
            if (
                orientation_source.startswith("cad_camera_symbol")
                or orientation_source.startswith("cad_cd_wall_camera")
                or orientation_source.startswith("missing_cd_wall_camera")
                or attrs.get("coverage_disabled") is True
            ):
                continue
            if self._apply_cd_wall_mount_context(device, entities, shell_center):
                continue
            if self._apply_ww_arch_wall_anchor_context(device, entities, shell_center):
                continue
            dx = float(shell_center["x"]) - float(pos["x"])
            dy = float(shell_center["y"]) - float(pos["y"])
            distance = (dx * dx + dy * dy) ** 0.5
            if distance < 3000.0:
                continue
            angle, source, confidence = self._bullet_angle_from_shell_context(pos, shell_center, shell_bbox, label)
            device.setdefault("orientation", {})["angle_deg"] = angle
            attrs["orientation_source"] = source
            attrs["orientation_confidence"] = confidence
            if source.startswith("warehouse_exterior"):
                attrs["orientation_reference"] = {"x": shell_center["x"], "y": shell_center["y"]}
                attrs["orientation_target"] = self._target_from_angle(pos, angle)
            else:
                attrs["orientation_target"] = {"x": shell_center["x"], "y": shell_center["y"]}

    def _bullet_angle_from_shell_context(
        self,
        pos: dict[str, float],
        shell_center: dict[str, float],
        shell_bbox: dict[str, float] | None,
        label: str = "",
    ) -> tuple[float, str, float]:
        raw_angle = self._angle_from_vector(float(shell_center["x"]) - float(pos["x"]), float(shell_center["y"]) - float(pos["y"]))
        if not shell_bbox:
            return self._snap_cardinal_angle(raw_angle, tolerance_deg=18.0), "warehouse_center_context", 0.76
        label_upper = str(label or "").upper()
        side_threshold = 8_000.0
        near_sides: list[str] = []
        if abs(float(pos["x"]) - shell_bbox["min_x"]) <= side_threshold:
            near_sides.append("left")
        if abs(float(pos["x"]) - shell_bbox["max_x"]) <= side_threshold:
            near_sides.append("right")
        if abs(float(pos["y"]) - shell_bbox["min_y"]) <= side_threshold:
            near_sides.append("bottom")
        if abs(float(pos["y"]) - shell_bbox["max_y"]) <= side_threshold:
            near_sides.append("top")
        outside_shell = (
            float(pos["x"]) < shell_bbox["min_x"] - 500.0
            or float(pos["x"]) > shell_bbox["max_x"] + 500.0
            or float(pos["y"]) < shell_bbox["min_y"] - 500.0
            or float(pos["y"]) > shell_bbox["max_y"] + 500.0
        )
        if label_upper.startswith("WW-") and (near_sides or outside_shell):
            outward_angle = self._angle_from_vector(float(pos["x"]) - float(shell_center["x"]), float(pos["y"]) - float(shell_center["y"]))
            if len(near_sides) >= 2:
                return round(outward_angle, 3), "warehouse_exterior_corner_context", 0.86
            if len(near_sides) == 1:
                side_angle = {"left": 270.0, "right": 90.0, "bottom": 0.0, "top": 180.0}[near_sides[0]]
                return side_angle, "warehouse_exterior_wall_side_context", 0.87
            return round(outward_angle, 3), "warehouse_exterior_context", 0.82
        if len(near_sides) >= 2:
            return round(raw_angle, 3), "warehouse_corner_context", 0.82
        if len(near_sides) == 1:
            side_angle = {"left": 90.0, "right": 270.0, "bottom": 180.0, "top": 0.0}[near_sides[0]]
            return side_angle, "warehouse_wall_side_context", 0.84
        return self._snap_cardinal_angle(raw_angle, tolerance_deg=18.0), "warehouse_center_context", 0.76

    def _apply_cd_wall_mount_context(
        self,
        device: dict[str, Any],
        entities: list[dict[str, Any]],
        shell_center: dict[str, float],
    ) -> bool:
        label = str(device.get("label") or "").upper()
        pos = device.get("geometry", {}).get("position")
        if not pos or not re.fullmatch(r"CD-\d{1,3}", label):
            return False
        column_bbox = self._nearby_column_bbox(pos, entities, radius_mm=2600.0)
        if not column_bbox:
            return False

        column_center = self._bbox_center(column_bbox)
        is_left_mount = column_center["x"] <= shell_center["x"]
        is_upper_mount = float(pos["y"]) >= column_center["y"]
        mount_x = column_bbox["max_x"] if is_left_mount else column_bbox["min_x"]
        mount_y = column_bbox["max_y"] if is_upper_mount else column_bbox["min_y"]
        if is_left_mount:
            angle = 90.0
        else:
            angle = 225.0 if is_upper_mount else 315.0

        device["geometry"] = {**device.get("geometry", {}), "type": "Point", "position": {"x": mount_x, "y": mount_y}}
        device.setdefault("orientation", {})["angle_deg"] = angle
        coverage = {**(device.get("coverage") or self._coverage_for("security.camera.bullet"))}
        coverage["length_m"] = 16.0 if not is_left_mount else 15.0
        coverage["angle_deg"] = 50.0 if not is_left_mount else 45.0
        device["coverage"] = coverage
        attrs = device.setdefault("attributes", {})
        attrs.update(
            {
                "mount": "wall",
                "position_source": "cad_s_colu_wall_mount",
                "orientation_source": "cad_s_colu_wall_mount",
                "orientation_confidence": 0.88,
                "wall_mount_side": "left_column_face" if is_left_mount else "right_column_face",
                "wall_bbox": column_bbox,
                "label_anchor": {"x": pos["x"], "y": pos["y"]},
            }
        )
        return True

    def _apply_ww_arch_wall_anchor_context(
        self,
        device: dict[str, Any],
        entities: list[dict[str, Any]],
        shell_center: dict[str, float],
    ) -> bool:
        label = str(device.get("label") or "").upper()
        if not re.fullmatch(r"WW-\d{1,3}", label):
            return False
        pos = device.get("geometry", {}).get("position")
        if not pos:
            return False
        anchor = self._nearby_arch_insert_anchor(pos, entities, radius_mm=2300.0)
        if not anchor:
            return False
        dx = float(pos["x"]) - float(anchor["x"])
        dy = float(pos["y"]) - float(anchor["y"])
        distance = (dx * dx + dy * dy) ** 0.5
        offset = 350.0
        if distance > 1.0:
            mount = {"x": anchor["x"] + dx / distance * offset, "y": anchor["y"] + dy / distance * offset}
        else:
            mount = dict(anchor)
        angle = round(self._angle_from_vector(mount["x"] - float(shell_center["x"]), mount["y"] - float(shell_center["y"])), 3)
        device["geometry"] = {**device.get("geometry", {}), "type": "Point", "position": mount}
        device.setdefault("orientation", {})["angle_deg"] = angle
        attrs = device.setdefault("attributes", {})
        attrs.update(
            {
                "mount": "wall",
                "position_source": "cad_arch_wall_anchor",
                "orientation_source": "cad_arch_wall_anchor_outward",
                "orientation_confidence": 0.86,
                "wall_anchor": anchor,
                "label_anchor": {"x": pos["x"], "y": pos["y"]},
                "orientation_reference": {"x": shell_center["x"], "y": shell_center["y"]},
                "orientation_target": self._target_from_angle(mount, angle),
            }
        )
        return True

    @staticmethod
    def _nearby_arch_insert_anchor(
        point: dict[str, float],
        entities: list[dict[str, Any]],
        radius_mm: float,
    ) -> dict[str, float] | None:
        best: tuple[float, dict[str, float]] | None = None
        for entity in entities:
            if entity.get("entity_type") != "INSERT":
                continue
            layer = str(entity.get("layer") or "")
            if "装修" not in layer:
                continue
            pos = entity.get("geometry", {}).get("position")
            if not pos:
                continue
            dx = float(pos["x"]) - float(point["x"])
            dy = float(pos["y"]) - float(point["y"])
            distance = (dx * dx + dy * dy) ** 0.5
            if distance > radius_mm:
                continue
            if best is None or distance < best[0]:
                best = (distance, {"x": float(pos["x"]), "y": float(pos["y"])})
        return best[1] if best else None

    def _nearby_column_bbox(
        self,
        point: dict[str, float],
        entities: list[dict[str, Any]],
        radius_mm: float,
    ) -> dict[str, float] | None:
        points: list[dict[str, float]] = []
        for entity in entities:
            layer = str(entity.get("layer") or "").upper()
            if layer != "S-COLU":
                continue
            entity_points = self._folded_geometry_points(entity)
            if not entity_points:
                continue
            if min(self._distance(point, candidate) for candidate in entity_points) > radius_mm:
                continue
            points.extend(entity_points)
        if len(points) < 2:
            return None
        return {
            "min_x": min(item["x"] for item in points),
            "min_y": min(item["y"] for item in points),
            "max_x": max(item["x"] for item in points),
            "max_y": max(item["y"] for item in points),
        }

    @staticmethod
    def _oriented_rect(center: dict[str, float], direction: dict[str, float], length_mm: float, width_mm: float) -> list[dict[str, float]]:
        half_l = length_mm / 2.0
        half_w = width_mm / 2.0
        perp = {"x": -direction["y"], "y": direction["x"]}
        return [
            {"x": center["x"] - direction["x"] * half_l - perp["x"] * half_w, "y": center["y"] - direction["y"] * half_l - perp["y"] * half_w},
            {"x": center["x"] + direction["x"] * half_l - perp["x"] * half_w, "y": center["y"] + direction["y"] * half_l - perp["y"] * half_w},
            {"x": center["x"] + direction["x"] * half_l + perp["x"] * half_w, "y": center["y"] + direction["y"] * half_l + perp["y"] * half_w},
            {"x": center["x"] - direction["x"] * half_l + perp["x"] * half_w, "y": center["y"] - direction["y"] * half_l + perp["y"] * half_w},
        ]

    def _infer_office_model(self, entities: list[dict[str, Any]]) -> dict[str, Any]:
        tower_model = self._infer_gatehouse_office_model(entities)
        if tower_model.get("floors"):
            return tower_model

        container_seeds: list[dict[str, float]] = []
        container_related_seeds: list[dict[str, float]] = []
        level1_seeds: list[dict[str, float]] = []
        level2_seeds: list[dict[str, float]] = []
        level2_title_seeds: list[dict[str, float]] = []
        for entity in entities:
            if entity.get("entity_type") not in {"TEXT", "MTEXT"}:
                continue
            position = entity.get("geometry", {}).get("position")
            if not position:
                continue
            folded_position, _ = self._fold_point(position)
            raw_text = str(entity.get("text", "")).strip()
            text = re.sub(r"\s+", "", raw_text.upper())
            oa_match = re.fullmatch(r"OA-(\d{1,3})", text)
            bg_camera_match = re.fullmatch(r"BG-(\d{1,3})", text)
            bg_ap_match = re.fullmatch(r"(?:BFR|BGL)-[A-Z0-9-]+-BG-AP-(\d{1,3})", text)
            if "办公室" in raw_text and "集装箱" in raw_text:
                container_seeds.append(folded_position)
                container_related_seeds.append(folded_position)
            if self._rack_units_from_text(raw_text):
                container_related_seeds.append(folded_position)
            elif bg_camera_match or bg_ap_match:
                container_related_seeds.append(folded_position)

            if "42U机柜" in raw_text:
                level1_seeds.append(folded_position)
            elif bg_ap_match and int(bg_ap_match.group(1)) <= 2:
                level1_seeds.append(folded_position)
            elif bg_camera_match and int(bg_camera_match.group(1)) <= 3:
                level1_seeds.append(folded_position)
            elif oa_match and int(oa_match.group(1)) <= 5:
                level1_seeds.append(folded_position)
            elif "夹层" in raw_text and "防火分区" not in raw_text and ("办公" in raw_text or "办公室" in raw_text or "二层" in raw_text):
                level2_title_seeds.append(folded_position)
            elif bg_ap_match and int(bg_ap_match.group(1)) >= 3:
                level2_seeds.append(folded_position)
            elif oa_match and int(oa_match.group(1)) >= 6:
                level2_seeds.append(folded_position)

        if container_seeds:
            seeds = container_related_seeds or container_seeds
            container_geometry_bbox = self._office_bbox_from_seeds(entities, seeds)
            container_bbox = self._office_content_bbox_from_seeds(entities, seeds) or container_geometry_bbox
            if not container_bbox:
                container_bbox = {
                    "min_x": min(point["x"] for point in seeds) - 6000.0,
                    "min_y": min(point["y"] for point in seeds) - 4000.0,
                    "max_x": max(point["x"] for point in seeds) + 6000.0,
                    "max_y": max(point["y"] for point in seeds) + 4000.0,
                }
            floors = [
                {
                    "level": 1,
                    "label": "办公区（集装箱）",
                    "area_type": "area.office",
                    "floor_elevation_m": 0.0,
                    "room_height_m": OFFICE_CONTAINER_ROOM_HEIGHT_M,
                    "height_source": "container_office_cad_text",
                    "source_bbox": container_bbox,
                    "target_bbox": container_bbox,
                    "cad_geometry_bbox": container_geometry_bbox,
                    "footprint_source": "cad_geometry" if container_geometry_bbox else "text_seed_scope",
                    "render_as_scope": container_geometry_bbox is None,
                    "wall_geometry_reliable": container_geometry_bbox is not None,
                    "transform": {"dx": 0.0, "dy": 0.0},
                    "office_kind": "container",
                }
            ]
            office_model = {"floors": floors, "objects": []}
            office_model["objects"] = self._extract_office_objects(entities, office_model)
            return office_model

        level1_geometry_bbox = self._office_bbox_from_seeds(entities, level1_seeds)
        level2_geometry_bbox = self._office_bbox_from_seeds(entities, level2_seeds or level2_title_seeds)
        level1_bbox = self._office_content_bbox_from_seeds(entities, level1_seeds) or level1_geometry_bbox
        level2_bbox = self._office_content_bbox_from_seeds(entities, level2_seeds or level2_title_seeds) or level2_geometry_bbox
        level1_seed_bbox = self._points_bbox(level1_seeds) if level1_seeds else None
        level2_seed_bbox = self._points_bbox(level2_seeds or level2_title_seeds) if (level2_seeds or level2_title_seeds) else None
        if not level1_bbox:
            return {"floors": [], "objects": []}
        if not level2_bbox:
            floors = [
                {
                    "level": 1,
                    "label": "办公区一层",
                    "area_type": "area.office",
                    "floor_elevation_m": 0.0,
                    "room_height_m": OFFICE_ROOM_HEIGHT_M,
                    "height_source": "visual_clearance_exaggerated",
                    "source_bbox": level1_bbox,
                    "evidence_bbox": level1_bbox,
                    "seed_bbox": level1_seed_bbox,
                    "target_bbox": level1_bbox,
                    "cad_geometry_bbox": level1_geometry_bbox,
                    "footprint_source": "cad_geometry" if level1_geometry_bbox else "text_seed_scope",
                    "render_as_scope": level1_geometry_bbox is None,
                    "wall_geometry_reliable": level1_geometry_bbox is not None,
                    "transform": {"dx": 0.0, "dy": 0.0},
                }
            ]
            office_model = {"floors": floors, "objects": []}
            if not self._is_generic_mode():
                self._apply_generic_gatehouse_confirmed_floor_contract(floors)
            office_model["objects"] = self._extract_office_objects(entities, office_model)
            if not self._is_generic_mode():
                office_model["objects"] = self._tag_confirmed_gatehouse_office_objects(office_model["objects"], office_model)
                office_model["objects"] = self._apply_generic_gatehouse_generation_rules(office_model["objects"], office_model, entities)
            return office_model

        has_explicit_mezzanine_title = bool(level2_title_seeds)
        level2_transform = {"dx": 0.0, "dy": 0.0}
        level2_area_type = "area.office"
        level2_label = "办公区二"
        level2_elevation_m = OFFICE_SECOND_FLOOR_ELEVATION_M
        level2_height_source = "visual_clearance_exaggerated"
        if has_explicit_mezzanine_title:
            level1_center = self._bbox_center(level1_bbox)
            level2_center = self._bbox_center(level2_bbox)
            level2_transform = {
                "dx": level1_center["x"] - level2_center["x"],
                "dy": level1_center["y"] - level2_center["y"],
            }
            level2_area_type = "area.office.mezzanine"
            level2_label = "办公区二层（夹层）"
            level2_elevation_m = OFFICE_SECOND_FLOOR_ELEVATION_M
            level2_height_source = "visual_clearance_exaggerated"
        level2_target_bbox = self._transform_bbox(level2_bbox, level2_transform)
        floors = [
            {
                "level": 1,
                "label": "办公区一层",
                "area_type": "area.office",
                "floor_elevation_m": 0.0,
                "room_height_m": OFFICE_ROOM_HEIGHT_M,
                "height_source": "visual_clearance_exaggerated",
                "source_bbox": level1_bbox,
                "evidence_bbox": level1_bbox,
                "seed_bbox": level1_seed_bbox,
                "target_bbox": level1_bbox,
                "cad_geometry_bbox": level1_geometry_bbox,
                "footprint_source": "cad_geometry" if level1_geometry_bbox else "text_seed_scope",
                "render_as_scope": level1_geometry_bbox is None,
                "wall_geometry_reliable": level1_geometry_bbox is not None,
                "transform": {"dx": 0.0, "dy": 0.0},
            },
            {
                "level": 2,
                "label": level2_label,
                "area_type": level2_area_type,
                "floor_elevation_m": level2_elevation_m,
                "room_height_m": OFFICE_ROOM_HEIGHT_M,
                "height_source": level2_height_source,
                "source_bbox": level2_bbox,
                "evidence_bbox": level2_bbox,
                "seed_bbox": level2_seed_bbox,
                "target_bbox": level2_target_bbox,
                "cad_geometry_bbox": level2_geometry_bbox,
                "footprint_source": "cad_geometry" if level2_geometry_bbox else "text_seed_scope",
                "render_as_scope": level2_geometry_bbox is None,
                "wall_geometry_reliable": level2_geometry_bbox is not None,
                "transform": level2_transform,
            },
        ]
        office_model = {"floors": floors, "objects": []}
        if not self._is_generic_mode():
            self._apply_generic_gatehouse_confirmed_floor_contract(floors)
        office_model["objects"] = self._extract_office_objects(entities, office_model)
        if not self._is_generic_mode():
            office_model["objects"] = self._tag_confirmed_gatehouse_office_objects(office_model["objects"], office_model)
            office_model["objects"] = self._apply_generic_gatehouse_generation_rules(office_model["objects"], office_model, entities)
            office_model["objects"].extend(self._infer_conveyor_dws_objects(entities))
        return office_model

    def _infer_gatehouse_office_model(self, entities: list[dict[str, Any]]) -> dict[str, Any]:
        if not self._is_project_specific_context():
            return {"floors": [], "objects": []}
        tower_titles: dict[str, list[dict[str, float]]] = {"southwest": [], "northwest": []}
        floor_labels: list[dict[str, Any]] = []
        main_plan_footprints = self._gatehouse_main_plan_footprints(entities)
        device_scope_footprints = self._gatehouse_device_cluster_footprints(entities, (self.base_view or {}).get("bounds") or {})
        for entity in entities:
            if entity.get("entity_type") not in {"TEXT", "MTEXT"}:
                continue
            position = entity.get("geometry", {}).get("position")
            if not position:
                continue
            folded_position, _ = self._fold_point(position)
            raw_text = str(entity.get("text", "")).strip()
            text = re.sub(r"\s+", "", raw_text)
            if "西南炮楼" in text:
                tower_titles["southwest"].append(folded_position)
            elif "西北炮楼" in text:
                tower_titles["northwest"].append(folded_position)
            elif text in {"一层", "二层"}:
                floor_labels.append({"level": 1 if text == "一层" else 2, "position": folded_position})

        title_points = {
            key: self._dedup_points(points, bucket_mm=1_000.0)
            for key, points in tower_titles.items()
        }
        if not title_points["southwest"] and not title_points["northwest"]:
            return {"floors": [], "objects": []}

        floors: list[dict[str, Any]] = []
        for tower_key, tower_name in (("southwest", "西南炮楼"), ("northwest", "西北炮楼")):
            if not title_points[tower_key]:
                continue
            title = title_points[tower_key][0]
            nearby_labels = [
                label
                for label in floor_labels
                if abs(float(label["position"]["x"]) - float(title["x"])) <= 70_000.0
                and abs(float(label["position"]["y"]) - float(title["y"])) <= 70_000.0
            ]
            by_level: dict[int, dict[str, Any]] = {}
            for level in (1, 2):
                candidates = [label for label in nearby_labels if label["level"] == level]
                if not candidates:
                    continue
                candidates.sort(key=lambda item: self._distance(item["position"], title))
                by_level[level] = candidates[0]
            if not by_level:
                continue

            floor_sources: dict[int, dict[str, Any]] = {}
            for level, label in by_level.items():
                seed = label["position"]
                geometry_bbox = self._office_detail_bbox_from_seed(entities, seed)
                content_bbox = self._office_detail_content_bbox_from_seed(entities, seed)
                layout_bbox = self._office_detail_layout_bbox_from_seed(entities, seed)
                source_bbox = content_bbox or layout_bbox or geometry_bbox
                if not source_bbox:
                    continue
                floor_sources[level] = {
                    "seed": seed,
                    "source_bbox": source_bbox,
                    "cad_geometry_bbox": geometry_bbox,
                    "layout_bbox": layout_bbox,
                }
            if not floor_sources:
                continue

            target_source = floor_sources.get(1) or floor_sources.get(2)
            has_main_plan_footprint = tower_key in main_plan_footprints
            target_bbox = dict(main_plan_footprints.get(tower_key) or target_source["source_bbox"])
            if not has_main_plan_footprint and any(source.get("layout_bbox") for source in floor_sources.values()):
                target_bbox = self._gatehouse_normalized_target_bbox(target_bbox)
            # Device labels can sit on virtual extension lines; keep them as evidence, not as the physical footprint.
            target_device_bbox = dict(device_scope_footprints.get(tower_key) or target_bbox)
            target_center = self._bbox_center(target_bbox)
            for level in (1, 2):
                source = floor_sources.get(level)
                if not source:
                    continue
                target_span_x = max(target_bbox["max_x"] - target_bbox["min_x"], 1.0)
                target_span_y = max(target_bbox["max_y"] - target_bbox["min_y"], 1.0)
                transform_source_bbox = (
                    source.get("layout_bbox")
                    or (source["cad_geometry_bbox"] if has_main_plan_footprint and source["cad_geometry_bbox"] else None)
                    or source["source_bbox"]
                )
                source_center = self._bbox_center(transform_source_bbox)
                source_span_x = max(transform_source_bbox["max_x"] - transform_source_bbox["min_x"], 1.0)
                source_span_y = max(transform_source_bbox["max_y"] - transform_source_bbox["min_y"], 1.0)
                transform = {
                    "dx": target_center["x"] - source_center["x"],
                    "dy": target_center["y"] - source_center["y"],
                    "source_center_x": source_center["x"],
                    "source_center_y": source_center["y"],
                    "target_center_x": target_center["x"],
                    "target_center_y": target_center["y"],
                    "scale_x": target_span_x / source_span_x if has_main_plan_footprint else 1.0,
                    "scale_y": target_span_y / source_span_y if has_main_plan_footprint else 1.0,
                }
                label = f"{tower_name}{'一层' if level == 1 else '二层'}"
                target_floor_bbox = (
                    target_bbox
                    if has_main_plan_footprint or (level > 1 and 1 in floor_sources)
                    else self._transform_bbox(source["source_bbox"], transform)
                )
                floors.append(
                    {
                        "id": f"{tower_key}_level_{level}",
                        "tower": tower_key,
                        "tower_label": tower_name,
                        "level": level,
                        "label": label,
                        "area_type": "area.office" if level == 1 else "area.office.mezzanine",
                        "floor_elevation_m": 0.0 if level == 1 else OFFICE_SECOND_FLOOR_ELEVATION_M,
                        "room_height_m": OFFICE_ROOM_HEIGHT_M,
                        "height_source": "gatehouse_cad_floor_detail",
                        "source_bbox": source["source_bbox"],
                        "target_bbox": target_floor_bbox,
                        "target_device_bbox": target_device_bbox,
                        "cad_geometry_bbox": source["cad_geometry_bbox"],
                        "layout_bbox": source.get("layout_bbox"),
                        "footprint_source": "cad_gatehouse_main_plan_footprint" if has_main_plan_footprint else "cad_gatehouse_floor_detail",
                        "render_as_scope": source["cad_geometry_bbox"] is None,
                        "wall_geometry_reliable": source["cad_geometry_bbox"] is not None,
                        "transform": transform,
                        "stacking_source": "same_gatehouse_footprint" if level > 1 and 1 in floor_sources else "source_floor_footprint",
                        "floor_seed": source["seed"],
                    }
                )

        if len(floors) < 2:
            return {"floors": [], "objects": []}
        office_model = {"floors": floors, "objects": []}
        office_model["objects"] = self._apply_gatehouse_confirmed_layout_rules(
            self._extract_office_objects(entities, office_model),
            office_model,
        )
        office_model["objects"].extend(self._infer_conveyor_dws_objects(entities))
        return office_model

    def _gatehouse_main_plan_footprints(self, entities: list[dict[str, Any]]) -> dict[str, dict[str, float]]:
        bounds = (self.base_view or {}).get("bounds") or {}
        if not bounds:
            return {}
        min_x = float(bounds.get("min_x", 0.0))
        max_x = float(bounds.get("max_x", 0.0))
        min_y = float(bounds.get("min_y", 0.0))
        max_y = float(bounds.get("max_y", 0.0))
        explicit = self._gatehouse_explicit_main_plan_footprints(entities, bounds)
        left_limit = min_x + max((max_x - min_x) * 0.24, 60_000.0)
        points: list[dict[str, float]] = []
        for entity in entities:
            if entity.get("entity_type") not in {"LINE", "LWPOLYLINE", "POLYLINE"}:
                continue
            if str(entity.get("layer", "")) != "A-SECT-钢柱":
                continue
            anchor = self._geometry_anchor(entity.get("geometry") or {})
            if not anchor or self._plan_copy_index(anchor) is None:
                continue
            for point in self._office_geometry_points(entity):
                if min_x <= point["x"] <= left_limit and min_y <= point["y"] <= max_y:
                    points.append(point)
        points = self._dedup_points(points, bucket_mm=50.0)
        if len(points) < 8:
            return explicit

        clusters: list[list[dict[str, float]]] = []
        for point in sorted(points, key=lambda item: item["y"]):
            if not clusters or point["y"] - clusters[-1][-1]["y"] > 25_000.0:
                clusters.append([point])
            else:
                clusters[-1].append(point)

        candidates: list[dict[str, Any]] = []
        for cluster in clusters:
            bbox = self._points_bbox(cluster)
            span_x = bbox["max_x"] - bbox["min_x"]
            span_y = bbox["max_y"] - bbox["min_y"]
            if not (8_000.0 <= span_x <= 25_000.0 and 8_000.0 <= span_y <= 25_000.0):
                continue
            if len(cluster) < 8:
                continue
            pad = 250.0
            candidates.append(
                {
                    "center_y": (bbox["min_y"] + bbox["max_y"]) / 2.0,
                    "bbox": {
                        "min_x": bbox["min_x"] - pad,
                        "min_y": bbox["min_y"] - pad,
                        "max_x": bbox["max_x"] + pad,
                        "max_y": bbox["max_y"] + pad,
                    },
                }
            )
        if len(candidates) < 2:
            return explicit
        mount_x = self._gatehouse_left_mount_x(entities, min_y, max_y)
        if mount_x is not None:
            adjusted: list[dict[str, Any]] = []
            for candidate in candidates:
                bbox = dict(candidate["bbox"])
                width = bbox["max_x"] - bbox["min_x"]
                if 8_000.0 <= width <= 25_000.0 and bbox["max_x"] < mount_x - 3_000.0:
                    bbox["max_x"] = mount_x
                    bbox["min_x"] = mount_x - width
                    candidate = {**candidate, "bbox": bbox, "right_edge_source": "left_cw_camera_mount_line"}
                adjusted.append(candidate)
            candidates = adjusted
        candidates.sort(key=lambda item: item["center_y"])
        fallback = {
            "southwest": dict(candidates[0]["bbox"]),
            "northwest": dict(candidates[-1]["bbox"]),
        }
        fallback.update(explicit)
        return fallback

    def _gatehouse_explicit_main_plan_footprints(
        self,
        entities: list[dict[str, Any]],
        bounds: dict[str, Any],
    ) -> dict[str, dict[str, float]]:
        min_x = float(bounds.get("min_x", 0.0))
        max_x = float(bounds.get("max_x", 0.0))
        min_y = float(bounds.get("min_y", 0.0))
        max_y = float(bounds.get("max_y", 0.0))
        mid_y = (min_y + max_y) / 2.0
        left_limit = min_x + max((max_x - min_x) * 0.26, 80_000.0)
        mount_x = self._gatehouse_left_mount_x(entities, min_y, max_y)
        physical_min_x = mount_x - 9_000.0 if mount_x is not None else min_x
        anchors: dict[str, list[dict[str, float]]] = {"southwest": [], "northwest": []}
        for entity in entities:
            if entity.get("entity_type") not in {"TEXT", "MTEXT"}:
                continue
            position = entity.get("geometry", {}).get("position")
            if not position:
                continue
            folded, _ = self._fold_point(position)
            x = float(folded["x"])
            y = float(folded["y"])
            if not (min_x <= x <= max_x and min_y <= y <= max_y):
                continue
            raw_text = str(entity.get("text", ""))
            compact = re.sub(r"\s+", "", raw_text.upper())
            is_machine_room = (
                "42U机柜" in raw_text
                or "UPS电源" in raw_text
                or re.search(r"(?:^|[;\\}])机房(?:$|[\\{;])", raw_text) is not None
                or compact in {"机房", "\\PXI-3,L4,T4;42U机柜", "\\PXI-3,L4,T4;UPS电源"}
            )
            if is_machine_room and y < mid_y and x <= left_limit:
                anchors["southwest"].append({"x": x, "y": y})
                continue
            is_physical_gatehouse_anchor = physical_min_x <= x <= left_limit
            is_upper_main_plan_anchor = (
                y > mid_y
                and is_physical_gatehouse_anchor
                and (
                    "会议室" in raw_text
                    or "钢化玻璃隔断" in raw_text
                    or "空调小室" in raw_text
                    or re.fullmatch(r"BG-?\d{1,3}", compact) is not None
                    or (AP_LABEL_PATTERN.fullmatch(compact) and "-BG-AP-" in compact)
                )
            )
            if is_upper_main_plan_anchor:
                anchors["northwest"].append({"x": x, "y": y})

        result: dict[str, dict[str, float]] = {}
        for tower_key, points in anchors.items():
            if not points:
                continue
            seed = self._bbox_center(self._points_bbox(points))
            bbox = self._gatehouse_wall_bbox_from_seed(entities, seed, bounds)
            if bbox:
                result[tower_key] = bbox
        return result

    def _gatehouse_device_cluster_footprints(
        self,
        entities: list[dict[str, Any]],
        bounds: dict[str, Any],
    ) -> dict[str, dict[str, float]]:
        min_x = float(bounds.get("min_x", 0.0))
        max_x = float(bounds.get("max_x", 0.0))
        min_y = float(bounds.get("min_y", 0.0))
        max_y = float(bounds.get("max_y", 0.0))
        mid_y = (min_y + max_y) / 2.0
        left_limit = min_x + max((max_x - min_x) * 0.28, 90_000.0)
        clusters: dict[str, list[dict[str, float]]] = {"southwest": [], "northwest": []}
        for entity in entities:
            if entity.get("entity_type") not in {"TEXT", "MTEXT"}:
                continue
            position = entity.get("geometry", {}).get("position")
            if not position:
                continue
            folded, _ = self._fold_point(position)
            x = float(folded["x"])
            y = float(folded["y"])
            if not (min_x <= x <= left_limit and min_y <= y <= max_y):
                continue
            if not self._is_gatehouse_main_plan_device_label(str(entity.get("text", ""))):
                continue
            clusters["southwest" if y < mid_y else "northwest"].append({"x": x, "y": y})

        result: dict[str, dict[str, float]] = {}
        for tower_key, points in clusters.items():
            points = self._dedup_points(points, bucket_mm=400.0)
            if len(points) < 3:
                continue
            bbox = self._points_bbox(points)
            bbox = {
                "min_x": bbox["min_x"] - 2_500.0,
                "min_y": bbox["min_y"] - 2_500.0,
                "max_x": bbox["max_x"] + 2_500.0,
                "max_y": bbox["max_y"] + 2_500.0,
            }
            span_x = bbox["max_x"] - bbox["min_x"]
            span_y = bbox["max_y"] - bbox["min_y"]
            if not (12_000.0 <= span_x <= 55_000.0 and 10_000.0 <= span_y <= 38_000.0):
                continue
            result[tower_key] = bbox
        return result

    @staticmethod
    def _is_gatehouse_main_plan_device_label(raw_text: str) -> bool:
        compact = re.sub(r"\s+", "", raw_text.upper())
        if re.fullmatch(r"BG-\d{1,3}", compact):
            return True
        if AP_LABEL_PATTERN.fullmatch(compact) and "-BG-AP-" in compact:
            return True
        return compact in {"机房", "42U机柜", "UPS电源"}

    @staticmethod
    def _is_office_auxiliary_line_entity(entity: dict[str, Any]) -> bool:
        if entity.get("entity_type") not in {"LINE", "LWPOLYLINE", "POLYLINE"}:
            return False
        linetypes = " ".join(
            str(entity.get(key) or "").upper()
            for key in ("linetype", "layer_linetype")
        )
        return any(token in linetypes for token in OFFICE_AUXILIARY_LINETYPE_TOKENS)

    def _gatehouse_wall_bbox_from_seed(
        self,
        entities: list[dict[str, Any]],
        seed: dict[str, float],
        bounds: dict[str, Any],
    ) -> dict[str, float] | None:
        points: list[dict[str, float]] = []
        vertical_wall_xs: list[float] = []
        for entity in entities:
            entity_type = entity.get("entity_type")
            layer = str(entity.get("layer", ""))
            if entity_type not in {"LINE", "LWPOLYLINE", "POLYLINE"}:
                continue
            if layer not in OFFICE_PARTITION_LAYERS:
                continue
            if self._is_office_auxiliary_line_entity(entity):
                continue
            entity_points = [
                point
                for point in self._office_geometry_points(entity)
                if self._point_in_bbox(point, bounds, 0.0)
            ]
            if not entity_points:
                continue
            if not self._near_any_seed(
                seed,
                entity_points,
                GATEHOUSE_MAIN_PLAN_SEARCH_RADIUS_X_MM,
                GATEHOUSE_MAIN_PLAN_SEARCH_RADIUS_Y_MM,
            ):
                continue
            points.extend(entity_points)
            for start, end in zip(entity_points, entity_points[1:]):
                dx = abs(float(start["x"]) - float(end["x"]))
                dy = abs(float(start["y"]) - float(end["y"]))
                if dx <= 25.0 and dy >= GATEHOUSE_MAIN_PLAN_LONG_WALL_MIN_MM:
                    vertical_wall_xs.extend([float(start["x"]), float(end["x"])])
        points = self._dedup_points(points, bucket_mm=80.0)
        if len(points) < 8:
            return None
        raw_bbox = {
            "min_x": min(point["x"] for point in points),
            "min_y": min(point["y"] for point in points),
            "max_x": max(point["x"] for point in points),
            "max_y": max(point["y"] for point in points),
        }
        if vertical_wall_xs:
            right_wall_x = max(vertical_wall_xs)
            if raw_bbox["max_x"] - right_wall_x > GATEHOUSE_MAIN_PLAN_PROTRUSION_CLIP_MM:
                raw_bbox["max_x"] = right_wall_x
            left_wall_x = min(vertical_wall_xs)
            if left_wall_x - raw_bbox["min_x"] > GATEHOUSE_MAIN_PLAN_PROTRUSION_CLIP_MM:
                raw_bbox["min_x"] = left_wall_x
        bbox = {
            "min_x": raw_bbox["min_x"] - GATEHOUSE_FOOTPRINT_PAD_MM,
            "min_y": raw_bbox["min_y"] - GATEHOUSE_FOOTPRINT_PAD_MM,
            "max_x": raw_bbox["max_x"] + GATEHOUSE_FOOTPRINT_PAD_MM,
            "max_y": raw_bbox["max_y"] + GATEHOUSE_FOOTPRINT_PAD_MM,
        }
        span_x = bbox["max_x"] - bbox["min_x"]
        span_y = bbox["max_y"] - bbox["min_y"]
        if not (8_000.0 <= span_x <= 22_000.0 and 8_000.0 <= span_y <= 22_000.0):
            return None
        return bbox

    def _gatehouse_left_mount_x(
        self,
        entities: list[dict[str, Any]],
        min_y: float,
        max_y: float,
    ) -> float | None:
        xs: list[float] = []
        for entity in entities:
            if entity.get("entity_type") not in {"TEXT", "MTEXT"}:
                continue
            raw_text = str(entity.get("text", ""))
            text = re.sub(r"\s+", "", raw_text.upper())
            if not re.fullmatch(r"CW-?\d{1,3}", text):
                continue
            position = entity.get("geometry", {}).get("position")
            if not position:
                continue
            folded, _ = self._fold_point(position)
            if min_y <= float(folded["y"]) <= max_y:
                xs.append(float(folded["x"]))
        if len(xs) < 8:
            return None
        xs.sort()
        mid = len(xs) // 2
        median = xs[mid] if len(xs) % 2 else (xs[mid - 1] + xs[mid]) / 2.0
        if max(xs) - min(xs) > 10_000.0:
            return None
        return median

    @staticmethod
    def _dedup_points(points: list[dict[str, float]], bucket_mm: float = 1_000.0) -> list[dict[str, float]]:
        deduped: list[dict[str, float]] = []
        seen: set[tuple[int, int]] = set()
        for point in points:
            key = (round(float(point["x"]) / bucket_mm), round(float(point["y"]) / bucket_mm))
            if key in seen:
                continue
            seen.add(key)
            deduped.append({"x": float(point["x"]), "y": float(point["y"])})
        return deduped

    def _office_bbox_from_seeds(self, entities: list[dict[str, Any]], seeds: list[dict[str, float]]) -> dict[str, float] | None:
        if not seeds:
            return None
        points: list[dict[str, float]] = []
        for entity in entities:
            if entity.get("entity_type") not in {"LINE", "LWPOLYLINE", "POLYLINE", "INSERT", "CIRCLE"}:
                continue
            layer = str(entity.get("layer", ""))
            block = str(entity.get("block_name", ""))
            if self._is_office_auxiliary_line_entity(entity):
                continue
            if layer not in OFFICE_GEOMETRY_LAYERS and block not in OFFICE_WORKSTATION_BLOCKS:
                continue
            folded_points = self._office_geometry_points(entity)
            if not folded_points:
                continue
            for point in folded_points:
                if any(
                    abs(point["x"] - seed["x"]) <= OFFICE_SEARCH_RADIUS_X_MM
                    and abs(point["y"] - seed["y"]) <= OFFICE_SEARCH_RADIUS_Y_MM
                    for seed in seeds
                ):
                    points.append(point)
        if len(points) < 4:
            return None
        return {
            "min_x": min(point["x"] for point in points) - OFFICE_BBOX_PAD_MM,
            "min_y": min(point["y"] for point in points) - OFFICE_BBOX_PAD_MM,
            "max_x": max(point["x"] for point in points) + OFFICE_BBOX_PAD_MM,
            "max_y": max(point["y"] for point in points) + OFFICE_BBOX_PAD_MM,
        }

    def _office_content_bbox_from_seeds(self, entities: list[dict[str, Any]], seeds: list[dict[str, float]]) -> dict[str, float] | None:
        if not seeds:
            return None
        points: list[dict[str, float]] = list(seeds)
        for entity in entities:
            entity_type = entity.get("entity_type")
            if self._is_office_auxiliary_line_entity(entity):
                continue
            if entity_type in {"TEXT", "MTEXT"}:
                raw_text = str(entity.get("text", "")).strip()
                text = re.sub(r"\s+", "", raw_text.upper())
                is_office_text = (
                    text.startswith("OA-")
                    or text.startswith("BG-")
                    or "-BG-AP-" in text
                    or self._rack_units_from_text(raw_text) is not None
                    or "办公室" in raw_text
                    or "夹层" in raw_text
                )
                if not is_office_text:
                    continue
            elif entity_type == "INSERT" and str(entity.get("block_name", "")) in OFFICE_WORKSTATION_BLOCKS:
                pass
            else:
                continue

            folded_points = self._office_geometry_points(entity)
            for point in folded_points:
                if self._near_any_seed(point, seeds, OFFICE_SEARCH_RADIUS_X_MM, OFFICE_SEARCH_RADIUS_Y_MM):
                    points.append(point)
        if len(points) < 2:
            return None
        return {
            "min_x": min(point["x"] for point in points) - OFFICE_FOOTPRINT_PAD_MM,
            "min_y": min(point["y"] for point in points) - OFFICE_FOOTPRINT_PAD_MM,
            "max_x": max(point["x"] for point in points) + OFFICE_FOOTPRINT_PAD_MM,
            "max_y": max(point["y"] for point in points) + OFFICE_FOOTPRINT_PAD_MM,
        }

    def _office_detail_bbox_from_seed(self, entities: list[dict[str, Any]], seed: dict[str, float]) -> dict[str, float] | None:
        points: list[dict[str, float]] = []
        for entity in entities:
            entity_type = entity.get("entity_type")
            layer = str(entity.get("layer", ""))
            block = str(entity.get("block_name", ""))
            if self._is_office_auxiliary_line_entity(entity):
                continue
            if entity_type == "INSERT" and block in OFFICE_WORKSTATION_BLOCKS:
                pass
            elif entity_type in {"LINE", "LWPOLYLINE", "POLYLINE"} and layer in OFFICE_PARTITION_LAYERS:
                pass
            elif entity_type in {"TEXT", "MTEXT"} and self._is_office_detail_text(str(entity.get("text", ""))):
                pass
            else:
                continue
            for point in self._office_geometry_points(entity):
                if abs(point["x"] - seed["x"]) <= 24_000.0 and abs(point["y"] - seed["y"]) <= 32_000.0:
                    points.append(point)
        if len(points) < 2:
            return None
        return {
            "min_x": min(point["x"] for point in points) - OFFICE_BBOX_PAD_MM,
            "min_y": min(point["y"] for point in points) - OFFICE_BBOX_PAD_MM,
            "max_x": max(point["x"] for point in points) + OFFICE_BBOX_PAD_MM,
            "max_y": max(point["y"] for point in points) + OFFICE_BBOX_PAD_MM,
        }

    def _office_detail_content_bbox_from_seed(self, entities: list[dict[str, Any]], seed: dict[str, float]) -> dict[str, float] | None:
        points: list[dict[str, float]] = [seed]
        for entity in entities:
            entity_type = entity.get("entity_type")
            block = str(entity.get("block_name", ""))
            if self._is_office_auxiliary_line_entity(entity):
                continue
            if entity_type == "INSERT" and block in OFFICE_WORKSTATION_BLOCKS:
                pass
            elif entity_type in {"TEXT", "MTEXT"} and self._is_office_detail_text(str(entity.get("text", ""))):
                pass
            else:
                continue
            for point in self._office_geometry_points(entity):
                if abs(point["x"] - seed["x"]) <= 24_000.0 and abs(point["y"] - seed["y"]) <= 32_000.0:
                    points.append(point)
        if len(points) < 2:
            return None
        return {
            "min_x": min(point["x"] for point in points) - OFFICE_FOOTPRINT_PAD_MM,
            "min_y": min(point["y"] for point in points) - OFFICE_FOOTPRINT_PAD_MM,
            "max_x": max(point["x"] for point in points) + OFFICE_FOOTPRINT_PAD_MM,
            "max_y": max(point["y"] for point in points) + OFFICE_FOOTPRINT_PAD_MM,
        }

    def _office_detail_layout_bbox_from_seed(self, entities: list[dict[str, Any]], seed: dict[str, float]) -> dict[str, float] | None:
        layer_points: defaultdict[str, list[dict[str, float]]] = defaultdict(list)
        candidate_layers = {
            "A-SECT-钢柱",
            "A-SECT-洁具",
            "A-SECT-门窗",
            "A-SECT-门窗(防火)",
            "A-SECT-墙体",
            "A-SECT-幕墙",
        }
        for entity in entities:
            entity_type = entity.get("entity_type")
            if entity_type not in {"LINE", "LWPOLYLINE", "POLYLINE", "INSERT"}:
                continue
            if self._is_office_auxiliary_line_entity(entity):
                continue
            layer = str(entity.get("layer", ""))
            block = str(entity.get("block_name", ""))
            if layer not in candidate_layers and block not in OFFICE_WORKSTATION_BLOCKS:
                continue
            points = self._office_geometry_points(entity)
            if not points:
                continue
            if not any(abs(point["x"] - seed["x"]) <= 20_000.0 and abs(point["y"] - seed["y"]) <= 32_000.0 for point in points):
                continue
            key = layer if layer in candidate_layers else f"block:{block}"
            layer_points[key].extend(points)

        candidates: list[tuple[float, dict[str, float], str]] = []
        for key, points in layer_points.items():
            if len(points) < 4:
                continue
            bbox = self._points_bbox(points)
            span_x = bbox["max_x"] - bbox["min_x"]
            span_y = bbox["max_y"] - bbox["min_y"]
            if (
                abs(span_x - GATEHOUSE_DETAIL_WIDTH_MM) <= GATEHOUSE_DETAIL_DIM_TOLERANCE_MM
                and abs(span_y - GATEHOUSE_DETAIL_DEPTH_MM) <= GATEHOUSE_DETAIL_DIM_TOLERANCE_MM
            ):
                layer_penalty = 0.0 if key in {"A-SECT-钢柱", "A-SECT-墙体", "A-SECT-洁具"} else 350.0
                score = abs(span_x - GATEHOUSE_DETAIL_WIDTH_MM) + abs(span_y - GATEHOUSE_DETAIL_DEPTH_MM) + layer_penalty
                candidates.append((score, bbox, key))

        if not candidates:
            return None
        candidates.sort(key=lambda item: item[0])
        return candidates[0][1]

    @staticmethod
    def _gatehouse_normalized_target_bbox(target_bbox: dict[str, float]) -> dict[str, float]:
        center_x = (float(target_bbox["min_x"]) + float(target_bbox["max_x"])) / 2.0
        center_y = (float(target_bbox["min_y"]) + float(target_bbox["max_y"])) / 2.0
        half_x = GATEHOUSE_DETAIL_WIDTH_MM / 2.0
        half_y = GATEHOUSE_DETAIL_DEPTH_MM / 2.0
        return {
            "min_x": center_x - half_x,
            "min_y": center_y - half_y,
            "max_x": center_x + half_x,
            "max_y": center_y + half_y,
        }

    @staticmethod
    def _valid_bbox(bbox: dict[str, Any] | None) -> bool:
        return bool(bbox) and {"min_x", "min_y", "max_x", "max_y"} <= set(bbox)

    @staticmethod
    def _bbox_span(bbox: dict[str, float]) -> tuple[float, float]:
        return (
            max(float(bbox["max_x"]) - float(bbox["min_x"]), 0.0),
            max(float(bbox["max_y"]) - float(bbox["min_y"]), 0.0),
        )

    @staticmethod
    def _centered_bbox(center: dict[str, float], width_mm: float, depth_mm: float) -> dict[str, float]:
        half_x = max(width_mm, 1.0) / 2.0
        half_y = max(depth_mm, 1.0) / 2.0
        return {
            "min_x": float(center["x"]) - half_x,
            "min_y": float(center["y"]) - half_y,
            "max_x": float(center["x"]) + half_x,
            "max_y": float(center["y"]) + half_y,
        }

    def _generic_gatehouse_physical_bbox(self, floor: dict[str, Any]) -> tuple[dict[str, float] | None, str]:
        evidence_bbox = floor.get("evidence_bbox") or floor.get("source_bbox")
        geometry_bbox = floor.get("cad_geometry_bbox")
        seed_bbox = floor.get("seed_bbox")
        center_source = seed_bbox if self._valid_bbox(seed_bbox) else geometry_bbox if self._valid_bbox(geometry_bbox) else evidence_bbox
        if not self._valid_bbox(center_source):
            return None, "missing_gatehouse_footprint_evidence"

        center = self._bbox_center(center_source)
        width = GATEHOUSE_DETAIL_WIDTH_MM
        depth = GATEHOUSE_DETAIL_DEPTH_MM
        source = "cad_gatehouse_confirmed_seed_normalized_footprint"

        if self._valid_bbox(seed_bbox):
            seed_span_x, seed_span_y = self._bbox_span(seed_bbox)
            width = max(width, seed_span_x + GENERIC_GATEHOUSE_SEED_PAD_MM * 2.0)
            depth = max(depth, seed_span_y + GENERIC_GATEHOUSE_SEED_PAD_MM * 2.0)

        if self._valid_bbox(geometry_bbox):
            span_x, span_y = self._bbox_span(geometry_bbox)
            geometry_plausible = (
                GENERIC_GATEHOUSE_MIN_FOOTPRINT_SPAN_MM <= span_x <= GENERIC_GATEHOUSE_MAX_FOOTPRINT_SPAN_MM
                and GENERIC_GATEHOUSE_MIN_FOOTPRINT_SPAN_MM <= span_y <= GENERIC_GATEHOUSE_MAX_FOOTPRINT_SPAN_MM
            )
            if geometry_plausible:
                width = max(width, span_x + GATEHOUSE_FOOTPRINT_PAD_MM * 2.0)
                depth = max(depth, span_y + GATEHOUSE_FOOTPRINT_PAD_MM * 2.0)
                source = "cad_gatehouse_confirmed_local_geometry"
            else:
                source = "cad_gatehouse_confirmed_seed_normalized_footprint"

        width = min(max(width, GENERIC_GATEHOUSE_MIN_FOOTPRINT_SPAN_MM), GENERIC_GATEHOUSE_MAX_FOOTPRINT_SPAN_MM)
        depth = min(max(depth, GENERIC_GATEHOUSE_MIN_FOOTPRINT_SPAN_MM), GENERIC_GATEHOUSE_MAX_FOOTPRINT_SPAN_MM)
        return self._centered_bbox(center, width, depth), source

    @staticmethod
    def _is_office_detail_text(raw_text: str) -> bool:
        text = re.sub(r"\s+", "", str(raw_text or "").upper())
        return (
            text in {"一层", "二层"}
            or "炮楼" in raw_text
            or "办公室" in raw_text
            or "办公" in raw_text
            or "会议室" in raw_text
            or "洽谈室" in raw_text
            or "机房" in raw_text
            or "空调小室" in raw_text
            or text.startswith("OA-")
            or text.startswith("BG-")
            or "-BG-AP-" in text
            or "U机柜" in raw_text
        )

    def _apply_generic_gatehouse_confirmed_floor_contract(self, floors: list[dict[str, Any]]) -> None:
        levels = {int(floor.get("level", 0) or 0): floor for floor in floors}
        if 1 not in levels or 2 not in levels:
            return
        if any(floor.get("office_kind") == "container" for floor in floors):
            return
        if self._is_no_main_plan_mode() and self._system_views_are_title_fallback_only():
            return

        base_floor = levels[1]
        physical_bboxes: dict[int, dict[str, float]] = {}
        footprint_sources: dict[int, str] = {}
        for level, floor in levels.items():
            if level not in {1, 2}:
                continue
            physical_bbox, footprint_source = self._generic_gatehouse_physical_bbox(floor)
            if not physical_bbox:
                continue
            physical_bboxes[level] = physical_bbox
            footprint_sources[level] = footprint_source

        base_bbox = physical_bboxes.get(1) or dict(base_floor.get("target_bbox") or base_floor.get("source_bbox") or {})
        if not self._valid_bbox(base_bbox):
            return

        for level, floor in levels.items():
            if level not in {1, 2}:
                continue
            source_physical_bbox = physical_bboxes.get(level)
            if source_physical_bbox:
                floor["source_bbox"] = source_physical_bbox
                floor["layout_bbox"] = source_physical_bbox
                floor["target_bbox"] = source_physical_bbox
                floor["physical_footprint_source"] = footprint_sources.get(level)
                floor["footprint_source"] = footprint_sources.get(level) or floor.get("footprint_source")
                if footprint_sources.get(level) == "cad_gatehouse_confirmed_seed_normalized_footprint":
                    floor["render_as_scope"] = True
                    floor["wall_geometry_reliable"] = False
            floor.setdefault("id", f"{GENERIC_GATEHOUSE_TOWER_KEY}_level_{level}")
            floor.setdefault("tower", GENERIC_GATEHOUSE_TOWER_KEY)
            floor.setdefault("tower_label", GENERIC_GATEHOUSE_TOWER_LABEL)
            floor["ruleset_id"] = GATEHOUSE_CONFIRMED_RULESET_ID
            floor["ruleset_name"] = GATEHOUSE_CONFIRMED_RULESET_NAME
            floor["layer_filter_contract"] = "tower_level_controls_devices_ap_coverage_labels_and_office_objects"
            if level != 2:
                continue

            source_bbox = dict(floor.get("source_bbox") or floor.get("target_bbox") or {})
            if not self._valid_bbox(source_bbox):
                continue
            source_center = self._bbox_center(source_bbox)
            target_center = self._bbox_center(base_bbox)
            source_span_x = max(float(source_bbox["max_x"]) - float(source_bbox["min_x"]), 1.0)
            source_span_y = max(float(source_bbox["max_y"]) - float(source_bbox["min_y"]), 1.0)
            target_span_x = max(float(base_bbox["max_x"]) - float(base_bbox["min_x"]), 1.0)
            target_span_y = max(float(base_bbox["max_y"]) - float(base_bbox["min_y"]), 1.0)
            floor["target_bbox"] = dict(base_bbox)
            floor["stacking_source"] = "same_gatehouse_footprint"
            floor["footprint_source"] = "cad_gatehouse_confirmed_generic_footprint"
            floor["transform"] = {
                "dx": target_center["x"] - source_center["x"],
                "dy": target_center["y"] - source_center["y"],
                "source_center_x": source_center["x"],
                "source_center_y": source_center["y"],
                "target_center_x": target_center["x"],
                "target_center_y": target_center["y"],
                "scale_x": target_span_x / source_span_x,
                "scale_y": target_span_y / source_span_y,
            }

    @staticmethod
    def _confirmed_gatehouse_floors(office_model: dict[str, Any] | None) -> list[dict[str, Any]]:
        if not office_model:
            return []
        return [
            floor
            for floor in office_model.get("floors", [])
            if (
                floor.get("ruleset_id") == GATEHOUSE_CONFIRMED_RULESET_ID
                or (floor.get("tower") in {"southwest", "northwest"} and floor.get("id"))
            )
        ]

    def _tag_confirmed_gatehouse_office_objects(
        self,
        objects: list[dict[str, Any]],
        office_model: dict[str, Any],
    ) -> list[dict[str, Any]]:
        floors = self._confirmed_gatehouse_floors(office_model)
        if not floors:
            return objects
        by_id = {str(floor.get("id")): floor for floor in floors if floor.get("id")}
        by_level = {int(floor.get("level", 0) or 0): floor for floor in floors}
        tagged: list[dict[str, Any]] = []
        for item in objects:
            attrs = dict(item.get("attributes") or {})
            floor = by_id.get(str(attrs.get("floor_id") or "")) or by_level.get(int(attrs.get("level", 0) or 0))
            if not floor:
                tagged.append(item)
                continue
            normalized = dict(item)
            attrs.update(
                {
                    "ruleset_id": GATEHOUSE_CONFIRMED_RULESET_ID,
                    "ruleset_name": GATEHOUSE_CONFIRMED_RULESET_NAME,
                    "floor_id": floor.get("id"),
                    "tower": floor.get("tower"),
                    "tower_label": floor.get("tower_label"),
                    "level": floor.get("level"),
                    "floor_label": floor.get("label"),
                    "floor_elevation_m": floor.get("floor_elevation_m", attrs.get("floor_elevation_m", 0.0)),
                    "room_height_m": floor.get("room_height_m", attrs.get("room_height_m", OFFICE_ROOM_HEIGHT_M)),
                }
            )
            normalized["attributes"] = attrs
            tagged.append(normalized)
        return tagged

    def _apply_generic_gatehouse_generation_rules(
        self,
        objects: list[dict[str, Any]],
        office_model: dict[str, Any],
        entities: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        floors = [
            floor
            for floor in self._confirmed_gatehouse_floors(office_model)
            if floor.get("tower") == GENERIC_GATEHOUSE_TOWER_KEY
        ]
        if not floors:
            return objects

        generated: list[dict[str, Any]] = []
        by_level = {int(floor.get("level", 0) or 0): floor for floor in floors}
        for floor in floors:
            floor.setdefault("furniture_generation_policy", "cad_only_no_inventory_workstation_inference")

        if by_level.get(1) and by_level.get(2) and not any(item.get("type") == "office.stairwell" for item in [*objects, *generated]):
            self._add_gatehouse_stairwell(generated, by_level[1], by_level[2], "generic_gatehouse")

        if not generated:
            return objects
        return [*objects, *generated]

    @staticmethod
    def _office_floor_existing_furniture_count(objects: list[dict[str, Any]], floor: dict[str, Any]) -> int:
        floor_id = str(floor.get("id") or "")
        count = 0
        furniture_types = {
            "office.workstation",
            "office.workstation_seat",
            "office.training_seat",
            "office.desk_row",
            "office.l_desk",
            "office.meeting_table",
        }
        for item in objects:
            if item.get("type") not in furniture_types:
                continue
            attrs = item.get("attributes") or {}
            if floor_id and str(attrs.get("floor_id") or "") != floor_id:
                continue
            if item.get("type") == "office.desk_row":
                count += int(attrs.get("seats") or 0)
            elif item.get("type") == "office.meeting_table":
                count += int(attrs.get("seats") or 0)
            else:
                count += 1
        return count

    def _expected_office_workstation_count_for_floor(self, entities: list[dict[str, Any]], floor: dict[str, Any]) -> int:
        search_bbox = floor.get("evidence_bbox") or floor.get("source_bbox")
        if not self._valid_bbox(search_bbox):
            return 0
        counts: list[int] = []
        for entity in entities:
            if entity.get("entity_type") not in {"TEXT", "MTEXT"}:
                continue
            position = entity.get("geometry", {}).get("position")
            if not position:
                continue
            folded_position, _ = self._fold_point(position)
            if not self._point_in_bbox(folded_position, search_bbox, 4_000.0):
                continue
            raw_text = str(entity.get("text", ""))
            compact = re.sub(r"\s+", "", raw_text.upper())
            patterns = (
                r"办公有线点位[：:]?D[*×X]?(\d{1,3})",
                r"(\d{1,3})个办公有线点位",
                r"(\d{1,3})个办公点位",
                r"(\d{1,3})个办公无线?AP[+，,、].*?(\d{1,3})个办公有线点位",
            )
            for pattern in patterns:
                for match in re.finditer(pattern, compact):
                    groups = [int(group) for group in match.groups() if group and group.isdigit()]
                    if groups:
                        counts.append(groups[-1])
        return max(counts) if counts else 0

    def _add_generic_gatehouse_desk_rows(
        self,
        objects: list[dict[str, Any]],
        floor: dict[str, Any],
        prefix: str,
        seat_count: int,
    ) -> None:
        seat_count = max(0, min(int(seat_count or 0), 40))
        if seat_count <= 0:
            return
        row_count = 1
        if seat_count > 20:
            row_count = 3
        elif seat_count > 8:
            row_count = 2
        seats_per_row = ceil(seat_count / row_count)
        remaining = seat_count
        for row_index in range(row_count):
            row_seats = min(remaining, seats_per_row)
            if row_seats <= 0:
                break
            modules = max(1, ceil(row_seats / 2))
            ry = 0.38 if row_count == 1 else 0.34 + (0.36 * row_index / max(row_count - 1, 1))
            self._add_gatehouse_desk_row(
                objects,
                floor,
                f"{prefix}_row_{row_index + 1}",
                0.18,
                0.82,
                ry,
                modules,
                f"办公桌排 {row_index + 1}",
                seat_type="office.workstation_seat",
                seat_sides=(-1, 1),
                seat_limit=row_seats,
            )
            remaining -= row_seats

    def _apply_gatehouse_confirmed_layout_rules(
        self,
        objects: list[dict[str, Any]],
        office_model: dict[str, Any],
    ) -> list[dict[str, Any]]:
        gatehouse_floors = [
            floor
            for floor in office_model.get("floors", [])
            if floor.get("tower") in {"southwest", "northwest"} and floor.get("id")
        ]
        if not gatehouse_floors:
            return objects

        floor_ids = {str(floor.get("id")) for floor in gatehouse_floors}
        preserved: list[dict[str, Any]] = []
        for item in objects:
            floor_id = str((item.get("attributes") or {}).get("floor_id") or "")
            if floor_id in floor_ids and item.get("type") in GATEHOUSE_CONFIRMED_LAYOUT_REPLACED_TYPES:
                continue
            preserved.append(item)

        generated = self._confirmed_gatehouse_furniture_objects(gatehouse_floors)
        return [*preserved, *generated]

    def _confirmed_gatehouse_furniture_objects(self, floors: list[dict[str, Any]]) -> list[dict[str, Any]]:
        by_key = {(str(floor.get("tower")), int(floor.get("level", 0) or 0)): floor for floor in floors}
        objects: list[dict[str, Any]] = []
        sw_l1 = by_key.get(("southwest", 1))
        sw_l2 = by_key.get(("southwest", 2))
        nw_l1 = by_key.get(("northwest", 1))
        nw_l2 = by_key.get(("northwest", 2))

        if sw_l1:
            self._add_gatehouse_desk_row(objects, sw_l1, "sw_l1_row_1", 0.22, 0.47, 0.60, 4, "一排8座", seat_type="office.workstation_seat", seat_sides=(-1, 1))
            self._add_gatehouse_desk_row(objects, sw_l1, "sw_l1_row_2", 0.22, 0.47, 0.42, 4, "二排8座", seat_type="office.workstation_seat", seat_sides=(-1, 1))
            self._add_gatehouse_stairwell(objects, sw_l1, sw_l2, "sw")

        if sw_l2:
            self._add_gatehouse_desk_row(objects, sw_l2, "sw_l2_9_row_1", 0.06, 0.24, 0.42, 3, "9人卡位上排6座", seat_type="office.workstation_seat", seat_sides=(-1, 1))
            self._add_gatehouse_desk_row(objects, sw_l2, "sw_l2_9_row_2", 0.06, 0.24, 0.75, 3, "9人卡位下排3座", seat_type="office.workstation_seat", seat_sides=(1,))
            training_rows = [
                (0.43, 0.58, 0.18),
                (0.73, 0.88, 0.22),
                (0.43, 0.58, 0.28),
                (0.73, 0.88, 0.32),
                (0.43, 0.58, 0.37),
                (0.73, 0.88, 0.41),
                (0.43, 0.58, 0.47),
                (0.73, 0.88, 0.51),
                (0.43, 0.58, 0.56),
                (0.73, 0.88, 0.60),
                (0.43, 0.58, 0.66),
                (0.73, 0.88, 0.70),
                (0.73, 0.88, 0.80),
                (0.61, 0.76, 0.95),
            ]
            for index, (rx1, rx2, ry) in enumerate(training_rows, start=1):
                self._add_gatehouse_desk_row(
                    objects,
                    sw_l2,
                    f"sw_l2_training_row_{index:02d}",
                    rx1,
                    rx2,
                    ry,
                    2,
                    f"培训室桌排 {index:02d}",
                    seat_type="office.training_seat",
                    seat_sides=(-1, 1),
                    row_length_m=3.3,
                    row_width_m=0.52,
                )
            self._add_gatehouse_meeting_table(objects, sw_l2, "sw_l2_meeting", 0.21, 0.18, "洽谈室20平圆桌")

        if nw_l1:
            self._add_gatehouse_desk_row(objects, nw_l1, "nw_l1_meeting_row", 0.18, 0.74, 0.50, 8, "会议室16座", seat_type="office.training_seat", seat_sides=(-1, 1), row_length_m=7.1)
            self._add_gatehouse_stairwell(objects, nw_l1, nw_l2, "nw")

        if nw_l2:
            self._add_gatehouse_desk_row(objects, nw_l2, "nw_l2_open_row_1", 0.15, 0.45, 0.60, 4, "开放办公区上排8座", seat_type="office.workstation_seat", seat_sides=(-1, 1))
            self._add_gatehouse_desk_row(objects, nw_l2, "nw_l2_open_row_2", 0.15, 0.45, 0.38, 4, "开放办公区下排8座", seat_type="office.workstation_seat", seat_sides=(-1, 1))
            l_desks = [
                ("office26", "独立办公室26平", 0.26, 0.84, [((0.18, 0.86), (0.26, 0.86)), ((0.32, 0.85), (0.32, 0.80)), ((0.36, 0.85), (0.36, 0.80))]),
                ("office196", "独立办公室19.6平", 0.72, 0.67, [((0.65, 0.69), (0.72, 0.69)), ((0.65, 0.64), (0.72, 0.64)), ((0.81, 0.68), (0.81, 0.63))]),
                ("office197", "独立办公室19.7平", 0.72, 0.37, [((0.65, 0.40), (0.72, 0.40)), ((0.65, 0.35), (0.72, 0.35)), ((0.81, 0.38), (0.81, 0.33))]),
                ("office193", "独立办公室19.3平", 0.72, 0.13, [((0.65, 0.16), (0.72, 0.16)), ((0.65, 0.11), (0.72, 0.11)), ((0.81, 0.14), (0.81, 0.09))]),
            ]
            for desk_key, room_label, rx, ry, seat_pairs in l_desks:
                self._add_gatehouse_l_desk(objects, nw_l2, f"nw_l2_{desk_key}", rx, ry, room_label)
                for seat_index, (seat_ratio, target_ratio) in enumerate(seat_pairs, start=1):
                    self._add_gatehouse_seat(
                        objects,
                        nw_l2,
                        f"nw_l2_{desk_key}_seat_{seat_index}",
                        seat_ratio[0],
                        seat_ratio[1],
                        target_ratio[0],
                        target_ratio[1],
                        "office.workstation_seat",
                        f"{room_label}座椅 {seat_index}",
                    )

        return objects

    def _gatehouse_floor_point(self, floor: dict[str, Any], rx: float, ry: float) -> dict[str, float]:
        bbox = floor.get("target_bbox") or floor.get("source_bbox") or {}
        min_x = float(bbox.get("min_x", 0.0))
        min_y = float(bbox.get("min_y", 0.0))
        width = max(float(bbox.get("max_x", min_x)) - min_x, 1.0)
        depth = max(float(bbox.get("max_y", min_y)) - min_y, 1.0)
        return {"x": min_x + width * rx, "y": min_y + depth * ry}

    @staticmethod
    def _gatehouse_floor_attrs(floor: dict[str, Any], source_kind: str, extra: dict[str, Any] | None = None) -> dict[str, Any]:
        attrs = {
            "source_kind": source_kind,
            "ruleset_id": GATEHOUSE_CONFIRMED_RULESET_ID,
            "ruleset_name": GATEHOUSE_CONFIRMED_RULESET_NAME,
            "floor_id": floor.get("id"),
            "tower": floor.get("tower"),
            "tower_label": floor.get("tower_label"),
            "level": floor.get("level"),
            "floor_label": floor.get("label"),
            "floor_elevation_m": floor.get("floor_elevation_m", 0.0),
            "room_height_m": floor.get("room_height_m", OFFICE_ROOM_HEIGHT_M),
        }
        if extra:
            attrs.update(extra)
        return attrs

    @staticmethod
    def _active_gatehouse_rule_sets(
        office_model: dict[str, Any] | None,
        office_objects: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        floors = RuleEngine._confirmed_gatehouse_floors(office_model)
        if not floors:
            return []
        object_count = sum(
            1
            for item in office_objects
            if (item.get("attributes") or {}).get("ruleset_id") == GATEHOUSE_CONFIRMED_RULESET_ID
        )
        return [
            {
                "id": GATEHOUSE_CONFIRMED_RULESET_ID,
                "name": GATEHOUSE_CONFIRMED_RULESET_NAME,
                "scope": "gatehouse_office_layout_and_model_generation",
                "trigger_phrase": GATEHOUSE_CONFIRMED_RULESET_NAME,
                "enabled": True,
                "floor_ids": [str(floor.get("id")) for floor in floors],
                "object_count": object_count,
                "application_mode": "cad_evidence_driven_generic" if any(floor.get("tower") == GENERIC_GATEHOUSE_TOWER_KEY for floor in floors) else "project_confirmed_gatehouse_layout",
                "contracts": [
                    "same_physical_footprint_for_level_1_and_2",
                    "tower_level_layer_filters_devices_ap_coverage_labels_and_office_objects",
                    "chair_face_towards_desk_or_room_center",
                    "single_office_l_desk_as_continuous_corner_desktop",
                    "meeting_table_controls_its_own_chairs_without_duplicate_loose_seats",
                    "stair_detail_lines_are_semantic_connectors_not_yellow_step_blocks",
                    "render_partitions_only_when_bound_to_tower_and_level",
                ],
            }
        ]

    def _add_gatehouse_desk_row(
        self,
        objects: list[dict[str, Any]],
        floor: dict[str, Any],
        key: str,
        rx1: float,
        rx2: float,
        ry: float,
        modules: int,
        label: str,
        *,
        seat_type: str,
        seat_sides: tuple[int, ...],
        row_length_m: float | None = None,
        row_width_m: float = 0.78,
        seat_limit: int | None = None,
    ) -> None:
        center = self._gatehouse_floor_point(floor, (rx1 + rx2) / 2.0, ry)
        bbox = floor.get("target_bbox") or floor.get("source_bbox") or {}
        width_m = max((float(bbox.get("max_x", 0.0)) - float(bbox.get("min_x", 0.0))) * abs(rx2 - rx1) / 1000.0, 1.2)
        seat_total = modules * len(seat_sides) if seat_limit is None else min(int(seat_limit), modules * len(seat_sides))
        objects.append(
            {
                "id": f"{key}_desk_row",
                "type": "office.desk_row",
                "label": f"{floor.get('label')} {label}",
                "source_entity_id": f"gatehouse_layout_rule:{key}:desk_row",
                "original_layer": "CAD炮楼家具规则",
                "confidence": 0.84,
                "geometry": {"type": "Point", "position": center},
                "orientation": {"angle_deg": 0.0},
                "attributes": self._gatehouse_floor_attrs(
                    floor,
                    "cad_gatehouse_confirmed_desk_row_rule",
                    {
                        "modules": modules,
                        "length_m": round(row_length_m or width_m, 2),
                        "width_m": row_width_m,
                        "seats": seat_total,
                    },
                ),
            }
        )
        seat_offset_ratio = 0.04
        emitted_seats = 0
        for module_index in range(modules):
            seat_rx = rx1 + (rx2 - rx1) * (module_index + 0.5) / max(modules, 1)
            for side in seat_sides:
                if seat_limit is not None and emitted_seats >= seat_limit:
                    continue
                self._add_gatehouse_seat(
                    objects,
                    floor,
                    f"{key}_seat_{module_index + 1}_{'a' if side < 0 else 'b'}",
                    seat_rx,
                    ry + seat_offset_ratio * side,
                    seat_rx,
                    ry,
                    seat_type,
                    f"{label} 座位 {len([item for item in objects if item.get('type') == seat_type and (item.get('attributes') or {}).get('floor_id') == floor.get('id')]) + 1:02d}",
                )
                emitted_seats += 1

    def _add_gatehouse_seat(
        self,
        objects: list[dict[str, Any]],
        floor: dict[str, Any],
        key: str,
        rx: float,
        ry: float,
        target_rx: float,
        target_ry: float,
        seat_type: str,
        label: str,
    ) -> None:
        position = self._gatehouse_floor_point(floor, rx, ry)
        target = self._gatehouse_floor_point(floor, target_rx, target_ry)
        objects.append(
            {
                "id": key,
                "type": seat_type,
                "label": f"{floor.get('label')} {label}",
                "source_entity_id": f"gatehouse_layout_rule:{key}:seat",
                "original_layer": "CAD炮楼家具规则",
                "confidence": 0.84,
                "geometry": {"type": "Point", "position": position},
                "orientation": {"angle_deg": 0.0},
                "attributes": self._gatehouse_floor_attrs(
                    floor,
                    "cad_gatehouse_confirmed_seat_direction_rule",
                    {"face_towards": target, "seat_only": True},
                ),
            }
        )

    def _add_gatehouse_l_desk(
        self,
        objects: list[dict[str, Any]],
        floor: dict[str, Any],
        key: str,
        rx: float,
        ry: float,
        room_label: str,
    ) -> None:
        objects.append(
            {
                "id": f"{key}_l_desk",
                "type": "office.l_desk",
                "label": f"{floor.get('label')} {room_label}L型办公桌",
                "source_entity_id": f"gatehouse_layout_rule:{key}:l_desk",
                "original_layer": "CAD炮楼家具规则",
                "confidence": 0.86,
                "geometry": {"type": "Point", "position": self._gatehouse_floor_point(floor, rx, ry)},
                "orientation": {"angle_deg": 0.0},
                "attributes": self._gatehouse_floor_attrs(
                    floor,
                    "cad_independent_office_l_desk_from_dwg_furniture_linework",
                    {
                        "room_label": room_label,
                        "desk_shape": "l_corner",
                        "main_length_m": 1.9,
                        "main_width_m": 0.72,
                        "return_length_m": 1.5,
                        "return_width_m": 0.72,
                        "return_side": "right",
                        "return_end": "front",
                        "layout_rule": "single_connected_l_shape_desktop_not_two_separate_rows",
                    },
                ),
            }
        )

    def _add_gatehouse_meeting_table(
        self,
        objects: list[dict[str, Any]],
        floor: dict[str, Any],
        key: str,
        rx: float,
        ry: float,
        label: str,
    ) -> None:
        objects.append(
            {
                "id": f"{key}_meeting_table",
                "type": "office.meeting_table",
                "label": f"{floor.get('label')} {label}",
                "source_entity_id": f"gatehouse_layout_rule:{key}:meeting_table",
                "original_layer": "CAD炮楼家具规则",
                "confidence": 0.82,
                "geometry": {"type": "Point", "position": self._gatehouse_floor_point(floor, rx, ry)},
                "orientation": {"angle_deg": 0.0},
                "attributes": self._gatehouse_floor_attrs(
                    floor,
                    "cad_meeting_room_circle_table_confirmed_rule",
                    {"seats": 4, "radius_m": 0.58, "rule": "chairs_generated_as_local_group_around_table"},
                ),
            }
        )

    def _add_gatehouse_stairwell(
        self,
        objects: list[dict[str, Any]],
        level1: dict[str, Any],
        level2: dict[str, Any] | None,
        prefix: str,
    ) -> None:
        if not level2:
            return
        objects.append(
            {
                "id": f"{prefix}_gatehouse_stairwell_1_to_2",
                "type": "office.stairwell",
                "label": f"{level1.get('label')}至二层楼梯连通",
                "source_entity_id": f"gatehouse_layout_rule:{prefix}:stairwell",
                "original_layer": "A-SECT-楼梯",
                "confidence": 0.76,
                "geometry": {"type": "Point", "position": self._gatehouse_floor_point(level1, 0.10, 0.18)},
                "orientation": {"angle_deg": 0.0},
                "attributes": self._gatehouse_floor_attrs(
                    level1,
                    "cad_stair_lines_connected_floor_pair",
                    {
                        "connects_to_floor_id": level2.get("id"),
                        "connects_to_elevation_m": level2.get("floor_elevation_m", OFFICE_SECOND_FLOOR_ELEVATION_M),
                        "length_m": 5.0,
                        "width_m": 1.55,
                        "render_model": False,
                        "render_as_scope": True,
                        "stair_visual_policy": "semantic_connector_only_no_yellow_stair_blocks",
                    },
                ),
            }
        )

    def _extract_office_objects(self, entities: list[dict[str, Any]], office_model: dict[str, Any]) -> list[dict[str, Any]]:
        objects: list[dict[str, Any]] = []
        seen: set[tuple[str, int, int]] = set()
        for entity in entities:
            if entity.get("entity_type") != "INSERT" or str(entity.get("block_name", "")) not in OFFICE_WORKSTATION_BLOCKS:
                continue
            position = entity.get("geometry", {}).get("position")
            if not position:
                continue
            folded_position, _ = self._fold_point(position)
            floor = self._office_floor_for_workstation_point(folded_position, office_model)
            if not floor:
                continue
            target = self._transform_point(folded_position, floor["transform"])
            dedup_step = 500.0 if self._system_views_are_title_fallback_only() and int(floor.get("level", 0) or 0) == 1 else 20.0
            floor_key = str(floor.get("id") or floor["level"])
            key = (floor_key, round(target["x"] / dedup_step), round(target["y"] / dedup_step))
            if key in seen:
                continue
            seen.add(key)
            index = sum(1 for item in objects if item["attributes"].get("floor_id") == floor.get("id")) + 1
            objects.append(
                {
                    "id": f"office_ws_{floor_key}_{index:03d}",
                    "type": "office.workstation",
                    "label": f"{floor['label']} 工位 {index:02d}",
                    "source_entity_id": entity["source_entity_id"],
                    "original_layer": entity.get("layer"),
                    "original_block_name": entity.get("block_name"),
                    "confidence": 0.78,
                    "geometry": {"type": "Point", "position": target},
                    "orientation": {"angle_deg": float(entity.get("rotation", 0.0) or 0.0)},
                    "attributes": {
                        "source_kind": "cad_furniture_block",
                        "floor_id": floor.get("id"),
                        "tower": floor.get("tower"),
                        "tower_label": floor.get("tower_label"),
                        "level": floor["level"],
                        "floor_label": floor["label"],
                        "floor_elevation_m": floor["floor_elevation_m"],
                        "room_height_m": floor["room_height_m"],
                    },
                }
            )
        objects.extend(self._extract_office_meeting_tables(entities, office_model, len(objects)))
        objects = self._filter_office_meeting_table_overlaps(objects)
        objects.extend(self._extract_office_partitions(entities, office_model, len(objects)))
        return objects

    def _extract_office_meeting_tables(
        self,
        entities: list[dict[str, Any]],
        office_model: dict[str, Any],
        id_offset: int = 0,
    ) -> list[dict[str, Any]]:
        room_seeds: list[dict[str, Any]] = []
        table_circles: list[dict[str, Any]] = []
        for entity in entities:
            entity_type = entity.get("entity_type")
            if entity_type in {"TEXT", "MTEXT"}:
                raw_text = str(entity.get("text", ""))
                if not any(keyword in raw_text for keyword in OFFICE_MEETING_ROOM_KEYWORDS):
                    continue
                points = self._office_geometry_points(entity)
                if not points:
                    continue
                floor = self._office_floor_for_workstation_point(points[0], office_model)
                if not floor:
                    continue
                room_seeds.append({"entity": entity, "point": points[0], "floor": floor})
            elif entity_type == "CIRCLE":
                geometry = entity.get("geometry", {})
                radius = float(geometry.get("radius", 0.0) or 0.0)
                if not (OFFICE_MEETING_TABLE_RADIUS_MIN_MM <= radius <= OFFICE_MEETING_TABLE_RADIUS_MAX_MM):
                    continue
                points = self._office_geometry_points(entity)
                if not points:
                    continue
                floor = self._office_floor_for_workstation_point(points[0], office_model)
                if not floor:
                    continue
                table_circles.append({"entity": entity, "point": points[0], "floor": floor, "radius": radius})

        if not room_seeds or not table_circles:
            return []

        tables: list[dict[str, Any]] = []
        seen: set[tuple[str, int, int]] = set()
        for seed in room_seeds:
            floor = seed["floor"]
            floor_key = str(floor.get("id") or floor["level"])
            candidates = [
                circle
                for circle in table_circles
                if str(circle["floor"].get("id") or circle["floor"]["level"]) == floor_key
                and hypot(circle["point"]["x"] - seed["point"]["x"], circle["point"]["y"] - seed["point"]["y"])
                <= OFFICE_MEETING_TABLE_SEARCH_RADIUS_MM
            ]
            if not candidates:
                continue
            candidates.sort(
                key=lambda circle: hypot(
                    circle["point"]["x"] - seed["point"]["x"],
                    circle["point"]["y"] - seed["point"]["y"],
                )
            )
            circle = candidates[0]
            target = self._transform_point(circle["point"], floor["transform"])
            key = (floor_key, round(target["x"] / 200.0), round(target["y"] / 200.0))
            if key in seen:
                continue
            seen.add(key)
            radius_m = max(0.35, min(float(circle["radius"]) / 1000.0, 1.4))
            index = id_offset + len(tables) + 1
            raw_label = str(seed["entity"].get("text", "")).strip()
            tables.append(
                {
                    "id": f"office_meeting_table_{floor_key}_{len(tables) + 1:03d}",
                    "type": "office.meeting_table",
                    "label": f"{floor['label']} {raw_label or '洽谈室圆桌'}",
                    "source_entity_id": circle["entity"]["source_entity_id"],
                    "original_layer": circle["entity"].get("layer"),
                    "confidence": 0.74,
                    "geometry": {"type": "Point", "position": target},
                    "orientation": {"angle_deg": 0.0},
                    "attributes": {
                        "source_kind": "cad_meeting_room_circle_table",
                        "room_label_source_entity_id": seed["entity"].get("source_entity_id"),
                        "floor_id": floor.get("id"),
                        "tower": floor.get("tower"),
                        "tower_label": floor.get("tower_label"),
                        "level": floor["level"],
                        "floor_label": floor["label"],
                        "floor_elevation_m": floor["floor_elevation_m"],
                        "room_height_m": floor["room_height_m"],
                        "seats": 4,
                        "radius_m": round(radius_m, 2),
                        "cad_radius_mm": round(float(circle["radius"]), 2),
                        "rule_index": index,
                    },
                }
            )
        return tables

    def _filter_office_meeting_table_overlaps(self, objects: list[dict[str, Any]]) -> list[dict[str, Any]]:
        tables = [
            item
            for item in objects
            if item.get("type") == "office.meeting_table" and item.get("geometry", {}).get("position")
        ]
        if not tables:
            return objects
        filtered: list[dict[str, Any]] = []
        for item in objects:
            if item.get("type") not in OFFICE_MEETING_TABLE_OVERLAP_SEAT_TYPES:
                filtered.append(item)
                continue
            position = item.get("geometry", {}).get("position")
            if not position:
                filtered.append(item)
                continue
            should_drop = False
            for table in tables:
                if not self._office_same_floor(item, table):
                    continue
                table_position = table.get("geometry", {}).get("position") or {}
                radius_mm = max(float(table.get("attributes", {}).get("radius_m", 0.55) or 0.55) * 1000.0, 350.0)
                distance = hypot(
                    float(position.get("x", 0.0)) - float(table_position.get("x", 0.0)),
                    float(position.get("y", 0.0)) - float(table_position.get("y", 0.0)),
                )
                if distance <= radius_mm + OFFICE_MEETING_TABLE_OVERLAP_PAD_MM:
                    should_drop = True
                    break
            if not should_drop:
                filtered.append(item)
        return filtered

    @staticmethod
    def _office_same_floor(left: dict[str, Any], right: dict[str, Any]) -> bool:
        left_attrs = left.get("attributes", {}) or {}
        right_attrs = right.get("attributes", {}) or {}
        left_floor = str(left_attrs.get("floor_id") or left_attrs.get("floor_label") or "")
        right_floor = str(right_attrs.get("floor_id") or right_attrs.get("floor_label") or "")
        if left_floor and right_floor:
            return left_floor == right_floor
        left_elevation = float(left_attrs.get("floor_elevation_m", 0.0) or 0.0)
        right_elevation = float(right_attrs.get("floor_elevation_m", 0.0) or 0.0)
        return abs(left_elevation - right_elevation) < 0.2

    @staticmethod
    def _filter_renderable_office_objects(objects: list[dict[str, Any]]) -> list[dict[str, Any]]:
        hidden_types = {"office.stair"}
        visible: list[dict[str, Any]] = []
        for obj in objects:
            obj_type = obj.get("type")
            if obj_type in hidden_types:
                continue
            if obj_type == "office.partition" and not (obj.get("attributes") or {}).get("tower"):
                continue
            visible.append(obj)
        return visible

    def _extract_office_partitions(
        self,
        entities: list[dict[str, Any]],
        office_model: dict[str, Any],
        id_offset: int = 0,
    ) -> list[dict[str, Any]]:
        partitions: list[dict[str, Any]] = []
        seen: set[tuple[str, int, int, int, int]] = set()
        for entity in entities:
            if entity.get("entity_type") not in {"LINE", "LWPOLYLINE", "POLYLINE"}:
                continue
            layer = str(entity.get("layer", ""))
            if layer not in OFFICE_PARTITION_LAYERS:
                continue
            if self._is_office_auxiliary_line_entity(entity):
                continue
            folded_points = self._office_geometry_points(entity)
            if len(folded_points) < 2:
                continue
            segments = list(zip(folded_points, folded_points[1:]))
            if entity.get("geometry", {}).get("closed") and len(folded_points) > 2:
                segments.append((folded_points[-1], folded_points[0]))
            for start, end in segments:
                length = hypot(end["x"] - start["x"], end["y"] - start["y"])
                if length < 450.0 or length > 18_000.0:
                    continue
                midpoint = {"x": (start["x"] + end["x"]) / 2.0, "y": (start["y"] + end["y"]) / 2.0}
                floor = self._office_floor_for_workstation_point(midpoint, office_model)
                if not floor:
                    continue
                layout_bbox = floor.get("layout_bbox")
                if layout_bbox:
                    clipped = self._clip_segment_to_bbox(start, end, layout_bbox)
                    if not clipped:
                        continue
                    start, end = clipped
                    length = hypot(end["x"] - start["x"], end["y"] - start["y"])
                    if length < 120.0:
                        continue
                target_start = self._transform_point(start, floor["transform"])
                target_end = self._transform_point(end, floor["transform"])
                floor_key = str(floor.get("id") or floor["level"])
                key = (
                    floor_key,
                    round(target_start["x"] / 120.0),
                    round(target_start["y"] / 120.0),
                    round(target_end["x"] / 120.0),
                    round(target_end["y"] / 120.0),
                )
                reverse_key = (key[0], key[3], key[4], key[1], key[2])
                if key in seen or reverse_key in seen:
                    continue
                seen.add(key)
                index = id_offset + len(partitions) + 1
                is_stair = "楼梯" in layer
                partitions.append(
                    {
                        "id": f"office_partition_{index:03d}",
                        "type": "office.stair" if is_stair else "office.partition",
                        "label": f"{floor['label']} {'楼梯' if is_stair else '隔墙'} {len(partitions) + 1:02d}",
                        "source_entity_id": entity["source_entity_id"],
                        "original_layer": layer,
                        "confidence": 0.72 if is_stair else 0.76,
                        "geometry": {"type": "LineString", "points": [target_start, target_end]},
                        "attributes": {
                            "source_kind": "cad_office_internal_geometry",
                            "floor_id": floor.get("id"),
                            "tower": floor.get("tower"),
                            "tower_label": floor.get("tower_label"),
                            "level": floor["level"],
                            "floor_label": floor["label"],
                            "floor_elevation_m": floor["floor_elevation_m"],
                            "room_height_m": floor["room_height_m"],
                            "height_m": 0.32 if is_stair else min(2.8, floor["room_height_m"] * 0.72),
                            "width_m": 0.18 if is_stair else 0.16,
                        },
                    }
                )
        return partitions

    def _infer_conveyor_dws_objects(self, entities: list[dict[str, Any]]) -> list[dict[str, Any]]:
        if not (self.base_view and self.base_view.get("no_main_plan_mode") and self.base_view.get("kind") == "monitor"):
            return []
        clusters = self._dws_conveyor_clusters_from_floor_layer(entities)
        if len(clusters) < 2:
            return []
        bounds = self.base_view.get("bounds") or {}
        base_center_x = (float(bounds.get("min_x", 0.0)) + float(bounds.get("max_x", 0.0))) / 2.0
        clusters = sorted(clusters, key=lambda item: abs(item["center"]["x"] - base_center_x))[:2]
        clusters = sorted(clusters, key=lambda item: item["center"]["y"], reverse=True)
        objects: list[dict[str, Any]] = []
        for cluster_index, cluster in enumerate(clusters[:2], start=1):
            lane_count = 3 if cluster_index == 1 else 4
            bbox = cluster["bbox"]
            span_x = bbox["max_x"] - bbox["min_x"]
            span_y = bbox["max_y"] - bbox["min_y"]
            lane_pitch = span_x / max(lane_count, 1)
            lane_width_m = max(min(lane_pitch / 1000.0 * 0.62, 1.15), 0.55)
            for lane_index in range(lane_count):
                x = bbox["min_x"] + lane_pitch * (lane_index + 0.5)
                y = cluster["center"]["y"]
                conveyor_id = f"conveyor_dws_{cluster_index}_{lane_index + 1:02d}"
                objects.append(
                    {
                        "id": conveyor_id,
                        "type": "logistics.conveyor_belt",
                        "label": f"传送带 {len([obj for obj in objects if obj['type'] == 'logistics.conveyor_belt']) + 1:02d}",
                        "source_entity_id": cluster["source_entity_id"],
                        "original_layer": "A-FLOR-GRND",
                        "confidence": 0.7,
                        "geometry": {"type": "Point", "position": {"x": x, "y": y}},
                        "orientation": {"angle_deg": 90.0},
                        "attributes": {
                            "source_kind": "cad_aflor_grnd_conveyor_cluster",
                            "cluster_index": cluster_index,
                            "lane_index": lane_index + 1,
                            "length_m": max(span_y / 1000.0, 8.0),
                            "width_m": lane_width_m,
                            "floor_elevation_m": 0.0,
                            "source_bbox": bbox,
                            "has_dws_host": cluster_index == 2 and lane_index < 3,
                        },
                    }
                )
                if cluster_index == 2 and lane_index < 3:
                    objects.append(
                        {
                            "id": f"dws_host_{lane_index + 1:02d}",
                            "type": "logistics.dws_host",
                            "label": f"DWS主机 {lane_index + 1:02d}",
                            "source_entity_id": cluster["source_entity_id"],
                            "original_layer": "A-FLOR-GRND",
                            "confidence": 0.66,
                            "geometry": {"type": "Point", "position": {"x": x + lane_pitch * 0.22, "y": y + span_y * 0.18}},
                            "orientation": {"angle_deg": 90.0},
                            "attributes": {
                                "source_kind": "cad_dws_note_attached_to_lower_conveyor",
                                "cluster_index": cluster_index,
                                "lane_index": lane_index + 1,
                                "floor_elevation_m": 0.0,
                                "host_role": "DWS电脑主机",
                            },
                        }
                    )
        return objects

    def _dws_conveyor_clusters_from_floor_layer(self, entities: list[dict[str, Any]]) -> list[dict[str, Any]]:
        candidates: list[dict[str, Any]] = []
        bounds = (self.base_view or {}).get("bounds") or {}
        for entity in entities:
            if entity.get("layer") != "A-FLOR-GRND" or entity.get("entity_type") not in {"LINE", "LWPOLYLINE", "POLYLINE"}:
                continue
            points = self._folded_geometry_points(entity)
            if len(points) < 2:
                continue
            bbox = self._points_bbox(points)
            if not self._bbox_intersects(bbox, bounds, pad_mm=100.0):
                continue
            span_x = bbox["max_x"] - bbox["min_x"]
            span_y = bbox["max_y"] - bbox["min_y"]
            if span_y < 9_000.0 or span_y > 16_000.0 or span_x > 6_000.0:
                continue
            candidates.append({"source_entity_id": entity["source_entity_id"], "bbox": bbox})
        if not candidates:
            return []
        by_y: dict[int, list[dict[str, Any]]] = defaultdict(list)
        for candidate in candidates:
            center_y = (candidate["bbox"]["min_y"] + candidate["bbox"]["max_y"]) / 2.0
            by_y[round(center_y / 2_000.0)].append(candidate)

        clusters: list[dict[str, Any]] = []
        for group in by_y.values():
            x_groups: list[list[dict[str, Any]]] = []
            for item in sorted(group, key=lambda candidate: candidate["bbox"]["min_x"]):
                if not x_groups:
                    x_groups.append([item])
                    continue
                previous_max_x = max(candidate["bbox"]["max_x"] for candidate in x_groups[-1])
                if item["bbox"]["min_x"] - previous_max_x <= 8_000.0:
                    x_groups[-1].append(item)
                else:
                    x_groups.append([item])
            for x_group in x_groups:
                if len(x_group) < 2:
                    continue
                bbox = {
                    "min_x": min(item["bbox"]["min_x"] for item in x_group),
                    "min_y": min(item["bbox"]["min_y"] for item in x_group),
                    "max_x": max(item["bbox"]["max_x"] for item in x_group),
                    "max_y": max(item["bbox"]["max_y"] for item in x_group),
                }
                span_x = bbox["max_x"] - bbox["min_x"]
                span_y = bbox["max_y"] - bbox["min_y"]
                if 4_000.0 <= span_x <= 5_500.0 and 10_000.0 <= span_y <= 15_500.0:
                    clusters.append(
                        {
                            "source_entity_id": "+".join(sorted(str(item["source_entity_id"]) for item in x_group)[:4]),
                            "bbox": bbox,
                            "center": self._bbox_center(bbox),
                        }
                    )
        return clusters[:]

    def _normalize_office_device(self, device: dict[str, Any], office_model: dict[str, Any]) -> dict[str, Any]:
        position = device.get("geometry", {}).get("position")
        if not position or not office_model.get("floors"):
            return device
        attrs = dict(device.get("attributes", {}))
        label = str(device.get("label", ""))
        device_type = str(device.get("type", ""))
        is_office_device = (
            attrs.get("zone") == "office"
            or "-BG-" in label.upper()
            or label.upper().startswith("BG-")
            or label.upper().startswith("OA-")
            or (device_type == "network.cabinet" and self._rack_units_from_text(label) is not None)
            or (device_type == "network.cabinet" and attrs.get("cabinet_role") in {"ups_power", "ups_battery"})
        )
        if not is_office_device:
            return device
        floor = self._office_floor_for_point(position, office_model)
        matched_target_bbox = False
        matched_device_scope = False
        if not floor:
            target_matches = []
            for candidate in office_model.get("floors", []):
                in_target = bool(
                    candidate.get("target_bbox")
                    and self._point_in_bbox(position, candidate["target_bbox"], OFFICE_FLOOR_MATCH_PAD_MM)
                )
                in_device_scope = bool(
                    candidate.get("target_device_bbox")
                    and self._point_in_bbox(position, candidate["target_device_bbox"], OFFICE_FLOOR_MATCH_PAD_MM)
                )
                if in_target or in_device_scope:
                    target_matches.append(candidate)
            if target_matches:
                floor = self._office_target_floor_for_point(
                    position,
                    target_matches,
                    label=label,
                    device_type=device_type,
                    attributes=attrs,
                )
                matched_target_bbox = bool(
                    floor
                    and floor.get("target_bbox")
                    and self._point_in_bbox(position, floor["target_bbox"], OFFICE_FLOOR_MATCH_PAD_MM)
                )
                matched_device_scope = bool(
                    floor
                    and floor.get("target_device_bbox")
                    and self._point_in_bbox(position, floor["target_device_bbox"], OFFICE_FLOOR_MATCH_PAD_MM)
                )
        if not floor:
            return device
        normalized = dict(device)
        if matched_device_scope and not matched_target_bbox and floor.get("target_device_bbox") and floor.get("target_bbox"):
            normalized["geometry"] = self._map_geometry_between_bboxes(device.get("geometry", {}), floor["target_device_bbox"], floor["target_bbox"])
            attrs["position_transform_source"] = "gatehouse_device_scope_to_physical_footprint"
        elif matched_target_bbox:
            normalized["geometry"] = device.get("geometry", {})
        else:
            normalized["geometry"] = self._transform_geometry(device.get("geometry", {}), floor["transform"])
        attrs.update(
            {
                "zone": "office",
                "tower": floor.get("tower"),
                "tower_label": floor.get("tower_label"),
                "level": floor["level"],
                "floor_label": floor["label"],
                "floor_elevation_m": floor["floor_elevation_m"],
                "room_height_m": floor["room_height_m"],
                "source_floor_bbox": floor["source_bbox"],
                "target_floor_bbox": floor.get("target_bbox"),
                "target_device_bbox": floor.get("target_device_bbox"),
            }
        )
        if floor.get("ruleset_id"):
            attrs.update(
                {
                    "ruleset_id": floor.get("ruleset_id"),
                    "ruleset_name": floor.get("ruleset_name", GATEHOUSE_CONFIRMED_RULESET_NAME),
                }
            )
        label_upper = label.upper()
        if device_type in {"security.camera.bullet", "security.camera.dome"} and label_upper.startswith("BG-"):
            norm_pos = normalized.get("geometry", {}).get("position") or position
            floor_bbox = floor.get("target_bbox") or floor.get("source_bbox") or {}
            if norm_pos and floor_bbox:
                center = self._bbox_center(floor_bbox)
                angle = self._snap_cardinal_angle(
                    self._angle_from_vector(center["x"] - norm_pos["x"], center["y"] - norm_pos["y"]),
                    tolerance_deg=22.0,
                )
                normalized.setdefault("orientation", {})["angle_deg"] = angle
                attrs.update(
                    {
                        "mount": "wall",
                        "source_kind": attrs.get("source_kind", "text_label"),
                        "orientation_source": "office_scope_center_context",
                        "orientation_confidence": 0.74,
                        "orientation_target": center,
                    }
                )
        if device_type == "network.cabinet":
            if attrs.get("cabinet_role") in {"ups_power", "ups_battery"}:
                attrs.update({"mount": "floor", "role": attrs.get("cabinet_role")})
            else:
                rack_units = self._rack_units_from_text(label) or int(attrs.get("rack_units") or 12)
                attrs.update({"rack_units": rack_units, "mount": "floor", "role": f"office_aggregation_{rack_units}u"})
        normalized["attributes"] = attrs
        return normalized

    @staticmethod
    def _office_target_floor_for_point(
        point: dict[str, float],
        floors: list[dict[str, Any]],
        label: str = "",
        device_type: str = "",
        attributes: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        attrs = attributes or {}
        normalized_label = re.sub(r"\s+", "", str(label or "").upper())
        force_level_1 = (
            device_type == "network.cabinet"
            or normalized_label in {"42U机柜", "UPS电源", "机房"}
            or attrs.get("cabinet_role") in {"ups_power", "ups_battery"}
        )
        by_tower: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for floor in floors:
            by_tower[str(floor.get("tower") or "")].append(floor)
        for candidates in by_tower.values():
            levels = {int(candidate.get("level") or 0): candidate for candidate in candidates}
            if 1 not in levels or 2 not in levels:
                continue
            if not any(candidate.get("stacking_source") == "same_gatehouse_footprint" for candidate in candidates):
                continue
            target_bbox = levels[1].get("target_bbox") or levels[2].get("target_bbox")
            if not target_bbox:
                continue
            if force_level_1:
                return levels[1]
            if levels[1].get("target_bbox") and RuleEngine._point_in_bbox(point, levels[1]["target_bbox"], OFFICE_FLOOR_MATCH_PAD_MM):
                return levels[1]
            if levels[2].get("source_bbox") and RuleEngine._point_in_bbox(point, levels[2]["source_bbox"], OFFICE_FLOOR_MATCH_PAD_MM):
                return levels[2]
            if levels[1].get("source_bbox") and RuleEngine._point_in_bbox(point, levels[1]["source_bbox"], OFFICE_FLOOR_MATCH_PAD_MM):
                return levels[1]
            device_scope_bbox = levels[1].get("target_device_bbox") or levels[2].get("target_device_bbox")
            if device_scope_bbox and RuleEngine._point_in_bbox(point, device_scope_bbox, OFFICE_FLOOR_MATCH_PAD_MM):
                return levels[2]
            split_bbox = levels[1].get("target_device_bbox") or levels[2].get("target_device_bbox") or target_bbox
            center_y = (float(split_bbox["min_y"]) + float(split_bbox["max_y"])) / 2.0
            return levels[2] if float(point["y"]) < center_y else levels[1]
        return sorted(floors, key=lambda item: item.get("level", 0))[0]

    def _normalize_office_structure(self, structure: dict[str, Any], office_model: dict[str, Any]) -> dict[str, Any]:
        geometry = structure.get("geometry", {})
        anchor = self._geometry_anchor(geometry)
        if not anchor or not office_model.get("floors"):
            return structure
        floor = self._office_floor_for_point(anchor, office_model)
        if not floor:
            return structure
        normalized = dict(structure)
        normalized["geometry"] = self._transform_geometry(geometry, floor["transform"])
        attrs = dict(normalized.get("attributes", {}))
        attrs.update(
            {
                "source_kind": "office_floor_structure",
                "tower": floor.get("tower"),
                "tower_label": floor.get("tower_label"),
                "level": floor["level"],
                "floor_label": floor["label"],
                "floor_elevation_m": floor["floor_elevation_m"],
                "room_height_m": floor["room_height_m"],
            }
        )
        if floor.get("ruleset_id"):
            attrs.update(
                {
                    "ruleset_id": floor.get("ruleset_id"),
                    "ruleset_name": floor.get("ruleset_name", GATEHOUSE_CONFIRMED_RULESET_NAME),
                }
            )
        normalized["attributes"] = attrs
        return normalized

    def _infer_office_device_links(self, devices: list[dict[str, Any]]) -> list[dict[str, Any]]:
        office_cores = [
            device
            for device in devices
            if device.get("type") == "network.cabinet"
            and str(device.get("attributes", {}).get("role", "")).startswith("office_aggregation_")
            and device.get("geometry", {}).get("position")
        ]
        core = max(office_cores, key=lambda item: int(item.get("attributes", {}).get("rack_units") or 0), default=None)
        if not core:
            return []
        core_pos = core["geometry"]["position"]
        core_entry_height = self._cabinet_entry_height(core) + float(core.get("attributes", {}).get("floor_elevation_m") or 0.0)
        convergence_point = self._core_convergence_point(core)
        links: list[dict[str, Any]] = []
        for device in devices:
            if device is core or not device.get("geometry", {}).get("position"):
                continue
            attrs = device.get("attributes", {})
            if attrs.get("zone") != "office" or device.get("type") not in {"network.ap", "security.camera.dome", "security.camera.bullet"}:
                continue
            if not attrs.get("floor_label") or (not attrs.get("tower") and not self._system_views_are_title_fallback_only()):
                continue
            core_attrs = core.get("attributes", {})
            if core_attrs.get("tower") and attrs.get("tower") != core_attrs.get("tower"):
                continue
            pos = device["geometry"]["position"]
            floor_elevation = float(attrs.get("floor_elevation_m") or 0.0)
            install_height = float(attrs.get("install_height_m") or (3.2 if device.get("type") == "network.ap" else 3.5))
            route_height = floor_elevation + install_height
            cable_type = "cable.network" if device.get("type") == "network.ap" else "cable.security"
            points = self._converged_route_to_core(pos, core_pos, convergence_point)
            links.append(
                {
                    "id": f"cable_office_{len(links) + 1:03d}",
                    "type": cable_type,
                    "source_entity_id": f"{device['source_entity_id']}->{core['source_entity_id']}",
                    "original_layer": "办公室弱电汇聚",
                    "confidence": 0.80,
                    "review_needed": False,
                    "geometry": {"type": "LineString", "points": points},
                    "length_mm": line_length(points),
                    "attributes": {
                        "source_kind": "office_device_link_inferred",
                        "layer_role": "weak_current",
                        "media": "六类线",
                        "source_device_id": device["id"],
                        "source_label": device.get("label"),
                        "target_device_id": core["id"],
                        "target_label": core.get("label"),
                        "height_m": route_height,
                        "source_entry_height_m": route_height,
                        "target_entry_height_m": core_entry_height,
                        "terminates_inside_cabinet": True,
                        "level": attrs.get("level"),
                        "floor_label": attrs.get("floor_label"),
                        "route_policy": "converge_to_42u_cabinet_zone",
                        "convergence_point": convergence_point,
                    },
                }
            )
        return links

    def _infer_single_cabinet_device_links(self, devices: list[dict[str, Any]]) -> list[dict[str, Any]]:
        cabinets = [
            device
            for device in devices
            if device.get("type") == "network.cabinet"
            and device.get("geometry", {}).get("position")
            and not self._is_power_cabinet(device)
        ]
        if len(cabinets) != 1:
            return []
        core = cabinets[0]
        core_pos = core["geometry"]["position"]
        core_entry_height = self._cabinet_entry_height(core) + float(core.get("attributes", {}).get("floor_elevation_m") or 0.0)
        convergence_point = self._core_convergence_point(core)
        links: list[dict[str, Any]] = []
        for device in devices:
            device_type = str(device.get("type", ""))
            if device is core or not device.get("geometry", {}).get("position"):
                continue
            if device_type == "network.cabinet":
                continue
            if not (device_type == "network.ap" or device_type.startswith("security.camera")):
                continue
            attrs = device.get("attributes", {})
            pos = device["geometry"]["position"]
            floor_elevation = float(attrs.get("floor_elevation_m") or 0.0)
            install_height = float(attrs.get("install_height_m") or self.install_height_hint(device_type))
            route_height = floor_elevation + install_height
            cable_type = "cable.network" if device_type == "network.ap" else "cable.security"
            points = self._converged_route_to_core(pos, core_pos, convergence_point)
            links.append(
                {
                    "id": f"cable_device_{len(links) + 1:03d}",
                    "type": cable_type,
                    "source_entity_id": f"{device['source_entity_id']}->{core['source_entity_id']}",
                    "original_layer": "单机柜弱电汇聚",
                    "confidence": 0.80,
                    "review_needed": False,
                    "geometry": {"type": "LineString", "points": points},
                    "length_mm": line_length(points),
                    "attributes": {
                        "source_kind": "single_cabinet_device_link_inferred",
                        "layer_role": "weak_current",
                        "media": "六类线",
                        "source_device_id": device["id"],
                        "source_label": device.get("label"),
                        "target_device_id": core["id"],
                        "target_label": core.get("label"),
                        "height_m": max(route_height, core_entry_height),
                        "source_entry_height_m": route_height,
                        "target_entry_height_m": core_entry_height,
                        "terminates_inside_cabinet": True,
                        "route_policy": "converge_to_42u_cabinet_zone",
                        "convergence_point": convergence_point,
                    },
                }
            )
        return links

    @staticmethod
    def install_height_hint(device_type: str) -> float:
        if device_type == "network.ap":
            return 6.0
        if device_type == "security.camera.fisheye":
            return 5.0
        if device_type == "security.camera.dome":
            return 3.0
        if device_type == "security.camera.rear":
            return 2.8
        if device_type.startswith("security.camera"):
            return 3.5
        return 3.0

    def _office_floor_for_point(self, point: dict[str, float], office_model: dict[str, Any]) -> dict[str, Any] | None:
        floors = sorted(office_model.get("floors", []), key=lambda item: item.get("level", 0), reverse=True)
        if any(floor.get("layout_bbox") for floor in floors):
            for floor in floors:
                layout_bbox = floor.get("layout_bbox")
                if layout_bbox and self._point_in_bbox(point, layout_bbox, OFFICE_FLOOR_MATCH_PAD_MM):
                    return floor
            return None
        for floor in floors:
            if self._point_in_bbox(point, floor["source_bbox"], OFFICE_FLOOR_MATCH_PAD_MM):
                return floor
            cad_bbox = floor.get("cad_geometry_bbox")
            if cad_bbox and self._point_in_bbox(point, cad_bbox, OFFICE_FLOOR_MATCH_PAD_MM):
                return floor
        return None

    def _office_floor_for_workstation_point(self, point: dict[str, float], office_model: dict[str, Any]) -> dict[str, Any] | None:
        floors = sorted(office_model.get("floors", []), key=lambda item: item.get("level", 0), reverse=True)
        if any(floor.get("layout_bbox") for floor in floors):
            for floor in floors:
                layout_bbox = floor.get("layout_bbox")
                if layout_bbox and self._point_in_bbox(point, layout_bbox, OFFICE_FLOOR_MATCH_PAD_MM):
                    return floor
            return None
        for floor in floors:
            if self._point_in_bbox(point, floor["source_bbox"], OFFICE_FLOOR_MATCH_PAD_MM):
                return floor
            cad_bbox = floor.get("cad_geometry_bbox")
            if cad_bbox and self._point_in_bbox(point, cad_bbox, OFFICE_FLOOR_MATCH_PAD_MM):
                return floor
        return None

    def _point_in_office_footprint(self, point: dict[str, float], office_model: dict[str, Any], pad: float = 2500.0) -> bool:
        for floor in office_model.get("floors", []):
            if self._point_in_bbox(point, floor["source_bbox"], pad):
                return True
            if self._point_in_bbox(point, floor["target_bbox"], pad):
                return True
        return False

    @staticmethod
    def _points_bbox(points: list[dict[str, float]]) -> dict[str, float]:
        if not points:
            return {"min_x": 0.0, "min_y": 0.0, "max_x": 0.0, "max_y": 0.0}
        return {
            "min_x": min(point["x"] for point in points),
            "min_y": min(point["y"] for point in points),
            "max_x": max(point["x"] for point in points),
            "max_y": max(point["y"] for point in points),
        }

    @staticmethod
    def _clip_segment_to_bbox(
        start: dict[str, float],
        end: dict[str, float],
        bbox: dict[str, float],
        pad_mm: float = 0.0,
    ) -> tuple[dict[str, float], dict[str, float]] | None:
        min_x = float(bbox["min_x"]) - pad_mm
        min_y = float(bbox["min_y"]) - pad_mm
        max_x = float(bbox["max_x"]) + pad_mm
        max_y = float(bbox["max_y"]) + pad_mm
        x0 = float(start["x"])
        y0 = float(start["y"])
        x1 = float(end["x"])
        y1 = float(end["y"])
        dx = x1 - x0
        dy = y1 - y0
        t0 = 0.0
        t1 = 1.0
        for p, q in (
            (-dx, x0 - min_x),
            (dx, max_x - x0),
            (-dy, y0 - min_y),
            (dy, max_y - y0),
        ):
            if abs(p) < 1e-9:
                if q < 0.0:
                    return None
                continue
            r = q / p
            if p < 0.0:
                if r > t1:
                    return None
                if r > t0:
                    t0 = r
            else:
                if r < t0:
                    return None
                if r < t1:
                    t1 = r
        return (
            {"x": x0 + t0 * dx, "y": y0 + t0 * dy},
            {"x": x0 + t1 * dx, "y": y0 + t1 * dy},
        )

    @staticmethod
    def _bbox_intersects(bbox: dict[str, float], bounds: dict[str, Any], pad_mm: float = 0.0) -> bool:
        if not bbox or not bounds:
            return False
        return not (
            bbox["max_x"] < float(bounds.get("min_x", 0.0)) - pad_mm
            or bbox["min_x"] > float(bounds.get("max_x", 0.0)) + pad_mm
            or bbox["max_y"] < float(bounds.get("min_y", 0.0)) - pad_mm
            or bbox["min_y"] > float(bounds.get("max_y", 0.0)) + pad_mm
        )

    def _folded_geometry_points(self, entity: dict[str, Any]) -> list[dict[str, float]]:
        geometry = entity.get("geometry", {})
        raw_points: list[dict[str, float]] = []
        if geometry.get("position"):
            raw_points = [geometry["position"]]
        elif geometry.get("center"):
            raw_points = [geometry["center"]]
        else:
            raw_points = list(geometry.get("points") or [])
        points: list[dict[str, float]] = []
        for point in raw_points:
            if self._plan_copy_index(point) is None:
                continue
            folded, _ = self._fold_point(point)
            points.append(folded)
        return points

    def _office_geometry_points(self, entity: dict[str, Any]) -> list[dict[str, float]]:
        geometry = entity.get("geometry", {})
        raw_points: list[dict[str, float]] = []
        if geometry.get("position"):
            raw_points = [geometry["position"]]
        elif geometry.get("center"):
            raw_points = [geometry["center"]]
        else:
            raw_points = list(geometry.get("points") or [])
        points: list[dict[str, float]] = []
        for point in raw_points:
            folded, _ = self._fold_point(point)
            points.append({"x": float(folded["x"]), "y": float(folded["y"])})
        return points

    @staticmethod
    def _near_any_seed(point: dict[str, float], seeds: list[dict[str, float]], radius_x: float, radius_y: float) -> bool:
        return any(
            abs(point["x"] - seed["x"]) <= radius_x and abs(point["y"] - seed["y"]) <= radius_y
            for seed in seeds
        )

    @staticmethod
    def _bbox_center(bbox: dict[str, float]) -> dict[str, float]:
        return {"x": (bbox["min_x"] + bbox["max_x"]) / 2.0, "y": (bbox["min_y"] + bbox["max_y"]) / 2.0}

    @staticmethod
    def _transform_point(point: dict[str, float], transform: dict[str, float]) -> dict[str, float]:
        if "source_center_x" in transform and "target_center_x" in transform:
            return {
                "x": float(transform["target_center_x"])
                + (point["x"] - float(transform["source_center_x"])) * float(transform.get("scale_x", 1.0)),
                "y": float(transform["target_center_y"])
                + (point["y"] - float(transform["source_center_y"])) * float(transform.get("scale_y", 1.0)),
            }
        return {"x": point["x"] + float(transform.get("dx", 0.0)), "y": point["y"] + float(transform.get("dy", 0.0))}

    def _transform_geometry(self, geometry: dict[str, Any], transform: dict[str, float]) -> dict[str, Any]:
        transformed = dict(geometry)
        if geometry.get("position"):
            transformed["position"] = self._transform_point(geometry["position"], transform)
        if geometry.get("center"):
            transformed["center"] = self._transform_point(geometry["center"], transform)
        if geometry.get("points"):
            transformed["points"] = [self._transform_point(point, transform) for point in geometry["points"]]
        return transformed

    @staticmethod
    def _map_point_between_bboxes(point: dict[str, float], source_bbox: dict[str, float], target_bbox: dict[str, float]) -> dict[str, float]:
        source_width = max(float(source_bbox["max_x"]) - float(source_bbox["min_x"]), 1.0)
        source_height = max(float(source_bbox["max_y"]) - float(source_bbox["min_y"]), 1.0)
        target_width = float(target_bbox["max_x"]) - float(target_bbox["min_x"])
        target_height = float(target_bbox["max_y"]) - float(target_bbox["min_y"])
        ratio_x = (float(point["x"]) - float(source_bbox["min_x"])) / source_width
        ratio_y = (float(point["y"]) - float(source_bbox["min_y"])) / source_height
        ratio_x = max(0.0, min(1.0, ratio_x))
        ratio_y = max(0.0, min(1.0, ratio_y))
        return {
            "x": float(target_bbox["min_x"]) + ratio_x * target_width,
            "y": float(target_bbox["min_y"]) + ratio_y * target_height,
        }

    def _map_geometry_between_bboxes(self, geometry: dict[str, Any], source_bbox: dict[str, float], target_bbox: dict[str, float]) -> dict[str, Any]:
        mapped = dict(geometry)
        if geometry.get("position"):
            mapped["position"] = self._map_point_between_bboxes(geometry["position"], source_bbox, target_bbox)
        if geometry.get("center"):
            mapped["center"] = self._map_point_between_bboxes(geometry["center"], source_bbox, target_bbox)
        if geometry.get("points"):
            mapped["points"] = [self._map_point_between_bboxes(point, source_bbox, target_bbox) for point in geometry["points"]]
        return mapped

    def _transform_bbox(self, bbox: dict[str, float], transform: dict[str, float]) -> dict[str, float]:
        p1 = self._transform_point({"x": bbox["min_x"], "y": bbox["min_y"]}, transform)
        p2 = self._transform_point({"x": bbox["max_x"], "y": bbox["max_y"]}, transform)
        return {
            "min_x": min(p1["x"], p2["x"]),
            "min_y": min(p1["y"], p2["y"]),
            "max_x": max(p1["x"], p2["x"]),
            "max_y": max(p1["y"], p2["y"]),
        }

    @staticmethod
    def _union_bbox(*bboxes: dict[str, float]) -> dict[str, float]:
        return {
            "min_x": min(bbox["min_x"] for bbox in bboxes),
            "min_y": min(bbox["min_y"] for bbox in bboxes),
            "max_x": max(bbox["max_x"] for bbox in bboxes),
            "max_y": max(bbox["max_y"] for bbox in bboxes),
        }

    @staticmethod
    def _point_in_bbox(point: dict[str, float], bbox: dict[str, float], pad: float = 0.0) -> bool:
        return (
            bbox["min_x"] - pad <= point["x"] <= bbox["max_x"] + pad
            and bbox["min_y"] - pad <= point["y"] <= bbox["max_y"] + pad
        )

    def _confirmed_gatehouse_room_areas(self, office_model: dict[str, Any] | None) -> list[dict[str, Any]]:
        if not office_model:
            return []
        floors = {
            (str(floor.get("tower")), int(floor.get("level", 0) or 0)): floor
            for floor in office_model.get("floors", [])
            if floor.get("tower") in {"southwest", "northwest"}
        }
        areas: list[dict[str, Any]] = []

        def rect(
            floor: dict[str, Any] | None,
            area_id: str,
            area_type: str,
            label: str,
            rx1: float,
            ry1: float,
            rx2: float,
            ry2: float,
            *,
            color: str,
            opacity: float,
            render_solid: bool = True,
            extra: dict[str, Any] | None = None,
        ) -> None:
            if not floor:
                return
            p1 = self._gatehouse_floor_point(floor, rx1, ry1)
            p2 = self._gatehouse_floor_point(floor, rx2, ry2)
            attrs = self._gatehouse_floor_attrs(
                floor,
                "cad_room_text_and_partition_scope",
                {
                    "height_m": floor.get("room_height_m", OFFICE_ROOM_HEIGHT_M),
                    "target_bbox": {
                        "min_x": min(p1["x"], p2["x"]),
                        "min_y": min(p1["y"], p2["y"]),
                        "max_x": max(p1["x"], p2["x"]),
                        "max_y": max(p1["y"], p2["y"]),
                    },
                    "render_color": color,
                    "opacity": opacity,
                    "show_label": True,
                    "render_solid": render_solid,
                    "label_control": "labels_layer_only",
                },
            )
            if extra:
                attrs.update(extra)
            area = self._rect_area(area_id, area_type, label, attrs["target_bbox"]["min_x"], attrs["target_bbox"]["min_y"], attrs["target_bbox"]["max_x"], attrs["target_bbox"]["max_y"], attrs)
            area["confidence"] = 0.78
            areas.append(area)

        sw_l1 = floors.get(("southwest", 1))
        sw_l2 = floors.get(("southwest", 2))
        nw_l1 = floors.get(("northwest", 1))
        nw_l2 = floors.get(("northwest", 2))
        rect(sw_l1, "room_sw_l1_open_16", "area.office.open_workstations", "16人卡位", 0.20, 0.37, 0.56, 0.66, color="#8fe1c1", opacity=0.16, extra={"expected_workstations": 16})
        rect(sw_l1, "room_sw_l1_machine", "area.office.utility", "机房", 0.64, 0.24, 0.98, 0.44, color="#ffcf6a", opacity=0.16)
        rect(sw_l1, "room_sw_l1_storage", "area.office.utility", "杂物间", 0.64, 0.44, 0.98, 0.68, color="#f4a261", opacity=0.16)
        rect(sw_l1, "room_sw_l1_stair", "area.office.stair", "楼梯间/一二层连通", 0.00, 0.00, 0.21, 0.73, color="#f0df9b", opacity=0.08, render_solid=False, extra={"render_as_scope": True, "stair_visual_policy": "reference_scope_only_do_not_render_yellow_blocks"})
        rect(sw_l2, "room_sw_l2_open_9", "area.office.open_workstations", "9人卡位", 0.06, 0.36, 0.35, 0.72, color="#8fe1c1", opacity=0.16, extra={"expected_workstations": 9})
        rect(sw_l2, "room_sw_l2_talk", "area.office.room", "洽谈室20平", 0.00, 0.00, 0.43, 0.36, color="#69d2e7", opacity=0.16)
        rect(sw_l2, "room_sw_l2_training", "area.office.room", "培训室", 0.40, 0.56, 0.91, 0.99, color="#7dd3fc", opacity=0.16)
        rect(sw_l2, "room_sw_l2_stair", "area.office.stair", "二层楼梯口", 0.57, 0.00, 0.91, 0.52, color="#f0df9b", opacity=0.08, render_solid=False, extra={"render_as_scope": True, "stair_visual_policy": "reference_scope_only_do_not_render_yellow_blocks"})
        rect(nw_l1, "room_nw_l1_meeting", "area.office.room", "会议室", 0.22, 0.19, 0.78, 0.78, color="#69d2e7", opacity=0.16)
        rect(nw_l1, "room_nw_l1_stair", "area.office.stair", "楼梯/一二层连通", 0.00, 0.01, 0.22, 0.98, color="#f0df9b", opacity=0.08, render_solid=False, extra={"render_as_scope": True, "stair_visual_policy": "reference_scope_only_do_not_render_yellow_blocks"})
        rect(nw_l2, "room_nw_l2_open_16", "area.office.open_workstations", "开放办公区53.8平", 0.03, 0.30, 0.54, 0.68, color="#8fe1c1", opacity=0.16, extra={"expected_workstations": 16})
        rect(nw_l2, "room_nw_l2_office_26", "area.office.room", "独立办公室26平", 0.03, 0.68, 0.54, 0.98, color="#7dd3fc", opacity=0.16)
        rect(nw_l2, "room_nw_l2_office_196", "area.office.room", "独立办公室19.6平", 0.56, 0.52, 0.96, 0.82, color="#7dd3fc", opacity=0.16)
        rect(nw_l2, "room_nw_l2_office_197", "area.office.room", "独立办公室19.7平", 0.56, 0.23, 0.96, 0.52, color="#7dd3fc", opacity=0.16)
        rect(nw_l2, "room_nw_l2_office_193", "area.office.room", "独立办公室19.3平", 0.56, 0.02, 0.96, 0.23, color="#7dd3fc", opacity=0.16)
        rect(nw_l2, "room_nw_l2_tea_stair", "area.office.service", "茶水/楼梯", 0.00, 0.02, 0.23, 0.30, color="#f4c76a", opacity=0.08, render_solid=False, extra={"render_as_scope": True, "stair_visual_policy": "reference_scope_only_do_not_render_yellow_blocks"})
        return areas

    def _infer_areas(self, entities: list[dict[str, Any]], office_model: dict[str, Any] | None = None) -> list[dict[str, Any]]:
        areas: list[dict[str, Any]] = []
        if office_model and office_model.get("floors"):
            for floor in office_model["floors"]:
                bbox = floor["target_bbox"]
                attrs = {
                    "level": floor["level"],
                    "floor_id": floor.get("id"),
                    "tower": floor.get("tower"),
                    "tower_label": floor.get("tower_label"),
                    "height_m": floor["room_height_m"],
                    "room_height_m": floor["room_height_m"],
                    "floor_elevation_m": floor["floor_elevation_m"],
                    "deck_height_m": floor["floor_elevation_m"] if floor["level"] > 1 else 0.0,
                    "source": "办公室详图识别并按炮楼楼层叠放",
                    "height_source": floor.get("height_source", "cad_inferred"),
                    "source_bbox": floor["source_bbox"],
                    "target_device_bbox": floor.get("target_device_bbox"),
                    "cad_geometry_bbox": floor.get("cad_geometry_bbox"),
                    "layout_bbox": floor.get("layout_bbox"),
                    "footprint_source": floor.get("footprint_source", "cad_geometry"),
                    "stacking_source": floor.get("stacking_source"),
                    "render_as_scope": bool(floor.get("render_as_scope")),
                    "render_solid": False if floor.get("render_as_scope") else True,
                    "wall_geometry_reliable": bool(floor.get("wall_geometry_reliable", True)),
                    "transform": floor["transform"],
                }
                if floor.get("ruleset_id"):
                    attrs.update(
                        {
                            "ruleset_id": floor.get("ruleset_id"),
                            "ruleset_name": floor.get("ruleset_name", GATEHOUSE_CONFIRMED_RULESET_NAME),
                            "layer_filter_contract": floor.get("layer_filter_contract"),
                        }
                    )
                if floor.get("office_kind"):
                    attrs["office_kind"] = floor["office_kind"]
                area_id = f"area_office_{floor.get('id')}" if floor.get("id") else f"area_office_level_{floor['level']}"
                area = self._rect_area(
                    area_id,
                    floor["area_type"],
                    floor["label"],
                    bbox["min_x"],
                    bbox["min_y"],
                    bbox["max_x"],
                    bbox["max_y"],
                    attrs,
                )
                if attrs.get("render_as_scope"):
                    area["confidence"] = 0.58
                areas.append(area)
            areas.extend(self._confirmed_gatehouse_room_areas(office_model))
        else:
            strong_office_points: list[dict[str, float]] = []
            weak_office_points: list[dict[str, float]] = []
            container_office = False
            for entity in entities:
                if entity.get("entity_type") not in {"TEXT", "MTEXT", "INSERT"}:
                    continue
                text = str(entity.get("text", ""))
                normalized_text = re.sub(r"\s+", "", text.upper())
                block = str(entity.get("block_name", ""))
                layer = str(entity.get("layer", ""))
                is_strong_office = (
                    normalized_text.startswith("OA-")
                    or normalized_text.startswith("BG-")
                    or re.fullmatch(r"(?:BFR|BGL)-[A-Z0-9-]+-BG-AP-\d{1,3}", normalized_text) is not None
                    or self._rack_units_from_text(text) is not None
                    or layer == "TK"
                )
                is_weak_office = "办公室" in text and len(normalized_text) <= 18
                if "办公室" in text and "集装箱" in text:
                    container_office = True
                if not (is_strong_office or is_weak_office):
                    continue
                position = entity.get("geometry", {}).get("position")
                if not position or self._plan_copy_index(position) != 0:
                    continue
                folded_position, _ = self._fold_point(position)
                if is_strong_office:
                    strong_office_points.append(folded_position)
                else:
                    weak_office_points.append(folded_position)

            office_points = strong_office_points or weak_office_points
            if office_points:
                min_x = min(point["x"] for point in office_points) - 6000.0
                max_x = max(point["x"] for point in office_points) + 6000.0
                min_y = min(point["y"] for point in office_points) - 4000.0
                max_y = max(point["y"] for point in office_points) + 4000.0
                if container_office:
                    areas.append(self._rect_area("area_office_container", "area.office", "办公区（集装箱）", min_x, min_y, max_x, max_y, {"level": 1, "height_m": OFFICE_CONTAINER_ROOM_HEIGHT_M, "floor_elevation_m": 0.0, "office_kind": "container", "height_source": "container_office_cad_text", "footprint_source": "text_seed_scope", "render_as_scope": True, "render_solid": False, "wall_geometry_reliable": False}))
                else:
                    areas.append(self._rect_area("area_office_ground", "area.office", "办公区一层", min_x, min_y, max_x, max_y, {"level": 1, "height_m": OFFICE_ROOM_HEIGHT_M, "floor_elevation_m": 0.0, "height_source": "visual_clearance_exaggerated", "footprint_source": "text_seed_scope", "render_as_scope": True, "render_solid": False, "wall_geometry_reliable": False}))
                    areas.append(self._rect_area("area_office_mezzanine", "area.office.mezzanine", "办公区二层（夹层）", min_x, min_y, max_x, max_y, {"level": 2, "height_m": OFFICE_ROOM_HEIGHT_M, "floor_elevation_m": OFFICE_SECOND_FLOOR_ELEVATION_M, "deck_height_m": OFFICE_SECOND_FLOOR_ELEVATION_M, "height_source": "visual_clearance_exaggerated", "footprint_source": "text_seed_scope", "render_as_scope": True, "render_solid": False, "wall_geometry_reliable": False}))

        lift_markers: list[dict[str, float]] = []
        for structure_layer in ("STRS-楼梯、台阶、坡道、升降平台、月台、救援平台",):
            for entity in entities:
                if entity.get("layer") != structure_layer or entity.get("entity_type") != "INSERT":
                    continue
                position = entity.get("geometry", {}).get("position")
                if not position or self._plan_copy_index(position) != 0:
                    continue
                folded_position, _ = self._fold_point(position)
                if office_model and office_model.get("floors") and self._point_in_office_footprint(folded_position, office_model):
                    continue
                if -990_000 <= folded_position["y"] <= -820_000:
                    lift_markers.append(folded_position)
        seen_lifts: set[tuple[int, int]] = set()
        for idx, point in enumerate(lift_markers, start=1):
            key = (round(point["x"] / 2000), round(point["y"] / 2000))
            if key in seen_lifts:
                continue
            seen_lifts.add(key)
            areas.append(
                self._rect_area(
                    f"area_lift_{idx:03d}",
                    "area.lift_platform",
                    f"升降平台 {idx:02d}",
                    point["x"] - 1800.0,
                    point["y"] - 1200.0,
                    point["x"] + 1800.0,
                    point["y"] + 1200.0,
                    {"height_m": DOCK_HEIGHT_M, "source": "STRS升降平台/月台图层"},
                )
            )
        return areas

    @staticmethod
    def _rect_area(area_id: str, area_type: str, label: str, min_x: float, min_y: float, max_x: float, max_y: float, attributes: dict[str, Any]) -> dict[str, Any]:
        return {
            "id": area_id,
            "type": area_type,
            "label": label,
            "confidence": 0.78,
            "geometry": {
                "type": "Polygon",
                "closed": True,
                "points": [
                    {"x": min_x, "y": min_y},
                    {"x": max_x, "y": min_y},
                    {"x": max_x, "y": max_y},
                    {"x": min_x, "y": max_y},
                ],
            },
            "attributes": attributes,
        }

    @staticmethod
    def _polygon_area(area_id: str, area_type: str, label: str, points: list[dict[str, float]], attributes: dict[str, Any]) -> dict[str, Any]:
        return {
            "id": area_id,
            "type": area_type,
            "label": label,
            "confidence": 0.86,
            "geometry": {
                "type": "Polygon",
                "closed": True,
                "points": [dict(point) for point in points],
            },
            "attributes": attributes,
        }

    def _infer_tray_cables(self, entities: list[dict[str, Any]]) -> list[dict[str, Any]]:
        markers: list[dict[str, Any]] = []
        seen_positions: set[tuple[int, int]] = set()
        for entity in entities:
            if entity.get("entity_type") not in {"TEXT", "MTEXT"}:
                continue
            text = str(entity.get("text", "")).strip()
            if "桥架" not in text or "镀锌" not in text:
                continue
            if re.search(r"安装高度\s*6(?:\.0)?\s*米", text):
                continue
            position = entity.get("geometry", {}).get("position")
            if not position or self._plan_copy_index(position) is None:
                continue
            folded_position, copy_index = self._fold_point(position)
            key = (round(folded_position["x"] / 100.0), round(folded_position["y"] / 100.0))
            if key in seen_positions:
                continue
            seen_positions.add(key)
            markers.append(
                {
                    "source_entity_id": entity["source_entity_id"],
                    "copy_index": copy_index,
                    "position": folded_position,
                    "text": text,
                }
            )

        segments: list[dict[str, Any]] = []
        for axis in ("x", "y"):
            for cluster in self._cluster_markers(markers, axis):
                ordered = sorted(cluster, key=lambda item: item["position"]["y" if axis == "x" else "x"])
                for start, end in zip(ordered, ordered[1:]):
                    p1 = start["position"]
                    p2 = end["position"]
                    if axis == "x":
                        avg_x = (p1["x"] + p2["x"]) / 2.0
                        points = [{"x": avg_x, "y": p1["y"]}, {"x": avg_x, "y": p2["y"]}]
                    else:
                        avg_y = (p1["y"] + p2["y"]) / 2.0
                        points = [{"x": p1["x"], "y": avg_y}, {"x": p2["x"], "y": avg_y}]
                    length_mm = line_length(points)
                    if length_mm < TRAY_MIN_SEGMENT_MM:
                        continue
                    segments.append(
                        {
                            "id": f"cable_tray_{len(segments) + 1:03d}",
                            "type": "cable.trunk",
                            "source_entity_id": f"{start['source_entity_id']}+{end['source_entity_id']}",
                            "original_layer": "CABLETRAY_DIM",
                            "confidence": 0.78,
                            "review_needed": False,
                            "geometry": {"type": "LineString", "points": points},
                            "length_mm": length_mm,
                            "attributes": {
                                "source_kind": "tray_label_inferred",
                                "source_text": "镀锌桥架",
                            },
                        }
                    )
        return self._dedup_linear_items(segments)

    @staticmethod
    def _cluster_markers(markers: list[dict[str, Any]], axis: str) -> list[list[dict[str, Any]]]:
        if not markers:
            return []
        ordered = sorted(markers, key=lambda item: item["position"][axis])
        clusters: list[list[dict[str, Any]]] = []
        current: list[dict[str, Any]] = [ordered[0]]
        current_value = ordered[0]["position"][axis]
        for marker in ordered[1:]:
            value = marker["position"][axis]
            if abs(value - current_value) <= TRAY_LABEL_TOLERANCE_MM:
                current.append(marker)
                current_value = sum(item["position"][axis] for item in current) / len(current)
            else:
                if len(current) > 1:
                    clusters.append(current)
                current = [marker]
                current_value = value
        if len(current) > 1:
            clusters.append(current)
        return clusters

    def _fold_item_geometry(self, item: dict[str, Any]) -> dict[str, Any]:
        geometry = item.get("geometry")
        if not geometry:
            return item
        folded_geometry, fold = self._fold_geometry(geometry)
        if not fold:
            return item
        folded = {**item, "geometry": folded_geometry}
        if folded.get("length_mm") and folded_geometry.get("points"):
            folded["length_mm"] = line_length(folded_geometry["points"])
        attributes = {**folded.get("attributes", {})}
        if fold.get("system_view"):
            attributes["merged_from_system_view"] = fold["system_view"]
        else:
            attributes["merged_from_plan_copy"] = int(fold["copy_index"]) + 1
        attributes["merge_offset_x_mm"] = fold["offset_x"]
        attributes["merge_offset_y_mm"] = fold["offset_y"]
        folded["attributes"] = attributes
        return folded

    def _fold_geometry(self, geometry: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any] | None]:
        anchor = self._geometry_anchor(geometry)
        if not anchor:
            return geometry, None
        fold = self._fold_offset_for_point(anchor)
        if not fold:
            return geometry, None
        offset_x = float(fold["offset_x"])
        offset_y = float(fold["offset_y"])
        folded = {**geometry}
        if "position" in geometry:
            folded["position"] = {**geometry["position"], "x": geometry["position"]["x"] - offset_x, "y": geometry["position"]["y"] - offset_y}
        if "points" in geometry:
            folded["points"] = [{**point, "x": point["x"] - offset_x, "y": point["y"] - offset_y} for point in geometry.get("points", [])]
        if "center" in geometry:
            folded["center"] = {**geometry["center"], "x": geometry["center"]["x"] - offset_x, "y": geometry["center"]["y"] - offset_y}
        return folded, fold

    def _fold_point(self, point: dict[str, float]) -> tuple[dict[str, float], int]:
        fold = self._fold_offset_for_point(point)
        if not fold:
            return point, 0
        return {**point, "x": point["x"] - float(fold["offset_x"]), "y": point["y"] - float(fold["offset_y"])}, int(fold.get("copy_index") or 0)

    def _fold_offset_for_point(self, point: dict[str, float]) -> dict[str, Any] | None:
        view = self._system_view_for_point(point)
        if view:
            return {
                "copy_index": int(view["index"]) + 1,
                "offset_x": float(view["offset_x"]),
                "offset_y": float(view["offset_y"]),
                "system_view": view["kind"],
            }
        copy_index = self._legacy_plan_copy_index(point)
        if copy_index is None or copy_index <= 0:
            return None
        return {
            "copy_index": copy_index,
            "offset_x": copy_index * PLAN_COPY_OFFSET_X_MM,
            "offset_y": 0.0,
        }

    @staticmethod
    def _geometry_anchor(geometry: dict[str, Any]) -> dict[str, float] | None:
        if geometry.get("position"):
            return geometry["position"]
        if geometry.get("center"):
            return geometry["center"]
        points = geometry.get("points") or []
        if points:
            return {
                "x": sum(point["x"] for point in points) / len(points),
                "y": sum(point["y"] for point in points) / len(points),
            }
        return None

    def _infer_reference_regions(self, entities: list[dict[str, Any]]) -> list[dict[str, Any]]:
        regions: list[dict[str, Any]] = []
        seen: set[tuple[int, int, str]] = set()
        for entity in entities:
            if entity.get("entity_type") not in {"TEXT", "MTEXT"}:
                continue
            text = str(entity.get("text") or "").strip()
            if self._is_demolition_text(text):
                continue
            if self._is_system_view_text(text):
                continue
            if not self._is_reference_region_text(text):
                continue
            position = entity.get("geometry", {}).get("position")
            if not position:
                continue
            pad_x, pad_y = self._reference_region_padding(text)
            key = (round(position["x"] / 1000.0), round(position["y"] / 1000.0), text[:20])
            if key in seen:
                continue
            seen.add(key)
            regions.append(
                {
                    "type": "reference.note" if self._is_reference_note_text(text) else "reference.detail",
                    "reason": "工艺、安装、剖面/立面和图示说明作为读取参考，不直接生成3D模型",
                    "excludes_model": not self._is_reference_note_text(text),
                    "source_entity_id": entity.get("source_entity_id"),
                    "source_text": text[:120],
                    "bounds": {
                        "min_x": position["x"] - pad_x,
                        "max_x": position["x"] + pad_x,
                        "min_y": position["y"] - pad_y,
                        "max_y": position["y"] + pad_y,
                    },
                }
            )
        return regions

    @staticmethod
    def _is_reference_region_text(text: str) -> bool:
        normalized = re.sub(r"\s+", "", text)
        if not normalized:
            return False
        if "首层平面图" in normalized:
            return False
        return any(keyword in normalized for keyword in REFERENCE_REGION_KEYWORDS)

    @staticmethod
    def _is_reference_note_text(text: str) -> bool:
        normalized = re.sub(r"\s+", "", text)
        return any(keyword in normalized for keyword in ("施工工艺", "工艺要求", "图示说明"))

    @staticmethod
    def _is_system_view_text(text: str) -> bool:
        normalized = re.sub(r"\s+", "", text)
        if not normalized:
            return False
        if any(keyword in normalized for keyword in ("正面示意图", "侧面示意图", "剖面示意图", "立面图", "安装示意", "悬挂方案")):
            return False
        return any(keyword in normalized for keyword in SYSTEM_VIEW_KEYWORDS)

    @staticmethod
    def _reference_region_padding(text: str) -> tuple[float, float]:
        normalized = re.sub(r"\s+", "", text)
        if any(keyword in normalized for keyword in ("施工工艺", "工艺要求", "图示说明")):
            return REFERENCE_NOTE_PAD_MM
        return REFERENCE_DETAIL_PAD_MM

    def _extract_process_notes(self, entities: list[dict[str, Any]]) -> list[str]:
        return self._extract_note_lines(entities, PROCESS_NOTE_KEYWORDS)

    def _extract_removal_notes(self, entities: list[dict[str, Any]]) -> list[str]:
        return self._extract_note_lines(entities, REMOVAL_NOTE_KEYWORDS, stop_keywords=REMOVAL_NOTE_STOP_KEYWORDS)

    def _extract_note_lines(
        self,
        entities: list[dict[str, Any]],
        keywords: tuple[str, ...],
        stop_keywords: tuple[str, ...] = (),
    ) -> list[str]:
        matched_texts: list[tuple[float, float, str]] = []
        for entity in entities:
            if entity.get("entity_type") not in {"TEXT", "MTEXT"}:
                continue
            text = str(entity.get("text") or "").strip()
            if not text:
                continue
            normalized = re.sub(r"\s+", "", text)
            if not any(keyword in normalized for keyword in keywords):
                continue
            position = entity.get("geometry", {}).get("position") or {}
            matched_texts.append((float(position.get("y", 0.0)), float(position.get("x", 0.0)), text))

        lines: list[str] = []
        seen: set[str] = set()
        for _, _, text in sorted(matched_texts, key=lambda item: (item[0], item[1])):
            for line in self._split_note_lines(text):
                normalized_line = re.sub(r"\s+", "", line)
                if stop_keywords and any(keyword in normalized_line for keyword in stop_keywords):
                    break
                if not normalized_line or normalized_line in seen:
                    continue
                seen.add(normalized_line)
                lines.append(line)
        return lines

    @staticmethod
    def _split_note_lines(text: str) -> list[str]:
        return [
            line.strip()
            for line in re.split(r"[\r\n]+", text)
            if line.strip()
        ]

    def _infer_ignored_regions(self, entities: list[dict[str, Any]]) -> list[dict[str, Any]]:
        regions: list[dict[str, Any]] = []
        seen: set[tuple[int, int, str]] = set()
        for entity in entities:
            if entity.get("entity_type") not in {"TEXT", "MTEXT"}:
                continue
            text = str(entity.get("text") or "").strip()
            if not self._is_demolition_text(text):
                continue
            position = entity.get("geometry", {}).get("position")
            if not position:
                continue
            key = (round(position["x"] / 1000.0), round(position["y"] / 1000.0), text[:20])
            if key in seen:
                continue
            seen.add(key)
            pad_x, pad_y = DEMOLITION_IGNORE_PAD_MM
            bounds = {
                "min_x": position["x"] - pad_x,
                "max_x": position["x"] + pad_x,
                "min_y": position["y"] - pad_y,
                "max_y": position["y"] + pad_y,
            }
            hit_count = self._region_entity_hit_count(bounds, entities)
            hit_ratio = hit_count / max(len(entities), 1)
            active = hit_ratio <= DEMOLITION_IGNORE_MAX_HIT_RATIO and hit_count <= DEMOLITION_IGNORE_MAX_HIT_COUNT
            filter_scope = "region" if active else DEMOLITION_IGNORE_SOURCE_ONLY
            regions.append(
                {
                    "type": "ignore.demolition",
                    "active": active,
                    "filter_scope": filter_scope,
                    "reason": (
                        "老库/老场地拆除内容不生成本期3D模型"
                        if active
                        else "拆除说明框覆盖主图实体过多，降级为仅忽略触发说明文字，避免过滤主图"
                    ),
                    "source_entity_id": entity.get("source_entity_id"),
                    "source_text": text[:120],
                    "hit_count": hit_count,
                    "hit_ratio": round(hit_ratio, 4),
                    "bounds": bounds,
                }
            )
        active_regions = [region for region in regions if region.get("active")]
        if active_regions:
            group_hit_count = self._regions_entity_hit_count(active_regions, entities)
            group_hit_ratio = group_hit_count / max(len(entities), 1)
            if group_hit_ratio > DEMOLITION_IGNORE_MAX_HIT_RATIO or group_hit_count > DEMOLITION_IGNORE_MAX_HIT_COUNT:
                for region in active_regions:
                    region["active"] = False
                    region["filter_scope"] = DEMOLITION_IGNORE_SOURCE_ONLY
                    region["group_hit_count"] = group_hit_count
                    region["group_hit_ratio"] = round(group_hit_ratio, 4)
                    region["reason"] = "拆除/老场地图框累计覆盖主图实体过多，降级为仅忽略触发说明文字，避免过滤本期主图"
        return regions

    def _region_entity_hit_count(self, bounds: dict[str, float], entities: list[dict[str, Any]]) -> int:
        region = {"bounds": bounds}
        count = 0
        for entity in entities:
            anchor = self._geometry_anchor(entity.get("geometry") or {})
            if anchor and self._point_in_region(anchor, region):
                count += 1
        return count

    def _regions_entity_hit_count(self, regions: list[dict[str, Any]], entities: list[dict[str, Any]]) -> int:
        count = 0
        for entity in entities:
            anchor = self._geometry_anchor(entity.get("geometry") or {})
            if anchor and any(self._point_in_region(anchor, region) for region in regions):
                count += 1
        return count

    @staticmethod
    def _is_demolition_text(text: str) -> bool:
        normalized = re.sub(r"\s+", "", text)
        if not normalized:
            return False
        return any(keyword in normalized for keyword in DEMOLITION_IGNORE_KEYWORDS)

    def _infer_frames(self, entities: list[dict[str, Any]]) -> list[dict[str, Any]]:
        rects = self._frame_rect_candidates(entities)
        system_titles = self._system_view_titles(entities)
        frames: list[dict[str, Any]] = []
        used_rect_ids: set[str] = set()

        for title in sorted(system_titles, key=lambda item: (item["position"]["y"], item["position"]["x"])):
            rect = self._nearest_system_frame_rect(title, rects)
            if not rect:
                rect = self._system_frame_rect_from_red_lines(title, entities)
            if not rect:
                rect = self._system_frame_rect_from_text_cluster(title, entities)
            bounds = rect["bounds"] if rect else self._fallback_system_frame_bounds(title)
            if rect:
                used_rect_ids.add(str(rect.get("source_entity_id")))
            frames.append(
                self._frame(
                    frame_id=f"frame_system_{title['kind']}",
                    kind="system_view",
                    title=title["text"],
                    bounds=bounds,
                    source=str(rect.get("source") or "cad_rect_near_title") if rect else "title_anchor_fallback",
                    system_view_kind=title["kind"],
                    source_entity_id=title.get("source_entity_id"),
                    reference_only=False,
                )
            )

        manual = self._manual_main_frame()
        if manual and self._manual_frame_overlaps_non_main_frame(manual, frames):
            manual = None
        if manual:
            frames.append(
                self._frame(
                    frame_id="frame_manual_main",
                    kind="main_plan",
                    title="手动框选主平面",
                    bounds=manual,
                    source="manual_main_frame",
                    reference_only=False,
                )
            )

        plan_rects = [
            rect
            for rect in rects
            if str(rect.get("source_entity_id")) not in used_rect_ids
            and rect["bounds"]["min_y"] > self._system_row_bottom_y(frames)
        ]
        main_rect = self._main_plan_rect(plan_rects, entities)
        if main_rect and not manual:
            frames.append(
                self._frame(
                    frame_id="frame_main_plan",
                    kind="main_plan",
                    title=main_rect.get("title") or "现方案主平面",
                    bounds=main_rect["bounds"],
                    source=main_rect.get("source") or "cad_plan_frame",
                    source_entity_id=main_rect.get("source_entity_id"),
                    reference_only=False,
                )
            )
        if main_rect or manual:
            base_bounds = manual or (main_rect or {}).get("bounds")
            if base_bounds:
                for rect in plan_rects:
                    if main_rect and rect.get("source_entity_id") == main_rect.get("source_entity_id"):
                        continue
                    bounds = rect["bounds"]
                    if bounds["max_x"] <= base_bounds["min_x"] - 2_000.0:
                        frames.append(
                            self._frame(
                                frame_id=f"frame_reference_{len(frames)}",
                                kind="reference_plan",
                                title="旧方案/拆除参考平面",
                                bounds=bounds,
                                source="cad_plan_frame_left_of_main",
                                source_entity_id=rect.get("source_entity_id"),
                                reference_only=True,
                            )
                        )

        return self._dedupe_frames(frames)

    def _frame_rect_candidates(self, entities: list[dict[str, Any]]) -> list[dict[str, Any]]:
        candidates: list[dict[str, Any]] = []
        for entity in entities:
            if entity.get("entity_type") not in {"LWPOLYLINE", "POLYLINE"}:
                continue
            geometry = entity.get("geometry") or {}
            points = geometry.get("points") or []
            if len(points) < 4:
                continue
            bbox = self._points_bbox(points)
            if not bbox:
                continue
            span_x = bbox["max_x"] - bbox["min_x"]
            span_y = bbox["max_y"] - bbox["min_y"]
            if not (30_000.0 <= span_x <= 900_000.0 and 25_000.0 <= span_y <= 800_000.0):
                continue
            ratio = span_x / max(span_y, 1.0)
            if not (0.75 <= ratio <= 2.2):
                continue
            layer = str(entity.get("layer") or "")
            if not any(keyword in layer for keyword in ("A-ROAD-RED", "改造修改-道口", "图框", "边框", "S_SURFACE")):
                continue
            candidates.append(
                {
                    "bounds": bbox,
                    "span_x": span_x,
                    "span_y": span_y,
                    "area": span_x * span_y,
                    "closed": bool(geometry.get("closed") or geometry.get("type") == "Polygon"),
                    "layer": layer,
                    "source_entity_id": entity.get("source_entity_id"),
                }
            )
        return sorted(candidates, key=lambda item: (item["bounds"]["min_y"], item["bounds"]["min_x"]))

    def _system_view_titles(self, entities: list[dict[str, Any]]) -> list[dict[str, Any]]:
        titles: list[dict[str, Any]] = []
        seen: set[str] = set()
        for entity in entities:
            if entity.get("entity_type") not in {"TEXT", "MTEXT"}:
                continue
            text = str(entity.get("text") or "").strip()
            kind = self._system_view_kind(text)
            position = entity.get("geometry", {}).get("position")
            if not kind or not position:
                continue
            key = f"{kind}:{round(position['x'])}:{round(position['y'])}"
            if key in seen:
                continue
            seen.add(key)
            titles.append(
                {
                    "kind": kind,
                    "text": text[:80],
                    "position": position,
                    "source_entity_id": entity.get("source_entity_id"),
                }
            )
        return titles

    def _nearest_system_frame_rect(self, title: dict[str, Any], rects: list[dict[str, Any]]) -> dict[str, Any] | None:
        pos = title["position"]
        matches: list[tuple[float, dict[str, Any]]] = []
        for rect in rects:
            bounds = rect["bounds"]
            center = self._bbox_center(bounds)
            span_x = bounds["max_x"] - bounds["min_x"]
            span_y = bounds["max_y"] - bounds["min_y"]
            if bounds["max_y"] > pos["y"] + max(8_000.0, span_y * 0.12):
                continue
            if pos["y"] - bounds["min_y"] > max(80_000.0, span_y * 2.25):
                continue
            if abs(center["x"] - pos["x"]) > max(95_000.0, span_x * 1.25):
                continue
            distance = abs(center["x"] - pos["x"]) + abs(bounds["max_y"] - pos["y"]) * 1.5
            matches.append((distance, rect))
        if not matches:
            return None
        return min(matches, key=lambda item: item[0])[1]

    def _system_frame_rect_from_red_lines(
        self,
        title: dict[str, Any],
        entities: list[dict[str, Any]],
    ) -> dict[str, Any] | None:
        pos = title["position"]
        horizontals: list[dict[str, Any]] = []
        for entity in entities:
            if entity.get("entity_type") != "LINE":
                continue
            if int(entity.get("effective_color") or entity.get("color") or 0) != 1:
                continue
            points = (entity.get("geometry") or {}).get("points") or []
            if len(points) != 2:
                continue
            start, end = points
            dx = float(end["x"]) - float(start["x"])
            dy = float(end["y"]) - float(start["y"])
            length = (dx * dx + dy * dy) ** 0.5
            if length < 150_000.0 or abs(dy) > max(500.0, length * 0.01):
                continue
            min_x = min(float(start["x"]), float(end["x"]))
            max_x = max(float(start["x"]), float(end["x"]))
            y = (float(start["y"]) + float(end["y"])) / 2.0
            if not (min_x - 20_000.0 <= float(pos["x"]) <= max_x + 20_000.0):
                continue
            if not (float(pos["y"]) - 260_000.0 <= y <= float(pos["y"]) + 25_000.0):
                continue
            horizontals.append(
                {
                    "min_x": min_x,
                    "max_x": max_x,
                    "y": y,
                    "length": length,
                    "source_entity_id": entity.get("source_entity_id"),
                    "layer": entity.get("layer"),
                }
            )

        matches: list[tuple[float, dict[str, Any]]] = []
        for top in horizontals:
            if abs(float(top["y"]) - float(pos["y"])) > 30_000.0:
                continue
            for bottom in horizontals:
                span_y = float(top["y"]) - float(bottom["y"])
                if not (80_000.0 <= span_y <= 260_000.0):
                    continue
                if abs(float(top["min_x"]) - float(bottom["min_x"])) > 8_000.0:
                    continue
                if abs(float(top["max_x"]) - float(bottom["max_x"])) > 8_000.0:
                    continue
                span_x = max(float(top["max_x"]), float(bottom["max_x"])) - min(float(top["min_x"]), float(bottom["min_x"]))
                score = abs(float(top["y"]) - float(pos["y"])) + abs(span_y - 188_000.0) * 0.15 - span_x * 0.001
                matches.append(
                    (
                        score,
                        {
                            "bounds": {
                                "min_x": min(float(top["min_x"]), float(bottom["min_x"])),
                                "max_x": max(float(top["max_x"]), float(bottom["max_x"])),
                                "min_y": min(float(top["y"]), float(bottom["y"])),
                                "max_y": max(float(top["y"]), float(bottom["y"])),
                            },
                            "span_x": span_x,
                            "span_y": span_y,
                            "area": span_x * span_y,
                            "closed": False,
                            "layer": top.get("layer"),
                            "source": "cad_red_line_pair_near_title",
                            "source_entity_id": top.get("source_entity_id"),
                        },
                    )
                )
        if not matches:
            return None
        return min(matches, key=lambda item: item[0])[1]

    def _system_frame_rect_from_text_cluster(
        self,
        title: dict[str, Any],
        entities: list[dict[str, Any]],
    ) -> dict[str, Any] | None:
        pos = title["position"]
        kind = str(title.get("kind") or "")
        text_points: list[dict[str, float]] = []
        for entity in entities:
            if entity.get("entity_type") not in {"TEXT", "MTEXT"}:
                continue
            point = (entity.get("geometry") or {}).get("position")
            if not point:
                continue
            dx = float(point["x"]) - float(pos["x"])
            dy = float(point["y"]) - float(pos["y"])
            if -320_000.0 <= dx <= 180_000.0 and -420_000.0 <= dy <= 30_000.0:
                text_points.append(point)
        if len(text_points) < 8:
            return None
        bounds = self._points_bbox(text_points)
        if not bounds:
            return None
        span_x = bounds["max_x"] - bounds["min_x"]
        span_y = bounds["max_y"] - bounds["min_y"]
        if span_x < 60_000.0 or span_y < 45_000.0:
            return None
        if span_x > 260_000.0 or span_y > 260_000.0:
            return None
        pad_x = 12_000.0
        pad_y = 10_000.0
        padded = {
            "min_x": bounds["min_x"] - pad_x,
            "max_x": bounds["max_x"] + pad_x,
            "min_y": bounds["min_y"] - pad_y,
            "max_y": bounds["max_y"] + pad_y,
        }
        return {
            "bounds": padded,
            "span_x": padded["max_x"] - padded["min_x"],
            "span_y": padded["max_y"] - padded["min_y"],
            "area": (padded["max_x"] - padded["min_x"]) * (padded["max_y"] - padded["min_y"]),
            "closed": False,
            "layer": "TEXT_CLUSTER",
            "source": "text_cluster_near_system_title",
            "source_entity_id": title.get("source_entity_id"),
            "system_view_kind": kind,
        }

    @staticmethod
    def _fallback_system_frame_bounds(title: dict[str, Any]) -> dict[str, float]:
        pos = title["position"]
        kind = str(title.get("kind") or "")
        rel_bounds = {**SYSTEM_VIEW_REL_BOUNDS_MM, **SYSTEM_VIEW_REL_BOUNDS_BY_KIND_MM.get(kind, {})}
        return {
            "min_x": pos["x"] + rel_bounds["min_x"],
            "max_x": pos["x"] + rel_bounds["max_x"],
            "min_y": pos["y"] + rel_bounds["min_y"],
            "max_y": pos["y"] + rel_bounds["max_y"],
        }

    @staticmethod
    def _system_row_bottom_y(frames: list[dict[str, Any]]) -> float:
        system_frames = [frame for frame in frames if frame.get("kind") == "system_view"]
        if not system_frames:
            return float("-inf")
        return max(float(frame.get("bounds", {}).get("max_y", float("-inf"))) for frame in system_frames) + 5_000.0

    def _manual_frame_overlaps_non_main_frame(self, bounds: dict[str, float], frames: list[dict[str, Any]]) -> bool:
        manual_area = self._bbox_area(bounds)
        if manual_area <= 0:
            return True
        for frame in frames:
            if frame.get("kind") not in {"system_view", "reference_plan"} and not frame.get("reference_only"):
                continue
            frame_bounds = frame.get("bounds") or {}
            frame_area = self._bbox_area(frame_bounds)
            if frame_area <= 0:
                continue
            overlap = self._bbox_overlap_area(bounds, frame_bounds)
            if overlap / max(min(manual_area, frame_area), 1.0) >= 0.85:
                return True
        return False

    def _main_plan_rect(self, plan_rects: list[dict[str, Any]], entities: list[dict[str, Any]]) -> dict[str, Any] | None:
        if not plan_rects:
            return None
        if len(plan_rects) == 1:
            return {**plan_rects[0], "title": "现方案主平面", "source": "single_plan_frame"}
        main_seeds: list[dict[str, Any]] = []
        for entity in entities:
            if entity.get("entity_type") not in {"TEXT", "MTEXT"}:
                continue
            text = str(entity.get("text") or "")
            normalized = re.sub(r"\s+", "", text)
            if not any(keyword in normalized for keyword in ("面积变化", "现方案", "当前方案", "新方案", "方案0703", "IT弱电规划")):
                continue
            position = entity.get("geometry", {}).get("position")
            if position:
                main_seeds.append({"position": position, "text": text[:80]})
        scored: list[tuple[int, float, float, int, dict[str, Any]]] = []
        for rect in plan_rects:
            bounds = rect["bounds"]
            center = self._bbox_center(bounds)
            contains_seed = any(self._point_in_bounds(seed["position"], bounds, pad_mm=10_000.0) for seed in main_seeds)
            candidate = {**rect}
            if contains_seed:
                candidate["title"] = "现方案主平面"
                candidate["source"] = "cad_plan_frame_contains_current_scheme_note"
            else:
                candidate.setdefault("title", "现方案主平面")
                candidate.setdefault("source", "cad_plan_frame_max_x")
            scored.append(
                (
                    1 if contains_seed else 0,
                    center["x"],
                    float(rect.get("area", 0.0)),
                    1 if rect.get("closed") else 0,
                    candidate,
                )
            )
        if not scored:
            return None
        return max(scored, key=lambda item: item[:4])[4]

    def _frame(
        self,
        *,
        frame_id: str,
        kind: str,
        title: str,
        bounds: dict[str, float],
        source: str,
        system_view_kind: str | None = None,
        source_entity_id: str | None = None,
        reference_only: bool = False,
    ) -> dict[str, Any]:
        span_x = float(bounds["max_x"] - bounds["min_x"])
        span_y = float(bounds["max_y"] - bounds["min_y"])
        frame: dict[str, Any] = {
            "frame_id": frame_id,
            "kind": kind,
            "title": title,
            "bounds": {key: float(value) for key, value in bounds.items()},
            "area": span_x * span_y,
            "span_x_mm": span_x,
            "span_y_mm": span_y,
            "source": source,
            "reference_only": reference_only,
        }
        if system_view_kind:
            frame["system_view_kind"] = system_view_kind
        if source_entity_id:
            frame["source_entity_id"] = source_entity_id
        return frame

    @staticmethod
    def _dedupe_frames(frames: list[dict[str, Any]]) -> list[dict[str, Any]]:
        deduped: list[dict[str, Any]] = []
        seen: set[tuple[int, int, str, str]] = set()
        for frame in frames:
            bounds = frame.get("bounds") or {}
            kind = str(frame.get("kind"))
            key = (
                round(float(bounds.get("min_x", 0.0)) / 1000.0),
                round(float(bounds.get("min_y", 0.0)) / 1000.0),
                kind,
                str(frame.get("system_view_kind") or "") if kind == "system_view" else "",
            )
            if key in seen:
                continue
            seen.add(key)
            frame["index"] = len(deduped)
            deduped.append(frame)
        return deduped

    def _select_base_view(self, frames: list[dict[str, Any]]) -> dict[str, Any] | None:
        main_frames = [frame for frame in frames if frame.get("kind") == "main_plan" and not frame.get("reference_only")]
        if main_frames:
            chosen = max(
                main_frames,
                key=lambda frame: (
                    1 if frame.get("source") == "manual_main_frame" else 0,
                    float(frame.get("area", 0.0)),
                    self._bbox_center(frame.get("bounds") or {}).get("x", 0.0),
                ),
            )
            return {
                "view_id": "base_main_plan",
                "kind": "main_plan",
                "frame_id": chosen.get("frame_id"),
                "title": chosen.get("title"),
                "bounds": chosen.get("bounds"),
                "source": chosen.get("source"),
                "no_main_plan_mode": False,
            }
        system_frames = [frame for frame in frames if frame.get("kind") == "system_view"]
        if system_frames:
            has_reliable_system_frame = any(frame.get("source") != "title_anchor_fallback" for frame in system_frames)
            priority = (
                {
                    "monitor": 5,
                    "network_broadcast": 4,
                    "network": 3,
                    "cabinet_link": 2,
                    "cabinet_spotlight_power": 1,
                }
                if has_reliable_system_frame
                else {
                    "network_broadcast": 5,
                    "network": 4,
                    "monitor": 3,
                    "cabinet_link": 2,
                    "cabinet_spotlight_power": 1,
                }
            )
            chosen = max(
                system_frames,
                key=lambda frame: (
                    priority.get(str(frame.get("system_view_kind") or ""), 0),
                    float(frame.get("area", 0.0)),
                ),
            )
            return {
                "view_id": f"base_{chosen.get('system_view_kind') or 'system'}",
                "kind": chosen.get("system_view_kind") or "system_view",
                "frame_id": chosen.get("frame_id"),
                "title": chosen.get("title"),
                "bounds": chosen.get("bounds"),
                "source": "no_main_plan_fallback",
                "no_main_plan_mode": True,
            }
        return None

    def _infer_canonical_views(self) -> list[dict[str, Any]]:
        if not self.base_view:
            return []
        views: list[dict[str, Any]] = [
            {
                "view_id": self.base_view.get("view_id") or "base_view",
                "kind": self.base_view.get("kind"),
                "frame_id": self.base_view.get("frame_id"),
                "title": self.base_view.get("title"),
                "bounds": self.base_view.get("bounds"),
                "canonical_offset": {"x_mm": 0.0, "y_mm": 0.0},
                "is_base": True,
                "no_main_plan_mode": bool(self.base_view.get("no_main_plan_mode")),
            }
        ]
        for view in self.system_views:
            views.append(
                {
                    "view_id": f"view_{view.get('kind')}",
                    "kind": view.get("kind"),
                    "frame_id": view.get("frame_id"),
                    "title": view.get("source_text"),
                    "bounds": view.get("bounds"),
                    "canonical_offset": {"x_mm": view.get("offset_x", 0.0), "y_mm": view.get("offset_y", 0.0)},
                    "is_base": False,
                    "no_main_plan_mode": bool(self.base_view.get("no_main_plan_mode")),
                }
            )
        return views

    def _reference_regions_from_frames(self) -> list[dict[str, Any]]:
        regions: list[dict[str, Any]] = []
        for frame in self.frames:
            if not frame.get("reference_only"):
                continue
            regions.append(
                {
                    "type": "reference.frame",
                    "reason": "多图框切分判定为旧方案/拆除参考图，只保留为读取参考，不生成本期3D模型",
                    "excludes_model": True,
                    "source_entity_id": frame.get("source_entity_id"),
                    "source_text": frame.get("title"),
                    "frame_id": frame.get("frame_id"),
                    "bounds": frame.get("bounds"),
                }
            )
        return regions

    def _frame_partition_quality(self, devices: list[dict[str, Any]]) -> dict[str, Any]:
        base = self.base_view or {}
        bounds = base.get("bounds") or {}
        device_points = [device.get("geometry", {}).get("position") for device in devices if device.get("geometry", {}).get("position")]
        inside = sum(1 for point in device_points if self._point_in_bounds(point, bounds, pad_mm=6_000.0)) if bounds else 0
        span_x = float(bounds.get("max_x", 0.0) or 0.0) - float(bounds.get("min_x", 0.0) or 0.0)
        span_y = float(bounds.get("max_y", 0.0) or 0.0) - float(bounds.get("min_y", 0.0) or 0.0)
        ratio = inside / max(len(device_points), 1)
        return {
            "frames_detected": len(self.frames),
            "base_view": base,
            "canonical_views": len(self.canonical_views),
            "base_span_x_mm": span_x,
            "base_span_y_mm": span_y,
            "device_points_inside_base": inside,
            "device_points_total": len(device_points),
            "device_inside_base_ratio": round(ratio, 4),
            "status": "ok" if self.frames and (span_x >= 50_000.0 or base.get("no_main_plan_mode")) and ratio >= 0.95 else "review_needed",
        }

    def _manual_main_frame(self) -> dict[str, float] | None:
        frame = self.manual_main_frame or {}
        bounds = frame.get("bounds") if isinstance(frame.get("bounds"), dict) else frame
        try:
            min_x = float(bounds["min_x"])
            min_y = float(bounds["min_y"])
            max_x = float(bounds["max_x"])
            max_y = float(bounds["max_y"])
        except (KeyError, TypeError, ValueError):
            return None
        if max_x <= min_x or max_y <= min_y:
            return None
        return {"min_x": min_x, "min_y": min_y, "max_x": max_x, "max_y": max_y}

    @staticmethod
    def _bbox_center(bounds: dict[str, Any]) -> dict[str, float]:
        return {
            "x": (float(bounds.get("min_x", 0.0) or 0.0) + float(bounds.get("max_x", 0.0) or 0.0)) / 2.0,
            "y": (float(bounds.get("min_y", 0.0) or 0.0) + float(bounds.get("max_y", 0.0) or 0.0)) / 2.0,
        }

    @staticmethod
    def _bbox_area(bounds: dict[str, Any]) -> float:
        try:
            span_x = float(bounds.get("max_x", 0.0)) - float(bounds.get("min_x", 0.0))
            span_y = float(bounds.get("max_y", 0.0)) - float(bounds.get("min_y", 0.0))
        except (TypeError, ValueError):
            return 0.0
        return max(span_x, 0.0) * max(span_y, 0.0)

    @staticmethod
    def _bbox_overlap_area(a: dict[str, Any], b: dict[str, Any]) -> float:
        try:
            min_x = max(float(a.get("min_x", 0.0)), float(b.get("min_x", 0.0)))
            max_x = min(float(a.get("max_x", 0.0)), float(b.get("max_x", 0.0)))
            min_y = max(float(a.get("min_y", 0.0)), float(b.get("min_y", 0.0)))
            max_y = min(float(a.get("max_y", 0.0)), float(b.get("max_y", 0.0)))
        except (TypeError, ValueError):
            return 0.0
        return max(max_x - min_x, 0.0) * max(max_y - min_y, 0.0)

    @staticmethod
    def _bbox_intersects(a: dict[str, Any], b: dict[str, Any], pad_mm: float = 0.0) -> bool:
        try:
            return (
                float(a.get("max_x", 0.0)) + pad_mm >= float(b.get("min_x", 0.0))
                and float(a.get("min_x", 0.0)) - pad_mm <= float(b.get("max_x", 0.0))
                and float(a.get("max_y", 0.0)) + pad_mm >= float(b.get("min_y", 0.0))
                and float(a.get("min_y", 0.0)) - pad_mm <= float(b.get("max_y", 0.0))
            )
        except (TypeError, ValueError):
            return False

    @staticmethod
    def _point_in_bounds(point: dict[str, float] | None, bounds: dict[str, Any], pad_mm: float = 0.0) -> bool:
        if not point or not bounds:
            return False
        return (
            float(bounds.get("min_x", float("-inf"))) - pad_mm <= float(point.get("x", float("inf"))) <= float(bounds.get("max_x", float("-inf"))) + pad_mm
            and float(bounds.get("min_y", float("-inf"))) - pad_mm <= float(point.get("y", float("inf"))) <= float(bounds.get("max_y", float("-inf"))) + pad_mm
        )

    def _infer_system_views(self, entities: list[dict[str, Any]]) -> list[dict[str, Any]]:
        system_frames = [frame for frame in self.frames if frame.get("kind") == "system_view"]
        if system_frames:
            base_bounds = (self.base_view or {}).get("bounds") or system_frames[0].get("bounds") or {}
            base_origin = {"x": float(base_bounds.get("min_x", 0.0) or 0.0), "y": float(base_bounds.get("min_y", 0.0) or 0.0)}
            views: list[dict[str, Any]] = []
            for frame in sorted(system_frames, key=lambda item: (item.get("bounds", {}).get("min_y", 0.0), item.get("bounds", {}).get("min_x", 0.0))):
                kind = str(frame.get("system_view_kind") or "")
                bounds = frame.get("bounds") or {}
                origin = {"x": float(bounds.get("min_x", 0.0) or 0.0), "y": float(bounds.get("min_y", 0.0) or 0.0)}
                views.append(
                    {
                        "index": len(views),
                        "kind": kind,
                        "frame_id": frame.get("frame_id"),
                        "source_text": frame.get("title"),
                        "source_entity_id": frame.get("source_entity_id"),
                        "origin": origin,
                        "base_origin": base_origin,
                        "offset_x": origin["x"] - base_origin["x"],
                        "offset_y": origin["y"] - base_origin["y"],
                        "bounds": bounds,
                        "role": "同一场地系统视图，按图框左下角平移叠合到主平面/基准视图",
                    }
                )
            return views

        titles: list[dict[str, Any]] = []
        for entity in entities:
            if entity.get("entity_type") not in {"TEXT", "MTEXT"}:
                continue
            text = str(entity.get("text") or "").strip()
            kind = self._system_view_kind(text)
            if not kind:
                continue
            position = entity.get("geometry", {}).get("position")
            if not position:
                continue
            titles.append({"kind": kind, "text": text[:80], "position": position, "source_entity_id": entity.get("source_entity_id")})
        if not titles:
            return []
        kinds = {title["kind"] for title in titles}
        if len(kinds) < 2:
            return []
        base = next((title for title in titles if title["kind"] == "monitor"), None)
        if not base:
            base = sorted(titles, key=lambda title: (-title["position"]["y"], title["position"]["x"]))[0]
        base_pos = base["position"]
        views: list[dict[str, Any]] = []
        seen: set[str] = set()
        for title in sorted(titles, key=lambda item: (item["position"]["y"], item["position"]["x"])):
            if title["kind"] in seen:
                continue
            seen.add(title["kind"])
            pos = title["position"]
            rel_bounds = self._system_view_relative_bounds(title["kind"])
            bounds = {
                "min_x": pos["x"] + rel_bounds["min_x"],
                "max_x": pos["x"] + rel_bounds["max_x"],
                "min_y": pos["y"] + rel_bounds["min_y"],
                "max_y": pos["y"] + rel_bounds["max_y"],
            }
            views.append(
                {
                    "index": len(views),
                    "kind": title["kind"],
                    "source_text": title["text"],
                    "source_entity_id": title["source_entity_id"],
                    "origin": pos,
                    "base_origin": base_pos,
                    "offset_x": pos["x"] - base_pos["x"],
                    "offset_y": pos["y"] - base_pos["y"],
                    "bounds": bounds,
                    "role": "同一场地不同系统视图，需平移叠合到基准监控/主平面视图",
                }
                )
        return views

    def _refine_system_view_alignment(self, entities: list[dict[str, Any]]) -> None:
        if not self.system_views or not self.base_view or self.base_view.get("kind") != "main_plan":
            return
        base_bounds = self.base_view.get("bounds") or {}
        base_points = self._view_alignment_points(entities, base_bounds)
        if len(base_points) < SYSTEM_VIEW_ALIGNMENT_MIN_POINTS:
            return
        base_bbox = self._points_bbox(base_points)
        if not base_bbox:
            return

        for view in self.system_views:
            view_points = self._view_alignment_points(entities, view.get("bounds") or {})
            view_bbox = self._points_bbox(view_points)
            if not view_bbox:
                continue
            matched_offset = self._view_alignment_offset_by_point_match(
                base_points,
                view_points,
                current_offset_x=float(view.get("offset_x", 0.0) or 0.0),
                current_offset_y=float(view.get("offset_y", 0.0) or 0.0),
            )
            if not matched_offset:
                continue

            refined_offset_x = float(matched_offset["offset_x"])
            refined_offset_y = float(matched_offset["offset_y"])
            current_offset_x = float(view.get("offset_x", 0.0) or 0.0)
            current_offset_y = float(view.get("offset_y", 0.0) or 0.0)
            adjust_x = refined_offset_x - current_offset_x
            adjust_y = refined_offset_y - current_offset_y
            if (
                abs(adjust_x) > SYSTEM_VIEW_ALIGNMENT_MAX_ADJUST_X_MM
                or abs(adjust_y) > SYSTEM_VIEW_ALIGNMENT_MAX_ADJUST_Y_MM
            ):
                continue
            if abs(adjust_x) < 1.0 and abs(adjust_y) < 1.0:
                continue

            view["frame_offset_x"] = current_offset_x
            view["frame_offset_y"] = current_offset_y
            view["offset_x"] = refined_offset_x
            view["offset_y"] = refined_offset_y
            view["alignment"] = {
                "source": "repeated_structure_point_match",
                "layers": sorted(SYSTEM_VIEW_ALIGNMENT_LAYERS),
                "base_bbox": {key: round(float(value), 3) for key, value in base_bbox.items()},
                "view_bbox": {key: round(float(value), 3) for key, value in view_bbox.items()},
                "match_count": int(matched_offset["match_count"]),
                "bucket_mm": SYSTEM_VIEW_ALIGNMENT_BUCKET_MM,
                "adjust_x_mm": round(adjust_x, 3),
                "adjust_y_mm": round(adjust_y, 3),
            }

    def _view_alignment_points(self, entities: list[dict[str, Any]], bounds: dict[str, Any]) -> list[dict[str, float]]:
        if not bounds:
            return []
        points: list[dict[str, float]] = []
        for entity in entities:
            if entity.get("entity_type") not in {"LINE", "LWPOLYLINE", "POLYLINE"}:
                continue
            if str(entity.get("layer") or "") not in SYSTEM_VIEW_ALIGNMENT_LAYERS:
                continue
            anchor = self._geometry_anchor(entity.get("geometry") or {})
            if not self._point_in_bounds(anchor, bounds):
                continue
            points.extend(self._geometry_points(entity.get("geometry") or {}))
        return points

    def _view_alignment_offset_by_point_match(
        self,
        base_points: list[dict[str, float]],
        view_points: list[dict[str, float]],
        *,
        current_offset_x: float,
        current_offset_y: float,
    ) -> dict[str, float] | None:
        if len(base_points) < SYSTEM_VIEW_ALIGNMENT_MIN_POINTS or len(view_points) < SYSTEM_VIEW_ALIGNMENT_MIN_POINTS:
            return None
        bucket = SYSTEM_VIEW_ALIGNMENT_BUCKET_MM
        candidates: Counter[tuple[int, int]] = Counter()
        max_adjust_x = SYSTEM_VIEW_ALIGNMENT_MAX_ADJUST_X_MM
        max_adjust_y = SYSTEM_VIEW_ALIGNMENT_MAX_ADJUST_Y_MM
        for view_point in view_points:
            sx = float(view_point["x"])
            sy = float(view_point["y"])
            for base_point in base_points:
                dx = round((sx - float(base_point["x"])) / bucket) * bucket
                dy = round((sy - float(base_point["y"])) / bucket) * bucket
                if abs(dx - current_offset_x) > max_adjust_x or abs(dy - current_offset_y) > max_adjust_y:
                    continue
                candidates[(int(dx), int(dy))] += 1
        if not candidates:
            return None
        (offset_x, offset_y), match_count = candidates.most_common(1)[0]
        min_matches = max(SYSTEM_VIEW_ALIGNMENT_MIN_MATCHES, int(min(len(base_points), len(view_points)) * 0.35))
        if match_count < min_matches:
            return None
        return {
            "offset_x": float(offset_x),
            "offset_y": float(offset_y),
            "match_count": float(match_count),
        }

    @staticmethod
    def _alignment_spans_compatible(base_span_x: float, base_span_y: float, view_span_x: float, view_span_y: float) -> bool:
        if min(base_span_x, base_span_y, view_span_x, view_span_y) <= 0.0:
            return False
        ratio_x = view_span_x / base_span_x
        ratio_y = view_span_y / base_span_y
        return 0.55 <= ratio_x <= 1.75 and 0.55 <= ratio_y <= 1.75

    @staticmethod
    def _system_view_relative_bounds(kind: str) -> dict[str, float]:
        return {**SYSTEM_VIEW_REL_BOUNDS_MM, **SYSTEM_VIEW_REL_BOUNDS_BY_KIND_MM.get(kind, {})}

    @staticmethod
    def _system_view_kind(text: str) -> str | None:
        normalized = re.sub(r"\s+", "", text)
        if not normalized:
            return None
        is_view_title = any(keyword in normalized for keyword in ("示意图", "线路图", "链路图", "配电图"))
        if not is_view_title:
            return None
        if any(keyword in normalized for keyword in ("监控", "视频")):
            return "monitor"
        if "机柜" in normalized and any(keyword in normalized for keyword in ("级联", "链路")):
            return "cabinet_link"
        if "机柜" in normalized and any(keyword in normalized for keyword in ("射灯", "电缆", "电路")):
            return "cabinet_spotlight_power"
        if any(keyword in normalized for keyword in ("网络&广播", "网络广播")):
            return "network_broadcast"
        if any(keyword in normalized for keyword in ("网络", "广播", "AP")):
            return "network"
        if any(keyword in normalized for keyword in ("级联", "链路")):
            return "cascade"
        if any(keyword in normalized for keyword in ("电缆", "配电图", "电路")):
            return "cable"
        return None

    def _system_view_for_point(self, point: dict[str, float]) -> dict[str, Any] | None:
        candidates = [view for view in self.system_views if self._point_in_region(point, view)]
        if not candidates:
            return None
        return min(
            candidates,
            key=lambda view: (
                abs(point["x"] - view["origin"]["x"]) / max(SYSTEM_VIEW_REL_BOUNDS_MM["max_x"], 1.0)
                + abs(point["y"] - view["origin"]["y"]) / max(abs(SYSTEM_VIEW_REL_BOUNDS_MM["min_y"]), 1.0)
            ),
        )

    def _is_entity_ignored(self, entity: dict[str, Any]) -> bool:
        if not self.ignored_regions:
            return False
        source_id = str(entity.get("source_entity_id") or "")
        if any(
            region.get("filter_scope") == DEMOLITION_IGNORE_SOURCE_ONLY
            and source_id
            and source_id == str(region.get("source_entity_id") or "")
            for region in self.ignored_regions
        ):
            return True
        anchor = self._geometry_anchor(entity.get("geometry") or {})
        if not anchor:
            return False
        return any(region.get("active", True) and self._point_in_region(anchor, region) for region in self.ignored_regions)

    def _is_entity_reference(self, entity: dict[str, Any]) -> bool:
        if not self.reference_regions:
            return False
        anchor = self._geometry_anchor(entity.get("geometry") or {})
        if not anchor:
            return False
        return any(region.get("excludes_model", True) and self._point_in_region(anchor, region) for region in self.reference_regions)

    def _is_model_point(self, point: dict[str, float]) -> bool:
        if self._plan_copy_index(point) is not None:
            return True
        if not self.plan_windows and not self.system_views:
            return True
        return False

    def _is_model_device_point(self, point: dict[str, float], entity: dict[str, Any], semantic_type: str) -> bool:
        if self._is_model_point(point):
            return True
        return False

    @staticmethod
    def _point_in_region(point: dict[str, float], region: dict[str, Any]) -> bool:
        bounds = region.get("bounds", {})
        return (
            bounds.get("min_x", float("-inf")) <= point.get("x", float("inf")) <= bounds.get("max_x", float("-inf"))
            and bounds.get("min_y", float("-inf")) <= point.get("y", float("inf")) <= bounds.get("max_y", float("-inf"))
        )

    def _plan_copy_index(self, point: dict[str, float]) -> int | None:
        if self._system_view_for_point(point):
            return 0
        legacy_index = self._legacy_plan_copy_index(point)
        if legacy_index is not None:
            return legacy_index
        x = point.get("x")
        y = point.get("y")
        if x is None or y is None:
            return None
        for index, window in enumerate(self.plan_windows):
            if (
                window["min_x"] <= x <= window["max_x"]
                and window["min_y"] <= y <= window["max_y"]
            ):
                return index
        return None

    @staticmethod
    def _legacy_plan_copy_index(point: dict[str, float]) -> int | None:
        x = point.get("x")
        y = point.get("y")
        if x is None or y is None:
            return None
        if y < PLAN_MIN_Y_MM or y > PLAN_MAX_Y_MM:
            return None
        min_x = PLAN_COPY_START_X_MM
        max_x = PLAN_COPY_START_X_MM + PLAN_COPY_OFFSET_X_MM * PLAN_COPY_COUNT
        if x < min_x or x >= max_x:
            return None
        copy_index = int((x - PLAN_COPY_START_X_MM) // PLAN_COPY_OFFSET_X_MM)
        if 0 <= copy_index < PLAN_COPY_COUNT:
            return copy_index
        return None

    def _infer_plan_windows(self, entities: list[dict[str, Any]]) -> list[dict[str, float]]:
        if self.base_view and self.base_view.get("kind") == "main_plan" and self.base_view.get("bounds"):
            bounds = self.base_view["bounds"]
            return [
                {
                    "min_x": float(bounds["min_x"]),
                    "max_x": float(bounds["max_x"]),
                    "min_y": float(bounds["min_y"]),
                    "max_y": float(bounds["max_y"]),
                }
            ]
        if self.system_views:
            bounds = (self.base_view or {}).get("bounds")
            if bounds and self.base_view.get("no_main_plan_mode"):
                return [
                    {
                        "min_x": float(bounds["min_x"]),
                        "max_x": float(bounds["max_x"]),
                        "min_y": float(bounds["min_y"]),
                        "max_y": float(bounds["max_y"]),
                    }
                ]
            return []
        seeds: list[dict[str, float]] = []
        for entity in entities:
            if self._is_entity_ignored(entity) or self._is_entity_reference(entity):
                continue
            position = entity.get("geometry", {}).get("position")
            if not position:
                continue
            if self._legacy_plan_copy_index(position) is not None:
                return []
            text = str(entity.get("text") or "").strip()
            normalized = re.sub(r"\s+", "", text.upper())
            if not normalized:
                continue
            if (
                re.search(r"\b(CW|GX|YY|WH|WW|CD|OA)-\d{1,3}\b", normalized)
                or AP_LABEL_PATTERN.search(normalized)
                or "机柜" in text
            ):
                seeds.append(position)
        if len(seeds) < 3:
            return []

        min_x = min(point["x"] for point in seeds)
        max_x = max(point["x"] for point in seeds)
        min_y = min(point["y"] for point in seeds)
        max_y = max(point["y"] for point in seeds)
        span_x = max_x - min_x
        span_y = max_y - min_y
        pad_x = max(span_x * 1.4, 80_000.0)
        pad_y = max(span_y * 1.4, 80_000.0)
        return [
            {
                "min_x": min_x - pad_x,
                "max_x": max_x + pad_x,
                "min_y": min_y - pad_y,
                "max_y": max_y + pad_y,
            }
        ]

    @staticmethod
    def _dedup_linear_items(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
        seen: set[tuple[Any, ...]] = set()
        deduped: list[dict[str, Any]] = []
        for item in items:
            signature = RuleEngine._geometry_signature(item)
            if signature in seen:
                continue
            seen.add(signature)
            deduped.append(item)
        return deduped

    @staticmethod
    def _geometry_signature(item: dict[str, Any]) -> tuple[Any, ...]:
        geometry = item.get("geometry", {})
        if geometry.get("points"):
            coords = tuple((round(point["x"], 1), round(point["y"], 1)) for point in geometry.get("points", []))
        elif geometry.get("position"):
            pos = geometry["position"]
            coords = (round(pos["x"], 1), round(pos["y"], 1))
        elif geometry.get("center"):
            center = geometry["center"]
            coords = (round(center["x"], 1), round(center["y"], 1), round(float(geometry.get("radius", 0.0)), 1))
        else:
            coords = ()
        attrs = item.get("attributes", {})
        source_identity = None
        if str(item.get("type", "")).startswith("cable.") and (attrs.get("route_policy") or str(attrs.get("source_kind", "")).endswith("_inferred")):
            source_identity = (
                attrs.get("source_device_id") or attrs.get("source_fixture_id") or item.get("source_entity_id"),
                attrs.get("target_device_id") or attrs.get("target_label"),
                attrs.get("media"),
            )
        return (item.get("type"), item.get("original_layer") or item.get("layer"), attrs.get("level"), source_identity, geometry.get("type"), coords)

    @staticmethod
    def _match_rule(value: str, rules: dict[str, Any], source: str) -> dict[str, Any] | None:
        if not value:
            return None
        normalized = value.lower()
        best: dict[str, Any] | None = None
        for semantic_type, config in rules.items():
            for keyword in config.get("keywords", []):
                keyword_text = str(keyword)
                if not RuleEngine._keyword_matches(value, normalized, keyword_text):
                    continue
                if True:
                    candidate = {
                        "type": semantic_type,
                        "confidence": float(config.get("confidence", 0.75)),
                        "source": source,
                        "matched": keyword_text,
                    }
                    if best is None or candidate["confidence"] > best["confidence"]:
                        best = candidate
        return best

    @staticmethod
    def _keyword_matches(original: str, normalized: str, keyword: str) -> bool:
        keyword_normalized = keyword.lower()
        if not (keyword.isascii() and keyword.replace("_", "").isalnum() and len(keyword) <= 3):
            return keyword_normalized in normalized
        token = []
        tokens: list[str] = []
        for char in original:
            if char.isascii() and (char.isalnum() or char == "_"):
                token.append(char.lower())
            else:
                if token:
                    tokens.append("".join(token))
                    token = []
        if token:
            tokens.append("".join(token))
        return keyword_normalized in tokens

    @staticmethod
    def _label_prefix(semantic_type: str) -> str:
        if semantic_type == "network.ap":
            return "AP"
        if semantic_type == "network.cabinet":
            return "CAB"
        if semantic_type == "network.switch":
            return "SW"
        if semantic_type.startswith("security.camera"):
            return "C"
        return "DEV"

    def _device(self, entity: dict[str, Any], classification: dict[str, Any], label_counts: defaultdict[str, int]) -> dict[str, Any]:
        semantic_type = classification["type"]
        prefix = self._label_prefix(semantic_type)
        label_counts[prefix] += 1
        label = entity.get("attributes", {}).get("tag") or entity.get("attributes", {}).get("编号") or f"{prefix}-{label_counts[prefix]:03d}"
        geometry = entity["geometry"]
        return {
            "id": f"dev_{entity['source_entity_id']}",
            "type": semantic_type,
            "label": label,
            "source_entity_id": entity["source_entity_id"],
            "original_layer": entity.get("layer"),
            "original_block_name": entity.get("block_name"),
            "confidence": classification["confidence"],
            "review_needed": classification["confidence"] < 0.75,
            "geometry": geometry,
            "orientation": {"angle_deg": float(entity.get("rotation", 0.0) or 0.0)},
            "coverage": self._coverage_for(semantic_type),
            "attributes": {
                **entity.get("attributes", {}),
                "matched_rule": classification.get("matched"),
                "matched_source": classification.get("source"),
            },
        }

    @staticmethod
    def _adjust_ap_coverage_from_layout(devices: list[dict[str, Any]]) -> None:
        aps = [device for device in devices if device.get("type") == "network.ap" and device.get("geometry", {}).get("position")]
        if not aps:
            return

        for device in aps:
            attrs = device.setdefault("attributes", {})
            source = attrs.get("coverage_radius_source") or attrs.get("coverage_radius_source_kind")
            try:
                radius_mm = float(attrs.get("coverage_radius_source_radius_mm") or 0.0)
            except (TypeError, ValueError):
                radius_mm = 0.0
            if source in {"cad_circle", "cad_block_coverage_circle"} or radius_mm > 0.0:
                continue
            current = float((device.get("coverage") or {}).get("radius_m") or 0.0)
            radius = RuleEngine._layout_ap_radius(device, aps)
            coverage = {**(device.get("coverage") or {})}
            coverage["radius_m"] = radius
            device["coverage"] = coverage
            attrs["coverage_radius_source"] = "layout_ap_spacing"
            if current > 0.0:
                attrs["coverage_radius_previous_m"] = round(current, 3)

    @staticmethod
    def _layout_ap_radius(device: dict[str, Any], aps: list[dict[str, Any]]) -> float:
        peers = [peer for peer in aps if peer is not device and RuleEngine._same_ap_coverage_group(device, peer)]
        if not peers:
            peers = [peer for peer in aps if peer is not device]
        distances = sorted(
            distance
            for distance in (RuleEngine._device_distance_m(device, peer) for peer in peers)
            if distance > 1.5
        )
        limits = AP_LAYOUT_RADIUS_LIMITS_M["office" if device.get("attributes", {}).get("zone") == "office" else "warehouse"]
        raw_radius = distances[0] * AP_LAYOUT_SPACING_FACTOR if distances else limits["fallback"]
        return round(max(limits["min"], min(raw_radius, limits["max"])), 1)

    @staticmethod
    def _same_ap_coverage_group(left: dict[str, Any], right: dict[str, Any]) -> bool:
        left_attrs = left.get("attributes") or {}
        right_attrs = right.get("attributes") or {}
        left_zone = left_attrs.get("zone") or "warehouse"
        right_zone = right_attrs.get("zone") or "warehouse"
        left_floor = float(left_attrs.get("floor_elevation_m") or 0.0)
        right_floor = float(right_attrs.get("floor_elevation_m") or 0.0)
        return left_zone == right_zone and abs(left_floor - right_floor) < 0.2

    @staticmethod
    def _device_distance_m(left: dict[str, Any], right: dict[str, Any]) -> float:
        left_pos = left.get("geometry", {}).get("position") or {}
        right_pos = right.get("geometry", {}).get("position") or {}
        dx = float(left_pos.get("x", 0.0)) - float(right_pos.get("x", 0.0))
        dy = float(left_pos.get("y", 0.0)) - float(right_pos.get("y", 0.0))
        return (dx * dx + dy * dy) ** 0.5 / 1000.0

    @staticmethod
    def _coverage_for(semantic_type: str) -> dict[str, float]:
        if semantic_type == "network.ap":
            return {"radius_m": AP_LAYOUT_RADIUS_LIMITS_M["warehouse"]["fallback"]}
        if semantic_type == "security.camera.fisheye":
            return {"radius_m": 10.0}          # 鱼眼覆盖 10m 半径
        if semantic_type == "security.camera.dome":
            return {"length_m": 15.0, "angle_deg": 90.0}
        if semantic_type == "security.camera.rear":
            return {"length_m": 8.0, "angle_deg": 36.0}
        if semantic_type.startswith("security.camera"):
            return {"length_m": 15.0, "angle_deg": 45.0}
        return {}

    def _native_cable_classification(self, entity: dict[str, Any]) -> dict[str, Any] | None:
        if entity.get("source_kind") == "insert_virtual_entity":
            return None
        if entity.get("entity_type") not in NATIVE_CABLE_ENTITY_TYPES:
            return None
        geometry = entity.get("geometry") or {}
        if geometry.get("type") not in NATIVE_CABLE_GEOMETRY_TYPES:
            return None
        points = geometry.get("points") or []
        length_mm = float(entity.get("native_length_mm") or line_length(points))
        layer = str(entity.get("layer") or "")
        small_scale_fallback = self._small_scale_route_fallback(layer, length_mm)
        if small_scale_fallback:
            return small_scale_fallback
        if length_mm < NATIVE_CABLE_MIN_LENGTH_MM:
            return None
        if self._is_device_cable_layer(layer):
            return None

        direct_match = self._match_rule(layer, self.rules.get("native_cable_layer_rules", {}), "native_layer")
        if direct_match:
            return direct_match

        fallback = self._native_cable_fallback_match(layer)
        if fallback:
            return fallback
        return None

    @staticmethod
    def _small_scale_route_fallback(layer: str, length_mm: float) -> dict[str, Any] | None:
        config = SMALL_SCALE_ROUTE_LAYER_FALLBACKS.get(layer)
        if not config or length_mm < SMALL_SCALE_ROUTE_MIN_LENGTH_MM:
            return None
        semantic_type, confidence = config
        return {
            "type": semantic_type,
            "confidence": float(confidence),
            "source": "small_scale_native_layer_fallback",
            "matched": layer,
        }

    def _native_cable_fallback_match(self, layer: str) -> dict[str, Any] | None:
        normalized = layer.strip().lower()
        for config in self.rules.get("native_cable_fallback_layers", []):
            fallback_layer = str(config.get("layer") or "").strip()
            if not fallback_layer or fallback_layer.lower() != normalized:
                continue
            if not bool(config.get("auto_keep", False)):
                return None
            return {
                "type": str(config.get("type") or "cable.unknown"),
                "confidence": float(config.get("confidence", 0.35)),
                "source": "native_layer_fallback",
                "matched": fallback_layer,
            }
        return None

    @staticmethod
    def _is_device_cable_layer(layer: str) -> bool:
        if not layer:
            return False
        upper = layer.upper()
        return any(keyword.upper() in upper for keyword in DEVICE_CABLE_LAYER_KEYWORDS)

    def _filter_cable_candidates(
        self, candidates: list[dict[str, Any]]
    ) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
        kept: list[dict[str, Any]] = []
        filtered_out: list[dict[str, Any]] = []
        for candidate in candidates:
            reason = self._cable_candidate_filter_reason(candidate)
            if reason:
                filtered_out.append(self._filtered_cable_candidate(candidate, reason))
                continue
            kept.append(candidate)
        return kept, filtered_out

    def _cable_candidate_filter_reason(self, candidate: dict[str, Any]) -> str | None:
        attrs = candidate.get("attributes") or {}
        parent_block = str(attrs.get("parent_block_name") or candidate.get("parent_block_name") or "")
        if parent_block:
            block_reason = self._device_parent_block_reason(parent_block)
            if block_reason:
                return block_reason

        cad_role = str(attrs.get("cad_role") or candidate.get("cad_role") or "")
        if cad_role in DEVICE_CABLE_CAD_ROLES:
            return f"cad_role_{cad_role}"

        original_layer = str(candidate.get("original_layer") or "")
        parent_layer = str(attrs.get("parent_layer") or "")
        if self._is_device_cable_layer(original_layer) or self._is_device_cable_layer(parent_layer):
            return "device_layer"
        return None

    @staticmethod
    def _device_parent_block_reason(block_name: str) -> str | None:
        if not block_name:
            return None
        upper = block_name.upper()
        if "鱼眼" in block_name or "FISHEYE" in upper:
            return "fisheye_symbol_block"
        if "半球" in block_name or "DOME" in upper:
            return "dome_symbol_block"
        if "AP" in upper or "无线" in block_name:
            return "ap_symbol_block"
        if any(keyword in block_name for keyword in ("枪", "摄像", "摄像头")) or "CAMERA" in upper or "BULLET" in upper:
            return "camera_symbol_block"
        if any(keyword.upper() in upper for keyword in DEVICE_CABLE_PARENT_KEYWORDS):
            return "device_symbol_block"
        return None

    @staticmethod
    def _filtered_cable_candidate(candidate: dict[str, Any], reason: str) -> dict[str, Any]:
        attrs = candidate.get("attributes") or {}
        return {
            "id": candidate.get("id"),
            "source_entity_id": candidate.get("source_entity_id"),
            "type": candidate.get("type"),
            "original_layer": candidate.get("original_layer"),
            "parent_block": attrs.get("parent_block_name"),
            "parent_layer": attrs.get("parent_layer"),
            "cad_role": attrs.get("cad_role"),
            "source_kind": attrs.get("source_kind"),
            "length_mm": candidate.get("length_mm"),
            "reason": reason,
        }

    def _annotate_cable_native_matches(
        self, cables: list[dict[str, Any]], candidates: list[dict[str, Any]]
    ) -> None:
        native_candidates = [
            candidate
            for candidate in candidates
            if candidate.get("attributes", {}).get("source_kind") == "cad_native_line"
        ]
        used_candidate_ids: set[str] = set()
        for cable in cables:
            cable["route_source"] = "inferred_via_devices"
            cable["cad_native_match_id"] = None
            match = self._best_native_cable_match(cable, native_candidates, used_candidate_ids)
            if not match:
                continue
            cable["route_source"] = "cad_polyline"
            cable["cad_native_match_id"] = match.get("id")
            used_candidate_ids.add(str(match.get("id")))
            match["pending_promotion"] = False

    def _best_native_cable_match(
        self,
        cable: dict[str, Any],
        candidates: list[dict[str, Any]],
        used_candidate_ids: set[str],
    ) -> dict[str, Any] | None:
        cable_points = cable.get("geometry", {}).get("points") or []
        if len(cable_points) < 2:
            return None
        cable_length = line_length(cable_points)
        best: tuple[float, dict[str, Any]] | None = None
        for candidate in candidates:
            candidate_id = str(candidate.get("id") or "")
            if candidate_id in used_candidate_ids:
                continue
            candidate_points = candidate.get("geometry", {}).get("points") or []
            if len(candidate_points) < 2:
                continue
            candidate_length = line_length(candidate_points)
            threshold = max(2_000.0, min(cable_length, candidate_length) * 0.15)
            endpoint_distance = self._route_endpoint_distance(cable_points, candidate_points)
            if endpoint_distance > threshold:
                continue
            shape_distance = self._route_hausdorff_distance(cable_points, candidate_points)
            if shape_distance > threshold:
                continue
            score = endpoint_distance + shape_distance
            if best is None or score < best[0]:
                best = (score, candidate)
        return best[1] if best else None

    @staticmethod
    def _route_endpoint_distance(left: list[dict[str, float]], right: list[dict[str, float]]) -> float:
        forward = max(RuleEngine._point_distance(left[0], right[0]), RuleEngine._point_distance(left[-1], right[-1]))
        reverse = max(RuleEngine._point_distance(left[0], right[-1]), RuleEngine._point_distance(left[-1], right[0]))
        return min(forward, reverse)

    @staticmethod
    def _route_hausdorff_distance(left: list[dict[str, float]], right: list[dict[str, float]]) -> float:
        return max(
            RuleEngine._directed_route_distance(left, right),
            RuleEngine._directed_route_distance(right, left),
        )

    @staticmethod
    def _directed_route_distance(points: list[dict[str, float]], reference: list[dict[str, float]]) -> float:
        if len(reference) < 2:
            return float("inf")
        return max(RuleEngine._point_to_polyline_distance(point, reference) for point in points)

    @staticmethod
    def _point_to_polyline_distance(point: dict[str, float], polyline: list[dict[str, float]]) -> float:
        distances = [
            RuleEngine._point_to_segment_distance(point, start, end)
            for start, end in zip(polyline, polyline[1:])
        ]
        return min(distances) if distances else float("inf")

    @staticmethod
    def _point_to_segment_distance(
        point: dict[str, float],
        start: dict[str, float],
        end: dict[str, float],
    ) -> float:
        dx = end["x"] - start["x"]
        dy = end["y"] - start["y"]
        length_sq = dx * dx + dy * dy
        if length_sq <= 0:
            return RuleEngine._point_distance(point, start)
        t = ((point["x"] - start["x"]) * dx + (point["y"] - start["y"]) * dy) / length_sq
        t = max(0.0, min(1.0, t))
        projection = {"x": start["x"] + t * dx, "y": start["y"] + t * dy}
        return RuleEngine._point_distance(point, projection)

    @staticmethod
    def _point_distance(left: dict[str, float], right: dict[str, float]) -> float:
        dx = float(left.get("x", 0.0)) - float(right.get("x", 0.0))
        dy = float(left.get("y", 0.0)) - float(right.get("y", 0.0))
        return (dx * dx + dy * dy) ** 0.5

    def _virtual_cable_candidates(self, entities: list[dict[str, Any]]) -> list[dict[str, Any]]:
        candidates: list[dict[str, Any]] = []
        seen: set[tuple[Any, ...]] = set()
        for parent in entities:
            parent_id = str(parent.get("source_entity_id") or "")
            for index, shape in enumerate(parent.get("cad_virtual_shapes") or []):
                geometry = shape.get("geometry") or {}
                if geometry.get("type") not in {"LineString", "Arc", "Polygon"}:
                    continue
                shape_entity = {
                    **shape,
                    "source_entity_id": f"{parent_id}:v{index}",
                    "parent_source_entity_id": parent_id,
                    "parent_block_name": parent.get("block_name"),
                    "parent_layer": parent.get("layer"),
                    "block_name": parent.get("block_name"),
                }
                classification = self.classify(shape_entity)
                if not classification or not str(classification.get("type", "")).startswith("cable."):
                    continue
                if classification.get("type") == "cable.unknown" and not self._looks_like_route_candidate(shape_entity):
                    continue
                points = geometry.get("points") or []
                key = (
                    shape_entity.get("layer"),
                    geometry.get("type"),
                    tuple((round(float(point.get("x", 0.0)), 1), round(float(point.get("y", 0.0)), 1)) for point in points[:4]),
                )
                if key in seen:
                    continue
                seen.add(key)
                candidates.append(self._cable(shape_entity, classification, candidate=True))
        return candidates[:2000]

    @staticmethod
    def _looks_like_route_candidate(entity: dict[str, Any]) -> bool:
        geometry = entity.get("geometry") or {}
        points = geometry.get("points") or []
        if geometry.get("type") == "Arc":
            return False
        return line_length(points) >= 3000.0

    @staticmethod
    def _cable_candidate_summary(
        candidates: list[dict[str, Any]], filtered_out: list[dict[str, Any]]
    ) -> dict[str, Any]:
        by_type = Counter(str(item.get("type", "unknown")) for item in candidates)
        by_layer = Counter(str(item.get("original_layer") or "unknown") for item in candidates)
        by_source = Counter(str(item.get("attributes", {}).get("source_kind") or "unknown") for item in candidates)
        by_role = Counter(str(item.get("type") or "unknown") for item in candidates)
        filtered_by_layer = Counter(str(item.get("original_layer") or "unknown") for item in filtered_out)
        filtered_by_source = Counter(str(item.get("source_kind") or "unknown") for item in filtered_out)
        filtered_by_parent = Counter(
            str(item.get("parent_block") or "none")
            for item in filtered_out
            if item.get("parent_block")
        )
        by_parent = Counter(
            str(item.get("attributes", {}).get("parent_block_name") or "none")
            for item in candidates
            if item.get("attributes", {}).get("parent_block_name")
        )
        filtered_reasons = Counter(str(item.get("reason") or "unknown") for item in filtered_out)
        by_source.setdefault("cad_native_line", 0)
        by_source.setdefault("cad_insert_virtual_candidate", 0)
        return {
            "total": len(candidates) + len(filtered_out),
            "kept": len(candidates),
            "filtered_out": len(filtered_out),
            "exported_limit": 500,
            "truncated": len(candidates) > 500,
            "filtered_exported_limit": 1000,
            "filtered_truncated": len(filtered_out) > 1000,
            "by_role": dict(sorted(by_role.items())),
            "by_type": dict(sorted(by_type.items())),
            "by_layer": dict(by_layer.most_common(20)),
            "by_source_kind": dict(sorted(by_source.items())),
            "by_parent_block": dict(by_parent.most_common(20)),
            "filtered_by_layer": dict(filtered_by_layer.most_common(20)),
            "filtered_by_source_kind": dict(sorted(filtered_by_source.items())),
            "filtered_by_parent_block": dict(filtered_by_parent.most_common(20)),
            "filtered_out_reasons": dict(filtered_reasons.most_common(20)),
        }

    @staticmethod
    def _cable(
        entity: dict[str, Any],
        classification: dict[str, Any],
        *,
        candidate: bool = False,
        source_kind_override: str | None = None,
        cad_role_override: str | None = None,
    ) -> dict[str, Any]:
        points = entity["geometry"].get("points", [])
        source_kind = "cad_layer_candidate" if candidate else "cad_layer_direct"
        if entity.get("source_kind") == "insert_virtual_entity":
            source_kind = "cad_insert_virtual_candidate" if candidate else "cad_insert_virtual_direct"
        if source_kind_override:
            source_kind = source_kind_override
        cad_role = cad_role_override or entity.get("cad_role")
        attributes = {
            "source_kind": source_kind,
            "matched_rule": classification.get("matched"),
            "matched_source": classification.get("source"),
            "classification_source": classification.get("source"),
            "matched_keyword": classification.get("matched"),
            "cad_entity_type": entity.get("entity_type"),
            "cad_source_kind": entity.get("source_kind"),
            "cad_role": cad_role,
            "layer_color": entity.get("layer_color"),
            "effective_color": entity.get("effective_color"),
            "parent_source_entity_id": entity.get("parent_source_entity_id"),
            "parent_block_name": entity.get("parent_block_name"),
            "parent_layer": entity.get("parent_layer"),
        }
        attributes = {key: value for key, value in attributes.items() if value is not None}
        review_needed = candidate or classification["confidence"] < 0.75 or classification["type"] == "cable.unknown"
        item = {
            "id": f"cable_{entity['source_entity_id']}",
            "type": classification["type"],
            "source_entity_id": entity["source_entity_id"],
            "original_layer": entity.get("layer"),
            "confidence": classification["confidence"],
            "review_needed": review_needed,
            "geometry": entity["geometry"],
            "length_mm": line_length(points),
            "attributes": attributes,
        }
        if candidate:
            item["pending_promotion"] = source_kind == "cad_native_line"
            item["length_m"] = round(float(item["length_mm"]) / 1000.0, 3)
            item["node_count"] = int(entity.get("node_count") or len(points))
            if points:
                item["start"] = points[0]
                item["end"] = points[-1]
        return item
