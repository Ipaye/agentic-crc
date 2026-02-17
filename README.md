# Intelligent Agentic Code Review System

An AI-powered code review system that integrates with GitHub PRs, using multi-agent orchestration with CrewAI and local LLMs via Ollama.

## Features

- **GitHub Integration**: Full PR lifecycle support (webhook-driven and API-based)
- **Multi-Agent System**: Coordinated agents for review, refactoring, and verification
- **Static Analysis**: AST-based parsing, pattern matching, and rule engine
- **Semantic Analysis**: LLM-powered code understanding via Ollama
- **Auto-Refactoring**: Automated fixes for common issues with safety checks
- **Configurable Rules**: YAML-based coding standards for style, security, and quality

## Architecture

```
┌─────────────────┐     ┌──────────────────┐     ┌─────────────────┐
│  GitHub PR/     │────▶│  Webhook Server  │────▶│  Event Handler  │
│  Webhook        │     │  (FastAPI)       │     │                 │
└─────────────────┘     └──────────────────┘     └────────┬────────┘
                                                          │
                                                          ▼
┌─────────────────────────────────────────────────────────────────────┐
│                        Review Orchestrator                          │
├─────────────────┬───────────────────┬──────────────────────────────┤
│ Code Review     │  Refactoring      │  Verification                │
│ Agent           │  Agent            │  Agent                       │
│ • Static        │  • Style fixes    │  • Syntax check              │
│ • Semantic      │  • Security fixes │  • Test execution            │
│ • Handoff       │  • Imports        │  • Impact assessment         │
└────────┬────────┴────────┬──────────┴──────────────────────────────┘
         │                 │
         ▼                 ▼
┌─────────────────┐     ┌─────────────────┐
│ Code Analyzer   │     │ Ollama Client   │
│ • Parser        │     │ • codellama     │
│ • Rules         │     │ • Prompts       │
│ • Patterns      │     │ • Streaming     │
└─────────────────┘     └─────────────────┘
```

## Quick Start

### Prerequisites

- Python 3.10+
- [Ollama](https://ollama.ai) with `codellama:7b` model (optional, for LLM analysis)
- GitHub App or Personal Access Token

### Installation

```bash
# Clone the repository
git clone https://github.com/ipaye/agentic-crc.git
cd agentic-crc

# Create virtual environment
python -m venv venv
source venv/bin/activate  # or `venv\Scripts\activate` on Windows

# Install dependencies
pip install -e ".[dev]"
# Optional: CrewAI helpers and planners (requires Python 3.10+)
pip install -e "[crewai]"

# Copy environment template
cp .env.example .env

# Pull Ollama model (defaults to `codellama:7b`, override `OLLAMA_MODEL` if needed)
ollama pull codellama:7b
```

### Configuration

Edit `.env` with your settings:

```bash
# GitHub Configuration
GITHUB_TOKEN=ghp_your_token_here
GITHUB_WEBHOOK_SECRET=your_webhook_secret
GITHUB_APP_ID=your_app_id_if_using_a_github_app
GITHUB_APP_PRIVATE_KEY_PATH=path/to/private-key.pem

# Ollama Configuration
OLLAMA_ENABLED=true  # set to false in CI to skip LLM calls
OLLAMA_HOST=http://localhost:11434
OLLAMA_MODEL=codellama:7b
OLLAMA_TIMEOUT=300

# Webhook Server
WEBHOOK_HOST=0.0.0.0
WEBHOOK_PORT=8000

# Analysis Limits
MAX_FILES_PER_PR=50
MAX_DIFF_LINES=5000
ANALYSIS_TIMEOUT=300

# Agent Configuration
AGENT_MAX_ITERATIONS=10
REFACTOR_AUTO_COMMIT=false
VERIFY_BEFORE_COMMIT=true

# Logging
LOG_LEVEL=INFO
LOG_FORMAT=json
```

### Running the Webhook Server

```bash
# Start the server (uses WEBHOOK_PORT, defaults to 8000)
python -m src.main server

# Or with uvicorn directly
uvicorn src.webhook.server:app --host 0.0.0.0 --port 8000
```

### Analyzing a PR Locally

```bash
# Analyze a specific PR
python -m src.main analyze --repo owner/repo --pr 123

# With auto-refactoring enabled
python -m src.main analyze --repo owner/repo --pr 123 --auto-fix
```

## Project Structure

```
src/
├── config.py           # Central configuration
├── main.py             # CLI entry point
├── github/             # GitHub integration
│   ├── client.py       # API client with rate limiting
│   ├── models.py       # Data models (PR, FileChange, etc.)
│   └── pr_handler.py   # PR workflow coordination
├── webhook/            # Webhook infrastructure
│   ├── server.py       # FastAPI application
│   └── handlers.py     # Event handlers
├── analysis/           # Code analysis pipeline
│   ├── analyzer.py     # Main analyzer orchestration
│   ├── parser.py       # AST parsing (tree-sitter + regex)
│   ├── rules.py        # Rule engine with built-in rules
│   └── patterns.py     # Code smell detection
├── llm/                # LLM integration
│   ├── ollama_client.py # Ollama API client
│   ├── prompts.py      # Prompt templates
│   └── semantic_analyzer.py # LLM-based analysis
├── agents/             # Multi-agent system
│   ├── state.py        # Agent state management
│   ├── code_review_agent.py
│   ├── refactoring_agent.py
│   ├── verification_agent.py
│   └── orchestrator.py # Workflow coordination
└── utils/
    └── logging.py      # Structured logging
rules/
├── style.yaml          # Style rules
├── security.yaml       # Security rules
├── quality.yaml        # Code quality rules
└── best_practices.yaml # Best practice rules
```

## Multi-Agent System

### Code Review Agent

- Performs static analysis using rules and patterns
- Executes semantic analysis via LLM
- Evaluates handoff criteria for delegation

### Refactoring Agent

- Applies automated fixes for common issues
- Handles style, security, and import fixes
- Creates commits with clear explanations

### Verification Agent

- Validates syntax for multiple languages
- Assesses change impact and risk
- Executes tests when available

### Handoff Criteria

The system delegates to the refactoring agent when:

- Complexity is below threshold (auto-fixable)
- There are style/whitespace violations
- Security issues have known fixes
- Import cleanup is needed

## Coding Rules

Rules are defined in YAML format:

```yaml
rules:
  - id: SEC001
    name: hardcoded-secret
    severity: error
    category: security
    description: Potential hardcoded secret detected
    pattern: '(password|secret|api_key)\s*=\s*["\'][^"\']+["\']'
    languages: [python, javascript, typescript]
    message: "Avoid hardcoding secrets. Use environment variables."
```

### Built-in Rule Categories

- **Style**: Line length, whitespace, formatting
- **Security**: Hardcoded secrets, SQL injection, CORS misconfig
- **Quality**: Complexity, dead code, parameter limits
- **Best Practices**: Type comparison, TODOs, deprecation

## GitHub Actions

The included workflow (`.github/workflows/code-review.yml`) runs on:

- PR opened, synchronized, or reopened

Features:

- Full code review analysis
- Security scanning with Bandit
- Linting with Ruff

LLM analysis is disabled by default in CI to avoid timeouts. Enable it by setting:

```
OLLAMA_ENABLED=true
```

## API Reference

### GitHub Client

```python
from src.github.client import GitHubClient

client = GitHubClient(token="ghp_...")

# Get PR info
pr = client.get_pull_request("owner/repo", 123)

# Get changed files
files = pr.files

# Post review comments
client.post_review_comments("owner/repo", 123, comments)
```

### Orchestrator

```python
from src.agents.orchestrator import ReviewOrchestrator

orchestrator = ReviewOrchestrator(
    github_client=client,
    enable_auto_commit=False,
    enable_verification=True
)

result = orchestrator.run_workflow(pr_info, file_changes)
print(result.summary)
```

## Logging & Outputs

Analysis logs are always exported in machine-readable formats:

- JSON: `logs/pr_<PR_NUMBER>_<TIMESTAMP>/analysis_results.json`
- JSONL: `logs/pr_<PR_NUMBER>_<TIMESTAMP>/analysis_results.jsonl`
- CSV: `logs/pr_<PR_NUMBER>_<TIMESTAMP>/analysis_results.csv`

These include rule triggers, confidence scores, and summaries for auditability.

## Development

### Running Tests

```bash
# Run all tests
pytest

# With coverage
pytest --cov=src --cov-report=html
```

### Linting

```bash
# Format code
ruff format src/

# Check linting
ruff check src/
```

### Type Checking

```bash
mypy src/
```

## Environment Variables

| Variable                    | Description                             | Default                  |
| --------------------------- | --------------------------------------- | ------------------------ |
| `GITHUB_TOKEN`              | GitHub API token                        | Required                 |
| `GITHUB_WEBHOOK_SECRET`     | Webhook signature secret                | Required for webhooks    |
| `GITHUB_APP_ID`             | GitHub App ID (optional)                | `None`                   |
| `GITHUB_APP_PRIVATE_KEY_PATH` | Path to GitHub App private key         | `None`                   |
| `OLLAMA_ENABLED`            | Enable LLM analysis                     | `true`                   |
| `OLLAMA_HOST`               | Ollama server URL                       | `http://localhost:11434` |
| `OLLAMA_MODEL`              | LLM model to use                        | `codellama:7b`           |
| `OLLAMA_TIMEOUT`            | Request timeout for Ollama (seconds)    | `300`                    |
| `WEBHOOK_HOST`              | Webhook server bind host                | `0.0.0.0`                |
| `WEBHOOK_PORT`              | Webhook server bind port                | `8000`                   |
| `MAX_FILES_PER_PR`          | Max files processed per PR              | `50`                     |
| `MAX_DIFF_LINES`            | Max diff lines analyzed per PR          | `5000`                   |
| `ANALYSIS_TIMEOUT`          | Time budget for a single analysis (sec) | `300`                    |
| `AGENT_MAX_ITERATIONS`      | Max agent orchestration iterations      | `10`                     |
| `REFACTOR_AUTO_COMMIT`      | Auto-commit refactoring changes         | `false`                  |
| `VERIFY_BEFORE_COMMIT`      | Run verification before committing      | `true`                   |
| `LOG_LEVEL`                 | Structlog level for console/file logs    | `INFO`                   |
| `LOG_FORMAT`                | Logging format (`json` or `console`)    | `json`                   |

## License

MIT License - See [LICENSE](LICENSE) for details.

## Contributing

1. Fork the repository
2. Create a feature branch
3. Make your changes with tests
4. Submit a pull request

The code review system will automatically analyze your PR! 🤖
