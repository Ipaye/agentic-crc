"""
Rule engine for loading and applying coding standards rules.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Callable

import yaml

from src.analysis.parser import Language
from src.config import get_settings
from src.utils.logging import get_logger

logger = get_logger("analysis.rules")


class RuleCategory(str, Enum):
    """Categories of code review rules."""
    STYLE = "style"
    QUALITY = "quality"
    SECURITY = "security"
    BEST_PRACTICES = "best_practices"
    PERFORMANCE = "performance"


class RuleSeverity(str, Enum):
    """Severity levels for rules."""
    ERROR = "error"
    WARNING = "warning"
    INFO = "info"
    SUGGESTION = "suggestion"


@dataclass
class Rule:
    """Definition of a code review rule."""

    id: str
    name: str
    description: str
    category: RuleCategory
    severity: RuleSeverity
    languages: list[Language]
    pattern: str | None = None  # Regex pattern
    anti_pattern: str | None = None  # Pattern that should NOT match
    message_template: str = ""
    suggestion_template: str | None = None
    documentation_url: str | None = None
    enabled: bool = True
    custom_checker: Callable | None = None

    def applies_to(self, language: Language) -> bool:
        """Check if rule applies to a language."""
        return language in self.languages or Language.UNKNOWN in self.languages


@dataclass
class RuleResult:
    """Result of applying a rule to code."""

    rule: Rule
    file_path: str
    line_number: int
    column: int = 0
    matched_text: str = ""
    message: str = ""
    suggestion: str | None = None
    confidence: float = 1.0
    context: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for serialization."""
        return {
            "rule_id": self.rule.id,
            "rule_name": self.rule.name,
            "category": self.rule.category.value,
            "severity": self.rule.severity.value,
            "file_path": self.file_path,
            "line_number": self.line_number,
            "column": self.column,
            "matched_text": self.matched_text,
            "message": self.message,
            "suggestion": self.suggestion,
            "confidence": self.confidence
        }


class RuleEngine:
    """
    Engine for loading and applying coding standards rules.
    """

    def __init__(self, rules_path: Path | None = None):
        """Initialize the rule engine."""
        self.settings = get_settings()
        self.rules_path = rules_path or self.settings.analysis.rules_path
        self.rules: dict[str, Rule] = {}
        self._load_builtin_rules()
        self._load_custom_rules()

        logger.info(
            "rule_engine_initialized",
            total_rules=len(self.rules),
            rules_path=str(self.rules_path)
        )

    def _load_builtin_rules(self) -> None:
        """Load built-in default rules."""
        builtin_rules = [
            # Style & Formatting Rules
            Rule(
                id="STYLE-001",
                name="snake_case_variables",
                description="Variable names should use snake_case in Python",
                category=RuleCategory.STYLE,
                severity=RuleSeverity.WARNING,
                languages=[Language.PYTHON],
                pattern=r"\b([a-z]+[A-Z][a-zA-Z]*)\s*=",
                message_template="Variable '{matched}' should use snake_case naming convention",
                suggestion_template="Consider renaming to: {snake_case}"
            ),
            Rule(
                id="STYLE-002",
                name="camelCase_variables",
                description="Variable names should use camelCase in JavaScript/TypeScript",
                category=RuleCategory.STYLE,
                severity=RuleSeverity.WARNING,
                languages=[Language.JAVASCRIPT, Language.TYPESCRIPT],
                pattern=r"(?:let|const|var)\s+([a-z]+_[a-z_]+)\s*=",
                message_template="Variable '{matched}' should use camelCase naming convention",
                suggestion_template="Consider renaming to: {camelCase}"
            ),
            Rule(
                id="STYLE-003",
                name="class_name_pascal_case",
                description="Class names should use PascalCase",
                category=RuleCategory.STYLE,
                severity=RuleSeverity.WARNING,
                languages=[Language.PYTHON, Language.JAVASCRIPT, Language.TYPESCRIPT, Language.JAVA],
                pattern=r"class\s+([a-z][a-zA-Z0-9_]*)",
                message_template="Class '{matched}' should use PascalCase naming",
                suggestion_template="Consider renaming to: {PascalCase}"
            ),

            # Code Quality Rules
            Rule(
                id="QUALITY-001",
                name="function_too_long",
                description="Functions should not exceed 50 lines",
                category=RuleCategory.QUALITY,
                severity=RuleSeverity.WARNING,
                languages=[Language.PYTHON, Language.JAVASCRIPT, Language.TYPESCRIPT, Language.JAVA],
                message_template="Function is {line_count} lines long (recommended: ≤50)",
                suggestion_template="Consider breaking this function into smaller, focused functions",
                custom_checker=lambda code, lang: None  # Handled by analyzer
            ),
            Rule(
                id="QUALITY-002",
                name="high_complexity",
                description="Function cyclomatic complexity should not exceed 10",
                category=RuleCategory.QUALITY,
                severity=RuleSeverity.WARNING,
                languages=[Language.PYTHON, Language.JAVASCRIPT, Language.TYPESCRIPT, Language.JAVA],
                message_template="Function has cyclomatic complexity of {complexity} (recommended: ≤10)",
                suggestion_template="Consider simplifying conditionals or extracting logic"
            ),
            Rule(
                id="QUALITY-003",
                name="deeply_nested_code",
                description="Avoid deeply nested code blocks (>3 levels)",
                category=RuleCategory.QUALITY,
                severity=RuleSeverity.WARNING,
                languages=[Language.PYTHON, Language.JAVASCRIPT, Language.TYPESCRIPT, Language.JAVA],
                pattern=r"^(\s{16,})\S",  # 4+ levels of indentation
                message_template="Code is nested {depth} levels deep (recommended: ≤3)",
                suggestion_template="Consider using early returns or extracting nested logic"
            ),
            Rule(
                id="QUALITY-004",
                name="magic_numbers",
                description="Avoid magic numbers, use named constants",
                category=RuleCategory.QUALITY,
                severity=RuleSeverity.INFO,
                languages=[Language.PYTHON, Language.JAVASCRIPT, Language.TYPESCRIPT, Language.JAVA],
                pattern=r"(?<![\w.])\b(\d{2,})\b(?!\s*[:\]])",  # Numbers with 2+ digits
                message_template="Magic number '{matched}' should be a named constant",
                suggestion_template="Define a constant: MEANINGFUL_NAME = {matched}"
            ),

            # Security Rules
            Rule(
                id="SECURITY-001",
                name="hardcoded_secret",
                description="Avoid hardcoded secrets, passwords, or API keys",
                category=RuleCategory.SECURITY,
                severity=RuleSeverity.ERROR,
                languages=[Language.PYTHON, Language.JAVASCRIPT, Language.TYPESCRIPT, Language.JAVA],
                pattern=r"(?i)(password|secret|api_key|apikey|token|auth)\s*[=:]\s*['\"][^'\"]{8,}['\"]",
                message_template="Potential hardcoded secret detected: {matched}",
                suggestion_template="Use environment variables or a secrets manager"
            ),
            Rule(
                id="SECURITY-002",
                name="sql_injection_risk",
                description="Potential SQL injection vulnerability",
                category=RuleCategory.SECURITY,
                severity=RuleSeverity.ERROR,
                languages=[Language.PYTHON, Language.JAVASCRIPT, Language.TYPESCRIPT, Language.JAVA],
                pattern=r"(?i)(execute|query|raw)\s*\([^)]*['\"].*%s.*['\"].*%|f['\"].*SELECT.*{",
                message_template="Potential SQL injection risk in query construction",
                suggestion_template="Use parameterized queries or an ORM",
                documentation_url="https://owasp.org/www-community/attacks/SQL_Injection"
            ),
            Rule(
                id="SECURITY-003",
                name="eval_usage",
                description="Avoid using eval() or similar dynamic code execution",
                category=RuleCategory.SECURITY,
                severity=RuleSeverity.ERROR,
                languages=[Language.PYTHON, Language.JAVASCRIPT, Language.TYPESCRIPT],
                pattern=r"\b(eval|exec)\s*\(",
                message_template="Use of {matched} can be a security risk",
                suggestion_template="Consider using safer alternatives like ast.literal_eval or JSON parsing"
            ),

            # Best Practices Rules
            Rule(
                id="BEST-001",
                name="missing_docstring",
                description="Public functions should have docstrings",
                category=RuleCategory.BEST_PRACTICES,
                severity=RuleSeverity.INFO,
                languages=[Language.PYTHON],
                anti_pattern=r"def\s+[^_]\w+\s*\([^)]*\):[^\n]*\n\s*['\"]['\"]['\"]",
                message_template="Function '{name}' is missing a docstring",
                suggestion_template="Add a docstring describing the function's purpose and parameters"
            ),
            Rule(
                id="BEST-002",
                name="unused_import",
                description="Remove unused imports",
                category=RuleCategory.BEST_PRACTICES,
                severity=RuleSeverity.INFO,
                languages=[Language.PYTHON, Language.JAVASCRIPT, Language.TYPESCRIPT],
                message_template="Import '{name}' appears to be unused",
                suggestion_template="Remove the unused import to keep the code clean"
            ),
            Rule(
                id="BEST-003",
                name="broad_exception",
                description="Avoid catching broad exceptions",
                category=RuleCategory.BEST_PRACTICES,
                severity=RuleSeverity.WARNING,
                languages=[Language.PYTHON],
                pattern=r"except\s*(?:Exception|BaseException)?\s*:",
                message_template="Catching broad exceptions can hide bugs",
                suggestion_template="Catch specific exception types instead"
            ),
            Rule(
                id="BEST-004",
                name="console_log_left",
                description="Remove debug console.log statements",
                category=RuleCategory.BEST_PRACTICES,
                severity=RuleSeverity.WARNING,
                languages=[Language.JAVASCRIPT, Language.TYPESCRIPT],
                pattern=r"console\.(log|debug|info)\s*\(",
                message_template="Debug console.{method} statement should be removed",
                suggestion_template="Remove or replace with proper logging"
            ),
            Rule(
                id="BEST-005",
                name="print_statement",
                description="Remove debug print statements",
                category=RuleCategory.BEST_PRACTICES,
                severity=RuleSeverity.INFO,
                languages=[Language.PYTHON],
                pattern=r"^\s*print\s*\(",
                message_template="Debug print statement should be removed",
                suggestion_template="Use proper logging instead: logging.debug()"
            ),
        ]

        for rule in builtin_rules:
            self.rules[rule.id] = rule

    def _load_custom_rules(self) -> None:
        """Load custom rules from YAML files."""
        if not self.rules_path.exists():
            logger.info("rules_path_not_found", path=str(self.rules_path))
            return

        for yaml_file in self.rules_path.glob("*.yaml"):
            try:
                self._load_rules_from_yaml(yaml_file)
            except Exception as e:
                logger.error(
                    "failed_to_load_rules",
                    file=str(yaml_file),
                    error=str(e)
                )

    def _load_rules_from_yaml(self, yaml_file: Path) -> None:
        """Load rules from a YAML file."""
        with open(yaml_file) as f:
            data = yaml.safe_load(f)

        if not data or "rules" not in data:
            return

        for rule_data in data["rules"]:
            try:
                # Parse languages
                languages = [
                    Language(lang) for lang in rule_data.get("languages", ["unknown"])
                ]

                rule = Rule(
                    id=rule_data["id"],
                    name=rule_data["name"],
                    description=rule_data.get("description", ""),
                    category=RuleCategory(rule_data.get("category", "best_practices")),
                    severity=RuleSeverity(rule_data.get("severity", "warning")),
                    languages=languages,
                    pattern=rule_data.get("pattern"),
                    anti_pattern=rule_data.get("anti_pattern"),
                    message_template=rule_data.get("message_template", ""),
                    suggestion_template=rule_data.get("suggestion_template"),
                    documentation_url=rule_data.get("documentation_url"),
                    enabled=rule_data.get("enabled", True)
                )

                self.rules[rule.id] = rule
                logger.debug("custom_rule_loaded", rule_id=rule.id)

            except Exception as e:
                logger.warning(
                    "failed_to_parse_rule",
                    rule_data=rule_data,
                    error=str(e)
                )

    def get_rules_for_language(self, language: Language) -> list[Rule]:
        """Get all enabled rules that apply to a specific language."""
        return [
            rule for rule in self.rules.values()
            if rule.enabled and rule.applies_to(language)
        ]

    def get_rules_by_category(self, category: RuleCategory) -> list[Rule]:
        """Get all enabled rules in a category."""
        return [
            rule for rule in self.rules.values()
            if rule.enabled and rule.category == category
        ]

    def get_all_rules(self) -> list[Rule]:
        """Get all enabled rules."""
        return [rule for rule in self.rules.values() if rule.enabled]

    def load_rules_from_directory(self, directory: Path) -> None:
        """Load rules from YAML files in a directory."""
        if not directory.exists():
            return
        for yaml_file in directory.glob("*.yaml"):
            self._load_rules_from_yaml(yaml_file)
        for yaml_file in directory.glob("*.yml"):
            self._load_rules_from_yaml(yaml_file)

    def apply_rule(
        self,
        rule: Rule,
        code: str,
        file_path: str,
        language: Language
    ) -> list[RuleResult]:
        """
        Apply a single rule to code and return all violations.
        """
        if not rule.applies_to(language):
            return []

        results = []
        lines = code.split("\n")

        # Pattern-based matching
        if rule.pattern:
            pattern = re.compile(rule.pattern, re.MULTILINE)
            for i, line in enumerate(lines, 1):
                for match in pattern.finditer(line):
                    matched_text = match.group(1) if match.groups() else match.group(0)
                    if matched_text is None:
                        matched_text = match.group(0)

                    # Build a dict with all named groups + standard keys
                    fmt_kwargs = {
                        "matched": matched_text,
                        "line": i,
                        "method": matched_text,
                        "depth": matched_text,
                        "name": matched_text,
                        "line_count": matched_text,
                        "complexity": matched_text,
                    }
                    # Override with any named groups from the regex
                    fmt_kwargs.update(match.groupdict())

                    # Format message
                    try:
                        message = rule.message_template.format(**fmt_kwargs)
                    except (KeyError, IndexError):
                        message = rule.message_template

                    # Format suggestion if available
                    suggestion = None
                    if rule.suggestion_template:
                        suggestion = self._format_suggestion(
                            rule.suggestion_template,
                            matched_text,
                            language
                        )

                    results.append(RuleResult(
                        rule=rule,
                        file_path=file_path,
                        line_number=i,
                        column=match.start(),
                        matched_text=matched_text,
                        message=message,
                        suggestion=suggestion
                    ))

        # Anti-pattern matching (rule triggers when pattern is NOT found)
        if rule.anti_pattern and not rule.pattern:
            pattern = re.compile(rule.anti_pattern, re.MULTILINE)
            if not pattern.search(code):
                results.append(RuleResult(
                    rule=rule,
                    file_path=file_path,
                    line_number=1,
                    message=rule.message_template
                ))

        return results

    def _format_suggestion(
        self,
        template: str,
        matched_text: str,
        language: Language
    ) -> str:
        """Format a suggestion with appropriate naming conventions."""
        if not matched_text or not matched_text.strip():
            return template

        # Convert matched text to different naming conventions
        words = re.split(r"[_\s]+|(?=[A-Z])", matched_text)
        words = [w.lower() for w in words if w]

        if not words:
            return template.format(matched=matched_text)

        snake_case = "_".join(words)
        camel_case = words[0] + "".join(w.title() for w in words[1:])
        pascal_case = "".join(w.title() for w in words)

        try:
            return template.format(
                matched=matched_text,
                snake_case=snake_case,
                camelCase=camel_case,
                PascalCase=pascal_case
            )
        except (KeyError, IndexError):
            return template

    def apply_all_rules(
        self,
        code: str,
        file_path: str,
        language: Language
    ) -> list[RuleResult]:
        """
        Apply all applicable rules to code.
        """
        results = []

        for rule in self.get_rules_for_language(language):
            try:
                rule_results = self.apply_rule(rule, code, file_path, language)
                results.extend(rule_results)
            except Exception as e:
                logger.error(
                    "rule_application_failed",
                    rule_id=rule.id,
                    file=file_path,
                    error=str(e)
                )

        # Sort by line number
        results.sort(key=lambda r: r.line_number)

        return results
