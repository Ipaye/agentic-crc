"""
Refactoring Agent - Applies automated code fixes and refactoring.

Receives handoff from Code Review Agent and applies fixes for:
- Code style issues
- Simple security fixes
- Code smell removal
- Method extraction and simplification
"""
from __future__ import annotations

import ast
import re
from dataclasses import dataclass, field

from ..github.client import GitHubClient
from ..github.models import FileChange, ReviewComment
from .state import AgentState, AgentWorkItem, HandoffDecision


@dataclass
class RefactoringResult:
    """Result of a refactoring operation."""
    file_path: str
    original_content: str
    refactored_content: str
    changes_made: list[str] = field(default_factory=list)
    success: bool = True
    error: str | None = None


@dataclass
class CommitResult:
    """Result of committing changes."""
    sha: str | None = None
    success: bool = True
    error: str | None = None
    files_changed: list[str] = field(default_factory=list)


class RefactoringAgent:
    """
    Agent responsible for applying automated code fixes and refactoring.

    Capabilities:
    - Auto-fix style issues (trailing whitespace, line length)
    - Fix simple security issues (remove hardcoded secrets pattern)
    - Apply common refactoring patterns
    - Create commits with clear explanations
    """

    def __init__(
        self,
        github_client: GitHubClient | None = None,
        state: AgentState | None = None
    ):
        self.github_client = github_client
        self.state = state or AgentState(session_id="refactoring")
        self.refactoring_results: list[RefactoringResult] = []

    def process_handoff(
        self,
        handoff: HandoffDecision,
        file_changes: list[FileChange],
        comments: list[ReviewComment]
    ) -> list[RefactoringResult]:
        """
        Process a handoff from the Code Review Agent.

        Args:
            handoff: HandoffDecision with delegation details
            file_changes: Files to potentially refactor
            comments: Review comments identifying issues

        Returns:
            List of RefactoringResult for each processed file
        """
        self.state.update_context("handoff", handoff.__dict__)
        self.state.create_checkpoint("pre_refactoring")

        results = []

        # Filter to priority files if specified
        files_to_process = file_changes
        if handoff.priority_files:
            priority_set = set(handoff.priority_files)
            files_to_process = [
                f for f in file_changes
                if f.filename in priority_set
            ]

        # Group comments by file
        comments_by_file: dict[str, list[ReviewComment]] = {}
        for comment in comments:
            if comment.file_path:
                if comment.file_path not in comments_by_file:
                    comments_by_file[comment.file_path] = []
                comments_by_file[comment.file_path].append(comment)

        for file_change in files_to_process:
            if not file_change.patch:
                continue

            file_comments = comments_by_file.get(file_change.filename, [])

            # Create work item for tracking
            work_item = AgentWorkItem(
                item_id=f"refactor_{file_change.filename}",
                file_path=file_change.filename,
                task_type="refactor",
                data={"comments": [c.body for c in file_comments]}
            )
            self.state.add_work_item(work_item)

            try:
                result = self._refactor_file(
                    file_change,
                    file_comments,
                    handoff.reasons
                )
                results.append(result)

                if result.success and result.changes_made:
                    self.state.complete_work_item(
                        work_item.item_id,
                        {"changes": result.changes_made}
                    )
            except Exception as e:
                results.append(RefactoringResult(
                    file_path=file_change.filename,
                    original_content="",
                    refactored_content="",
                    success=False,
                    error=str(e)
                ))

        self.refactoring_results = results
        return results

    def _refactor_file(
        self,
        file_change: FileChange,
        comments: list[ReviewComment],
        handoff_reasons: list[str]
    ) -> RefactoringResult:
        """Apply refactoring to a single file."""
        content = self._reconstruct_content(file_change)
        if not content.strip():
            return RefactoringResult(
                file_path=file_change.filename,
                original_content="",
                refactored_content="",
                changes_made=[],
                success=False,
                error="Missing full file content for safe refactor"
            )
        original = content
        changes_made = []

        # Determine which fixes to apply based on comments and reasons
        reasons_text = ' '.join(handoff_reasons).lower()
        comments_text = ' '.join(c.body.lower() for c in comments)

        # Style fixes
        if any(kw in reasons_text for kw in ['style', 'whitespace', 'formatting']):
            content, style_changes = self._apply_style_fixes(content, file_change.filename)
            changes_made.extend(style_changes)

        # Security fixes
        if any(kw in reasons_text for kw in ['security', 'injection', 'credential', 'secret']):
            content, security_changes = self._apply_security_fixes(content, file_change.filename)
            changes_made.extend(security_changes)

        # Code quality fixes
        if any(kw in reasons_text for kw in ['quality', 'smell', 'complexity', 'refactor']):
            content, quality_changes = self._apply_quality_fixes(content, file_change.filename)
            changes_made.extend(quality_changes)

        # Apply fixes based on specific comments
        for comment in comments:
            comment_lower = comment.body.lower()

            if "unused import" in comment_lower:
                content, import_changes = self._remove_unused_imports(content, file_change.filename)
                changes_made.extend(import_changes)

            if "too long" in comment_lower or "line length" in comment_lower:
                content, length_changes = self._fix_long_lines(content, file_change.filename)
                changes_made.extend(length_changes)

            if "magic number" in comment_lower or "constant" in comment_lower:
                content, const_changes = self._extract_constants(content, file_change.filename)
                changes_made.extend(const_changes)

            if "duplicate" in comment_lower:
                content, dedup_changes = self._remove_duplicate_code(content, file_change.filename)
                changes_made.extend(dedup_changes)

        return RefactoringResult(
            file_path=file_change.filename,
            original_content=original,
            refactored_content=content,
            changes_made=changes_made,
            success=True
        )

    def _reconstruct_content(self, file_change: FileChange) -> str:
        """Reconstruct file content from patch."""
        # Prefer full file content when available
        if file_change.content:
            return file_change.content

        # Fallback to patch-only reconstruction
        if not file_change.patch:
            return ""

        lines = []
        for line in file_change.patch.split('\n'):
            if line.startswith('+') and not line.startswith('+++'):
                lines.append(line[1:])
            elif not line.startswith('-') and not line.startswith('@@'):
                lines.append(line)

        return '\n'.join(lines)

    def _apply_style_fixes(self, content: str, filename: str) -> tuple[str, list[str]]:
        """Apply common style fixes."""
        changes = []

        # Remove trailing whitespace
        new_content = re.sub(r'[ \t]+$', '', content, flags=re.MULTILINE)
        if new_content != content:
            changes.append("Removed trailing whitespace")
            content = new_content

        # Ensure file ends with newline
        if content and not content.endswith('\n'):
            content += '\n'
            changes.append("Added final newline")

        # Remove multiple blank lines (keep max 2)
        new_content = re.sub(r'\n{4,}', '\n\n\n', content)
        if new_content != content:
            changes.append("Reduced consecutive blank lines")
            content = new_content

        # Python-specific: fix spacing around operators
        if filename.endswith('.py'):
            # Add space after comma if missing
            new_content = re.sub(r',([^\s\n])', r', \1', content)
            if new_content != content:
                changes.append("Fixed spacing after commas")
                content = new_content

        return content, changes

    def _apply_security_fixes(self, content: str, filename: str) -> tuple[str, list[str]]:
        """Apply security fixes with actual code transformations."""
        changes = []

        if not filename.endswith('.py'):
            return content, changes

        # 1. Replace hardcoded credentials with environment variables
        credential_pattern = r'(\w*(?:password|passwd|pwd|secret|api_key|apikey|token)\w*)\s*=\s*["\']([^"\']+)["\']'

        def replace_credential(match):
            var_name = match.group(1)
            env_var = var_name.upper()
            return f'{var_name} = os.environ.get("{env_var}", "")'

        if re.search(credential_pattern, content, re.IGNORECASE):
            # Add os import if needed
            if 'import os' not in content:
                content = 'import os\n' + content
                changes.append("Added os import for environment variables")

            new_content = re.sub(credential_pattern, replace_credential, content, flags=re.IGNORECASE)
            if new_content != content:
                changes.append("Replaced hardcoded credentials with environment variables")
                content = new_content

        # Replace API keys (sk-xxx, pk_xxx, rk_xxx patterns)
        api_key_pattern = r'["\'](?:sk-|pk_|rk_)[a-zA-Z0-9]{20,}["\']'
        if re.search(api_key_pattern, content):
            if 'import os' not in content:
                content = 'import os\n' + content
                changes.append("Added os import for environment variables")

            new_content = re.sub(api_key_pattern, 'os.environ.get("API_KEY", "")', content)
            if new_content != content:
                changes.append("Replaced hardcoded API key with environment variable")
                content = new_content

        # 2. Replace dangerous eval() with ast.literal_eval()
        eval_pattern = r'\beval\s*\(\s*([^)]+)\s*\)'
        if re.search(eval_pattern, content):
            if 'import ast' not in content and 'from ast import' not in content:
                # Add at top after other imports
                lines = content.split('\n')
                import_idx = 0
                for i, line in enumerate(lines):
                    if line.startswith('import ') or line.startswith('from '):
                        import_idx = i + 1
                lines.insert(import_idx, 'import ast')
                content = '\n'.join(lines)
                changes.append("Added ast import for safe evaluation")

            new_content = re.sub(eval_pattern, r'ast.literal_eval(\1)', content)
            if new_content != content:
                changes.append("Replaced eval() with ast.literal_eval() for safety")
                content = new_content

        # 3. Fix SQL injection - replace string formatting with parameterized queries
        sql_injection_patterns = [
            # cursor.execute("SELECT * FROM users WHERE id = " + user_id)
            (r'(execute\s*\(\s*["\'][^"\']*(?:SELECT|INSERT|UPDATE|DELETE)[^"\']*["\'])\s*\+\s*(\w+)',
             r'\1, (\2,)'),
            # cursor.execute(f"SELECT * FROM users WHERE id = {user_id}")
            (r'execute\s*\(\s*f["\']([^"\']*)\{(\w+)\}([^"\']*)["\']',
             r'execute("\1?\3", (\2,)'),
            # cursor.execute("SELECT * FROM users WHERE id = %s" % user_id)
            (r'execute\s*\(\s*["\']([^"\']+)["\']\s*%\s*(\w+)\s*\)',
             r'execute("\1", (\2,))'),
        ]

        for pattern, replacement in sql_injection_patterns:
            new_content = re.sub(pattern, replacement, content)
            if new_content != content:
                changes.append("Fixed SQL injection vulnerability with parameterized query")
                content = new_content

        # 4. Replace subprocess shell=True with shell=False and list args
        shell_true_pattern = r'subprocess\.(run|call|Popen)\s*\(\s*(["\'][^"\']+["\'])\s*,\s*shell\s*=\s*True'
        if re.search(shell_true_pattern, content):
            def replace_shell_true(match):
                func = match.group(1)
                cmd = match.group(2).strip('"\'')
                args = cmd.split()
                args_str = str(args)
                return f'subprocess.{func}({args_str}, shell=False'

            new_content = re.sub(shell_true_pattern, replace_shell_true, content)
            if new_content != content:
                changes.append("Replaced shell=True with shell=False and list arguments")
                content = new_content

        # 5. Fix bare except clauses
        bare_except_pattern = r'(\s*)except\s*:\s*\n'
        if re.search(bare_except_pattern, content):
            new_content = re.sub(
                bare_except_pattern,
                r'\1except Exception:\n',
                content
            )
            if new_content != content:
                changes.append("Replaced bare except with 'except Exception'")
                content = new_content

        # 6. Disable debug mode
        debug_pattern = r'(DEBUG\s*=\s*)(True|1)'
        if re.search(debug_pattern, content):
            new_content = re.sub(debug_pattern, r'\1False', content)
            if new_content != content:
                changes.append("Disabled debug mode for security")
                content = new_content

        return content, changes

    def _remove_unused_imports(self, content: str, filename: str) -> tuple[str, list[str]]:
        """Remove unused imports from Python files."""
        changes = []

        if not filename.endswith('.py'):
            return content, changes

        try:
            tree = ast.parse(content)
        except SyntaxError:
            return content, changes

        # Find all imported names
        imported_names: set[str] = set()
        import_lines: dict[str, int] = {}

        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    name = alias.asname or alias.name.split('.')[0]
                    imported_names.add(name)
                    import_lines[name] = node.lineno
            elif isinstance(node, ast.ImportFrom):
                for alias in node.names:
                    name = alias.asname or alias.name
                    imported_names.add(name)
                    import_lines[name] = node.lineno

        # Find all used names (simplified - doesn't handle all cases)
        used_names: set[str] = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Name):
                used_names.add(node.id)
            elif isinstance(node, ast.Attribute):
                if isinstance(node.value, ast.Name):
                    used_names.add(node.value.id)

        # Find unused imports
        unused = imported_names - used_names

        if unused:
            lines = content.split('\n')
            lines_to_remove = set()

            for name in unused:
                if name in import_lines:
                    lines_to_remove.add(import_lines[name] - 1)

            # Remove lines (from end to preserve line numbers)
            for line_idx in sorted(lines_to_remove, reverse=True):
                if line_idx < len(lines):
                    removed_line = lines[line_idx]
                    # Only remove if it's a simple import line
                    if re.match(r'^\s*(from|import)\s+', removed_line):
                        del lines[line_idx]
                        changes.append(f"Removed unused import: {removed_line.strip()}")

            content = '\n'.join(lines)

        return content, changes

    def _fix_long_lines(self, content: str, filename: str, max_length: int = 100) -> tuple[str, list[str]]:
        """Attempt to fix lines that are too long."""
        changes = []
        lines = content.split('\n')
        new_lines = []

        for i, line in enumerate(lines):
            if len(line) > max_length:
                # Try to break at logical points
                fixed_line = self._break_long_line(line, max_length, filename)
                if fixed_line != line:
                    changes.append(f"Line {i+1}: Attempted to fix long line")
                new_lines.append(fixed_line)
            else:
                new_lines.append(line)

        return '\n'.join(new_lines), changes

    def _break_long_line(self, line: str, max_length: int, filename: str) -> str:
        """Attempt to break a long line at a logical point."""
        if len(line) <= max_length:
            return line

        indent = len(line) - len(line.lstrip())
        indent_str = line[:indent]

        # Try breaking at different points
        break_points = [
            (', ', ',\n' + indent_str + '    '),
            (' and ', ' and \\\n' + indent_str + '    '),
            (' or ', ' or \\\n' + indent_str + '    '),
            ('(', '(\n' + indent_str + '    '),
        ]

        for old, new in break_points:
            if old in line:
                # Find a break point that results in reasonable line lengths
                idx = line.rfind(old, 0, max_length)
                if idx > indent + 10:  # Ensure meaningful content before break
                    return line[:idx] + new + line[idx + len(old):]

        return line  # Return original if no good break point found

    def _apply_quality_fixes(self, content: str, filename: str) -> tuple[str, list[str]]:
        """Apply code quality improvements."""
        changes = []

        if not filename.endswith('.py'):
            return content, changes

        # 1. Simplify boolean comparisons
        # Replace 'if x == True:' with 'if x:'
        bool_patterns = [
            (r'\bif\s+(\w+)\s*==\s*True\s*:', r'if \1:'),
            (r'\bif\s+(\w+)\s*==\s*False\s*:', r'if not \1:'),
            (r'\bif\s+(\w+)\s*!=\s*True\s*:', r'if not \1:'),
            (r'\bif\s+(\w+)\s*!=\s*False\s*:', r'if \1:'),
            (r'\bif\s+(\w+)\s+is\s+True\s*:', r'if \1:'),
            (r'\bif\s+(\w+)\s+is\s+False\s*:', r'if not \1:'),
            (r'\bif\s+not\s+(\w+)\s*==\s*True\s*:', r'if not \1:'),
        ]

        for pattern, replacement in bool_patterns:
            new_content = re.sub(pattern, replacement, content)
            if new_content != content:
                changes.append("Simplified boolean comparison")
                content = new_content

        # 2. Replace 'if len(x) > 0:' with 'if x:'
        len_patterns = [
            (r'\bif\s+len\((\w+)\)\s*>\s*0\s*:', r'if \1:'),
            (r'\bif\s+len\((\w+)\)\s*!=\s*0\s*:', r'if \1:'),
            (r'\bif\s+len\((\w+)\)\s*==\s*0\s*:', r'if not \1:'),
            (r'\bif\s+len\((\w+)\)\s*<\s*1\s*:', r'if not \1:'),
        ]

        for pattern, replacement in len_patterns:
            new_content = re.sub(pattern, replacement, content)
            if new_content != content:
                changes.append("Simplified length check to pythonic form")
                content = new_content

        # 3. Use f-strings instead of .format() for simple cases
        format_pattern = r'["\']([^"\']*)\{\}([^"\']*)["\']\.format\((\w+)\)'
        new_content = re.sub(format_pattern, r'f"\1{\3}\2"', content)
        if new_content != content:
            changes.append("Converted .format() to f-string")
            content = new_content

        # 4. Replace type() check with isinstance()
        type_check_pattern = r'\btype\((\w+)\)\s*==\s*(\w+)\b'
        new_content = re.sub(type_check_pattern, r'isinstance(\1, \2)', content)
        if new_content != content:
            changes.append("Replaced type() check with isinstance()")
            content = new_content

        # 5. Remove redundant pass in try/except
        pass_pattern = r'(except\s+\w+\s*:)\s*\n\s*pass\s*\n(\s*finally:)'
        new_content = re.sub(pass_pattern, r'\1\n        pass  # TODO: Handle exception\n\2', content)

        # 6. Rename trivial temp variables in a safe scope
        content, rename_changes = self._rename_temp_variables(content, filename)
        changes.extend(rename_changes)

        # 7. Extract very simple method blocks (safe, no-arg calls only)
        content, extract_changes = self._extract_simple_method_blocks(content, filename)
        changes.extend(extract_changes)

        return content, changes

    def _rename_temp_variables(self, content: str, filename: str) -> tuple[str, list[str]]:
        """Rename temp variables within a single function scope (safe, Python-only)."""
        changes = []

        if not filename.endswith('.py'):
            return content, changes

        try:
            tree = ast.parse(content)
        except SyntaxError:
            return content, changes

        lines = content.split('\n')
        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef) and hasattr(node, "lineno") and hasattr(node, "end_lineno"):
                start = node.lineno - 1
                end = node.end_lineno
                block = lines[start:end]

                for var in ["tmp", "temp"]:
                    assign_count = len(re.findall(rf'\b{var}\s*=', "\n".join(block)))
                    if assign_count == 1:
                        if re.search(rf'\b{var}\b', "\n".join(block)) and "temporary_value" not in "\n".join(block):
                            block_text = "\n".join(block)
                            block_text = re.sub(rf'\b{var}\b', "temporary_value", block_text)
                            block = block_text.split('\n')
                            changes.append(f"Renamed variable '{var}' to 'temporary_value' in {node.name}()")

                lines[start:end] = block

        return "\n".join(lines), changes

    def _extract_simple_method_blocks(self, content: str, filename: str) -> tuple[str, list[str]]:
        """Extract simple no-arg call blocks into a helper method (safe, Python-only)."""
        changes = []

        if not filename.endswith('.py'):
            return content, changes

        try:
            tree = ast.parse(content)
        except SyntaxError:
            return content, changes

        lines = content.split('\n')
        helper_count = 0

        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef) and hasattr(node, "lineno") and hasattr(node, "end_lineno"):
                func_start = node.lineno - 1
                func_end = node.end_lineno
                def_line = lines[func_start]
                func_indent = len(def_line) - len(def_line.lstrip())
                body_indent = func_indent + 4
                body_lines = lines[func_start + 1:func_end]

                # Find 4-8 consecutive no-arg call lines
                candidate_start = None
                candidate_end = None
                streak = 0

                for i, line in enumerate(body_lines):
                    if re.match(rf'^\s{{{body_indent}}}[\w\.]+\(\s*\)\s*$', line):
                        if candidate_start is None:
                            candidate_start = i
                        streak += 1
                        if streak >= 4:
                            candidate_end = i
                    else:
                        if streak >= 4:
                            break
                        candidate_start = None
                        candidate_end = None
                        streak = 0

                if candidate_start is not None and candidate_end is not None:
                    helper_count += 1
                    helper_name = f"_extracted_{node.name}_{helper_count}"
                    block = body_lines[candidate_start:candidate_end + 1]

                    helper_def = [
                        " " * func_indent + f"def {helper_name}():",
                        *block,
                        ""
                    ]

                    # Insert helper above the function
                    lines = (
                        lines[:func_start] +
                        helper_def +
                        lines[func_start:]
                    )

                    # Replace block with helper call
                    new_body_lines = (
                        body_lines[:candidate_start] +
                        [" " * body_indent + f"{helper_name}()"] +
                        body_lines[candidate_end + 1:]
                    )
                    lines[func_start + 1:func_end + len(helper_def)] = new_body_lines

                    changes.append(f"Extracted {candidate_end - candidate_start + 1} lines into {helper_name}()")
                    break

        return "\n".join(lines), changes

    def _extract_constants(self, content: str, filename: str) -> tuple[str, list[str]]:
        """Extract magic numbers and strings to named constants."""
        changes = []

        if not filename.endswith('.py'):
            return content, changes

        # Find magic numbers used multiple times
        magic_numbers = re.findall(r'(?<!["\'\w])(\d{3,})(?!["\'\w])', content)
        number_counts: dict[str, int] = {}
        for num in magic_numbers:
            number_counts[num] = number_counts.get(num, 0) + 1

        # Extract numbers used more than once
        constants_to_add = []
        for num, count in number_counts.items():
            if count >= 2 and int(num) not in [100, 200, 404, 500]:  # Skip common HTTP codes
                const_name = f"CONSTANT_{num}"
                constants_to_add.append((num, const_name))

        if constants_to_add:
            lines = content.split('\n')

            # Find where to insert constants (after imports)
            insert_idx = 0
            for i, line in enumerate(lines):
                if line.startswith('import ') or line.startswith('from '):
                    insert_idx = i + 1
                elif line.strip() and not line.startswith('#') and insert_idx > 0:
                    break

            # Add constant definitions
            const_lines = ['\n# Constants']
            for num, const_name in constants_to_add:
                const_lines.append(f'{const_name} = {num}')
                # Replace occurrences
                content = re.sub(rf'(?<!["\'\w]){num}(?!["\'\w])', const_name, content)
                changes.append(f"Extracted magic number {num} to {const_name}")

            const_lines.append('')
            lines = lines[:insert_idx] + const_lines + lines[insert_idx:]
            content = '\n'.join(lines)

        return content, changes

    def _remove_duplicate_code(self, content: str, filename: str) -> tuple[str, list[str]]:
        """Identify and suggest fixes for duplicate code blocks."""
        changes = []

        if not filename.endswith('.py'):
            return content, changes

        lines = content.split('\n')

        # Find duplicate consecutive lines (simple detection)
        seen_blocks: dict[str, list[int]] = {}
        i = 0
        while i < len(lines) - 2:
            # Create a 3-line block fingerprint
            block = '\n'.join(lines[i:i+3]).strip()
            if len(block) > 20:  # Only consider non-trivial blocks
                if block in seen_blocks:
                    seen_blocks[block].append(i)
                else:
                    seen_blocks[block] = [i]
            i += 1

        # Report duplicates (don't auto-fix complex duplications)
        for block, positions in seen_blocks.items():
            if len(positions) > 1:
                changes.append(f"Found duplicate code block at lines {[p+1 for p in positions]}")

        return content, changes

    def commit_changes(
        self,
        repo: str,
        branch: str,
        results: list[RefactoringResult] | None = None,
        commit_message: str | None = None
    ) -> CommitResult:
        """
        Commit refactoring changes to the repository.

        Args:
            repo: Repository in format 'owner/repo'
            branch: Branch to commit to
            results: Refactoring results to commit (defaults to self.refactoring_results)
            commit_message: Custom commit message

        Returns:
            CommitResult with commit details
        """
        if not self.github_client:
            return CommitResult(
                success=False,
                error="GitHub client not configured"
            )

        results = results or self.refactoring_results

        # Filter to only successful results with actual changes
        changes_to_commit = [
            r for r in results
            if r.success and r.changes_made and r.refactored_content != r.original_content
        ]

        if not changes_to_commit:
            return CommitResult(
                success=True,
                files_changed=[]
            )

        # Build commit message
        if not commit_message:
            all_changes = []
            for result in changes_to_commit:
                for change in result.changes_made:
                    all_changes.append(f"- {change}")

            commit_message = "refactor: automated code improvements\n\n"
            commit_message += "Changes made:\n"
            commit_message += "\n".join(all_changes[:20])  # Limit message size
            if len(all_changes) > 20:
                commit_message += f"\n... and {len(all_changes) - 20} more changes"

        # Prepare file updates
        file_updates = {
            result.file_path: result.refactored_content
            for result in changes_to_commit
        }

        try:
            sha = self.github_client.create_commit_bulk(
                repo_full_name=repo,
                branch=branch,
                file_updates=file_updates,
                message=commit_message
            )

            self.state.create_checkpoint(f"post_commit_{sha[:8]}")

            return CommitResult(
                sha=sha,
                success=True,
                files_changed=list(file_updates.keys())
            )
        except Exception as e:
            return CommitResult(
                success=False,
                error=str(e)
            )

    def generate_summary(self, results: list[RefactoringResult] | None = None) -> str:
        """Generate a summary of refactoring operations."""
        results = results or self.refactoring_results

        if not results:
            return "No refactoring operations performed."

        successful = [r for r in results if r.success]
        failed = [r for r in results if not r.success]

        total_changes = sum(len(r.changes_made) for r in successful)

        lines = [
            "## Refactoring Summary",
            "",
            f"**Files processed:** {len(results)}",
            f"**Successful:** {len(successful)}",
            f"**Failed:** {len(failed)}",
            f"**Total changes:** {total_changes}",
            "",
        ]

        if successful:
            lines.append("### Changes Made")
            for result in successful:
                if result.changes_made:
                    lines.append(f"\n**{result.file_path}:**")
                    for change in result.changes_made:
                        lines.append(f"- {change}")

        if failed:
            lines.append("\n### Failures")
            for result in failed:
                lines.append(f"- {result.file_path}: {result.error}")

        return "\n".join(lines)

    def rollback(self) -> bool:
        """Rollback to pre-refactoring state."""
        return self.state.rollback("pre_refactoring")
