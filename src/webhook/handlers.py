"""
Webhook event handlers for GitHub events.
"""
from __future__ import annotations

from typing import Any
import asyncio
from dataclasses import asdict

from src.github.client import GitHubClient
from src.github.pr_handler import PullRequestHandler
from src.utils.logging import get_logger
from src.analysis.analyzer import CodeAnalyzer
from src.llm.semantic_analyzer import SemanticAnalyzer
from src.config import get_settings

logger = get_logger("webhook.handlers")


class WebhookEventHandler:
    """
    Handles incoming GitHub webhook events and triggers appropriate actions.
    """

    def __init__(self):
        """Initialize the event handler."""
        self._github_client = None
        self._pr_handler = None
        self._review_orchestrator = None

    @property
    def github_client(self) -> GitHubClient:
        """Lazy initialization of GitHub client."""
        if self._github_client is None:
            self._github_client = GitHubClient()
        return self._github_client

    @property
    def pr_handler(self) -> PullRequestHandler:
        """Lazy initialization of PR handler."""
        if self._pr_handler is None:
            self._pr_handler = PullRequestHandler(self.github_client)
        return self._pr_handler

    @property
    def review_orchestrator(self):
        """Lazy initialization of review orchestrator."""
        if self._review_orchestrator is None:
            # Import here to avoid circular imports
            from src.agents.orchestrator import ReviewOrchestrator
            settings = get_settings()
            self._review_orchestrator = ReviewOrchestrator(
                github_client=self.github_client,
                code_analyzer=CodeAnalyzer(),
                semantic_analyzer=SemanticAnalyzer() if settings.ollama.enabled else None
            )
        return self._review_orchestrator

    async def handle_pull_request_event(
        self,
        payload: dict[str, Any],
        delivery_id: str
    ) -> None:
        """
        Handle a pull_request webhook event.

        Triggered when a PR is opened, updated, or reopened.
        """
        action = payload.get("action")
        pr_data = payload.get("pull_request", {})
        repo_data = payload.get("repository", {})

        pr_number = pr_data.get("number")
        repo_full_name = repo_data.get("full_name")

        logger.info(
            "handling_pull_request_event",
            action=action,
            pr_number=pr_number,
            repo=repo_full_name,
            delivery_id=delivery_id
        )

        try:
            # Fetch full PR details
            pr_info = self.pr_handler.fetch_pr_for_review(repo_full_name, pr_number)

            # Check if we should skip
            should_skip, reason = self.pr_handler.should_skip_review(pr_info)
            if should_skip:
                logger.info(
                    "skipping_review",
                    pr_number=pr_number,
                    reason=reason
                )
                return

            # Run the review through the orchestrator
            result = await self._run_review(pr_info)

            logger.info(
                "review_completed",
                pr_number=pr_number,
                issues_found=result.get("comments_posted", 0),
                delivery_id=delivery_id
            )

        except Exception as e:
            logger.error(
                "failed_to_handle_pr_event",
                pr_number=pr_number,
                error=str(e),
                delivery_id=delivery_id,
                exc_info=True
            )

            # Post error comment to PR
            try:
                self.github_client.post_issue_comment(
                    repo_full_name,
                    pr_number,
                    f"⚠️ **Code Review Error**\n\n"
                    f"An error occurred while reviewing this PR:\n"
                    f"```\n{str(e)}\n```\n\n"
                    f"Please check the logs for more details. Delivery ID: `{delivery_id}`"
                )
            except Exception:
                pass

    async def handle_review_comment_event(
        self,
        payload: dict[str, Any],
        delivery_id: str
    ) -> None:
        """
        Handle a pull_request_review_comment webhook event.

        Can be used to trigger re-review if someone comments with a trigger phrase.
        """
        action = payload.get("action")
        comment = payload.get("comment", {})
        pr_data = payload.get("pull_request", {})
        repo_data = payload.get("repository", {})

        # Check for re-review trigger
        comment_body = comment.get("body", "").lower()
        trigger_phrases = ["@code-review", "/review", "/re-review"]

        if action == "created" and any(phrase in comment_body for phrase in trigger_phrases):
            pr_number = pr_data.get("number")
            repo_full_name = repo_data.get("full_name")

            logger.info(
                "re_review_triggered",
                pr_number=pr_number,
                repo=repo_full_name,
                delivery_id=delivery_id
            )

            await self.trigger_manual_review(repo_full_name, pr_number)

    async def trigger_manual_review(
        self,
        repo_full_name: str,
        pr_number: int
    ) -> dict[str, Any]:
        """
        Manually trigger a review for a specific PR.
        """
        logger.info(
            "manual_review_starting",
            repo=repo_full_name,
            pr_number=pr_number
        )

        try:
            pr_info = self.pr_handler.fetch_pr_for_review(repo_full_name, pr_number)

            # Check if we should skip
            should_skip, reason = self.pr_handler.should_skip_review(pr_info)
            if should_skip:
                logger.info(
                    "skipping_manual_review",
                    pr_number=pr_number,
                    reason=reason
                )
                return {"status": "skipped", "reason": reason}

            result = await self._run_review(pr_info)
            return result

        except Exception as e:
            logger.error(
                "manual_review_failed",
                repo=repo_full_name,
                pr_number=pr_number,
                error=str(e)
            )
            raise

    async def _run_review(self, pr_info) -> dict[str, Any]:
        """
        Run the full review process through the orchestrator.
        """
        # Run orchestrator (handles agent coordination)
        result = await asyncio.to_thread(
            self.review_orchestrator.run_workflow,
            pr_info,
            pr_info.files
        )

        return asdict(result)
