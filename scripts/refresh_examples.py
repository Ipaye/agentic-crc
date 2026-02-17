"""Copy the latest analysis log outputs into the examples directory for demos."""

from __future__ import annotations

import argparse
import json
import shutil
from pathlib import Path
from typing import Iterable


def find_log_candidates(logs_root: Path) -> Iterable[Path]:
    """Yield candidate log directories sorted by modification time (most recent first)."""
    for entry in sorted(
        (entry for entry in logs_root.iterdir() if entry.is_dir() and entry.name.startswith("pr_")),
        key=lambda entry: entry.stat().st_mtime,
        reverse=True
    ):
        yield entry


def copy_logs(src_dir: Path, dest_root: Path) -> Path:
    """Copy the entire log directory into the examples/latest_logs namespace."""
    dest = dest_root / src_dir.name
    if dest.exists():
        shutil.rmtree(dest)
    shutil.copytree(src_dir, dest)
    return dest


def build_sample_summary(
    analysis_data: dict,
    log_dir: Path,
    max_issues: int = 3
) -> dict:
    """Prepare a lightweight summary that mirrors the sample artifact format."""
    results = analysis_data.get("results", [])
    summary_stats = analysis_data.get("summary", {})

    issues = []
    for result in results[:max_issues]:
        issues.append(
            {
                "rule_id": result.get("rule_id", "<unknown>"),
                "file_path": result.get("file_path", "unknown"),
                "line_number": result.get("line_number"),
                "severity": result.get("severity") or "unknown",
                "message": result.get("message", result.get("rule_name", "")),
            }
        )

    total_issues = summary_stats.get("total_issues", len(results))
    files_count = len(summary_stats.get("issues_per_file", {}))
    summary_text = (
        f"Detected {total_issues} issue{'s' if total_issues != 1 else ''}"
        f" across {files_count} file{'s' if files_count != 1 else ''}."
    )

    return {
        "summary": summary_text,
        "issues": issues,
        "logs": ["analysis_results.json", "analysis_results.jsonl", "analysis_results.csv"],
        "source_log_dir": str(log_dir),
        "summary_stats": summary_stats,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Refresh the examples/ artifacts from the latest run.")
    parser.add_argument("--logs-root", type=Path, default=Path("logs"), help="Directory containing log exports.")
    parser.add_argument("--examples-dir", type=Path, default=Path("examples"), help="Examples directory to update.")
    parser.add_argument("--latest-logs-dir", type=Path, default=Path("examples/latest_logs"), help="Destination for copied logs.")
    parser.add_argument("--sample-file", type=Path, default=Path("examples/sample_review_summary.json"), help="Summary JSON to overwrite.")
    parser.add_argument("--max-issues", type=int, default=3, help="Maximum number of issues to include in the summary.")
    args = parser.parse_args()

    if not args.logs_root.exists():
        raise SystemExit(f"Logs root not found: {args.logs_root}")

    log_candidates = list(find_log_candidates(args.logs_root))
    if not log_candidates:
        raise SystemExit(f"No log directories found in {args.logs_root}")

    latest_log = log_candidates[0]
    analysis_file = latest_log / "analysis_results.json"
    if not analysis_file.exists():
        raise SystemExit(f"{analysis_file} does not exist")

    copied_log_dir = copy_logs(latest_log, args.latest_logs_dir)

    with analysis_file.open() as f:
        analysis_data = json.load(f)

    summary = build_sample_summary(analysis_data, latest_log, max_issues=args.max_issues)
    args.sample_file.parent.mkdir(parents=True, exist_ok=True)
    with args.sample_file.open("w") as f:
        json.dump(summary, f, indent=2)

    print(f"Copied {latest_log} -> {copied_log_dir}")
    print(f"Updated summary: {args.sample_file}")


if __name__ == "__main__":
    main()
