"""
Prompt templates for LLM-based code analysis.
"""
from __future__ import annotations


class PromptTemplates:
    """
    Collection of prompt templates for different analysis tasks.
    """

    # System prompts for different roles
    SYSTEM_PROMPTS = {
        "review": """You are an expert code reviewer with deep knowledge of software engineering best practices, design patterns, and security. Your role is to:
1. Identify bugs, security vulnerabilities, and code quality issues
2. Suggest improvements for readability, maintainability, and performance
3. Point out deviations from coding standards and best practices
4. Provide actionable, constructive feedback

Be specific, cite line numbers when relevant, and always explain the reasoning behind your feedback.
Format your response as JSON when possible.""",

        "security": """You are a security-focused code analyst specializing in identifying vulnerabilities and security risks. Focus on:
1. Input validation and sanitization issues
2. Authentication and authorization flaws
3. Data exposure and privacy concerns
4. Injection vulnerabilities (SQL, XSS, command injection)
5. Cryptographic weaknesses
6. Insecure configurations

Prioritize findings by severity and provide clear remediation steps.
Format your response as JSON when possible.""",

        "performance": """You are a performance optimization specialist. Analyze code for:
1. Time complexity issues (O(n²) loops, unnecessary iterations)
2. Memory inefficiencies (memory leaks, excessive allocations)
3. I/O bottlenecks (blocking operations, unoptimized queries)
4. Caching opportunities
5. Algorithm improvements

Provide specific optimization suggestions with expected impact.
Format your response as JSON when possible.""",

        "refactoring": """You are a code refactoring expert. Your goal is to improve code structure while preserving functionality. Focus on:
1. Extract method opportunities
2. Variable and function renaming for clarity
3. Simplifying complex conditionals
4. Removing code duplication
5. Applying design patterns where appropriate
6. Improving separation of concerns

Provide specific before/after code examples.
Format your response as JSON when possible.""",

        "documentation": """You are a technical documentation specialist. Review code for:
1. Missing or inadequate docstrings/comments
2. Unclear function/class purposes
3. Undocumented parameters and return values
4. Missing type hints
5. Opportunities for inline explanations

Provide sample documentation for identified gaps.
Format your response as JSON when possible."""
    }

    @classmethod
    def get_system_prompt(cls, analysis_type: str) -> str:
        """Get the system prompt for a specific analysis type."""
        return cls.SYSTEM_PROMPTS.get(analysis_type, cls.SYSTEM_PROMPTS["review"])

    @classmethod
    def get_analysis_prompt(
        cls,
        code: str,
        filename: str,
        analysis_type: str = "review",
        context: str | None = None,
        focus_areas: list | None = None
    ) -> str:
        """
        Generate a prompt for code analysis.
        """
        prompt = f"""Analyze the following code from file `{filename}`:

```
{code}
```

"""

        if context:
            prompt += f"""
Additional context:
{context}

"""

        if focus_areas:
            prompt += f"""
Focus particularly on these areas:
{chr(10).join(f"- {area}" for area in focus_areas)}

"""

        prompt += """
Provide your analysis in the following JSON format:
```json
{
    "issues": [
        {
            "line": <line_number>,
            "severity": "<error|warning|info|suggestion>",
            "category": "<security|quality|style|performance>",
            "description": "<clear description of the issue>",
            "suggestion": "<how to fix the issue>",
            "code_example": "<corrected code if applicable>"
        }
    ],
    "overall_assessment": "<brief summary of code quality>",
    "positive_aspects": ["<things done well>"],
    "priority_fixes": ["<most important issues to address>"]
}
```

Be thorough but concise. Focus on actionable feedback."""

        return prompt

    @classmethod
    def get_diff_review_prompt(
        cls,
        diff: str,
        filename: str,
        full_file_content: str | None = None
    ) -> str:
        """
        Generate a prompt for reviewing a code diff.
        """
        prompt = f"""Review the following code changes in file `{filename}`:

```diff
{diff}
```

"""

        if full_file_content:
            prompt += f"""
For context, here is the full file after changes:
```
{full_file_content}
```

"""

        prompt += """
Analyze only the changed lines (lines starting with + or -).
Provide feedback in JSON format:
```json
{
    "issues": [
        {
            "line": <line_number_in_new_file>,
            "severity": "<error|warning|info|suggestion>",
            "description": "<issue description>",
            "suggestion": "<fix suggestion>"
        }
    ],
    "change_quality": "<good|acceptable|needs_improvement>",
    "summary": "<brief assessment of the changes>"
}
```"""

        return prompt

    @classmethod
    def get_refactoring_prompt(
        cls,
        code: str,
        filename: str,
        issues: list
    ) -> str:
        """
        Generate a prompt for suggesting refactoring.
        """
        issues_text = "\n".join(f"- {issue}" for issue in issues)

        prompt = f"""The following code from `{filename}` has been identified as needing refactoring:

```
{code}
```

The following issues have been identified:
{issues_text}

Please provide specific refactoring suggestions in JSON format:
```json
{{
    "refactorings": [
        {{
            "type": "<extract_method|rename|simplify_conditional|remove_duplication|other>",
            "description": "<what to do>",
            "before": "<original code snippet>",
            "after": "<refactored code snippet>",
            "impact": "<why this improves the code>"
        }}
    ],
    "overall_approach": "<summary of refactoring strategy>",
    "estimated_improvement": {{
        "readability": <1-10>,
        "maintainability": <1-10>,
        "testability": <1-10>
    }}
}}
```

Focus on practical, incremental improvements that preserve functionality."""

        return prompt

    @classmethod
    def get_explanation_prompt(cls, code: str, filename: str) -> str:
        """
        Generate a prompt for explaining code.
        """
        return f"""Explain the following code from `{filename}`:

```
{code}
```

Provide a clear explanation including:
1. **Purpose**: What does this code do?
2. **How it works**: Step-by-step explanation of the logic
3. **Key components**: Important functions, classes, or patterns used
4. **Dependencies**: External libraries or modules used
5. **Potential issues**: Any concerns or areas for improvement

Be concise but thorough."""

    @classmethod
    def get_test_suggestion_prompt(
        cls,
        code: str,
        filename: str,
        existing_tests: str | None = None
    ) -> str:
        """
        Generate a prompt for suggesting tests.
        """
        prompt = f"""Suggest tests for the following code from `{filename}`:

```
{code}
```

"""

        if existing_tests:
            prompt += f"""
Existing tests:
```
{existing_tests}
```

Focus on gaps in test coverage.
"""

        prompt += """
Provide test suggestions in JSON format:
```json
{
    "test_cases": [
        {
            "name": "<test function name>",
            "description": "<what is being tested>",
            "type": "<unit|integration|edge_case>",
            "code": "<complete test code>"
        }
    ],
    "coverage_gaps": ["<areas not well tested>"],
    "testing_strategy": "<overall approach recommendation>"
}
```"""

        return prompt

    @classmethod
    def get_pr_summary_prompt(
        cls,
        pr_title: str,
        pr_body: str | None,
        files_changed: list,
        total_additions: int,
        total_deletions: int
    ) -> str:
        """
        Generate a prompt for summarizing a PR.
        """
        files_text = "\n".join(f"- {f}" for f in files_changed[:20])
        if len(files_changed) > 20:
            files_text += f"\n... and {len(files_changed) - 20} more files"

        return f"""Summarize this pull request:

**Title:** {pr_title}

**Description:**
{pr_body or "No description provided"}

**Changes:**
- {total_additions} additions, {total_deletions} deletions
- Files changed:
{files_text}

Provide a brief summary including:
1. Main purpose of the changes
2. Key areas affected
3. Potential review focus areas

Be concise (2-3 paragraphs max)."""
