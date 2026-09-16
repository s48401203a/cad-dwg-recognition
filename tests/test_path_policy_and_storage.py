"""路径策略与存储可靠性测试。

覆盖：
- ID / 文件名收敛、越界路径、符号链接、跨平台路径、项目包相对引用。
- JSON 原子写入、并发 read-modify-write、损坏隔离、revision 冲突、写入中断。
"""

from __future__ import annotations

import json
import os
import threading
from pathlib import Path

import pytest

import path_policy

# 注意：conftest 会在每个测试前重载 path_policy，模块级 import 会绑定**旧**的类对象，
# 因此这里一律通过模块属性取用（否则 pytest.raises 匹配不上重载后的异常类型）。
resolve_within_roots = path_policy.resolve_within_roots


# --------------------------------------------------------------- ID 与文件名


@pytest.mark.parametrize("value", ["proj_abc123", "draw_1a2b3c4d5e", "a", "A-1_2", "x" * 64])
def test_safe_ids_accepted(value: str):
    assert path_policy.is_safe_id(value)


@pytest.mark.parametrize(
    "value",
    ["", " ", "../etc", "a/b", "a\\b", "a b", "..", ".", "x" * 65, "a\x00b", "-leading", None, 123, "café"],
)
def test_unsafe_ids_rejected(value):
    assert not path_policy.is_safe_id(value)


def test_validate_project_id_raises_on_traversal():
    with pytest.raises(path_policy.PathPolicyError) as excinfo:
        path_policy.validate_project_id("../../etc")
    assert excinfo.value.code == "invalid_id"


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("../../etc/passwd", "passwd"),
        ("..\\..\\windows\\system.ini", "system.ini"),
        ("C:\\Windows\\evil.dxf", "evil.dxf"),
        ("/etc/shadow", "shadow"),
        ("图纸 A.dxf", "图纸 A.dxf"),
        ("...hidden", "hidden"),
        ("", "drawing"),
        ("a" * 400 + ".dxf", None),  # 只断言长度受限
    ],
)
def test_sanitize_filename(raw: str, expected: str | None):
    cleaned = path_policy.sanitize_filename(raw)
    if expected is not None:
        assert cleaned == expected
    assert "/" not in cleaned and "\\" not in cleaned
    assert len(cleaned) <= 120


@pytest.mark.parametrize(
    "value",
    ["/etc/passwd", "../x", "a/b", "a\\b", "C:\\x", "~/x", "file:///x", "\\\\server\\share"],
)
def test_looks_like_path_detects_paths(value: str):
    assert path_policy.looks_like_path(value)


@pytest.mark.parametrize("value", ["proj_abc", "draw_123", "generic"])
def test_looks_like_path_accepts_plain_ids(value: str):
    assert not path_policy.looks_like_path(value)


# --------------------------------------------------------------- 允许根目录


def test_resolve_within_roots_accepts_inside(tmp_path: Path):
    root = tmp_path / "root"
    (root / "sub").mkdir(parents=True)
    target = root / "sub" / "f.json"
    target.write_text("{}", encoding="utf-8")
    assert resolve_within_roots(target, [root], must_exist=True) == target.resolve()


def test_resolve_within_roots_rejects_outside(tmp_path: Path):
    root = tmp_path / "root"
    root.mkdir()
    outside = tmp_path / "outside.json"
    outside.write_text("{}", encoding="utf-8")
    with pytest.raises(path_policy.PathPolicyError) as excinfo:
        resolve_within_roots(outside, [root])
    assert excinfo.value.code == "outside_allowed_roots"


def test_resolve_within_roots_rejects_dotdot_escape(tmp_path: Path):
    root = tmp_path / "root"
    (root / "a").mkdir(parents=True)
    with pytest.raises(path_policy.PathPolicyError):
        resolve_within_roots("../../etc/passwd", [root / "a"])


def test_resolve_within_roots_rejects_symlink_escape(tmp_path: Path):
    root = tmp_path / "root"
    root.mkdir()
    secret = tmp_path / "secret.json"
    secret.write_text('{"secret": 1}', encoding="utf-8")
    link = root / "link.json"
    try:
        link.symlink_to(secret)
    except (OSError, NotImplementedError):
        pytest.skip("当前平台不支持创建符号链接")
    assert link.exists(), "符号链接应指向存在的目标"
    with pytest.raises(path_policy.PathPolicyError) as excinfo:
        resolve_within_roots(link, [root], must_exist=True)
    assert excinfo.value.code in {"symlink_rejected", "outside_allowed_roots"}


@pytest.mark.parametrize("value", ["C:\\Windows\\System32", "\\\\server\\share\\x", "\\\\?\\C:\\x"])
def test_resolve_within_roots_rejects_cross_platform_absolute(tmp_path: Path, value: str):
    root = tmp_path / "root"
    root.mkdir()
    with pytest.raises(path_policy.PathPolicyError):
        resolve_within_roots(value, [root])


def test_resolve_within_roots_rejects_empty(tmp_path: Path):
    with pytest.raises(path_policy.PathPolicyError) as excinfo:
        resolve_within_roots("   ", [tmp_path])
    assert excinfo.value.code == "empty_path"


# --------------------------------------------------------------- 存储可靠性


@pytest.fixture()
def store(clean_runtime):
    import storage

    return storage


def test_atomic_write_leaves_no_temp_files(store, tmp_path: Path):
    target = tmp_path / "data.json"
    store.write_json(target, {"a": 1})
    assert json.loads(target.read_text(encoding="utf-8")) == {"a": 1}
    leftovers = [item.name for item in tmp_path.iterdir() if item.name.startswith(".data.json")]
    assert leftovers == [], f"不应留下临时文件: {leftovers}"


def test_write_interruption_keeps_previous_file_valid(store, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    target = tmp_path / "data.json"
    store.write_json(target, {"version": "old"})
    original = target.read_text(encoding="utf-8")

    real_replace = os.replace

    def failing_replace(src, dst):  # noqa: ANN001
        raise OSError("simulated crash during replace")

    monkeypatch.setattr(os, "replace", failing_replace)
    with pytest.raises(OSError):
        store.write_json(target, {"version": "new"})
    monkeypatch.setattr(os, "replace", real_replace)

    assert target.read_text(encoding="utf-8") == original, "中断后旧文件必须仍然有效"
    # 临时文件被清理
    assert [item.name for item in tmp_path.iterdir() if item.name.endswith(".tmp")] == []


def test_corrupt_json_is_quarantined_and_reported(store, tmp_path: Path):
    target = tmp_path / "broken.json"
    target.write_text("{ not json", encoding="utf-8")
    with pytest.raises(store.CorruptJsonError) as excinfo:
        store.read_json_strict(target, None)
    assert excinfo.value.quarantine_path is not None
    assert excinfo.value.quarantine_path.exists()
    assert not target.exists(), "损坏文件必须被移走，避免被当成空数据再次覆盖"
    reason = excinfo.value.quarantine_path.with_suffix(excinfo.value.quarantine_path.suffix + ".reason.txt")
    assert reason.exists()


def test_concurrent_register_upload_loses_no_records(store, clean_runtime):
    """并发注册上传：read-modify-write 必须加锁，不能丢更新。"""
    errors: list[BaseException] = []

    def worker(index: int) -> None:
        try:
            store.register_upload(f"file_{index}", {"file_id": f"file_{index}", "n": index})
        except BaseException as exc:  # pragma: no cover
            errors.append(exc)

    threads = [threading.Thread(target=worker, args=(index,)) for index in range(40)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert not errors, errors
    data = store.read_uploads_strict()
    assert len(data) == 40, f"并发写入丢失记录: {len(data)}"
    for index in range(40):
        assert data[f"file_{index}"]["n"] == index


def test_concurrent_project_save_keeps_revision_monotonic(store, clean_runtime):
    project_id = "proj_concurrent1"
    store.save_project({"id": project_id, "name": "并发", "save_dir": str(store.project_dir(project_id)), "drawings": []})
    seen: list[int] = []
    errors: list[BaseException] = []
    lock = threading.Lock()

    def worker(index: int) -> None:
        try:
            meta = store.load_project(project_id)
            meta["drawings"] = list(meta.get("drawings") or []) + [{"id": f"draw_{index}"}]
            saved = store.save_project(meta)
            with lock:
                seen.append(saved["revision"])
        except BaseException as exc:  # pragma: no cover
            errors.append(exc)

    threads = [threading.Thread(target=worker, args=(index,)) for index in range(20)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert not errors, errors
    assert len(set(seen)) == len(seen), f"revision 必须唯一: {sorted(seen)}"
    final = store.load_project(project_id)
    assert final["revision"] == max(seen)


def test_revision_conflict_detected(store, clean_runtime):
    project_id = "proj_rev1"
    store.save_project({"id": project_id, "name": "rev", "save_dir": str(store.project_dir(project_id)), "drawings": []})
    first = store.load_project(project_id)
    stale = first["revision"]
    # 另一个会话先保存
    first["name"] = "第二个会话"
    store.save_project(first)

    stale_meta = dict(first)
    stale_meta["name"] = "旧版本"
    with pytest.raises(store.RevisionConflict):
        store.save_project(stale_meta, expected_revision=stale)
    assert store.load_project(project_id)["name"] == "第二个会话", "旧版本不得覆盖新修改"


def test_project_dir_rejects_traversal_id(store):
    with pytest.raises(path_policy.PathPolicyError):
        store.project_dir("../../etc")
    with pytest.raises(path_policy.PathPolicyError):
        store.archived_project_dir("a/b")


def test_save_dir_outside_managed_root_is_not_a_trusted_root(store, clean_runtime):
    """即使 meta.json 被写入任意 save_dir，也不能把它变成可读根。"""
    project_id = "proj_evilsave"
    meta = {"id": project_id, "name": "evil", "save_dir": "/etc", "drawings": []}
    store.save_project(meta)
    roots = [Path(item).resolve() for item in store.allowed_roots_for_meta(store.load_project(project_id))]
    assert Path("/etc").resolve() not in roots
    assert all(str(item).startswith(str(clean_runtime["root"])) for item in roots)


def test_extra_allowed_roots_requires_explicit_opt_in(store, clean_runtime, monkeypatch, tmp_path):
    """受管目录之外的本地项目需要通过 CAD_ALLOWED_PROJECT_ROOTS 显式授权。"""
    external = clean_runtime["root"] / "external-project"
    external.mkdir(parents=True, exist_ok=True)
    meta = {"id": "proj_external1", "name": "外部", "save_dir": str(external), "drawings": []}

    roots_without = [Path(item).resolve() for item in store.allowed_roots_for_meta(meta)]
    assert external.resolve() not in roots_without

    monkeypatch.setenv("CAD_ALLOWED_PROJECT_ROOTS", str(external))
    roots_with = [Path(item).resolve() for item in store.allowed_roots_for_meta(meta)]
    assert external.resolve() in roots_with


def test_legacy_layout_migrates_with_explicit_trust(store, clean_runtime, monkeypatch):
    """显式授权后，旧布局（save_dir 在受管目录外）也能迁移到规范位置。"""
    project_id = "proj_legacy2"
    save_dir = clean_runtime["root"] / "legacy-external"
    legacy = save_dir / "draw_legacy2" / "semantic.json"
    legacy.parent.mkdir(parents=True, exist_ok=True)
    legacy.write_text('{"stats": {"devices": 3}}', encoding="utf-8")
    monkeypatch.setenv("CAD_ALLOWED_PROJECT_ROOTS", str(save_dir))

    meta = {
        "id": project_id,
        "name": "legacy-external",
        "save_dir": str(save_dir),
        "drawings": [{"id": "draw_legacy2", "semantic_path": str(legacy)}],
    }
    store.save_project(meta)
    loaded = store.load_project(project_id)
    migrations = store.migrate_drawing_paths(loaded)
    assert migrations, "应产生迁移记录"
    canonical = store.drawing_semantic_path(project_id, "draw_legacy2")
    assert canonical.exists()
    assert loaded["drawings"][0]["semantic_path"] == str(canonical)


def test_project_package_absolute_reference_is_rejected(store, clean_runtime, tmp_path: Path):
    package = clean_runtime["packages"] / "pkg1"
    package.mkdir(parents=True, exist_ok=True)
    secret = tmp_path / "outside-semantic.json"
    secret.write_text('{"devices": []}', encoding="utf-8")
    manifest = {
        "project_id": "proj_pkg1",
        "name": "包",
        "save_dir": ".",
        "drawings": [{"id": "draw_pkg1", "semantic_path": str(secret)}],
    }
    (package / "project.json").write_text(json.dumps(manifest), encoding="utf-8")
    meta = store.read_project_package(package)
    assert meta is not None
    # 绝对路径引用必须被丢弃，不能变成可读路径
    assert all("semantic_path" not in drawing for drawing in meta["drawings"])


def test_project_package_dotdot_reference_is_rejected(store, clean_runtime):
    package = clean_runtime["packages"] / "pkg2"
    package.mkdir(parents=True, exist_ok=True)
    manifest = {
        "project_id": "proj_pkg2",
        "name": "包",
        "save_dir": ".",
        "source_dir": "../../etc",
        "drawings": [{"id": "draw_pkg2", "semantic_path": "../../x/semantic.json"}],
    }
    (package / "project.json").write_text(json.dumps(manifest), encoding="utf-8")
    meta = store.read_project_package(package)
    assert meta["source_dir"] is None
    assert all("semantic_path" not in drawing for drawing in meta["drawings"])


def test_import_project_package_outside_root_is_rejected(store, clean_runtime, tmp_path: Path):
    outsider = tmp_path / "outside-package"
    outsider.mkdir()
    (outsider / "project.json").write_text(json.dumps({"project_id": "proj_out", "name": "x"}), encoding="utf-8")
    with pytest.raises(path_policy.PathPolicyError):
        store.import_project_package(outsider)


def test_migrate_legacy_drawing_layout(store, clean_runtime, monkeypatch):
    """旧布局 <save_dir>/<drawing_id>/semantic.json 会被复制到规范位置（需显式授权该根）。"""
    project_id = "proj_legacy1"
    save_dir = clean_runtime["root"] / "legacy-save"
    legacy = save_dir / "draw_legacy1" / "semantic.json"
    legacy.parent.mkdir(parents=True, exist_ok=True)
    legacy.write_text('{"stats": {}}', encoding="utf-8")

    monkeypatch.setenv("CAD_ALLOWED_PROJECT_ROOTS", str(save_dir))
    meta = {
        "id": project_id,
        "name": "legacy",
        "save_dir": str(save_dir),
        "drawings": [{"id": "draw_legacy1", "semantic_path": str(legacy)}],
    }
    store.save_project(meta)
    loaded = store.load_project(project_id)
    migrations = store.migrate_drawing_paths(loaded)
    assert migrations, "应产生迁移记录"
    canonical = store.drawing_semantic_path(project_id, "draw_legacy1")
    assert canonical.exists()
    assert json.loads(canonical.read_text(encoding="utf-8")) == {"stats": {}}
    assert loaded["drawings"][0]["semantic_path"] == str(canonical)


def test_migrate_preserves_manually_placed_overrides(store, clean_runtime, tmp_path: Path):
    """重新解析不得丢失人工校正：overrides 与 semantic.json 是分开的。"""
    import placement

    project_id = "proj_keep_overrides"
    store.save_project(
        {
            "id": project_id,
            "name": "摆放试验场",
            "save_dir": str(store.project_dir(project_id)),
            "drawings": [],
            "placement_studio": True,
        }
    )
    meta = store.load_project(project_id)
    placement.ensure_placement_scene(meta)
    placement.save_overrides(
        meta,
        {
            "site": {"length_m": 42},
            "instances": [
                {
                    "id": "ap1",
                    "catalog_id": "network.ap.warehouse",
                    "kind": "device",
                    "geometry": {"type": "point", "position": {"x": 100, "y": 200}},
                    "attributes": {"install_height_m": 6.0},
                }
            ],
            "circuits": [],
        },
    )
    before = placement.load_overrides(meta)
    assert before["instances"][0]["id"] == "ap1"

    # 模拟重新解析：只重建 semantic.json
    drawing = meta["drawings"][0]
    store.write_json(Path(drawing["semantic_path"]), {"drawing_meta": {"source": "placement_studio"}, "devices": []})
    after = placement.load_overrides(meta)
    assert after["instances"][0]["id"] == "ap1", "重新解析后人工摆放必须保留"
    assert after["site"]["length_m"] == 42


def test_overrides_rejects_invalid_payloads(store, clean_runtime):
    import placement

    project_id = "proj_validate_overrides"
    meta = {"id": project_id, "name": "x", "save_dir": str(store.project_dir(project_id)), "status": "active"}
    store.save_project(meta)

    with pytest.raises(placement.OverrideValidationError):
        placement.save_overrides(meta, {"instances": [{"id": "../evil"}]})
    with pytest.raises(placement.OverrideValidationError):
        placement.save_overrides(
            meta,
            {"instances": [{"id": "a", "geometry": {"type": "point", "position": {"x": float("nan"), "y": 0}}}]},
        )
    with pytest.raises(placement.OverrideValidationError):
        placement.save_overrides(
            meta,
            {"instances": [{"id": "a", "geometry": {"type": "point", "position": {"x": float("inf"), "y": 0}}}]},
        )
    with pytest.raises(placement.OverrideValidationError):
        placement.save_overrides(meta, {"instances": [{"id": "a", "kind": "not-a-kind"}]})
    with pytest.raises(placement.OverrideValidationError):
        placement.save_overrides(meta, {"circuits": [{"id": "c1", "points": [{"x": 0, "y": 0}]}]})

    # 合法数据通过，并带上递增 revision
    saved = placement.save_overrides(
        meta,
        {
            "instances": [
                {
                    "id": "ap1",
                    "kind": "device",
                    "geometry": {"type": "point", "position": {"x": 1, "y": 2}},
                }
            ],
            "circuits": [{"id": "c1", "points": [{"x": 0, "y": 0}, {"x": 10, "y": 0}]}],
        },
    )
    assert saved["revision"] == 1
    assert placement.load_overrides(meta)["revision"] == 1


def test_overrides_revision_conflict(store, clean_runtime):
    import placement

    project_id = "proj_overrides_rev"
    meta = {"id": project_id, "name": "x", "save_dir": str(store.project_dir(project_id)), "status": "active"}
    store.save_project(meta)
    placement.save_overrides(meta, {"instances": [], "circuits": []})
    stale = placement.load_overrides(meta)["revision"]

    placement.save_overrides(meta, {"instances": [{"id": "later"}], "circuits": []})
    with pytest.raises(placement.RevisionConflict):
        placement.save_overrides(meta, {"instances": [], "circuits": []}, expected_revision=stale)
    assert placement.load_overrides(meta)["instances"][0]["id"] == "later"
