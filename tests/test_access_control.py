"""开发来源（Vite 代理）与 CORS 白名单的独立测试。

单独成文件的原因：CORS 中间件在应用导入时按当时的策略装配，因此需要在
导入 `main` 之前设置 `CAD_DEV_ORIGINS`。这样每个进程只装配一次，测试之间不会互相污染。
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from tests.conftest import reload_backend

DEV_ORIGIN = "http://127.0.0.1:5173"


@pytest.fixture()
def dev_origin_client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    from fastapi.testclient import TestClient

    dirs = {
        "root": tmp_path,
        "projects": tmp_path / "projects",
        "archive": tmp_path / "projects-archive",
        "uploads": tmp_path / "uploads",
        "packages": tmp_path / "project-packages",
        "exports": tmp_path / "exports",
        "logs": tmp_path / "logs",
        "backups": tmp_path / "backups",
    }
    for name, directory in dirs.items():
        if name != "root":
            directory.mkdir(parents=True, exist_ok=True)
    monkeypatch.setenv("CAD_RUNTIME_ROOT", str(tmp_path))
    monkeypatch.setenv("CAD_PROJECTS_DIR", str(dirs["projects"]))
    monkeypatch.setenv("CAD_PROJECTS_ARCHIVE_DIR", str(dirs["archive"]))
    monkeypatch.setenv("CAD_UPLOAD_DIR", str(dirs["uploads"]))
    monkeypatch.setenv("CAD_PROJECT_PACKAGES_DIR", str(dirs["packages"]))
    monkeypatch.setenv("CAD_EXPORTS_DIR", str(dirs["exports"]))
    monkeypatch.setenv("CAD_LOG_DIR", str(dirs["logs"]))
    monkeypatch.setenv("CAD_BACKUPS_DIR", str(dirs["backups"]))
    monkeypatch.setenv("CAD_HOST", "127.0.0.1")
    monkeypatch.setenv("CAD_ALLOWED_HOSTS", "testserver")
    monkeypatch.setenv("CAD_DEV_ORIGINS", DEV_ORIGIN)
    monkeypatch.delenv("CAD_LAN_MODE", raising=False)
    monkeypatch.delenv("CAD_ACCESS_TOKEN", raising=False)

    # 先解析策略，再重载依赖它的模块
    import security

    security.set_policy(None)
    reload_backend(dirs)

    import main

    with TestClient(main.app, base_url="http://127.0.0.1") as test_client:
        yield test_client


def test_vite_dev_origin_is_allowed(dev_origin_client):
    response = dev_origin_client.get("/api/projects", headers={"Origin": DEV_ORIGIN})
    assert response.status_code == 200, response.text
    assert response.headers.get("access-control-allow-origin") == DEV_ORIGIN


def test_unlisted_origin_is_rejected(dev_origin_client):
    response = dev_origin_client.get("/api/projects", headers={"Origin": "http://127.0.0.1:5999"})
    assert response.status_code == 403
    assert response.json()["code"] == "origin_not_allowed"


def test_preflight_for_dev_origin(dev_origin_client):
    response = dev_origin_client.options(
        "/api/projects",
        headers={
            "Origin": DEV_ORIGIN,
            "Access-Control-Request-Method": "POST",
            "Access-Control-Request-Headers": "content-type",
        },
    )
    assert response.status_code in {200, 204}
    assert response.headers.get("access-control-allow-origin") == DEV_ORIGIN


def test_default_dev_origins_include_vite_ports():
    import security

    policy = security.load_access_policy({})
    assert "http://127.0.0.1:5173" in policy.dev_origins
    assert "http://localhost:5173" in policy.dev_origins


def test_wildcard_origin_is_not_configured():
    """回归：不得再对任意 Origin 放开。"""
    import security

    policy = security.load_access_policy({})
    assert "*" not in policy.dev_origins
