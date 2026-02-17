"""
Configuration management for the Agentic Code Review System.
"""
from __future__ import annotations

import os
from pathlib import Path
from typing import Optional

from dotenv import load_dotenv
from pydantic import BaseModel, Field

# Load environment variables from .env file
load_dotenv()


class GitHubConfig(BaseModel):
    """GitHub API configuration."""

    token: str = Field(default_factory=lambda: os.getenv("GITHUB_TOKEN", ""))
    webhook_secret: str = Field(default_factory=lambda: os.getenv("GITHUB_WEBHOOK_SECRET", ""))
    app_id: Optional[str] = Field(default_factory=lambda: os.getenv("GITHUB_APP_ID"))
    app_private_key_path: Optional[str] = Field(
        default_factory=lambda: os.getenv("GITHUB_APP_PRIVATE_KEY_PATH")
    )
    api_base_url: str = "https://api.github.com"
    rate_limit_buffer: int = 100  # Reserve this many API calls


class OllamaConfig(BaseModel):
    """Ollama LLM configuration."""

    enabled: bool = Field(default_factory=lambda: os.getenv("OLLAMA_ENABLED", "true").lower() == "true")
    host: str = Field(default_factory=lambda: os.getenv("OLLAMA_HOST", "http://localhost:11434"))
    model: str = Field(default_factory=lambda: os.getenv("OLLAMA_MODEL", "codellama:7b"))
    temperature: float = 0.1
    max_tokens: int = 4096
    timeout: int = Field(default_factory=lambda: int(os.getenv("OLLAMA_TIMEOUT", "300")))


class WebhookConfig(BaseModel):
    """Webhook server configuration."""

    host: str = Field(default_factory=lambda: os.getenv("WEBHOOK_HOST", "0.0.0.0"))
    port: int = Field(default_factory=lambda: int(os.getenv("WEBHOOK_PORT", "8000")))
    path: str = "/webhook"


class AnalysisConfig(BaseModel):
    """Code analysis configuration."""

    max_files_per_pr: int = Field(
        default_factory=lambda: int(os.getenv("MAX_FILES_PER_PR", "50"))
    )
    max_diff_lines: int = Field(
        default_factory=lambda: int(os.getenv("MAX_DIFF_LINES", "5000"))
    )
    analysis_timeout: int = Field(
        default_factory=lambda: int(os.getenv("ANALYSIS_TIMEOUT", "300"))
    )
    rules_path: Path = Path(__file__).parent.parent / "rules"


class AgentConfig(BaseModel):
    """Multi-agent system configuration."""

    max_iterations: int = Field(
        default_factory=lambda: int(os.getenv("AGENT_MAX_ITERATIONS", "10"))
    )
    refactor_auto_commit: bool = Field(
        default_factory=lambda: os.getenv("REFACTOR_AUTO_COMMIT", "false").lower() == "true"
    )
    verify_before_commit: bool = Field(
        default_factory=lambda: os.getenv("VERIFY_BEFORE_COMMIT", "true").lower() == "true"
    )
    # Delegation thresholds
    complexity_threshold: int = 15  # Cyclomatic complexity
    violation_threshold: int = 5    # Violations per file to trigger delegation
    coverage_threshold: float = 0.5  # Min test coverage


class LoggingConfig(BaseModel):
    """Logging configuration."""

    level: str = Field(default_factory=lambda: os.getenv("LOG_LEVEL", "INFO"))
    format: str = Field(default_factory=lambda: os.getenv("LOG_FORMAT", "json"))
    output_dir: Path = Path(__file__).parent.parent / "logs"

    @property
    def level_value(self) -> int:
        """Convert log level string to numeric value for filtering."""
        import logging
        return getattr(logging, self.level.upper(), logging.INFO)


class Settings(BaseModel):
    """Main settings container."""

    github: GitHubConfig = Field(default_factory=GitHubConfig)
    ollama: OllamaConfig = Field(default_factory=OllamaConfig)
    webhook: WebhookConfig = Field(default_factory=WebhookConfig)
    analysis: AnalysisConfig = Field(default_factory=AnalysisConfig)
    agent: AgentConfig = Field(default_factory=AgentConfig)
    logging: LoggingConfig = Field(default_factory=LoggingConfig)

    class Config:
        arbitrary_types_allowed = True


# Global settings instance
settings = Settings()


def get_settings() -> Settings:
    """Get the global settings instance."""
    return settings


def reload_settings() -> Settings:
    """Reload settings from environment."""
    global settings
    load_dotenv(override=True)
    settings = Settings()
    return settings
