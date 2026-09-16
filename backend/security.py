"""访问控制：默认拒绝 + 显式匿名白名单。

威胁模型（本工具是**本机/局域网单用户工具**，不是公网服务）：
- 在配置了访问令牌（或启用局域网模式）后，未经认证的访问者不得**枚举、读取或导出**项目与图纸内容；
  包括项目列表/详情/语义数据/模型覆盖/项目包、导出接口、静态导出文件、日志与 WebSocket。
- 任意网页在用户浏览器里对本机端口发起跨源请求（CSRF / DNS rebinding）。
- 局域网内其他设备直接访问未鉴权的管理接口。

设计要点：
1. **默认拒绝**：`/api/**` 一律需要令牌，只有显式列入 `PUBLIC_API_PATHS` 的少数只读入口匿名放行。
2. 前端外壳（`/`、`index.html`、`*.js`、`*.css`、`/vendor/**`、`/share-config.js`）必须匿名可取，
   否则未认证用户连登录界面都拿不到；这些文件本身来自公开仓库，不含任何项目内容。
3. `/exports/**` 始终需要认证（主令牌或**作用域分享令牌**，见 `share_tokens.py`）。
4. **Host / Origin / CORS 不是身份认证**：无 `Origin` 的脚本客户端同样受令牌约束。
5. 未配置令牌时（默认回环本机使用）行为不变，保持零摩擦。
"""

from __future__ import annotations

import hmac
import ipaddress
import os
import re
import secrets
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

LOOPBACK_HOSTS = {"127.0.0.1", "localhost", "::1", "[::1]"}

#: 允许匿名访问的 API 路径（精确匹配）。只放行不泄露项目内容的只读入口与认证入口。
PUBLIC_API_PATHS = frozenset(
    {
        "/api/health",
        "/api/auth/session",
        "/api/auth/login",
        "/api/auth/logout",
    }
)

#: 允许匿名访问的公开前端资源（正则匹配整条路径）。
PUBLIC_ASSET_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"^/$"),
    re.compile(r"^/[A-Za-z0-9._-]+\.html$"),
    re.compile(r"^/share-config\.js$"),
    re.compile(r"^/(?:js|css)/[A-Za-z0-9._/-]+\.(?:js|css)$"),
    re.compile(r"^/vendor/[A-Za-z0-9._/-]+\.(?:js|mjs|css|woff2?|ttf|png|jpg|svg)$"),
)

#: 导出挂载点前缀：始终需要认证（主令牌或作用域分享令牌）。
EXPORTS_PREFIX = "/exports"

#: 需要路由到应用而非静态前端的路径前缀。
API_PREFIX = "/api"

#: 写方法（保留导出，供旧调用方引用）。
PROTECTED_METHODS = frozenset({"POST", "PUT", "PATCH", "DELETE"})

#: 兼容旧名字：现在这些前缀已包含在"默认拒绝"里。
PROTECTED_PREFIXES = ("/api/", EXPORTS_PREFIX)

#: 会话 cookie 名称。HttpOnly，不参与 JS 读取。
SESSION_COOKIE = "cad_session"


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

    @property
    def auth_enabled(self) -> bool:
        """是否需要认证。为假时（默认回环、未配置令牌）保持零摩擦的本地体验。"""
        return bool(self.token) and self.token_required

    def describe(self) -> dict[str, Any]:
        return {
            "bind_host": self.host,
            "lan_enabled": self.lan_enabled,
            "token_required": self.token_required,
            "auth_enabled": self.auth_enabled,
            "dev_origins": sorted(self.dev_origins),
            "allowed_hosts": sorted(self.allowed_hosts),
        }


@dataclass
class AccessDecision:
    """一次请求的访问判定结果。"""

    allowed: bool
    auth: str = "none"  # none | token | share_token | local
    needs_auth: bool = False
    reason: str | None = None
    scope_path: str | None = None


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
    token_required_flag = _truthy(source.get("CAD_TOKEN_REQUIRED"))

    dev_origins = _split_list(source.get("CAD_DEV_ORIGINS"))
    if not dev_origins:
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
    if token_required_flag and not token:
        raise AccessDenied(
            "已设置 CAD_TOKEN_REQUIRED 但未提供 CAD_ACCESS_TOKEN：请设置令牌，或移除 CAD_TOKEN_REQUIRED",
            status_code=500,
            code="token_required_without_token",
        )

    return AccessPolicy(
        host=host,
        token=token,
        token_required=bool(token) or lan or token_required_flag,
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
    """读取当前策略；环境变量变化后自动重新加载。"""
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


# ---------------------------------------------------------------- 匿名白名单


def is_public_asset(path: str) -> bool:
    """是否为可匿名获取的公开前端资源（登录界面本身必须能加载）。"""
    candidate = path or "/"
    if candidate.startswith(EXPORTS_PREFIX):
        # 导出目录永远不匿名：它承载项目内容。
        return False
    return any(pattern.match(candidate) for pattern in PUBLIC_ASSET_PATTERNS)


def is_public_api(path: str) -> bool:
    """是否为可匿名访问的 API 入口（精确匹配，避免前缀绕过）。"""
    return (path or "").rstrip("/") in PUBLIC_API_PATHS or (path or "") in PUBLIC_API_PATHS


def requires_auth(method: str, path: str, policy: AccessPolicy | None = None) -> bool:
    """该请求是否需要认证。未启用认证时一律返回 False（默认回环本机体验）。"""
    policy = policy or current_policy()
    if not policy.auth_enabled:
        return False
    candidate = path or "/"
    if candidate.startswith(EXPORTS_PREFIX):
        return True
    if is_public_api(candidate):
        return False
    if candidate.startswith(API_PREFIX):
        # 默认拒绝：/api 下除白名单外全部需要认证（含 GET 读接口）。
        return True
    if is_public_asset(candidate):
        return False
    # 非 /api、非导出、非公开前端资源：保守起见需要认证。
    return True


def requires_token(method: str, path: str, policy: AccessPolicy | None = None) -> bool:
    """兼容旧签名：等价于 `requires_auth`。"""
    return requires_auth(method, path, policy)


# ---------------------------------------------------------------- 令牌提取


def extract_token(headers: Any, cookies: Any = None, query_token: str | None = None) -> str | None:
    """从 `Authorization: Bearer`、`X-CAD-Token`、会话 cookie 或 `?token=` 取令牌。

    注意：返回的是调用方提供的凭据，**不得**写入日志或响应体。
    """
    if query_token:
        return str(query_token).strip()
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
        for name in (SESSION_COOKIE, "cad_token"):
            try:
                value = cookies.get(name)
            except Exception:
                value = None
            if value:
                return str(value).strip()
    return None


def token_matches(candidate: str | None, policy: AccessPolicy | None = None) -> bool:
    policy = policy or current_policy()
    if not policy.token:
        return False
    if not candidate:
        return False
    return hmac.compare_digest(str(candidate), policy.token)


# ---------------------------------------------------------------- Host / Origin

def host_header_allowed(host_header: str | None, policy: AccessPolicy | None = None) -> bool:
    """Host 头是否可接受（防 DNS rebinding）。"""
    policy = policy or current_policy()
    if not host_header:
        return True
    hostname = _hostname_of(host_header)
    if not hostname:
        return False
    if _is_loopback_host(hostname):
        return True
    if hostname in policy.allowed_hosts:
        return True
    if policy.lan_enabled:
        if hostname in {policy.host.strip("[]"), "0.0.0.0"}:
            return True
        try:
            address = ipaddress.ip_address(hostname)
        except ValueError:
            return False
        return address.is_private
    return False


def origin_allowed(origin: str | None, host_header: str | None, policy: AccessPolicy | None = None) -> bool:
    """浏览器来源是否为同源或显式允许的开发来源。

    这只防 CSRF，**不是**身份认证：无 Origin 的脚本客户端仍受令牌约束。
    """
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


# ---------------------------------------------------------------- 统一检查


def check_request(
    *,
    method: str,
    path: str,
    headers: Any,
    query_token: str | None = None,
    cookies: Any = None,
    policy: AccessPolicy | None = None,
    scoped_token_allowed: bool = False,
) -> AccessDecision:
    """HTTP 入口统一检查。不通过则抛 `AccessDenied`。

    `scoped_token_allowed=True` 用于 `/exports/**`：允许作用域分享令牌，
    但作用域校验由调用方（`authorize_export_request`）完成。
    """
    policy = policy or current_policy()
    host_header = _get_header(headers, "host")
    origin = _get_header(headers, "origin")
    referer = _get_header(headers, "referer")

    if not host_header_allowed(host_header, policy):
        raise AccessDenied(f"Host 头不被允许: {host_header}", code="host_not_allowed")

    # CSRF：浏览器来源必须同源或显式允许。无 Origin 的脚本客户端不走这条分支，
    # 但其身份仍由下面的令牌检查决定。
    if origin and not origin_allowed(origin, host_header, policy):
        raise AccessDenied(f"来源不被允许: {origin}", code="origin_not_allowed")

    if not origin and referer:
        referer_origin = _origin_of(referer)
        if referer_origin and not origin_allowed(referer_origin, host_header, policy):
            raise AccessDenied(f"来源不被允许: {referer_origin}", code="origin_not_allowed")

    if not requires_auth(method, path, policy):
        return AccessDecision(allowed=True, auth="none")

    candidate = extract_token(headers, cookies, query_token)
    if token_matches(candidate, policy):
        return AccessDecision(allowed=True, auth="token")

    if scoped_token_allowed:
        # 交给调用方用作用域校验；这里只表示"凭据可能可以接受"。
        return AccessDecision(allowed=True, auth="deferred", needs_auth=True, scope_path=path)

    raise AccessDenied("需要访问令牌：请先登录或在请求中携带令牌", status_code=401, code="auth_required")


def check_websocket(
    *,
    path: str,
    headers: Any,
    query_token: str | None = None,
    cookies: Any = None,
    policy: AccessPolicy | None = None,
) -> None:
    """WebSocket 握手检查：同一套 Host/Origin/令牌规则。"""
    policy = policy or current_policy()
    host_header = _get_header(headers, "host")
    origin = _get_header(headers, "origin")
    if not host_header_allowed(host_header, policy):
        raise AccessDenied(f"WebSocket Host 头不被允许: {host_header}", code="host_not_allowed")
    if origin and not origin_allowed(origin, host_header, policy):
        raise AccessDenied(f"WebSocket 来源不被允许: {origin}", code="origin_not_allowed")
    if policy.auth_enabled:
        candidate = extract_token(headers, cookies, query_token)
        if not token_matches(candidate, policy):
            raise AccessDenied("WebSocket 需要访问令牌", status_code=401, code="auth_required")


def authorize_export_request(
    *,
    path: str,
    headers: Any,
    query_token: str | None = None,
    cookies: Any = None,
    policy: AccessPolicy | None = None,
) -> AccessDecision:
    """`/exports/**` 的授权：主令牌，或作用域限于该导出目录的分享令牌。"""
    policy = policy or current_policy()
    if not policy.auth_enabled:
        return AccessDecision(allowed=True, auth="local")

    candidate = extract_token(headers, cookies, query_token)
    if token_matches(candidate, policy):
        return AccessDecision(allowed=True, auth="token")

    if candidate:
        from share_tokens import resolve_share_token

        record = resolve_share_token(candidate, path)
        if record:
            return AccessDecision(allowed=True, auth="share_token", scope_path=record.get("path_prefix"))

    raise AccessDenied("导出文件需要访问令牌或有效的分享链接", status_code=401, code="auth_required")


def public_health_payload(payload: dict[str, Any], *, authenticated: bool) -> dict[str, Any]:
    """`/api/health` 的内容分级：匿名只给非敏感探活信息。"""
    if authenticated:
        return payload
    return {
        "ok": payload.get("ok", True),
        "auth_required": bool(payload.get("auth_required")),
        "authenticated": False,
        "capabilities": {
            name: {"available": bool(info.get("available"))}
            for name, info in (payload.get("capabilities") or {}).items()
            if isinstance(info, dict)
        },
    }


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
    "AccessDecision",
    "AccessDenied",
    "AccessPolicy",
    "API_PREFIX",
    "EXPORTS_PREFIX",
    "PROTECTED_METHODS",
    "PROTECTED_PREFIXES",
    "PUBLIC_API_PATHS",
    "PUBLIC_ASSET_PATTERNS",
    "SESSION_COOKIE",
    "authorize_export_request",
    "check_request",
    "check_websocket",
    "current_policy",
    "extract_token",
    "generate_token",
    "host_header_allowed",
    "is_public_api",
    "is_public_asset",
    "load_access_policy",
    "origin_allowed",
    "public_health_payload",
    "requires_auth",
    "requires_token",
    "set_policy",
    "token_matches",
]
