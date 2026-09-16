"""pytest 公共装置。

要点：
- 运行时根目录指向**临时目录**（`CAD_RUNTIME_ROOT`），绝不触碰开发机上被忽略的
  `backend/projects/`、`backend/uploads/` 等真实业务目录。
- `storage` 在导入时读取环境变量，因此这里在导入任何后端模块之前完成设置，
  并让 `main` 在运行时导入（避免导入顺序造成的路径错配）。
"""

from __future__ import annotations

import os
import shutil
import sys
import tempfile
from pathlib import Path
from typing import Iterator

import pytest

ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"

for path in (str(ROOT), str(BACKEND)):
    if path not in sys.path:
        sys.path.insert(0, path)

_TEMP_HOME = Path(tempfile.mkdtemp(prefix="cad-test-runtime-"))
os.environ.setdefault("CAD_RUNTIME_ROOT", str(_TEMP_HOME))


@pytest.fixture(scope="session")
def runtime_root() -> Path:
    return Path(os.environ["CAD_RUNTIME_ROOT"])


@pytest.fixture(scope="session", autouse=True)
def _cleanup_runtime() -> Iterator[None]:
    yield
    if Path(os.environ.get("CAD_RUNTIME_ROOT", "")).name.startswith("cad-test-runtime-"):
        shutil.rmtree(os.environ["CAD_RUNTIME_ROOT"], ignore_errors=True)


_LOADED_PATHS: dict[str, set[str]] = {"value": set()}

# 依赖 storage 的模块必须自底向上重载，否则会持有旧 storage 对象的路径绑定。
_RELOAD_ORDER = (
    "path_policy",
    "parser.dxf_units",
    "parser.dxf_geometry",
    "storage",
    "parser.dxf_reader",
    "semantic.rule_engine",
    "placement",
    "capabilities",
    "api.projects",
    "api.parse",
    "api.upload",
    "api.visual_audit",
    "api.replay",
    "main",
)


def reload_backend(dirs: dict[str, Path]) -> None:
    """把所有后端模块的路径绑定切到给定目录（幂等）。"""
    import importlib

    key = "|".join(str(dirs[name]) for name in sorted(dirs))
    if key in _LOADED_PATHS["value"]:
        return
    for name in _RELOAD_ORDER:
        module = sys.modules.get(name)
        if module is not None:
            importlib.reload(module)
    _LOADED_PATHS["value"].add(key)


@pytest.fixture()
def clean_runtime(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[dict[str, Path]]:
    """每个测试一套独立的项目/上传/导出目录，并重载 storage 与依赖模块。"""
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
    monkeypatch.delenv("CAD_SCOPE_PROJECT_ID", raising=False)

    reload_backend(dirs)
    yield dirs


def _load_app(monkeypatch: pytest.MonkeyPatch):
    import importlib

    import security

    monkeypatch.setenv("CAD_HOST", "127.0.0.1")
    monkeypatch.delenv("CAD_LAN_MODE", raising=False)
    # TestClient 使用的 Host 是 testserver；显式登记为允许的主机，避免为测试放宽生产默认值。
    monkeypatch.setenv("CAD_ALLOWED_HOSTS", "testserver")
    security.set_policy(None)

    import main

    importlib.reload(main)
    return main


@pytest.fixture()
def client(clean_runtime: dict[str, Path], monkeypatch: pytest.MonkeyPatch):
    """回环访问策略下的 TestClient（需要 httpx）。"""
    from fastapi.testclient import TestClient

    monkeypatch.delenv("CAD_ACCESS_TOKEN", raising=False)
    monkeypatch.delenv("CAD_TOKEN_REQUIRED", raising=False)
    main = _load_app(monkeypatch)
    replay_module = sys.modules.get("api.replay")
    if replay_module is not None and hasattr(replay_module, "_state"):
        replay_module._state.update({"running": False, "job_id": None, "process": None, "project_id": None, "drawing_id": None})
    with TestClient(main.app, base_url="http://127.0.0.1") as test_client:
        yield test_client


@pytest.fixture()
def token_client(clean_runtime: dict[str, Path], monkeypatch: pytest.MonkeyPatch):
    """要求访问令牌的 TestClient。"""
    from fastapi.testclient import TestClient

    token = "test-token-1234567890"
    monkeypatch.setenv("CAD_ACCESS_TOKEN", token)
    main = _load_app(monkeypatch)
    # replay 进程状态是模块级全局，测试间必须重置
    main_module_state = sys.modules.get("api.replay")
    if main_module_state is not None and hasattr(main_module_state, "_state"):
        main_module_state._state.update({"running": False, "job_id": None, "process": None})
    with TestClient(main.app, base_url="http://127.0.0.1") as test_client:
        test_client.headers.update({"X-CAD-Token": token})
        yield test_client
