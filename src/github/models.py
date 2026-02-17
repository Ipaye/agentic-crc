"""
Data models for GitHub integration.
"""
from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field


class FileChangeType(str, Enum):
    """Type of file change in a PR."""
    ADDED = "added"
    MODIFIED = "modified"
    DELETED = "deleted"
    RENAMED = "renamed"


class ReviewCommentSeverity(str, Enum):
    """Severity levels for review comments."""
    ERROR = "error"
    WARNING = "warning"
    INFO = "info"
    SUGGESTION = "suggestion"


class DiffHunk(BaseModel):
    """Represents a single diff hunk within a file."""

    old_start: int
    old_count: int
    new_start: int
    new_count: int
    content: str
    header: str  # The @@ line

    @property
    def line_range(self) -> tuple[int, int]:
        """Get the line range affected by this hunk."""
        return (self.new_start, self.new_start + self.new_count - 1)


class FileChange(BaseModel):
    """Represents a changed file in a pull request."""

    filename: str
    status: FileChangeType
    additions: int = 0
    deletions: int = 0
    changes: int = 0
    patch: Optional[str] = None
    previous_filename: Optional[str] = None  # For renames
    hunks: list[DiffHunk] = Field(default_factory=list)
    content: Optional[str] = None  # Full file content for context

    @property
    def extension(self) -> str:
        """Get the file extension."""
        if "." in self.filename:
            return self.filename.rsplit(".", 1)[1].lower()
        return ""

    @property
    def is_code_file(self) -> bool:
        """Check if this is a code file that should be reviewed."""
        code_extensions = {
            "py", "js", "ts", "jsx", "tsx", "java", "go", "rs",
            "rb", "php", "c", "cpp", "h", "hpp", "cs", "swift",
            "kt", "scala", "vue", "svelte"
        }
        return self.extension in code_extensions

    def parse_hunks(self) -> None:
        """Parse the patch content into individual hunks."""
        if not self.patch:
            return

        self.hunks = []
        current_hunk = None
        hunk_content_lines = []

        for line in self.patch.split("\n"):
            if line.startswith("@@"):
                # Save previous hunk if exists
                if current_hunk:
                    current_hunk.content = "\n".join(hunk_content_lines)
                    self.hunks.append(current_hunk)
                    hunk_content_lines = []

                # Parse hunk header: @@ -old_start,old_count +new_start,new_count @@
                parts = line.split("@@")
                if len(parts) >= 2:
                    ranges = parts[1].strip().split()
                    old_range = ranges[0][1:].split(",")  # Remove leading -
                    new_range = ranges[1][1:].split(",")  # Remove leading +

                    current_hunk = DiffHunk(
                        old_start=int(old_range[0]),
                        old_count=int(old_range[1]) if len(old_range) > 1 else 1,
                        new_start=int(new_range[0]),
                        new_count=int(new_range[1]) if len(new_range) > 1 else 1,
                        header=line,
                        content=""
                    )
            elif current_hunk is not None:
                hunk_content_lines.append(line)

        # Don't forget the last hunk
        if current_hunk:
            current_hunk.content = "\n".join(hunk_content_lines)
            self.hunks.append(current_hunk)


class CommitInfo(BaseModel):
    """Information about a commit in a pull request."""

    sha: str
    message: str
    author: str
    author_email: Optional[str] = None
    timestamp: datetime
    url: str
    files_changed: int = 0
    additions: int = 0
    deletions: int = 0


class PullRequestInfo(BaseModel):
    """Comprehensive information about a pull request."""

    number: int
    title: str
    body: Optional[str] = None
    state: str
    author: str
    base_branch: str
    head_branch: str
    head_sha: str
    base_sha: str
    repo_full_name: str
    html_url: str
    created_at: datetime
    updated_at: datetime
    mergeable: Optional[bool] = None
    draft: bool = False
    files: list[FileChange] = Field(default_factory=list)
    commits: list[CommitInfo] = Field(default_factory=list)
    labels: list[str] = Field(default_factory=list)

    @property
    def repo_owner(self) -> str:
        """Get the repository owner from the full name."""
        return self.repo_full_name.split("/")[0]

    @property
    def repo_name(self) -> str:
        """Get the repository name from the full name."""
        return self.repo_full_name.split("/")[1]

    @property
    def code_files(self) -> list[FileChange]:
        """Get only the code files that should be reviewed."""
        return [f for f in self.files if f.is_code_file]

    @property
    def total_changes(self) -> int:
        """Get the total number of line changes."""
        return sum(f.additions + f.deletions for f in self.files)


class ReviewComment(BaseModel):
    """A review comment to be posted on a pull request."""

    file_path: str
    line_number: int
    body: str
    severity: ReviewCommentSeverity = ReviewCommentSeverity.WARNING
    rule_id: Optional[str] = None
    suggestion: Optional[str] = None  # Suggested fix code
    commit_sha: Optional[str] = None
    documentation_url: Optional[str] = None

    def format_body(self) -> str:
        """Format the comment body with proper GitHub markdown."""
        severity_emoji = {
            ReviewCommentSeverity.ERROR: "🔴",
            ReviewCommentSeverity.WARNING: "🟡",
            ReviewCommentSeverity.INFO: "🔵",
            ReviewCommentSeverity.SUGGESTION: "💡"
        }

        emoji = severity_emoji.get(self.severity, "")
        formatted = f"{emoji} **{self.severity.value.upper()}**"

        if self.rule_id:
            formatted += f" `[{self.rule_id}]`"

        formatted += f"\n\n{self.body}"

        if self.suggestion:
            formatted += f"\n\n**Suggested fix:**\n```suggestion\n{self.suggestion}\n```"

        if self.documentation_url:
            formatted += f"\n\n**Reference:** {self.documentation_url}"

        return formatted


class ReviewSummary(BaseModel):
    """Summary of the entire review for a pull request."""

    pr_number: int
    total_files_reviewed: int
    total_issues: int
    errors: int = 0
    warnings: int = 0
    suggestions: int = 0
    info: int = 0
    files_with_issues: list[str] = Field(default_factory=list)
    top_rules_triggered: dict = Field(default_factory=dict)
    review_timestamp: datetime = Field(default_factory=datetime.now)

    def format_summary_comment(self) -> str:
        """Format a summary comment for the PR."""
        status_emoji = "✅" if self.errors == 0 else "⚠️" if self.errors < 3 else "❌"

        summary = f"""## {status_emoji} Code Review Summary

| Metric | Count |
|--------|-------|
| Files Reviewed | {self.total_files_reviewed} |
| Total Issues | {self.total_issues} |
| 🔴 Errors | {self.errors} |
| 🟡 Warnings | {self.warnings} |
| 💡 Suggestions | {self.suggestions} |
| 🔵 Info | {self.info} |

"""

        if self.files_with_issues:
            summary += "### Files with Issues\n"
            for file in self.files_with_issues[:10]:  # Top 10
                summary += f"- `{file}`\n"
            if len(self.files_with_issues) > 10:
                summary += f"- ... and {len(self.files_with_issues) - 10} more\n"
            summary += "\n"

        if self.top_rules_triggered:
            summary += "### Most Triggered Rules\n"
            for rule_id, count in sorted(
                self.top_rules_triggered.items(),
                key=lambda x: x[1],
                reverse=True
            )[:5]:
                summary += f"- `{rule_id}`: {count} occurrences\n"

        summary += f"\n---\n*Review completed at {self.review_timestamp.isoformat()}*"

        return summary
