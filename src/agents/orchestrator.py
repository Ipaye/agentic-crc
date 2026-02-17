"""
Review Orchestrator - Coordinates the multi-agent review workflow.

Manages the handoff between:
1. Code Review Agent - Initial analysis
2. Refactoring Agent - Applies fixes
3. Verification Agent - Validates changes
"""
from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any

from ..analysis.analyzer import CodeAnalyzer
from ..github.client import GitHubClient
from ..github.models import FileChange, PullRequestInfo, ReviewComment, ReviewSummary
from ..github.pr_handler import PullRequestHandler
from ..llm.semantic_analyzer import SemanticAnalyzer
from .code_review_agent import CodeReviewAgent, ReviewResult
from .refactoring_agent import CommitResult, RefactoringAgent, RefactoringResult
from .state import AgentState, HandoffDecision
from ..utils.logging import AnalysisLogger


class WorkflowStage(Enum):
    """Stages in the review workflow."""
    INITIALIZED = "initialized"
    REVIEWING = "reviewing"
    REVIEW_COMPLETE = "review_complete"
    REFACTORING = "refactoring"
    REFACTORING_COMPLETE = "refactoring_complete"
    VERIFYING = "verifying"
    VERIFICATION_COMPLETE = "verification_complete"
    COMMITTING = "committing"
    COMPLETED = "completed"
    FAILED = "failed"


@dataclass
class WorkflowContext:
    """Context passed between workflow stages."""
    pr_info: PullRequestInfo
    file_changes: list[FileChange]
    review_result: ReviewResult | None = None
    handoff_decision: HandoffDecision | None = None
    refactoring_results: list[RefactoringResult] = field(default_factory=list)
    commit_result: CommitResult | None = None
    review_summary: ReviewSummary | None = None
    analysis_logger: AnalysisLogger | None = None
    verification_passed: bool = False
    errors: list[str] = field(default_factory=list)


@dataclass
class WorkflowResult:
    """Final result of the review workflow."""
    success: bool
    stage_reached: WorkflowStage
    comments_posted: int = 0
    files_refactored: int = 0
    commit_sha: str | None = None
    summary: str = ""
    duration_seconds: float = 0
    errors: list[str] = field(default_factory=list)


class ReviewOrchestrator:
    """
    Orchestrates the complete code review workflow.

    Workflow:
    1. Code Review Agent analyzes the PR
    2. If delegation criteria met, handoff to Refactoring Agent
    3. Verification Agent validates changes (optional)
    4. Commit changes if verification passes
    """

    def __init__(
        self,
        github_client: GitHubClient,
        code_analyzer: CodeAnalyzer | None = None,
        semantic_analyzer: SemanticAnalyzer | None = None,
        enable_auto_commit: bool = False,
        enable_verification: bool = True
    ):
        self.github_client = github_client
        self.code_analyzer = code_analyzer or CodeAnalyzer()
        self.semantic_analyzer = semantic_analyzer
        self.enable_auto_commit = enable_auto_commit
        self.enable_verification = enable_verification

        # Initialize agents with shared state
        self.master_state = AgentState(session_id="orchestrator")
        self.review_agent = CodeReviewAgent(
            code_analyzer=self.code_analyzer,
            semantic_analyzer=self.semantic_analyzer,
            state=self.master_state
        )
        self.refactoring_agent = RefactoringAgent(
            github_client=self.github_client,
            state=self.master_state
        )
        self.pr_handler = PullRequestHandler(self.github_client)

        self.current_stage = WorkflowStage.INITIALIZED
        self.context: WorkflowContext | None = None

    def run_workflow(
        self,
        pr_info: PullRequestInfo,
        file_changes: list[FileChange]
    ) -> WorkflowResult:
        """
        Execute the complete review workflow.

        Args:
            pr_info: Pull request information
            file_changes: Files changed in the PR

        Returns:
            WorkflowResult with complete workflow status
        """
        start_time = datetime.now()

        self.context = WorkflowContext(
            pr_info=pr_info,
            file_changes=file_changes
        )

        self.master_state.create_checkpoint("workflow_start")

        try:
            # Stage 1: Code Review
            self.context.analysis_logger = AnalysisLogger(
                pr_info.number,
                pr_info.repo_full_name
            )
            self._stage_review()

            # Check if we should proceed to refactoring
            if self._should_refactor():
                # Stage 2: Refactoring
                self._stage_refactor()

                # Stage 3: Verification (if enabled)
                if self.enable_verification:
                    self._stage_verify()
                else:
                    self.context.verification_passed = True

                # Stage 4: Commit (if enabled and verification passed)
                if self.enable_auto_commit and self.context.verification_passed:
                    self._stage_commit()

            self.current_stage = WorkflowStage.COMPLETED

        except Exception as e:
            self.context.errors.append(f"Workflow error: {str(e)}")
            self.current_stage = WorkflowStage.FAILED

        duration = (datetime.now() - start_time).total_seconds()

        return self._build_result(duration)

    def _stage_review(self):
        """Execute the code review stage."""
        self.current_stage = WorkflowStage.REVIEWING

        try:
            review_result = self.review_agent.review(
                self.context.pr_info,
                self.context.file_changes,
                analysis_logger=self.context.analysis_logger
            )
            self.context.review_result = review_result
            self.context.handoff_decision = review_result.handoff_decision

            # Post review comments
            if review_result.comments:
                self._post_comments(review_result.comments)
            else:
                # Still post summary when no line comments
                self._post_comments([])

            self.current_stage = WorkflowStage.REVIEW_COMPLETE

        except Exception as e:
            self.context.errors.append(f"Review stage error: {str(e)}")
            raise

    def _stage_refactor(self):
        """Execute the refactoring stage."""
        self.current_stage = WorkflowStage.REFACTORING

        try:
            if not self.context.handoff_decision:
                return

            results = self.refactoring_agent.process_handoff(
                handoff=self.context.handoff_decision,
                file_changes=self.context.file_changes,
                comments=self.context.review_result.comments if self.context.review_result else []
            )

            self.context.refactoring_results = results
            self.current_stage = WorkflowStage.REFACTORING_COMPLETE

        except Exception as e:
            self.context.errors.append(f"Refactoring stage error: {str(e)}")
            raise

    def _stage_verify(self):
        """Execute the verification stage."""
        self.current_stage = WorkflowStage.VERIFYING

        try:
            # Verify each refactoring result
            all_valid = True

            for result in self.context.refactoring_results:
                if not result.success:
                    all_valid = False
                    continue

                # Verify the refactored content is valid
                if not self._verify_content(result):
                    all_valid = False
                    self.context.errors.append(
                        f"Verification failed for {result.file_path}"
                    )

            self.context.verification_passed = all_valid
            self.current_stage = WorkflowStage.VERIFICATION_COMPLETE

        except Exception as e:
            self.context.errors.append(f"Verification stage error: {str(e)}")
            self.context.verification_passed = False

    def _stage_commit(self):
        """Execute the commit stage."""
        self.current_stage = WorkflowStage.COMMITTING

        try:
            commit_result = self.refactoring_agent.commit_changes(
                repo=self.context.pr_info.repo_full_name,
                branch=self.context.pr_info.head_branch
            )

            self.context.commit_result = commit_result

            if not commit_result.success:
                self.context.errors.append(
                    f"Commit failed: {commit_result.error}"
                )
            else:
                summary = self.refactoring_agent.generate_summary()
                comment_body = (
                    "## 🤖 Refactoring Update\n\n"
                    f"{summary}\n\n"
                    f"**Commit SHA:** `{commit_result.sha}`\n"
                    f"**Files changed:** {len(commit_result.files_changed)}"
                )
                self.github_client.post_issue_comment(
                    self.context.pr_info.repo_full_name,
                    self.context.pr_info.number,
                    comment_body
                )

        except Exception as e:
            self.context.errors.append(f"Commit stage error: {str(e)}")

    def _should_refactor(self) -> bool:
        """Determine if refactoring should proceed."""
        if not self.context.handoff_decision:
            return False

        return self.context.handoff_decision.should_delegate

    def _verify_content(self, result: RefactoringResult) -> bool:
        """Verify refactored content is valid."""
        if not result.refactored_content:
            return True  # No content to verify

        filename = result.file_path.lower()

        # Python syntax check
        if filename.endswith('.py'):
            try:
                compile(result.refactored_content, filename, 'exec')
                return True
            except SyntaxError:
                return False

        # JavaScript/TypeScript - basic checks
        if filename.endswith(('.js', '.ts', '.jsx', '.tsx')):
            # Check for balanced braces
            content = result.refactored_content
            if content.count('{') != content.count('}'):
                return False
            if content.count('(') != content.count(')'):
                return False
            if content.count('[') != content.count(']'):
                return False
            return True

        # For other files, assume valid
        return True

    def _post_comments(self, comments: list[ReviewComment]):
        """Post review comments to GitHub with summary and logging."""
        try:
            summary = self.pr_handler.create_review_summary(
                self.context.pr_info,
                comments
            )
            self.context.review_summary = summary
            self.pr_handler.post_review_comments(
                repo_full_name=self.context.pr_info.repo_full_name,
                pr_number=self.context.pr_info.number,
                comments=comments,
                summary=summary,
                analysis_logger=self.context.analysis_logger
            )
        except Exception as e:
            self.context.errors.append(f"Failed to post comments: {str(e)}")

    def _build_result(self, duration: float) -> WorkflowResult:
        """Build the final workflow result."""
        comments_posted = 0
        if self.context.review_result:
            comments_posted = len(self.context.review_result.comments)

        files_refactored = len([
            r for r in self.context.refactoring_results
            if r.success and r.changes_made
        ])

        commit_sha = None
        if self.context.commit_result and self.context.commit_result.success:
            commit_sha = self.context.commit_result.sha

        summary = self._generate_summary()

        return WorkflowResult(
            success=self.current_stage == WorkflowStage.COMPLETED,
            stage_reached=self.current_stage,
            comments_posted=comments_posted,
            files_refactored=files_refactored,
            commit_sha=commit_sha,
            summary=summary,
            duration_seconds=duration,
            errors=self.context.errors
        )

    def _generate_summary(self) -> str:
        """Generate a summary of the workflow execution."""
        lines = ["# Code Review Workflow Summary", ""]

        # PR Info
        lines.append(f"**Pull Request:** #{self.context.pr_info.number}")
        lines.append(f"**Title:** {self.context.pr_info.title}")
        lines.append(f"**Status:** {self.current_stage.value}")
        lines.append("")

        # Review Results
        if self.context.review_result:
            review = self.context.review_result
            lines.append("## Review Analysis")
            lines.append(f"- Comments: {len(review.comments)}")
            lines.append(f"- Files analyzed: {len(review.files_analyzed)}")
            lines.append("")

            if review.summary:
                lines.append("### Summary")
                lines.append(review.summary)
                lines.append("")

        # Handoff Decision
        if self.context.handoff_decision:
            decision = self.context.handoff_decision
            lines.append("## Handoff Decision")
            lines.append(f"- Delegated to refactoring: {decision.should_delegate}")

            if decision.reasons:
                lines.append("- Reasons:")
                for reason in decision.reasons:
                    lines.append(f"  - {reason}")
            lines.append("")

        # Refactoring Results
        if self.context.refactoring_results:
            lines.append("## Refactoring Results")
            successful = [r for r in self.context.refactoring_results if r.success]
            lines.append(f"- Files processed: {len(self.context.refactoring_results)}")
            lines.append(f"- Successful: {len(successful)}")

            total_changes = sum(len(r.changes_made) for r in successful)
            lines.append(f"- Total changes: {total_changes}")
            lines.append("")

        # Commit Info
        if self.context.commit_result:
            lines.append("## Commit")
            if self.context.commit_result.success:
                lines.append(f"- SHA: {self.context.commit_result.sha}")
                lines.append(f"- Files: {len(self.context.commit_result.files_changed)}")
            else:
                lines.append(f"- Failed: {self.context.commit_result.error}")
            lines.append("")

        # Errors
        if self.context.errors:
            lines.append("## Errors")
            for error in self.context.errors:
                lines.append(f"- {error}")

        return "\n".join(lines)

    def rollback_workflow(self) -> bool:
        """Rollback the entire workflow to the start."""
        return self.master_state.rollback("workflow_start")


class AgentCommunicationProtocol:
    """
    Protocol for agent-to-agent communication.

    Provides structured message passing between agents with:
    - Message validation
    - Priority handling
    - Async communication
    """

    def __init__(self):
        self.message_queue: asyncio.Queue = asyncio.Queue()
        self.handlers: dict[str, callable] = {}

    def register_handler(self, message_type: str, handler: callable):
        """Register a handler for a message type."""
        self.handlers[message_type] = handler

    async def send_message(
        self,
        from_agent: str,
        to_agent: str,
        message_type: str,
        payload: dict[str, Any],
        priority: int = 5
    ):
        """Send a message between agents."""
        message = {
            "from": from_agent,
            "to": to_agent,
            "type": message_type,
            "payload": payload,
            "priority": priority,
            "timestamp": datetime.now().isoformat()
        }

        await self.message_queue.put((priority, message))

    async def process_messages(self):
        """Process queued messages."""
        while not self.message_queue.empty():
            _, message = await self.message_queue.get()

            handler = self.handlers.get(message["type"])
            if handler:
                try:
                    await handler(message)
                except Exception as e:
                    print(f"Error processing message: {e}")

            self.message_queue.task_done()
