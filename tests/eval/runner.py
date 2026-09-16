from __future__ import annotations

import argparse
import json
import sys
import tempfile
from datetime import datetime
from pathlib import Path
from typing import Any

import yaml


ROOT = Path(__file__).resolve().parents[2]
BACKEND = ROOT / "backend"
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tests.eval.make_generic_fixture import build_generic_electrical_min
from tests.eval.metrics import collect_metrics, compare_desired, compare_targets
from tests.eval.report import render_html
from tests.eval.specificity import analyze_specificity
from tests.synthetic import BUILDERS as FIXTURE_BUILDERS
from tests.synthetic import build_named, write_dxf


def load_cases() -> dict[str, Any]:
    path = Path(__file__).with_name("cases.yaml")
    return yaml.safe_load(path.read_text(encoding="utf-8")) or {}


def materialize_fixture(case: dict[str, Any], *, output_dir: Path | None = None) -> Path:
    """按用例定义生成合成夹具并返回 DXF 路径。

    用例可以：
    - 指定 `builder` + `builder_args`：用 `tests/synthetic.py` 的生成器现场生成
      （不写入被跟踪的 fixture 文件，避免测试运行修改仓库内容）。
    - 指定 `dxf`：使用仓库内既有的合成 DXF。

    缺省写到临时目录；仅 `generic_electrical_min` 保留历史行为写回 tests/fixtures，
    因为它同时也是人工检查用的参考图。
    """
    case_id = str(case.get("id") or "case")
    builder = case.get("builder")
    if builder:
        if builder not in FIXTURE_BUILDERS:
            raise KeyError(f"未知夹具生成器: {builder}（可用: {', '.join(sorted(FIXTURE_BUILDERS))}）")
        kwargs = dict(case.get("builder_args") or {})
        target_dir = output_dir or Path(tempfile.mkdtemp(prefix="cad-eval-fixture-"))
        target = Path(target_dir) / f"{case_id}.dxf"
        target.parent.mkdir(parents=True, exist_ok=True)
        return write_dxf(target, build_named(str(builder), **kwargs))

    if case_id == "generic_electrical_min":
        # 现场生成到临时目录：测试运行**不得**修改被跟踪的夹具文件。
        # 仓库内测试时若已存在该夹具则直接复用（保证结果可复现，无需写入）。
        target_dir = output_dir or Path(tempfile.mkdtemp(prefix="cad-eval-fixture-"))
        target = Path(target_dir) / f"{case_id}.dxf"
        tracked = ROOT / str(case.get("dxf") or "")
        if tracked.exists():
            return tracked
        return build_generic_electrical_min(target)

    return ROOT / str(case["dxf"])


def parse_dxf(dxf_path: Path, profile: str) -> dict[str, Any]:
    from parser.dxf_reader import DxfReader
    from semantic.rule_engine import RuleEngine

    parsed = DxfReader.read(dxf_path)
    engine = RuleEngine(site_profiles=[profile])
    source = {
        "dxf_path": str(dxf_path),
        "original_name": dxf_path.name,
        "format": "dxf",
        "converted": False,
        "parsed_at": datetime.now().isoformat(timespec="seconds"),
    }
    semantic = engine.build_semantic(parsed, source)
    # 原始 CAD 实体层面的几何事实（与语义分类无关）：用于断言曲线与闭合几何确实被读到。
    semantic["geometry_facts"] = geometry_facts(parsed)
    return semantic


def geometry_facts(parsed: dict[str, Any]) -> dict[str, int]:
    """统计解析结果中的曲线/闭合/块引用/不支持实体数量。"""
    curved = 0
    closed = 0
    block_refs = 0
    for entity in parsed.get("entities") or []:
        entity_type = str(entity.get("entity_type") or "")
        geometry = entity.get("geometry") or {}
        if entity_type in {"ARC", "CIRCLE", "ELLIPSE"}:
            curved += 1
        if entity.get("has_arc_segments"):
            curved += 1
        if geometry.get("closed"):
            closed += 1
        if entity_type == "INSERT":
            block_refs += 1
    return {
        "curved_entities": curved,
        "closed_entities": closed,
        "block_references": block_refs,
        "skipped_unsupported_entities": int(parsed.get("skipped_unsupported_entities") or 0),
        "total_entities": int(parsed.get("total_entities") or 0),
    }


def evaluate_semantic(
    *,
    case_id: str,
    name: str,
    mode: str,
    semantic: dict[str, Any],
    desired: dict[str, Any] | None = None,
    baseline: dict[str, Any] | None = None,
    geometry: dict[str, Any] | None = None,
    error: str | None = None,
) -> dict[str, Any]:
    if error:
        return {
            "id": case_id,
            "name": name,
            "mode": mode,
            "ok": False,
            "error": error,
            "site_profiles": [],
            "metrics": {},
            "specificity": {"score": None, "level": "unknown", "hits": []},
            "baseline_compare": {"enabled": bool(baseline), "passed": False, "gaps": [error]},
            "desired_compare": {"enabled": bool(desired), "passed": False, "gaps": [error]},
        }
    metrics = collect_metrics(semantic)
    specificity = analyze_specificity(semantic)
    baseline_compare = compare_targets(metrics, baseline, "baseline")
    desired_compare = compare_desired(metrics, desired)
    if geometry:
        geometry_gaps = compare_geometry(metrics, geometry)
        desired_compare["gaps"] = list(desired_compare.get("gaps") or []) + geometry_gaps
        if geometry_gaps:
            desired_compare["passed"] = False
        desired_compare["geometry_enabled"] = True
    if desired and desired.get("max_specificity") is not None:
        if float(specificity.get("score") or 0) > float(desired["max_specificity"]):
            desired_compare["passed"] = False
            desired_compare["gaps"] = list(desired_compare.get("gaps") or [])
            desired_compare["gaps"].append(
                f"specificity: actual={specificity.get('score')} desired<={desired['max_specificity']}"
            )
    # ok 语义：有 baseline 时以 baseline 为准；否则看 desired 是否真的声明了断言。
    # desired 为空对象（或缺失）表示本用例只用单元/几何类断言，不应被判为失败。
    if mode != "fixture":
        ok = True
    elif baseline_compare.get("enabled"):
        ok = bool(baseline_compare.get("passed"))
    elif desired or geometry:
        ok = bool(desired_compare.get("passed"))
    else:
        ok = True
    return {
        "id": case_id,
        "name": name,
        "mode": mode,
        "ok": ok,
        "site_profiles": metrics.get("site_profiles") or [],
        "metrics": metrics,
        "specificity": specificity,
        "baseline_compare": baseline_compare,
        "desired_compare": desired_compare,
    }


def compare_geometry(metrics: dict[str, Any], expected: dict[str, Any]) -> list[str]:
    """比较原始 CAD 实体层面的几何事实（曲线/闭合/块引用/跳过的类型）。

    这些断言不依赖语义分类，用来证明「孤立几何特征确实被读到」，
    与 devices/cables 数量断言互补。
    """
    facts = metrics.get("geometry_facts") or {}
    gaps: list[str] = []
    for key, value in expected.items():
        actual = int(facts.get(key) or 0)
        if isinstance(value, dict):
            minimum = value.get("min")
            maximum = value.get("max")
            if minimum is not None and actual < int(minimum):
                gaps.append(f"geometry.{key}: actual={actual} desired>={minimum}")
            if maximum is not None and actual > int(maximum):
                gaps.append(f"geometry.{key}: actual={actual} desired<={maximum}")
        elif actual != int(value):
            gaps.append(f"geometry.{key}: actual={actual} desired={value}")
    return gaps


def run_public_fixtures(profile_override: str | None = None) -> list[dict[str, Any]]:
    config = load_cases()
    results: list[dict[str, Any]] = []
    for case in config.get("cases") or []:
        if case.get("kind") != "fixture":
            continue
        profile = profile_override or case.get("profile") or config.get("default_profile") or "express"
        try:
            dxf = materialize_fixture(case)
            semantic = parse_dxf(dxf, profile)
            result = evaluate_semantic(
                case_id=case["id"],
                name=case.get("name") or case["id"],
                mode="fixture",
                semantic=semantic,
                desired=case.get("desired"),
                baseline=case.get("baseline"),
            )
            try:
                result["dxf"] = str(dxf.relative_to(ROOT))
            except ValueError:
                # 临时目录里生成的夹具不属于仓库（这是有意为之：测试不修改被跟踪文件）
                result["dxf"] = f"<生成于临时目录>/{dxf.name}"
            result["profile_requested"] = profile
        except Exception as exc:
            result = evaluate_semantic(
                case_id=case["id"],
                name=case.get("name") or case["id"],
                mode="fixture",
                semantic={},
                desired=case.get("desired"),
                baseline=case.get("baseline"),
                geometry=case.get("geometry"),
                error=str(exc),
            )
        results.append(result)
    return results


def iter_local_semantics() -> list[dict[str, Any]]:
    found: list[dict[str, Any]] = []
    roots = [BACKEND / "projects", BACKEND / "projects-archive"]
    for root in roots:
        if not root.exists():
            continue
        for meta_path in sorted(root.glob("*/meta.json")):
            try:
                meta = json.loads(meta_path.read_text(encoding="utf-8"))
            except json.JSONDecodeError:
                continue
            drawing_id = meta.get("current_drawing_id")
            drawings = meta.get("drawings") or []
            drawing = next((item for item in drawings if item.get("id") == drawing_id), None)
            if drawing is None and drawings:
                drawing = drawings[0]
            if not drawing:
                continue
            semantic_value = drawing.get("semantic_path")
            semantic_path = Path(semantic_value) if semantic_value else meta_path.parent / str(drawing.get("id")) / "semantic.json"
            if not semantic_path.is_absolute():
                semantic_path = meta_path.parent / semantic_path
            if not semantic_path.exists():
                continue
            found.append(
                {
                    "id": f"local_{meta.get('id')}",
                    "name": str(meta.get("name") or meta.get("id")),
                    "project_id": meta.get("id"),
                    "semantic_path": semantic_path,
                }
            )
    return found


def run_local_existing() -> list[dict[str, Any]]:
    results: list[dict[str, Any]] = []
    for item in iter_local_semantics():
        try:
            semantic = json.loads(item["semantic_path"].read_text(encoding="utf-8"))
            result = evaluate_semantic(
                case_id=item["id"],
                name=item["name"],
                mode="existing",
                semantic=semantic,
            )
            result["project_id"] = item.get("project_id")
        except Exception as exc:
            result = evaluate_semantic(
                case_id=item["id"],
                name=item["name"],
                mode="existing",
                semantic={},
                error=str(exc),
            )
        results.append(result)
    return results


def build_summary(cases: list[dict[str, Any]]) -> dict[str, Any]:
    fixture_gaps = [item for item in cases if item.get("mode") == "fixture" and not item.get("ok")]
    return {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "case_count": len(cases),
        "fixture_gap_count": len(fixture_gaps),
        "render_ready_count": sum(1 for item in cases if (item.get("metrics") or {}).get("render_ready")),
        "high_specificity_count": sum(1 for item in cases if (item.get("specificity") or {}).get("level") == "high"),
        "cases": cases,
    }


def write_outputs(summary: dict[str, Any]) -> dict[str, Path]:
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    out_dir = ROOT / "exports" / "eval" / stamp
    latest = ROOT / "exports" / "eval" / "latest"
    out_dir.mkdir(parents=True, exist_ok=True)
    summary_path = out_dir / "summary.json"
    summary_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    report_path = render_html(summary, out_dir / "report.html")
    latest.mkdir(parents=True, exist_ok=True)
    (latest / "summary.json").write_text(summary_path.read_text(encoding="utf-8"), encoding="utf-8")
    (latest / "report.html").write_text(report_path.read_text(encoding="utf-8"), encoding="utf-8")
    return {"dir": out_dir, "summary": summary_path, "report": report_path, "latest_report": latest / "report.html"}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="CAD generic parse evaluation")
    parser.add_argument("--fixtures-only", action="store_true")
    parser.add_argument("--existing-only", action="store_true")
    parser.add_argument("--profile", default=None, help="覆盖夹具使用的 site profile")
    parser.add_argument("--strict", action="store_true", help="通用 desired 缺口也视为失败")
    args = parser.parse_args(argv)

    cases: list[dict[str, Any]] = []
    if not args.existing_only:
        cases.extend(run_public_fixtures(args.profile))
    if not args.fixtures_only:
        cases.extend(run_local_existing())
    desired_gaps = [
        item
        for item in cases
        if item.get("mode") == "fixture" and not (item.get("desired_compare") or {}).get("passed", True)
    ]
    summary = build_summary(cases)
    summary["desired_gap_count"] = len(desired_gaps)
    paths = write_outputs(summary)
    print(f"cases={summary['case_count']} baseline_gaps={summary['fixture_gap_count']} desired_gaps={summary['desired_gap_count']}")
    print(f"report={paths['report']}")
    print(f"latest={paths['latest_report']}")
    for item in cases:
        if item.get("mode") != "fixture":
            continue
        if not item.get("ok"):
            print("BASELINE_GAP", item.get("id"), "; ".join((item.get("baseline_compare") or {}).get("gaps") or [item.get("error") or ""]))
        for gap in (item.get("desired_compare") or {}).get("gaps") or []:
            print("DESIRED_GAP", item.get("id"), gap)
    if summary["fixture_gap_count"]:
        return 1
    if args.strict and desired_gaps:
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
