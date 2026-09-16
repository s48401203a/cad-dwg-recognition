from __future__ import annotations

import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from log_retention import enforce_log_budget  # noqa: E402


def test_deletes_oldest_until_budget(tmp_path: Path) -> None:
    now = time.time()
    oldest = tmp_path / "server-1.out.log"
    middle = tmp_path / "server-2.out.log"
    newest = tmp_path / "server-3.out.log"
    oldest.write_bytes(b"a" * 400)
    middle.write_bytes(b"b" * 400)
    newest.write_bytes(b"c" * 400)
    os.utime(oldest, (now - 300, now - 300))
    os.utime(middle, (now - 200, now - 200))
    os.utime(newest, (now - 10, now - 10))

    result = enforce_log_budget(max_bytes=500, roots=[tmp_path])

    assert result["ok"] is True
    assert result["after_bytes"] <= 500
    assert not oldest.exists()
    assert newest.exists()
    assert newest.stat().st_size == 400


def test_truncates_last_file_to_budget(tmp_path: Path) -> None:
    huge = tmp_path / "server-current.out.log"
    huge.write_bytes(b"head" + (b"t" * 200) + b"TAILDATA")

    result = enforce_log_budget(max_bytes=8, roots=[tmp_path])

    assert result["after_bytes"] <= 8
    assert huge.exists()
    assert huge.read_bytes().endswith(b"TAILDATA")
    assert huge.stat().st_size == 8


def test_ignores_non_log_files(tmp_path: Path) -> None:
    keep = tmp_path / "notes.txt"
    keep.write_bytes(b"y" * 900)
    log = tmp_path / "app.log"
    log.write_bytes(b"z" * 900)

    result = enforce_log_budget(max_bytes=100, roots=[tmp_path])

    assert keep.exists()
    assert keep.stat().st_size == 900
    assert result["after_bytes"] <= 100
    assert log.stat().st_size <= 100
