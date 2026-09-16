"""统一的项目/图纸/文件路径访问策略。

设计原则：
- 客户端只提交 **项目 ID / 图纸 ID / 文件 ID**，绝不提交文件系统路径。
- 所有由服务端解析出的路径必须落在显式允许的根目录之内。
- 所有入口（读取、保存、导出、归档、恢复、打开文件、项目包导入）复用同一套校验。

本模块是纯函数式的，不导入 storage，避免循环依赖；storage 反过来导入本模块。
"""

from __future__ import annotations

import re
from pathlib import Path, PurePosixPath, PureWindowsPath
from typing import Any, Iterable

# 项目 / 图纸 / 上传 ID 只允许 ASCII 字母数字、下划线、连字符，且必须有界长度。
# 真实 ID 形如 proj_1a2b3c4d5e / draw_1a2b3c4d5e / 32 位 hex。
SAFE_ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,63}$")
MAX_ID_LENGTH = 64

# 文件名允许中文等 Unicode 字符，但禁止路径分隔符与控制字符。
_UNSAFE_FILENAME_CHARS = set('<>:"/\\|?*')


class PathPolicyError(ValueError):
    """路径或 ID 未通过访问策略校验。调用方应转换为 HTTP 400/403。"""

    def __init__(self, message: str, *, code: str = "path_rejected") -> None:
        super().__init__(message)
        self.code = code


def _reject(message: str, code: str = "path_rejected") -> "PathPolicyError":
    return PathPolicyError(message, code=code)


def is_safe_id(value: Any, *, max_length: int = MAX_ID_LENGTH) -> bool:
    """ID 是否只含安全字符。空值 / 非字符串视为不安全。"""
    if not isinstance(value, str):
        return False
    candidate = value.strip()
    if not candidate or len(candidate) > max_length:
        return False
    return bool(SAFE_ID_PATTERN.match(candidate))


def validate_id(value: Any, *, kind: str = "ID") -> str:
    """校验并返回规范化 ID，不合法则抛 PathPolicyError。"""
    if isinstance(value, str):
        candidate = value.strip()
    else:
        candidate = ""
    if not candidate:
        raise _reject(f"{kind} 不能为空", code="invalid_id")
    if len(candidate) > MAX_ID_LENGTH:
        raise _reject(f"{kind} 过长（上限 {MAX_ID_LENGTH} 字符）", code="invalid_id")
    if not SAFE_ID_PATTERN.match(candidate):
        raise _reject(f"{kind} 含非法字符，只允许字母、数字、下划线和连字符", code="invalid_id")
    return candidate


def validate_project_id(value: Any) -> str:
    return validate_id(value, kind="项目 ID")


def validate_drawing_id(value: Any) -> str:
    return validate_id(value, kind="图纸 ID")


def validate_file_id(value: Any) -> str:
    return validate_id(value, kind="文件 ID")


def sanitize_filename(value: Any, *, fallback: str = "drawing", max_length: int = 120) -> str:
    """把上传文件名收敛为安全的单段文件名。

    去掉任何目录成分（含 Windows 反斜杠与 UNC 前缀）、控制字符与保留字符。
    """
    raw = str(value or "").replace("\x00", "")
    # 先在两种平台语义下取最后一段，防止仅用 Path.name 在 POSIX 上漏掉反斜杠。
    raw = PureWindowsPath(raw).name if "\\" in raw else raw
    raw = PurePosixPath(raw).name
    raw = raw.replace("/", "_").replace("\\", "_")
    cleaned = "".join(ch for ch in raw if ch not in _UNSAFE_FILENAME_CHARS and ord(ch) >= 32)
    cleaned = cleaned.strip().strip(".")
    if not cleaned:
        cleaned = fallback
    if len(cleaned) > max_length:
        suffix = PurePosixPath(cleaned).suffix[:16]
        stem_budget = max(1, max_length - len(suffix))
        cleaned = f"{PurePosixPath(cleaned).stem[:stem_budget]}{suffix}"
    return cleaned


def looks_like_path(value: Any) -> bool:
    """判断字符串是否像文件系统路径（而非纯 ID）。

    用于拒绝"客户端提交路径"这类输入。绝对路径、URI、含分隔符或 `..` 的值都算路径。
    """
    if not isinstance(value, str):
        return False
    candidate = value.strip()
    if not candidate:
        return False
    if candidate.startswith(("/", "\\", "~", "file:", "\\\\")):
        return True
    if re.match(r"^[A-Za-z]:[\\/]", candidate):
        return True
    if "/" in candidate or "\\" in candidate:
        return True
    parts = candidate.split("/")
    return ".." in parts or ".." in candidate.split("\\")


def resolve_within_roots(
    value: str | Path,
    roots: Iterable[str | Path],
    *,
    label: str = "路径",
    must_exist: bool = False,
    allow_symlink: bool = False,
) -> Path:
    """把 value 解析为绝对路径，并确认它位于 roots 之一的内部。

    - 相对路径按第一个存在的根目录解析（用于项目包内的相对引用）。
    - 符号链接会被 `resolve()` 展开后再做归属检查，因此指向根目录外部的链接会被拒绝。
    - 跨平台路径：`C:\\x`、`\\\\server\\share` 在 POSIX 上不会被当成相对路径。
    """
    if value is None or (isinstance(value, str) and not value.strip()):
        raise _reject(f"{label} 不能为空", code="empty_path")

    raw = str(value).strip().replace("\x00", "")
    normalized_roots = [Path(root).expanduser() for root in roots]
    normalized_roots = [root for root in normalized_roots if str(root)]
    if not normalized_roots:
        raise _reject(f"{label} 没有可用的允许根目录", code="no_allowed_roots")

    resolved_roots: list[Path] = []
    for root in normalized_roots:
        try:
            resolved_roots.append(root.resolve())
        except OSError:
            continue
    if not resolved_roots:
        raise _reject(f"{label} 的允许根目录不可用", code="no_allowed_roots")

    candidate = _interpret_path(raw)
    if candidate is None:
        raise _reject(f"{label} 含非法路径格式", code="malformed_path")

    if not candidate.is_absolute():
        # 相对路径：优先取第一个自身存在候选的根，否则用第一个根。
        resolved = None
        fallback_root = resolved_roots[0]
        for root in resolved_roots:
            probe = root / candidate
            if probe.exists():
                fallback_root = root
                resolved = probe
                break
        candidate = resolved if resolved is not None else fallback_root / candidate

    try:
        final = candidate.resolve()
    except OSError as exc:
        raise _reject(f"{label} 无法解析: {exc}", code="unresolvable_path") from exc

    if not allow_symlink and candidate.is_symlink():
        raise _reject(f"{label} 不允许符号链接", code="symlink_rejected")

    if not any(_is_within(final, root) for root in resolved_roots):
        raise _reject(f"{label} 超出允许的目录范围", code="outside_allowed_roots")

    if must_exist and not final.exists():
        raise _reject(f"{label} 不存在", code="missing_path")

    return final


def _interpret_path(raw: str) -> Path | None:
    """把字符串解释为本地路径。

    跨平台防护：Windows 盘符路径（`C:\\x`）与 UNC 路径（`\\\\server\\share`）在当前平台
    无法表示，也不能被当成相对路径拼到项目根下——直接判定为「不属于任何允许根目录」。
    """
    if re.match(r"^[A-Za-z]:[\\/]", raw) or raw.startswith("\\\\"):
        raise _reject(f"路径使用了当前平台不支持的绝对路径格式: {raw}", code="cross_platform_path")
    if raw.startswith(("/", "\\")):
        return Path(raw.replace("\\", "/")) if raw.startswith("\\") else Path(raw)
    if raw.startswith("~"):
        return Path(raw).expanduser()
    # 兜底：反斜杠既可能是 Windows 分隔符，也可能是误用；按分隔符规范化后再判定
    if "\\" in raw:
        normalized = raw.replace("\\", "/")
        if normalized.startswith("/") or ".." in normalized.split("/"):
            raise _reject(f"路径含非法分隔符或上级引用: {raw}", code="cross_platform_path")
        return Path(normalized)
    if raw in {".", "./"}:
        return Path(".")
    return Path(raw)


def _is_within(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
        return True
    except ValueError:
        return False


def ensure_within_roots(path: Path, roots: Iterable[str | Path], *, label: str = "路径") -> Path:
    """对一个已经是 Path 的值做归属校验（用于服务端已解析出的路径复查）。"""
    return resolve_within_roots(path, roots, label=label)


def is_within_roots(path: Path | str, roots: Iterable[str | Path]) -> bool:
    try:
        resolve_within_roots(path, roots, label="路径")
        return True
    except PathPolicyError:
        return False


def iter_unique_paths(values: Iterable[Any]) -> list[Path]:
    """把一组候选值解析为去重后的绝对路径（忽略不可解析项）。"""
    seen: list[Path] = []
    for value in values:
        if not value:
            continue
        try:
            resolved = Path(str(value)).expanduser().resolve()
        except OSError:
            continue
        if resolved not in seen:
            seen.append(resolved)
    return seen
