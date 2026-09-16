"""认证入口：会话探测、登录、登出。

设计：主访问令牌本身即凭据。登录成功后写一个 HttpOnly 会话 cookie，
使浏览器后续的 API 调用、`/exports/**` 静态文件请求与 WebSocket 都能通过校验，
而不需要把令牌暴露在 URL 或前端可读存储里。

- `GET  /api/auth/session`：匿名可访问，返回是否需要认证与当前是否已认证。
- `POST /api/auth/login` ：校验令牌，成功则设置 cookie；失败返回 401（不区分"未配置/错误"，避免枚举）。
- `POST /api/auth/logout`：清除 cookie。

令牌永远不会出现在响应体里。
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request, Response
from pydantic import BaseModel

from security import SESSION_COOKIE, current_policy, extract_token, token_matches

router = APIRouter()

#: HttpOnly 会话 cookie 的有效期（秒）。与令牌本身的生命周期无关，过期后重新登录即可。
SESSION_MAX_AGE = 30 * 24 * 3600


class LoginBody(BaseModel):
    token: str


def _session_cookie_kwargs(request: Request) -> dict:
    forwarded = (request.headers.get("x-forwarded-proto") or "").split(",")[0].strip().lower()
    secure = request.url.scheme == "https" or forwarded == "https"
    return {
        "key": SESSION_COOKIE,
        "httponly": True,
        "samesite": "lax",
        "secure": secure,
        "path": "/",
    }


def is_authenticated(request: Request) -> bool:
    policy = current_policy()
    if not policy.auth_enabled:
        return True
    candidate = extract_token(request.headers, request.cookies, request.query_params.get("token"))
    return token_matches(candidate, policy)


@router.get("/auth/session")
async def auth_session(request: Request) -> dict:
    """匿名可访问：告诉前端是否需要登录、当前是否已登录。"""
    policy = current_policy()
    authenticated = is_authenticated(request)
    return {
        "auth_required": policy.auth_enabled,
        "authenticated": authenticated,
        "lan_enabled": policy.lan_enabled,
        "bind_host": policy.host,
    }


@router.post("/auth/login")
async def auth_login(body: LoginBody, request: Request, response: Response) -> dict:
    policy = current_policy()
    if not policy.auth_enabled:
        # 未启用认证时无需登录；直接成功，避免前端在本地模式下被卡住。
        return {"authenticated": True, "auth_required": False}
    if not token_matches((body.token or "").strip(), policy):
        raise HTTPException(status_code=401, detail="访问令牌不正确")
    response.set_cookie(value=str(body.token).strip(), max_age=SESSION_MAX_AGE, **_session_cookie_kwargs(request))
    return {"authenticated": True, "auth_required": True}


@router.post("/auth/logout")
async def auth_logout(request: Request, response: Response) -> dict:
    response.delete_cookie(**_session_cookie_kwargs(request))
    return {"authenticated": False}
