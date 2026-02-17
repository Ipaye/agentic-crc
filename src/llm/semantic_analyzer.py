"""
Semantic code analyzer using LLM for deep analysis.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any

from src.github.models import FileChange, ReviewComment, ReviewCommentSeverity
from src.llm.ollama_client import OllamaClient
from src.llm.prompts import PromptTemplates
from src.utils.logging import get_logger

logger = get_logger("llm.semantic")


@dataclass
class SemanticIssue:
    """An issue found through semantic analysis."""

    line: int
    severity: str
    category: str
    description: str
    suggestion: str
    code_example: str | None = None
    confidence: float = 0.8


@dataclass
class SemanticAnalysisResult:
    """Result of semantic code analysis."""

    file_path: str
    issues: list[SemanticIssue] = field(default_factory=list)
    overall_assessment: str = ""
    positive_aspects: list[str] = field(default_factory=list)
    priority_fixes: list[str] = field(default_factory=list)
    raw_response: str | None = None


class SemanticAnalyzer:
    """
    Uses LLM for semantic code analysis beyond pattern matching.

    This analyzer catches issues that require understanding of:
    - Code semantics and intent
    - Business logic correctness
    - Naming appropriateness
    - Architecture concerns
    - Complex security issues
    """

    def __init__(self, ollama_client: OllamaClient | None = None):
        """Initialize the semantic analyzer."""
        self.client = ollama_client or OllamaClient()
        self._available = self._check_availability()

        logger.info(
            "semantic_analyzer_initialized",
            available=self._available
        )

    def _check_availability(self) -> bool:
        """Check if LLM is available for analysis."""
        try:
            return self.client._check_connection()
        except Exception:
            return False

    @property
    def is_available(self) -> bool:
        """Check if semantic analysis is available."""
        return self._available

    async def analyze_file(
        self,
        file_change: FileChange,
        analysis_type: str = "review",
        focus_areas: list[str] | None = None
    ) -> SemanticAnalysisResult:
        """
        Perform semantic analysis on a file.

        Args:
            file_change: The file to analyze
            analysis_type: Type of analysis (review, security, performance)
            focus_areas: Specific areas to focus on
        """
        if not self._available:
            logger.warning("semantic_analysis_unavailable")
            return SemanticAnalysisResult(file_path=file_change.filename)

        code = file_change.content or ""
        if not code and file_change.patch:
            # Extract code from patch
            lines = []
            for line in file_change.patch.split("\n"):
                if line.startswith("+") and not line.startswith("+++"):
                    lines.append(line[1:])
                elif line.startswith(" "):
                    lines.append(line[1:])
            code = "\n".join(lines)

        if not code:
            return SemanticAnalysisResult(file_path=file_change.filename)

        # Generate analysis prompt
        prompt = PromptTemplates.get_analysis_prompt(
            code=code,
            filename=file_change.filename,
            analysis_type=analysis_type,
            focus_areas=focus_areas
        )

        system_prompt = PromptTemplates.get_system_prompt(analysis_type)

        try:
            response = await self.client.generate_async(
                prompt=prompt,
                system_prompt=system_prompt,
                temperature=0.1
            )

            return self._parse_response(file_change.filename, response)

        except Exception as e:
            logger.error(
                "semantic_analysis_failed",
                file=file_change.filename,
                error=str(e)
            )
            return SemanticAnalysisResult(
                file_path=file_change.filename,
                raw_response=str(e)
            )

    def analyze_file_sync(
        self,
        file_change: FileChange,
        analysis_type: str = "review",
        focus_areas: list[str] | None = None
    ) -> SemanticAnalysisResult:
        """Synchronous version of analyze_file."""
        if not self._available:
            logger.warning("semantic_analysis_unavailable")
            return SemanticAnalysisResult(file_path=file_change.filename)

        code = file_change.content or ""
        if not code and file_change.patch:
            lines = []
            for line in file_change.patch.split("\n"):
                if line.startswith("+") and not line.startswith("+++"):
                    lines.append(line[1:])
                elif line.startswith(" "):
                    lines.append(line[1:])
            code = "\n".join(lines)

        if not code:
            return SemanticAnalysisResult(file_path=file_change.filename)

        prompt = PromptTemplates.get_analysis_prompt(
            code=code,
            filename=file_change.filename,
            analysis_type=analysis_type,
            focus_areas=focus_areas
        )

        system_prompt = PromptTemplates.get_system_prompt(analysis_type)

        try:
            response = self.client.generate(
                prompt=prompt,
                system_prompt=system_prompt,
                temperature=0.1
            )

            return self._parse_response(file_change.filename, response)

        except Exception as e:
            logger.error(
                "semantic_analysis_failed",
                file=file_change.filename,
                error=str(e)
            )
            return SemanticAnalysisResult(
                file_path=file_change.filename,
                raw_response=str(e)
            )

    async def analyze_diff(
        self,
        file_change: FileChange
    ) -> SemanticAnalysisResult:
        """
        Analyze only the changed code in a diff.
        """
        if not self._available or not file_change.patch:
            return SemanticAnalysisResult(file_path=file_change.filename)

        prompt = PromptTemplates.get_diff_review_prompt(
            diff=file_change.patch,
            filename=file_change.filename,
            full_file_content=file_change.content
        )

        system_prompt = PromptTemplates.get_system_prompt("review")

        try:
            response = await self.client.generate_async(
                prompt=prompt,
                system_prompt=system_prompt,
                temperature=0.1
            )

            return self._parse_response(file_change.filename, response)

        except Exception as e:
            logger.error(
                "diff_analysis_failed",
                file=file_change.filename,
                error=str(e)
            )
            return SemanticAnalysisResult(file_path=file_change.filename)

    def analyze_diff_sync(
        self,
        file_change: FileChange
    ) -> SemanticAnalysisResult:
        """
        Synchronous version of analyze_diff.
        """
        if not self._available or not file_change.patch:
            return SemanticAnalysisResult(file_path=file_change.filename)

        prompt = PromptTemplates.get_diff_review_prompt(
            diff=file_change.patch,
            filename=file_change.filename,
            full_file_content=file_change.content
        )

        system_prompt = PromptTemplates.get_system_prompt("review")

        try:
            response = self.client.generate(
                prompt=prompt,
                system_prompt=system_prompt,
                temperature=0.1
            )

            return self._parse_response(file_change.filename, response)

        except Exception as e:
            logger.error(
                "diff_analysis_failed",
                file=file_change.filename,
                error=str(e)
            )
            return SemanticAnalysisResult(file_path=file_change.filename)

    def _parse_response(
        self,
        file_path: str,
        response: str
    ) -> SemanticAnalysisResult:
        """Parse LLM response into structured result."""
        result = SemanticAnalysisResult(
            file_path=file_path,
            raw_response=response
        )

        try:
            # Try to extract JSON from response
            import re
            json_match = re.search(
                r"```(?:json)?\s*(\{.*?\})\s*```",
                response,
                re.DOTALL
            )

            if json_match:
                data = json.loads(json_match.group(1))
            else:
                # Try parsing whole response as JSON
                data = json.loads(response)

            # Extract issues
            for issue_data in data.get("issues", []):
                issue = SemanticIssue(
                    line=issue_data.get("line", 1),
                    severity=issue_data.get("severity", "warning"),
                    category=issue_data.get("category", "quality"),
                    description=issue_data.get("description", ""),
                    suggestion=issue_data.get("suggestion", ""),
                    code_example=issue_data.get("code_example")
                )
                result.issues.append(issue)

            result.overall_assessment = data.get("overall_assessment", "")
            result.positive_aspects = data.get("positive_aspects", [])
            result.priority_fixes = data.get("priority_fixes", [])

        except (json.JSONDecodeError, KeyError) as e:
            logger.warning(
                "failed_to_parse_llm_response",
                error=str(e),
                response_preview=response[:200]
            )
            # Try to extract issues from unstructured text
            result.issues = self._extract_issues_from_text(response)

        return result

    def _extract_issues_from_text(self, text: str) -> list[SemanticIssue]:
        """Extract issues from unstructured LLM response."""
        issues = []
        import re

        # Look for issue-like patterns
        lines = text.split("\n")

        for line in lines:
            # Check for numbered or bulleted items
            match = re.match(r"^(?:\d+[.)]|\*|-)\s*(.+)", line)
            if match:
                content = match.group(1)

                # Try to extract line number
                line_match = re.search(r"[Ll]ine\s*(\d+)", content)
                line_num = int(line_match.group(1)) if line_match else 1

                # Infer severity
                severity = "warning"
                if any(w in content.lower() for w in ["error", "critical", "bug"]):
                    severity = "error"
                elif any(w in content.lower() for w in ["suggestion", "consider", "minor"]):
                    severity = "suggestion"
                elif any(w in content.lower() for w in ["info", "note"]):
                    severity = "info"

                issues.append(SemanticIssue(
                    line=line_num,
                    severity=severity,
                    category="quality",
                    description=content,
                    suggestion="",
                    confidence=0.6  # Lower confidence for text extraction
                ))

        return issues

    def to_review_comments(
        self,
        result: SemanticAnalysisResult
    ) -> list[ReviewComment]:
        """Convert semantic analysis result to review comments."""
        comments = []

        severity_map = {
            "error": ReviewCommentSeverity.ERROR,
            "warning": ReviewCommentSeverity.WARNING,
            "info": ReviewCommentSeverity.INFO,
            "suggestion": ReviewCommentSeverity.SUGGESTION
        }

        for issue in result.issues:
            body = f"**{issue.category.title()}**: {issue.description}"

            if issue.suggestion:
                body += f"\n\n**Suggestion**: {issue.suggestion}"

            if issue.code_example:
                body += f"\n\n**Example fix**:\n```\n{issue.code_example}\n```"

            comments.append(ReviewComment(
                file_path=result.file_path,
                line_number=issue.line,
                body=body,
                severity=severity_map.get(issue.severity, ReviewCommentSeverity.WARNING),
                rule_id=f"SEMANTIC-{issue.category.upper()}"
            ))

        return comments

    async def get_refactoring_suggestions(
        self,
        file_change: FileChange,
        issues: list[str]
    ) -> dict[str, Any]:
        """
        Get specific refactoring suggestions for identified issues.
        """
        if not self._available or not file_change.content:
            return {"refactorings": []}

        prompt = PromptTemplates.get_refactoring_prompt(
            code=file_change.content,
            filename=file_change.filename,
            issues=issues
        )

        system_prompt = PromptTemplates.get_system_prompt("refactoring")

        try:
            response = await self.client.generate_async(
                prompt=prompt,
                system_prompt=system_prompt,
                temperature=0.2
            )

            # Parse JSON response
            import re
            json_match = re.search(
                r"```(?:json)?\s*(\{.*?\})\s*```",
                response,
                re.DOTALL
            )

            if json_match:
                return json.loads(json_match.group(1))

            return {"refactorings": [], "raw_response": response}

        except Exception as e:
            logger.error(
                "refactoring_suggestions_failed",
                error=str(e)
            )
            return {"refactorings": [], "error": str(e)}

    async def explain_code(
        self,
        code: str,
        filename: str
    ) -> str:
        """Get an explanation of a code snippet."""
        if not self._available:
            return "Semantic analysis unavailable."

        prompt = PromptTemplates.get_explanation_prompt(code, filename)

        try:
            return await self.client.generate_async(
                prompt=prompt,
                temperature=0.3
            )
        except Exception as e:
            logger.error("code_explanation_failed", error=str(e))
            return f"Failed to generate explanation: {e}"
