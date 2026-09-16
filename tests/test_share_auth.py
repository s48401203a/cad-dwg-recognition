"""分享链接与作用域分享令牌的鉴权与副作用测试。

要求对应：
- 分享默认需要认证；若提供匿名分享，必须使用与主令牌独立、作用域限于具体导出、
  可撤销或可过期的授权机制。
- 分享不得泄露主访问令牌，也不能借此访问其他项目。
- 会生成文件的 share-link GET 路由改为受保护的 POST。
"""

from __future__ import annotations

from pathlib import Path

import pytest

from tests.synthetic import build_basic_fixture, write_dxf

TOKEN = "test-token-1234567890"
WRONG = "definitely-wrong-token-xx"


def _parsed_project(client, tmp_path: Path, name: str) -> dict:
    dxf = write_dxf(tmp_path / f"{name}.dxf", build_basic_fixture())
    with dxf.open("rb") as handle:
        upload = client.post("/api/upload", files={"file": (f"{name}.dxf", handle, "application/dxf")})
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


@pytest.fixture()
def share_context(token_client, clean_runtime, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """两个已解析项目 + 令牌存储隔离到临时目录。"""
    monkeypatch.setenv("CAD_SHARE_TOKENS_PATH", str(tmp_path / "share-tokens.json"))
    first = _parsed_project(token_client, tmp_path, "分享项目A")
    second = _parsed_project(token_client, tmp_path, "分享项目B")
    return {"client": token_client, "first": first, "second": second}


def _share_via_post(client, project_id: str, drawing_id: str | None = None) -> dict:
    response = client.post(f"/api/projects/{project_id}/share-link", json={"drawing_id": drawing_id})
    assert response.status_code == 200, response.text
    return response.json()


# --------------------------------------------------------------- 默认需要认证


def test_share_link_requires_auth(share_context, clean_runtime):
    client = share_context["client"]
    project_id = share_context["first"]["project_id"]

    client.headers.pop("X-CAD-Token", None)
    client.cookies.clear()
    denied_post = client.post(f"/api/projects/{project_id}/share-link", json={})
    assert denied_post.status_code == 401
    denied_get = client.get(f"/api/projects/{project_id}/share-link")
    assert denied_get.status_code == 401
    assert "html" not in denied_get.text.lower()


def test_share_link_get_is_deprecated_and_does_not_issue_token(share_context):
    """GET 形式保留兼容，但只返回"需要认证"的链接，不签发分享令牌。"""
    client = share_context["client"]
    project_id = share_context["first"]["project_id"]

    response = client.get(f"/api/projects/{project_id}/share-link")
    assert response.status_code == 200, response.text
    payload = response.json()
    assert "deprecated" in payload
    assert payload.get("share_scope") is None
    assert "share=" not in payload["url"], "GET 不得返回带分享令牌的链接"


# --------------------------------------------------------------- 作用域与泄露


def test_share_link_never_leaks_main_token(share_context):
    client = share_context["client"]
    project_id = share_context["first"]["project_id"]
    drawing_id = share_context["first"]["drawing_id"]

    payload = _share_via_post(client, project_id, drawing_id)
    body = str(payload)
    assert TOKEN not in body, "分享响应绝不能包含主访问令牌"
    assert "share=" in payload["url"], "应签发作用域分享令牌"
    # 作用域必须包含项目 ID，且限定到这一个导出文件（导出真实布局为
    # /exports/static-pages/<项目ID>/<文件>.html）
    assert payload["share_scope"].startswith("/exports/")
    assert project_id in payload["share_scope"]
    assert payload["share_scope"].endswith(".html")
    assert payload["share_expires_at"] > 0

    # URL 中的分享令牌必须与主令牌不同
    from urllib.parse import parse_qs, urlsplit

    share_token = parse_qs(urlsplit(payload["url"]).query).get("share", [""])[0]
    assert share_token and share_token != TOKEN


def test_share_token_scoped_to_one_export_and_cannot_touch_api(share_context):
    client = share_context["client"]
    first = share_context["first"]
    payload = _share_via_post(client, first["project_id"], first["drawing_id"])

    from urllib.parse import parse_qs, urlsplit

    share_token = parse_qs(urlsplit(payload["url"]).query)["share"][0]
    export_path = urlsplit(payload["url"]).path

    client.headers.pop("X-CAD-Token", None)
    client.cookies.clear()

    # 1) 自己的导出页：可用
    own = client.get(f"{export_path}?share={share_token}")
    assert own.status_code == 200, own.text

    # 2) 其他项目：拒绝
    other_project = share_context["second"]["project_id"]
    foreign = client.get(f"/exports/{other_project}/whatever.html?share={share_token}")
    assert foreign.status_code == 401

    # 3) 其他导出文件：拒绝
    sibling = client.get(f"{export_path.rsplit('/', 1)[0]}/other.html?share={share_token}")
    assert sibling.status_code == 401

    # 4) 任何 API：分享令牌无效（不能拿它枚举或读取项目）
    for path in ("/api/projects", f"/api/projects/{first['project_id']}", f"/api/projects/{first['project_id']}/export"):
        assert client.get(f"{path}?share={share_token}").status_code == 401
        assert client.get(f"{path}?token={share_token}").status_code == 401

    # 5) 错误分享令牌：拒绝
    assert client.get(f"{export_path}?share=wrong-share-token").status_code == 401

    # 6) 主令牌仍然可以访问导出（认证用户不受影响）
    assert client.get(f"{export_path}?token={TOKEN}").status_code == 200


def test_share_token_can_be_revoked(share_context):
    client = share_context["client"]
    first = share_context["first"]
    payload = _share_via_post(client, first["project_id"], first["drawing_id"])

    from urllib.parse import parse_qs, urlsplit

    share_token = parse_qs(urlsplit(payload["url"]).query)["share"][0]
    export_path = urlsplit(payload["url"]).path

    listed = client.get(f"/api/projects/{first['project_id']}/share-tokens")
    assert listed.status_code == 200
    listed_body = listed.text
    assert share_token not in listed_body, "审计列表不得回显令牌本身"
    assert listed.json()["tokens"], "应列出有效分享令牌"
    scopes = [item["path_prefix"] for item in listed.json()["tokens"]]
    assert all(item.startswith("/exports/") for item in scopes)

    revoked = client.delete(f"/api/projects/{first['project_id']}/share-tokens")
    assert revoked.status_code == 200
    assert revoked.json()["revoked"] >= 1

    client.headers.pop("X-CAD-Token", None)
    client.cookies.clear()
    assert client.get(f"{export_path}?share={share_token}").status_code == 401


def test_share_token_expires(share_context, monkeypatch: pytest.MonkeyPatch):
    client = share_context["client"]
    first = share_context["first"]

    monkeypatch.setenv("CAD_SHARE_TTL_HOURS", "0.0001")  # 约 0.36 秒
    payload = _share_via_post(client, first["project_id"], first["drawing_id"])
    from urllib.parse import parse_qs, urlsplit

    share_token = parse_qs(urlsplit(payload["url"]).query)["share"][0]
    export_path = urlsplit(payload["url"]).path

    import time

    time.sleep(0.6)
    client.headers.pop("X-CAD-Token", None)
    client.cookies.clear()
    assert client.get(f"{export_path}?share={share_token}").status_code == 401, "过期令牌必须失效"


def test_share_failure_is_reported_not_silently_insecure(share_context, monkeypatch: pytest.MonkeyPatch):
    """签发令牌失败时，退回"需要认证"并如实说明，而不是给出无保护的链接。"""
    client = share_context["client"]
    first = share_context["first"]

    import share_tokens

    def boom(**_kwargs):
        raise share_tokens.ShareTokenError("模拟签发失败")

    monkeypatch.setattr(share_tokens, "issue_share_token", boom)
    payload = _share_via_post(client, first["project_id"], first["drawing_id"])
    assert payload.get("share_scope") is None
    assert "share_error" in payload
    assert "share=" not in payload["url"]
    assert payload["requires_auth"] is True


def test_share_tokens_are_isolated_per_project(share_context):
    client = share_context["client"]
    first = share_context["first"]
    second = share_context["second"]

    first_payload = _share_via_post(client, first["project_id"], first["drawing_id"])
    second_payload = _share_via_post(client, second["project_id"], second["drawing_id"])

    from urllib.parse import parse_qs, urlsplit

    first_scope = first_payload["share_scope"]
    second_scope = second_payload["share_scope"]
    assert first_scope != second_scope

    first_token = parse_qs(urlsplit(first_payload["url"]).query)["share"][0]
    listing = client.get(f"/api/projects/{first['project_id']}/share-tokens").json()
    assert all(item["path_prefix"].startswith("/exports/") for item in listing["tokens"])
    assert all(first["project_id"] in item["path_prefix"] for item in listing["tokens"])
    assert all(item["path_prefix"] != second_scope for item in listing["tokens"])

    # 撤销 A 的令牌不影响 B
    client.delete(f"/api/projects/{first['project_id']}/share-tokens")
    client.headers.pop("X-CAD-Token", None)
    client.cookies.clear()
    assert client.get(f"{first_scope}?share={first_token}").status_code == 401
    second_token = parse_qs(urlsplit(second_payload["url"]).query)["share"][0]
    assert client.get(f"{second_scope}?share={second_token}").status_code == 200
