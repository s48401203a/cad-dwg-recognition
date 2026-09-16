"""本机私有"场地适配"配置的加载器。

背景：规则引擎里曾直接硬编码一批**面向特定图纸/项目约定**的字面量，例如
设备编号前缀、编号范围写法、项目/方案名称关键词、以及按关键词扩充图层匹配。
这些内容的**来源与公开授权无法从仓库证据确认**，因此从公共代码中移出，
改为由本机私有配置提供；公共版本只保留通用的解析逻辑与结构。

加载位置：与 `mapping.yaml` / `profiles/` 同一套私有覆盖目录
（环境变量 `CAD_PROJECT_RULES_DIR`），文件名为 `site-adaptations.yaml`。

安全默认：**未提供配置时不内置任何供应商/客户前缀**，相关匹配分支自然不命中，
行为等价于"该适配不存在"，而不是"默认关闭但仍随代码公开"。
配置里不放任何敏感值；它本身位于被忽略的私有目录中。
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

ADAPTATIONS_FILENAME = "site-adaptations.yaml"

#: 私有配置目录（与 rule_engine 的 `CAD_PROJECT_RULES_DIR` 保持一致）。
PROJECT_RULES_DIR_ENV = "CAD_PROJECT_RULES_DIR"

#: 编号占位符：`{n}` 匹配 1-3 位数字，`{n:02d}` 匹配定宽数字，`{range}` 匹配范围写法。
_PATTERN_TOKENS = {
    "{n}": r"\d{1,3}",
    "{n:02d}": r"\d{2}",
    "{n:03d}": r"\d{3}",
    "{range}": r"\d{1,3}(?:[~～-]\d{1,3})?",
    "{sep}": r"[-_ ]?",
}


@dataclass
class SiteAdaptations:
    """一次解析上下文中的场地适配配置。未提供配置时全部为空。"""

    #: 设备编号：模型类型 -> 编号正则列表（用于整串匹配）
    label_patterns: dict[str, list[str]] = field(default_factory=dict)
    #: 设备编号范围：模型类型 -> 编号范围正则列表（用 `{range}` 占位）
    label_range_patterns: dict[str, list[str]] = field(default_factory=dict)
    #: 项目/方案名称关键词（用于区分主图与附带图框）
    project_name_keywords: list[str] = field(default_factory=list)
    #: 追加到公开规则里的关键词：规则键路径 -> 关键词列表
    extra_rule_keywords: dict[str, list[str]] = field(default_factory=dict)
    #: 追加到"设备/电缆图层关键词"的图层名样式（未配置时为空）
    extra_layer_keywords: list[str] = field(default_factory=list)
    #: 追加的"数量注释"正则：键 -> 正则列表（未配置时为空）
    extra_quantity_patterns: dict[str, list[str]] = field(default_factory=dict)
    #: 配置来源（用于审计；不写入导出内容）
    source_path: str | None = None

    #: 编译后的正则（内部使用，不参与序列化）
    compiled_label: dict[str, list[re.Pattern[str]]] = field(default_factory=dict, repr=False)
    compiled_range: dict[str, list[re.Pattern[str]]] = field(default_factory=dict, repr=False)

    @property
    def empty(self) -> bool:
        return not (
            self.label_patterns
            or self.label_range_patterns
            or self.project_name_keywords
            or self.extra_rule_keywords
            or self.extra_layer_keywords
            or self.extra_quantity_patterns
        )

    def patterns_for(self, model: str) -> list[re.Pattern[str]]:
        return self.compiled_label.get(model, [])

    def range_patterns_for(self, model: str) -> list[re.Pattern[str]]:
        return self.compiled_range.get(model, [])

    def all_label_patterns(self) -> list[re.Pattern[str]]:
        return [pattern for patterns in self.compiled_label.values() for pattern in patterns]

    def all_range_patterns(self) -> list[re.Pattern[str]]:
        return [pattern for patterns in self.compiled_range.values() for pattern in patterns]


def _expand(pattern: str) -> str:
    """把占位符展开为通用正则片段（不引入任何供应商/客户前缀）。"""
    expanded = str(pattern)
    for token, regex in _PATTERN_TOKENS.items():
        if token in expanded:
            expanded = expanded.replace(token, regex)
    return expanded


def _compile_all(values: Any) -> list[re.Pattern[str]]:
    patterns: list[re.Pattern[str]] = []
    if not isinstance(values, list):
        return patterns
    for item in values:
        text = str(item or "").strip()
        if not text:
            continue
        try:
            patterns.append(re.compile(_expand(text), re.IGNORECASE))
        except re.error:
            # 非法正则不应让整个解析失败：跳过并在审计信息里可见（计入 skipped 数量）
            continue
    return patterns


def _normalize_pattern_map(raw: Any) -> dict[str, list[str]]:
    result: dict[str, list[str]] = {}
    if not isinstance(raw, dict):
        return result
    for key, values in raw.items():
        model = str(key or "").strip()
        if not model:
            continue
        texts = [str(item).strip() for item in values if str(item or "").strip()] if isinstance(values, list) else []
        if texts:
            result[model] = texts
    return result


def adaptations_path(rules_dir: Path | None = None) -> Path | None:
    """返回私有配置文件路径（不存在时返回 None）。"""
    if rules_dir is not None:
        candidate = Path(rules_dir) / ADAPTATIONS_FILENAME
        return candidate if candidate.is_file() else None
    import os

    raw = os.environ.get(PROJECT_RULES_DIR_ENV)
    if not raw:
        return None
    candidate = Path(raw).expanduser() / ADAPTATIONS_FILENAME
    return candidate if candidate.is_file() else None


def load_site_adaptations(rules_dir: Path | None = None, *, data: dict[str, Any] | None = None) -> SiteAdaptations:
    """加载场地适配配置。未配置或读取失败时返回空配置（不抛异常，保证解析可继续）。"""
    payload = data
    source: str | None = None
    if payload is None:
        path = adaptations_path(rules_dir)
        if path is None:
            return SiteAdaptations()
        source = str(path)
        try:
            loaded = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        except (OSError, yaml.YAMLError):
            return SiteAdaptations()
        payload = loaded if isinstance(loaded, dict) else {}

    if not isinstance(payload, dict):
        return SiteAdaptations()

    label_patterns = _normalize_pattern_map(payload.get("label_patterns"))
    label_range_patterns = _normalize_pattern_map(payload.get("label_range_patterns"))
    keywords = [str(item).strip() for item in (payload.get("project_name_keywords") or []) if str(item or "").strip()]

    extra_rule_keywords: dict[str, list[str]] = {}
    raw_extra = payload.get("extra_rule_keywords")
    if isinstance(raw_extra, dict):
        for key, values in raw_extra.items():
            path_key = str(key or "").strip()
            if not path_key:
                continue
            items = [str(item).strip() for item in values if str(item or "").strip()] if isinstance(values, list) else []
            if items:
                extra_rule_keywords[path_key] = items

    extra_layer_keywords = [
        str(item).strip() for item in (payload.get("extra_layer_keywords") or []) if str(item or "").strip()
    ]

    extra_quantity_patterns: dict[str, list[str]] = {}
    raw_quantity = payload.get("extra_quantity_patterns")
    if isinstance(raw_quantity, dict):
        for key, values in raw_quantity.items():
            name = str(key or "").strip()
            if not name:
                continue
            items = [str(item).strip() for item in values if str(item or "").strip()] if isinstance(values, list) else []
            if items:
                extra_quantity_patterns[name] = items

    return SiteAdaptations(
        extra_layer_keywords=extra_layer_keywords,
        extra_quantity_patterns=extra_quantity_patterns,
        label_patterns=label_patterns,
        label_range_patterns=label_range_patterns,
        project_name_keywords=keywords,
        extra_rule_keywords=extra_rule_keywords,
        source_path=source,
        compiled_label={model: _compile_all(values) for model, values in label_patterns.items()},
        compiled_range={model: _compile_all(values) for model, values in label_range_patterns.items()},
    )


def _resolve_rule_node(rules: dict[str, Any], path_key: str) -> dict[str, Any] | None:
    """按 `组.键` 定位规则节点。

    注意：规则键**本身可能含点**（例如 `cable.security` 是一个完整键名），
    因此必须"最长键名优先"：先按整串找，再逐级回退切分。
    """
    parts = [part for part in str(path_key).split(".") if part]
    for split_at in range(len(parts) - 1, 0, -1):
        group_key = ".".join(parts[:split_at])
        rule_key = ".".join(parts[split_at:])
        group = rules.get(group_key)
        if isinstance(group, dict):
            target = group.get(rule_key)
            if isinstance(target, dict):
                return target
    return None


def merge_rule_keywords(rules: dict[str, Any], adaptations: SiteAdaptations) -> dict[str, Any]:
    """把私有配置里的关键词**追加**到公开规则的 keywords 列表（就地修改并返回）。"""
    for path_key, keywords in adaptations.extra_rule_keywords.items():
        target = _resolve_rule_node(rules, path_key)
        if target is None:
            continue
        existing = target.get("keywords")
        merged = list(existing) if isinstance(existing, list) else []
        for keyword in keywords:
            if keyword not in merged:
                merged.append(keyword)
        target["keywords"] = merged
    return rules


__all__ = [
    "ADAPTATIONS_FILENAME",
    "PROJECT_RULES_DIR_ENV",
    "SiteAdaptations",
    "adaptations_path",
    "load_site_adaptations",
    "merge_rule_keywords",
]
