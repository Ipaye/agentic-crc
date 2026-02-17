"""
Structured logging utilities for the Agentic Code Review System.
"""
from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any

import structlog

from src.config import get_settings


def setup_logging() -> structlog.BoundLogger:
    """Configure structured logging with appropriate processors."""
    settings = get_settings()

    # Ensure log directory exists
    settings.logging.output_dir.mkdir(parents=True, exist_ok=True)

    # Configure processors based on format
    if settings.logging.format == "json":
        processors = [
            structlog.stdlib.add_log_level,
            structlog.stdlib.PositionalArgumentsFormatter(),
            structlog.processors.TimeStamper(fmt="iso"),
            structlog.processors.StackInfoRenderer(),
            structlog.processors.format_exc_info,
            structlog.processors.UnicodeDecoder(),
            structlog.processors.JSONRenderer()
        ]
    else:
        processors = [
            structlog.stdlib.add_log_level,
            structlog.stdlib.PositionalArgumentsFormatter(),
            structlog.processors.TimeStamper(fmt="iso"),
            structlog.processors.StackInfoRenderer(),
            structlog.processors.format_exc_info,
            structlog.processors.UnicodeDecoder(),
            structlog.dev.ConsoleRenderer(colors=True)
        ]

    structlog.configure(
        processors=processors,
        wrapper_class=structlog.make_filtering_bound_logger(settings.logging.level_value),
        context_class=dict,
        logger_factory=structlog.PrintLoggerFactory(),
        cache_logger_on_first_use=True
    )

    return structlog.get_logger()


def get_logger(name: str = "code_review") -> structlog.BoundLogger:
    """Get a logger instance with the given name."""
    return structlog.get_logger(name)


class AnalysisLogger:
    """
    Specialized logger for analysis results.
    Outputs to both console and files in machine-readable formats.
    """

    def __init__(self, pr_number: int, repo_name: str):
        self.pr_number = pr_number
        self.repo_name = repo_name
        self.settings = get_settings()
        self.session_id = datetime.now().strftime("%Y%m%d_%H%M%S")
        self.log_dir = self.settings.logging.output_dir / f"pr_{pr_number}_{self.session_id}"
        self.log_dir.mkdir(parents=True, exist_ok=True)
        self.logger = get_logger(f"analysis.{pr_number}")
        self._analysis_results = []
        self._comments = []

    def log_rule_triggered(
        self,
        rule_id: str,
        file_path: str,
        line_number: int,
        severity: str,
        message: str,
        confidence: float,
        reasoning: str
    ) -> None:
        """Log a triggered rule with full details."""
        record = {
            "timestamp": datetime.now().isoformat(),
            "pr_number": self.pr_number,
            "repo": self.repo_name,
            "rule_id": rule_id,
            "file_path": file_path,
            "line_number": line_number,
            "severity": severity,
            "message": message,
            "confidence": confidence,
            "reasoning": reasoning
        }
        self._analysis_results.append(record)
        self.logger.info(
            "rule_triggered",
            rule_id=rule_id,
            file=file_path,
            line=line_number,
            severity=severity,
            confidence=confidence
        )

    def log_comment_posted(
        self,
        file_path: str,
        line_number: int,
        comment_body: str,
        comment_id: int
    ) -> None:
        """Log a posted review comment."""
        record = {
            "timestamp": datetime.now().isoformat(),
            "pr_number": self.pr_number,
            "file_path": file_path,
            "line_number": line_number,
            "comment_id": comment_id,
            "body_preview": comment_body[:200] if len(comment_body) > 200 else comment_body
        }
        self._comments.append(record)
        self.logger.info(
            "comment_posted",
            file=file_path,
            line=line_number,
            comment_id=comment_id
        )

    def export_results(self) -> dict[str, Path]:
        """Export all analysis results to files."""
        import csv
        import json

        output_files = {}

        # Export as JSON
        json_path = self.log_dir / "analysis_results.json"
        with open(json_path, "w") as f:
            json.dump({
                "pr_number": self.pr_number,
                "repo": self.repo_name,
                "session_id": self.session_id,
                "results": self._analysis_results,
                "comments": self._comments,
                "summary": self._generate_summary()
            }, f, indent=2)
        output_files["json"] = json_path

        # Export as JSONL
        jsonl_path = self.log_dir / "analysis_results.jsonl"
        with open(jsonl_path, "w") as f:
            for result in self._analysis_results:
                f.write(json.dumps(result) + "\n")
        output_files["jsonl"] = jsonl_path

        # Export as CSV
        if self._analysis_results:
            csv_path = self.log_dir / "analysis_results.csv"
            with open(csv_path, "w", newline="") as f:
                writer = csv.DictWriter(f, fieldnames=self._analysis_results[0].keys())
                writer.writeheader()
                writer.writerows(self._analysis_results)
            output_files["csv"] = csv_path

        self.logger.info(
            "results_exported",
            output_dir=str(self.log_dir),
            files=list(output_files.keys())
        )

        return output_files

    def _generate_summary(self) -> dict[str, Any]:
        """Generate analysis summary statistics."""
        severity_counts = {}
        rule_counts = {}
        file_counts = {}

        for result in self._analysis_results:
            severity = result.get("severity", "unknown")
            severity_counts[severity] = severity_counts.get(severity, 0) + 1

            rule_id = result.get("rule_id", "unknown")
            rule_counts[rule_id] = rule_counts.get(rule_id, 0) + 1

            file_path = result.get("file_path", "unknown")
            file_counts[file_path] = file_counts.get(file_path, 0) + 1

        return {
            "total_issues": len(self._analysis_results),
            "total_comments": len(self._comments),
            "severity_breakdown": severity_counts,
            "rule_breakdown": rule_counts,
            "issues_per_file": file_counts,
            "avg_confidence": (
                sum(r.get("confidence", 0) for r in self._analysis_results) /
                len(self._analysis_results) if self._analysis_results else 0
            )
        }
