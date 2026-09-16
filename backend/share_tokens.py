"""作用域分享令牌：把静态导出分享给**未认证**访问者，同时不泄露主令牌。

设计约束（对应任务要求 7）：
- 分享令牌与主访问令牌**完全独立**，由密码学随机数生成，无法从主令牌推导，也不能用于任何 API。
- **作用域限定到具体导出目录**：令牌只对 `/exports/<项目>/<导出文件…>` 生效；
  访问其他项目、其他导出或任何 `/api/*` 一律拒绝。
- **可过期、可撤销**：默认有效期由 `CAD_SHARE_TTL_HOURS` 控制（默认 24 小时），
  过期的记录在解析时被清理；`revoke_share_tokens()` 可按项目撤销。
- 令牌**只**出现在分享链接的查询串里；不写入日志、不写入导出内容、不写入项目元数据。
"""

from __future__ import annotations

import contextlib
import json
import os
import re
import secrets
import threading
import time
from pathlib import Path
from typing import Any
from urllib.parse import quote, unquote

from path_policy import is_safe_id, sanitize_filename

DEFAULT_TTL_HOURS = 24.0
STORE_FILENAME = "share-tokens.json"
EXPORTS_PREFIX = "/exports"


class ShareTokenError(ValueError):
    """分享令牌无法签发（通常是参数非法）。"""


def share_tokens_path() -> Path:
    """令牌存储位置：默认在运行期目录下，随 `CAD_RUNTIME_ROOT` 走。"""
    override = os.environ.get("CAD_SHARE_TOKENS_PATH")
    if override:
        return Path(override).expanduser()
    import storage

    return Path(storage.RUNTIME_ROOT) / "share" / STORE_FILENAME


def share_ttl_seconds() -> float:
    raw = os.environ.get("CAD_SHARE_TTL_HOURS")
    try:
        hours = float(raw) if raw else DEFAULT_TTL_HOURS
    except ValueError:
        hours = DEFAULT_TTL_HOURS
    if hours <= 0:
        hours = DEFAULT_TTL_HOURS
    return hours * 3600.0


def _load_store() -> dict[str, Any]:
    path = share_tokens_path()
    if not path.exists():
        return {"version": 1, "tokens": []}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {"version": 1, "tokens": []}
    if not isinstance(data, dict) or not isinstance(data.get("tokens"), list):
        return {"version": 1, "tokens": []}
    return data


def _save_store(data: dict[str, Any]) -> None:
    path = share_tokens_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(tmp, path)


def _prune(tokens: list[dict[str, Any]], now: float | None = None) -> tuple[list[dict[str, Any]], bool]:
    """清理过期记录，返回 (保留列表, 是否有变化)。"""
    current = time.time() if now is None else now
    kept: list[dict[str, Any]] = []
    changed = False
    for item in tokens:
        if not isinstance(item, dict):
            changed = True
            continue
        try:
            expires_at = float(item.get("expires_at") or 0)
        except (TypeError, ValueError):
            changed = True
            continue
        if expires_at and expires_at > current:
            kept.append(item)
        else:
            changed = True
    return kept, changed


def normalize_export_prefix(project_id: Any, export_relpath: Any) -> str:
    """把项目 ID 与导出相对路径收敛为受作用域保护的 URL 前缀。

    支持 `/exports/<项目>/<导出相对路径>` 这类多级布局（实际导出位于
    `exports/static-pages/<项目>/<文件>.html`），但**不接受**任何上级引用，
    且每一段都经过文件名收敛。
    """
    if not is_safe_id(str(project_id or "")):
        raise ShareTokenError(f"项目 ID 非法: {project_id!r}")
    raw = str(export_relpath or "").strip().lstrip("/")
    if not raw:
        raise ShareTokenError("导出路径不能为空")
    parts = [part for part in raw.split("/") if part not in {"", "."}]
    if not parts or any(part == ".." for part in parts):
        raise ShareTokenError("导出路径不能包含上级引用")
    safe_parts = [sanitize_filename(part, fallback="export") for part in parts]
    if not safe_parts[-1].lower().endswith(".html"):
        safe_parts[-1] = f"{safe_parts[-1]}.html"
    # 直接采用真实的磁盘相对路径（例如 `static-pages/<项目ID>/<文件>.html`），
    # 不再额外插入项目 ID，避免作用域与实际访问路径不一致。
    return f"{EXPORTS_PREFIX}/{'/'.join(safe_parts)}"


def issue_share_token(*, project_id: Any, export_path: Any, drawing_id: Any = None, ttl_seconds: float | None = None) -> dict[str, Any]:
    """签发一个作用域分享令牌。返回记录（含 `token` 与 `path_prefix`）。"""
    path_prefix = normalize_export_prefix(project_id, export_path)
    token = secrets.token_urlsafe(24)
    now = time.time()
    ttl = share_ttl_seconds() if ttl_seconds is None else float(ttl_seconds)
    record = {
        "token": token,
        "path_prefix": path_prefix,
        "project_id": str(project_id),
        "drawing_id": str(drawing_id) if drawing_id else None,
        "issued_at": now,
        "expires_at": now + ttl,
    }
    with _store_lock():
        store = _load_store()
        tokens, _ = _prune(store.get("tokens") or [])
        tokens.append(record)
        store["tokens"] = tokens
        _save_store(store)
    return record


def _path_variants(value: Any) -> set[str]:
    """同一路径的候选写法：原始、解码后、编码后。

    导出文件名可能包含中文等非 ASCII 字符。不同层对编码的处理并不一致：
    ASGI 传给应用的 `path` 通常是百分号编码的串，而磁盘上的真实文件名是解码后的；
    浏览器、分享链接与静态挂载点又各自可能保留或去掉编码。因此作用域比较
    必须同时接受编码与解码两种形式，否则合法分享链接会被误判为越界（或反向漏判）。
    """
    raw = str(value or "")
    variants = {raw, unquote(raw), quote(unquote(raw), safe="/")}
    normalized: set[str] = set()
    for item in variants:
        collapsed = re.sub(r"/{2,}", "/", item)
        normalized.add(collapsed.rstrip("/"))
    return {item for item in normalized if item}


def resolve_share_token(token: Any, request_path: Any) -> dict[str, Any] | None:
    """校验分享令牌是否对该请求路径有效。无效返回 None（不抛异常）。"""
    if not token:
        return None
    candidate = str(token).strip()
    if not candidate:
        return None
    target_variants = _path_variants(request_path)

    with _store_lock():
        store = _load_store()
        tokens, changed = _prune(store.get("tokens") or [])
        if changed:
            store["tokens"] = tokens
            with contextlib.suppress(OSError):
                _save_store(store)

    for item in tokens:
        stored = str(item.get("token") or "")
        if not stored or not secrets.compare_digest(stored, candidate):
            continue
        prefix_variants = _path_variants(item.get("path_prefix"))
        if not prefix_variants:
            continue
        # 作用域判定：请求必须位于该导出文件/目录之下（编码/解码任一形式匹配即可）
        matched = any(
            target == prefix or target.startswith(f"{prefix}/")
            for target in target_variants
            for prefix in prefix_variants
        )
        if matched:
            return {
                "project_id": item.get("project_id"),
                "drawing_id": item.get("drawing_id"),
                "path_prefix": item.get("path_prefix"),
                "expires_at": item.get("expires_at"),
            }
        return None
    return None


def revoke_share_tokens(project_id: Any | None = None) -> int:
    """撤销分享令牌：给出项目 ID 时只撤销该项目，否则全部撤销。返回撤销数量。"""
    with _store_lock():
        store = _load_store()
        tokens = [item for item in (store.get("tokens") or []) if isinstance(item, dict)]
        if project_id is None:
            store["tokens"] = []
            removed = len(tokens)
        else:
            target = str(project_id)
            kept = [item for item in tokens if str(item.get("project_id")) != target]
            removed = len(tokens) - len(kept)
            store["tokens"] = kept
        _save_store(store)
    return removed


def list_share_tokens(project_id: Any | None = None) -> list[dict[str, Any]]:
    """列出有效令牌的安全字段（**不含 token 本身**）。"""
    store = _load_store()
    tokens, _ = _prune(store.get("tokens") or [])
    result = []
    for item in tokens:
        if project_id is not None and str(item.get("project_id")) != str(project_id):
            continue
        result.append(
            {
                "project_id": item.get("project_id"),
                "drawing_id": item.get("drawing_id"),
                "path_prefix": item.get("path_prefix"),
                "issued_at": item.get("issued_at"),
                "expires_at": item.get("expires_at"),
            }
        )
    return result


#: 令牌存储是低写入频率的小文件，进程内互斥即可。
_STORE_LOCK = threading.RLock()


@contextlib.contextmanager
def _store_lock():
    with _STORE_LOCK:
        yield


def share_url(base_origin: str, path_prefix: str, token: str) -> str:
    """构造带作用域令牌的分享链接。"""
    origin = str(base_origin or "").rstrip("/")
    return f"{origin}{path_prefix}?share={quote(str(token), safe='')}"


__all__ = [
    "DEFAULT_TTL_HOURS",
    "ShareTokenError",
    "issue_share_token",
    "list_share_tokens",
    "normalize_export_prefix",
    "resolve_share_token",
    "revoke_share_tokens",
    "share_ttl_seconds",
    "share_tokens_path",
    "share_url",
]
