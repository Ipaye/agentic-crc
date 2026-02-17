"""
AST Parser using tree-sitter for multiple languages.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from enum import Enum

from src.utils.logging import get_logger

logger = get_logger("analysis.parser")


class Language(str, Enum):
    """Supported programming languages."""
    PYTHON = "python"
    JAVASCRIPT = "javascript"
    TYPESCRIPT = "typescript"
    JAVA = "java"
    GO = "go"
    RUST = "rust"
    UNKNOWN = "unknown"


@dataclass
class ASTNode:
    """Represents a node in the AST."""
    type: str
    text: str
    start_line: int
    end_line: int
    start_col: int
    end_col: int
    children: list[ASTNode] = field(default_factory=list)
    parent: ASTNode | None = None

    @property
    def line_count(self) -> int:
        """Number of lines this node spans."""
        return self.end_line - self.start_line + 1


@dataclass
class FunctionInfo:
    """Information about a function/method."""
    name: str
    start_line: int
    end_line: int
    parameters: list[str]
    complexity: int = 1  # Cyclomatic complexity
    nested_depth: int = 0
    body_lines: int = 0
    docstring: str | None = None


@dataclass
class ClassInfo:
    """Information about a class."""
    name: str
    start_line: int
    end_line: int
    methods: list[FunctionInfo] = field(default_factory=list)
    attributes: list[str] = field(default_factory=list)
    bases: list[str] = field(default_factory=list)


@dataclass
class ImportInfo:
    """Information about an import statement."""
    module: str
    names: list[str]
    line: int
    is_from_import: bool = False


class ASTParser:
    """
    AST Parser that provides language-agnostic code analysis.
    Uses regex-based fallback when tree-sitter is not available.
    """

    # Language detection by extension
    EXTENSION_MAP = {
        "py": Language.PYTHON,
        "js": Language.JAVASCRIPT,
        "jsx": Language.JAVASCRIPT,
        "ts": Language.TYPESCRIPT,
        "tsx": Language.TYPESCRIPT,
        "java": Language.JAVA,
        "go": Language.GO,
        "rs": Language.RUST,
    }

    def __init__(self):
        """Initialize the parser."""
        self._tree_sitter_available = False
        self._try_init_tree_sitter()

    def _try_init_tree_sitter(self):
        """Try to initialize tree-sitter parsers."""
        try:
            import tree_sitter_javascript
            import tree_sitter_python
            from tree_sitter import Language as TSLanguage
            from tree_sitter import Parser

            self._tree_sitter_available = True
            self._ts_parser = Parser()

            # Load languages
            self._languages = {
                Language.PYTHON: TSLanguage(tree_sitter_python.language()),
                Language.JAVASCRIPT: TSLanguage(tree_sitter_javascript.language()),
            }

            logger.info("tree_sitter_initialized", languages=list(self._languages.keys()))

        except ImportError as e:
            logger.warning(
                "tree_sitter_not_available",
                error=str(e),
                fallback="regex"
            )
            self._tree_sitter_available = False

    def detect_language(self, filename: str) -> Language:
        """Detect the programming language from filename."""
        ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
        return self.EXTENSION_MAP.get(ext, Language.UNKNOWN)

    def parse(self, code: str, language: Language) -> ASTNode | None:
        """
        Parse code and return the AST root node.
        """
        if self._tree_sitter_available and language in self._languages:
            return self._parse_tree_sitter(code, language)

        # Fallback to regex-based parsing
        return self._parse_regex(code, language)

    def _parse_tree_sitter(self, code: str, language: Language) -> ASTNode | None:
        """Parse code using tree-sitter."""
        try:
            self._ts_parser.language = self._languages[language]
            tree = self._ts_parser.parse(bytes(code, "utf8"))
            return self._convert_ts_node(tree.root_node, code)
        except Exception as e:
            logger.error("tree_sitter_parse_error", error=str(e))
            return self._parse_regex(code, language)

    def _convert_ts_node(self, ts_node, code: str) -> ASTNode:
        """Convert a tree-sitter node to our ASTNode format."""
        node = ASTNode(
            type=ts_node.type,
            text=code[ts_node.start_byte:ts_node.end_byte],
            start_line=ts_node.start_point[0] + 1,
            end_line=ts_node.end_point[0] + 1,
            start_col=ts_node.start_point[1],
            end_col=ts_node.end_point[1]
        )

        for child in ts_node.children:
            child_node = self._convert_ts_node(child, code)
            child_node.parent = node
            node.children.append(child_node)

        return node

    def _parse_regex(self, code: str, language: Language) -> ASTNode:
        """
        Fallback regex-based parsing for basic structure extraction.
        """
        lines = code.split("\n")
        root = ASTNode(
            type="module",
            text=code,
            start_line=1,
            end_line=len(lines),
            start_col=0,
            end_col=len(lines[-1]) if lines else 0
        )

        # This is a simplified parser - real parsing would use tree-sitter
        return root

    def extract_functions(
        self,
        code: str,
        language: Language
    ) -> list[FunctionInfo]:
        """
        Extract all function/method definitions from code.
        """
        functions = []
        lines = code.split("\n")

        if language == Language.PYTHON:
            functions = self._extract_python_functions(code, lines)
        elif language in (Language.JAVASCRIPT, Language.TYPESCRIPT):
            functions = self._extract_js_functions(code, lines)
        elif language == Language.JAVA:
            functions = self._extract_java_methods(code, lines)
        else:
            # Generic function extraction
            functions = self._extract_generic_functions(code, lines)

        # Calculate complexity for each function
        for func in functions:
            func_code = "\n".join(lines[func.start_line - 1:func.end_line])
            func.complexity = self.calculate_complexity(func_code, language)
            func.body_lines = func.end_line - func.start_line - 1

        return functions

    def _extract_python_functions(
        self,
        code: str,
        lines: list[str]
    ) -> list[FunctionInfo]:
        """Extract Python function definitions."""
        functions = []

        # Pattern for function definitions
        func_pattern = re.compile(
            r"^\s*(async\s+)?def\s+(\w+)\s*\(([^)]*)\)\s*(?:->.*?)?:"
        )

        current_indent = -1
        current_func = None

        for i, line in enumerate(lines, 1):
            match = func_pattern.match(line)
            if match:
                # Save previous function
                if current_func:
                    current_func.end_line = i - 1
                    functions.append(current_func)

                # Start new function
                indent_level = len(line) - len(line.lstrip())
                params = [p.strip().split(":")[0].split("=")[0].strip()
                         for p in match.group(3).split(",") if p.strip()]

                current_func = FunctionInfo(
                    name=match.group(2),
                    start_line=i,
                    end_line=len(lines),
                    parameters=params,
                    nested_depth=indent_level // 4
                )
                current_indent = indent_level

            elif current_func and line.strip():
                # Check if we've exited the function
                line_indent = len(line) - len(line.lstrip())
                if line_indent <= current_indent and not line.strip().startswith("#"):
                    current_func.end_line = i - 1
                    functions.append(current_func)
                    current_func = None

        # Don't forget the last function
        if current_func:
            current_func.end_line = len(lines)
            functions.append(current_func)

        return functions

    def _extract_js_functions(
        self,
        code: str,
        lines: list[str]
    ) -> list[FunctionInfo]:
        """Extract JavaScript/TypeScript function definitions."""
        functions = []

        # Patterns for different function syntaxes
        patterns = [
            # Regular function
            re.compile(r"(?:async\s+)?function\s+(\w+)\s*\(([^)]*)\)"),
            # Arrow function assigned to variable
            re.compile(r"(?:const|let|var)\s+(\w+)\s*=\s*(?:async\s+)?\(([^)]*)\)\s*=>"),
            # Method in class or object
            re.compile(r"^\s*(?:async\s+)?(\w+)\s*\(([^)]*)\)\s*{"),
        ]

        brace_depth = 0
        current_func = None

        for i, line in enumerate(lines, 1):
            for pattern in patterns:
                match = pattern.search(line)
                if match and not current_func:
                    params = [p.strip().split(":")[0].split("=")[0].strip()
                             for p in match.group(2).split(",") if p.strip()]

                    current_func = FunctionInfo(
                        name=match.group(1),
                        start_line=i,
                        end_line=len(lines),
                        parameters=params
                    )
                    brace_depth = line.count("{") - line.count("}")
                    break

            if current_func and not any(p.search(line) for p in patterns):
                brace_depth += line.count("{") - line.count("}")
                if brace_depth <= 0:
                    current_func.end_line = i
                    functions.append(current_func)
                    current_func = None
                    brace_depth = 0

        if current_func:
            functions.append(current_func)

        return functions

    def _extract_java_methods(
        self,
        code: str,
        lines: list[str]
    ) -> list[FunctionInfo]:
        """Extract Java method definitions."""
        functions = []

        # Pattern for method definitions
        method_pattern = re.compile(
            r"(?:public|private|protected|static|\s)+[\w<>\[\]]+\s+(\w+)\s*\(([^)]*)\)\s*(?:throws\s+[\w,\s]+)?\s*{"
        )

        brace_depth = 0
        current_func = None

        for i, line in enumerate(lines, 1):
            match = method_pattern.search(line)
            if match and not current_func:
                params = [p.strip().split()[-1]
                         for p in match.group(2).split(",") if p.strip()]

                current_func = FunctionInfo(
                    name=match.group(1),
                    start_line=i,
                    end_line=len(lines),
                    parameters=params
                )
                brace_depth = line.count("{") - line.count("}")

            elif current_func:
                brace_depth += line.count("{") - line.count("}")
                if brace_depth <= 0:
                    current_func.end_line = i
                    functions.append(current_func)
                    current_func = None

        if current_func:
            functions.append(current_func)

        return functions

    def _extract_generic_functions(
        self,
        code: str,
        lines: list[str]
    ) -> list[FunctionInfo]:
        """Generic function extraction for unknown languages."""
        # Basic pattern that might catch most function definitions
        pattern = re.compile(r"(?:func|def|function|fn)\s+(\w+)")
        functions = []

        for i, line in enumerate(lines, 1):
            match = pattern.search(line)
            if match:
                functions.append(FunctionInfo(
                    name=match.group(1),
                    start_line=i,
                    end_line=i + 10,  # Rough estimate
                    parameters=[]
                ))

        return functions

    def extract_classes(
        self,
        code: str,
        language: Language
    ) -> list[ClassInfo]:
        """Extract class definitions from code."""
        classes = []
        lines = code.split("\n")

        if language == Language.PYTHON:
            classes = self._extract_python_classes(code, lines)
        elif language in (Language.JAVASCRIPT, Language.TYPESCRIPT):
            classes = self._extract_js_classes(code, lines)
        elif language == Language.JAVA:
            classes = self._extract_java_classes(code, lines)

        return classes

    def _extract_python_classes(
        self,
        code: str,
        lines: list[str]
    ) -> list[ClassInfo]:
        """Extract Python class definitions."""
        classes = []
        class_pattern = re.compile(r"^\s*class\s+(\w+)(?:\s*\(([^)]*)\))?\s*:")

        current_class = None
        class_indent = -1

        for i, line in enumerate(lines, 1):
            match = class_pattern.match(line)
            if match:
                if current_class:
                    current_class.end_line = i - 1
                    classes.append(current_class)

                bases = []
                if match.group(2):
                    bases = [b.strip() for b in match.group(2).split(",")]

                current_class = ClassInfo(
                    name=match.group(1),
                    start_line=i,
                    end_line=len(lines),
                    bases=bases
                )
                class_indent = len(line) - len(line.lstrip())

            elif current_class and line.strip():
                line_indent = len(line) - len(line.lstrip())
                if line_indent <= class_indent:
                    current_class.end_line = i - 1
                    classes.append(current_class)
                    current_class = None

        if current_class:
            classes.append(current_class)

        return classes

    def _extract_js_classes(
        self,
        code: str,
        lines: list[str]
    ) -> list[ClassInfo]:
        """Extract JavaScript/TypeScript class definitions."""
        classes = []
        class_pattern = re.compile(r"class\s+(\w+)(?:\s+extends\s+(\w+))?")

        brace_depth = 0
        current_class = None

        for i, line in enumerate(lines, 1):
            match = class_pattern.search(line)
            if match and not current_class:
                bases = [match.group(2)] if match.group(2) else []
                current_class = ClassInfo(
                    name=match.group(1),
                    start_line=i,
                    end_line=len(lines),
                    bases=bases
                )
                brace_depth = line.count("{") - line.count("}")

            elif current_class:
                brace_depth += line.count("{") - line.count("}")
                if brace_depth <= 0:
                    current_class.end_line = i
                    classes.append(current_class)
                    current_class = None

        if current_class:
            classes.append(current_class)

        return classes

    def _extract_java_classes(
        self,
        code: str,
        lines: list[str]
    ) -> list[ClassInfo]:
        """Extract Java class definitions."""
        classes = []
        class_pattern = re.compile(
            r"(?:public|private|protected|abstract|final|\s)*class\s+(\w+)"
            r"(?:\s+extends\s+(\w+))?(?:\s+implements\s+([\w,\s]+))?"
        )

        brace_depth = 0
        current_class = None

        for i, line in enumerate(lines, 1):
            match = class_pattern.search(line)
            if match and not current_class:
                bases = []
                if match.group(2):
                    bases.append(match.group(2))
                if match.group(3):
                    bases.extend([b.strip() for b in match.group(3).split(",")])

                current_class = ClassInfo(
                    name=match.group(1),
                    start_line=i,
                    end_line=len(lines),
                    bases=bases
                )
                brace_depth = line.count("{") - line.count("}")

            elif current_class:
                brace_depth += line.count("{") - line.count("}")
                if brace_depth <= 0:
                    current_class.end_line = i
                    classes.append(current_class)
                    current_class = None

        if current_class:
            classes.append(current_class)

        return classes

    def calculate_complexity(
        self,
        code: str,
        language: Language
    ) -> int:
        """
        Calculate cyclomatic complexity of code.

        Complexity increases with:
        - Conditional statements (if, elif, else)
        - Loops (for, while)
        - Exception handlers (try, catch)
        - Boolean operators (and, or)
        """
        complexity = 1  # Base complexity

        # Patterns that increase complexity
        if language == Language.PYTHON:
            patterns = [
                r"\bif\b", r"\belif\b", r"\bfor\b", r"\bwhile\b",
                r"\band\b", r"\bor\b", r"\bexcept\b", r"\bwith\b"
            ]
        elif language in (Language.JAVASCRIPT, Language.TYPESCRIPT):
            patterns = [
                r"\bif\s*\(", r"\belse\s+if\b", r"\bfor\s*\(", r"\bwhile\s*\(",
                r"\bcase\s+", r"\bcatch\s*\(", r"&&", r"\|\|", r"\?\s*"
            ]
        elif language == Language.JAVA:
            patterns = [
                r"\bif\s*\(", r"\belse\s+if\b", r"\bfor\s*\(", r"\bwhile\s*\(",
                r"\bcase\s+", r"\bcatch\s*\(", r"&&", r"\|\|", r"\?\s*"
            ]
        else:
            patterns = [
                r"\bif\b", r"\bfor\b", r"\bwhile\b", r"\bcase\b",
                r"&&", r"\|\|"
            ]

        for pattern in patterns:
            complexity += len(re.findall(pattern, code))

        return complexity

    def extract_imports(
        self,
        code: str,
        language: Language
    ) -> list[ImportInfo]:
        """Extract import statements from code."""
        imports = []
        lines = code.split("\n")

        if language == Language.PYTHON:
            import_pattern = re.compile(r"^import\s+([\w.]+)")
            from_pattern = re.compile(r"^from\s+([\w.]+)\s+import\s+(.+)")

            for i, line in enumerate(lines, 1):
                line = line.strip()
                match = from_pattern.match(line)
                if match:
                    names = [n.strip().split(" as ")[0]
                            for n in match.group(2).split(",")]
                    imports.append(ImportInfo(
                        module=match.group(1),
                        names=names,
                        line=i,
                        is_from_import=True
                    ))
                else:
                    match = import_pattern.match(line)
                    if match:
                        imports.append(ImportInfo(
                            module=match.group(1),
                            names=[match.group(1).split(".")[-1]],
                            line=i,
                            is_from_import=False
                        ))

        elif language in (Language.JAVASCRIPT, Language.TYPESCRIPT):
            import_pattern = re.compile(
                r"import\s+(?:{([^}]+)}|(\w+))\s+from\s+['\"]([^'\"]+)['\"]"
            )
            require_pattern = re.compile(
                r"(?:const|let|var)\s+(?:{([^}]+)}|(\w+))\s*=\s*require\(['\"]([^'\"]+)['\"]\)"
            )

            for i, line in enumerate(lines, 1):
                for pattern in [import_pattern, require_pattern]:
                    match = pattern.search(line)
                    if match:
                        if match.group(1):
                            names = [n.strip().split(" as ")[0]
                                    for n in match.group(1).split(",")]
                        else:
                            names = [match.group(2)]

                        imports.append(ImportInfo(
                            module=match.group(3),
                            names=names,
                            line=i,
                            is_from_import=True
                        ))
                        break

        return imports
