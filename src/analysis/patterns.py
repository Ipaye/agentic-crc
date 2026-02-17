"""
Pattern matching utilities for code analysis.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from enum import Enum

from src.analysis.parser import Language
from src.utils.logging import get_logger

logger = get_logger("analysis.patterns")


class PatternType(str, Enum):
    """Types of code patterns."""
    CODE_SMELL = "code_smell"
    ANTI_PATTERN = "anti_pattern"
    SECURITY_RISK = "security_risk"
    PERFORMANCE_ISSUE = "performance_issue"
    STYLE_VIOLATION = "style_violation"


@dataclass
class PatternMatch:
    """Result of a pattern match."""

    pattern_name: str
    pattern_type: PatternType
    file_path: str
    line_number: int
    column: int
    matched_text: str
    context: str  # Surrounding code for context
    description: str
    severity: str
    fix_suggestion: str | None = None


class PatternMatcher:
    """
    Advanced pattern matching for detecting code issues.
    """

    def __init__(self):
        """Initialize with built-in patterns."""
        self.patterns: dict[Language, list[dict]] = {
            Language.PYTHON: self._get_python_patterns(),
            Language.JAVASCRIPT: self._get_javascript_patterns(),
            Language.TYPESCRIPT: self._get_typescript_patterns(),
            Language.JAVA: self._get_java_patterns(),
        }

    def _get_python_patterns(self) -> list[dict]:
        """Get Python-specific patterns."""
        return [
            {
                "name": "mutable_default_argument",
                "type": PatternType.CODE_SMELL,
                "pattern": r"def\s+\w+\s*\([^)]*(\w+)\s*=\s*(\[\]|\{\}|\bset\(\))",
                "description": "Mutable default argument can cause unexpected behavior",
                "severity": "warning",
                "fix": "Use None as default and initialize inside the function"
            },
            {
                "name": "global_variable_modification",
                "type": PatternType.CODE_SMELL,
                "pattern": r"^\s*global\s+\w+",
                "description": "Modifying global variables makes code hard to reason about",
                "severity": "warning",
                "fix": "Consider passing values as arguments and returning results"
            },
            {
                "name": "bare_except",
                "type": PatternType.ANTI_PATTERN,
                "pattern": r"except\s*:",
                "description": "Bare except catches all exceptions including KeyboardInterrupt",
                "severity": "error",
                "fix": "Catch specific exceptions: except SpecificException:"
            },
            {
                "name": "string_format_injection",
                "type": PatternType.SECURITY_RISK,
                "pattern": r"\.format\s*\([^)]*\b(request|user_input|input)\b",
                "description": "Potential format string injection vulnerability",
                "severity": "error",
                "fix": "Validate and sanitize user input before formatting"
            },
            {
                "name": "subprocess_shell_true",
                "type": PatternType.SECURITY_RISK,
                "pattern": r"subprocess\.\w+\s*\([^)]*shell\s*=\s*True",
                "description": "Using shell=True with subprocess can be a security risk",
                "severity": "error",
                "fix": "Use shell=False and pass arguments as a list"
            },
            {
                "name": "pickle_load",
                "type": PatternType.SECURITY_RISK,
                "pattern": r"pickle\.loads?\s*\(",
                "description": "Unpickling untrusted data can execute arbitrary code",
                "severity": "error",
                "fix": "Use safer alternatives like JSON for serialization"
            },
            {
                "name": "inefficient_list_comprehension",
                "type": PatternType.PERFORMANCE_ISSUE,
                "pattern": r"list\s*\(\s*\w+\s+for\s+\w+\s+in",
                "description": "Use list comprehension directly instead of list() on generator",
                "severity": "info",
                "fix": "Replace list(x for x in ...) with [x for x in ...]"
            },
            {
                "name": "nested_list_append",
                "type": PatternType.PERFORMANCE_ISSUE,
                "pattern": r"for\s+\w+\s+in[^:]+:\s*\n\s+\w+\.append\(",
                "description": "Consider using list comprehension for better performance",
                "severity": "info",
                "fix": "Use list comprehension: [item for item in iterable]"
            },
            {
                "name": "star_import",
                "type": PatternType.STYLE_VIOLATION,
                "pattern": r"from\s+[\w.]+\s+import\s+\*",
                "description": "Star imports pollute namespace and make code harder to read",
                "severity": "warning",
                "fix": "Import specific names: from module import name1, name2"
            },
            {
                "name": "single_letter_variable",
                "type": PatternType.CODE_SMELL,
                "pattern": r"^\s*([a-zA-Z])\s*=\s*(?!.*for\s+\1\s+in)",
                "description": "Single-letter variable names reduce code readability",
                "severity": "info",
                "fix": "Use descriptive variable names"
            },
        ]

    def _get_javascript_patterns(self) -> list[dict]:
        """Get JavaScript-specific patterns."""
        return [
            {
                "name": "var_declaration",
                "type": PatternType.STYLE_VIOLATION,
                "pattern": r"\bvar\s+\w+\s*=",
                "description": "Use const or let instead of var",
                "severity": "warning",
                "fix": "Replace var with const for immutable values or let for mutable"
            },
            {
                "name": "equality_check",
                "type": PatternType.CODE_SMELL,
                "pattern": r"[^=!]\s*==\s*[^=]",
                "description": "Use strict equality (===) instead of loose equality (==)",
                "severity": "warning",
                "fix": "Replace == with === for type-safe comparison"
            },
            {
                "name": "nested_callbacks",
                "type": PatternType.CODE_SMELL,
                "pattern": r"function\s*\([^)]*\)\s*\{[^}]*function\s*\([^)]*\)\s*\{[^}]*function",
                "description": "Deeply nested callbacks (callback hell)",
                "severity": "warning",
                "fix": "Use async/await or Promise chains"
            },
            {
                "name": "innerHTML_assignment",
                "type": PatternType.SECURITY_RISK,
                "pattern": r"\.innerHTML\s*=",
                "description": "Direct innerHTML assignment can lead to XSS vulnerabilities",
                "severity": "error",
                "fix": "Use textContent or sanitize HTML before assignment"
            },
            {
                "name": "document_write",
                "type": PatternType.SECURITY_RISK,
                "pattern": r"document\.write\s*\(",
                "description": "document.write can overwrite the entire document",
                "severity": "error",
                "fix": "Use DOM manipulation methods instead"
            },
            {
                "name": "sync_xhr",
                "type": PatternType.PERFORMANCE_ISSUE,
                "pattern": r"XMLHttpRequest\s*\(\s*\)[^;]*\.open\s*\([^)]*,\s*[^)]*,\s*false",
                "description": "Synchronous XHR blocks the main thread",
                "severity": "error",
                "fix": "Use async XMLHttpRequest or fetch API"
            },
            {
                "name": "function_in_loop",
                "type": PatternType.PERFORMANCE_ISSUE,
                "pattern": r"for\s*\([^)]*\)\s*\{[^}]*function\s*\(",
                "description": "Function created inside loop - creates new function each iteration",
                "severity": "warning",
                "fix": "Define the function outside the loop"
            },
            {
                "name": "missing_await",
                "type": PatternType.CODE_SMELL,
                "pattern": r"async\s+function[^}]+(?<!await\s)\b(fetch|axios|request)\s*\(",
                "description": "Async function may be missing await on async operation",
                "severity": "warning",
                "fix": "Add await before the async operation"
            },
        ]

    def _get_typescript_patterns(self) -> list[dict]:
        """Get TypeScript-specific patterns (extends JavaScript)."""
        ts_patterns = self._get_javascript_patterns()
        ts_patterns.extend([
            {
                "name": "any_type",
                "type": PatternType.CODE_SMELL,
                "pattern": r":\s*any\b",
                "description": "Using 'any' type defeats TypeScript's type checking",
                "severity": "warning",
                "fix": "Define a proper type or use 'unknown' for truly unknown types"
            },
            {
                "name": "non_null_assertion",
                "type": PatternType.CODE_SMELL,
                "pattern": r"\w+!\.",
                "description": "Non-null assertion bypasses null checking",
                "severity": "info",
                "fix": "Use optional chaining (?.) or proper null checks"
            },
            {
                "name": "ts_ignore_comment",
                "type": PatternType.CODE_SMELL,
                "pattern": r"//\s*@ts-ignore",
                "description": "@ts-ignore suppresses all TypeScript errors",
                "severity": "warning",
                "fix": "Fix the type error or use @ts-expect-error with explanation"
            },
        ])
        return ts_patterns

    def _get_java_patterns(self) -> list[dict]:
        """Get Java-specific patterns."""
        return [
            {
                "name": "string_concatenation_loop",
                "type": PatternType.PERFORMANCE_ISSUE,
                "pattern": r"for\s*\([^)]*\)\s*\{[^}]*\+\s*=\s*[\"']",
                "description": "String concatenation in loop is inefficient",
                "severity": "warning",
                "fix": "Use StringBuilder for string concatenation in loops"
            },
            {
                "name": "empty_catch_block",
                "type": PatternType.CODE_SMELL,
                "pattern": r"catch\s*\([^)]+\)\s*\{\s*\}",
                "description": "Empty catch block swallows exceptions silently",
                "severity": "error",
                "fix": "Log the exception or handle it appropriately"
            },
            {
                "name": "public_fields",
                "type": PatternType.CODE_SMELL,
                "pattern": r"public\s+(?!static\s+final)\w+\s+\w+\s*;",
                "description": "Public fields break encapsulation",
                "severity": "warning",
                "fix": "Use private fields with getter/setter methods"
            },
            {
                "name": "raw_types",
                "type": PatternType.CODE_SMELL,
                "pattern": r"\b(List|Map|Set|Collection)\s+\w+\s*=",
                "description": "Using raw types instead of parameterized generics",
                "severity": "warning",
                "fix": "Use parameterized types: List<String> instead of List"
            },
            {
                "name": "system_out_print",
                "type": PatternType.STYLE_VIOLATION,
                "pattern": r"System\.(out|err)\.(print|println)\s*\(",
                "description": "Use logging framework instead of System.out",
                "severity": "info",
                "fix": "Use a logging framework like SLF4J or Log4j"
            },
            {
                "name": "runtime_exception",
                "type": PatternType.ANTI_PATTERN,
                "pattern": r"throw\s+new\s+RuntimeException\s*\(",
                "description": "Throwing generic RuntimeException loses context",
                "severity": "warning",
                "fix": "Use or create specific exception types"
            },
            {
                "name": "sql_string_concat",
                "type": PatternType.SECURITY_RISK,
                "pattern": r"(executeQuery|prepareStatement)\s*\([^)]*\+",
                "description": "SQL query using string concatenation - SQL injection risk",
                "severity": "error",
                "fix": "Use PreparedStatement with parameterized queries"
            },
        ]

    def find_patterns(
        self,
        code: str,
        file_path: str,
        language: Language
    ) -> list[PatternMatch]:
        """
        Find all pattern matches in code.
        """
        matches = []
        lines = code.split("\n")

        patterns = self.patterns.get(language, [])

        for pattern_def in patterns:
            try:
                regex = re.compile(pattern_def["pattern"], re.MULTILINE)

                for i, line in enumerate(lines, 1):
                    for match in regex.finditer(line):
                        # Get context (surrounding lines)
                        start = max(0, i - 3)
                        end = min(len(lines), i + 2)
                        context = "\n".join(lines[start:end])

                        matches.append(PatternMatch(
                            pattern_name=pattern_def["name"],
                            pattern_type=pattern_def["type"],
                            file_path=file_path,
                            line_number=i,
                            column=match.start(),
                            matched_text=match.group(0),
                            context=context,
                            description=pattern_def["description"],
                            severity=pattern_def["severity"],
                            fix_suggestion=pattern_def.get("fix")
                        ))

            except re.error as e:
                logger.error(
                    "pattern_regex_error",
                    pattern_name=pattern_def["name"],
                    error=str(e)
                )

        return matches

    def find_duplicates(
        self,
        code: str,
        file_path: str,
        min_lines: int = 5
    ) -> list[tuple[int, int, int, int]]:
        """
        Find duplicate code blocks.

        Returns list of tuples: (start1, end1, start2, end2)
        """
        lines = code.split("\n")
        duplicates = []

        # Normalize lines (strip whitespace, ignore empty lines)
        normalized = [(i, line.strip()) for i, line in enumerate(lines, 1) if line.strip()]

        n = len(normalized)

        for i in range(n):
            for j in range(i + min_lines, n):
                # Check if sequences match
                match_len = 0
                while (i + match_len < j and
                       j + match_len < n and
                       normalized[i + match_len][1] == normalized[j + match_len][1]):
                    match_len += 1

                if match_len >= min_lines:
                    duplicates.append((
                        normalized[i][0],
                        normalized[i + match_len - 1][0],
                        normalized[j][0],
                        normalized[j + match_len - 1][0]
                    ))
                    # Skip ahead to avoid overlapping matches
                    break

        return duplicates

    def find_long_lines(
        self,
        code: str,
        file_path: str,
        max_length: int = 120
    ) -> list[PatternMatch]:
        """Find lines exceeding the maximum length."""
        matches = []

        for i, line in enumerate(code.split("\n"), 1):
            if len(line) > max_length:
                matches.append(PatternMatch(
                    pattern_name="line_too_long",
                    pattern_type=PatternType.STYLE_VIOLATION,
                    file_path=file_path,
                    line_number=i,
                    column=max_length,
                    matched_text=line,
                    context=line,
                    description=f"Line is {len(line)} characters (max: {max_length})",
                    severity="info",
                    fix_suggestion="Break the line into multiple shorter lines"
                ))

        return matches

    def find_todos(
        self,
        code: str,
        file_path: str
    ) -> list[PatternMatch]:
        """Find TODO, FIXME, XXX, and HACK comments."""
        matches = []
        patterns = [
            (r"#\s*(TODO|FIXME|XXX|HACK):?\s*(.*)$", "comment"),
            (r"//\s*(TODO|FIXME|XXX|HACK):?\s*(.*)$", "comment"),
            (r"/\*\s*(TODO|FIXME|XXX|HACK):?\s*(.*?)\*/", "block_comment"),
        ]

        for i, line in enumerate(code.split("\n"), 1):
            for pattern, _ in patterns:
                match = re.search(pattern, line, re.IGNORECASE)
                if match:
                    tag = match.group(1).upper()
                    message = match.group(2).strip()

                    matches.append(PatternMatch(
                        pattern_name=f"{tag.lower()}_comment",
                        pattern_type=PatternType.CODE_SMELL,
                        file_path=file_path,
                        line_number=i,
                        column=match.start(),
                        matched_text=match.group(0),
                        context=line,
                        description=f"{tag}: {message}" if message else tag,
                        severity="info" if tag == "TODO" else "warning"
                    ))

        return matches
