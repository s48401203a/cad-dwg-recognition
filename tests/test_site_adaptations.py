"""场地适配隔离的回归测试。

验证两件事：
1. **未配置时行为等价**：公共代码不内置任何供应商/客户编号前缀，
   相关匹配分支自然不命中（等价于"该适配不存在"），而不是"默认关闭但仍随代码公开"。
2. **配置后可恢复**：把适配放进本机私有目录（`CAD_PROJECT_RULES_DIR`）后，
   编号识别与图层关键词扩充重新生效。
"""

from __future__ import annotations

import textwrap
from pathlib import Path

import pytest

from semantic.rule_engine import RuleEngine
from semantic.site_adaptations import adaptations_path, load_site_adaptations, merge_rule_keywords

# 测试用的**虚构**前缀（与任何真实项目无关）
DEMO_PREFIX = "ZZZ"
DEMO_LAYER = "示例-弱电图层"


@pytest.fixture()
def private_rules_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """建一个私有规则目录，并把它接到 CAD_PROJECT_RULES_DIR。"""
    rules_dir = tmp_path / "private-rules"
    rules_dir.mkdir()
    monkeypatch.setenv("CAD_PROJECT_RULES_DIR", str(rules_dir))
    return rules_dir


def _write_adaptations(rules_dir: Path, body: str) -> None:
    (rules_dir / "site-adaptations.yaml").write_text(textwrap.dedent(body), encoding="utf-8")


# --------------------------------------------------------------- 未配置时


def test_unconfigured_adaptations_are_empty(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    """没有 site-adaptations.yaml 时，适配配置为空。"""
    monkeypatch.setenv("CAD_PROJECT_RULES_DIR", str(tmp_path / "not-exists"))
    adaptations = load_site_adaptations()
    assert adaptations.empty is True
    assert adaptations.all_label_patterns() == []
    assert adaptations.all_range_patterns() == []
    assert adaptations.project_name_keywords == []
    assert adaptations_path() is None


def test_engine_has_no_builtin_site_prefixes():
    """公共代码默认不识别任何"场地编号"：引擎的适配配置为空。"""
    engine = RuleEngine(site_profiles=["generic"])
    assert engine.adaptations.empty is True
    # 常见的中性/占位编号不应被当成场地编号识别
    assert engine._matches_adaptation_label("ap", "AP-01") is False
    assert engine._matches_adaptation_label("ap", f"{DEMO_PREFIX}-01") is False
    assert engine._adaptation_range_fullmatch("ap", f"{DEMO_PREFIX}-AP-01") is None
    assert engine._adaptation_prefixes("ap") == []
    assert engine._label_has_adaptation_token(f"{DEMO_PREFIX}-AP-01") is False


def test_unconfigured_project_name_keywords_do_not_match():
    """未配置时，不把任何字样当作"项目/方案名"。"""
    engine = RuleEngine(site_profiles=["generic"])
    for text in ("现方案", "当前方案", "新方案", "面积变化", "某某项目"):
        assert engine._matches_project_name_keyword(text) is False


def test_main_plan_title_is_neutral():
    """主平面标题是中性词，不含任何项目/方案名。"""
    from semantic import rule_engine

    assert rule_engine.MAIN_PLAN_TITLE == "主平面"


# --------------------------------------------------------------- 配置后


def test_configured_label_patterns_are_usable(private_rules_dir: Path):
    """配置后：编号整串匹配与范围匹配重新生效。"""
    _write_adaptations(
        private_rules_dir,
        f"""
        version: "1"
        label_patterns:
          ap:
            - "{DEMO_PREFIX}-{{n}}"
        label_range_patterns:
          ap:
            - "(?P<prefix>{DEMO_PREFIX}-AP-)({{range}})"
        """,
    )
    engine = RuleEngine(site_profiles=["generic"])
    assert engine.adaptations.empty is False
    assert engine._matches_adaptation_label("ap", f"{DEMO_PREFIX}-01") is True
    assert engine._matches_adaptation_label("ap", "OTHER-01") is False

    match = engine._adaptation_range_fullmatch("ap", f"{DEMO_PREFIX}-AP-01~08")
    assert match is not None, "配置的范围模式应能匹配"
    assert engine._adaptation_range_fullmatch("ap", "OTHER-AP-01~08") is None


def test_configured_extra_layer_keywords_apply(private_rules_dir: Path):
    """配置后：额外的图层名关键词参与图层判定。"""
    _write_adaptations(
        private_rules_dir,
        f"""
        version: "1"
        extra_layer_keywords:
          - "{DEMO_LAYER}"
        """,
    )
    engine = RuleEngine(site_profiles=["generic"])
    assert engine._extra_layer_keywords() == [DEMO_LAYER]
    assert engine._is_device_cable_layer(DEMO_LAYER) is True
    # 未配置的图层名仍不匹配
    assert engine._is_device_cable_layer("毫无关系的图层") is False


def test_configured_project_name_keywords_apply(private_rules_dir: Path):
    """配置后：项目/方案名称关键词生效（此前是硬编码）。"""
    _write_adaptations(
        private_rules_dir,
        """
        version: "1"
        project_name_keywords:
          - "示例方案名"
        """,
    )
    engine = RuleEngine(site_profiles=["generic"])
    assert engine._matches_project_name_keyword("这里是示例方案名的图框") is True
    assert engine._matches_project_name_keyword("普通图框") is False


def test_configured_rule_keywords_are_merged(private_rules_dir: Path):
    """配置后：图层规则关键词被追加进公开规则（只增不改）。"""
    _write_adaptations(
        private_rules_dir,
        f"""
        version: "1"
        extra_rule_keywords:
          layer_rules.cable.security:
            - "{DEMO_LAYER}"
        """,
    )
    engine = RuleEngine(site_profiles=["generic"])
    keywords = ((engine.rules.get("layer_rules") or {}).get("cable.security") or {}).get("keywords") or []
    assert DEMO_LAYER in keywords
    # 公开规则里的通用关键词仍在
    assert "监控" in keywords


# --------------------------------------------------------------- 健壮性


def test_invalid_config_does_not_break_parsing(private_rules_dir: Path):
    """配置损坏或含非法正则时，解析仍可继续（该条被跳过，不抛异常）。"""
    _write_adaptations(
        private_rules_dir,
        """
        version: "1"
        label_patterns:
          ap:
            - "([unclosed"
            - "OK-{n}"
        """,
    )
    engine = RuleEngine(site_profiles=["generic"])
    # 合法的一条仍然生效
    assert engine._matches_adaptation_label("ap", "OK-01") is True


def test_merge_rule_keywords_ignores_unknown_paths(private_rules_dir: Path):
    """未知规则路径被忽略，不抛异常、不新增节点。"""
    _write_adaptations(
        private_rules_dir,
        """
        version: "1"
        extra_rule_keywords:
          not_a_real_group.not_a_real_rule:
            - "x"
        """,
    )
    engine = RuleEngine(site_profiles=["generic"])
    assert "not_a_real_group" not in engine.rules


def test_adaptations_module_has_no_builtin_prefix_literals():
    """公共模块本身不得再出现真实供应商/客户前缀字面量。

    这是一个**结构性**断言：源码里只允许出现占位符与通用词。
    """
    source = Path("backend/semantic/site_adaptations.py").read_text(encoding="utf-8")
    for forbidden in ("BFR", "BGL", "-BG-AP-", "弱电规划", "方案0703"):
        assert forbidden not in source, f"site_adaptations.py 不应内置 {forbidden!r}"


def test_configured_quantity_patterns_apply(private_rules_dir: Path):
    """配置后：项目专属的"数量注释"正则生效（公开版只保留通用写法）。"""
    _write_adaptations(
        private_rules_dir,
        f"""
        version: "1"
        extra_quantity_patterns:
          ap:
            - "场地AP[（(]?编号[：:]?{DEMO_PREFIX}-AP-0*1[~～]0*(\\\\d{{1,3}})"
        """,
    )
    engine = RuleEngine(site_profiles=["generic"])
    assert engine._extra_quantity_patterns("ap"), "应读到私有配置的数量正则"

    entities = [
        {"entity_type": "TEXT", "text": f"场地AP（编号：{DEMO_PREFIX}-AP-01~12）"},
    ]
    assert engine._expected_site_ap_max_number(entities) == 12


def test_unconfigured_quantity_patterns_do_not_match():
    """未配置时：项目专属的数量注释写法不被识别（不内置默认）。"""
    engine = RuleEngine(site_profiles=["generic"])
    assert engine._extra_quantity_patterns("ap") == []
    entities = [{"entity_type": "TEXT", "text": f"场地AP（编号：{DEMO_PREFIX}-AP-01~12）"}]
    assert engine._expected_site_ap_max_number(entities) is None


# --------------------------------------------------------------- A1 场地数值隔离


def test_unconfigured_site_values_are_absent():
    """未配置时：场地数值一项都读不到（不是回落到内置默认）。"""
    engine = RuleEngine(site_profiles=["generic"])
    for key in (
        "dock_height_m",
        "warehouse_wall_height_m",
        "warehouse_roof_peak_height_m",
        "power_equipment_min_center_spacing_mm",
        "power_equipment_service_clearance_m",
        "tray_min_segment_mm",
        "tray_label_tolerance_mm",
    ):
        assert engine._site_value(key) is None, f"{key} 不应有内置默认值"
    assert engine._power_clearance_attrs("service_channel_to_ups_m") == {}
    assert engine._warehouse_shell_attrs() == {}
    assert engine._dock_value_attrs() == {}


def test_unconfigured_site_values_do_not_write_height_fields():
    """未配置时：语义结果不写入场地尺寸字段。"""
    engine = RuleEngine(site_profiles=["express"])
    site = engine._site_metadata([])
    for key in ("dock_height_m", "warehouse_floor_height_m", "warehouse_wall_height_m", "warehouse_roof_peak_height_m"):
        assert key not in site, f"未配置时不应写入 {key}"


def test_unconfigured_height_inference_is_skipped():
    """未配置目标高度时：不做高度挑选（只读标注、不写入结果）。"""
    engine = RuleEngine(site_profiles=["express"])
    entities = [{"entity_type": "TEXT", "text": "9.500"}, {"entity_type": "TEXT", "text": "11.000"}]
    assert engine._infer_warehouse_heights(entities) == {}


def test_configured_site_values_are_applied(private_rules_dir: Path):
    """配置后：场地数值生效，且高度推断按配置目标进行。"""
    _write_adaptations(
        private_rules_dir,
        """
        version: "1"
        site_values:
          dock_height_m: 1.1
          warehouse_wall_height_m: 9.0
          warehouse_roof_peak_height_m: 10.0
          power_equipment_service_clearance_m: 0.2
          power_equipment_min_center_spacing_mm: 1200
        vehicle_legend_counts:
          box_4_2: 11
        """,
    )
    engine = RuleEngine(site_profiles=["express"])
    assert engine._site_value("dock_height_m") == 1.1
    assert engine._power_clearance_attrs("service_channel_to_ups_m")["maintenance_clearance_m"] == 0.2
    site = engine._site_metadata([])
    assert site["dock_height_m"] == 1.1
    assert site["warehouse_wall_height_m"] == 9.0

    heights = engine._infer_warehouse_heights(
        [{"entity_type": "TEXT", "text": "9.000"}, {"entity_type": "TEXT", "text": "10.000"}]
    )
    assert heights.get("warehouse_wall_height_m") == 9.0
    assert engine._vehicle_legend_weight("box_4_2") == 11.0
    assert engine._vehicle_legend_weight("box_9_6") == 1.0, "未配置的车型按等权"


def test_placement_placeholder_marks_source():
    """摆放试验场：未配置时用明确标注的占位值，而不是从原场地值改名。"""
    from placement import PLACEHOLDER_WALL_HEIGHT_M, default_semantic, load_catalog

    catalog = load_catalog()
    semantic = default_semantic({"id": "proj_placeholder", "name": "摆放试验场", "site_profiles": ["generic"]}, catalog)
    source = (semantic.get("site") or {}).get("height_source") or {}
    assert source.get("warehouse_wall_height_m") == "placeholder_default"
    assert semantic["site"]["warehouse_wall_height_m"] == PLACEHOLDER_WALL_HEIGHT_M


def test_public_configs_have_no_site_numbers():
    """结构性断言：公开配置里不得出现场地数值。"""
    import re
    from pathlib import Path as _Path

    for relative in ("backend/config/company_standards.yaml", "backend/config/model-catalog.yaml",
                     "backend/config/profiles/express.yaml", "backend/config/profiles/generic.yaml"):
        text = _Path(relative).read_text(encoding="utf-8")
        for key in ("dock_height_m", "warehouse_wall_height_m", "warehouse_roof_peak_height_m",
                    "camera_to_vehicle_tail_gap_m", "legend_count"):
            for match in re.finditer(rf"^\s*{key}:\s*(\S+)\s*$", text, re.M):
                raise AssertionError(f"{relative} 仍含场地数值：{key}: {match.group(1)}")
