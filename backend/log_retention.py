"""Keep on-disk logs at or under a fixed budget by deleting/truncating oldest first."""

from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path
from typing import Any, Iterable

DEFAULT_MAX_BYTES = 500 * 1024 * 1024
DEFAULT_INTERVAL_SEC = 300
TAIL_MIN_BYTES = 256 * 1024


def max_log_bytes() -> int:
    raw_bytes = os.environ.get("CAD_LOG_MAX_BYTES", "").strip()
    if raw_bytes.isdigit():
        return max(1, int(raw_bytes))
    raw_mb = os.environ.get("CAD_LOG_MAX_MB", "").strip()
    if raw_mb.isdigit():
        return max(1, int(raw_mb) * 1024 * 1024)
    return DEFAULT_MAX_BYTES


def _is_log_file(path: Path) -> bool:
    name = path.name.lower()
    return name.endswith(".log") or ".log." in name


def _iter_log_files(roots: Iterable[Path]) -> list[Path]:
    found: list[Path] = []
    seen: set[Path] = set()
    for root in roots:
        if not root:
            continue
        try:
            resolved = root.expanduser().resolve()
        except OSError:
            continue
        if resolved.is_file():
            candidates = [resolved]
        elif resolved.is_dir():
            try:
                candidates = [p for p in resolved.rglob("*") if p.is_file()]
            except OSError:
                continue
        else:
            continue
        for path in candidates:
            if not _is_log_file(path):
                continue
            try:
                key = path.resolve()
            except OSError:
                key = path
            if key in seen:
                continue
            seen.add(key)
            found.append(path)
    return found


def default_log_roots() -> list[Path]:
    roots: list[Path] = []
    try:
        from storage import LOG_DIR, ROOT_DIR
    except Exception:
        here = Path(__file__).resolve()
        ROOT_DIR = here.parent.parent
        LOG_DIR = here.parent / "logs"
    roots.append(LOG_DIR)
    extra = os.environ.get("CAD_LOG_DIR", "").strip()
    if extra:
        roots.append(Path(extra))
    roots.append(ROOT_DIR / ".vite-dev.log")
    roots.append(ROOT_DIR / "output" / "replay" / "runner.log")
    return roots


def _file_mtime(path: Path) -> float:
    try:
        return path.stat().st_mtime
    except OSError:
        return 0.0


def _file_size(path: Path) -> int:
    try:
        return path.stat().st_size
    except OSError:
        return 0


def _truncate_keep_tail(path: Path, keep_bytes: int) -> int:
    size = _file_size(path)
    keep_bytes = max(0, int(keep_bytes))
    if size <= keep_bytes:
        return 0
    if keep_bytes == 0:
        with path.open("wb"):
            pass
        return size
    with path.open("r+b") as handle:
        handle.seek(size - keep_bytes)
        tail = handle.read(keep_bytes)
        handle.seek(0)
        handle.write(tail)
        handle.truncate(len(tail))
        handle.flush()
        os.fsync(handle.fileno())
    return size - len(tail)


def _try_unlink(path: Path) -> bool:
    try:
        path.unlink()
        return True
    except OSError:
        return False


def enforce_log_budget(
    max_bytes: int | None = None,
    roots: Iterable[Path] | None = None,
) -> dict[str, Any]:
    """Delete or tail-truncate oldest log files until total size <= max_bytes."""
    budget = int(max_bytes if max_bytes is not None else max_log_bytes())
    files = _iter_log_files(roots if roots is not None else default_log_roots())
    files.sort(key=lambda path: (_file_mtime(path), path.name))
    total = sum(_file_size(path) for path in files)
    deleted: list[str] = []
    truncated: list[dict[str, int | str]] = []
    before = total

    index = 0
    while total > budget and index < len(files):
        path = files[index]
        size = _file_size(path)
        remaining_files = len(files) - index
        if remaining_files > 1:
            if _try_unlink(path):
                total -= size
                deleted.append(str(path))
            else:
                keep = max(TAIL_MIN_BYTES, min(size, budget - (total - size)))
                if keep < size:
                    freed = _truncate_keep_tail(path, keep)
                    if freed:
                        total -= freed
                        truncated.append({"path": str(path), "kept": keep, "freed": freed})
        else:
            keep = min(size, budget)
            if keep < size:
                freed = _truncate_keep_tail(path, keep)
                if freed:
                    total -= freed
                    truncated.append({"path": str(path), "kept": keep, "freed": freed})
        index += 1

    return {
        "ok": True,
        "max_bytes": budget,
        "before_bytes": before,
        "after_bytes": max(0, total),
        "file_count": len(files) - len(deleted),
        "deleted": deleted,
        "truncated": truncated,
        "cleaned": bool(deleted or truncated),
    }


async def log_retention_loop(interval_sec: float | None = None) -> None:
    delay = float(interval_sec or os.environ.get("CAD_LOG_RETENTION_SEC") or DEFAULT_INTERVAL_SEC)
    delay = max(30.0, delay)
    while True:
        try:
            result = enforce_log_budget()
            if result.get("cleaned"):
                print(
                    f"[log-retention] {result['before_bytes']} -> {result['after_bytes']} bytes "
                    f"(deleted {len(result['deleted'])}, truncated {len(result['truncated'])})",
                    flush=True,
                )
        except Exception as exc:
            print(f"[log-retention] cleanup failed: {exc}", flush=True)
        await asyncio.sleep(delay)


def main() -> int:
    result = enforce_log_budget()
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
