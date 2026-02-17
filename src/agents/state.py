"""
State management for multi-agent code review system.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Any

from src.utils.logging import get_logger

logger = get_logger("agents.state")


class AgentStatus(str, Enum):
    """Status of an agent's work."""
    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    FAILED = "failed"
    DELEGATED = "delegated"


class HandoffReason(str, Enum):
    """Reasons for delegating to another agent."""
    HIGH_COMPLEXITY = "high_complexity"
    MULTIPLE_VIOLATIONS = "multiple_violations"
    AUTO_FIXABLE = "auto_fixable"
    SECURITY_CRITICAL = "security_critical"
    TEST_COVERAGE = "test_coverage"
    MANUAL_REQUEST = "manual_request"


@dataclass
class HandoffDecision:
    """Decision to hand off work to another agent."""

    should_handoff: bool
    target_agent: str | None = None
    reasons: list[HandoffReason] = field(default_factory=list)
    priority_files: list[str] = field(default_factory=list)
    context: dict[str, Any] = field(default_factory=dict)

    @property
    def should_delegate(self) -> bool:
        """Alias for should_handoff for backwards compatibility."""
        return self.should_handoff

    def to_dict(self) -> dict[str, Any]:
        return {
            "should_handoff": self.should_handoff,
            "target_agent": self.target_agent,
            "reasons": [r.value for r in self.reasons],
            "priority_files": self.priority_files,
            "context": self.context
        }


@dataclass
class AgentWorkItem:
    """A single work item for an agent."""

    item_id: str
    file_path: str
    task_type: str
    priority: int = 0
    data: dict[str, Any] = field(default_factory=dict)
    status: AgentStatus = AgentStatus.PENDING
    result: dict[str, Any] | None = None
    error: str | None = None


@dataclass
class AgentState:
    """
    State management for agent handoffs and coordination.

    This maintains the state across agent transitions, enabling:
    - State persistence for long-running reviews
    - Context sharing between agents
    - Rollback capability
    - Progress tracking
    """

    session_id: str = ""
    pr_number: int = 0
    repo_full_name: str = ""

    # Current state
    current_agent: str = "code_review"
    status: AgentStatus = AgentStatus.PENDING

    # Work items
    work_items: list[AgentWorkItem] = field(default_factory=list)

    # Results from each agent
    review_results: dict[str, Any] = field(default_factory=dict)
    refactoring_results: dict[str, Any] = field(default_factory=dict)
    verification_results: dict[str, Any] = field(default_factory=dict)

    # Handoff history
    handoff_history: list[dict[str, Any]] = field(default_factory=list)

    # Checkpoints for rollback
    checkpoints: list[dict[str, Any]] = field(default_factory=list)

    # Timing
    started_at: datetime | None = None
    completed_at: datetime | None = None

    def __post_init__(self):
        if not self.session_id:
            self.session_id = datetime.now().strftime("%Y%m%d_%H%M%S")

    def start(self) -> None:
        """Mark the review session as started."""
        self.status = AgentStatus.IN_PROGRESS
        self.started_at = datetime.now()
        logger.info(
            "agent_session_started",
            session_id=self.session_id,
            pr_number=self.pr_number
        )

    def complete(self) -> None:
        """Mark the review session as completed."""
        self.status = AgentStatus.COMPLETED
        self.completed_at = datetime.now()
        logger.info(
            "agent_session_completed",
            session_id=self.session_id,
            duration_seconds=(self.completed_at - self.started_at).total_seconds()
            if self.started_at else None
        )

    def fail(self, error: str) -> None:
        """Mark the review session as failed."""
        self.status = AgentStatus.FAILED
        self.completed_at = datetime.now()
        logger.error(
            "agent_session_failed",
            session_id=self.session_id,
            error=error
        )

    def create_checkpoint(self, name: str) -> None:
        """Create a checkpoint for potential rollback."""
        checkpoint = {
            "name": name,
            "timestamp": datetime.now().isoformat(),
            "current_agent": self.current_agent,
            "status": self.status.value,
            "review_results": self.review_results.copy(),
            "refactoring_results": self.refactoring_results.copy(),
            "work_items": [
                {"item_id": w.item_id, "status": w.status.value}
                for w in self.work_items
            ]
        }
        self.checkpoints.append(checkpoint)
        logger.info(
            "checkpoint_created",
            name=name,
            total_checkpoints=len(self.checkpoints)
        )

    def rollback_to_checkpoint(self, name: str) -> bool:
        """Rollback to a named checkpoint."""
        for i, checkpoint in enumerate(self.checkpoints):
            if checkpoint["name"] == name:
                # Restore state
                self.current_agent = checkpoint["current_agent"]
                self.status = AgentStatus(checkpoint["status"])
                self.review_results = checkpoint["review_results"]
                self.refactoring_results = checkpoint["refactoring_results"]

                # Remove checkpoints after this one
                self.checkpoints = self.checkpoints[:i + 1]

                logger.info(
                    "rollback_completed",
                    checkpoint_name=name
                )
                return True

        logger.warning("checkpoint_not_found", name=name)
        return False

    def rollback(self, name: str) -> bool:
        """Alias for rollback_to_checkpoint."""
        return self.rollback_to_checkpoint(name)

    def record_handoff(
        self,
        from_agent: str,
        to_agent: str,
        decision: HandoffDecision
    ) -> None:
        """Record a handoff between agents."""
        self.handoff_history.append({
            "timestamp": datetime.now().isoformat(),
            "from_agent": from_agent,
            "to_agent": to_agent,
            "decision": decision.to_dict()
        })
        self.current_agent = to_agent
        logger.info(
            "agent_handoff",
            from_agent=from_agent,
            to_agent=to_agent,
            reasons=[r.value for r in decision.reasons]
        )

    def add_work_item(
        self,
        work_item: AgentWorkItem = None,
        item_id: str = None,
        file_path: str = None,
        task_type: str = None,
        priority: int = 0,
        data: dict | None = None
    ) -> AgentWorkItem:
        """Add a work item to the queue."""
        if work_item is not None:
            self.work_items.append(work_item)
            return work_item
        item = AgentWorkItem(
            item_id=item_id or str(len(self.work_items)),
            file_path=file_path or "",
            task_type=task_type or "unknown",
            priority=priority,
            data=data or {}
        )
        self.work_items.append(item)
        return item

    def update_context(self, key: str, value: Any) -> None:
        """Update context data for the current workflow."""
        if not hasattr(self, '_context'):
            self._context = {}
        self._context[key] = value

    def get_context(self, key: str, default: Any = None) -> Any:
        """Get context data for the current workflow."""
        if not hasattr(self, '_context'):
            return default
        return self._context.get(key, default)

    def complete_work_item(self, item_id: str, result: dict | None = None) -> None:
        """Mark a work item as complete (alias for mark_item_complete)."""
        self.mark_item_complete(item_id, result)

    def get_pending_items(self) -> list[AgentWorkItem]:
        """Get pending work items sorted by priority."""
        pending = [w for w in self.work_items if w.status == AgentStatus.PENDING]
        return sorted(pending, key=lambda x: -x.priority)

    def mark_item_complete(
        self,
        item_id: str,
        result: dict | None = None
    ) -> None:
        """Mark a work item as complete."""
        for item in self.work_items:
            if item.item_id == item_id:
                item.status = AgentStatus.COMPLETED
                item.result = result
                break

    def mark_item_failed(self, item_id: str, error: str) -> None:
        """Mark a work item as failed."""
        for item in self.work_items:
            if item.item_id == item_id:
                item.status = AgentStatus.FAILED
                item.error = error
                break

    def to_dict(self) -> dict[str, Any]:
        """Serialize state to dictionary."""
        return {
            "pr_number": self.pr_number,
            "repo_full_name": self.repo_full_name,
            "session_id": self.session_id,
            "current_agent": self.current_agent,
            "status": self.status.value,
            "started_at": self.started_at.isoformat() if self.started_at else None,
            "completed_at": self.completed_at.isoformat() if self.completed_at else None,
            "review_results": self.review_results,
            "refactoring_results": self.refactoring_results,
            "verification_results": self.verification_results,
            "handoff_history": self.handoff_history,
            "work_items": [
                {
                    "item_id": w.item_id,
                    "file_path": w.file_path,
                    "task_type": w.task_type,
                    "priority": w.priority,
                    "status": w.status.value,
                    "result": w.result,
                    "error": w.error
                }
                for w in self.work_items
            ]
        }

    def save(self, path: Path | None = None) -> Path:
        """Save state to file."""
        if path is None:
            path = Path(f"state_{self.session_id}.json")

        with open(path, "w") as f:
            json.dump(self.to_dict(), f, indent=2)

        logger.info("state_saved", path=str(path))
        return path

    @classmethod
    def load(cls, path: Path) -> AgentState:
        """Load state from file."""
        with open(path) as f:
            data = json.load(f)

        state = cls(
            pr_number=data["pr_number"],
            repo_full_name=data["repo_full_name"],
            session_id=data["session_id"]
        )
        state.current_agent = data.get("current_agent", "code_review")
        state.status = AgentStatus(data.get("status", "pending"))
        state.review_results = data.get("review_results", {})
        state.refactoring_results = data.get("refactoring_results", {})
        state.verification_results = data.get("verification_results", {})
        state.handoff_history = data.get("handoff_history", [])

        if data.get("started_at"):
            state.started_at = datetime.fromisoformat(data["started_at"])
        if data.get("completed_at"):
            state.completed_at = datetime.fromisoformat(data["completed_at"])

        # Restore work items
        for item_data in data.get("work_items", []):
            item = AgentWorkItem(
                item_id=item_data["item_id"],
                file_path=item_data["file_path"],
                task_type=item_data["task_type"],
                priority=item_data.get("priority", 0),
                status=AgentStatus(item_data.get("status", "pending")),
                result=item_data.get("result"),
                error=item_data.get("error")
            )
            state.work_items.append(item)

        logger.info("state_loaded", path=str(path))
        return state
