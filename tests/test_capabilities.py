# -*- coding: utf-8 -*-
"""能力探测模块的回归测试。

这些测试只做「本地能力探测」，不读任何项目数据，也不依赖 ODA / playwright 是否真的安装：
需要特定环境的分支一律用 stub 模块注入，保证在任何机器上都能稳定复现。

注意：本仓库的 `tests/conftest.py` 会在用例之间 `importlib.reload` 后端模块（其中包含
`capabilities`），因此这里一律通过模块属性访问函数与异常类，避免持有 reload 前的旧类对象。
"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

import pytest

ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

import capabilities  # noqa: E402

EXPECTED_NAMES = {"dxf_parse", "dwg_convert", "static_export", "share_link", "visual_audit", "replay"}


@pytest.fixture(autouse=True)
def _fresh_probe_cache():
    """每条用例前后都清空探测缓存，避免用例之间互相污染。"""
    capabilities.reset_cache()
    try:
        yield
    finally:
        capabilities.reset_cache()


def _stub_module(**attributes: Any) -> Any:
    return type("StubModule", (), attributes)


# ---------------------------------------------------------------- 报告结构


def test_capability_report_shape() -> None:
    report = capabilities.capability_report()

    # 顶层 generated_at + 6 项能力 = 报告对外共 7 个键
    assert set(report) == {"generated_at", "capabilities"}
    assert len(report["capabilities"]) + 1 == 7
    assert isinstance(report["generated_at"], str) and report["generated_at"]

    entries = report["capabilities"]
    assert set(entries) == EXPECTED_NAMES == set(capabilities.CAPABILITY_NAMES)


def test_every_entry_reports_available_reason_and_detail() -> None:
    entries = capabilities.capability_report()["capabilities"]

    for name, entry in entries.items():
        assert isinstance(entry["available"], bool), name
        assert isinstance(entry["detail"], dict), name
        if entry["available"]:
            assert entry["reason"] is None, name
        else:
            assert isinstance(entry["reason"], str) and entry["reason"].strip(), name


def test_capability_report_is_json_serialisable() -> None:
    dumped = json.dumps(capabilities.capability_report(), ensure_ascii=False)
    assert '"available"' in dumped
    assert len(json.loads(dumped)["capabilities"]) == 6


def test_report_entries_are_copies_not_shared_state() -> None:
    first = capabilities.capability("dxf_parse")
    first["detail"]["injected"] = True
    assert "injected" not in capabilities.capability("dxf_parse")["detail"]


# ---------------------------------------------------------------- 未知能力 / require


def test_unknown_capability_is_unavailable() -> None:
    assert capabilities.is_available("unknown") is False
    assert capabilities.capability("unknown") == {"available": False, "reason": "未知能力: unknown"}


def test_require_unknown_capability_raises_with_attributes() -> None:
    with pytest.raises(capabilities.CapabilityUnavailable) as captured:
        capabilities.require("unknown")

    error = captured.value
    assert error.name == "unknown"
    assert error.reason
    assert "unknown" in str(error)
    assert isinstance(error, RuntimeError)


def test_require_passes_when_capability_available() -> None:
    # 内置静态导出器不依赖任何第三方库，任何 checkout 里都必须可用
    assert capabilities.is_available("static_export") is True
    capabilities.require("static_export")


# ---------------------------------------------------------------- 各项能力


def test_static_export_reports_builtin_exporter(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("CAD_STATIC_EXPORT_TOOL", raising=False)
    capabilities.reset_cache()

    entry = capabilities.capability("static_export")
    assert entry["available"] is True
    assert entry["reason"] is None
    assert entry["detail"]["exporter"] == "builtin"
    assert entry["detail"]["builtin_available"] is True
    assert entry["detail"]["external_tool"] is None


def test_static_export_reports_external_tool_when_configured(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    tool = tmp_path / "export_tool.py"
    tool.write_text("# stub\n", encoding="utf-8")
    monkeypatch.setenv("CAD_STATIC_EXPORT_TOOL", str(tool))
    capabilities.reset_cache()

    entry = capabilities.capability("static_export")
    assert entry["available"] is True
    assert entry["detail"]["exporter"] == "external"
    assert entry["detail"]["external_tool"] == str(tool)


def test_static_export_ignores_missing_external_tool(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("CAD_STATIC_EXPORT_TOOL", str(tmp_path / "not-here.py"))
    capabilities.reset_cache()

    entry = capabilities.capability("static_export")
    assert entry["available"] is True
    assert entry["detail"]["exporter"] == "builtin"


def test_share_link_follows_static_export(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("CAD_STATIC_EXPORT_TOOL", raising=False)
    capabilities.reset_cache()

    assert capabilities.capability("share_link")["available"] is capabilities.is_available("static_export")


def test_share_link_reason_points_at_static_export(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(capabilities, "_import_builtin_exporter", lambda: (None, "ModuleNotFoundError: boom"))
    capabilities.reset_cache()

    entry = capabilities.capability("share_link")
    assert entry["available"] is False
    assert "静态导出" in entry["reason"]


def test_dxf_parse_reason_mentions_requirements_when_ezdxf_missing(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(capabilities, "_import_module", lambda name: (None, "ModuleNotFoundError: No module named 'ezdxf'"))
    capabilities.reset_cache()

    entry = capabilities.capability("dxf_parse")
    assert entry["available"] is False
    assert "requirements.txt" in entry["reason"]
    assert entry["detail"]["version"] is None


def test_dwg_convert_unavailable_reason_says_dxf_still_works(monkeypatch: pytest.MonkeyPatch) -> None:
    stub = _stub_module(DwgConverter=_stub_module(available=lambda: False))
    monkeypatch.setattr(capabilities, "_import_module", lambda name: (stub, None))
    capabilities.reset_cache()

    entry = capabilities.capability("dwg_convert")
    assert entry["available"] is False
    reason = entry["reason"]
    assert "DXF" in reason and "仍然可用" in reason
    assert "ODA" in reason
    assert entry["detail"] == {"oda_path": None}


def test_dwg_convert_reports_oda_path_when_available(monkeypatch: pytest.MonkeyPatch) -> None:
    stub = _stub_module(
        DwgConverter=_stub_module(available=lambda: True),
        find_oda_file_converter=lambda: Path("/opt/oda/ODAFileConverter"),
    )
    monkeypatch.setattr(capabilities, "_import_module", lambda name: (stub, None))
    capabilities.reset_cache()

    entry = capabilities.capability("dwg_convert")
    assert entry["available"] is True
    assert entry["reason"] is None
    assert entry["detail"]["oda_path"] == "/opt/oda/ODAFileConverter"


def test_visual_audit_reason_mentions_matplotlib(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(capabilities, "_import_module", lambda name: (None, "ModuleNotFoundError: No module named 'matplotlib'"))
    capabilities.reset_cache()

    entry = capabilities.capability("visual_audit")
    assert entry["available"] is False
    assert "matplotlib" in entry["reason"]


# ---------------------------------------------------------------- replay


def test_replay_unavailable_without_orchestrator(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setattr(capabilities, "REPO_ROOT", tmp_path)
    monkeypatch.delenv("CAD_ENABLE_REPLAY", raising=False)
    capabilities.reset_cache()

    entry = capabilities.capability("replay")
    assert entry["available"] is False
    assert entry["reason"]
    assert "公开" in entry["reason"]
    assert "orchestrator" in entry["reason"]
    assert entry["detail"]["runner_present"] is False


def test_replay_env_can_disable_explicitly(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setattr(capabilities, "REPO_ROOT", tmp_path)
    monkeypatch.setenv("CAD_ENABLE_REPLAY", "0")
    capabilities.reset_cache()

    entry = capabilities.capability("replay")
    assert entry["available"] is False
    assert "CAD_ENABLE_REPLAY" in entry["reason"]


def test_replay_env_enable_still_requires_modules(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setattr(capabilities, "REPO_ROOT", tmp_path)
    monkeypatch.setenv("CAD_ENABLE_REPLAY", "true")
    capabilities.reset_cache()

    entry = capabilities.capability("replay")
    assert entry["available"] is False
    assert "CAD_ENABLE_REPLAY" in entry["reason"]
    assert "orchestrator" in entry["reason"]


def test_replay_available_when_runner_and_playwright_exist(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    (tmp_path / "orchestrator").mkdir()
    (tmp_path / "orchestrator" / "replay_runner.py").write_text("# stub\n", encoding="utf-8")
    monkeypatch.setattr(capabilities, "REPO_ROOT", tmp_path)
    monkeypatch.delenv("CAD_ENABLE_REPLAY", raising=False)
    monkeypatch.setattr(
        capabilities, "_import_module", lambda name: (_stub_module(), None) if name == "playwright" else (None, "unused")
    )
    capabilities.reset_cache()

    entry = capabilities.capability("replay")
    assert entry["available"] is True
    assert entry["reason"] is None
    assert entry["detail"]["runner_present"] is True


def test_replay_reason_mentions_playwright_when_missing(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    (tmp_path / "orchestrator").mkdir()
    (tmp_path / "orchestrator" / "replay_runner.py").write_text("# stub\n", encoding="utf-8")
    monkeypatch.setattr(capabilities, "REPO_ROOT", tmp_path)
    monkeypatch.delenv("CAD_ENABLE_REPLAY", raising=False)
    monkeypatch.setattr(capabilities, "_import_module", lambda name: (None, "ModuleNotFoundError: No module named 'playwright'"))
    capabilities.reset_cache()

    entry = capabilities.capability("replay")
    assert entry["available"] is False
    assert "playwright" in entry["reason"]


# ---------------------------------------------------------------- 缓存 / 探测健壮性


def test_reset_cache_clears_lru_probes() -> None:
    capabilities.reset_cache()
    assert capabilities._probe_dxf_parse.cache_info().currsize == 0
    capabilities.capability("dxf_parse")
    assert capabilities._probe_dxf_parse.cache_info().currsize == 1
    capabilities.reset_cache()
    assert capabilities._probe_dxf_parse.cache_info().currsize == 0


def test_import_probe_never_raises() -> None:
    module, error = capabilities._import_module("definitely_not_a_real_module_for_tests")
    assert module is None
    assert isinstance(error, str) and "ModuleNotFoundError" in error
