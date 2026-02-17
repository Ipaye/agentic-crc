"""
Main code analyzer that orchestrates all analysis components.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from src.analysis.parser import ASTParser, ClassInfo, FunctionInfo, Language
from src.analysis.patterns import PatternMatch, PatternMatcher
from src.analysis.rules import RuleEngine, RuleResult, RuleSeverity
from src.config import get_settings
from src.github.models import FileChange, ReviewComment, ReviewCommentSeverity
from src.utils.logging import get_logger

logger = get_logger("analysis.analyzer")


@dataclass
class AnalysisResult:
    """Complete analysis result for a file."""

    file_path: str
    language: Language
    rule_violations: list[RuleResult] = field(default_factory=list)
    pattern_matches: list[PatternMatch] = field(default_factory=list)
    functions: list[FunctionInfo] = field(default_factory=list)
    classes: list[ClassInfo] = field(default_factory=list)
    complexity_score: int = 0
    maintainability_score: float = 100.0

    @property
    def total_issues(self) -> int:
        """Total number of issues found."""
        return len(self.rule_violations) + len(self.pattern_matches)

    @property
    def error_count(self) -> int:
        """Count of error-level issues."""
        return (
            sum(1 for r in self.rule_violations if r.rule.severity == RuleSeverity.ERROR) +
            sum(1 for p in self.pattern_matches if p.severity == "error")
        )

    @property
    def warning_count(self) -> int:
        """Count of warning-level issues."""
        return (
            sum(1 for r in self.rule_violations if r.rule.severity == RuleSeverity.WARNING) +
            sum(1 for p in self.pattern_matches if p.severity == "warning")
        )


class CodeAnalyzer:
    """
    Main code analyzer that combines AST parsing, rule checking, and pattern matching.
    """

    def __init__(self):
        """Initialize the analyzer with all components."""
        self.parser = ASTParser()
        self.rule_engine = RuleEngine()
        self.pattern_matcher = PatternMatcher()
        self.settings = get_settings()

        logger.info("code_analyzer_initialized")

    def analyze_file(
        self,
        file_change: FileChange,
        focus_on_changes: bool = True
    ) -> AnalysisResult:
        """
        Analyze a single file and return comprehensive results.

        Args:
            file_change: The file change from a PR
            focus_on_changes: Only report issues on changed lines
        """
        # Determine language
        language = self.parser.detect_language(file_change.filename)

        if language == Language.UNKNOWN:
            logger.info(
                "skipping_unknown_language",
                file=file_change.filename
            )
            return AnalysisResult(
                file_path=file_change.filename,
                language=language
            )

        # Use full content if available, otherwise use patch
        code = file_change.content or ""
        if not code and file_change.patch:
            # Extract added lines from patch
            code = self._extract_code_from_patch(file_change.patch)

        if not code:
            return AnalysisResult(
                file_path=file_change.filename,
                language=language
            )

        # Get the set of changed lines if focusing on changes
        changed_lines = set()
        if focus_on_changes and file_change.hunks:
            for hunk in file_change.hunks:
                for i in range(hunk.new_start, hunk.new_start + hunk.new_count):
                    changed_lines.add(i)

        # Perform analysis
        result = AnalysisResult(
            file_path=file_change.filename,
            language=language
        )

        # Extract structural information
        result.functions = self.parser.extract_functions(code, language)
        result.classes = self.parser.extract_classes(code, language)

        # Calculate complexity
        result.complexity_score = self._calculate_file_complexity(code, language, result.functions)

        # Apply rules
        rule_results = self.rule_engine.apply_all_rules(code, file_change.filename, language)

        # Filter to changed lines if needed
        if focus_on_changes and changed_lines:
            rule_results = [r for r in rule_results if r.line_number in changed_lines]

        result.rule_violations = rule_results

        # Find patterns
        patterns = self.pattern_matcher.find_patterns(code, file_change.filename, language)

        if focus_on_changes and changed_lines:
            patterns = [p for p in patterns if p.line_number in changed_lines]

        result.pattern_matches = patterns

        # Add function-level checks
        self._check_functions(result, code, language, changed_lines)

        # Calculate maintainability score
        result.maintainability_score = self._calculate_maintainability(result)

        logger.info(
            "file_analyzed",
            file=file_change.filename,
            language=language.value,
            issues=result.total_issues,
            complexity=result.complexity_score,
            maintainability=result.maintainability_score
        )

        return result

    def _extract_code_from_patch(self, patch: str) -> str:
        """Extract the added code lines from a patch."""
        lines = []
        for line in patch.split("\n"):
            if line.startswith("+") and not line.startswith("+++"):
                lines.append(line[1:])
            elif line.startswith(" "):
                lines.append(line[1:])
        return "\n".join(lines)

    def _calculate_file_complexity(
        self,
        code: str,
        language: Language,
        functions: list[FunctionInfo]
    ) -> int:
        """Calculate overall file complexity."""
        if not functions:
            return self.parser.calculate_complexity(code, language)

        # Sum of function complexities
        return sum(f.complexity for f in functions)

    def _check_functions(
        self,
        result: AnalysisResult,
        code: str,
        language: Language,
        changed_lines: set
    ) -> None:
        """Add function-level rule checks."""
        for func in result.functions:
            # Skip if function wasn't changed
            if changed_lines and not any(
                func.start_line <= line <= func.end_line
                for line in changed_lines
            ):
                continue

            # Check function length
            if func.body_lines > 50:
                result.rule_violations.append(RuleResult(
                    rule=self.rule_engine.rules.get("QUALITY-001"),
                    file_path=result.file_path,
                    line_number=func.start_line,
                    message=f"Function '{func.name}' is {func.body_lines} lines long (recommended: ≤50)",
                    suggestion=f"Consider breaking '{func.name}' into smaller, focused functions",
                    context={"function_name": func.name, "line_count": func.body_lines}
                ))

            # Check complexity
            if func.complexity > 10:
                result.rule_violations.append(RuleResult(
                    rule=self.rule_engine.rules.get("QUALITY-002"),
                    file_path=result.file_path,
                    line_number=func.start_line,
                    message=f"Function '{func.name}' has cyclomatic complexity of {func.complexity} (recommended: ≤10)",
                    suggestion="Consider simplifying conditionals or extracting logic",
                    context={"function_name": func.name, "complexity": func.complexity}
                ))

    def _calculate_maintainability(self, result: AnalysisResult) -> float:
        """
        Calculate maintainability index (0-100).

        Based on:
        - Complexity
        - Issue density
        - Code structure
        """
        score = 100.0

        # Deduct for complexity
        if result.complexity_score > 20:
            score -= min(30, (result.complexity_score - 20) * 2)

        # Deduct for issues
        score -= result.error_count * 10
        score -= result.warning_count * 3

        # Deduct for long functions
        for func in result.functions:
            if func.body_lines > 100:
                score -= 5
            elif func.body_lines > 50:
                score -= 2

        return max(0, min(100, score))

    def analyze_files(
        self,
        files: list[FileChange],
        focus_on_changes: bool = True
    ) -> dict[str, AnalysisResult]:
        """
        Analyze multiple files.
        """
        results = {}

        for file_change in files:
            if not file_change.is_code_file:
                continue

            try:
                result = self.analyze_file(file_change, focus_on_changes)
                results[file_change.filename] = result
            except Exception as e:
                logger.error(
                    "file_analysis_failed",
                    file=file_change.filename,
                    error=str(e)
                )

        return results

    def to_review_comments(
        self,
        results: dict[str, AnalysisResult],
        analysis_logger=None
    ) -> list[ReviewComment]:
        """
        Convert analysis results to review comments.
        """
        comments = []

        for file_path, result in results.items():
            # Convert rule violations
            for violation in result.rule_violations:
                if analysis_logger:
                    analysis_logger.log_rule_triggered(
                        rule_id=violation.rule.id if violation.rule else "RULE-UNKNOWN",
                        file_path=file_path,
                        line_number=violation.line_number,
                        severity=violation.rule.severity.value if violation.rule else "warning",
                        message=violation.message,
                        confidence=getattr(violation, "confidence", 1.0),
                        reasoning=violation.message or ""
                    )

                severity_map = {
                    RuleSeverity.ERROR: ReviewCommentSeverity.ERROR,
                    RuleSeverity.WARNING: ReviewCommentSeverity.WARNING,
                    RuleSeverity.INFO: ReviewCommentSeverity.INFO,
                    RuleSeverity.SUGGESTION: ReviewCommentSeverity.SUGGESTION
                }

                comments.append(ReviewComment(
                    file_path=file_path,
                    line_number=violation.line_number,
                    body=violation.message,
                    severity=severity_map.get(
                        violation.rule.severity,
                        ReviewCommentSeverity.WARNING
                    ) if violation.rule else ReviewCommentSeverity.WARNING,
                    rule_id=violation.rule.id if violation.rule else None,
                    suggestion=violation.suggestion,
                    documentation_url=violation.rule.documentation_url if violation.rule else None
                ))

            # Convert pattern matches
            for pattern in result.pattern_matches:
                if analysis_logger:
                    analysis_logger.log_rule_triggered(
                        rule_id=f"PATTERN-{pattern.pattern_name.upper()}",
                        file_path=file_path,
                        line_number=pattern.line_number,
                        severity=pattern.severity,
                        message=pattern.description,
                        confidence=0.7,
                        reasoning=pattern.description
                    )

                severity_map = {
                    "error": ReviewCommentSeverity.ERROR,
                    "warning": ReviewCommentSeverity.WARNING,
                    "info": ReviewCommentSeverity.INFO
                }

                body = f"{pattern.description}"
                if pattern.fix_suggestion:
                    body += f"\n\n**Suggestion:** {pattern.fix_suggestion}"

                comments.append(ReviewComment(
                    file_path=file_path,
                    line_number=pattern.line_number,
                    body=body,
                    severity=severity_map.get(pattern.severity, ReviewCommentSeverity.WARNING),
                    rule_id=f"PATTERN-{pattern.pattern_name.upper()}"
                ))

        # Group comments by (file_path, rule_id) so the same issue type
        # produces one consolidated comment per file instead of N duplicates.
        grouped = self._group_comments(comments)

        return grouped

    @staticmethod
    def _group_comments(comments: list[ReviewComment]) -> list[ReviewComment]:
        """
        Group comments that share the same file and rule/issue type into a
        single consolidated comment listing all affected lines.

        Comments with different rule_ids or different files stay separate.
        A comment without a rule_id is never grouped (kept as-is).
        """
        from collections import OrderedDict

        ungrouped: list[ReviewComment] = []
        # key → list of comments to merge
        buckets: OrderedDict[tuple[str, str], list[ReviewComment]] = OrderedDict()

        for comment in comments:
            if not comment.rule_id:
                # No rule_id → cannot meaningfully group; keep individual
                ungrouped.append(comment)
                continue

            key = (comment.file_path, comment.rule_id)
            buckets.setdefault(key, []).append(comment)

        merged: list[ReviewComment] = []
        for (file_path, rule_id), group in buckets.items():
            if len(group) == 1:
                # Only one occurrence — no need to merge
                merged.append(group[0])
                continue

            # Sort by line number for a clean listing
            group.sort(key=lambda c: c.line_number)

            # Use the highest severity in the group
            severity_order = {
                ReviewCommentSeverity.ERROR: 3,
                ReviewCommentSeverity.WARNING: 2,
                ReviewCommentSeverity.SUGGESTION: 1,
                ReviewCommentSeverity.INFO: 0,
            }
            worst_severity = max(group, key=lambda c: severity_order.get(c.severity, 0)).severity

            # Build a consolidated body
            lines = [c.line_number for c in group]
            lines_str = ", ".join(f"L{ln}" for ln in lines)
            base_body = group[0].body  # representative message

            consolidated_body = (
                f"{base_body}\n\n"
                f"**Found {len(group)} occurrences** (lines {lines_str})"
            )

            # Collect unique suggestions
            suggestions = list(dict.fromkeys(
                c.suggestion for c in group if c.suggestion
            ))
            suggestion = "\n".join(suggestions) if suggestions else group[0].suggestion

            merged.append(ReviewComment(
                file_path=file_path,
                line_number=group[0].line_number,  # anchor at first occurrence
                body=consolidated_body,
                severity=worst_severity,
                rule_id=rule_id,
                suggestion=suggestion,
                commit_sha=group[0].commit_sha,
            ))

        # Deduplicate the ungrouped list by exact location
        seen: set[tuple[str, int, str | None]] = set()
        unique_ungrouped: list[ReviewComment] = []
        for comment in ungrouped:
            dup_key = (comment.file_path, comment.line_number, comment.body[:80])
            if dup_key not in seen:
                seen.add(dup_key)
                unique_ungrouped.append(comment)

        return merged + unique_ungrouped

    def get_complexity_scores(
        self,
        results: dict[str, AnalysisResult]
    ) -> dict[str, int]:
        """Get complexity scores for all analyzed files."""
        return {
            file_path: result.complexity_score
            for file_path, result in results.items()
        }
