import json
import os
import shutil
from datetime import datetime
from pathlib import Path
from typing import Any

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


def now_iso() -> str:
    return datetime.now().isoformat(timespec="seconds")


def read_json(path: Path, default: Any) -> Any:
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return default


def write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def load_uploads() -> dict[str, Any]:
    return read_json(UPLOAD_INDEX, {})


def save_uploads(data: dict[str, Any]) -> None:
    write_json(UPLOAD_INDEX, data)


def register_upload(file_id: str, record: dict[str, Any]) -> None:
    uploads = load_uploads()
    uploads[file_id] = record
    save_uploads(uploads)


def get_upload(file_id: str) -> dict[str, Any] | None:
    return load_uploads().get(file_id)


def project_dir(project_id: str) -> Path:
    return PROJECTS_DIR / project_id


def archived_project_dir(project_id: str) -> Path:
    return PROJECTS_ARCHIVE_DIR / project_id


def project_storage_dir(meta: dict[str, Any]) -> Path:
    return archived_project_dir(meta["id"]) if is_project_archived(meta) else project_dir(meta["id"])


def is_project_archived(meta: dict[str, Any] | None) -> bool:
    return bool(meta and meta.get("status") == "archived")


def normalize_project_meta(meta: dict[str, Any] | None, status: str = "active") -> dict[str, Any] | None:
    if not meta:
        return None
    meta.setdefault("status", status)
    return meta


def load_project(project_id: str, include_archived: bool = False) -> dict[str, Any] | None:
    meta = project_dir(project_id) / "meta.json"
    if not meta.exists():
        package_meta = load_project_package(project_id)
        if package_meta:
            return package_meta
        if not include_archived:
            return None
        archived_meta = archived_project_dir(project_id) / "meta.json"
        return normalize_project_meta(read_json(archived_meta, None), "archived") if archived_meta.exists() else None
    return normalize_project_meta(read_json(meta, None), "active")


def save_project(meta: dict[str, Any]) -> None:
    target_dir = archived_project_dir(meta["id"]) if is_project_archived(meta) else project_dir(meta["id"])
    write_json(target_dir / "meta.json", meta)
    if not is_project_archived(meta):
        write_project_package_manifest(meta)


def list_projects(include_archived: bool = False) -> list[dict[str, Any]]:
    projects: list[dict[str, Any]] = []
    seen: set[str] = set()
    for child in sorted(PROJECTS_DIR.iterdir(), key=lambda p: p.stat().st_mtime, reverse=True):
        if not child.is_dir():
            continue
        meta = read_json(child / "meta.json", None)
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
            meta = read_json(child / "meta.json", None)
            if meta:
                normalized = normalize_project_meta(meta, "archived")
                if normalized and normalized["id"] not in seen:
                    projects.append(normalized)
                    seen.add(normalized["id"])
    projects.sort(key=lambda item: item.get("updated_at") or item.get("archived_at") or item.get("created_at") or "", reverse=True)
    return projects


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
    for meta in discover_project_packages():
        if meta.get("id") == project_id:
            return meta
    return None


def import_project_package(package_dir: str | Path) -> dict[str, Any]:
    meta = read_project_package(Path(package_dir))
    if not meta:
        raise FileNotFoundError(f"项目包缺少 {PROJECT_PACKAGE_MANIFEST}: {package_dir}")
    save_project(meta)
    return meta


def read_project_package(package_dir: Path) -> dict[str, Any] | None:
    manifest_path = package_dir / PROJECT_PACKAGE_MANIFEST
    manifest = read_json(manifest_path, None)
    if not isinstance(manifest, dict):
        return None
    project_id = manifest.get("project_id") or manifest.get("id")
    if not project_id:
        return None
    save_dir_value = manifest.get("save_dir") or "."
    save_dir = _resolve_package_path(package_dir, save_dir_value)
    drawings = [_normalize_package_drawing(package_dir, item) for item in manifest.get("drawings", []) if isinstance(item, dict)]
    meta = {
        "id": str(project_id),
        "name": str(manifest.get("name") or project_id),
        "save_dir": str(save_dir),
        "status": manifest.get("status") or "active",
        "created_at": manifest.get("created_at") or now_iso(),
        "updated_at": manifest.get("updated_at") or datetime.fromtimestamp(manifest_path.stat().st_mtime).isoformat(timespec="seconds"),
        "current_drawing_id": manifest.get("current_drawing_id"),
        "drawings": drawings,
        "site_profiles": manifest.get("site_profiles") or ["express"],
        "package_dir": str(package_dir),
        "package_manifest_path": str(manifest_path),
        "source_dir": str(_resolve_package_path(package_dir, manifest.get("source_dir") or "source")),
        "default_port": manifest.get("default_port") or manifest.get("startup_port"),
        "model_binding_path": manifest.get("model_binding_path"),
        "model_bindings_locked": bool(manifest.get("model_bindings_locked")),
        "model_binding_updated_at": manifest.get("model_binding_updated_at"),
    }
    return normalize_project_meta(meta, "active")


def write_project_package_manifest(meta: dict[str, Any]) -> None:
    save_dir_value = meta.get("save_dir")
    if not save_dir_value:
        return
    save_dir = Path(save_dir_value).expanduser()
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
        "site_profiles": meta.get("site_profiles") or ["express"],
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
    packaged = dict(drawing)
    for key in ("semantic_path", "dxf_path"):
        if packaged.get(key):
            packaged[key] = _relative_or_absolute(Path(packaged[key]), save_dir)
    return packaged


def _normalize_package_drawing(package_dir: Path, drawing: dict[str, Any]) -> dict[str, Any]:
    normalized = dict(drawing)
    for key in ("semantic_path", "dxf_path"):
        value = normalized.get(key)
        if value:
            normalized[key] = str(_resolve_package_path(package_dir, value))
    return normalized


def _resolve_package_path(package_dir: Path, value: str | Path) -> Path:
    path = Path(value).expanduser()
    if path.is_absolute():
        return path
    return (package_dir / path).resolve()


def _relative_or_absolute(path: Path, base_dir: Path) -> str:
    try:
        return str(path.resolve().relative_to(base_dir.resolve()))
    except (OSError, ValueError):
        return str(path)


def archive_project(project_id: str) -> dict[str, Any]:
    source_dir = project_dir(project_id)
    target_dir = archived_project_dir(project_id)
    if not source_dir.exists():
        if target_dir.exists():
            raise ValueError("项目已经归档")
        raise FileNotFoundError(project_id)
    if target_dir.exists():
        _backup_conflicting_project_dir(target_dir, project_id, "archive-target")
    meta = normalize_project_meta(read_json(source_dir / "meta.json", None), "active")
    if not meta:
        raise FileNotFoundError(f"项目缺少 meta.json: {project_id}")
    meta.setdefault("active_save_dir", meta.get("save_dir") or str(source_dir))
    _relocate_project_paths(meta, source_dir, target_dir)
    meta["save_dir"] = str(target_dir)
    meta["status"] = "archived"
    meta["archived_at"] = now_iso()
    meta["updated_at"] = now_iso()
    write_json(source_dir / "meta.json", meta)
    shutil.move(str(source_dir), str(target_dir))
    return normalize_project_meta(read_json(target_dir / "meta.json", meta), "archived")


def restore_project(project_id: str) -> dict[str, Any]:
    source_dir = archived_project_dir(project_id)
    target_dir = project_dir(project_id)
    if not source_dir.exists():
        if target_dir.exists():
            raise ValueError("项目未归档")
        raise FileNotFoundError(project_id)
    if target_dir.exists():
        _backup_conflicting_project_dir(target_dir, project_id, "restore-target")
    meta = normalize_project_meta(read_json(source_dir / "meta.json", None), "archived")
    if not meta:
        raise FileNotFoundError(f"归档项目缺少 meta.json: {project_id}")
    _relocate_project_paths(meta, source_dir, target_dir)
    meta["save_dir"] = meta.get("active_save_dir") or str(target_dir)
    meta["status"] = "active"
    meta["restored_at"] = now_iso()
    meta["updated_at"] = now_iso()
    write_json(source_dir / "meta.json", meta)
    shutil.move(str(source_dir), str(target_dir))
    return normalize_project_meta(read_json(target_dir / "meta.json", meta), "active")


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
    backup_root = ARCHIVE_CONFLICT_BACKUP_DIR / f"{project_id}-{reason}-{timestamp}"
    backup_dir = backup_root
    index = 1
    while backup_dir.exists():
        index += 1
        backup_dir = ARCHIVE_CONFLICT_BACKUP_DIR / f"{project_id}-{reason}-{timestamp}-{index}"
    backup_dir.parent.mkdir(parents=True, exist_ok=True)
    shutil.move(str(target_dir), str(backup_dir))
    return backup_dir


def _relocate_project_paths(meta: dict[str, Any], old_root: Path, new_root: Path) -> None:
    old_root = old_root.resolve()
    for drawing in meta.get("drawings", []):
        semantic_path = drawing.get("semantic_path")
        if not semantic_path:
            continue
        try:
            current = Path(semantic_path).resolve()
            relative = current.relative_to(old_root)
        except (OSError, ValueError):
            continue
        drawing["semantic_path"] = str(new_root / relative)
