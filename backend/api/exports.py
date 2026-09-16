"""静态导出文件的受保护服务。

为什么不直接用 `StaticFiles` 挂载 `/exports`：
- 导出文件名可能包含中文等非 ASCII 字符，`StaticFiles` 会拿百分号编码后的路径去匹配，
  导致"鉴权通过但取不到文件"的 404（本次修复前实测）。
- 需要统一入口做鉴权（主令牌或作用域分享令牌）与路径策略校验，并覆盖 GET/HEAD。

本模块负责：路径解码与规范化、越界拒绝、按目录列举、以及实际文件响应。
"""

from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, Request
from fastapi.responses import FileResponse, JSONResponse, Response
from starlette.responses import PlainTextResponse

from path_policy import PathPolicyError, resolve_within_roots

router = APIRouter()

MEDIA_TYPES = {
    ".html": "text/html; charset=utf-8",
    ".htm": "text/html; charset=utf-8",
    ".json": "application/json; charset=utf-8",
    ".js": "text/javascript; charset=utf-8",
    ".mjs": "text/javascript; charset=utf-8",
    ".css": "text/css; charset=utf-8",
    ".svg": "image/svg+xml",
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".webp": "image/webp",
    ".txt": "text/plain; charset=utf-8",
}
NO_STORE = {"Cache-Control": "no-store", "X-CAD-Exports": "protected"}


def exports_root() -> Path:
    import main

    return Path(main.EXPORTS_DIR)


def _decode_relpath(request: Request) -> str:
    """取 `/exports` 之后的相对路径（已解码）。

    关键：使用 ASGI `raw_path` 而不是 `request.url.path`。
    Starlette 路由在匹配 `{path:path}` 时**已经解码一次**，再用 `url.path` 解一次
    会把文件名中的 `%` 二次解码（中文文件名尤其明显），导致"鉴权通过但找不到文件"。
    `raw_path` 是请求原始字节，只解一次即可。
    """
    from urllib.parse import unquote

    raw_bytes = request.scope.get("raw_path")
    if raw_bytes:
        raw_path = raw_bytes.decode("latin-1") if isinstance(raw_bytes, bytes) else str(raw_bytes)
    else:
        raw_path = str(request.url.path)
    raw_path = raw_path.split("?", 1)[0]
    decoded = unquote(raw_path)
    if decoded.startswith("/exports"):
        decoded = decoded[len("/exports") :]
    return decoded.strip("/")


def _resolve_target(relpath: str) -> Path:
    root = exports_root()
    if not relpath:
        return root
    try:
        return resolve_within_roots(root / relpath, [root], label="导出文件")
    except PathPolicyError as exc:
        raise FileNotFoundError(str(exc)) from exc


def _render_directory_listing(directory: Path) -> Response:
    root = exports_root()
    entries = sorted(
        (
            {
                "name": child.name,
                "path": f"/exports/{child.relative_to(root).as_posix()}" if child.is_file() else None,
                "is_dir": child.is_dir(),
            }
            for child in directory.iterdir()
        ),
        key=lambda item: (not item["is_dir"], item["name"]),
    )
    if directory == root and not entries:
        return PlainTextResponse("暂无导出文件。", status_code=200, headers=NO_STORE)
    return JSONResponse(
        {
            "note": "该列表需要访问令牌；分享链接只能访问被授权的那一个导出文件。",
            "root": directory.relative_to(root).as_posix() or "/",
            "entries": entries,
        },
        headers=NO_STORE,
    )


@router.api_route("/exports", methods=["GET", "HEAD"])
@router.api_route("/exports/{relpath:path}", methods=["GET", "HEAD"])
async def serve_export_file(request: Request, relpath: str = "") -> Response:
    """提供导出文件。鉴权由访问控制中间件统一完成（GET/HEAD 均已覆盖）。"""
    try:
        target = _resolve_target(_decode_relpath(request))
    except FileNotFoundError as exc:
        return JSONResponse({"detail": f"导出路径无效: {exc}"}, status_code=404, headers=NO_STORE)

    if not target.exists():
        return JSONResponse({"detail": "导出文件不存在"}, status_code=404, headers=NO_STORE)

    if target.is_dir():
        if not request.url.path.endswith("/"):
            return Response(status_code=307, headers={"Location": f"{request.url.path}/", **NO_STORE})
        return _render_directory_listing(target)

    if not target.is_file():
        return JSONResponse({"detail": "导出路径不是文件"}, status_code=404, headers=NO_STORE)

    media_type = MEDIA_TYPES.get(target.suffix.lower(), "application/octet-stream")
    return FileResponse(
        str(target),
        media_type=media_type,
        headers={**NO_STORE, "X-Content-Type-Options": "nosniff"},
    )
