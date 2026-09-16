"""生成 docs/assets 下的演示截图。

为什么要这个脚本：仓库此前的 `demo-sanitized.png` 来自其它工具（界面为英文且画面文字与本仓库
前端不一致），无法从仓库证据证明其来源与可授权性。本脚本用**本仓库自己的代码 + 被跟踪的合成夹具**
重新生成演示图，产出可复现、可追溯到具体命令。

前提：
- 本机已安装依赖（`pip install -r requirements.txt`）与 Playwright 浏览器。
- Chrome 可用（脚本使用 `channel="chrome"`）；也可改用 `playwright install chromium` 后把
  `channel` 设为 None。

用法：
    python tools_docs/make_demo_screenshots.py
    python tools_docs/make_demo_screenshots.py --port 8500 --out docs/assets

产物：
    docs/assets/demo-scene.png    3D 场景（含图层列表与统计）
    docs/assets/demo-export.png   静态导出页（自包含离线 HTML）

安全性：仅使用 `tests/fixtures/generic_electrical_min.dxf`（由代码生成的合成图纸），
不读取任何客户图纸；服务运行在临时运行目录中，导出内容不含本机绝对路径。
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import signal
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "tests" / "fixtures" / "generic_electrical_min.dxf"
DEFAULT_OUT = ROOT / "docs" / "assets"


def wait_health(port: int, timeout: float = 90.0) -> bool:
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            with urllib.request.urlopen(f"http://127.0.0.1:{port}/api/health", timeout=2) as response:
                if response.status == 200:
                    return True
        except (urllib.error.URLError, OSError):
            time.sleep(0.7)
    return False


def upload(path: Path, port: int) -> dict:
    boundary = "----demoshot"
    payload = b"".join([
        f"--{boundary}\r\n".encode(),
        f'Content-Disposition: form-data; name="file"; filename="{path.name}"\r\n'.encode(),
        b"Content-Type: application/dxf\r\n\r\n",
        path.read_bytes(),
        f"\r\n--{boundary}--\r\n".encode(),
    ])
    request = urllib.request.Request(
        f"http://127.0.0.1:{port}/api/upload",
        data=payload,
        method="POST",
        headers={"Content-Type": f"multipart/form-data; boundary={boundary}"},
    )
    with urllib.request.urlopen(request, timeout=120) as response:
        return json.loads(response.read())


def main() -> int:
    parser = argparse.ArgumentParser(description="用本仓库代码生成演示截图")
    parser.add_argument("--port", type=int, default=8500)
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    parser.add_argument("--keep-runtime", action="store_true", help="保留临时运行目录便于排查")
    args = parser.parse_args()

    if not FIXTURE.is_file():
        print(f"[demo] 缺少合成夹具：{FIXTURE}", file=sys.stderr)
        return 2

    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        print("[demo] 需要 playwright：pip install -r requirements.txt 且安装浏览器", file=sys.stderr)
        return 3

    runtime = ROOT / ".tmp-demo-shots"
    if runtime.exists():
        shutil.rmtree(runtime, ignore_errors=True)
    runtime.mkdir(parents=True, exist_ok=True)

    env = dict(os.environ)
    env.update({
        "CAD_RUNTIME_ROOT": str(runtime / "runtime"),
        "CAD_EXPORTS_DIR": str(runtime / "exports"),
        "CAD_RUNTIME_STATE_DIR": str(runtime / "state"),
        "CAD_LOG_DIR": str(runtime / "logs"),
        "CAD_HOST": "127.0.0.1",
    })
    for key in ("CAD_ACCESS_TOKEN", "CAD_TOKEN_REQUIRED", "CAD_LAN_MODE", "CAD_SCOPE_PROJECT_ID"):
        env.pop(key, None)

    log_path = runtime / "server.log"
    log_handle = log_path.open("wb")
    process = subprocess.Popen(
        [sys.executable, str(ROOT / "backend" / "server.py"), "--port", str(args.port), "--no-open"],
        cwd=str(ROOT), env=env, stdout=log_handle, stderr=subprocess.STDOUT,
    )

    args.out.mkdir(parents=True, exist_ok=True)
    try:
        if not wait_health(args.port):
            print("[demo] 服务启动失败，日志尾部：", file=sys.stderr)
            print(log_path.read_text(encoding="utf-8", errors="replace")[-1200:], file=sys.stderr)
            return 4
        print(f"[demo] 服务已启动：http://127.0.0.1:{args.port}")

        info = upload(FIXTURE, args.port)
        print(f"[demo] 已上传合成夹具 {FIXTURE.name}（file_id={info.get('file_id')}）")

        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(channel="chrome")
            context = browser.new_context(viewport={"width": 1440, "height": 900}, device_scale_factor=1)
            page = context.new_page()
            console_errors: list[str] = []
            page.on("console", lambda m: console_errors.append(f"{m.type}: {m.text[:120]}") if m.type == "error" else None)
            page.on("pageerror", lambda e: console_errors.append(f"pageerror: {e}"))

            page.goto(f"http://127.0.0.1:{args.port}/", wait_until="networkidle")
            page.wait_for_timeout(2500)

            # 上传夹具由页面的 file input 触发，走真实的解析链路
            file_input = page.locator("input[type=file]").first
            file_input.set_input_files(str(FIXTURE))
            print("[demo] 等待解析完成…")

            project_state = None
            for _ in range(60):
                page.wait_for_timeout(1500)
                project_state = page.evaluate(
                    """async () => {
                        const list = await (await fetch('/api/projects')).json();
                        for (const item of list) {
                            const meta = await (await fetch(`/api/projects/${item.id}`)).json();
                            const drawing = (meta.drawings || []).find(d => (d.stats || {}).devices);
                            if (drawing) return {project: meta.id, drawing: drawing.id, stats: drawing.stats};
                        }
                        return null;
                    }"""
                )
                if project_state:
                    break

            if not project_state:
                print("[demo] 解析未在超时内完成", file=sys.stderr)
                return 5
            print(f"[demo] 解析结果：{json.dumps(project_state['stats'], ensure_ascii=False)[:160]}")

            # 场景稳定后截图
            page.wait_for_timeout(4000)
            scene_target = args.out / "demo-scene.png"
            page.screenshot(path=str(scene_target))
            print(f"[demo] 已生成 {scene_target}")

            # 静态导出页截图（自包含离线 HTML，由本仓库导出器生成）
            export_info = page.evaluate(
                """async (payload) => {
                    const res = await fetch(`/api/projects/${payload.project}/export-static`, {
                        method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify({})});
                    if (!res.ok) return {status: res.status};
                    const data = await res.json();
                    return {status: 200, url: data.url};
                }""",
                project_state,
            )
            if export_info.get("status") == 200:
                export_page = context.new_page()
                export_page.goto(f"http://127.0.0.1:{args.port}{export_info['url']}", wait_until="networkidle")
                export_page.wait_for_timeout(3500)
                export_target = args.out / "demo-export.png"
                export_page.screenshot(path=str(export_target))
                print(f"[demo] 已生成 {export_target}")
                export_page.close()
            else:
                print(f"[demo] 静态导出不可用（{export_info.get('status')}），跳过导出页截图", file=sys.stderr)

            if console_errors:
                print("[demo] 页面 console 报错：", file=sys.stderr)
                for line in console_errors[:5]:
                    print(f"  {line}", file=sys.stderr)

            browser.close()

        print("\n[demo] 可复现命令：")
        print(f"  python tools_docs/make_demo_screenshots.py --port {args.port}")
        return 0
    finally:
        process.send_signal(signal.SIGTERM)
        try:
            process.wait(timeout=20)
        except subprocess.TimeoutExpired:
            process.kill()
        log_handle.close()
        if not args.keep_runtime:
            shutil.rmtree(runtime, ignore_errors=True)


if __name__ == "__main__":
    raise SystemExit(main())
