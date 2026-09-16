"""DXF 单位处理：把 `$INSUNITS` 正确映射为毫米，并支持显式单位选择。

要点：
- 完整的 DXF `$INSUNITS` 取值表（含英尺/英寸），不再只覆盖少数几种。
- 单位码 0（无单位）与未知码不再静默当作毫米：解析结果会带上 `unit_unspecified=True`
  与 `unit_resolution` 说明，调用方可以据此提示用户显式选择。
- 允许显式覆盖：`unit="ft"` 或 `unit_scale_to_mm=304.8`。
"""

from __future__ import annotations

from typing import Any

MM_PER_UNIT: dict[int, float] = {
    1: 25.4,  # Inches
    2: 304.8,  # Feet
    3: 1609344.0,  # Miles
    4: 1.0,  # Millimeters
    5: 10.0,  # Centimeters
    6: 1000.0,  # Meters
    7: 1000000.0,  # Kilometers
    8: 2.54e-5,  # Microinches
    9: 2.54e-2,  # Mils
    10: 914.4,  # Yards
    11: 1.0e-7,  # Angstroms
    12: 1.0e-6,  # Nanometers
    13: 1.0e-3,  # Microns
    14: 100.0,  # Decimeters
    15: 10000.0,  # Decameters
    16: 100000.0,  # Hectometers
    17: 1.0e12,  # Gigameters
    18: 1.495978707e14,  # Astronomical units
    19: 9.4607304725808e18,  # Light years
    20: 3.0856775814913673e19,  # Parsecs
    21: 304.8006096012192,  # US Survey Feet
    22: 25.400050800101603,  # US Survey Inch
    23: 914.4018288036576,  # US Survey Yard
    24: 1609347.2186944362,  # US Survey Mile
}

UNIT_NAME_BY_CODE: dict[int, str] = {
    1: "in",
    2: "ft",
    3: "mi",
    4: "mm",
    5: "cm",
    6: "m",
    7: "km",
    8: "microinch",
    9: "mil",
    10: "yd",
    11: "angstrom",
    12: "nm",
    13: "um",
    14: "dm",
    15: "dam",
    16: "hm",
    17: "gm",
    18: "au",
    19: "ly",
    20: "pc",
    21: "usft",
    22: "usin",
    23: "usyd",
    24: "usmi",
}

UNIT_CODE_BY_NAME: dict[str, int] = {name: code for code, name in UNIT_NAME_BY_CODE.items()}
UNIT_CODE_BY_NAME.update(
    {
        "millimeter": 4,
        "millimeters": 4,
        "毫米": 4,
        "centimeter": 5,
        "centimeters": 5,
        "厘米": 5,
        "meter": 6,
        "meters": 6,
        "metre": 6,
        "metres": 6,
        "米": 6,
        "inch": 1,
        "inches": 1,
        "英寸": 1,
        "foot": 2,
        "feet": 2,
        "英尺": 2,
        "unitless": 0,
        "none": 0,
        "unspecified": 0,
        "无单位": 0,
    }
)

#: 无法解释为单位码时的兜底（保持与历史行为一致：按毫米处理，但会标记为待确认）。
DEFAULT_SCALE_TO_MM = 1.0

_UNSET = object()


def scale_for_unit_code(code: Any, *, default: float = DEFAULT_SCALE_TO_MM) -> float:
    """把 DXF 单位码换成毫米比例；未知码返回 default。"""
    try:
        numeric = int(code)
    except (TypeError, ValueError):
        return default
    return MM_PER_UNIT.get(numeric, default)


def describe_unit_code(code: Any) -> dict[str, Any]:
    """描述单位码：比例、名称、是否可确定。"""
    try:
        numeric = int(code)
    except (TypeError, ValueError):
        numeric = None
    known = numeric in MM_PER_UNIT if numeric is not None else False
    return {
        "unit_code": numeric,
        "unit_name": UNIT_NAME_BY_CODE.get(numeric) if numeric is not None else None,
        "unit_scale_to_mm": MM_PER_UNIT.get(numeric, DEFAULT_SCALE_TO_MM) if numeric is not None else DEFAULT_SCALE_TO_MM,
        "unit_known": known,
        "unit_unspecified": (numeric == 0) or not known,
    }


def resolve_unit(
    raw_code: Any,
    *,
    unit: str | None = None,
    unit_scale_to_mm: float | None = None,
) -> dict[str, Any]:
    """综合 `$INSUNITS`、显式单位名与显式比例，得出最终换算信息。

    返回字段：
    - `unit_scale_to_mm`：最终使用的比例。
    - `unit_code` / `unit_name`：最终采用（或原始）单位。
    - `unit_source`：`override_scale` / `override_name` / `dxf_header` / `dxf_header_unknown` / `default`。
    - `unit_unspecified`：是否无法从图纸自身确定单位（需要用户确认）。
    - `header_unit_*`：图纸头声明的原始信息，便于审计与前端提示。
    """
    header = describe_unit_code(raw_code)
    result: dict[str, Any] = {
        "unit_scale_to_mm": header["unit_scale_to_mm"],
        "unit_code": header["unit_code"],
        "unit_name": header["unit_name"],
        "unit_known": header["unit_known"],
        "unit_unspecified": header["unit_unspecified"],
        "unit_source": "dxf_header" if header["unit_known"] else "dxf_header_unknown",
        "header_unit_code": header["unit_code"],
        "header_unit_name": header["unit_name"],
        "header_unit_scale_to_mm": header["unit_scale_to_mm"],
        "explicit_unit": False,
    }

    if unit_scale_to_mm is not None:
        scale = _validate_scale(unit_scale_to_mm)
        result.update(
            {
                "unit_scale_to_mm": scale,
                "unit_code": None,
                "unit_name": None,
                "unit_unspecified": False,
                "unit_source": "override_scale",
                "explicit_unit": True,
            }
        )
        return result

    if unit:
        key = str(unit).strip().lower()
        if key and key not in {"auto", "header", "dxf"}:
            code = UNIT_CODE_BY_NAME.get(key)
            if code is None and not _looks_numeric(key):
                raise ValueError(f"未知单位: {unit}（可用: {', '.join(sorted(set(UNIT_CODE_BY_NAME)))}）")
            if code is None:
                scale = _validate_scale(float(key))
                result.update(
                    {
                        "unit_scale_to_mm": scale,
                        "unit_code": None,
                        "unit_name": None,
                        "unit_unspecified": False,
                        "unit_source": "override_scale",
                        "explicit_unit": True,
                    }
                )
                return result
            if code == 0:
                # 显式选择"无单位"= 明确按毫米 1:1 处理，但仍标记来源为显式。
                result.update(
                    {
                        "unit_scale_to_mm": DEFAULT_SCALE_TO_MM,
                        "unit_code": 0,
                        "unit_name": UNIT_NAME_BY_CODE.get(0, "unitless"),
                        "unit_unspecified": False,
                        "unit_source": "override_name",
                        "explicit_unit": True,
                    }
                )
                return result
            result.update(
                {
                    "unit_scale_to_mm": scale_for_unit_code(code),
                    "unit_code": code,
                    "unit_name": UNIT_NAME_BY_CODE.get(code, key),
                    "unit_known": True,
                    "unit_unspecified": False,
                    "unit_source": "override_name",
                    "explicit_unit": True,
                }
            )
            return result

    return result


def _validate_scale(value: Any) -> float:
    try:
        scale = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"unit_scale_to_mm 必须是数字: {value!r}") from exc
    if not (scale > 0) or scale != scale or scale in {float("inf"), float("-inf")}:
        raise ValueError(f"unit_scale_to_mm 必须是正的有限数字: {value!r}")
    return scale


def _looks_numeric(value: str) -> bool:
    try:
        float(value)
        return True
    except ValueError:
        return False


def normalize_unit_selection(unit: str | None, unit_scale_to_mm: float | None) -> dict[str, Any]:
    """API 层入口：把请求参数收敛为 DxfReader 的单位选项。"""
    resolved = resolve_unit(None, unit=unit, unit_scale_to_mm=unit_scale_to_mm)
    return {
        "unit": resolved.get("unit_name"),
        "unit_scale_to_mm": resolved["unit_scale_to_mm"],
        "unit_source": resolved["unit_source"],
    }


def available_units() -> list[dict[str, Any]]:
    """给前端/API 的单位下拉列表。"""
    common = ["mm", "cm", "m", "in", "ft", "usft"]
    return [
        {
            "name": name,
            "unit_code": UNIT_CODE_BY_NAME[name],
            "scale_to_mm": scale_for_unit_code(UNIT_CODE_BY_NAME[name]),
        }
        for name in common
    ]


__all__ = [
    "DEFAULT_SCALE_TO_MM",
    "MM_PER_UNIT",
    "UNIT_CODE_BY_NAME",
    "UNIT_NAME_BY_CODE",
    "available_units",
    "describe_unit_code",
    "normalize_unit_selection",
    "resolve_unit",
    "scale_for_unit_code",
]
