"""
Pull Request handler for coordinating the review process.
"""
from __future__ import annotations

from src.config import get_settings
from src.github.client import GitHubClient
from src.github.models import PullRequestInfo, ReviewComment, ReviewCommentSeverity, ReviewSummary
from src.utils.logging import AnalysisLogger, get_logger

logger = get_logger("github.pr_handler")


class PullRequestHandler:
    """
    Handles the complete pull request review workflow.
    """

    def __init__(self, github_client: GitHubClient | None = None):
        """Initialize the PR handler."""
        self.github = github_client or GitHubClient()
        self.settings = get_settings()

    def fetch_pr_for_review(
        self,
        repo_full_name: str,
        pr_number: int
    ) -> PullRequestInfo:
        """
        Fetch a pull request with all necessary data for review.
        """
        logger.info(
            "fetching_pr_for_review",
            repo=repo_full_name,
            pr_number=pr_number
        )

        pr_info = self.github.get_pull_request(repo_full_name, pr_number)

        # Log summary
        logger.info(
            "pr_fetch_complete",
            pr_number=pr_number,
            title=pr_info.title,
            author=pr_info.author,
            files_count=len(pr_info.files),
            code_files_count=len(pr_info.code_files),
            total_changes=pr_info.total_changes
        )

        return pr_info

    def should_skip_review(self, pr_info: PullRequestInfo) -> tuple[bool, str]:
        """
        Determine if a PR should be skipped from review.
        Returns (should_skip, reason).
        """
        # Skip draft PRs
        if pr_info.draft:
            return True, "PR is a draft"

        # Skip if labeled to skip
        skip_labels = {"skip-review", "wip", "work-in-progress", "no-review"}
        if any(label.lower() in skip_labels for label in pr_info.labels):
            return True, "PR has skip-review label"

        # Skip if no code files changed
        if not pr_info.code_files:
            return True, "No code files changed"

        # Skip if too many changes (might need manual review)
        if pr_info.total_changes > self.settings.analysis.max_diff_lines:
            return True, f"Too many changes ({pr_info.total_changes} > {self.settings.analysis.max_diff_lines})"

        return False, ""

    def post_review_comments(
        self,
        repo_full_name: str,
        pr_number: int,
        comments: list[ReviewComment],
        summary: ReviewSummary,
        analysis_logger: AnalysisLogger | None = None
    ) -> dict:
        """
        Post all review comments to the pull request.
        Groups similar comments before posting to avoid spamming the PR.
        Returns posting statistics.
        """
        analysis_logger = analysis_logger or AnalysisLogger(pr_number, repo_full_name)

        # Group similar comments so the PR isn't flooded with duplicates
        comments = self._group_comments(comments)

        # Determine review event based on severity
        if summary.errors > 0:
            event = "REQUEST_CHANGES"
        elif summary.warnings > 3:
            event = "COMMENT"
        else:
            event = "COMMENT"

        posted_count = 0
        failed_count = 0

        try:
            # Try to post as a single review (more efficient)
            if comments:
                review_id = self.github.post_review(
                    repo_full_name,
                    pr_number,
                    comments,
                    summary.format_summary_comment(),
                    event
                )
                posted_count = len(comments)

                for comment in comments:
                    analysis_logger.log_comment_posted(
                        comment.file_path,
                        comment.line_number,
                        comment.body,
                        review_id
                    )
            else:
                # Just post summary if no line comments
                self.github.post_issue_comment(
                    repo_full_name,
                    pr_number,
                    summary.format_summary_comment()
                )

        except Exception as e:
            logger.error(
                "failed_to_post_review",
                error=str(e),
                falling_back_to_individual=True
            )

            # Fall back to individual comments
            for comment in comments:
                try:
                    comment_id = self.github.post_review_comment(
                        repo_full_name,
                        pr_number,
                        comment
                    )
                    posted_count += 1
                    analysis_logger.log_comment_posted(
                        comment.file_path,
                        comment.line_number,
                        comment.body,
                        comment_id
                    )
                except Exception as ce:
                    logger.error(
                        "failed_to_post_comment",
                        file=comment.file_path,
                        line=comment.line_number,
                        error=str(ce)
                    )
                    failed_count += 1

            # Post summary separately
            try:
                self.github.post_issue_comment(
                    repo_full_name,
                    pr_number,
                    summary.format_summary_comment()
                )
            except Exception as se:
                logger.error("failed_to_post_summary", error=str(se))

        # Export results
        analysis_logger.export_results()

        return {
            "posted": posted_count,
            "failed": failed_count,
            "total": len(comments)
        }

    def create_review_summary(
        self,
        pr_info: PullRequestInfo,
        comments: list[ReviewComment]
    ) -> ReviewSummary:
        """
        Create a summary of the review from the comments.
        """
        summary = ReviewSummary(
            pr_number=pr_info.number,
            total_files_reviewed=len(pr_info.code_files),
            total_issues=len(comments)
        )

        # Count severities
        for comment in comments:
            if comment.severity == ReviewCommentSeverity.ERROR:
                summary.errors += 1
            elif comment.severity == ReviewCommentSeverity.WARNING:
                summary.warnings += 1
            elif comment.severity == ReviewCommentSeverity.SUGGESTION:
                summary.suggestions += 1
            else:
                summary.info += 1

            # Track files with issues
            if comment.file_path not in summary.files_with_issues:
                summary.files_with_issues.append(comment.file_path)

            # Track rules
            if comment.rule_id:
                summary.top_rules_triggered[comment.rule_id] = (
                    summary.top_rules_triggered.get(comment.rule_id, 0) + 1
                )

        return summary

    def check_delegation_criteria(
        self,
        pr_info: PullRequestInfo,
        comments: list[ReviewComment],
        complexity_scores: dict[str, int]
    ) -> dict:
        """
        Check if the PR should be delegated to the refactoring agent.
        Returns delegation decision and reasons.
        """
        settings = self.settings.agent
        reasons = []
        should_delegate = False

        # Check complexity
        high_complexity_files = [
            f for f, score in complexity_scores.items()
            if score > settings.complexity_threshold
        ]
        if high_complexity_files:
            reasons.append(f"High complexity: {', '.join(high_complexity_files)}")
            should_delegate = True

        # Check violations per file
        file_violations = {}
        for comment in comments:
            file_violations[comment.file_path] = file_violations.get(comment.file_path, 0) + 1

        high_violation_files = [
            f for f, count in file_violations.items()
            if count >= settings.violation_threshold
        ]
        if high_violation_files:
            reasons.append(f"Multiple violations: {', '.join(high_violation_files)}")
            should_delegate = True

        # Check for specific refactorable patterns
        refactorable_rules = {
            "STYLE-001",  # Variable naming
            "QUALITY-001",  # Long methods
            "QUALITY-002",  # Complex conditionals
            "QUALITY-003",  # Duplicate code
        }

        refactorable_comments = [
            c for c in comments
            if c.rule_id in refactorable_rules and c.suggestion
        ]
        if len(refactorable_comments) >= 3:
            reasons.append(f"{len(refactorable_comments)} auto-fixable issues found")
            should_delegate = True

        return {
            "should_delegate": should_delegate,
            "reasons": reasons,
            "high_complexity_files": high_complexity_files,
            "high_violation_files": high_violation_files,
            "refactorable_comments": refactorable_comments
        }

    @staticmethod
    def _group_comments(comments: list[ReviewComment]) -> list[ReviewComment]:
        """
        Group comments that share the same file and rule/issue type into a
        single consolidated comment, listing all affected lines.

        This prevents flooding a PR with many identical comments.
        """
        from collections import OrderedDict

        ungrouped: list[ReviewComment] = []
        buckets: OrderedDict[tuple[str, str], list[ReviewComment]] = OrderedDict()

        for comment in comments:
            if not comment.rule_id:
                ungrouped.append(comment)
                continue
            key = (comment.file_path, comment.rule_id)
            buckets.setdefault(key, []).append(comment)

        merged: list[ReviewComment] = []
        for (file_path, rule_id), group in buckets.items():
            if len(group) == 1:
                merged.append(group[0])
                continue

            group.sort(key=lambda c: c.line_number)

            severity_order = {
                ReviewCommentSeverity.ERROR: 3,
                ReviewCommentSeverity.WARNING: 2,
                ReviewCommentSeverity.SUGGESTION: 1,
                ReviewCommentSeverity.INFO: 0,
            }
            worst = max(group, key=lambda c: severity_order.get(c.severity, 0)).severity

            lines = [c.line_number for c in group]
            lines_str = ", ".join(f"L{ln}" for ln in lines)
            base_body = group[0].body

            body = (
                f"{base_body}\n\n"
                f"**Found {len(group)} occurrences** (lines {lines_str})"
            )

            suggestions = list(dict.fromkeys(
                c.suggestion for c in group if c.suggestion
            ))

            merged.append(ReviewComment(
                file_path=file_path,
                line_number=group[0].line_number,
                body=body,
                severity=worst,
                rule_id=rule_id,
                suggestion="\n".join(suggestions) if suggestions else group[0].suggestion,
                commit_sha=group[0].commit_sha,
            ))

        # Deduplicate ungrouped by body prefix + location
        seen: set[tuple[str, int, str]] = set()
        unique: list[ReviewComment] = []
        for c in ungrouped:
            dup_key = (c.file_path, c.line_number, c.body[:80])
            if dup_key not in seen:
                seen.add(dup_key)
                unique.append(c)

        return merged + unique
