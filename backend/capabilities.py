# -*- coding: utf-8 -*-
"""部署能力探测：让 UI / API 只提供当前部署真正可用的功能。

背景：本仓库的公开分发**不包含** `orchestrator/` 与 `tools/`（两者都被 .gitignore 排除），
但 API 层仍会调用它们提供的功能（静态导出、分享链接、归档快照、replay 编排）。
与其让前端按钮点下去必然 500，不如先探测一次能力，把不可用的入口禁用并给出中文原因。

设计约束：
- 只依赖标准库；`ezdxf` / `playwright` / `matplotlib` / ODA File Converter 的探测全部是可选的。
- 探测函数**绝不抛异常**：失败即视为不可用，并把中文原因写进 `reason`。
- 昂贵的 import 探测用 `functools.lru_cache` 缓存；测试可用 `reset_cache()` 清空。
"""

from __future__ import annotations

import functools
import importlib
import os
from datetime import datetime
from pathlib import Path
from typing import Any

BACKEND_DIR = Path(__file__).resolve().parent
REPO_ROOT = BACKEND_DIR.parent

# 静态导出：内置实现（backend/exporting/static_export.py）与可选的外部工具覆盖。
BUILTIN_EXPORT_MODULES: tuple[str, ...] = ("exporting.static_export", "backend.exporting.static_export")
EXTERNAL_EXPORT_ENV = "CAD_STATIC_EXPORT_TOOL"

# replay 编排器：公开分发里没有这个目录。
ORCHESTRATOR_DIRNAME = "orchestrator"
REPLAY_RUNNER_FILENAME = "replay_runner.py"
REPLAY_ENV = "CAD_ENABLE_REPLAY"

CAPABILITY_NAMES: tuple[str, ...] = (
    "dxf_parse",
    "dwg_convert",
    "static_export",
    "share_link",
    "visual_audit",
    "replay",
)

_TRUE_VALUES = {"1", "true", "yes", "on"}
_FALSE_VALUES = {"0", "false", "no", "off"}

_INSTALL_HINT = "请执行 pip install -r requirements.txt（离线环境可先用 wheelhouse 安装）"


class CapabilityUnavailable(RuntimeError):
    """请求的能力在当前部署不可用。API 层应转换为 HTTP 501/503（而不是 500）。"""

    def __init__(self, name: str, reason: str) -> None:
        self.name = name
        self.reason = reason
        super().__init__(f"能力不可用: {name} —— {reason}")


# ---------------------------------------------------------------- 探测辅助


def _entry(available: bool, reason: str | None, detail: dict[str, Any] | None = None) -> dict[str, Any]:
    """统一的探测结果结构。可用时 reason 一律为 None，避免前端拿到误导性提示。"""
    return {"available": bool(available), "reason": None if available else (reason or "未知原因"), "detail": detail or {}}


def _import_module(name: str) -> tuple[Any | None, str | None]:
    """import 一个模块，返回 (module, error_text)。永不抛异常。"""
    try:
        return importlib.import_module(name), None
    except Exception as exc:  # noqa: BLE001 - 探测阶段吞掉一切异常，只记录原因
        return None, f"{type(exc).__name__}: {exc}"


def _env_flag(name: str) -> bool | None:
    """读取三态布尔环境变量：True / False / None（未设置或无法识别）。"""
    raw = os.environ.get(name)
    if raw is None:
        return None
    value = raw.strip().lower()
    if value in _TRUE_VALUES:
        return True
    if value in _FALSE_VALUES:
        return False
    return None


# ---------------------------------------------------------------- 各项能力探测


@functools.lru_cache(maxsize=None)
def _probe_dxf_parse() -> dict[str, Any]:
    module, error = _import_module("ezdxf")
    if module is None:
        return _entry(
            False,
            f"未安装 ezdxf，无法解析 DXF 图纸（{error}）。{_INSTALL_HINT}。",
            {"version": None},
        )
    return _entry(True, None, {"version": str(getattr(module, "__version__", "") or "unknown")})


@functools.lru_cache(maxsize=None)
def _probe_dwg_convert() -> dict[str, Any]:
    module, error = _import_module("parser.dwg_converter")
    if module is None:
        return _entry(
            False,
            "DWG 转 DXF 不可用：未能加载 DWG 转换模块（"
            f"{error}）。DXF 解析仍然可用，不需要 ODA File Converter。",
            {"oda_path": None},
        )
    converter = getattr(module, "DwgConverter", None)
    oda_path: str | None = None
    finder = getattr(module, "find_oda_file_converter", None)
    if callable(finder):
        try:
            found = finder()
            oda_path = str(found) if found else None
        except Exception:  # noqa: BLE001 - 探测 ODA 路径失败不影响能力判定
            oda_path = None
    try:
        available = bool(converter is not None and converter.available())
    except Exception as exc:  # noqa: BLE001
        available = False
        error = f"{type(exc).__name__}: {exc}"
    if available:
        return _entry(True, None, {"oda_path": oda_path})
    reason = (
        "DWG 转 DXF 不可用：未检测到 ODA File Converter"
        + (f"（探测异常: {error}）" if error else "")
        + "。DXF 解析仍然可用，不需要 ODA；若需要处理 DWG，请安装 ODA File Converter 或设置 ODA_FILE_CONVERTER。"
    )
    return _entry(False, reason, {"oda_path": oda_path})


def _configured_external_exporter() -> Path | None:
    raw = os.environ.get(EXTERNAL_EXPORT_ENV)
    if not raw or not raw.strip():
        return None
    try:
        candidate = Path(raw).expanduser()
        return candidate if candidate.is_file() else None
    except OSError:
        return None


def _import_builtin_exporter() -> tuple[Any | None, str | None]:
    """尝试导入内置静态导出模块，返回 (module, error_text)。"""
    first_error: str | None = None
    for name in BUILTIN_EXPORT_MODULES:
        module, error = _import_module(name)
        if module is not None:
            return module, None
        if first_error is None:
            first_error = error
    return None, first_error


@functools.lru_cache(maxsize=None)
def _probe_static_export() -> dict[str, Any]:
    external = _configured_external_exporter()
    module, error = _import_builtin_exporter()
    builtin_ok = module is not None
    exporter = "external" if external is not None else ("builtin" if builtin_ok else None)
    detail: dict[str, Any] = {
        "exporter": exporter,
        "builtin_available": builtin_ok,
        "external_tool": str(external) if external is not None else None,
    }
    if builtin_ok:
        return _entry(True, None, detail)
    return _entry(
        False,
        "内置静态导出模块不可用（"
        f"{error}），静态页面导出 / 分享链接 / 归档快照都会被禁用；"
        "请确认 backend/exporting/static_export.py 存在且可导入，或通过 "
        f"{EXTERNAL_EXPORT_ENV} 指向外部导出工具。",
        detail,
    )


@functools.lru_cache(maxsize=None)
def _probe_share_link() -> dict[str, Any]:
    static_export = _probe_static_export()
    if static_export["available"]:
        return _entry(True, None, {})
    return _entry(False, f"分享链接依赖静态导出，而静态导出不可用：{static_export['reason']}", {})


@functools.lru_cache(maxsize=None)
def _probe_visual_audit() -> dict[str, Any]:
    # 该模块在 import 时就会拉起 matplotlib（Agg 后端），所以"能 import"就等于"能截图"
    module, error = _import_module("capture.dxf_region_renderer")
    if module is None or not callable(getattr(module, "capture_dxf_region", None)):
        return _entry(
            False,
            "视觉核对不可用：未能加载 capture.dxf_region_renderer.capture_dxf_region（"
            f"{error or '未找到 capture_dxf_region'}）。该功能需要 matplotlib 渲染 DXF 区域截图，"
            f"{_INSTALL_HINT}。",
            {},
        )
    return _entry(True, None, {})


@functools.lru_cache(maxsize=None)
def _probe_replay() -> dict[str, Any]:
    override = _env_flag(REPLAY_ENV)
    if override is False:
        return _entry(False, f"已通过环境变量 {REPLAY_ENV}=0 显式禁用 replay 逐图层复原编排。", {})

    orchestrator_dir = REPO_ROOT / ORCHESTRATOR_DIRNAME
    runner_present = (orchestrator_dir / REPLAY_RUNNER_FILENAME).is_file()
    prefix = f"环境变量 {REPLAY_ENV}=1 强制启用 replay，但" if override is True else ""

    if not runner_present:
        # 公开分发里没有 orchestrator/：没必要再去 import playwright
        return _entry(
            False,
            f"{prefix}replay 编排器未随公开版分发：仓库内缺少 {ORCHESTRATOR_DIRNAME}/{REPLAY_RUNNER_FILENAME}，"
            f"逐图层复原校验（python -m {ORCHESTRATOR_DIRNAME}.replay_runner）无法运行。"
            "该目录属于内部工具，不在公开仓库内（.gitignore 已排除）。",
            {"orchestrator_dir": str(orchestrator_dir), "runner_present": False},
        )

    playwright, playwright_error = _import_module("playwright")
    if playwright is None:
        return _entry(
            False,
            f"{prefix}已找到 {ORCHESTRATOR_DIRNAME}/{REPLAY_RUNNER_FILENAME}，但未安装 playwright，"
            f"无法驱动无头浏览器截图（{playwright_error}）。{_INSTALL_HINT}。",
            {"orchestrator_dir": str(orchestrator_dir), "runner_present": True},
        )
    return _entry(True, None, {"orchestrator_dir": str(orchestrator_dir), "runner_present": True})


_PROBES = {
    "dxf_parse": _probe_dxf_parse,
    "dwg_convert": _probe_dwg_convert,
    "static_export": _probe_static_export,
    "share_link": _probe_share_link,
    "visual_audit": _probe_visual_audit,
    "replay": _probe_replay,
}


# ---------------------------------------------------------------- 公开 API


def reset_cache() -> None:
    """清空所有探测缓存（测试用；也可在安装依赖后热刷新）。"""
    for probe in _PROBES.values():
        probe.cache_clear()


def capability(name: str) -> dict[str, Any]:
    """返回单个能力的判定结果；未知能力名返回不可用 + 未知能力原因。"""
    probe = _PROBES.get(name)
    if probe is None:
        return {"available": False, "reason": f"未知能力: {name}"}
    result = probe()
    return {"available": bool(result["available"]), "reason": result.get("reason"), "detail": dict(result.get("detail") or {})}


def is_available(name: str) -> bool:
    return bool(capability(name)["available"])


def require(name: str) -> None:
    """能力不可用时抛出 CapabilityUnavailable（中文消息，可直接给用户看）。"""
    result = capability(name)
    if not result["available"]:
        raise CapabilityUnavailable(name, str(result.get("reason") or f"能力不可用: {name}"))


def capability_report() -> dict[str, Any]:
    """返回可 JSON 序列化的能力报告：generated_at + 6 项能力（共 7 个键）。"""
    return {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "capabilities": {name: capability(name) for name in CAPABILITY_NAMES},
    }


if __name__ == "__main__":  # 便于手工排查：python backend/capabilities.py
    import json

    print(json.dumps(capability_report(), ensure_ascii=False, indent=2))
