"""
Main entry point for the Intelligent Agentic Code Review System.

Usage:
    python -m src.main server      # Start webhook server
    python -m src.main analyze     # Analyze a PR
    python -m src.main rules       # List available rules
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

from src.config import settings


def run_server(args):
    """Start the webhook server."""
    import uvicorn

    from src.webhook.server import app

    print(f"Starting webhook server on {settings.webhook.host}:{settings.webhook.port}")
    uvicorn.run(
        app,
        host=settings.webhook.host,
        port=settings.webhook.port,
        log_level="info"
    )


def analyze_pr(args):
    """Analyze a pull request."""
    from src.agents.orchestrator import ReviewOrchestrator
    from src.analysis.analyzer import CodeAnalyzer
    from src.github.client import GitHubClient
    from src.llm.semantic_analyzer import SemanticAnalyzer
    from src.utils.logging import setup_logging

    setup_logging()

    # Initialize clients
    github_client = GitHubClient(token=settings.github.token)
    code_analyzer = CodeAnalyzer()

    # Optionally initialize semantic analyzer
    semantic_analyzer = None
    if args.use_llm:
        semantic_analyzer = SemanticAnalyzer()

    try:
        # Fetch PR information
        print(f"Fetching PR #{args.pr} from {args.repo}...")
        pr_info = github_client.get_pull_request(args.repo, args.pr)

        print(f"PR: {pr_info.title}")
        print(f"Author: {pr_info.author}")
        print(f"Files changed: {len(pr_info.files)}")
        print()

        # Run orchestrator
        orchestrator = ReviewOrchestrator(
            github_client=github_client,
            code_analyzer=code_analyzer,
            semantic_analyzer=semantic_analyzer,
            enable_auto_commit=args.auto_fix,
            enable_verification=not args.skip_verification
        )

        result = orchestrator.run_workflow(pr_info, pr_info.files)

        # Output results
        print(result.summary)
        print()
        print(f"Workflow completed in {result.duration_seconds:.2f}s")
        print(f"Stage reached: {result.stage_reached.value}")
        print(f"Comments generated: {result.comments_posted}")

        if args.auto_fix:
            print(f"Files refactored: {result.files_refactored}")
            if result.commit_sha:
                print(f"Commit SHA: {result.commit_sha}")

        if result.errors:
            print("\nErrors:")
            for error in result.errors:
                print(f"  - {error}")

        return 0 if result.success else 1

    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1


def list_rules(args):
    """List available coding rules."""
    from src.analysis.rules import RuleEngine

    engine = RuleEngine()

    # Load custom rules if directory specified
    if args.rules_dir:
        rules_dir = Path(args.rules_dir)
        if rules_dir.exists():
            engine.load_rules_from_directory(rules_dir)

    rules = engine.get_all_rules()

    # Group by category
    by_category: dict[str, list] = {}
    for rule in rules:
        category = rule.category
        if category not in by_category:
            by_category[category] = []
        by_category[category].append(rule)

    print(f"Total rules: {len(rules)}\n")

    for category in sorted(by_category.keys()):
        print(f"## {category.upper()}")
        print()
        for rule in by_category[category]:
            severity_icon = {"error": "🔴", "warning": "🟡", "info": "🔵"}.get(rule.severity, "⚪")
            print(f"  {severity_icon} {rule.id}: {rule.name}")
            print(f"     {rule.description}")
        print()

    return 0


def main():
    """Main entry point."""
    parser = argparse.ArgumentParser(
        description="Intelligent Agentic Code Review System",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python -m src.main server
  python -m src.main analyze --repo owner/repo --pr 123
  python -m src.main analyze --repo owner/repo --pr 123 --auto-fix --use-llm
  python -m src.main rules --rules-dir ./rules
        """
    )

    subparsers = parser.add_subparsers(dest="command", help="Available commands")

    # Server command
    server_parser = subparsers.add_parser("server", help="Start webhook server")
    server_parser.set_defaults(func=run_server)

    # Analyze command
    analyze_parser = subparsers.add_parser("analyze", help="Analyze a pull request")
    analyze_parser.add_argument("--repo", required=True, help="Repository (owner/repo)")
    analyze_parser.add_argument("--pr", type=int, required=True, help="Pull request number")
    analyze_parser.add_argument("--auto-fix", action="store_true", help="Enable auto-refactoring")
    analyze_parser.add_argument("--use-llm", action="store_true", help="Enable LLM semantic analysis")
    analyze_parser.add_argument("--skip-verification", action="store_true", help="Skip verification stage")
    analyze_parser.set_defaults(func=analyze_pr)

    # Rules command
    rules_parser = subparsers.add_parser("rules", help="List available rules")
    rules_parser.add_argument("--rules-dir", help="Custom rules directory")
    rules_parser.set_defaults(func=list_rules)

    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        return 1

    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
