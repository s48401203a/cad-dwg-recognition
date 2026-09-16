# -*- coding: utf-8 -*-
"""内置静态导出：把某张图纸的 semantic.json 渲染成单文件离线 3D 快照页。

为什么需要这个模块
------------------
公开分发里没有 `tools/export_static_landing_pages.py`（`tools/`、`orchestrator/` 都被 .gitignore
排除），但 `backend/api/projects.py` 的「静态导出 / 分享链接 / 归档快照」都会调用它，导致这些
按钮点下去必然失败。这里提供一个自包含的通用替代实现，契约与老工具保持一致：

    export_single_project(meta, *, output_root, drawing_id=None, file_name=None, public_url_prefix=...)

设计约束
--------
- 只依赖标准库 + 本仓库的 `path_policy` / `storage`；**不依赖** `SceneBuilder.js` 那一堆兄弟模块。
- 产出是单文件 HTML：内嵌 semantic 数据 + 用 vendored three.js 本地渲染，不联网、不需要后端。
- 绝不把本地绝对路径（`save_dir`、源 DWG/DXF 路径等）写进 HTML —— 静态页是可以外发的。
- 只信任服务端解析出来的路径：图纸 ID 先过 `path_policy`，semantic 路径必须落在
  `storage.allowed_roots_for_meta(meta)` 之内，越界一律拒绝读取。
"""

from __future__ import annotations

import contextlib
import json
import os
import re
import tempfile
from datetime import datetime
from html import escape
from pathlib import Path
from typing import Any
from urllib.parse import quote

import storage
from path_policy import PathPolicyError, is_safe_id, resolve_within_roots, sanitize_filename

# backend/ 的上一级 = 仓库根
REPO_ROOT = Path(__file__).resolve().parents[2]
FRONTEND_DIR = REPO_ROOT / "frontend"
THREE_VENDOR_DIR = FRONTEND_DIR / "vendor" / "three"
THREE_ENTRY_FILENAME = "three.module.js"
# 应用把 frontend/ 挂在 `/`，vendored three 由此可通过 `/vendor/three/...` 访问
THREE_APP_BASE = "/vendor/three/"
DEFAULT_PUBLIC_URL_PREFIX = "/exports/static-pages"
SEMANTIC_TAG_ID = "cad-semantic"

# 这些键一律不进 HTML：本地路径 / 归档产物位置属于主机内部信息
_PATH_KEYS = frozenset(
    {
        "save_dir",
        "package_dir",
        "source_dir",
        "sandbox_dir",
        "work_dir",
        "output_dir",
        "semantic_path",
        "dxf_path",
        "dwg_path",
        "source_path",
        "source_file",
        "file_path",
        "html_path",
        "html_dir",
        "archived_html_path",
        "archive_snapshot",
        "model_path",
        "report_path",
        "log_path",
        "save_path",
        "raw_path",
    }
)
_REDACTED_PREFIX = "<已隐藏本地路径>"
# 嵌在长文本里的绝对路径（警告、备注等）：只认带扩展名的，且遇到中日韩文字/全角标点即止，
# 避免误伤 "AP-01/02"、"AP/摄像头" 这类标签。
_ABS_FILE_RE = re.compile(
    r"(?:[A-Za-z]:[\\/]|/)[^\s\"'<>|,;:)\]}\u3000-\u303f\uff00-\uffef\u4e00-\u9fff]*\.[A-Za-z0-9]{1,8}"
)


# ---------------------------------------------------------------- 公开 API


def exporter_info() -> dict[str, Any]:
    """内置导出器的身份信息，供 API/能力探测展示。"""
    return {"kind": "builtin", "module": __name__}


def export_single_project(
    meta: dict[str, Any],
    *,
    output_root: str | Path,
    drawing_id: str | None = None,
    file_name: str | None = None,
    public_url_prefix: str = DEFAULT_PUBLIC_URL_PREFIX,
) -> dict[str, Any]:
    """把一张图纸的 semantic.json 导出为单文件离线 3D 快照页。

    返回（至少）包含：``path``（绝对路径）/ ``file_name`` / ``url`` / ``drawing_id`` /
    ``bytes``（与 ``size_bytes`` 相同）。

    异常：
    - `path_policy.PathPolicyError`：图纸 ID 非法（调用方应转 HTTP 400）。
    - `FileNotFoundError`：图纸不存在，或找不到 semantic.json（HTTP 404）。
    - `storage.CorruptJsonError`：semantic.json 存在但已损坏，绝不静默当成空数据。
    - `storage.StorageError`：semantic.json 为空或不是 JSON 对象。
    """
    if not isinstance(meta, dict):
        raise ValueError("项目 meta 必须是 dict")

    drawing = _resolve_drawing(meta, drawing_id)
    selected_drawing_id = str(drawing.get("id") or "")
    semantic_source = _resolve_semantic_source(meta, drawing)

    semantic = storage.read_json_strict(semantic_source, None)
    if not isinstance(semantic, dict):
        raise storage.StorageError(
            f"图纸 {selected_drawing_id} 的 semantic.json 内容为空或不是 JSON 对象，无法导出静态页面"
        )

    generated_at = datetime.now().isoformat(timespec="seconds")
    project_id = _directory_id(meta.get("id"))
    payload = _build_payload(semantic, meta, drawing, generated_at=generated_at)

    display_name = _project_name(payload, meta)
    target = _resolve_output_path(
        output_root=output_root,
        project_id=project_id,
        file_name=file_name,
        fallback_name=f"{display_name}-{selected_drawing_id or 'drawing'}.html",
    )
    three_base = _three_base_for(target.parent)
    html = _render_html(payload, three_base=three_base, generated_at=generated_at)
    _write_text_atomic(target, html)

    size_bytes = target.stat().st_size
    if size_bytes <= 0:
        raise storage.StorageError(f"静态导出文件为空: {target.name}")

    relative_path = target.relative_to(Path(output_root).expanduser().resolve()).as_posix()
    prefix = (public_url_prefix or DEFAULT_PUBLIC_URL_PREFIX).rstrip("/")
    return {
        "path": str(target),
        "directory": str(target.parent),
        "file_name": target.name,
        "url": f"{prefix}/{quote(relative_path, safe='/')}",
        "project_id": project_id,
        "drawing_id": selected_drawing_id,
        "size_bytes": size_bytes,
        "bytes": size_bytes,
        "generated_at": generated_at,
        "three_base": three_base,
        "exporter": exporter_info(),
    }


# ---------------------------------------------------------------- 定位图纸与语义


def _resolve_drawing(meta: dict[str, Any], drawing_id: str | None) -> dict[str, Any]:
    """按 drawing_id → current_drawing_id → 第一张图纸的顺序定位图纸。"""
    drawings = [item for item in (meta.get("drawings") or []) if isinstance(item, dict)]

    if drawing_id is not None:
        if not is_safe_id(drawing_id):
            raise PathPolicyError(
                f"图纸 ID 非法: {drawing_id!r}（只允许字母、数字、下划线和连字符）", code="invalid_id"
            )
        wanted = str(drawing_id).strip()
        for drawing in drawings:
            if str(drawing.get("id") or "") == wanted:
                return drawing
        raise FileNotFoundError(
            f"图纸不存在: {wanted}（项目 {meta.get('id')!r} 中没有这张图纸，无法导出静态页面）"
        )

    current = meta.get("current_drawing_id")
    if current:
        for drawing in drawings:
            if str(drawing.get("id") or "") == str(current):
                return drawing
    if drawings:
        return drawings[0]
    raise FileNotFoundError(f"项目 {meta.get('id')!r} 还没有任何图纸，无法导出静态页面（请先上传并解析图纸）")


def _semantic_candidates(meta: dict[str, Any], drawing: dict[str, Any]) -> list[Path]:
    """semantic.json 的候选路径：规范位置优先，其次图纸记录里的 semantic_path（需在允许根内）。"""
    candidates: list[Path] = []
    project_id = str(meta.get("id") or "")
    drawing_id = str(drawing.get("id") or "")

    if is_safe_id(project_id) and is_safe_id(drawing_id):
        archived = bool(meta.get("status") == "archived")
        for flag in ((True, False) if archived else (False, True)):
            with contextlib.suppress(Exception):
                candidates.append(storage.drawing_semantic_path(project_id, drawing_id, archived=flag))

    stored = drawing.get("semantic_path")
    if isinstance(stored, str) and stored.strip():
        # save_dir 不是信任来源：只有当它自身落在受管根目录内时才会被 accept
        roots = storage.allowed_roots_for_meta(meta)
        with contextlib.suppress(PathPolicyError):
            candidates.append(resolve_within_roots(stored, roots, label="图纸 semantic 路径", must_exist=True))

    seen: list[Path] = []
    for path in candidates:
        if path not in seen:
            seen.append(path)
    return seen


def _resolve_semantic_source(meta: dict[str, Any], drawing: dict[str, Any]) -> Path:
    drawing_id = str(drawing.get("id") or "")
    for candidate in _semantic_candidates(meta, drawing):
        if candidate.is_file():
            return candidate
    raise FileNotFoundError(
        f"图纸 {drawing_id} 的 semantic.json 不存在，无法导出静态页面。"
        "请先解析这张图纸（规范位置：<项目存储目录>/drawings/"
        f"{sanitize_filename(drawing_id, fallback='drawing')}/semantic.json）。"
    )


def _directory_id(value: Any) -> str:
    """项目目录名：合法项目 ID 直接用，否则退化为安全文件名。"""
    if is_safe_id(value):
        return str(value).strip()
    return sanitize_filename(value, fallback="project", max_length=64)


def _project_name(payload: dict[str, Any], meta: dict[str, Any]) -> str:
    project = payload.get("project") or {}
    drawing_meta = payload.get("drawing_meta") or {}
    for candidate in (project.get("name"), meta.get("name"), drawing_meta.get("name"), drawing_meta.get("original_name")):
        text = str(candidate or "").strip()
        if text:
            return text
    return "未命名项目"


def _resolve_output_path(
    *,
    output_root: str | Path,
    project_id: str,
    file_name: str | None,
    fallback_name: str,
) -> Path:
    """把输出路径钉死在 output_root 之内（`../../evil.html` 之类一律降级为单段文件名）。"""
    root = Path(output_root).expanduser()
    root.mkdir(parents=True, exist_ok=True)
    root_resolved = root.resolve()

    candidate_name = sanitize_filename(file_name if file_name else fallback_name, fallback="index.html")
    if not candidate_name.lower().endswith(".html"):
        candidate_name = f"{candidate_name}.html"

    target_dir = root_resolved / project_id
    target_dir.mkdir(parents=True, exist_ok=True)
    target = (target_dir / candidate_name).resolve()
    with contextlib.suppress(PathPolicyError):
        return resolve_within_roots(target, [root_resolved], label="静态导出路径", must_exist=False)
    raise PathPolicyError(f"静态导出路径越界，已拒绝写入: {candidate_name}", code="outside_allowed_roots")


def _write_text_atomic(path: Path, text: str) -> None:
    """同目录临时文件 + os.replace，避免半截 HTML 被分享出去。"""
    path.parent.mkdir(parents=True, exist_ok=True)
    handle_fd, temp_name = tempfile.mkstemp(dir=str(path.parent), prefix=f".{path.name}.", suffix=".tmp")
    try:
        with os.fdopen(handle_fd, "w", encoding="utf-8", newline="\n") as handle:
            handle.write(text)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp_name, path)
    except BaseException:
        with contextlib.suppress(OSError):
            os.unlink(temp_name)
        raise


# ---------------------------------------------------------------- 内嵌数据


def _build_payload(
    semantic: dict[str, Any],
    meta: dict[str, Any],
    drawing: dict[str, Any],
    *,
    generated_at: str,
) -> dict[str, Any]:
    """构造真正写进 HTML 的数据：剔除路径、补齐 project/stats。"""
    payload = _scrub(semantic, _sensitive_prefixes(meta))
    if not isinstance(payload, dict):  # pragma: no cover - _scrub 对 dict 输入必然返回 dict
        payload = {}

    project = payload.get("project")
    project = dict(project) if isinstance(project, dict) else {}
    project.pop("save_dir", None)  # 老工具会塞 save_dir，这里必须剥掉
    project.update(
        {
            "id": str(meta.get("id") or project.get("id") or ""),
            "name": str(meta.get("name") or project.get("name") or ""),
            "drawing_id": str(drawing.get("id") or project.get("drawing_id") or ""),
            "drawing_name": str(drawing.get("name") or project.get("drawing_name") or ""),
            "generated_at": generated_at,
            "readonly_static": True,
        }
    )
    payload["project"] = project
    payload["stats"] = _collection_counts(payload)
    payload["generated_at"] = generated_at
    return payload


def _sensitive_prefixes(meta: dict[str, Any]) -> tuple[str, ...]:
    """本项目相关的本地目录前缀：出现在任何字符串里都要被抹掉。"""
    values: list[str] = []
    for key in ("save_dir", "package_dir", "source_dir"):
        raw = meta.get(key)
        if raw:
            values.append(str(raw).rstrip("/\\"))
    for root in (storage.PROJECTS_DIR, storage.PROJECTS_ARCHIVE_DIR, storage.PROJECT_PACKAGES_DIR, storage.UPLOAD_DIR):
        values.append(str(root).rstrip("/\\"))
    unique: list[str] = []
    for value in values:
        if value and value not in unique:
            unique.append(value)
    # 长前缀优先，避免先替换父目录导致子路径残留
    return tuple(sorted(unique, key=len, reverse=True))


def _scrub(value: Any, sensitive: tuple[str, ...] = ()) -> Any:
    """递归清洗：删除路径类键，把绝对路径（含嵌在文本里的）替换为占位串。"""
    if isinstance(value, dict):
        return {
            str(item_key): _scrub(item_value, sensitive)
            for item_key, item_value in value.items()
            if str(item_key).lower() not in _PATH_KEYS
        }
    if isinstance(value, (list, tuple)):
        return [_scrub(item, sensitive) for item in value]
    if isinstance(value, str):
        return _redact_string(value, sensitive)
    if isinstance(value, (int, float, bool)) or value is None:
        return value
    return str(value)


def _redact_string(text: str, sensitive: tuple[str, ...] = ()) -> str:
    """把字符串里的本地绝对路径换成占位串（保留末段文件名，便于排错）。"""
    # 先处理嵌在文本里的路径，再处理已知目录前缀，避免占位串被二次匹配
    result = _ABS_FILE_RE.sub(lambda match: _redact_path(match.group(0)), text) if _ABS_FILE_RE.search(text) else text
    for prefix in sensitive:
        if prefix and prefix in result:
            result = result.replace(prefix, _REDACTED_PREFIX)
    if _looks_absolute(result):
        return _redact_path(result)
    return result


def _looks_absolute(value: str) -> bool:
    text = value.strip()
    if not text:
        return False
    if text.startswith("\\\\"):  # UNC
        return True
    if len(text) > 2 and text[0].isalpha() and text[1] == ":" and text[2] in "\\/":  # Windows 盘符
        return True
    return text.startswith("/")


def _redact_path(value: str) -> str:
    """绝对路径只保留最后一段名字，避免把主机目录结构带出去。"""
    name = value.replace("\\", "/").rstrip("/").rsplit("/", 1)[-1]
    return f"{_REDACTED_PREFIX}/{name}" if name else _REDACTED_PREFIX


def _as_int(value: Any, fallback: int = 0) -> int:
    if isinstance(value, bool):
        return fallback
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value)
    if isinstance(value, str):
        with contextlib.suppress(ValueError):
            return int(float(value.strip()))
    return fallback


def _as_list(payload: dict[str, Any], key: str) -> list[Any]:
    value = payload.get(key)
    return value if isinstance(value, list) else []


def _collection_counts(payload: dict[str, Any]) -> dict[str, int]:
    devices = _as_list(payload, "devices")
    fixtures = _as_list(payload, "fixtures")
    cables = _as_list(payload, "cables")
    structures = _as_list(payload, "structures")
    areas = _as_list(payload, "areas")
    office_objects = _as_list(payload, "office_objects")
    parking_spaces = _as_list(payload, "parking_spaces")
    annotations = _as_list(payload, "annotations")

    model_objects = (
        len(devices) + len(fixtures) + len(cables) + len(structures) + len(areas) + len(office_objects) + len(parking_spaces)
    )
    existing_stats = payload.get("stats") if isinstance(payload.get("stats"), dict) else {}
    counts = {
        "devices": len(devices) + len(fixtures),
        "device_only": len(devices),
        "fixtures": len(fixtures),
        "cables": len(cables),
        "structures": len(structures),
        "areas": len(areas) + len(office_objects) + len(parking_spaces),
        "annotations": len(annotations),
        "model_objects": model_objects,
        "review_needed": _as_int(existing_stats.get("review_needed"), 0),
        "total_entities": _as_int(existing_stats.get("total_entities"), model_objects),
    }
    if counts["total_entities"] <= 0:
        counts["total_entities"] = model_objects
    return counts


# ---------------------------------------------------------------- three.js 前缀


def _is_within(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
        return True
    except ValueError:
        return False


def _three_base_for(output_dir: Path) -> str:
    """计算导出页到 vendored three.js 的相对前缀；算不出来就退回应用挂载路径。

    只在导出目录位于本仓库之内时才使用相对路径：此时前缀是 `../../../frontend/vendor/three/`
    这种仓库内布局，既不会把主机绝对路径带进分享文件（`os.path.relpath` 在跨目录时会算出
    `../../../../../Users/...` 这种等于泄露仓库位置的串），也能在 file:// 下直接打开。
    其余情况（导出到仓库外、跨盘符、vendored 文件缺失）一律退回应用挂载的 `/vendor/three/`。
    """
    entry = THREE_VENDOR_DIR / THREE_ENTRY_FILENAME
    try:
        if not entry.is_file():
            return THREE_APP_BASE
        repo_root = REPO_ROOT.resolve()
        target_dir = output_dir.resolve()
        if not _is_within(target_dir, repo_root):
            return THREE_APP_BASE
        relative = Path(os.path.relpath(THREE_VENDOR_DIR, start=target_dir)).as_posix()
        if not relative or relative.startswith("/"):
            return THREE_APP_BASE
        if not relative.endswith("/"):
            relative += "/"
        if not _is_within((target_dir / relative).resolve(), repo_root):
            return THREE_APP_BASE
        if (target_dir / relative / THREE_ENTRY_FILENAME).resolve() != entry.resolve():
            return THREE_APP_BASE
        return relative
    except (OSError, ValueError):
        return THREE_APP_BASE


# ---------------------------------------------------------------- HTML


def _render_html(payload: dict[str, Any], *, three_base: str, generated_at: str) -> str:
    project = payload.get("project") if isinstance(payload.get("project"), dict) else {}
    stats = payload.get("stats") if isinstance(payload.get("stats"), dict) else {}

    project_name = str(project.get("name") or "未命名项目")
    drawing_name = str(project.get("drawing_name") or project.get("drawing_id") or "未指定图纸")
    title = f"{project_name} - {drawing_name} (静态 3D 快照)"

    semantic_json = json.dumps(payload, ensure_ascii=False).replace("<", "\\u003c")
    importmap = json.dumps(
        {
            "imports": {
                "three": f"{three_base}{THREE_ENTRY_FILENAME}",
                "three/addons/": f"{three_base}examples/jsm/",
            },
            "scopes": {
                # OrbitControls 内部 `from 'three'` 按所在作用域解析：
                # 这样无论从相对路径还是从应用的 /vendor 挂载加载，都指向同一份 three.js
                three_base: {"three": f"{three_base}{THREE_ENTRY_FILENAME}"},
                THREE_APP_BASE: {"three": f"{THREE_APP_BASE}{THREE_ENTRY_FILENAME}"},
            },
        },
        ensure_ascii=False,
        indent=2,
    )

    html = _HTML_TEMPLATE
    replacements = {
        "__TITLE__": escape(title),
        "__PROJECT_NAME__": escape(project_name),
        "__DRAWING_NAME__": escape(drawing_name),
        "__GENERATED_AT__": escape(generated_at),
        "__METRICS__": _metrics_html(stats),
        "__IMPORTMAP__": importmap,
        "__SEMANTIC_ID__": SEMANTIC_TAG_ID,
        "__CSS__": _VIEWER_CSS,
        "__VIEWER_JS__": (
            _VIEWER_JS.replace("__THREE_BASE__", three_base)
            .replace("__THREE_MODULE_URL__", f"{three_base}{THREE_ENTRY_FILENAME}")
            .replace("__SEMANTIC_ID__", SEMANTIC_TAG_ID)
        ),
    }
    for token, value in replacements.items():
        html = html.replace(token, value)
    # 内嵌数据放最后替换，避免数据里恰好出现 __TOKEN__ 被再次替换
    return html.replace("__SEMANTIC_JSON__", semantic_json)


def _metrics_html(stats: dict[str, Any]) -> str:
    items = (
        ("设备", _as_int(stats.get("devices"), 0)),
        ("线路", _as_int(stats.get("cables"), 0)),
        ("结构", _as_int(stats.get("structures"), 0)),
        ("区域", _as_int(stats.get("areas"), 0)),
        ("实体", _as_int(stats.get("total_entities"), 0)),
    )
    return "".join(f'<span class="metric"><b>{count}</b>{escape(label)}</span>' for label, count in items)


_HTML_TEMPLATE = """<!doctype html>
<html lang="zh-CN">
<head>
<meta charset="utf-8" />
<meta name="viewport" content="width=device-width, initial-scale=1" />
<meta name="robots" content="noindex, nofollow" />
<title>__TITLE__</title>
<link rel="icon" href="data:," />
<style>
__CSS__
</style>
<script type="importmap">
__IMPORTMAP__
</script>
</head>
<body>
<header id="topbar">
  <div class="brand">
    <h1>__PROJECT_NAME__</h1>
    <p class="sub">图纸：<b>__DRAWING_NAME__</b> · 生成时间：__GENERATED_AT__</p>
  </div>
  <div class="metrics">__METRICS__</div>
</header>
<div id="readonly">只读静态快照（read-only snapshot）· 已剔除本地路径 · 离线渲染，不联网、不需要后端服务
</div>
<main>
  <aside id="side">
    <section>
      <h2>图层 / 类型</h2>
      <div class="row">
        <button type="button" id="layersAll">全选</button>
        <button type="button" id="layersNone">全不选</button>
      </div>
      <div id="layers" class="layers"></div>
    </section>
    <section>
      <h2>视图</h2>
      <div class="row">
        <button type="button" id="fit">适配视图</button>
        <button type="button" id="topView">俯视</button>
        <button type="button" id="perspView">透视</button>
      </div>
      <p class="hint">左键旋转 · 右键平移 · 滚轮缩放</p>
    </section>
    <section>
      <h2>对象信息</h2>
      <div id="info" class="hint">点击场景中的对象查看属性（此页为只读快照，不能编辑）。</div>
    </section>
    <section>
      <h2>关于</h2>
      <p class="hint">本页由内置静态导出器生成：解析数据以 JSON 内嵌，three.js 从仓库
      <code>frontend/vendor/</code> 本地加载，可直接双击打开或放到任意静态目录分享。</p>
    </section>
  </aside>
  <section id="stage">
    <canvas id="view"></canvas>
  </section>
</main>
<script type="application/json" id="__SEMANTIC_ID__">__SEMANTIC_JSON__</script>
<script type="module">
__VIEWER_JS__
</script>
</body>
</html>
"""


_VIEWER_CSS = """
:root { color-scheme: dark; --ink: #eef3ee; --dim: #9aa79c; --line: rgba(238, 243, 238, .14); --accent: #f4b43a; }
* { box-sizing: border-box; }
html, body { margin: 0; height: 100%; background: #070a08; color: var(--ink);
  font-family: "Microsoft YaHei", "PingFang SC", system-ui, Arial, sans-serif; }
body { display: flex; flex-direction: column; }
#topbar { display: flex; align-items: center; justify-content: space-between; gap: 16px;
  padding: 10px 16px; border-bottom: 1px solid var(--line); background: #0b100d; flex-wrap: wrap; }
#topbar h1 { margin: 0; font-size: 16px; font-weight: 600; }
#topbar .sub { margin: 2px 0 0; font-size: 12px; color: var(--dim); }
.metrics { display: flex; gap: 8px; flex-wrap: wrap; }
.metric { display: flex; align-items: baseline; gap: 5px; padding: 4px 10px; font-size: 12px; color: var(--dim);
  border: 1px solid var(--line); border-radius: 999px; background: rgba(238, 243, 238, .04); }
.metric b { color: var(--ink); font-size: 13px; }
#readonly { padding: 6px 16px; font-size: 12px; color: #ffd98b; background: rgba(244, 180, 58, .1);
  border-bottom: 1px solid rgba(244, 180, 58, .28); }
main { flex: 1; display: flex; min-height: 0; }
#side { width: 264px; flex: none; overflow: auto; padding: 12px; border-right: 1px solid var(--line);
  background: #0a0f0c; }
#side section { margin-bottom: 16px; }
#side h2 { margin: 0 0 8px; font-size: 12px; letter-spacing: .08em; color: var(--dim); text-transform: uppercase; }
.row { display: flex; gap: 6px; flex-wrap: wrap; margin-bottom: 8px; }
button { padding: 5px 10px; font: inherit; font-size: 12px; color: var(--ink); cursor: pointer;
  border: 1px solid var(--line); border-radius: 6px; background: rgba(238, 243, 238, .06); }
button:hover { border-color: rgba(244, 180, 58, .7); background: rgba(244, 180, 58, .14); }
.layers { display: grid; gap: 4px; max-height: 45vh; overflow: auto; }
.layers label { display: flex; align-items: center; gap: 7px; padding: 4px 6px; font-size: 12px;
  border: 1px solid transparent; border-radius: 6px; }
.layers label:hover { border-color: var(--line); background: rgba(238, 243, 238, .05); }
.layers span { flex: 1; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.layers em { color: var(--dim); font-style: normal; font-size: 11px; }
.hint { margin: 0; font-size: 12px; line-height: 1.6; color: var(--dim); }
.hint code { font-size: 11px; }
#info .irow { display: flex; justify-content: space-between; gap: 10px; padding: 3px 0; font-size: 12px;
  border-bottom: 1px dashed rgba(238, 243, 238, .1); }
#info .irow span { color: var(--dim); }
#info .irow b { font-weight: 500; text-align: right; word-break: break-all; }
#info.error { color: #ffb4a8; }
#stage { position: relative; flex: 1; min-width: 0; }
#view { display: block; width: 100%; height: 100%; }
"""


_VIEWER_JS = r"""
/* 静态快照查看器：无框架、无构建、不联网。数据来自内嵌 JSON，three.js 来自本地 vendored 文件。 */
const THREE_BASE = "__THREE_BASE__";
const THREE_MODULE_URL = "__THREE_MODULE_URL__";
const THREE_APP_BASE = "/vendor/three/";
const MM_TO_M = 0.001;

let THREE = null;
let OrbitControls = null;
let renderer = null;
let scene = null;
let camera = null;
let controls = null;
let root = null;
let raycaster = null;
const layerGroups = new Map();
const layerInputs = new Map();
const pickables = [];
const materialCache = new Map();

const DATA = readJson("__SEMANTIC_ID__");
const MAP = buildMapper();

function el(id) { return document.getElementById(id); }

function readJson(id) {
  const node = document.getElementById(id);
  if (!node) return {};
  try {
    const parsed = JSON.parse(node.textContent || "{}");
    return parsed && typeof parsed === "object" ? parsed : {};
  } catch (error) {
    showInfo([["错误", "内嵌 semantic 数据无法解析：" + (error && error.message ? error.message : String(error))]]);
    return {};
  }
}

function arr(value) { return Array.isArray(value) ? value : []; }
function obj(value) { return value && typeof value === "object" && !Array.isArray(value) ? value : {}; }
function num(value, fallback) { const parsed = Number(value); return Number.isFinite(parsed) ? parsed : fallback; }

function point2(value) {
  if (!value) return null;
  const source = Array.isArray(value) ? { x: value[0], y: value[1] } : obj(value);
  const x = num(source.x, null);
  const y = num(source.y, null);
  return x === null || y === null ? null : { x, y };
}

function textOf(item) {
  const attrs = obj(item.attributes);
  return [item.type, item.kind, item.label, item.original_layer, item.original_block_name, attrs.category, attrs.zone]
    .filter(function (value) { return typeof value === "string" && value; })
    .join(" ")
    .toLowerCase();
}

/* ---------- 几何：统一采样成折线（单位 mm） ---------- */

function sampleArc(cx, cy, radius, startDeg, endDeg, full) {
  const steps = full ? 48 : 24;
  const start = num(startDeg, 0) * Math.PI / 180;
  let sweep = full ? Math.PI * 2 : num(endDeg, 360) * Math.PI / 180 - start;
  if (!full) { while (sweep <= 0) sweep += Math.PI * 2; }
  const points = [];
  for (let index = 0; index <= steps; index += 1) {
    const angle = start + sweep * (index / steps);
    points.push({ x: cx + Math.cos(angle) * radius, y: cy + Math.sin(angle) * radius });
  }
  return points;
}

function polyline(geometry) {
  const geo = obj(geometry);
  const type = String(geo.type || "").toLowerCase();
  if (type === "point" || type === "multipoint") return [];
  if (type === "circle") {
    const center = point2(geo.center);
    const radius = num(geo.radius, 0);
    return center && radius > 0 ? sampleArc(center.x, center.y, radius, 0, 360, true) : [];
  }
  if (type === "arc") {
    const center = point2(geo.center);
    const radius = num(geo.radius, 0);
    return center && radius > 0 ? sampleArc(center.x, center.y, radius, geo.start_angle, geo.end_angle, false) : [];
  }
  const points = arr(geo.points).map(point2).filter(Boolean);
  if (points.length >= 2) return points;
  const single = point2(geo.position) || point2(geo.center);
  return single ? [single] : [];
}

function anchor(geometry) {
  const geo = obj(geometry);
  const direct = point2(geo.position) || point2(geo.center) || point2(geo.start) || point2(geo.end);
  if (direct) return direct;
  const points = polyline(geo);
  if (!points.length) return null;
  let sx = 0;
  let sy = 0;
  for (const point of points) { sx += point.x; sy += point.y; }
  return { x: sx / points.length, y: sy / points.length };
}

function allItems() {
  return arr(DATA.structures).concat(arr(DATA.areas), arr(DATA.office_objects), arr(DATA.parking_spaces),
    arr(DATA.cables), arr(DATA.devices), arr(DATA.fixtures));
}

function boundsOf(data) {
  const extents = obj(data.extents);
  const min = point2(extents.min);
  const max = point2(extents.max);
  if (min && max && max.x > min.x && max.y > min.y) return { min: min, max: max };
  let x0 = Infinity, y0 = Infinity, x1 = -Infinity, y1 = -Infinity;
  const track = function (point) {
    if (!point) return;
    x0 = Math.min(x0, point.x); y0 = Math.min(y0, point.y);
    x1 = Math.max(x1, point.x); y1 = Math.max(y1, point.y);
  };
  for (const item of allItems()) {
    for (const point of polyline(item.geometry)) track(point);
    track(anchor(item.geometry));
  }
  if (!Number.isFinite(x0) || x1 <= x0 || y1 <= y0) return { min: { x: 0, y: 0 }, max: { x: 1000, y: 1000 } };
  return { min: { x: x0, y: y0 }, max: { x: x1, y: y1 } };
}

function buildMapper() {
  const bounds = boundsOf(DATA);
  const centerX = (bounds.min.x + bounds.max.x) / 2;
  const centerY = (bounds.min.y + bounds.max.y) / 2;
  return {
    bounds: bounds,
    size: {
      x: Math.max((bounds.max.x - bounds.min.x) * MM_TO_M, 1),
      y: Math.max((bounds.max.y - bounds.min.y) * MM_TO_M, 1),
    },
    toXZ: function (point) {
      const safe = point || { x: 0, y: 0 };
      return { x: (safe.x - centerX) * MM_TO_M, z: -(safe.y - centerY) * MM_TO_M };
    },
    toWorld: function (point, height) {
      const mapped = this.toXZ(point);
      return new THREE.Vector3(mapped.x, num(height, 0), mapped.z);
    },
  };
}

/* ---------- 分类与图层 ---------- */

const CATEGORIES = [
  { key: "camera", color: 0xff6b6b, shape: "box", size: 0.34, test: /camera|枪机|半球|鱼眼|球机|摄像/ },
  { key: "ap", color: 0x4dd0e1, shape: "cylinder", size: 0.26, test: /\bap\b|wireless|无线|wifi/ },
  { key: "lighting", color: 0xfff1a8, shape: "cylinder", size: 0.3, test: /light|floodlight|照明|射灯|灯具/ },
  { key: "cabinet", color: 0xb388ff, shape: "box", size: 0.7, test: /cabinet|rack|机柜|配线架/ },
  { key: "power", color: 0xffd166, shape: "box", size: 0.4, test: /breaker|power|配电|电源|供电|ups/ },
  { key: "network", color: 0x7ee0b0, shape: "box", size: 0.4, test: /network|switch|网络|交换机|路由器/ },
  { key: "cable", color: 0xf4b43a, shape: "box", size: 0.3, test: /cable|trunk|桥架|线路|线缆/ },
  { key: "building", color: 0x9aa7b0, shape: "box", size: 0.5, test: /wall|building|structure|outline|墙|柱|结构|门/ },
  { key: "area", color: 0x6f8fa8, shape: "box", size: 0.5, test: /area|zone|区域|分区|场地/ },
];
const DEFAULT_CATEGORY = { key: "device", color: 0xdfe6df, shape: "box", size: 0.32, test: null };

function categoryOf(item) {
  const text = textOf(item);
  for (const category of CATEGORIES) {
    if (category.test.test(text)) return category;
  }
  return DEFAULT_CATEGORY;
}

function layerNameOf(item, fallback) {
  const attrs = obj(item.attributes);
  const raw = item.original_layer || item.layer || attrs.layer || attrs.layer_name || attrs.floor_label || "";
  const name = String(raw === null || raw === undefined ? "" : raw).trim();
  return name || fallback;
}

function infoRows(item, fallbackKind) {
  const attrs = obj(item.attributes);
  const geo = obj(item.geometry);
  const confidence = item.confidence === null || item.confidence === undefined
    ? "-"
    : Math.round(num(item.confidence, 0) * 100) + "%";
  const rows = [
    ["对象类型", item.type || fallbackKind || "未分类"],
    ["编号 / 名称", item.label || item.id || "-"],
    ["图层", item.original_layer || item.layer || "-"],
    ["块名", item.original_block_name || "-"],
    ["几何", geo.type || "-"],
    ["置信度", confidence],
  ];
  const notes = [
    ["安装高度", attrs.install_height_m, " m"],
    ["覆盖半径", attrs.coverage_radius_m, " m"],
    ["线缆介质", attrs.media, ""],
    ["楼层", attrs.floor_label, ""],
  ];
  for (const [label, value, unit] of notes) {
    if (value === null || value === undefined || value === "") continue;
    rows.push([label, unit ? num(value, 0) + unit : String(value)]);
  }
  if (item.length_mm !== null && item.length_mm !== undefined) rows.push(["长度", Math.round(num(item.length_mm, 0)) + " mm"]);
  if (item.source_entity_id) rows.push(["来源实体", String(item.source_entity_id)]);
  return rows;
}

/* ---------- three.js 资源 ---------- */

function meshMaterial(color, options) {
  const key = "m:" + color + ":" + JSON.stringify(options || {});
  let cached = materialCache.get(key);
  if (!cached) {
    cached = new THREE.MeshStandardMaterial(Object.assign({
      color: color, metalness: 0.08, roughness: 0.78, side: THREE.DoubleSide,
    }, options || {}));
    materialCache.set(key, cached);
  }
  return cached;
}

function lineMaterial(color, opacity) {
  const key = "l:" + color + ":" + opacity;
  let cached = materialCache.get(key);
  if (!cached) {
    cached = new THREE.LineBasicMaterial({ color: color, transparent: opacity < 1, opacity: opacity });
    materialCache.set(key, cached);
  }
  return cached;
}

function groupFor(layer) {
  let group = layerGroups.get(layer);
  if (!group) {
    group = new THREE.Group();
    group.name = layer;
    root.add(group);
    layerGroups.set(layer, group);
  }
  return group;
}

function tag(object, rows) {
  object.userData.rows = rows;
  pickables.push(object);
  return object;
}

/* ---------- 建模 ---------- */

function isClosedRing(points, geometry) {
  const geo = obj(geometry);
  if (geo.closed === true) return true;
  if (String(geo.type || "").toLowerCase() === "polygon" && points.length >= 3) return true;
  if (points.length < 4) return false;
  const first = points[0];
  const last = points[points.length - 1];
  return Math.abs(first.x - last.x) < 1e-6 && Math.abs(first.y - last.y) < 1e-6;
}

function addExtrudedPolygon(item, points, height, group, color) {
  const shape = new THREE.Shape();
  points.forEach(function (point, index) {
    const mapped = MAP.toXZ(point);
    if (index === 0) shape.moveTo(mapped.x, -mapped.z);
    else shape.lineTo(mapped.x, -mapped.z);
  });
  shape.closePath();
  const geometry = new THREE.ExtrudeGeometry(shape, { depth: Math.max(height, 0.2), bevelEnabled: false });
  const mesh = new THREE.Mesh(geometry, meshMaterial(color));
  mesh.rotation.x = -Math.PI / 2;
  group.add(tag(mesh, infoRows(item, "structure")));
}

const MAX_WALL_BOXES = 4000;
let wallBoxCount = 0;

function addWallStrip(item, points, height, group, color) {
  const vectors = points.map(function (point) { return MAP.toWorld(point, 0); });
  const thickness = Math.min(Math.max(height * 0.06, 0.12), 1.2);
  for (let index = 0; index < vectors.length - 1; index += 1) {
    const from = vectors[index];
    const to = vectors[index + 1];
    const length = from.distanceTo(to);
    if (!(length > 0.01)) continue;
    if (wallBoxCount < MAX_WALL_BOXES) {
      wallBoxCount += 1;
      const mesh = new THREE.Mesh(new THREE.BoxGeometry(length, height, thickness), meshMaterial(color));
      mesh.position.set((from.x + to.x) / 2, height / 2, (from.z + to.z) / 2);
      mesh.rotation.y = -Math.atan2(to.z - from.z, to.x - from.x);
      group.add(tag(mesh, infoRows(item, "structure")));
    } else {
      const line = new THREE.Line(new THREE.BufferGeometry().setFromPoints([from, to]), lineMaterial(color, 1));
      group.add(tag(line, infoRows(item, "structure")));
    }
  }
}

function addFlatPolygon(item, points, group, color) {
  const shape = new THREE.Shape();
  points.forEach(function (point, index) {
    const mapped = MAP.toXZ(point);
    if (index === 0) shape.moveTo(mapped.x, -mapped.z);
    else shape.lineTo(mapped.x, -mapped.z);
  });
  shape.closePath();
  const mesh = new THREE.Mesh(new THREE.ShapeGeometry(shape), meshMaterial(color, {
    transparent: true, opacity: 0.16, depthWrite: false,
  }));
  mesh.rotation.x = -Math.PI / 2;
  mesh.position.y = 0.02;
  group.add(tag(mesh, infoRows(item, "area")));

  const outline = points.map(function (point) { return MAP.toWorld(point, 0.03); });
  if (outline.length >= 2) {
    outline.push(outline[0]);
    group.add(new THREE.Line(new THREE.BufferGeometry().setFromPoints(outline), lineMaterial(color, 0.85)));
  }
}

function addLine(item, points, height, group, color, fallbackKind) {
  const vectors = points.map(function (point) { return MAP.toWorld(point, height); });
  if (vectors.length < 2) return;
  const line = new THREE.Line(new THREE.BufferGeometry().setFromPoints(vectors), lineMaterial(color, 0.95));
  group.add(tag(line, infoRows(item, fallbackKind)));
}

function addDevice(item, group, color, shape, size) {
  const point = anchor(item.geometry);
  if (!point) return;
  const attrs = obj(item.attributes);
  const height = num(attrs.install_height_m, num(attrs.height_m, 2.5));
  const geometry = shape === "cylinder"
    ? new THREE.CylinderGeometry(size, size, size * 1.4, 16)
    : new THREE.BoxGeometry(size, size * 1.1, size * 0.7);
  const mesh = new THREE.Mesh(geometry, meshMaterial(color));
  mesh.position.copy(MAP.toWorld(point, height));
  mesh.rotation.y = num(attrs.rotation_deg, 0) * Math.PI / 180;
  group.add(tag(mesh, infoRows(item, "device")));
}

function build() {
  for (const item of arr(DATA.structures)) {
    const group = groupFor(layerNameOf(item, "建筑结构"));
    const category = categoryOf(item);
    const points = polyline(item.geometry);
    const height = Math.max(num(obj(item.attributes).height_m, num(item.height_m, 5)), 0.2);
    if (points.length >= 3 && isClosedRing(points, item.geometry)) addExtrudedPolygon(item, points, height, group, category.color);
    else if (points.length >= 2) addWallStrip(item, points, height, group, category.color);
    else {
      const single = anchor(item.geometry);
      if (single) addDevice(item, group, category.color, "box", Math.max(category.size, 0.4));
    }
  }

  for (const item of arr(DATA.areas).concat(arr(DATA.office_objects), arr(DATA.parking_spaces))) {
    const group = groupFor(layerNameOf(item, "区域"));
    const category = categoryOf(item);
    const points = polyline(item.geometry);
    if (points.length >= 3 && isClosedRing(points, item.geometry)) addFlatPolygon(item, points, group, category.color);
    else if (points.length >= 2) addLine(item, points, 0.05, group, category.color, "area");
  }

  for (const item of arr(DATA.cables)) {
    const group = groupFor(layerNameOf(item, "弱电线路"));
    const category = categoryOf(item);
    const points = polyline(item.geometry);
    const height = num(obj(item.attributes).install_height_m, 0.6);
    addLine(item, points, height, group, category.color, "cable");
  }

  for (const item of arr(DATA.devices).concat(arr(DATA.fixtures))) {
    const group = groupFor(layerNameOf(item, "设备"));
    const category = categoryOf(item);
    addDevice(item, group, category.color, category.shape, category.size);
  }
}

/* ---------- 视图 ---------- */

function addGround() {
  const size = Math.max(MAP.size.x, MAP.size.y) * 1.6 + 20;
  const divisions = Math.min(Math.max(Math.round(size / 5), 8), 240);
  const grid = new THREE.GridHelper(size, divisions, 0x33413a, 0x1d2622);
  scene.add(grid);
  const planeGeometry = new THREE.PlaneGeometry(size, size);
  planeGeometry.rotateX(-Math.PI / 2);
  const plane = new THREE.Mesh(planeGeometry, meshMaterial(0x111813, { roughness: 1, metalness: 0, transparent: false }));
  plane.position.y = -0.02;
  scene.add(plane);
}

function sceneBox() {
  return new THREE.Box3().setFromObject(root);
}

function fitView() {
  const box = sceneBox();
  if (!box || box.isEmpty()) return;
  const size = box.getSize(new THREE.Vector3());
  const center = box.getCenter(new THREE.Vector3());
  const radius = Math.max(size.length() * 0.55, 5);
  const fov = camera.fov * Math.PI / 180;
  const distance = radius / Math.max(Math.tan(fov / 2), 0.1);
  camera.position.set(center.x + distance * 0.55, center.y + distance * 0.8, center.z + distance * 0.75);
  camera.near = Math.max(distance / 2000, 0.05);
  camera.far = distance * 40 + 500;
  camera.updateProjectionMatrix();
  controls.target.copy(center);
  controls.update();
}

function topView() {
  const box = sceneBox();
  if (!box || box.isEmpty()) return;
  const size = box.getSize(new THREE.Vector3());
  const center = box.getCenter(new THREE.Vector3());
  const distance = Math.max(size.x, size.z) * 1.2 + 10;
  camera.position.set(center.x, center.y + distance, center.z + 0.001);
  camera.near = 0.05;
  camera.far = distance * 20 + 500;
  camera.updateProjectionMatrix();
  controls.target.copy(center);
  controls.update();
}

function resize() {
  const stage = el("stage");
  const width = Math.max(stage ? stage.clientWidth : window.innerWidth, 1);
  const height = Math.max(stage ? stage.clientHeight : window.innerHeight, 1);
  renderer.setSize(width, height, false);
  camera.aspect = width / height;
  camera.updateProjectionMatrix();
}

function animate() {
  window.requestAnimationFrame(animate);
  if (controls) controls.update();
  if (renderer && scene && camera) renderer.render(scene, camera);
}

/* ---------- 交互与信息面板 ---------- */

function escapeHtml(value) {
  return String(value)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
}

function showInfo(rows) {
  const box = el("info");
  if (!box) return;
  box.className = "";
  box.innerHTML = rows.map(function (row) {
    return '<div class="irow"><span>' + escapeHtml(row[0]) + "</span><b>" + escapeHtml(row[1]) + "</b></div>";
  }).join("");
}

function showFatal(message) {
  const box = el("info");
  if (box) {
    box.className = "hint error";
    box.textContent = "three.js 加载失败（" + message + "）。可能原因："
      + "1) 导出页与仓库 frontend/vendor/three/ 的相对位置已变，或 vendored three.js 缺失；"
      + "2) 用 Chrome 以 file:// 直接打开时浏览器会拦截跨文件 ES module 加载"
      + "（可改用 Firefox/Safari，或把导出目录放到静态服务器、应用的 /exports/ 挂载下访问，"
      + "例如 python -m http.server）；"
      + "3) 由应用托管时请确认 /vendor/three/ 可访问。";
  }
}

function isVisible(object) {
  let node = object;
  while (node) {
    if (node.visible === false) return false;
    node = node.parent;
  }
  return true;
}

function pick(clientX, clientY) {
  const rect = renderer.domElement.getBoundingClientRect();
  const pointer = new THREE.Vector2(
    ((clientX - rect.left) / Math.max(rect.width, 1)) * 2 - 1,
    -((clientY - rect.top) / Math.max(rect.height, 1)) * 2 + 1
  );
  raycaster.setFromCamera(pointer, camera);
  const hits = raycaster.intersectObjects(pickables, false);
  const hit = hits.filter(function (entry) { return isVisible(entry.object); })[0];
  if (!hit || !hit.object.userData.rows) {
    showInfo([["提示", "未选中对象，点击设备 / 结构 / 线路可查看属性。"]]);
    return;
  }
  showInfo(hit.object.userData.rows);
}

function setAllLayers(visible) {
  layerGroups.forEach(function (group, layer) {
    group.visible = visible;
    const input = layerInputs.get(layer);
    if (input) input.checked = visible;
  });
}

function buildLayerPanel() {
  const box = el("layers");
  if (!box) return;
  const names = Array.from(layerGroups.keys()).sort(function (a, b) { return a.localeCompare(b, "zh-Hans-CN"); });
  if (!names.length) {
    box.innerHTML = '<p class="hint">没有可显示的图层数据。</p>';
    return;
  }
  box.innerHTML = "";
  names.forEach(function (name) {
    const group = layerGroups.get(name);
    const label = document.createElement("label");
    const input = document.createElement("input");
    input.type = "checkbox";
    input.checked = true;
    input.dataset.layer = name;
    input.addEventListener("change", function () { group.visible = input.checked; });
    layerInputs.set(name, input);
    const text = document.createElement("span");
    text.textContent = name;
    text.title = name;
    const count = document.createElement("em");
    count.textContent = String(group.children.length);
    label.appendChild(input);
    label.appendChild(text);
    label.appendChild(count);
    box.appendChild(label);
  });
}

/* ---------- 启动 ---------- */

async function loadThree() {
  // 基址顺序很关键：
  // - 由应用托管（http/https）时，frontend 挂在 `/`，`/vendor/three/` 一定可达；
  //   而按文件系统算出的相对路径在 URL 层面会被浏览器截断到根，导致 404。
  // - 用 file:// 直接双击打开时，绝对路径 `/vendor/three/` 不可达，必须用文件相对路径。
  const isFileProtocol = (typeof location !== "undefined" && location.protocol === "file:");
  const bases = isFileProtocol ? [THREE_BASE, THREE_APP_BASE] : [THREE_APP_BASE, THREE_BASE];
  let lastError = null;
  for (const base of bases) {
    try {
      const three = await import(base + "three.module.js");
      const orbit = await import(base + "examples/jsm/controls/OrbitControls.js");
      if (three && orbit && orbit.OrbitControls) return { three: three, controls: orbit.OrbitControls };
      lastError = new Error("OrbitControls 未导出");
    } catch (error) {
      lastError = error;
    }
  }
  throw lastError || new Error("未知加载错误");
}

function initScene() {
  const canvas = el("view");
  renderer = new THREE.WebGLRenderer({ canvas: canvas, antialias: true });
  renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, 2));
  scene = new THREE.Scene();
  scene.background = new THREE.Color(0x070a08);
  camera = new THREE.PerspectiveCamera(50, 1, 0.1, 50000);
  controls = new OrbitControls(camera, renderer.domElement);
  controls.enableDamping = true;
  controls.dampingFactor = 0.08;
  controls.screenSpacePanning = true;
  scene.add(new THREE.HemisphereLight(0xdfe9ff, 0x22302a, 1.15));
  const sun = new THREE.DirectionalLight(0xffffff, 1.1);
  sun.position.set(60, 120, 40);
  scene.add(sun);
  root = new THREE.Group();
  scene.add(root);
  raycaster = new THREE.Raycaster();
  raycaster.params.Line.threshold = 0.6;
  addGround();
  build();
  buildLayerPanel();
  resize();
  fitView();
  window.addEventListener("resize", resize);

  let pressed = null;
  renderer.domElement.addEventListener("pointerdown", function (event) { pressed = { x: event.clientX, y: event.clientY }; });
  renderer.domElement.addEventListener("pointerup", function (event) {
    if (!pressed) return;
    const moved = Math.hypot(event.clientX - pressed.x, event.clientY - pressed.y);
    pressed = null;
    if (moved < 4) pick(event.clientX, event.clientY);
  });
  el("fit").addEventListener("click", fitView);
  el("topView").addEventListener("click", topView);
  el("perspView").addEventListener("click", fitView);
  el("layersAll").addEventListener("click", function () { setAllLayers(true); });
  el("layersNone").addEventListener("click", function () { setAllLayers(false); });
}

function boot() {
  loadThree().then(function (lib) {
    THREE = lib.three;
    OrbitControls = lib.controls;
    initScene();
    animate();
    const stats = obj(DATA.stats);
    showInfo([
      ["项目", obj(DATA.project).name || "-"],
      ["图纸", obj(DATA.project).drawing_name || obj(DATA.project).drawing_id || "-"],
      ["设备", String(num(stats.devices, 0))],
      ["线路", String(num(stats.cables, 0))],
      ["结构", String(num(stats.structures, 0))],
      ["区域", String(num(stats.areas, 0))],
      ["实体总数", String(num(stats.total_entities, 0))],
      ["提示", "点击场景对象查看属性；此页为只读快照。"],
    ]);
  }).catch(function (error) {
    showFatal(error && error.message ? error.message : String(error));
  });
}

boot();
"""
