from __future__ import annotations

import html
import json
from datetime import datetime
from pathlib import Path
from typing import Any


def _esc(value: Any) -> str:
    return html.escape("" if value is None else str(value))


def _copy_button_script() -> str:
    return """
function copyBlock(id, btn) {
  const node = document.getElementById(id);
  if (!node) return;
  const text = node.innerText;
  const done = (ok) => { btn.textContent = ok ? '已复制' : '复制失败'; setTimeout(() => btn.textContent = '复制', 1200); };
  if (navigator.clipboard && navigator.clipboard.writeText) {
    navigator.clipboard.writeText(text).then(() => done(true)).catch(() => done(false));
    return;
  }
  const area = document.createElement('textarea');
  area.value = text;
  document.body.appendChild(area);
  area.select();
  try { done(document.execCommand('copy')); } catch (err) { done(false); }
  area.remove();
}
"""


def render_html(summary: dict[str, Any], output_path: Path) -> Path:
    cases = summary.get("cases") or []
    rows = []
    for item in cases:
        metrics = item.get("metrics") or {}
        stats = metrics.get("stats") or {}
        spec = item.get("specificity") or {}
        desired = item.get("desired_compare") or {}
        if item.get("mode") == "fixture":
            status = "基线通过" if item.get("ok") else "基线缺口"
            if (item.get("desired_compare") or {}).get("enabled") and not (item.get("desired_compare") or {}).get("passed"):
                status += " / 通用未达标"
        else:
            status = "已收集"
        rows.append(
            f"<tr class='{'ok' if item.get('ok') else 'gap'}'>"
            f"<td>{_esc(item.get('id'))}</td>"
            f"<td>{_esc(item.get('name'))}</td>"
            f"<td>{_esc(item.get('mode'))}</td>"
            f"<td>{_esc(', '.join(item.get('site_profiles') or []))}</td>"
            f"<td>{_esc(stats.get('devices'))}</td>"
            f"<td>{_esc(stats.get('cables'))}</td>"
            f"<td>{_esc(stats.get('structures'))}</td>"
            f"<td>{_esc(stats.get('frames'))}</td>"
            f"<td>{_esc(spec.get('score'))} / {_esc(spec.get('level'))}</td>"
            f"<td>{_esc('是' if metrics.get('render_ready') else '否')}</td>"
            f"<td>{_esc(status)}</td>"
            f"</tr>"
        )
    fixture_gaps = []
    for item in cases:
        if item.get("mode") == "fixture":
            for gap in (item.get("desired_compare") or {}).get("gaps") or []:
                fixture_gaps.append(f"{item.get('id')}: {gap}")
    gap_html = "".join(f"<li>{_esc(gap)}</li>" for gap in fixture_gaps) or "<li>公开夹具暂无 desired 缺口</li>"
    payload_id = "summary-json"
    generated = summary.get("generated_at") or datetime.now().isoformat(timespec="seconds")
    html_doc = f"""<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>CAD 通用解析评测报告</title>
  <style>
    :root {{ --bg:#10140f; --card:#1a211b; --line:#2c382e; --text:#e7efe6; --muted:#93a094; --ok:#7ddc83; --gap:#ffb020; --bad:#ff6b6b; }}
    * {{ box-sizing:border-box; }}
    body {{ margin:0; font:15px/1.55 -apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif; background:var(--bg); color:var(--text); }}
    main {{ max-width:1180px; margin:0 auto; padding:32px 20px 64px; }}
    h1,h2 {{ margin:0 0 12px; }}
    .muted {{ color:var(--muted); }}
    .cards {{ display:grid; grid-template-columns:repeat(auto-fit,minmax(160px,1fr)); gap:12px; margin:20px 0 28px; }}
    .card {{ background:var(--card); border:1px solid var(--line); border-radius:12px; padding:14px 16px; }}
    .card b {{ display:block; font-size:28px; margin-top:6px; }}
    table {{ width:100%; border-collapse:collapse; background:var(--card); border-radius:12px; overflow:hidden; }}
    th,td {{ text-align:left; padding:10px 12px; border-bottom:1px solid var(--line); vertical-align:top; }}
    tr.gap td:last-child {{ color:var(--gap); font-weight:700; }}
    tr.ok td:last-child {{ color:var(--ok); }}
    pre {{ background:#0c100c; border:1px solid var(--line); border-radius:12px; padding:14px; overflow:auto; }}
    .toolbar {{ display:flex; justify-content:flex-end; margin:8px 0; }}
    button {{ background:#243027; color:var(--text); border:1px solid var(--line); border-radius:8px; padding:6px 10px; cursor:pointer; }}
    section {{ margin:32px 0; }}
  </style>
</head>
<body>
  <main>
    <h1>CAD 通用解析评测报告</h1>
    <p class="muted">生成时间 {_esc(generated)} · 公开夹具测通用能力，本地项目只做收集分析、不写入仓库。</p>
    <div class="cards">
      <div class="card">用例<b>{_esc(summary.get('case_count'))}</b></div>
      <div class="card">回归基线缺口<b>{_esc(summary.get('fixture_gap_count'))}</b></div>
      <div class="card">通用目标缺口<b>{_esc(summary.get('desired_gap_count'))}</b></div>
      <div class="card">可渲染<b>{_esc(summary.get('render_ready_count'))}</b></div>
      <div class="card">高百世耦合<b>{_esc(summary.get('high_specificity_count'))}</b></div>
    </div>
    <section>
      <h2>方案口径</h2>
      <p>当前默认 profile 是 <code>generic</code>。评测把「公开通用最小图」和「本机已有项目」分开：前者衡量能不能独立读一张正常强弱电图，后者只收集现状，不当作开源金标。百世 <code>express</code> / <code>supply_chain</code> 仍可作为可选场地包启用。</p>
    </section>
    <section>
      <h2>用例结果</h2>
      <table>
        <thead><tr><th>ID</th><th>名称</th><th>模式</th><th>Profile</th><th>设备</th><th>线路</th><th>结构</th><th>图框</th><th>百世耦合</th><th>可出 3D</th><th>夹具判定</th></tr></thead>
        <tbody>{''.join(rows)}</tbody>
      </table>
    </section>
    <section>
      <h2>通用夹具缺口</h2>
      <ul>{gap_html}</ul>
    </section>
    <section>
      <h2>原始汇总 JSON</h2>
      <p class="muted">复制后可贴进其他分析脚本。复制按钮用浏览器剪贴板，不依赖外部库。</p>
      <div class="toolbar"><button type="button" onclick="copyBlock('{payload_id}', this)">复制</button></div>
      <pre id="{payload_id}">{_esc(json.dumps(summary, ensure_ascii=False, indent=2))}</pre>
    </section>
  </main>
  <script>{_copy_button_script()}</script>
</body>
</html>
"""
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(html_doc, encoding="utf-8")
    return output_path
