#!/usr/bin/env python3
"""Compare AGILAB UI screenshot evidence with visual baselines."""

from __future__ import annotations

import argparse
import importlib.util
import json
import re
import sys
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Mapping, Sequence


REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_BASELINE = REPO_ROOT / "docs/source/_static/page-shots/screenshot_manifest.json"
DEFAULT_CURRENT = REPO_ROOT / "screenshots/ui-visual-baseline-robot/current/screenshot_manifest.json"
SCHEMA = "agilab.ui_visual_baseline_report.v1"


@dataclass(frozen=True)
class VisualComparison:
    page: str
    status: str
    current_image: str
    baseline_image: str = ""
    detail: str = ""
    current_sha256: str = ""
    baseline_sha256: str = ""
    width_px: int | None = None
    height_px: int | None = None
    diff_ratio: float | None = None
    diff_pixels: int | None = None
    total_pixels: int | None = None


def _load_screenshot_manifest_module() -> Any:
    module_path = REPO_ROOT / "src/agilab/screenshot_manifest.py"
    spec = importlib.util.spec_from_file_location("ui_visual_baseline_screenshot_manifest", module_path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Could not load screenshot manifest module from {module_path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


SCREENSHOTS = _load_screenshot_manifest_module()


def _manifest_file(path: Path) -> Path:
    candidate = path.expanduser()
    if candidate.is_dir():
        candidate = candidate / SCREENSHOTS.SCREENSHOT_MANIFEST_FILENAME
    return candidate


def load_manifest(path: Path) -> Any:
    manifest_file = _manifest_file(path)
    payload = json.loads(manifest_file.read_text(encoding="utf-8"))
    return SCREENSHOTS.ScreenshotManifest.from_dict(payload)


def _record_image_path(manifest: Any, record: Any) -> Path:
    raw_path = Path(str(record.image_path)).expanduser()
    if raw_path.is_absolute():
        return raw_path
    root = Path(str(manifest.root)).expanduser()
    return root / raw_path


def normalize_page_key(value: str) -> str:
    normalized = re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")
    page_aliases = (
        ("home", ("home", "core-pages-overview", "start")),
        ("orchestrate", ("orchestrate", "execute")),
        ("workflow", ("workflow",)),
        ("analysis", ("analysis",)),
        ("settings", ("settings",)),
        ("project", ("project",)),
    )
    for page, aliases in page_aliases:
        if any(alias in normalized for alias in aliases):
            return page
    return normalized


def records_by_page(manifest: Any) -> dict[str, Any]:
    records: dict[str, Any] = {}
    for record in manifest.screenshots:
        page = normalize_page_key(str(record.page or Path(str(record.image_path)).stem))
        records.setdefault(page, record)
    return records


def _pixel_diff(
    current_path: Path,
    baseline_path: Path,
    *,
    channel_threshold: int,
) -> tuple[float | None, int | None, int | None, str | None]:
    try:
        from PIL import Image
    except ModuleNotFoundError:
        return None, None, None, "Pillow unavailable; compared metadata and hashes only"
    with Image.open(current_path) as current_image, Image.open(baseline_path) as baseline_image:
        current = current_image.convert("RGB")
        baseline = baseline_image.convert("RGB")
        if current.size != baseline.size:
            return None, None, None, f"image dimensions differ: current={current.size} baseline={baseline.size}"
        current_pixels = current.load()
        baseline_pixels = baseline.load()
        width, height = current.size
        total = width * height
        diff = 0
        for y in range(height):
            for x in range(width):
                a = current_pixels[x, y]
                b = baseline_pixels[x, y]
                if max(abs(a[0] - b[0]), abs(a[1] - b[1]), abs(a[2] - b[2])) > channel_threshold:
                    diff += 1
        return diff / max(1, total), diff, total, None


def build_report(
    *,
    current_manifest_path: Path,
    baseline_manifest_path: Path,
    max_diff_ratio: float,
    channel_threshold: int,
    allow_missing_baseline: bool,
) -> dict[str, Any]:
    current_manifest = load_manifest(current_manifest_path)
    baseline_manifest = load_manifest(baseline_manifest_path)
    current_records = records_by_page(current_manifest)
    baseline_records = records_by_page(baseline_manifest)
    comparisons: list[VisualComparison] = []
    for page, current_record in sorted(current_records.items()):
        current_path = _record_image_path(current_manifest, current_record)
        baseline_record = baseline_records.get(page)
        if baseline_record is None:
            status = "warning" if allow_missing_baseline else "failed"
            comparisons.append(
                VisualComparison(
                    page=page,
                    status=status,
                    current_image=str(current_path),
                    detail="no baseline screenshot matched this page",
                    current_sha256=str(current_record.sha256),
                    width_px=current_record.width_px,
                    height_px=current_record.height_px,
                )
            )
            continue
        baseline_path = _record_image_path(baseline_manifest, baseline_record)
        diff_ratio, diff_pixels, total_pixels, diff_error = _pixel_diff(
            current_path,
            baseline_path,
            channel_threshold=channel_threshold,
        )
        if diff_error and "dimensions differ" in diff_error:
            status = "failed"
            detail = diff_error
        elif diff_ratio is None:
            status = "matched" if current_record.sha256 == baseline_record.sha256 else "warning"
            detail = diff_error or "pixel diff unavailable"
        elif diff_ratio <= max_diff_ratio:
            status = "matched"
            detail = f"pixel diff ratio {diff_ratio:.6f} <= {max_diff_ratio:.6f}"
        else:
            status = "failed"
            detail = f"pixel diff ratio {diff_ratio:.6f} > {max_diff_ratio:.6f}"
        comparisons.append(
            VisualComparison(
                page=page,
                status=status,
                current_image=str(current_path),
                baseline_image=str(baseline_path),
                detail=detail,
                current_sha256=str(current_record.sha256),
                baseline_sha256=str(baseline_record.sha256),
                width_px=current_record.width_px,
                height_px=current_record.height_px,
                diff_ratio=diff_ratio,
                diff_pixels=diff_pixels,
                total_pixels=total_pixels,
            )
        )
    failed = [item for item in comparisons if item.status == "failed"]
    return {
        "schema": SCHEMA,
        "success": not failed,
        "current_manifest": str(_manifest_file(current_manifest_path)),
        "baseline_manifest": str(_manifest_file(baseline_manifest_path)),
        "max_diff_ratio": max_diff_ratio,
        "channel_threshold": channel_threshold,
        "allow_missing_baseline": allow_missing_baseline,
        "summary": {
            "comparison_count": len(comparisons),
            "matched_count": sum(1 for item in comparisons if item.status == "matched"),
            "warning_count": sum(1 for item in comparisons if item.status == "warning"),
            "failed_count": len(failed),
        },
        "comparisons": [asdict(item) for item in comparisons],
    }


def render_human(report: Mapping[str, Any]) -> str:
    summary = report.get("summary", {})
    lines = [
        "AGILAB UI visual baseline report",
        f"verdict: {'PASS' if report.get('success') else 'FAIL'}",
        (
            f"comparisons={summary.get('comparison_count', 0)} "
            f"matched={summary.get('matched_count', 0)} "
            f"warnings={summary.get('warning_count', 0)} "
            f"failed={summary.get('failed_count', 0)}"
        ),
    ]
    for item in report.get("comparisons", []):
        if item.get("status") != "matched":
            lines.append(f"- {item.get('page')}: {item.get('status')} - {item.get('detail')}")
    return "\n".join(lines)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--current", type=Path, default=DEFAULT_CURRENT, help="Current screenshot manifest path or directory.")
    parser.add_argument("--baseline", type=Path, default=DEFAULT_BASELINE, help="Baseline screenshot manifest path or directory.")
    parser.add_argument("--max-diff-ratio", type=float, default=0.02)
    parser.add_argument("--channel-threshold", type=int, default=10)
    parser.add_argument("--allow-missing-baseline", action="store_true")
    parser.add_argument("--advisory", action="store_true", help="Always exit zero while preserving failed comparisons in the JSON report.")
    parser.add_argument("--output", type=Path, help="Optional JSON report output path.")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(list(argv) if argv is not None else None)
    report = build_report(
        current_manifest_path=args.current,
        baseline_manifest_path=args.baseline,
        max_diff_ratio=args.max_diff_ratio,
        channel_threshold=args.channel_threshold,
        allow_missing_baseline=args.allow_missing_baseline,
    )
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2, sort_keys=True) if args.json else render_human(report))
    return 0 if args.advisory or report["success"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
