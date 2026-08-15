from __future__ import annotations

import argparse
import json
import sys
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


def load_cases() -> dict[str, Any]:
    path = Path(__file__).with_name("cases.yaml")
    return yaml.safe_load(path.read_text(encoding="utf-8")) or {}


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
    return engine.build_semantic(parsed, source)


def evaluate_semantic(
    *,
    case_id: str,
    name: str,
    mode: str,
    semantic: dict[str, Any],
    desired: dict[str, Any] | None = None,
    baseline: dict[str, Any] | None = None,
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
    if desired and desired.get("max_specificity") is not None:
        if float(specificity.get("score") or 0) > float(desired["max_specificity"]):
            desired_compare["passed"] = False
            desired_compare["gaps"] = list(desired_compare.get("gaps") or [])
            desired_compare["gaps"].append(
                f"specificity: actual={specificity.get('score')} desired<={desired['max_specificity']}"
            )
    ok = True if mode != "fixture" else bool(baseline_compare.get("passed") if baseline_compare.get("enabled") else desired_compare.get("passed"))
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


def run_public_fixtures(profile_override: str | None = None) -> list[dict[str, Any]]:
    config = load_cases()
    results: list[dict[str, Any]] = []
    for case in config.get("cases") or []:
        if case.get("kind") != "fixture":
            continue
        dxf = ROOT / str(case["dxf"])
        if case["id"] == "generic_electrical_min":
            dxf = build_generic_electrical_min(dxf)
        profile = profile_override or case.get("profile") or config.get("default_profile") or "express"
        try:
            if not dxf.exists():
                raise FileNotFoundError(f"缺少夹具 DXF: {dxf}")
            semantic = parse_dxf(dxf, profile)
            result = evaluate_semantic(
                case_id=case["id"],
                name=case.get("name") or case["id"],
                mode="fixture",
                semantic=semantic,
                desired=case.get("desired"),
                baseline=case.get("baseline"),
            )
            result["dxf"] = str(dxf.relative_to(ROOT))
            result["profile_requested"] = profile
        except Exception as exc:
            result = evaluate_semantic(
                case_id=case["id"],
                name=case.get("name") or case["id"],
                mode="fixture",
                semantic={},
                desired=case.get("desired"),
                baseline=case.get("baseline"),
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
