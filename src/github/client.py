"""
GitHub API client with rate limiting and error handling.
"""
from __future__ import annotations

import time
from datetime import datetime
from typing import Any

from github.PullRequest import PullRequest
from github.Repository import Repository
from github import InputGitTreeElement
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential

from github import Github, GithubException, RateLimitExceededException
from src.config import get_settings
from src.github.models import CommitInfo, FileChange, FileChangeType, PullRequestInfo, ReviewComment
from src.utils.logging import get_logger

logger = get_logger("github.client")


class GitHubClient:
    """
    GitHub API client with automatic rate limiting and retry logic.
    """

    def __init__(self, token: str | None = None):
        """Initialize the GitHub client."""
        settings = get_settings()
        self.token = token or settings.github.token
        self.rate_limit_buffer = settings.github.rate_limit_buffer

        if not self.token:
            raise ValueError("GitHub token is required. Set GITHUB_TOKEN environment variable.")

        self._client = Github(self.token)
        self._check_rate_limit()
        # Try to get user info - may fail with installation tokens (GitHub Actions)
        try:
            user_login = self._client.get_user().login
            logger.info("github_client_initialized", user=user_login)
        except Exception:
            # Installation tokens can't access /user endpoint
            logger.info("github_client_initialized", user="github-actions[bot]")

    def _check_rate_limit(self) -> None:
        """Check and log current rate limit status."""
        rate_limit = self._client.get_rate_limit()
        # Handle different PyGithub versions - try 'core' first, then 'rate'
        if hasattr(rate_limit, 'core'):
            core = rate_limit.core
        elif hasattr(rate_limit, 'rate'):
            core = rate_limit.rate
        else:
            # Fallback: skip rate limit check if structure is unknown
            logger.warning("rate_limit_check_skipped", reason="unknown_api_structure")
            return

        logger.debug(
            "rate_limit_status",
            remaining=core.remaining,
            limit=core.limit,
            reset_at=core.reset.isoformat()
        )

        if core.remaining < self.rate_limit_buffer:
            wait_time = (core.reset - datetime.utcnow()).total_seconds() + 5
            if wait_time > 0:
                logger.warning(
                    "rate_limit_approaching",
                    remaining=core.remaining,
                    waiting_seconds=wait_time
                )
                time.sleep(wait_time)

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=4, max=60),
        retry=retry_if_exception_type(RateLimitExceededException)
    )
    def _api_call(self, func: callable, *args, **kwargs) -> Any:
        """Execute an API call with rate limit handling."""
        self._check_rate_limit()
        try:
            return func(*args, **kwargs)
        except RateLimitExceededException:
            logger.warning("rate_limit_exceeded", retrying=True)
            raise
        except GithubException as e:
            logger.error("github_api_error", status=e.status, message=str(e))
            raise

    def get_repository(self, repo_full_name: str) -> Repository:
        """Get a repository by its full name (owner/repo)."""
        return self._api_call(self._client.get_repo, repo_full_name)

    def get_pull_request(self, repo_full_name: str, pr_number: int) -> PullRequestInfo:
        """
        Get comprehensive pull request information including files and commits.
        """
        repo = self.get_repository(repo_full_name)
        pr = self._api_call(repo.get_pull, pr_number)

        # Build PullRequestInfo
        pr_info = PullRequestInfo(
            number=pr.number,
            title=pr.title,
            body=pr.body,
            state=pr.state,
            author=pr.user.login,
            base_branch=pr.base.ref,
            head_branch=pr.head.ref,
            head_sha=pr.head.sha,
            base_sha=pr.base.sha,
            repo_full_name=repo_full_name,
            html_url=pr.html_url,
            created_at=pr.created_at,
            updated_at=pr.updated_at,
            mergeable=pr.mergeable,
            draft=pr.draft,
            labels=[label.name for label in pr.labels]
        )

        # Get changed files
        pr_info.files = self._get_pr_files(pr, repo)

        # Get commits
        pr_info.commits = self._get_pr_commits(pr)

        logger.info(
            "pull_request_fetched",
            pr_number=pr_number,
            files_count=len(pr_info.files),
            commits_count=len(pr_info.commits)
        )

        return pr_info

    def _get_pr_files(self, pr: PullRequest, repo: Repository) -> list[FileChange]:
        """Get all changed files in a pull request with their diffs."""
        files = []
        settings = get_settings()

        for idx, file in enumerate(self._api_call(pr.get_files)):
            if idx >= settings.analysis.max_files_per_pr:
                logger.warning(
                    "max_files_reached",
                    limit=settings.analysis.max_files_per_pr
                )
                break

            status_map = {
                "added": FileChangeType.ADDED,
                "modified": FileChangeType.MODIFIED,
                "removed": FileChangeType.DELETED,
                "renamed": FileChangeType.RENAMED
            }

            file_change = FileChange(
                filename=file.filename,
                status=status_map.get(file.status, FileChangeType.MODIFIED),
                additions=file.additions,
                deletions=file.deletions,
                changes=file.changes,
                patch=file.patch,
                previous_filename=file.previous_filename
            )

            # Parse diff hunks
            file_change.parse_hunks()

            # Get full file content for context (if not deleted)
            if file_change.status != FileChangeType.DELETED and file_change.is_code_file:
                try:
                    content_file = self._api_call(
                        repo.get_contents,
                        file.filename,
                        ref=pr.head.sha
                    )
                    if hasattr(content_file, 'decoded_content'):
                        file_change.content = content_file.decoded_content.decode('utf-8')
                except GithubException as e:
                    logger.warning(
                        "failed_to_fetch_content",
                        file=file.filename,
                        error=str(e)
                    )

            files.append(file_change)

        return files

    def _get_pr_commits(self, pr: PullRequest) -> list[CommitInfo]:
        """Get all commits in a pull request."""
        commits = []

        for commit in self._api_call(pr.get_commits):
            # commit.files may be PaginatedList - convert to list for count
            files_changed = 0
            if commit.files:
                try:
                    files_changed = len(list(commit.files))
                except (TypeError, AttributeError):
                    files_changed = commit.files.totalCount if hasattr(commit.files, 'totalCount') else 0

            commit_info = CommitInfo(
                sha=commit.sha,
                message=commit.commit.message,
                author=commit.commit.author.name,
                author_email=commit.commit.author.email,
                timestamp=commit.commit.author.date,
                url=commit.html_url,
                files_changed=files_changed,
                additions=commit.stats.additions if commit.stats else 0,
                deletions=commit.stats.deletions if commit.stats else 0
            )
            commits.append(commit_info)

        return commits

    def post_review_comment(
        self,
        repo_full_name: str,
        pr_number: int,
        comment: ReviewComment
    ) -> int:
        """
        Post a review comment on a specific line in a pull request.
        Returns the comment ID.
        """
        repo = self.get_repository(repo_full_name)
        pr = self._api_call(repo.get_pull, pr_number)

        # Use the commit SHA if provided, otherwise use head SHA
        commit_sha = comment.commit_sha or pr.head.sha

        try:
            review_comment = self._api_call(
                pr.create_review_comment,
                body=comment.format_body(),
                commit=repo.get_commit(commit_sha),
                path=comment.file_path,
                line=comment.line_number
            )

            logger.info(
                "review_comment_posted",
                pr_number=pr_number,
                file=comment.file_path,
                line=comment.line_number,
                comment_id=review_comment.id
            )

            return review_comment.id

        except GithubException as e:
            # If line-level comment fails, try PR-level comment
            if e.status == 422:
                logger.warning(
                    "line_comment_failed_trying_pr_comment",
                    file=comment.file_path,
                    line=comment.line_number
                )
                issue_comment = self._api_call(
                    pr.create_issue_comment,
                    f"**{comment.file_path}:{comment.line_number}**\n\n{comment.format_body()}"
                )
                return issue_comment.id
            raise

    def post_review(
        self,
        repo_full_name: str,
        pr_number: int,
        comments: list[ReviewComment],
        summary: str,
        event: str = "COMMENT"  # APPROVE, REQUEST_CHANGES, COMMENT
    ) -> int:
        """
        Post a full review with multiple comments at once.
        This is more efficient than posting individual comments.
        """
        repo = self.get_repository(repo_full_name)
        pr = self._api_call(repo.get_pull, pr_number)

        # Format comments for the review API
        review_comments = []
        for comment in comments:
            review_comments.append({
                "path": comment.file_path,
                "line": comment.line_number,
                "body": comment.format_body()
            })

        review = self._api_call(
            pr.create_review,
            body=summary,
            event=event,
            comments=review_comments
        )

        logger.info(
            "review_posted",
            pr_number=pr_number,
            comments_count=len(comments),
            event=event,
            review_id=review.id
        )

        return review.id

    def post_issue_comment(
        self,
        repo_full_name: str,
        pr_number: int,
        body: str
    ) -> int:
        """Post a general comment on a pull request (not line-specific)."""
        repo = self.get_repository(repo_full_name)
        pr = self._api_call(repo.get_pull, pr_number)

        comment = self._api_call(pr.create_issue_comment, body)

        logger.info(
            "issue_comment_posted",
            pr_number=pr_number,
            comment_id=comment.id
        )

        return comment.id

    def post_review_comments(
        self,
        repo: str,
        pr_number: int,
        comments: list[ReviewComment]
    ) -> None:
        """Post multiple review comments to a PR."""
        for comment in comments:
            try:
                self.post_review_comment(repo, pr_number, comment)
            except Exception as e:
                logger.warning(
                    "failed_to_post_comment",
                    file=comment.file_path,
                    line=comment.line_number,
                    error=str(e)
                )

    def create_commit(
        self,
        repo_full_name: str,
        branch: str,
        file_path: str,
        content: str,
        message: str
    ) -> str:
        """
        Create or update a file in the repository.
        Returns the commit SHA.
        """
        repo = self.get_repository(repo_full_name)

        try:
            # Try to get existing file
            existing = self._api_call(repo.get_contents, file_path, ref=branch)
            result = self._api_call(
                repo.update_file,
                file_path,
                message,
                content,
                existing.sha,
                branch=branch
            )
        except GithubException as e:
            if e.status == 404:
                # File doesn't exist, create it
                result = self._api_call(
                    repo.create_file,
                    file_path,
                    message,
                    content,
                    branch=branch
                )
            else:
                raise

        commit_sha = result["commit"].sha
        logger.info(
            "commit_created",
            repo=repo_full_name,
            branch=branch,
            file=file_path,
            sha=commit_sha
        )

        return commit_sha

    def create_commit_bulk(
        self,
        repo_full_name: str,
        branch: str,
        file_updates: dict[str, str],
        message: str
    ) -> str:
        """
        Create a single commit updating multiple files.
        Returns the commit SHA.
        """
        repo = self.get_repository(repo_full_name)

        # Get current commit for the branch
        ref = repo.get_git_ref(f"heads/{branch}")
        base_commit = repo.get_git_commit(ref.object.sha)
        base_tree = base_commit.tree

        # Create blobs and tree elements
        elements = []
        for path, content in file_updates.items():
            blob = repo.create_git_blob(content, "utf-8")
            elements.append(InputGitTreeElement(path=path, mode="100644", type="blob", sha=blob.sha))

        # Create new tree
        new_tree = repo.create_git_tree(elements, base_tree)

        # Create commit
        new_commit = repo.create_git_commit(message, new_tree, [base_commit])

        # Update branch reference
        ref.edit(new_commit.sha)

        logger.info(
            "bulk_commit_created",
            repo=repo_full_name,
            branch=branch,
            files=len(file_updates),
            sha=new_commit.sha
        )

        return new_commit.sha

    def get_file_content(
        self,
        repo_full_name: str,
        file_path: str,
        ref: str = "main"
    ) -> str | None:
        """Get the content of a file from the repository."""
        repo = self.get_repository(repo_full_name)

        try:
            content_file = self._api_call(repo.get_contents, file_path, ref=ref)
            if hasattr(content_file, 'decoded_content'):
                return content_file.decoded_content.decode('utf-8')
        except GithubException as e:
            if e.status == 404:
                return None
            raise

        return None
