"""
Code Review Agent - Main agent for analyzing pull requests.
"""
from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from typing import Any

import os

# CrewAI is optional - only available on Python 3.10+
try:
    from crewai import Agent, Crew, Task
    from langchain_ollama import OllamaLLM
    CREWAI_AVAILABLE = True
except ImportError:
    CREWAI_AVAILABLE = False
    Agent = None
    Task = None
    Crew = None
    OllamaLLM = None

from src.agents.state import AgentState, HandoffDecision, HandoffReason
from src.analysis.analyzer import AnalysisResult, CodeAnalyzer
from src.config import get_settings
from src.github.models import FileChange, PullRequestInfo, ReviewComment
from src.llm.semantic_analyzer import SemanticAnalyzer
from src.utils.logging import AnalysisLogger, get_logger

logger = get_logger("agents.code_review")


@dataclass
class ReviewResult:
    """Result of a code review."""
    comments: list[ReviewComment] = field(default_factory=list)
    files_analyzed: list[str] = field(default_factory=list)
    summary: str = ""
    handoff_decision: HandoffDecision | None = None
    metrics: dict[str, Any] = field(default_factory=dict)


class CodeReviewAgent:
    """
    Agent responsible for code review and analysis.

    This agent:
    1. Analyzes code changes using static analysis
    2. Applies coding standards rules
    3. Uses LLM for semantic analysis
    4. Generates review comments
    5. Decides if refactoring delegation is needed
    """

    def __init__(
        self,
        code_analyzer: CodeAnalyzer | None = None,
        semantic_analyzer: SemanticAnalyzer | None = None,
        state: AgentState | None = None
    ):
        """Initialize the code review agent."""
        self.settings = get_settings()
        self.analyzer = code_analyzer or CodeAnalyzer()
        if semantic_analyzer is not None:
            self.semantic_analyzer = semantic_analyzer
        elif self.settings.ollama.enabled:
            self.semantic_analyzer = SemanticAnalyzer()
        else:
            self.semantic_analyzer = None
        self.state = state

        # Initialize CrewAI components
        self._init_crewai()

        logger.info("code_review_agent_initialized")

    def _init_crewai(self) -> None:
        """Initialize CrewAI agent and tools."""
        if not CREWAI_AVAILABLE:
            logger.info("crewai_not_available", reason="crewai package not installed (pip install -e '.[crewai]')")
            self._crewai_available = False
            self.agent = None
            self.llm = None
            return

        try:
            # Prevent CrewAI from requiring OPENAI_API_KEY when using Ollama
            if not os.environ.get("OPENAI_API_KEY"):
                os.environ["OPENAI_API_KEY"] = "not-needed-using-ollama"

            self.llm = OllamaLLM(
                model=self.settings.ollama.model,
                base_url=self.settings.ollama.host
            )

            self.agent = Agent(
                role="Senior Code Reviewer",
                goal="Thoroughly review code changes and identify issues, improvements, and best practices",
                backstory="""You are an experienced senior software engineer with expertise in
                multiple programming languages and frameworks. You have a keen eye for code quality,
                security vulnerabilities, and performance issues. You provide constructive feedback
                that helps developers improve their code while maintaining a positive tone.""",
                verbose=True,
                allow_delegation=True,
                llm=self.llm
            )

            self._crewai_available = True
            logger.info("crewai_agent_initialized")

        except Exception as e:
            logger.warning(
                "crewai_initialization_failed",
                error=str(e),
                fallback="standard_analysis"
            )
            self._crewai_available = False
            self.agent = None

    def review(
        self,
        pr_info: PullRequestInfo,
        files: list[FileChange],
        analysis_logger: AnalysisLogger | None = None
    ) -> ReviewResult:
        """
        Perform a complete code review on a pull request.

        Args:
            pr_info: Pull request information
            files: List of file changes in the PR

        Returns:
            ReviewResult with comments, metrics, and handoff decision
        """
        code_files = pr_info.code_files
        logger.info(
            "starting_code_review",
            pr_number=pr_info.number,
            files_count=len(code_files)
        )

        comments: list[ReviewComment] = []
        files_analyzed: list[str] = [f.filename for f in code_files]
        metrics = {
            "total_files": len(code_files),
            "total_issues": 0,
            "errors": 0,
            "warnings": 0,
            "suggestions": 0
        }

        # Step 1: Static analysis with rules
        static_results = self._run_static_analysis(code_files, True)

        # Convert to comments
        static_comments = self.analyzer.to_review_comments(
            static_results,
            analysis_logger=analysis_logger
        )
        comments.extend(static_comments)

        # Get complexity scores
        complexity_scores = self.analyzer.get_complexity_scores(static_results)

        # Step 2: Semantic analysis with LLM (if available)
        if self.semantic_analyzer and self.semantic_analyzer.is_available:
            semantic_comments = self._run_semantic_analysis(
                code_files,
                True
            )
            comments.extend(semantic_comments)

        # Update metrics
        for comment in comments:
            metrics["total_issues"] += 1
            if comment.severity.value == "error":
                metrics["errors"] += 1
            elif comment.severity.value == "warning":
                metrics["warnings"] += 1
            else:
                metrics["suggestions"] += 1

        # Step 3: Determine if delegation is needed
        handoff_decision = self._evaluate_handoff(
            comments,
            complexity_scores,
            static_results
        )

        # Generate summary
        summary = self._generate_summary(pr_info, comments, metrics)

        logger.info(
            "code_review_completed",
            pr_number=pr_info.number,
            total_issues=metrics["total_issues"],
            should_delegate=handoff_decision.should_handoff
        )

        return ReviewResult(
            comments=comments,
            files_analyzed=files_analyzed,
            summary=summary,
            handoff_decision=handoff_decision,
            metrics=metrics
        )

    def _run_static_analysis(
        self,
        files: list[FileChange],
        focus_on_changes: bool
    ) -> dict[str, AnalysisResult]:
        """Run static code analysis on files."""
        logger.debug("running_static_analysis", files_count=len(files))
        return self.analyzer.analyze_files(files, focus_on_changes)

    def _run_semantic_analysis(
        self,
        files: list[FileChange],
        focus_on_changes: bool
    ) -> list[ReviewComment]:
        """Run LLM-based semantic analysis on files."""
        comments = []

        # Limit files for semantic analysis to avoid timeouts
        max_files_for_semantic = 5
        priority_files = sorted(
            files,
            key=lambda f: f.changes,
            reverse=True
        )[:max_files_for_semantic]

        for file in priority_files:
            try:
                if focus_on_changes and file.patch:
                    result = self.semantic_analyzer.analyze_diff_sync(file)
                else:
                    result = self.semantic_analyzer.analyze_file_sync(file)

                file_comments = self.semantic_analyzer.to_review_comments(result)
                comments.extend(file_comments)

            except Exception as e:
                logger.warning(
                    "semantic_analysis_file_failed",
                    file=file.filename,
                    error=str(e)
                )

        return comments

    def _evaluate_handoff(
        self,
        comments: list[ReviewComment],
        complexity_scores: dict[str, int],
        analysis_results: dict[str, AnalysisResult]
    ) -> HandoffDecision:
        """
        Evaluate whether to hand off to the refactoring agent.

        Criteria:
        1. High complexity scores (> threshold)
        2. Multiple violations in same file (> threshold)
        3. Auto-fixable issues present
        4. Security-critical issues
        """
        settings = self.settings.agent
        reasons = []
        priority_files = []
        context = {}

        # Check complexity threshold
        high_complexity_files = [
            f for f, score in complexity_scores.items()
            if score > settings.complexity_threshold
        ]
        if high_complexity_files:
            reasons.append(HandoffReason.HIGH_COMPLEXITY)
            priority_files.extend(high_complexity_files)
            context["high_complexity_files"] = high_complexity_files

        # Check violations per file
        file_violations = {}
        for comment in comments:
            file_violations[comment.file_path] = file_violations.get(comment.file_path, 0) + 1

        high_violation_files = [
            f for f, count in file_violations.items()
            if count >= settings.violation_threshold
        ]
        if high_violation_files:
            reasons.append(HandoffReason.MULTIPLE_VIOLATIONS)
            for f in high_violation_files:
                if f not in priority_files:
                    priority_files.append(f)
            context["high_violation_files"] = high_violation_files

        # Check for auto-fixable issues
        auto_fixable_rules = {"STYLE-001", "STYLE-002", "STYLE-003", "BEST-005"}
        auto_fixable_count = sum(
            1 for c in comments
            if c.rule_id in auto_fixable_rules and c.suggestion
        )
        if auto_fixable_count >= 3:
            reasons.append(HandoffReason.AUTO_FIXABLE)
            context["auto_fixable_count"] = auto_fixable_count

        # Check for security issues
        security_comments = [
            c for c in comments
            if c.rule_id and c.rule_id.startswith("SECURITY")
            and c.severity.value == "error"
        ]
        if security_comments:
            reasons.append(HandoffReason.SECURITY_CRITICAL)
            context["security_issues"] = len(security_comments)

        should_handoff = len(reasons) > 0

        return HandoffDecision(
            should_handoff=should_handoff,
            target_agent="refactoring" if should_handoff else None,
            reasons=reasons,
            priority_files=priority_files,
            context=context
        )

    def _generate_summary(
        self,
        pr_info: PullRequestInfo,
        comments: list[ReviewComment],
        metrics: dict[str, Any]
    ) -> str:
        """Generate a summary of the review."""
        lines = [
            f"## Code Review for PR #{pr_info.number}",
            "",
            f"**Title:** {pr_info.title}",
            f"**Author:** {pr_info.author}",
            f"**Files analyzed:** {metrics['total_files']}",
            "",
            "### Issues Found",
            f"- Total: {metrics['total_issues']}",
            f"- Errors: {metrics['errors']}",
            f"- Warnings: {metrics['warnings']}",
            f"- Suggestions: {metrics['suggestions']}",
        ]

        if comments:
            lines.append("")
            lines.append("### Top Issues")
            # Show top 5 most important issues
            top_comments = sorted(
                comments,
                key=lambda c: 0 if c.severity.value == "error" else (1 if c.severity.value == "warning" else 2)
            )[:5]
            for comment in top_comments:
                lines.append(f"- [{comment.severity.value.upper()}] {comment.file_path}: {comment.body[:80]}...")

        return "\n".join(lines)

    def review_sync(
        self,
        pr_info: PullRequestInfo,
        focus_on_changes: bool = True
    ) -> dict[str, Any]:
        """Synchronous version of review."""
        return asyncio.run(self.review(pr_info, focus_on_changes))

    def create_crew_task(
        self,
        pr_info: PullRequestInfo
    ) -> Task | None:
        """Create a CrewAI task for the review."""
        if not self._crewai_available:
            return None

        # Prepare file summary
        files_summary = "\n".join([
            f"- {f.filename} ({f.additions}+ {f.deletions}-)"
            for f in pr_info.code_files[:10]
        ])

        task_description = f"""
        Review the pull request #{pr_info.number}: {pr_info.title}

        Author: {pr_info.author}
        Changes: {pr_info.total_changes} lines across {len(pr_info.code_files)} files

        Files changed:
        {files_summary}

        Please provide:
        1. A summary of what this PR does
        2. Any issues or concerns identified
        3. Suggestions for improvement
        4. Whether the changes are ready to merge
        """

        return Task(
            description=task_description,
            expected_output="A comprehensive code review with actionable feedback",
            agent=self.agent
        )
