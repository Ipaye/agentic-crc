"""
Verification Agent - Validates refactoring changes before commit.

Safety mechanisms include:
- Syntax validation
- Test execution
- Change impact assessment
- Rollback capability
"""
from __future__ import annotations

import ast
import subprocess
import tempfile
from dataclasses import dataclass, field
from pathlib import Path

from .refactoring_agent import RefactoringResult
from .state import AgentState


@dataclass
class VerificationResult:
    """Result of verification checks."""
    file_path: str
    syntax_valid: bool = True
    tests_passed: bool | None = None  # None if no tests run
    impact_score: float = 0.0  # 0-1, higher = more risky
    issues: list[str] = field(default_factory=list)

    @property
    def is_safe(self) -> bool:
        """Check if changes are safe to commit."""
        if not self.syntax_valid:
            return False
        if self.tests_passed is False:
            return False
        if self.impact_score > 0.8:
            return False
        return True


@dataclass
class BatchVerificationResult:
    """Result of verifying multiple files."""
    results: list[VerificationResult] = field(default_factory=list)
    all_safe: bool = True
    total_issues: int = 0
    summary: str = ""

    def add_result(self, result: VerificationResult):
        """Add a verification result."""
        self.results.append(result)
        if not result.is_safe:
            self.all_safe = False
        self.total_issues += len(result.issues)


class VerificationAgent:
    """
    Agent responsible for verifying code changes before commit.

    Capabilities:
    - Syntax validation for multiple languages
    - Test execution (when test files exist)
    - Change impact assessment
    - Rollback recommendation
    """

    def __init__(
        self,
        state: AgentState | None = None,
        enable_test_execution: bool = False,
        impact_threshold: float = 0.8
    ):
        self.state = state or AgentState(session_id="verification")
        self.enable_test_execution = enable_test_execution
        self.impact_threshold = impact_threshold

    async def verify_refactoring(
        self,
        results: list[RefactoringResult]
    ) -> BatchVerificationResult:
        """
        Verify all refactoring results.

        Args:
            results: List of refactoring results to verify

        Returns:
            BatchVerificationResult with all verification outcomes
        """
        self.state.create_checkpoint("pre_verification")

        batch_result = BatchVerificationResult()

        for result in results:
            if not result.success:
                batch_result.add_result(VerificationResult(
                    file_path=result.file_path,
                    syntax_valid=False,
                    issues=["Refactoring failed"]
                ))
                continue

            verification = await self._verify_file(result)
            batch_result.add_result(verification)

        batch_result.summary = self._generate_summary(batch_result)

        return batch_result

    async def _verify_file(self, result: RefactoringResult) -> VerificationResult:
        """Verify a single refactored file."""
        verification = VerificationResult(file_path=result.file_path)

        # Skip if no changes
        if result.original_content == result.refactored_content:
            return verification

        # Syntax validation
        syntax_valid, syntax_errors = self._validate_syntax(
            result.refactored_content,
            result.file_path
        )
        verification.syntax_valid = syntax_valid
        verification.issues.extend(syntax_errors)

        # Impact assessment
        verification.impact_score = self._assess_impact(
            result.original_content,
            result.refactored_content,
            result.changes_made
        )

        if verification.impact_score > self.impact_threshold:
            verification.issues.append(
                f"High impact score ({verification.impact_score:.2f}) - manual review recommended"
            )

        # Test execution (if enabled)
        if self.enable_test_execution and syntax_valid:
            test_passed, test_errors = await self._run_tests(
                result.file_path,
                result.refactored_content
            )
            verification.tests_passed = test_passed
            verification.issues.extend(test_errors)

        return verification

    def _validate_syntax(
        self,
        content: str,
        filename: str
    ) -> tuple[bool, list[str]]:
        """Validate syntax of the refactored content."""
        errors = []
        filename_lower = filename.lower()

        # Python
        if filename_lower.endswith('.py'):
            try:
                ast.parse(content)
                return True, []
            except SyntaxError as e:
                errors.append(f"Python syntax error at line {e.lineno}: {e.msg}")
                return False, errors

        # JavaScript/TypeScript - basic validation
        if filename_lower.endswith(('.js', '.ts', '.jsx', '.tsx')):
            issues = self._validate_js_basic(content)
            if issues:
                return False, issues
            return True, []

        # JSON
        if filename_lower.endswith('.json'):
            import json
            try:
                json.loads(content)
                return True, []
            except json.JSONDecodeError as e:
                errors.append(f"JSON error: {e.msg}")
                return False, errors

        # YAML
        if filename_lower.endswith(('.yaml', '.yml')):
            try:
                import yaml
                yaml.safe_load(content)
                return True, []
            except yaml.YAMLError as e:
                errors.append(f"YAML error: {str(e)}")
                return False, errors

        # For unknown file types, assume valid
        return True, []

    def _validate_js_basic(self, content: str) -> list[str]:
        """Basic JavaScript/TypeScript validation."""
        issues = []

        # Check balanced braces
        if content.count('{') != content.count('}'):
            issues.append("Unbalanced curly braces")

        if content.count('(') != content.count(')'):
            issues.append("Unbalanced parentheses")

        if content.count('[') != content.count(']'):
            issues.append("Unbalanced square brackets")

        # Check for common issues
        lines = content.split('\n')
        for i, line in enumerate(lines, 1):
            stripped = line.strip()

            # Empty statement
            if stripped == ';':
                issues.append(f"Line {i}: Empty statement")

            # Likely incomplete line
            if stripped.endswith(('=', '+', '-', '*', '/', '&&', '||', ',')):
                if i < len(lines) and not lines[i].strip():
                    issues.append(f"Line {i}: Incomplete statement")

        return issues

    def _assess_impact(
        self,
        original: str,
        refactored: str,
        changes_made: list[str]
    ) -> float:
        """
        Assess the impact/risk of the changes.

        Returns a score from 0-1 where higher = more risky.
        """
        if not original or not refactored:
            return 0.0

        score = 0.0

        # Factor 1: Percentage of lines changed
        orig_lines = len(original.split('\n'))
        refact_lines = len(refactored.split('\n'))
        line_diff = abs(orig_lines - refact_lines)

        if orig_lines > 0:
            change_ratio = line_diff / orig_lines
            score += min(change_ratio * 0.3, 0.3)

        # Factor 2: Type of changes
        high_risk_patterns = [
            'security', 'auth', 'password', 'token', 'key',
            'delete', 'remove', 'drop', 'truncate'
        ]

        for change in changes_made:
            change_lower = change.lower()
            if any(pattern in change_lower for pattern in high_risk_patterns):
                score += 0.2
                break

        # Factor 3: Structural changes
        if 'class' in original and 'class' not in refactored:
            score += 0.2

        if 'def ' in original:
            orig_funcs = original.count('def ')
            refact_funcs = refactored.count('def ')
            if orig_funcs != refact_funcs:
                score += 0.1

        # Factor 4: Number of changes
        num_changes = len(changes_made)
        if num_changes > 10:
            score += 0.2
        elif num_changes > 5:
            score += 0.1

        return min(score, 1.0)

    async def _run_tests(
        self,
        file_path: str,
        content: str
    ) -> tuple[bool, list[str]]:
        """
        Run tests for the refactored file.

        This is a simplified implementation. In production,
        you'd integrate with the actual test framework.
        """
        errors = []

        # Only run for Python files for now
        if not file_path.endswith('.py'):
            return True, []

        # Create temporary file with refactored content
        with tempfile.NamedTemporaryFile(
            mode='w',
            suffix='.py',
            delete=False
        ) as f:
            f.write(content)
            temp_path = f.name

        try:
            # Try to find associated test file
            test_file = self._find_test_file(file_path)

            if test_file:
                # Run pytest on the test file
                result = subprocess.run(
                    ['python', '-m', 'pytest', test_file, '-v', '--tb=short'],
                    capture_output=True,
                    text=True,
                    timeout=60
                )

                if result.returncode != 0:
                    errors.append(f"Tests failed:\n{result.stdout}\n{result.stderr}")
                    return False, errors

                return True, []

            # No test file found, try basic import test
            result = subprocess.run(
                ['python', '-c', f'import ast; ast.parse(open("{temp_path}").read())'],
                capture_output=True,
                text=True,
                timeout=10
            )

            if result.returncode != 0:
                errors.append(f"Import test failed: {result.stderr}")
                return False, errors

            return True, []

        except subprocess.TimeoutExpired:
            errors.append("Test execution timed out")
            return False, errors
        except Exception as e:
            errors.append(f"Test execution error: {str(e)}")
            return False, errors
        finally:
            # Clean up temp file
            Path(temp_path).unlink(missing_ok=True)

    def _find_test_file(self, file_path: str) -> str | None:
        """Find the test file for a given source file."""
        path = Path(file_path)

        # Common test file patterns
        test_patterns = [
            f"test_{path.name}",
            f"{path.stem}_test.py",
            f"tests/test_{path.name}",
            f"tests/{path.stem}_test.py",
        ]

        for pattern in test_patterns:
            test_path = path.parent / pattern
            if test_path.exists():
                return str(test_path)

        return None

    def _generate_summary(self, batch_result: BatchVerificationResult) -> str:
        """Generate a summary of verification results."""
        lines = ["## Verification Summary", ""]

        total = len(batch_result.results)
        safe = sum(1 for r in batch_result.results if r.is_safe)

        lines.append(f"**Files verified:** {total}")
        lines.append(f"**Safe to commit:** {safe}/{total}")
        lines.append(f"**Total issues:** {batch_result.total_issues}")
        lines.append("")

        if batch_result.all_safe:
            lines.append("✅ All changes verified safe for commit.")
        else:
            lines.append("⚠️ Some changes require attention before commit.")
            lines.append("")
            lines.append("### Issues Found")

            for result in batch_result.results:
                if result.issues:
                    lines.append(f"\n**{result.file_path}:**")
                    for issue in result.issues:
                        lines.append(f"- {issue}")

        return "\n".join(lines)

    def should_proceed_with_commit(
        self,
        batch_result: BatchVerificationResult
    ) -> tuple[bool, str]:
        """
        Determine if changes should be committed.

        Returns:
            Tuple of (should_commit, reason)
        """
        if batch_result.all_safe:
            return True, "All verifications passed"

        # Check if issues are minor
        critical_issues = []
        for result in batch_result.results:
            if not result.syntax_valid:
                critical_issues.append(f"{result.file_path}: Invalid syntax")
            if result.tests_passed is False:
                critical_issues.append(f"{result.file_path}: Tests failed")

        if critical_issues:
            return False, "Critical issues found: " + "; ".join(critical_issues)

        # Allow commit with warnings if no critical issues
        if batch_result.total_issues <= 3:
            return True, "Minor issues found, proceeding with caution"

        return False, f"Too many issues ({batch_result.total_issues}) - manual review required"

    async def rollback_on_failure(self) -> bool:
        """Rollback changes if verification failed."""
        return self.state.rollback("pre_verification")
