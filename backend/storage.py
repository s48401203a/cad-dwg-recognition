"""项目/上传/项目包持久化。

可靠性约定：
- 所有 JSON 写入走「同目录临时文件 + fsync + os.replace」，进程中断不会留下半截文件。
- read-modify-write 全过程持有文件锁（同进程 threading.Lock + 跨进程 flock），并发不丢更新。
- JSON 损坏不再静默当作空数据：隔离到 `*.corrupt-<时间戳>` 并抛出明确错误，
  避免「损坏 -> 当空 -> 覆盖」把用户数据彻底抹掉。
- 项目与 overrides 带 revision，旧版本写入会抛 RevisionConflict 而不是覆盖新修改。
- 所有磁盘路径在使用前经过 path_policy 的允许根目录校验。
"""

from __future__ import annotations

import contextlib
import errno
import json
import os
import shutil
import tempfile
import threading
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Iterator

from path_policy import (
    PathPolicyError,
    is_safe_id,
    resolve_within_roots,
    sanitize_filename,
    validate_project_id,
)

BASE_DIR = Path(__file__).resolve().parent
ROOT_DIR = BASE_DIR.parent


def _env_path(name: str, default: Path) -> Path:
    value = os.environ.get(name)
    return Path(value).expanduser() if value else default


RUNTIME_ROOT = Path(os.environ["CAD_RUNTIME_ROOT"]).expanduser() if os.environ.get("CAD_RUNTIME_ROOT") else BASE_DIR
_runtime_isolated = bool(os.environ.get("CAD_RUNTIME_ROOT"))
UPLOAD_DIR = _env_path("CAD_UPLOAD_DIR", RUNTIME_ROOT / "uploads")
LOG_DIR = _env_path("CAD_LOG_DIR", RUNTIME_ROOT / "logs")
PROJECTS_DIR = _env_path("CAD_PROJECTS_DIR", RUNTIME_ROOT / "projects")
PROJECTS_ARCHIVE_DIR = _env_path("CAD_PROJECTS_ARCHIVE_DIR", RUNTIME_ROOT / "projects-archive")
_backup_root = _env_path("CAD_BACKUPS_DIR", RUNTIME_ROOT / "backups" if _runtime_isolated else BASE_DIR.parent / "backups")
DELETED_PROJECT_BACKUP_DIR = _backup_root / "deleted-projects"
ARCHIVE_CONFLICT_BACKUP_DIR = _backup_root / "archive-conflicts"
PROJECT_PACKAGES_DIR = _env_path("CAD_PROJECT_PACKAGES_DIR", RUNTIME_ROOT / "project-packages" if _runtime_isolated else ROOT_DIR / "projects")
PROJECT_PACKAGE_MANIFEST = "project.json"
UPLOAD_INDEX = UPLOAD_DIR / "index.json"
META_FILENAME = "meta.json"
SEMANTIC_FILENAME = "semantic.json"

for directory in (
    UPLOAD_DIR,
    LOG_DIR,
    PROJECTS_DIR,
    PROJECTS_ARCHIVE_DIR,
    DELETED_PROJECT_BACKUP_DIR,
    ARCHIVE_CONFLICT_BACKUP_DIR,
    PROJECT_PACKAGES_DIR,
):
    directory.mkdir(parents=True, exist_ok=True)


class StorageError(RuntimeError):
    """存储层基类错误。"""


class CorruptJsonError(StorageError):
    """JSON 文件存在但无法解析。附带隔离文件路径，供用户恢复。"""

    def __init__(self, path: Path, quarantine_path: Path | None, detail: str) -> None:
        self.path = path
        self.quarantine_path = quarantine_path
        message = f"JSON 文件损坏，无法解析: {path} ({detail})"
        if quarantine_path:
            message += f"；原文件已隔离到 {quarantine_path}"
        super().__init__(message)


class RevisionConflict(StorageError):
    """乐观并发冲突：调用方持有的是旧 revision。"""

    def __init__(self, path: Path, expected: Any, actual: Any) -> None:
        self.path = path
        self.expected = expected
        self.actual = actual
        super().__init__(f"数据已被其他会话修改（期望 revision={expected!r}，当前 revision={actual!r}），请刷新后重试")


# ---------------------------------------------------------------- 锁

_LOCKS: dict[str, threading.RLock] = {}
_LOCKS_GUARD = threading.Lock()


def _thread_lock_for(path: Path) -> threading.RLock:
    key = str(path)
    with _LOCKS_GUARD:
        lock = _LOCKS.get(key)
        if lock is None:
            lock = threading.RLock()
            _LOCKS[key] = lock
        return lock


@contextlib.contextmanager
def file_lock(path: Path) -> Iterator[None]:
    """对单个 JSON 文件加锁，覆盖整个 read-modify-write。

    同进程用可重入锁；跨进程在 POSIX 上用 flock。Windows 无 flock 时退化为进程内锁
    （本项目默认单进程 uvicorn；多进程部署需外部锁，已在文档中说明）。
    """
    lock = _thread_lock_for(path)
    with lock:
        lock_path = path.with_suffix(path.suffix + ".lock")
        handle = None
        try:
            lock_path.parent.mkdir(parents=True, exist_ok=True)
            handle = open(lock_path, "a+b")
            if os.name == "posix":
                import fcntl

                fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
        except OSError:
            if handle is not None:
                with contextlib.suppress(OSError):
                    handle.close()
            handle = None
        try:
            yield
        finally:
            if handle is not None:
                try:
                    if os.name == "posix":
                        import fcntl

                        fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
                except OSError:
                    pass
                with contextlib.suppress(OSError):
                    handle.close()


# ---------------------------------------------------------------- JSON 读写


def now_iso() -> str:
    return datetime.now().isoformat(timespec="seconds")


def _quarantine(path: Path, detail: str) -> Path | None:
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    target = path.with_name(f"{path.name}.corrupt-{stamp}")
    try:
        shutil.move(str(path), str(target))
    except OSError:
        return None
    reason = path.with_name(f"{path.name}.corrupt-{stamp}.reason.txt")
    with contextlib.suppress(OSError):
        reason.write_text(f"{now_iso()} {detail}\n", encoding="utf-8")
    return target


def write_json_atomic(path: Path, data: Any) -> None:
    """原子写入 JSON：临时文件 + fsync + os.replace。"""
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(data, ensure_ascii=False, indent=2)
    fd, tmp_name = tempfile.mkstemp(dir=str(path.parent), prefix=f".{path.name}.", suffix=".tmp")
    tmp_path = Path(tmp_name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp_path, path)
    except BaseException:
        with contextlib.suppress(OSError):
            tmp_path.unlink()
        raise
    if os.name == "posix":
        # 让替换结果落盘，避免断电后目录项丢失
        with contextlib.suppress(OSError):
            dir_fd = os.open(str(path.parent), os.O_RDONLY)
            try:
                os.fsync(dir_fd)
            finally:
                os.close(dir_fd)


def write_json(path: Path, data: Any) -> None:
    write_json_atomic(path, data)


def read_json_strict(path: Path, default: Any = None, *, quarantine: bool = True) -> Any:
    """读取 JSON；文件存在但损坏时抛出 CorruptJsonError（可先隔离）。"""
    if not path.exists():
        return default
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise StorageError(f"读取失败: {path} ({exc})") from exc
    if not text.strip():
        return default
    try:
        return json.loads(text)
    except json.JSONDecodeError as exc:
        quarantined = _quarantine(path, f"JSONDecodeError: {exc}") if quarantine else None
        raise CorruptJsonError(path, quarantined, str(exc)) from exc


def read_json(path: Path | None, default: Any) -> Any:
    """兼容旧调用：损坏时隔离并返回默认值，但记录诊断。

    新代码应优先使用 read_json_strict，只有在"损坏也不能中断主流程"的只读探测场景
    才使用本函数。
    """
    if path is None:
        return default
    try:
        return read_json_strict(path, default)
    except CorruptJsonError:
        return default


def read_uploads_strict() -> dict[str, Any]:
    data = read_json_strict(UPLOAD_INDEX, {})
    if not isinstance(data, dict):
        raise StorageError(f"上传索引格式非法（应为对象）: {UPLOAD_INDEX}")
    return data


def load_uploads() -> dict[str, Any]:
    try:
        return read_uploads_strict()
    except (CorruptJsonError, StorageError):
        return {}


def save_uploads(data: dict[str, Any]) -> None:
    write_json(UPLOAD_INDEX, data)


def register_upload(file_id: str, record: dict[str, Any]) -> None:
    """注册上传记录：整个 read-modify-write 在文件锁内完成，并发不丢更新。"""
    with file_lock(UPLOAD_INDEX):
        uploads = read_uploads_strict()
        uploads[file_id] = record
        write_json(UPLOAD_INDEX, uploads)


def update_upload(file_id: str, mutate: Callable[[dict[str, Any]], None]) -> dict[str, Any] | None:
    with file_lock(UPLOAD_INDEX):
        uploads = read_uploads_strict()
        record = uploads.get(file_id)
        if not isinstance(record, dict):
            return None
        mutate(record)
        write_json(UPLOAD_INDEX, uploads)
        return record


def get_upload(file_id: str) -> dict[str, Any] | None:
    record = load_uploads().get(file_id)
    return record if isinstance(record, dict) else None


# ---------------------------------------------------------------- 项目目录


def _allowed_project_roots() -> list[Path]:
    return [PROJECTS_DIR, PROJECTS_ARCHIVE_DIR, PROJECT_PACKAGES_DIR, UPLOAD_DIR]


def project_dir(project_id: str) -> Path:
    """项目目录：ID 先校验再拼接，杜绝 `../` 逃逸。"""
    safe = validate_project_id(project_id)
    return PROJECTS_DIR / safe


def archived_project_dir(project_id: str) -> Path:
    safe = validate_project_id(project_id)
    return PROJECTS_ARCHIVE_DIR / safe


def project_storage_dir(meta: dict[str, Any]) -> Path:
    return archived_project_dir(meta["id"]) if is_project_archived(meta) else project_dir(meta["id"])


def drawing_semantic_path(project_id: str, drawing_id: str, *, archived: bool = False) -> Path:
    """图纸 semantic.json 的规范位置（服务端唯一决定）。"""
    safe_project = validate_project_id(project_id)
    safe_drawing = validate_project_id(drawing_id)
    root = PROJECTS_ARCHIVE_DIR if archived else PROJECTS_DIR
    return root / safe_project / "drawings" / safe_drawing / SEMANTIC_FILENAME


def extra_allowed_roots() -> list[Path]:
    """操作者显式登记为可信的额外根目录（`CAD_ALLOWED_PROJECT_ROOTS`，冒号/分号分隔）。

    用途：历史项目保存在受管目录之外时，需要一次显式的、由部署者给出的授权，
    而不是让项目元数据自己决定能读哪些路径。默认（未设置）时该列表为空。
    """
    raw = os.environ.get("CAD_ALLOWED_PROJECT_ROOTS")
    if not raw:
        return []
    roots: list[Path] = []
    for chunk in raw.replace(";", os.pathsep).split(os.pathsep):
        text = chunk.strip()
        if not text:
            continue
        candidate = Path(text).expanduser()
        try:
            resolved = candidate.resolve()
        except OSError:
            continue
        if resolved.is_dir() and resolved not in roots:
            roots.append(resolved)
    return roots


def allowed_roots_for_meta(meta: dict[str, Any] | None) -> list[Path]:
    """某个项目允许访问的根目录集合。

    关键约束：`save_dir` / `package_dir` **不是信任来源**。它们只有在自身已经位于
    受管根目录（projects / projects-archive / project-packages / uploads）或操作者
    显式登记的可信根目录之内时，才会被加入允许集合。这样即使 meta.json 被写入
    `save_dir: /etc`，也无法把它变成可读根。
    """
    managed = list(_allowed_project_roots())
    managed_resolved = [Path(root).expanduser() for root in managed]
    extra = extra_allowed_roots()
    roots: list[Path] = list(managed)
    roots.extend(extra)
    if not meta:
        return roots
    storage_dir = project_storage_dir(meta)
    roots.append(storage_dir)
    trusted = [_resolve_safe(root) for root in [*managed_resolved, *extra]]
    trusted = [root for root in trusted if root is not None]
    for key in ("save_dir", "package_dir", "source_dir"):
        value = meta.get(key)
        if not value:
            continue
        candidate = _resolve_safe(Path(str(value)).expanduser())
        if candidate is None:
            continue
        if any(_path_inside(candidate, root) for root in trusted):
            roots.append(candidate)
    return roots


def _resolve_safe(path: Path) -> Path | None:
    try:
        return path.resolve()
    except OSError:
        return None


def _path_inside(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
        return True
    except ValueError:
        return False


def is_project_archived(meta: dict[str, Any] | None) -> bool:
    return bool(meta and meta.get("status") == "archived")


def normalize_project_meta(meta: dict[str, Any] | None, status: str = "active") -> dict[str, Any] | None:
    if not meta:
        return None
    meta.setdefault("status", status)
    meta.setdefault("revision", 1)
    return meta


def project_meta_path(project_id: str, *, archived: bool = False) -> Path:
    return (archived_project_dir(project_id) if archived else project_dir(project_id)) / META_FILENAME


def load_project(project_id: str, include_archived: bool = False) -> dict[str, Any] | None:
    """读取项目 meta。

    语义：
    - 项目目录存在 -> 必须能解析出 meta；损坏时抛 CorruptJsonError（并已隔离原文件），
      绝不返回 None 让调用方误以为「项目不存在」。
    - 项目目录不存在 -> 回退到项目包发现与归档目录查找。
    """
    try:
        validate_project_id(project_id)
    except PathPolicyError:
        return None
    meta = project_meta_path(project_id)
    if meta.exists():
        try:
            data = read_json_strict(meta, None)
        except CorruptJsonError:
            raise
        if data is None:
            raise StorageError(f"项目元数据为空: {meta}")
        return normalize_project_meta(data, "active") if isinstance(data, dict) else None
    package_meta = load_project_package(project_id)
    if package_meta:
        return package_meta
    if not include_archived:
        return None
    archived_meta = archived_project_dir(project_id) / META_FILENAME
    if not archived_meta.exists():
        return None
    return normalize_project_meta(read_json_strict(archived_meta, None), "archived")


def load_project_strict(project_id: str, include_archived: bool = False) -> dict[str, Any] | None:
    """与 load_project 相同，但项目 meta.json 损坏时抛出 CorruptJsonError。"""
    try:
        validate_project_id(project_id)
    except PathPolicyError:
        return None
    meta_path = project_meta_path(project_id)
    if meta_path.exists():
        return normalize_project_meta(read_json_strict(meta_path, None), "active")
    return load_project(project_id, include_archived=include_archived)


def save_project(meta: dict[str, Any], *, expected_revision: Any = None, bump_revision: bool = True) -> dict[str, Any]:
    """保存项目 meta。

    并发控制：
    - 传入 expected_revision 时做乐观并发校验，不匹配抛 RevisionConflict。
    - 未传时按「读当前 revision + 1」写入，保证 revision 单调递增。

    兼容性：接受旧 meta（无 revision），首次保存后补齐为整数。
    """
    project_id = validate_project_id(str(meta.get("id") or ""))
    archived = is_project_archived(meta)
    target_dir = archived_project_dir(project_id) if archived else project_dir(project_id)
    meta_path = target_dir / META_FILENAME
    with file_lock(meta_path):
        current: dict[str, Any] | None = None
        if meta_path.exists():
            current = read_json_strict(meta_path, None)
            if not isinstance(current, dict):
                current = None
        current_revision = (current or {}).get("revision")
        if expected_revision is not None:
            normalized_expected = _normalize_revision(expected_revision)
            normalized_current = _normalize_revision(current_revision)
            if current is not None and normalized_current != normalized_expected:
                raise RevisionConflict(meta_path, normalized_expected, normalized_current)
        if bump_revision:
            base = _normalize_revision(current_revision) if current is not None else 0
            meta["revision"] = base + 1
        else:
            meta.setdefault("revision", _normalize_revision(current_revision))
        write_json(meta_path, meta)
    if not archived:
        write_project_package_manifest(meta)
    return meta


def _normalize_revision(value: Any) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def list_projects(include_archived: bool = False) -> list[dict[str, Any]]:
    projects: list[dict[str, Any]] = []
    seen: set[str] = set()
    for child in sorted(PROJECTS_DIR.iterdir(), key=lambda p: p.stat().st_mtime, reverse=True):
        if not child.is_dir():
            continue
        meta = read_json(child / META_FILENAME, None)
        if meta:
            normalized = normalize_project_meta(meta, "active")
            if normalized:
                projects.append(normalized)
                seen.add(normalized["id"])
    for meta in discover_project_packages():
        if meta["id"] not in seen and (include_archived or not is_project_archived(meta)):
            projects.append(meta)
            seen.add(meta["id"])
    if include_archived:
        for child in sorted(PROJECTS_ARCHIVE_DIR.iterdir(), key=lambda p: p.stat().st_mtime, reverse=True):
            if not child.is_dir():
                continue
            meta = read_json(child / META_FILENAME, None)
            if meta:
                normalized = normalize_project_meta(meta, "archived")
                if normalized and normalized["id"] not in seen:
                    projects.append(normalized)
                    seen.add(normalized["id"])
    projects.sort(key=lambda item: item.get("updated_at") or item.get("archived_at") or item.get("created_at") or "", reverse=True)
    return projects


# ---------------------------------------------------------------- 项目包


def discover_project_packages(root_dir: Path | None = None) -> list[dict[str, Any]]:
    root = Path(root_dir) if root_dir else PROJECT_PACKAGES_DIR
    packages: list[dict[str, Any]] = []
    if not root.exists():
        return packages
    manifests = sorted(root.rglob(PROJECT_PACKAGE_MANIFEST), key=lambda p: p.stat().st_mtime, reverse=True)
    for manifest in manifests:
        package_dir = manifest.parent
        if package_dir == root:
            continue
        meta = read_project_package(package_dir)
        if meta:
            packages.append(meta)
    return packages


def load_project_package(project_id: str) -> dict[str, Any] | None:
    if not is_safe_id(project_id):
        return None
    for meta in discover_project_packages():
        if meta.get("id") == project_id:
            return meta
    return None


def resolve_package_reference(package_dir: str | Path, value: Any, *, label: str = "项目包路径") -> Path:
    """解析项目包内的相对引用。

    项目包只能通过 **包目录内的相对路径** 引用文件：绝对路径、`..` 逃逸、
    符号链接越界一律拒绝。历史项目包里登记的绝对路径不会再被信任为可读。
    """
    package_root = Path(package_dir).expanduser()
    if not str(value).strip():
        raise PathPolicyError(f"{label} 不能为空", code="empty_path")
    text = str(value).strip().replace("\x00", "")
    candidate = Path(text).expanduser()
    if candidate.is_absolute() or text.startswith("\\\\") or (len(text) > 1 and text[1] == ":"):
        raise PathPolicyError(f"{label} 必须是项目包内的相对路径: {text}", code="absolute_package_path")
    return resolve_within_roots(candidate, [package_root], label=label)


def import_project_package(package_dir: str | Path) -> dict[str, Any]:
    """导入项目包。package_dir 必须位于已登记的项目包根目录内。"""
    resolved = resolve_within_roots(
        package_dir,
        [PROJECT_PACKAGES_DIR],
        label="项目包目录",
        must_exist=True,
    )
    if not resolved.is_dir():
        raise PathPolicyError(f"项目包目录不是目录: {resolved}", code="not_a_directory")
    meta = read_project_package(resolved)
    if not meta:
        raise FileNotFoundError(f"项目包缺少 {PROJECT_PACKAGE_MANIFEST}: {resolved}")
    save_project(meta)
    return meta


def read_project_package(package_dir: Path) -> dict[str, Any] | None:
    package_dir = Path(package_dir)
    manifest_path = package_dir / PROJECT_PACKAGE_MANIFEST
    manifest = read_json(manifest_path, None)
    if not isinstance(manifest, dict):
        return None
    raw_project_id = manifest.get("project_id") or manifest.get("id")
    if not raw_project_id or not is_safe_id(str(raw_project_id)):
        return None
    project_id = str(raw_project_id)

    def safe_reference(key: str, default: str) -> str | None:
        value = manifest.get(key)
        if value in (None, ""):
            value = default
        try:
            return str(resolve_package_reference(package_dir, value, label=f"项目包字段 {key}"))
        except PathPolicyError:
            return None

    save_dir = safe_reference("save_dir", ".")
    if save_dir:
        # save_dir 只作为「包内已校验过的路径」使用；它不再是信任根的来源。
        try:
            resolve_within_roots(save_dir, [package_dir], label="项目包 save_dir", must_exist=False)
        except PathPolicyError:
            save_dir = None
    drawings = [_normalize_package_drawing(package_dir, item) for item in manifest.get("drawings", []) if isinstance(item, dict)]
    meta = {
        "id": project_id,
        "name": str(manifest.get("name") or project_id),
        "save_dir": save_dir or str(package_dir),
        "status": manifest.get("status") or "active",
        "created_at": manifest.get("created_at") or now_iso(),
        "updated_at": manifest.get("updated_at") or datetime.fromtimestamp(manifest_path.stat().st_mtime).isoformat(timespec="seconds"),
        "current_drawing_id": manifest.get("current_drawing_id"),
        "drawings": drawings,
        "site_profiles": manifest.get("site_profiles") or ["generic"],
        "package_dir": str(package_dir),
        "package_manifest_path": str(manifest_path),
        "source_dir": safe_reference("source_dir", "source"),
        "default_port": manifest.get("default_port") or manifest.get("startup_port"),
        "model_binding_path": manifest.get("model_binding_path"),
        "model_bindings_locked": bool(manifest.get("model_bindings_locked")),
        "model_binding_updated_at": manifest.get("model_binding_updated_at"),
        "revision": 1,
    }
    return normalize_project_meta(meta, "active")


def _manifest_write_dir(meta: dict[str, Any]) -> Path | None:
    """项目包 manifest 的写入目录。

    只在 `save_dir` 已通过信任校验（受管根目录，或操作者用
    `CAD_ALLOWED_PROJECT_ROOTS` 显式登记的根目录）时返回它；否则退回项目自身的
    存储目录。**绝不**因为 meta.json 里写了 `save_dir: /etc` 就往系统目录写文件。
    """
    save_dir_value = meta.get("save_dir")
    if not save_dir_value:
        return None
    project_id = str(meta.get("id") or "")
    trusted = [Path(root).expanduser() for root in [*_allowed_project_roots(), *extra_allowed_roots()]]
    resolved_trusted = [item for item in (_resolve_safe(root) for root in trusted) if item is not None]
    candidate = _resolve_safe(Path(str(save_dir_value)).expanduser())
    if candidate is not None and any(_path_inside(candidate, root) for root in resolved_trusted):
        return candidate
    if is_project_archived(meta) or not is_safe_id(project_id):
        return None
    try:
        return project_dir(project_id)
    except PathPolicyError:
        return None


def write_project_package_manifest(meta: dict[str, Any]) -> None:
    save_dir = _manifest_write_dir(meta)
    if save_dir is None:
        return
    try:
        save_dir.mkdir(parents=True, exist_ok=True)
    except OSError:
        return
    startup = _find_project_startup_script(save_dir)
    manifest = {
        "schema_version": "cad-project-package/1.0",
        "project_id": meta["id"],
        "name": meta.get("name") or meta["id"],
        "save_dir": ".",
        "status": meta.get("status", "active"),
        "site_profiles": meta.get("site_profiles") or ["generic"],
        "created_at": meta.get("created_at") or now_iso(),
        "updated_at": meta.get("updated_at") or now_iso(),
        "current_drawing_id": meta.get("current_drawing_id"),
        "source_dir": "source",
        "default_port": meta.get("default_port"),
        "startup_script": startup.name if startup else None,
        "model_binding_path": meta.get("model_binding_path"),
        "model_bindings_locked": bool(meta.get("model_bindings_locked")),
        "model_binding_updated_at": meta.get("model_binding_updated_at"),
        "drawings": [_package_drawing(save_dir, drawing) for drawing in meta.get("drawings", [])],
        "orchestration": {
            "source_patterns": ["*.dwg", "*.dxf"],
            "split_by_schematic": True,
            "replay_layer_check": True,
        },
    }
    write_json(save_dir / PROJECT_PACKAGE_MANIFEST, manifest)


def _find_project_startup_script(save_dir: Path) -> Path | None:
    scripts = sorted(save_dir.glob("启动-*.ps1"))
    return scripts[0] if scripts else None


def _package_drawing(save_dir: Path, drawing: dict[str, Any]) -> dict[str, Any]:
    packaged = {key: value for key, value in drawing.items() if key not in {"semantic_path", "dxf_path", "source_path", "uploaded_path"}}
    for key in ("semantic_path", "dxf_path"):
        value = drawing.get(key)
        if value:
            packaged[key] = _relative_or_absolute(Path(value), save_dir)
    return packaged


def _normalize_package_drawing(package_dir: Path, drawing: dict[str, Any]) -> dict[str, Any]:
    normalized = {key: value for key, value in drawing.items() if key not in {"semantic_path", "dxf_path", "source_path", "uploaded_path"}}
    for key in ("semantic_path", "dxf_path"):
        value = drawing.get(key)
        if value:
            try:
                normalized[key] = str(resolve_package_reference(package_dir, value, label=f"项目包图纸字段 {key}"))
            except PathPolicyError:
                continue
    return normalized


def _relative_or_absolute(path: Path, base_dir: Path) -> str:
    try:
        return str(path.resolve().relative_to(base_dir.resolve()))
    except (OSError, ValueError):
        # 包外路径不写入 manifest，避免把本机绝对路径泄露到项目包里
        return ""


# ---------------------------------------------------------------- 归档 / 恢复


def archive_project(project_id: str, *, expected_revision: Any = None) -> dict[str, Any]:
    source_dir = project_dir(project_id)
    target_dir = archived_project_dir(project_id)
    if not source_dir.exists():
        if target_dir.exists():
            raise ValueError("项目已经归档")
        raise FileNotFoundError(project_id)
    if target_dir.exists():
        _backup_conflicting_project_dir(target_dir, project_id, "archive-target")
    meta_path = source_dir / META_FILENAME
    meta = normalize_project_meta(read_json_strict(meta_path, None), "active")
    if not meta:
        raise FileNotFoundError(f"项目缺少 {META_FILENAME}: {project_id}")
    if expected_revision is not None and _normalize_revision(meta.get("revision")) != _normalize_revision(expected_revision):
        raise RevisionConflict(meta_path, _normalize_revision(expected_revision), _normalize_revision(meta.get("revision")))
    meta.setdefault("active_save_dir", meta.get("save_dir") or str(source_dir))
    _relocate_project_paths(meta, source_dir, target_dir)
    meta["save_dir"] = str(target_dir)
    meta["status"] = "archived"
    meta["archived_at"] = now_iso()
    meta["updated_at"] = now_iso()
    meta["revision"] = _normalize_revision(meta.get("revision")) + 1
    write_json(meta_path, meta)
    shutil.move(str(source_dir), str(target_dir))
    moved = target_dir / META_FILENAME
    return normalize_project_meta(read_json(moved, meta), "archived")


def restore_project(project_id: str) -> dict[str, Any]:
    source_dir = archived_project_dir(project_id)
    target_dir = project_dir(project_id)
    if not source_dir.exists():
        if target_dir.exists():
            raise ValueError("项目未归档")
        raise FileNotFoundError(project_id)
    if target_dir.exists():
        _backup_conflicting_project_dir(target_dir, project_id, "restore-target")
    meta_path = source_dir / META_FILENAME
    meta = normalize_project_meta(read_json_strict(meta_path, None), "archived")
    if not meta:
        raise FileNotFoundError(f"归档项目缺少 {META_FILENAME}: {project_id}")
    _relocate_project_paths(meta, source_dir, target_dir)
    meta["save_dir"] = meta.get("active_save_dir") or str(target_dir)
    meta["status"] = "active"
    meta["restored_at"] = now_iso()
    meta["updated_at"] = now_iso()
    meta["revision"] = _normalize_revision(meta.get("revision")) + 1
    write_json(meta_path, meta)
    shutil.move(str(source_dir), str(target_dir))
    moved = target_dir / META_FILENAME
    return normalize_project_meta(read_json(moved, meta), "active")


def delete_archived_project(project_id: str) -> Path:
    source_dir = archived_project_dir(project_id)
    if not source_dir.exists():
        raise FileNotFoundError(project_id)
    timestamp = now_iso().replace(":", "").replace("-", "").replace("T", "-")
    backup_dir = DELETED_PROJECT_BACKUP_DIR / f"{project_id}-{timestamp}"
    shutil.copytree(source_dir, backup_dir)
    shutil.rmtree(source_dir)
    return backup_dir


def _backup_conflicting_project_dir(target_dir: Path, project_id: str, reason: str) -> Path:
    timestamp = now_iso().replace(":", "").replace("-", "").replace("T", "-")
    backup_dir = ARCHIVE_CONFLICT_BACKUP_DIR / f"{project_id}-{reason}-{timestamp}"
    index = 1
    while backup_dir.exists():
        index += 1
        backup_dir = ARCHIVE_CONFLICT_BACKUP_DIR / f"{project_id}-{reason}-{timestamp}-{index}"
    backup_dir.parent.mkdir(parents=True, exist_ok=True)
    shutil.move(str(target_dir), str(backup_dir))
    return backup_dir


def _relocate_project_paths(meta: dict[str, Any], old_root: Path, new_root: Path) -> None:
    """归档/恢复时把项目内相对引用重定位到新根目录。"""
    old_root = old_root.resolve()
    for drawing in meta.get("drawings", []):
        if not isinstance(drawing, dict):
            continue
        for key in ("semantic_path", "dxf_path", "source_path", "uploaded_path"):
            value = drawing.get(key)
            if not value:
                continue
            try:
                current = Path(str(value)).resolve()
                relative = current.relative_to(old_root)
            except (OSError, ValueError):
                continue
            drawing[key] = str(new_root / relative)


# ---------------------------------------------------------------- 迁移辅助


def migrate_drawing_paths(meta: dict[str, Any]) -> list[dict[str, Any]]:
    """把项目里旧的 `<save_dir>/<drawing_id>/semantic.json` 布局迁移为
    `<project_storage_dir>/drawings/<drawing_id>/semantic.json`。

    返回迁移记录列表（不写盘；由调用方决定何时 save_project）。
    """
    project_id = str(meta.get("id") or "")
    if not is_safe_id(project_id):
        return []
    migrations: list[dict[str, Any]] = []
    roots = allowed_roots_for_meta(meta)
    for drawing in meta.get("drawings", []):
        if not isinstance(drawing, dict):
            continue
        drawing_id = str(drawing.get("id") or "")
        if not is_safe_id(drawing_id):
            continue
        canonical = drawing_semantic_path(project_id, drawing_id, archived=is_project_archived(meta))
        if canonical.exists():
            drawing["semantic_path"] = str(canonical)
            continue
        existing = drawing.get("semantic_path")
        if not existing:
            continue
        try:
            source = resolve_within_roots(existing, roots, label="图纸 semantic.json")
        except PathPolicyError:
            continue
        if not source.exists() or source == canonical:
            continue
        canonical.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, canonical)
        drawing["semantic_path"] = str(canonical)
        migrations.append({"drawing_id": drawing_id, "from": str(source), "to": str(canonical)})
    return migrations


def cleanup_stale_lock_files(root: Path, max_age_seconds: float = 7 * 24 * 3600) -> int:
    """清理陈旧的 .lock 文件，避免长期运行堆积。"""
    removed = 0
    if not root.exists():
        return 0
    cutoff = time.time() - max_age_seconds
    for lock_path in root.rglob("*.lock"):
        try:
            if lock_path.stat().st_mtime < cutoff:
                lock_path.unlink()
                removed += 1
        except OSError:
            continue
    return removed


__all__ = [
    "ARCHIVE_CONFLICT_BACKUP_DIR",
    "BASE_DIR",
    "CorruptJsonError",
    "DELETED_PROJECT_BACKUP_DIR",
    "LOG_DIR",
    "META_FILENAME",
    "PROJECTS_ARCHIVE_DIR",
    "PROJECTS_DIR",
    "PROJECT_PACKAGES_DIR",
    "PROJECT_PACKAGE_MANIFEST",
    "ROOT_DIR",
    "RUNTIME_ROOT",
    "RevisionConflict",
    "SEMANTIC_FILENAME",
    "StorageError",
    "UPLOAD_DIR",
    "UPLOAD_INDEX",
    "allowed_roots_for_meta",
    "archive_project",
    "archived_project_dir",
    "cleanup_stale_lock_files",
    "delete_archived_project",
    "discover_project_packages",
    "extra_allowed_roots",
    "drawing_semantic_path",
    "file_lock",
    "get_upload",
    "import_project_package",
    "is_project_archived",
    "list_projects",
    "load_project",
    "load_project_package",
    "load_project_strict",
    "load_uploads",
    "migrate_drawing_paths",
    "normalize_project_meta",
    "now_iso",
    "project_dir",
    "project_meta_path",
    "project_storage_dir",
    "read_json",
    "read_json_strict",
    "read_project_package",
    "read_uploads_strict",
    "register_upload",
    "resolve_package_reference",
    "restore_project",
    "sanitize_filename",
    "save_project",
    "save_uploads",
    "update_upload",
    "write_json",
    "write_json_atomic",
    "write_project_package_manifest",
]
