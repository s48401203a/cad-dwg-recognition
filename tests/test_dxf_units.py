"""DXF 单位换算测试（数值断言）。

覆盖本轮「单位正确性」修复：
- `$INSUNITS=2`（英尺）的 10 单位直线必须是 3048.0 mm，不再被当成毫米。
- 同一物理形状用 in/ft/mm/cm/m/usft 表达，归一化后毫米坐标必须在 1e-9 相对误差内一致。
- `$INSUNITS=0`（无单位）与未知码（99）必须被标记 `unit_unspecified=True` 并给出警告，
  但解析本身不能崩。
- 显式覆盖 `unit="ft"` / `unit_scale_to_mm=304.8` 必须生效，并如实报告 `unit_source`。

所有夹具都是代码生成的临时文件（tmp_path），不读取任何真实客户图纸。
"""

from __future__ import annotations

import math
from pathlib import Path

import pytest

from parser.dxf_reader import DxfReader
from parser.dxf_units import (
    DEFAULT_SCALE_TO_MM,
    MM_PER_UNIT,
    UNIT_CODE_BY_NAME,
    UNIT_NAME_BY_CODE,
    available_units,
    describe_unit_code,
    normalize_unit_selection,
    resolve_unit,
    scale_for_unit_code,
)
from tests.synthetic import build_unit_scale_line_fixture, build_units_fixture, write_dxf

# 本任务要求的常见单位码 -> 每单位毫米数
EXPECTED_SCALE = {
    1: 25.4,  # inch
    2: 304.8,  # foot
    4: 1.0,  # millimetre
    5: 10.0,  # centimetre
    6: 1000.0,  # metre
    21: 304.8006096012192,  # US survey foot
}


def _only_line(result: dict) -> dict:
    lines = [entity for entity in result["entities"] if entity["entity_type"] == "LINE"]
    assert len(lines) == 1, f"期望恰好 1 条 LINE，实际 {[e['entity_type'] for e in result['entities']]}"
    return lines[0]


def _line_length_mm(entity: dict) -> float:
    points = entity["geometry"]["points"]
    return math.hypot(points[1]["x"] - points[0]["x"], points[1]["y"] - points[0]["y"])


def _scaled_line_fixture(units: int, *, length: float):
    """构造一条给定「图纸单位」长度的直线（复用 synthetic 的单位夹具，只改长度）。"""
    if length == 1.0:
        return build_unit_scale_line_fixture(units=units)
    doc = build_unit_scale_line_fixture(units=units)
    doc.modelspace().delete_all_entities()
    doc.modelspace().add_line((0, 0), (length, 0), dxfattribs={"layer": "桥架"})
    return doc


# --------------------------------------------------------------- 单位码基础表


@pytest.mark.parametrize("code,scale", sorted(EXPECTED_SCALE.items()))
def test_scale_for_unit_code_matches_mm_per_unit(code: int, scale: float):
    """`scale_for_unit_code` 必须给出该单位码的毫米比例。"""
    assert scale_for_unit_code(code) == pytest.approx(scale, rel=0, abs=0)
    assert MM_PER_UNIT[code] == pytest.approx(scale, rel=0, abs=0)


def test_foot_is_exactly_twelve_inches():
    """1 ft 必须等于 12 in（304.8 mm）。

    注意：这是浮点乘法的一致性，不是位相等 —— 12 × 25.4 = 304.79999999999995，
    与表中字面量 304.8 相差 1 个 ulp（相对误差 ~1.6e-16）。因此这里用 1e-15 相对容差，
    而不是 `rel=0`；该差异属于 IEEE754 表示误差，不是实现缺陷（见交付说明）。
    """
    assert MM_PER_UNIT[2] == pytest.approx(12.0 * MM_PER_UNIT[1], rel=1e-15)
    assert MM_PER_UNIT[2] == 304.8
    assert abs(MM_PER_UNIT[2] - 12.0 * MM_PER_UNIT[1]) < 1e-13


def test_unknown_and_unitless_codes_are_flagged_not_silently_mm():
    """码 0 与未知码（99）必须被标记为「无法确定单位」，默认比例仅作兜底。"""
    for code in (0, 99, 12345, None, "not-a-number"):
        described = describe_unit_code(code)
        assert described["unit_unspecified"] is True, f"单位码 {code!r} 必须被标记为未声明"
        assert described["unit_known"] is False
        assert described["unit_scale_to_mm"] == DEFAULT_SCALE_TO_MM

    # 已知码不能被误标
    for code in EXPECTED_SCALE:
        described = describe_unit_code(code)
        assert described["unit_unspecified"] is False
        assert described["unit_known"] is True


# --------------------------------------------------------------- 核心：10 单位直线


def test_ten_unit_line_in_feet_is_3048_mm(tmp_path: Path):
    """标题修复点：10 单位 × $INSUNITS=2（英尺）= 3048.0 mm（精确相等）。"""
    path = write_dxf(tmp_path / "feet.dxf", build_units_fixture(2))
    result = DxfReader.read(path)

    assert result["unit_code"] == 2
    assert result["unit_name"] == "ft"
    assert result["unit_scale_to_mm"] == 304.8
    assert result["unit_source"] == "dxf_header"
    assert result["unit_unspecified"] is False
    assert result["unit_known"] is True
    assert result["unit_explicit"] is False
    assert result["header_unit_code"] == 2
    assert "unit_warning" not in result

    line = _only_line(result)
    assert line["native_length_mm"] == 3048.0
    assert line["curve_length_mm"] == 3048.0
    assert line["geometry"]["points"][1]["x"] == 3048.0
    assert _line_length_mm(line) == 3048.0


@pytest.mark.parametrize("code,scale", sorted(EXPECTED_SCALE.items()))
def test_one_unit_line_length_matches_unit_scale(tmp_path: Path, code: int, scale: float):
    """1 单位直线在每个单位下都必须等于该单位的毫米比例（1 in = 1/12 ft 一致性）。"""
    path = write_dxf(tmp_path / f"unit_{code}.dxf", build_units_fixture(code))
    result = DxfReader.read(path)

    assert result["unit_code"] == code
    assert result["unit_scale_to_mm"] == pytest.approx(scale, rel=0, abs=0)
    assert result["unit_unspecified"] is False

    # build_units_fixture 是 10 单位长
    line = _only_line(result)
    assert line["native_length_mm"] == pytest.approx(10.0 * scale, rel=1e-12)


def test_twelve_inches_equals_one_foot_across_fixtures(tmp_path: Path):
    """12 个「英寸单位」的直线长度必须等于 1 个「英尺单位」的直线长度。"""
    inches = DxfReader.read(write_dxf(tmp_path / "in.dxf", build_units_fixture(1)))
    feet = DxfReader.read(write_dxf(tmp_path / "ft.dxf", build_units_fixture(2)))
    assert inches["unit_scale_to_mm"] == pytest.approx(feet["unit_scale_to_mm"] / 12.0, rel=1e-15)

    # 图纸里画 1 单位（英寸）与画 1 单位（英尺）的长度比必须是 12:1
    one_inch = DxfReader.read(write_dxf(tmp_path / "one_inch.dxf", _scaled_line_fixture(1, length=1.0)))
    one_foot = DxfReader.read(write_dxf(tmp_path / "one_foot.dxf", _scaled_line_fixture(2, length=1.0)))

    assert _only_line(one_inch)["native_length_mm"] == pytest.approx(25.4, rel=1e-12)
    assert _only_line(one_foot)["native_length_mm"] == pytest.approx(304.8, rel=1e-12)
    assert 12.0 * _only_line(one_inch)["native_length_mm"] == pytest.approx(
        _only_line(one_foot)["native_length_mm"], rel=1e-15
    )

    # 反过来：英尺图纸里画 12 个单位，等于 12 ft = 3657.6 mm
    twelve_feet_units = DxfReader.read(write_dxf(tmp_path / "twelve_feet.dxf", _scaled_line_fixture(2, length=12.0)))
    assert _only_line(twelve_feet_units)["native_length_mm"] == pytest.approx(3657.6, rel=1e-12)


# --------------------------------------------------------------- 跨单位往返一致


@pytest.mark.parametrize("code", sorted(EXPECTED_SCALE))
def test_round_trip_same_physical_geometry_in_every_unit(tmp_path: Path, code: int):
    """同一物理长度（304.8 mm）用不同单位表达，归一化到毫米后必须一致（rtol 1e-9）。

    做法：在每个单位里画「304.8 / 每单位毫米数」个单位长度，读回来应当是 304.8 mm。
    """
    scale = EXPECTED_SCALE[code]
    length_in_drawing_units = 304.8 / scale
    path = write_dxf(tmp_path / f"round_{code}.dxf", _scaled_line_fixture(code, length=length_in_drawing_units))

    result = DxfReader.read(path)
    line = _only_line(result)

    assert line["native_length_mm"] == pytest.approx(304.8, rel=1e-9)
    assert line["geometry"]["points"][1]["x"] == pytest.approx(304.8, rel=1e-9)


def test_round_trip_mm_cm_m_in_ft_agree_within_1e_9(tmp_path: Path):
    """mm / cm / m / in / ft 五种写法的毫米坐标必须一致（相对误差 1e-9）。"""
    target_mm = 1000.0
    lengths_mm: dict[str, float] = {}
    for code in (4, 5, 6, 1, 2):
        scale = EXPECTED_SCALE[code]
        path = write_dxf(tmp_path / f"agree_{code}.dxf", _scaled_line_fixture(code, length=target_mm / scale))
        result = DxfReader.read(path)
        lengths_mm[result["unit_name"]] = _only_line(result)["native_length_mm"]

    baseline = lengths_mm["mm"]
    assert baseline == pytest.approx(target_mm, rel=1e-12)
    for name, value in lengths_mm.items():
        assert value == pytest.approx(baseline, rel=1e-9), f"{name} 与其他单位不一致: {value} vs {baseline}"


# --------------------------------------------------------------- 无单位 / 未知码


def test_unitless_header_is_flagged_and_still_parseable(tmp_path: Path):
    """`$INSUNITS=0`：标记未声明 + 给出警告 + 仍可按 1:1 解析出实体。"""
    path = write_dxf(tmp_path / "unitless.dxf", build_units_fixture(0))
    result = DxfReader.read(path)

    assert result["unit_unspecified"] is True
    assert result["unit_known"] is False
    assert result["unit_code"] == 0
    assert result["header_unit_code"] == 0
    assert result["unit_source"] == "dxf_header_unknown", "图纸头无法确定单位时必须如实标注来源"
    assert isinstance(result.get("unit_warning"), str) and result["unit_warning"].strip()
    assert "确认单位" in result["unit_warning"]
    assert result["unit_resolution"]["unit_unspecified"] is True

    # 兜底 1:1，且实体照常可读
    assert result["unit_scale_to_mm"] == DEFAULT_SCALE_TO_MM
    assert _only_line(result)["native_length_mm"] == 10.0
    assert result["total_entities"] == 1


def test_unknown_unit_code_is_flagged_without_crashing(tmp_path: Path):
    """未知码 99：不崩、标记未声明、警告里带上原始码。"""
    path = write_dxf(tmp_path / "unknown_unit.dxf", build_units_fixture(99))
    result = DxfReader.read(path)

    assert result["unit_code"] == 99
    assert result["header_unit_code"] == 99
    assert result["unit_unspecified"] is True
    assert result["unit_known"] is False
    assert result["unit_source"] == "dxf_header_unknown"
    assert "99" in result["unit_warning"]
    assert result["unit_scale_to_mm"] == DEFAULT_SCALE_TO_MM
    # 仍然读得到实体，说明只是标记而不是拒绝解析
    assert _only_line(result)["native_length_mm"] == 10.0


def test_explicit_override_clears_unspecified_flag(tmp_path: Path):
    """图纸无单位时，显式指定单位应当消掉 unspecified 标记与警告。"""
    path = write_dxf(tmp_path / "unitless2.dxf", build_units_fixture(0))
    result = DxfReader.read(path, unit="ft")

    assert result["unit_unspecified"] is False
    assert "unit_warning" not in result
    assert result["unit_explicit"] is True
    assert result["unit_source"] == "override_name"
    assert _only_line(result)["native_length_mm"] == 3048.0


# --------------------------------------------------------------- 显式覆盖


def test_override_by_name_converts_10_units_to_3048_mm(tmp_path: Path):
    """`read(path, unit="ft")`：忽略图纸头的 mm，按英尺换算。"""
    path = write_dxf(tmp_path / "override_name.dxf", build_units_fixture(4))
    result = DxfReader.read(path, unit="ft")

    assert _only_line(result)["native_length_mm"] == 3048.0
    assert result["unit_scale_to_mm"] == 304.8
    assert result["unit_source"] == "override_name"
    assert result["unit_explicit"] is True
    assert result["unit_name"] == "ft"
    assert result["unit_code"] == 2
    assert result["unit_unspecified"] is False
    # 头信息仍然保留，便于审计
    assert result["header_unit_code"] == 4


def test_override_by_scale_converts_10_units_to_3048_mm(tmp_path: Path):
    """`read(path, unit_scale_to_mm=304.8)`：直接给定比例。"""
    path = write_dxf(tmp_path / "override_scale.dxf", build_units_fixture(4))
    result = DxfReader.read(path, unit_scale_to_mm=304.8)

    assert _only_line(result)["native_length_mm"] == 3048.0
    assert result["unit_scale_to_mm"] == 304.8
    assert result["unit_source"] == "override_scale"
    assert result["unit_explicit"] is True
    # 显式比例无法反推单位名，如实置空
    assert result["unit_code"] is None
    assert result["unit_name"] is None
    assert result["unit_unspecified"] is False


def test_override_takes_precedence_over_header(tmp_path: Path):
    """同一个文件，头声明英尺但显式改成英寸，结果必须是 254 mm（10 单位）。"""
    path = write_dxf(tmp_path / "precedence.dxf", build_units_fixture(2))
    header_result = DxfReader.read(path)
    override_result = DxfReader.read(path, unit="in")

    assert _only_line(header_result)["native_length_mm"] == 3048.0
    assert _only_line(override_result)["native_length_mm"] == 254.0
    assert override_result["header_unit_code"] == 2
    assert override_result["unit_source"] == "override_name"


@pytest.mark.parametrize("index,name", list(enumerate(["ft", "foot", "feet", "英尺"])))
def test_foot_aliases_and_chinese_name_are_accepted(tmp_path: Path, index: int, name: str):
    """英文别名与中文单位名都要被接受（`UNIT_CODE_BY_NAME` 里确实有中文键）。

    这里不做 `pytest.skip`：如果某个别名消失，本用例应当**失败**（映射被破坏是真问题）。
    """
    assert name in UNIT_CODE_BY_NAME, f"{name!r} 必须存在于 UNIT_CODE_BY_NAME"
    path = write_dxf(tmp_path / f"alias_{index}.dxf", build_units_fixture(4))
    result = DxfReader.read(path, unit=name)
    assert _only_line(result)["native_length_mm"] == 3048.0
    assert result["unit_source"] == "override_name"
    assert result["unit_name"] == "ft"


def test_chinese_names_exist_and_map_to_expected_codes():
    """中文单位名到单位码的映射必须存在且指向正确单位。"""
    assert UNIT_CODE_BY_NAME["毫米"] == 4
    assert UNIT_CODE_BY_NAME["厘米"] == 5
    assert UNIT_CODE_BY_NAME["米"] == 6
    assert UNIT_CODE_BY_NAME["英寸"] == 1
    assert UNIT_CODE_BY_NAME["英尺"] == 2


@pytest.mark.parametrize("name", ["毫米", "厘米", "米", "英寸", "英尺"])
def test_chinese_unit_names_convert_correctly(tmp_path: Path, name: str):
    code = UNIT_CODE_BY_NAME[name]
    path = write_dxf(tmp_path / f"cn_{code}.dxf", build_units_fixture(4))
    result = DxfReader.read(path, unit=name)
    assert _only_line(result)["native_length_mm"] == pytest.approx(10.0 * EXPECTED_SCALE[code], rel=1e-12)
    assert result["unit_explicit"] is True


def test_invalid_unit_name_raises_value_error(tmp_path: Path):
    path = write_dxf(tmp_path / "invalid_unit.dxf", build_units_fixture(4))
    with pytest.raises(ValueError) as excinfo:
        DxfReader.read(path, unit="furlong")
    assert "未知单位" in str(excinfo.value)


@pytest.mark.parametrize("index,bad_scale", list(enumerate([0, 0.0, -1, -304.8, float("inf"), float("-inf"), float("nan")])))
def test_bad_scale_raises_value_error(tmp_path: Path, index: int, bad_scale):
    """非正 / 非有限的显式比例必须 `ValueError`（`None` 表示「不覆盖」，见下一个用例）。"""
    path = write_dxf(tmp_path / f"badscale_{index}.dxf", build_units_fixture(4))
    with pytest.raises(ValueError):
        DxfReader.read(path, unit_scale_to_mm=bad_scale)


def test_scale_of_none_means_no_override(tmp_path: Path):
    """显式传 `unit_scale_to_mm=None` 等价于不覆盖（沿用图纸头）。"""
    path = write_dxf(tmp_path / "none_scale.dxf", build_units_fixture(2))
    result = DxfReader.read(path, unit_scale_to_mm=None)
    assert result["unit_source"] == "dxf_header"
    assert result["unit_explicit"] is False
    assert _only_line(result)["native_length_mm"] == 3048.0


def test_missing_file_raises_file_not_found(tmp_path: Path):
    with pytest.raises(FileNotFoundError):
        DxfReader.read(tmp_path / "does-not-exist.dxf")


# --------------------------------------------------------------- normalize_unit_selection


def test_normalize_unit_selection_none_none_falls_back_to_default_scale():
    """实测行为：`None` + `None` 不报错，返回兜底比例 1.0，来源标记为 `dxf_header_unknown`。

    `normalize_unit_selection` 内部用 `resolve_unit(None)` —— 没有图纸头可读，
    因此它**必然**报告「头无法使用」；比例是 1.0 兜底值而不是「未知」。
    这是实现的真实行为，本测试如实记录（见交付说明中的发现项）。
    """
    resolved = normalize_unit_selection(None, None)
    assert resolved["unit"] is None
    assert resolved["unit_scale_to_mm"] == DEFAULT_SCALE_TO_MM
    assert resolved["unit_source"] == "dxf_header_unknown"


def test_normalize_unit_selection_by_name():
    resolved = normalize_unit_selection("ft", None)
    assert resolved["unit"] == "ft"
    assert resolved["unit_scale_to_mm"] == 304.8
    assert resolved["unit_source"] == "override_name"


def test_normalize_unit_selection_by_scale():
    resolved = normalize_unit_selection(None, 304.8)
    assert resolved["unit"] is None
    assert resolved["unit_scale_to_mm"] == 304.8
    assert resolved["unit_source"] == "override_scale"


def test_normalize_unit_selection_chinese_name_normalizes_to_canonical():
    assert normalize_unit_selection("英尺", None)["unit"] == "ft"
    assert normalize_unit_selection("毫米", None)["unit"] == "mm"


def test_normalize_unit_selection_auto_and_empty_fall_back():
    """`auto` / `header` / `dxf` / 空串表示「不覆盖」，落到 1.0 兜底。"""
    for value in ("auto", "header", "dxf", "", "  "):
        resolved = normalize_unit_selection(value, None)
        assert resolved["unit_scale_to_mm"] == DEFAULT_SCALE_TO_MM, value
        assert resolved["unit_source"] == "dxf_header_unknown", value


def test_normalize_unit_selection_rejects_unknown_name():
    with pytest.raises(ValueError):
        normalize_unit_selection("furlong", None)


@pytest.mark.parametrize("bad", [0, -1, float("inf"), float("nan")])
def test_normalize_unit_selection_rejects_bad_scale(bad):
    with pytest.raises(ValueError):
        normalize_unit_selection(None, bad)


def test_normalize_unit_selection_accepts_numeric_string_scale():
    """实测行为：数字字符串会被当成比例（`unit="304.8"` -> override_scale）。"""
    resolved = normalize_unit_selection("304.8", None)
    assert resolved["unit_scale_to_mm"] == 304.8
    assert resolved["unit_source"] == "override_scale"


def test_normalize_unit_selection_explicit_unitless_means_one_to_one():
    """实测行为：显式 `unitless`/`none` 被当作「明确按毫米 1:1」，不再标记未声明。"""
    resolved = normalize_unit_selection("unitless", None)
    assert resolved["unit_scale_to_mm"] == DEFAULT_SCALE_TO_MM
    assert resolved["unit_source"] == "override_name"
    assert resolve_unit(None, unit="unitless")["unit_unspecified"] is False


# --------------------------------------------------------------- available_units


def test_available_units_shape_and_coverage():
    units = available_units()
    assert units, "单位下拉列表不能为空"
    names = {item["name"] for item in units}
    for required in ("mm", "cm", "m", "in", "ft"):
        assert required in names, f"缺少常用单位 {required}"
    for item in units:
        assert set(item) == {"name", "unit_code", "scale_to_mm"}, item
        assert isinstance(item["unit_code"], int)
        assert item["scale_to_mm"] > 0
        # 比例必须与单位表一致
        assert item["scale_to_mm"] == MM_PER_UNIT[item["unit_code"]]


def test_available_units_present_in_reader_output(tmp_path: Path):
    """`DxfReader.read` 的 `available_units` 必须与 `available_units()` 一致。"""
    path = write_dxf(tmp_path / "avail.dxf", build_units_fixture(4))
    result = DxfReader.read(path)
    assert result["available_units"] == available_units()


def test_unit_name_by_code_is_consistent_both_directions():
    """`UNIT_NAME_BY_CODE` 与 `UNIT_CODE_BY_NAME` 在常见单位上必须互为逆映射。"""
    for code in EXPECTED_SCALE:
        name = UNIT_NAME_BY_CODE[code]
        assert UNIT_CODE_BY_NAME[name] == code
