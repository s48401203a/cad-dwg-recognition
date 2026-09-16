"""访问控制：本地优先的 Host/Origin/CSRF 校验与可选令牌鉴权。

威胁模型（本工具是**本机单用户工具**，不是公网服务）：
- 任意网页在用户浏览器里对本机端口发起跨源请求（CSRF / DNS rebinding），
  进而读写项目、导出文件、调用打开文件等本地能力。
- 局域网内其他设备直接访问未鉴权的管理接口。

对策：
1. 默认只监听回环地址；绑定非回环地址必须显式开启局域网模式 **并** 设置访问令牌。
2. 浏览器来源的请求执行同源判定：`Origin`/`Referer` 必须与请求 `Host` 一致，
   或落在显式配置的开发来源（`CAD_DEV_ORIGINS`，如 Vite `http://127.0.0.1:5173`）。
3. 无 `Origin` 的非浏览器客户端（curl/脚本）允许，但受 Host 校验与可选令牌约束。
4. `Host` 头必须是回环地址、本机绑定地址或显式配置的主机名，防 DNS rebinding。
5. 令牌一旦配置，所有写操作与管理接口都需要它；只读预览接口保持开放，
   以便 `GET /api/health` 之类的探活与浏览器首屏不被阻断。
"""

from __future__ import annotations

import hmac
import ipaddress
import os
import secrets
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import urlsplit

LOOPBACK_HOSTS = {"127.0.0.1", "localhost", "::1", "[::1]"}

# 写操作 / 管理接口：一旦配置令牌，这些路径需要鉴权。
PROTECTED_PREFIXES = (
    "/api/upload",
    "/api/parse",
    "/api/project-packages/import",
    "/api/replay/start",
)
PROTECTED_METHODS = {"POST", "PUT", "PATCH", "DELETE"}


class AccessDenied(RuntimeError):
    """访问被拒绝。`status_code` 供 HTTP 层使用。"""

    def __init__(self, message: str, *, status_code: int = 403, code: str = "access_denied") -> None:
        super().__init__(message)
        self.status_code = status_code
        self.code = code


@dataclass
class AccessPolicy:
    """从环境变量解析出的运行期访问策略。"""

    host: str = "127.0.0.1"
    token: str | None = None
    token_required: bool = False
    dev_origins: set[str] = field(default_factory=set)
    allowed_hosts: set[str] = field(default_factory=set)
    trust_proxy: bool = False

    @property
    def lan_enabled(self) -> bool:
        return not _is_loopback_host(self.host)

    def describe(self) -> dict[str, Any]:
        return {
            "bind_host": self.host,
            "lan_enabled": self.lan_enabled,
            "token_required": self.token_required,
            "dev_origins": sorted(self.dev_origins),
            "allowed_hosts": sorted(self.allowed_hosts),
        }


def _is_loopback_host(host: str) -> bool:
    value = (host or "").strip().strip("[]").lower()
    if value in {"localhost", ""}:
        return True
    try:
        return ipaddress.ip_address(value).is_loopback
    except ValueError:
        return False


def _truthy(value: str | None) -> bool:
    return str(value or "").strip().lower() in {"1", "true", "yes", "on"}


def _split_list(value: str | None) -> set[str]:
    if not value:
        return set()
    return {item.strip().rstrip("/").lower() for item in value.split(",") if item.strip()}


def generate_token() -> str:
    return secrets.token_urlsafe(24)


def load_access_policy(env: dict[str, str] | None = None) -> AccessPolicy:
    """从环境变量构造访问策略。

    - `CAD_HOST`：绑定地址，默认 `127.0.0.1`。
    - `CAD_LAN_MODE`：显式开启局域网模式（非回环绑定）。
    - `CAD_ACCESS_TOKEN`：访问令牌；局域网模式下必须设置。
    - `CAD_DEV_ORIGINS`：允许的额外浏览器来源，逗号分隔（默认包含 Vite 常见端口）。
    - `CAD_ALLOWED_HOSTS`：允许的额外 Host 头。
    - `CAD_TOKEN_REQUIRED`：即使在回环模式下也强制令牌。
    """
    source = dict(os.environ if env is None else env)
    host = (source.get("CAD_HOST") or "127.0.0.1").strip() or "127.0.0.1"
    if _truthy(source.get("CAD_LAN_MODE")) and _is_loopback_host(host):
        host = "0.0.0.0"

    token = (source.get("CAD_ACCESS_TOKEN") or "").strip() or None
    lan = not _is_loopback_host(host)

    dev_origins = _split_list(source.get("CAD_DEV_ORIGINS"))
    if not dev_origins:
        # Vite 开发代理的默认来源；用户可以覆盖为空以外任何值。
        dev_origins = {
            "http://127.0.0.1:5173",
            "http://localhost:5173",
            "http://127.0.0.1:5174",
            "http://localhost:5174",
        }

    allowed_hosts = _split_list(source.get("CAD_ALLOWED_HOSTS"))

    if lan and not token:
        raise AccessDenied(
            "局域网模式必须设置访问令牌：请设置 CAD_ACCESS_TOKEN（或用 start.sh --lan 自动生成）后再绑定非回环地址",
            status_code=500,
            code="lan_requires_token",
        )

    return AccessPolicy(
        host=host,
        token=token,
        token_required=bool(token) or lan or _truthy(source.get("CAD_TOKEN_REQUIRED")),
        dev_origins=dev_origins,
        allowed_hosts=allowed_hosts,
        trust_proxy=_truthy(source.get("CAD_TRUST_PROXY")),
    )


_POLICY: AccessPolicy | None = None
_POLICY_ENV_KEYS = (
    "CAD_HOST",
    "CAD_LAN_MODE",
    "CAD_ACCESS_TOKEN",
    "CAD_DEV_ORIGINS",
    "CAD_ALLOWED_HOSTS",
    "CAD_TOKEN_REQUIRED",
    "CAD_TRUST_PROXY",
)
_POLICY_FINGERPRINT: tuple[str, ...] | None = None


def _env_fingerprint() -> tuple[str, ...]:
    return tuple(os.environ.get(key, "") for key in _POLICY_ENV_KEYS)


def current_policy() -> AccessPolicy:
    """读取当前策略；环境变量变化后自动重新加载（便于 CLI 先设令牌再导入应用）。"""
    global _POLICY, _POLICY_FINGERPRINT
    fingerprint = _env_fingerprint()
    if _POLICY is None or _POLICY_FINGERPRINT != fingerprint:
        _POLICY = load_access_policy()
        _POLICY_FINGERPRINT = fingerprint
    return _POLICY


def set_policy(policy: AccessPolicy | None) -> None:
    """测试用：注入策略并清空缓存。"""
    global _POLICY, _POLICY_FINGERPRINT
    _POLICY = policy
    _POLICY_FINGERPRINT = None if policy is None else _env_fingerprint()


# ---------------------------------------------------------------- 判定


def host_header_allowed(host_header: str | None, policy: AccessPolicy | None = None) -> bool:
    """Host 头是否可接受（防 DNS rebinding）。"""
    policy = policy or current_policy()
    if not host_header:
        return True  # HTTP/1.0 或已由 ASGI 服务器补全
    hostname = _hostname_of(host_header)
    if not hostname:
        return False
    if _is_loopback_host(hostname):
        return True
    if hostname in policy.allowed_hosts:
        return True
    if policy.lan_enabled:
        # 局域网模式下允许绑定地址本身与常见私有网段字面量
        if hostname in {policy.host.strip("[]"), "0.0.0.0"}:
            return True
        try:
            address = ipaddress.ip_address(hostname)
        except ValueError:
            return False
        return address.is_private
    return False


def origin_allowed(origin: str | None, host_header: str | None, policy: AccessPolicy | None = None) -> bool:
    """浏览器来源是否为同源或显式允许的开发来源。"""
    policy = policy or current_policy()
    if not origin:
        return True
    normalized = origin.strip().rstrip("/").lower()
    if normalized in {"null", "file://"}:
        return False
    if normalized in policy.dev_origins:
        return True
    return _origin_matches_host(normalized, host_header)


def _hostname_of(value: str) -> str:
    text = (value or "").strip()
    if not text:
        return ""
    if "//" in text:
        text = urlsplit(text).netloc or urlsplit(text).hostname or ""
    if text.startswith("["):
        end = text.find("]")
        return text[1:end].lower() if end > 0 else ""
    return text.split(":")[0].strip().lower()


def _port_of(value: str) -> str | None:
    text = (value or "").strip()
    if "//" in text:
        parsed = urlsplit(text)
        return str(parsed.port) if parsed.port else None
    if text.startswith("["):
        end = text.find("]")
        remainder = text[end + 1 :] if end > 0 else ""
        return remainder.lstrip(":").strip() or None
    if text.count(":") == 1:
        return text.split(":")[1].strip() or None
    return None


def _origin_matches_host(origin: str, host_header: str | None) -> bool:
    if not host_header:
        return False
    origin_host = _hostname_of(origin)
    host_host = _hostname_of(host_header)
    if not origin_host or not host_host:
        return False
    if origin_host != host_host:
        return False
    origin_port = _normalize_port(_port_of(origin) or ("443" if origin.startswith("https://") else "80"))
    host_port = _normalize_port(_port_of(host_header))
    return origin_port == host_port


def _normalize_port(value: str | None) -> str | None:
    """把默认端口折叠为 None，使 `http://127.0.0.1` 与 `http://127.0.0.1:80` 视为同源。"""
    if value is None:
        return None
    text = str(value).strip()
    if text in {"", "80", "443"}:
        return None
    return text


def token_matches(candidate: str | None, policy: AccessPolicy | None = None) -> bool:
    policy = policy or current_policy()
    if not policy.token:
        return False
    if not candidate:
        return False
    return hmac.compare_digest(str(candidate), policy.token)


def extract_token(headers: Any, cookies: Any = None) -> str | None:
    """从 `Authorization: Bearer`、`X-CAD-Token`、`?token=` 或 cookie 取令牌。"""
    try:
        auth = headers.get("authorization") or headers.get("Authorization")
    except Exception:
        auth = None
    if auth:
        parts = str(auth).split(None, 1)
        if len(parts) == 2 and parts[0].lower() == "bearer":
            return parts[1].strip()
    try:
        direct = headers.get("x-cad-token") or headers.get("X-CAD-Token")
    except Exception:
        direct = None
    if direct:
        return str(direct).strip()
    if cookies:
        try:
            value = cookies.get("cad_token")
        except Exception:
            value = None
        if value:
            return str(value).strip()
    return None


def requires_token(method: str, path: str, policy: AccessPolicy | None = None) -> bool:
    """该请求是否需要令牌。"""
    policy = policy or current_policy()
    if not policy.token_required:
        return False
    if not policy.token:
        # 局域网模式下未配置令牌已在 load_access_policy 阶段拒绝启动
        return False
    upper = (method or "GET").upper()
    if upper in PROTECTED_METHODS:
        return True
    return any(path.startswith(prefix) for prefix in PROTECTED_PREFIXES)


def check_request(
    *,
    method: str,
    path: str,
    headers: Any,
    query_token: str | None = None,
    cookies: Any = None,
    policy: AccessPolicy | None = None,
) -> None:
    """HTTP 入口统一检查。不通过则抛 AccessDenied。"""
    policy = policy or current_policy()
    host_header = _get_header(headers, "host")
    origin = _get_header(headers, "origin")
    referer = _get_header(headers, "referer")

    if not host_header_allowed(host_header, policy):
        raise AccessDenied(f"Host 头不被允许: {host_header}", code="host_not_allowed")

    # 浏览器来源校验：跨源写请求一律拒绝；跨源读请求同样拒绝，避免被任何网页探测本地项目。
    if origin and not origin_allowed(origin, host_header, policy):
        raise AccessDenied(f"来源不被允许: {origin}", code="origin_not_allowed")

    if not origin and referer:
        referer_origin = _origin_of(referer)
        if referer_origin and not origin_allowed(referer_origin, host_header, policy):
            raise AccessDenied(f"来源不被允许: {referer_origin}", code="origin_not_allowed")

    if requires_token(method, path, policy):
        candidate = query_token or extract_token(headers, cookies)
        if not token_matches(candidate, policy):
            raise AccessDenied("缺少或错误的访问令牌", status_code=401, code="token_required")


def check_websocket(
    *,
    path: str,
    headers: Any,
    query_token: str | None = None,
    cookies: Any = None,
    policy: AccessPolicy | None = None,
) -> None:
    """WebSocket 握手检查：同一套 Host/Origin 规则，并在配置令牌时要求令牌。"""
    policy = policy or current_policy()
    host_header = _get_header(headers, "host")
    origin = _get_header(headers, "origin")
    if not host_header_allowed(host_header, policy):
        raise AccessDenied(f"WebSocket Host 头不被允许: {host_header}", code="host_not_allowed")
    if origin and not origin_allowed(origin, host_header, policy):
        raise AccessDenied(f"WebSocket 来源不被允许: {origin}", code="origin_not_allowed")
    if policy.token and policy.token_required:
        candidate = query_token or extract_token(headers, cookies)
        if not token_matches(candidate, policy):
            raise AccessDenied("WebSocket 缺少或错误的访问令牌", status_code=401, code="token_required")


def _origin_of(url: str) -> str | None:
    parsed = urlsplit(url)
    if not parsed.scheme or not parsed.netloc:
        return None
    return f"{parsed.scheme}://{parsed.netloc}".lower()


def _get_header(headers: Any, name: str) -> str | None:
    if headers is None:
        return None
    try:
        value = headers.get(name)
    except Exception:
        return None
    return str(value) if value else None


__all__ = [
    "AccessDenied",
    "AccessPolicy",
    "PROTECTED_PREFIXES",
    "check_request",
    "check_websocket",
    "current_policy",
    "extract_token",
    "generate_token",
    "host_header_allowed",
    "load_access_policy",
    "origin_allowed",
    "requires_token",
    "set_policy",
    "token_matches",
]
