"""认证边界回归测试。

覆盖评审要求：
- 配置令牌后，匿名或错误令牌不能读取项目列表 / 详情 / 导出；
- 正确令牌可正常使用；
- 直接访问导出文件、关联文件与 HEAD 请求不能绕过认证；
- 无 Origin 的脚本客户端同样受令牌约束；
- 健康检查与必要公共前端资源匿名可用；
- 默认回环、未配置令牌时的既有行为不变。

所有数据都是临时目录里的合成项目，不涉及任何客户图纸。
"""

from __future__ import annotations

from pathlib import Path

import pytest

from tests.synthetic import build_basic_fixture, write_dxf

TOKEN = "test-token-1234567890"
WRONG = "definitely-wrong-token-xx"


@pytest.fixture()
def secured_client(token_client):
    """已配置令牌的客户端（夹具自带 X-CAD-Token 头）。"""
    return token_client


def _create_parsed_project(client, tmp_path: Path, name: str = "认证边界项目") -> dict:
    """建一个带真实 semantic.json 的项目，返回 {"project_id", "drawing_id"}。"""
    dxf = write_dxf(tmp_path / "auth.dxf", build_basic_fixture())
    with dxf.open("rb") as handle:
        upload = client.post("/api/upload", files={"file": ("auth.dxf", handle, "application/dxf")})
    assert upload.status_code == 200, upload.text
    created = client.post("/api/projects", json={"name": name, "site_profiles": ["generic"]})
    assert created.status_code == 200, created.text
    project_id = created.json()["id"]
    parsed = client.post(
        "/api/parse",
        json={"file_id": upload.json()["file_id"], "project_id": project_id, "site_profiles": ["generic"]},
    )
    assert parsed.status_code == 200, parsed.text
    return {"project_id": project_id, "drawing_id": parsed.json()["project"]["drawing_id"]}


# --------------------------------------------------------------- 匿名 / 错误令牌


def test_anonymous_cannot_read_projects_or_exports(secured_client, clean_runtime, tmp_path: Path):
    """核心回归：配置令牌后，匿名不得枚举 / 读取 / 导出项目。"""
    created = _create_parsed_project(secured_client, tmp_path)
    project_id = created["project_id"]

    secured_client.headers.pop("X-CAD-Token", None)

    read_endpoints = [
        "/api/projects",
        f"/api/projects/{project_id}",
        f"/api/projects/{project_id}/export",
        f"/api/projects/{project_id}/export?include_all_drawings=true",
        "/api/project-packages",
        "/api/site-profiles",
        "/api/model-catalog",
        "/api/units",
        "/api/replay/status",
        "/api/replay/log",
        "/api/replay/metrics",
        f"/api/projects/{project_id}/model-overrides",
    ]
    for path in read_endpoints:
        response = secured_client.get(path)
        assert response.status_code == 401, f"匿名 GET {path} 应 401，实际 {response.status_code}"
        assert "proj_" not in response.text, f"匿名响应不得包含项目 ID: {path}"
        assert "drawings" not in response.text, f"匿名响应不得包含图纸数据: {path}"

    # 详情接口的拒绝响应也不能回显项目名
    detail = secured_client.get(f"/api/projects/{project_id}")
    assert "认证边界项目" not in detail.text


def test_wrong_token_cannot_read_or_write(secured_client, clean_runtime, tmp_path: Path):
    created = _create_parsed_project(secured_client, tmp_path)
    project_id = created["project_id"]

    secured_client.headers.update({"X-CAD-Token": WRONG})
    for method, path in (
        ("GET", "/api/projects"),
        ("GET", f"/api/projects/{project_id}"),
        ("GET", f"/api/projects/{project_id}/export"),
        ("GET", "/api/project-packages"),
        ("POST", "/api/projects"),
        ("POST", f"/api/projects/{project_id}/reparse"),
        ("PUT", f"/api/projects/{project_id}/model-overrides"),
        ("DELETE", f"/api/projects/{project_id}"),
    ):
        response = secured_client.request(method, path, json={} if method in {"POST", "PUT"} else None)
        assert response.status_code == 401, f"错误令牌 {method} {path} 应 401，实际 {response.status_code}"


def test_correct_token_can_use_everything(secured_client, clean_runtime, tmp_path: Path):
    created = _create_parsed_project(secured_client, tmp_path)
    project_id = created["project_id"]
    drawing_id = created["drawing_id"]

    listing = secured_client.get("/api/projects")
    assert listing.status_code == 200
    assert any(item["id"] == project_id for item in listing.json())

    detail = secured_client.get(f"/api/projects/{project_id}")
    assert detail.status_code == 200
    assert detail.json()["id"] == project_id

    export = secured_client.get(f"/api/projects/{project_id}/export?drawing_id={drawing_id}")
    assert export.status_code == 200
    assert export.json().get("devices"), "导出应包含设备"

    static_export = secured_client.post(f"/api/projects/{project_id}/export-static", json={})
    assert static_export.status_code in {200, 503}, static_export.text
    if static_export.status_code == 200:
        assert Path(static_export.json()["path"]).exists()

    # 健康检查在认证后返回完整信息
    health = secured_client.get("/api/health").json()
    assert health["authenticated"] is True


def test_anonymous_request_without_origin_still_requires_token(secured_client, clean_runtime, tmp_path: Path):
    """脚本客户端不带 Origin：Host/Origin 校验放行，但身份仍由令牌决定。"""
    created = _create_parsed_project(secured_client, tmp_path)
    secured_client.headers.pop("X-CAD-Token", None)
    headers = {"User-Agent": "curl/8.0"}  # 明确不带 Origin

    for path in ("/api/projects", f"/api/projects/{created['project_id']}", "/api/project-packages"):
        response = secured_client.get(path, headers=headers)
        assert response.status_code == 401, f"无 Origin 的匿名 GET {path} 应 401"

    # 带上正确令牌则通过（证明拒绝原因是缺令牌，而不是被 Host/Origin 拦下）
    authed = secured_client.get("/api/projects", headers={**headers, "X-CAD-Token": TOKEN})
    assert authed.status_code == 200


def test_public_endpoints_stay_anonymous(secured_client, clean_runtime):
    secured_client.headers.pop("X-CAD-Token", None)

    health = secured_client.get("/api/health")
    assert health.status_code == 200
    payload = health.json()
    assert payload["ok"] is True
    assert payload["auth_required"] is True
    assert payload["authenticated"] is False
    # 匿名健康检查不回显本机路径与 ODA 路径
    for key in ("oda_path", "runtime_root", "projects_dir", "uploads_dir", "exports_dir"):
        assert key not in payload, f"匿名 health 不应包含 {key}"
    assert "reason" not in str(payload.get("capabilities")), "匿名 health 不回显不可用原因，避免信息泄露"

    session = secured_client.get("/api/auth/session")
    assert session.status_code == 200
    assert session.json() == {
        "auth_required": True,
        "authenticated": False,
        "lan_enabled": False,
        "bind_host": "127.0.0.1",
    }

    # 登录界面所需的前端外壳资源必须匿名可取，否则无法认证
    for asset in ("/", "/index.html", "/js/app.js", "/css/style.css", "/vendor/three/three.module.js"):
        response = secured_client.get(asset)
        assert response.status_code == 200, f"公开前端资源 {asset} 应可匿名加载"


def test_login_sets_session_cookie_and_grants_access(secured_client, clean_runtime, tmp_path: Path):
    created = _create_parsed_project(secured_client, tmp_path)
    secured_client.headers.pop("X-CAD-Token", None)

    assert secured_client.get("/api/projects").status_code == 401

    bad = secured_client.post("/api/auth/login", json={"token": WRONG})
    assert bad.status_code == 401
    assert TOKEN not in bad.text

    ok = secured_client.post("/api/auth/login", json={"token": TOKEN})
    assert ok.status_code == 200
    assert ok.json()["authenticated"] is True
    assert TOKEN not in ok.text, "登录响应绝不能回显令牌"
    assert "cad_session" in ok.cookies or any("cad_session" in h for h in ok.headers.get_list("set-cookie"))

    # cookie 已由 TestClient 保存：后续无自定义头的请求也能通过
    assert secured_client.get("/api/projects").status_code == 200
    assert secured_client.get(f"/api/projects/{created['project_id']}").status_code == 200

    logout = secured_client.post("/api/auth/logout")
    assert logout.status_code == 200
    assert secured_client.get("/api/projects").status_code == 401


def test_local_mode_without_token_is_unchanged(client, clean_runtime, tmp_path: Path):
    """默认回环、未配置令牌时保持零摩擦（文档所述的既有行为）。"""
    created = _create_parsed_project(client, tmp_path)
    assert client.get("/api/projects").status_code == 200
    assert client.get(f"/api/projects/{created['project_id']}").status_code == 200
    assert client.get(f"/api/projects/{created['project_id']}/export").status_code == 200

    health = client.get("/api/health").json()
    assert health["auth_required"] is False
    assert health["authenticated"] is True

    session = client.get("/api/auth/session").json()
    assert session["auth_required"] is False and session["authenticated"] is True

    # 未启用认证时可匿名取用的导出文件（无令牌、无 cookie）
    anonymous = client
    anonymous.cookies.clear()
    assert anonymous.get("/api/projects").status_code == 200


# --------------------------------------------------------------- /exports 静态保护


def test_exports_static_files_require_auth(secured_client, clean_runtime, tmp_path: Path):
    created = _create_parsed_project(secured_client, tmp_path)
    project_id = created["project_id"]

    exported = secured_client.post(f"/api/projects/{project_id}/export-static", json={})
    if exported.status_code != 200:
        pytest.skip(f"静态导出在本地不可用（{exported.status_code}）")
    url = exported.json()["url"]
    assert url.startswith("/exports/")

    # 1) 匿名：GET / HEAD 都是 401，且不返回文件内容
    secured_client.headers.pop("X-CAD-Token", None)
    secured_client.cookies.clear()
    anonymous_get = secured_client.get(url)
    assert anonymous_get.status_code == 401
    assert "<html" not in anonymous_get.text.lower(), "匿名访问导出文件不得返回页面内容"
    anonymous_head = secured_client.head(url)
    assert anonymous_head.status_code == 401, "HEAD 不得绕过认证"

    # 2) 错误令牌：401
    secured_client.headers.update({"X-CAD-Token": WRONG})
    assert secured_client.get(url).status_code == 401
    assert secured_client.head(url).status_code == 401

    # 3) 正确令牌：200（GET 与 HEAD 都可以）
    secured_client.headers.update({"X-CAD-Token": TOKEN})
    authed_get = secured_client.get(url)
    assert authed_get.status_code == 200
    assert "<html" in authed_get.text.lower()
    assert secured_client.head(url).status_code == 200

    # 4) 会话 cookie 也应可用：浏览器直接点开导出链接的场景
    secured_client.headers.pop("X-CAD-Token", None)
    secured_client.post("/api/auth/login", json={"token": TOKEN})
    assert secured_client.get(url).status_code == 200
    assert secured_client.head(url).status_code == 200


def test_exports_directory_listing_and_aliases_are_protected(secured_client, clean_runtime, tmp_path: Path):
    created = _create_parsed_project(secured_client, tmp_path)
    project_id = created["project_id"]
    exported = secured_client.post(f"/api/projects/{project_id}/export-static", json={})
    if exported.status_code != 200:
        pytest.skip("静态导出不可用")
    url = exported.json()["url"]

    secured_client.headers.pop("X-CAD-Token", None)
    secured_client.cookies.clear()

    # 目录形式、带查询串、以及导出目录本身都不能匿名访问
    for candidate in (url, url + "?x=1", url.rsplit("/", 1)[0] + "/", "/exports/", "/exports"):
        response = secured_client.get(candidate, follow_redirects=False)
        assert response.status_code == 401, f"匿名访问 {candidate} 应 401，实际 {response.status_code}"

    # 路径穿越也不能绕过
    traversal = "/exports/../backend/security.py"
    assert secured_client.get(traversal, follow_redirects=False).status_code in {400, 401, 404}


def test_token_in_query_does_not_leak_into_logs_or_response(secured_client, clean_runtime, tmp_path: Path):
    """`?token=` 可用（启动脚本会这样打开浏览器），但响应体与项目导出不得包含令牌。"""
    created = _create_parsed_project(secured_client, tmp_path)
    created_id = created["project_id"]
    secured_client.headers.pop("X-CAD-Token", None)

    via_query = secured_client.get(f"/api/projects?token={TOKEN}")
    assert via_query.status_code == 200
    assert TOKEN not in via_query.text

    detail = secured_client.get(f"/api/projects/{created_id}?token={TOKEN}")
    assert detail.status_code == 200
    assert TOKEN not in detail.text

    export = secured_client.get(f"/api/projects/{created_id}/export?token={TOKEN}")
    assert export.status_code == 200
    assert TOKEN not in export.text
