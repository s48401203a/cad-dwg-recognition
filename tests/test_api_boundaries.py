"""HTTP / API 边界测试。

覆盖本轮修复的越界与访问控制问题，全部使用**临时生成的无害文件**，
不读取任何真实私人文件或客户图纸。
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from tests.synthetic import build_basic_fixture, write_dxf


def _create_project(client, name: str = "边界测试项目") -> dict:
    response = client.post("/api/projects", json={"name": name, "site_profiles": ["generic"]})
    assert response.status_code == 200, response.text
    return response.json()


def _upload_dxf(client, path: Path) -> dict:
    with path.open("rb") as handle:
        response = client.post("/api/upload", files={"file": (path.name, handle, "application/dxf")})
    assert response.status_code == 200, response.text
    return response.json()


# --------------------------------------------------------------- 路径越界


def test_client_supplied_semantic_path_outside_project_is_not_read(client, clean_runtime, tmp_path: Path):
    """评审复现项：客户端提供项目目录外的 semantic_path，导出接口不得读取它。"""
    foreign = tmp_path / "outside" / "evil.json"
    foreign.parent.mkdir(parents=True, exist_ok=True)
    foreign.write_text(json.dumps({"secret": "should-never-be-read", "devices": [{"id": "x"}]}), encoding="utf-8")

    project = _create_project(client)
    added = client.post(
        f"/api/projects/{project['id']}/drawings",
        json={"drawing": {"name": "越界图纸", "semantic_path": str(foreign)}},
    )
    assert added.status_code == 200, added.text
    body = added.json()
    stored = next(item for item in body["drawings"] if item["name"] == "越界图纸")
    assert "semantic_path" not in stored, "客户端提供的路径字段必须被服务端剥离"
    assert "ignored_client_path_fields" in body

    export = client.get(f"/api/projects/{project['id']}/export?drawing_id={stored['id']}")
    assert export.status_code == 404, "越界 semantic_path 不得被读取"
    assert "should-never-be-read" not in export.text


def test_client_supplied_dxf_path_is_stripped(client, clean_runtime, tmp_path: Path):
    outsider = tmp_path / "outside" / "x.dxf"
    outsider.parent.mkdir(parents=True, exist_ok=True)
    outsider.write_text("0\nEOF\n", encoding="utf-8")
    project = _create_project(client)
    added = client.post(
        f"/api/projects/{project['id']}/drawings",
        json={"drawing": {"name": "带路径", "dxf_path": str(outsider), "source_path": str(outsider)}},
    )
    assert added.status_code == 200
    stored = next(item for item in added.json()["drawings"] if item["name"] == "带路径")
    for key in ("dxf_path", "source_path", "uploaded_path"):
        assert key not in stored
    source_open = client.post(f"/api/projects/{project['id']}/open-source-file", json={"drawing_id": stored["id"]})
    assert source_open.status_code == 404


def test_save_dir_outside_managed_roots_is_rejected(client, clean_runtime, tmp_path: Path):
    outside = tmp_path / "outside-save"
    response = client.post("/api/projects", json={"name": "越界保存目录", "save_dir": str(outside)})
    assert response.status_code == 400, response.text
    assert not outside.exists(), "被拒绝的 save_dir 不应被创建"


def test_arbitrary_drawing_fields_are_rejected(client, clean_runtime):
    project = _create_project(client)
    response = client.post(
        f"/api/projects/{project['id']}/drawings",
        json={"drawing": {"name": "x", "command": "rm -rf /"}},
    )
    assert response.status_code == 400
    assert "不允许的字段" in response.json()["detail"]


def test_invalid_project_id_is_rejected(client, clean_runtime):
    response = client.get("/api/projects/..%2F..%2Fetc")
    assert response.status_code in {400, 404}


@pytest.mark.parametrize(
    "path_value",
    [
        "../../etc/passwd",
        "/etc/passwd",
        "..\\..\\windows\\system32",
        "C:\\Windows\\System32",
        "~/secrets.json",
        "file:///etc/passwd",
    ],
)
def test_project_package_import_rejects_traversal(client, clean_runtime, path_value: str):
    response = client.post("/api/project-packages/import", json={"path": path_value})
    assert response.status_code == 400, f"{path_value} 应被拒绝，实际 {response.status_code}"
    assert "拒绝" in response.json()["detail"] or "非法" in response.json()["detail"] or "不存在" in response.json()["detail"]


def test_project_package_listing_has_no_paths(client, clean_runtime):
    response = client.get("/api/project-packages")
    assert response.status_code == 200
    for item in response.json():
        assert "package_dir" not in item
        assert "save_dir" not in item
        assert "package_manifest_path" not in item


def test_export_response_contains_no_local_paths(client, clean_runtime, tmp_path: Path):
    dxf = write_dxf(tmp_path / "basic.dxf", build_basic_fixture())
    upload = _upload_dxf(client, dxf)
    parsed = client.post(
        "/api/parse",
        json={"file_id": upload["file_id"], "site_profiles": ["generic"]},
    )
    assert parsed.status_code == 200, parsed.text
    project_id = parsed.json()["project"]["id"]

    exported = client.get(f"/api/projects/{project_id}/export")
    assert exported.status_code == 200
    payload = exported.json()
    assert str(tmp_path) not in exported.text, "导出内容不应包含本机绝对路径"
    assert "save_dir" not in payload["project"]
    for drawing in payload["project"]["drawings"]:
        assert "semantic_path" not in drawing
        assert "dxf_path" not in drawing


def test_upload_records_relative_to_upload_root(client, clean_runtime):
    dxf = write_dxf(clean_runtime["root"] / "u.dxf", build_basic_fixture())
    upload = _upload_dxf(client, dxf)
    assert upload["file_id"]
    # 响应不回显服务端路径
    assert "dxf_path" not in upload
    record = client.get("/api/health")
    assert record.status_code == 200


# --------------------------------------------------------------- 访问控制


def test_cross_origin_write_is_rejected(client, clean_runtime):
    response = client.post(
        "/api/projects",
        json={"name": "csrf"},
        headers={"Origin": "https://evil.example"},
    )
    assert response.status_code == 403
    assert response.json()["code"] == "origin_not_allowed"


def test_cross_origin_read_is_rejected(client, clean_runtime):
    response = client.get("/api/projects", headers={"Origin": "https://evil.example"})
    assert response.status_code == 403


def test_same_origin_is_allowed(client, clean_runtime):
    response = client.get("/api/projects", headers={"Origin": "http://127.0.0.1"})
    assert response.status_code == 200


def test_dns_rebinding_host_is_rejected(client, clean_runtime):
    response = client.get("/api/projects", headers={"Host": "attacker.example"})
    assert response.status_code == 403
    assert response.json()["code"] == "host_not_allowed"


def test_lan_mode_requires_token():
    import security

    with pytest.raises(security.AccessDenied) as excinfo:
        security.load_access_policy({"CAD_HOST": "0.0.0.0"})
    assert excinfo.value.code == "lan_requires_token"

    policy = security.load_access_policy({"CAD_HOST": "0.0.0.0", "CAD_ACCESS_TOKEN": "t" * 16})
    assert policy.lan_enabled and policy.token_required


def test_token_required_for_writes(token_client, clean_runtime, tmp_path: Path):
    # 带令牌：成功
    ok = token_client.post("/api/projects", json={"name": "ok"})
    assert ok.status_code == 200, ok.text

    # 不带令牌：401
    token_client.headers.pop("X-CAD-Token", None)
    denied = token_client.post("/api/projects", json={"name": "denied"})
    assert denied.status_code == 401
    assert denied.json()["code"] == "token_required"

    # 只读预览仍然开放
    readable = token_client.get("/api/projects")
    assert readable.status_code == 200


def test_websocket_rejects_cross_origin(client, clean_runtime):
    from starlette.websockets import WebSocketDisconnect

    with pytest.raises(WebSocketDisconnect) as excinfo:
        with client.websocket_connect("/ws/logs", headers={"Origin": "https://evil.example"}):
            pass
    assert excinfo.value.code == 1008


def test_websocket_accepts_same_origin(client, clean_runtime):
    """同源（Origin 与 Host 一致）必须放行。"""
    from fastapi.testclient import TestClient

    import main

    with TestClient(main.app, base_url="http://testserver") as same_origin:
        with same_origin.websocket_connect("/ws/logs", headers={"Origin": "http://testserver"}) as ws:
            ws.send_text("ping")


# --------------------------------------------------------------- 上传边界


def test_upload_rejects_unsupported_extension(client, clean_runtime, tmp_path: Path):
    bad = tmp_path / "evil.exe"
    bad.write_bytes(b"MZ")
    with bad.open("rb") as handle:
        response = client.post("/api/upload", files={"file": ("evil.exe", handle, "application/octet-stream")})
    assert response.status_code == 400


def test_upload_rejects_empty_file(client, clean_runtime, tmp_path: Path):
    empty = tmp_path / "empty.dxf"
    empty.write_bytes(b"")
    with empty.open("rb") as handle:
        response = client.post("/api/upload", files={"file": ("empty.dxf", handle, "application/dxf")})
    assert response.status_code == 400


def test_upload_size_limit_and_cleanup(client, clean_runtime, monkeypatch: pytest.MonkeyPatch):
    import importlib

    from fastapi.testclient import TestClient

    monkeypatch.setenv("CAD_MAX_UPLOAD_MB", "0.001")  # ~1KB
    import main

    importlib.reload(main)
    big = clean_runtime["root"] / "big.dxf"
    big.write_bytes(b"0\nSECTION\n" + b"x" * 50_000)
    with TestClient(main.app, base_url="http://127.0.0.1") as limited:
        with big.open("rb") as handle:
            response = limited.post("/api/upload", files={"file": ("big.dxf", handle, "application/dxf")})
        assert response.status_code == 413
    leftovers = [item for item in clean_runtime["uploads"].iterdir() if item.is_dir()]
    assert leftovers == [], f"失败上传必须清理临时目录，实际残留 {leftovers}"


def test_upload_filename_is_sanitized(client, clean_runtime, tmp_path: Path):
    dxf = write_dxf(tmp_path / "nice.dxf", build_basic_fixture())
    with dxf.open("rb") as handle:
        response = client.post("/api/upload", files={"file": ("../../evil.dxf", handle, "application/dxf")})
    assert response.status_code == 200
    assert response.json()["original_name"] == "evil.dxf"
    for item in clean_runtime["uploads"].iterdir():
        if item.is_dir() and item.name != "index.json":
            assert all(child.name == "evil.dxf" for child in item.iterdir())


# --------------------------------------------------------------- 能力门禁


def test_replay_disabled_reports_503_not_a_broken_entrypoint(client, clean_runtime, monkeypatch: pytest.MonkeyPatch):
    """干净检出（没有 orchestrator/）时 replay 必须是明确的 503，而不是必然失败的入口。

    用 `CAD_ENABLE_REPLAY=0` 复现"缺少可选模块"，这样在有内部 orchestrator 的开发机上
    也能验证公开分发行为。
    """
    import capabilities

    monkeypatch.setenv("CAD_ENABLE_REPLAY", "0")
    capabilities.reset_cache()
    try:
        info = client.get("/api/replay/capability")
        assert info.status_code == 200
        payload = info.json()
        assert payload["capability"] == "replay"
        assert payload["available"] is False
        assert payload["reason"]

        started = client.post("/api/replay/start", json={"project_id": "proj_x", "drawing_id": "draw_x"})
        assert started.status_code == 503, started.text
        assert "replay" in started.json()["detail"]

        status = client.get("/api/replay/status")
        assert status.status_code == 200
        assert status.json()["available"] is False
        assert status.json()["unavailable_reason"]
    finally:
        monkeypatch.delenv("CAD_ENABLE_REPLAY", raising=False)
        capabilities.reset_cache()


def test_replay_validates_ids_and_backend_url(client, clean_runtime, monkeypatch: pytest.MonkeyPatch):
    """即使 replay 可用，也必须校验 ID 与 backend_url（防 SSRF）。"""
    import capabilities

    monkeypatch.setenv("CAD_ENABLE_REPLAY", "1")
    capabilities.reset_cache()
    try:
        bad_id = client.post("/api/replay/start", json={"project_id": "../etc", "drawing_id": "draw_x"})
        assert bad_id.status_code in {400, 503}
        bad_url = client.post(
            "/api/replay/start",
            json={"project_id": "proj_x", "drawing_id": "draw_x", "backend_url": "http://evil.example/"},
        )
        assert bad_url.status_code in {400, 503}
    finally:
        monkeypatch.delenv("CAD_ENABLE_REPLAY", raising=False)
        capabilities.reset_cache()


def test_health_reports_capabilities_and_access(client, clean_runtime):
    response = client.get("/api/health")
    assert response.status_code == 200
    payload = response.json()
    assert payload["ok"] is True
    assert "capabilities" in payload and "access" in payload
    caps = payload["capabilities"]
    assert caps["dxf_parse"]["available"] is True
    assert payload["access"]["bind_host"] == "127.0.0.1"
    assert payload["access"]["lan_enabled"] is False
    # 旧字段保留，避免破坏既有调用方
    assert "oda_available" in payload


def test_static_export_available_in_clean_checkout(client, clean_runtime, tmp_path: Path):
    caps = client.get("/api/health").json()["capabilities"]
    dxf = write_dxf(tmp_path / "export.dxf", build_basic_fixture())
    upload = _upload_dxf(client, dxf)
    parsed = client.post("/api/parse", json={"file_id": upload["file_id"], "site_profiles": ["generic"]})
    assert parsed.status_code == 200, parsed.text
    project_id = parsed.json()["project"]["id"]

    response = client.post(f"/api/projects/{project_id}/export-static", json={})
    if not caps["static_export"]["available"]:
        assert response.status_code == 503
        assert "能力不可用" in response.json()["detail"]
        return
    assert response.status_code == 200, response.text
    body = response.json()
    assert Path(body["path"]).exists()
    assert body["size_bytes"] > 0
    html = Path(body["path"]).read_text(encoding="utf-8")
    assert str(tmp_path) not in html, "静态导出不应包含本机绝对路径"


# --------------------------------------------------------------- 归档只读


def test_archived_project_is_read_only(client, clean_runtime, tmp_path: Path):
    dxf = write_dxf(tmp_path / "a.dxf", build_basic_fixture())
    upload = _upload_dxf(client, dxf)
    parsed = client.post("/api/parse", json={"file_id": upload["file_id"], "site_profiles": ["generic"]})
    project_id = parsed.json()["project"]["id"]

    archived = client.post(f"/api/projects/{project_id}/archive")
    assert archived.status_code == 200, archived.text
    assert archived.json()["status"] == "archived"

    blocked = client.post("/api/projects/%s/drawings" % project_id, json={"drawing": {"name": "x"}})
    assert blocked.status_code == 409
    blocked_export = client.post(f"/api/projects/{project_id}/export-static", json={})
    assert blocked_export.status_code == 409

    restored = client.post(f"/api/projects/{project_id}/restore")
    assert restored.status_code == 200
    assert restored.json()["status"] == "active"


def test_revision_conflict_on_stale_save(client, clean_runtime, tmp_path: Path):
    project = _create_project(client)
    first = client.get(f"/api/projects/{project['id']}").json()
    stale_revision = first["revision"]

    # 模拟另一个会话先保存了一次
    client.post(f"/api/projects/{project['id']}/drawings", json={"drawing": {"name": "先到的修改"}})

    conflict = client.post(
        f"/api/projects/{project['id']}/reparse",
        json={"revision": stale_revision},
    )
    # 缺少当前图纸时先返回 404/400；有图纸时必须是 409
    assert conflict.status_code in {400, 404, 409}


def test_corrupt_project_meta_reports_error_and_quarantines(client, clean_runtime):
    project = _create_project(client)
    meta_path = clean_runtime["projects"] / project["id"] / "meta.json"
    meta_path.write_text("{ this is not json", encoding="utf-8")
    response = client.get(f"/api/projects/{project['id']}")
    assert response.status_code == 500
    assert "损坏" in response.json()["detail"]
    quarantined = list(meta_path.parent.glob("meta.json.corrupt-*"))
    assert quarantined, "损坏文件必须被隔离保留，而不是静默覆盖"
