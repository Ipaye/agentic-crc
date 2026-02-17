"""
Ollama LLM client for code analysis.
"""
from __future__ import annotations

import json
from collections.abc import Generator
from typing import Any

import httpx
from tenacity import retry, stop_after_attempt, wait_exponential

from src.config import get_settings
from src.utils.logging import get_logger

logger = get_logger("llm.ollama")


class OllamaClient:
    """
    Client for interacting with Ollama API for code analysis.
    """

    def __init__(
        self,
        host: str | None = None,
        model: str | None = None
    ):
        """Initialize the Ollama client."""
        settings = get_settings()
        self.host = host or settings.ollama.host
        self.model = model or settings.ollama.model
        self.temperature = settings.ollama.temperature
        self.max_tokens = settings.ollama.max_tokens
        self.timeout = settings.ollama.timeout

        self._client = httpx.Client(timeout=self.timeout)
        self._async_client = httpx.AsyncClient(timeout=self.timeout)

        logger.info(
            "ollama_client_initialized",
            host=self.host,
            model=self.model
        )

    def _check_connection(self) -> bool:
        """Check if Ollama is available."""
        try:
            response = self._client.get(f"{self.host}/api/tags")
            return response.status_code == 200
        except Exception as e:
            logger.error("ollama_connection_failed", error=str(e))
            return False

    def list_models(self) -> list[str]:
        """List available models."""
        try:
            response = self._client.get(f"{self.host}/api/tags")
            if response.status_code == 200:
                data = response.json()
                return [m["name"] for m in data.get("models", [])]
        except Exception as e:
            logger.error("failed_to_list_models", error=str(e))
        return []

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=2, max=30)
    )
    def generate(
        self,
        prompt: str,
        system_prompt: str | None = None,
        temperature: float | None = None,
        max_tokens: int | None = None
    ) -> str:
        """
        Generate a response from the LLM.

        Args:
            prompt: The user prompt
            system_prompt: Optional system prompt for context
            temperature: Override default temperature
            max_tokens: Override default max tokens

        Returns:
            Generated text response
        """
        payload = {
            "model": self.model,
            "prompt": prompt,
            "stream": False,
            "options": {
                "temperature": temperature or self.temperature,
                "num_predict": max_tokens or self.max_tokens
            }
        }

        if system_prompt:
            payload["system"] = system_prompt

        try:
            response = self._client.post(
                f"{self.host}/api/generate",
                json=payload
            )
            response.raise_for_status()
            data = response.json()

            generated_text = data.get("response", "")

            logger.debug(
                "ollama_generation_complete",
                prompt_length=len(prompt),
                response_length=len(generated_text),
                eval_count=data.get("eval_count", 0)
            )

            return generated_text

        except httpx.HTTPError as e:
            logger.error("ollama_generation_failed", error=str(e))
            raise

    async def generate_async(
        self,
        prompt: str,
        system_prompt: str | None = None,
        temperature: float | None = None,
        max_tokens: int | None = None
    ) -> str:
        """Async version of generate."""
        payload = {
            "model": self.model,
            "prompt": prompt,
            "stream": False,
            "options": {
                "temperature": temperature or self.temperature,
                "num_predict": max_tokens or self.max_tokens
            }
        }

        if system_prompt:
            payload["system"] = system_prompt

        try:
            response = await self._async_client.post(
                f"{self.host}/api/generate",
                json=payload
            )
            response.raise_for_status()
            data = response.json()
            return data.get("response", "")

        except httpx.HTTPError as e:
            logger.error("ollama_async_generation_failed", error=str(e))
            raise

    def generate_stream(
        self,
        prompt: str,
        system_prompt: str | None = None
    ) -> Generator[str, None, None]:
        """
        Generate a streaming response from the LLM.

        Yields chunks of the response as they arrive.
        """
        payload = {
            "model": self.model,
            "prompt": prompt,
            "stream": True,
            "options": {
                "temperature": self.temperature,
                "num_predict": self.max_tokens
            }
        }

        if system_prompt:
            payload["system"] = system_prompt

        try:
            with self._client.stream(
                "POST",
                f"{self.host}/api/generate",
                json=payload
            ) as response:
                for line in response.iter_lines():
                    if line:
                        data = json.loads(line)
                        chunk = data.get("response", "")
                        if chunk:
                            yield chunk

                        if data.get("done", False):
                            break

        except httpx.HTTPError as e:
            logger.error("ollama_stream_failed", error=str(e))
            raise

    def chat(
        self,
        messages: list[dict[str, str]],
        temperature: float | None = None
    ) -> str:
        """
        Chat-style interaction with the LLM.

        Args:
            messages: List of message dicts with 'role' and 'content'
            temperature: Override default temperature

        Returns:
            Assistant's response
        """
        payload = {
            "model": self.model,
            "messages": messages,
            "stream": False,
            "options": {
                "temperature": temperature or self.temperature
            }
        }

        try:
            response = self._client.post(
                f"{self.host}/api/chat",
                json=payload
            )
            response.raise_for_status()
            data = response.json()

            return data.get("message", {}).get("content", "")

        except httpx.HTTPError as e:
            logger.error("ollama_chat_failed", error=str(e))
            raise

    async def chat_async(
        self,
        messages: list[dict[str, str]],
        temperature: float | None = None
    ) -> str:
        """Async version of chat."""
        payload = {
            "model": self.model,
            "messages": messages,
            "stream": False,
            "options": {
                "temperature": temperature or self.temperature
            }
        }

        try:
            response = await self._async_client.post(
                f"{self.host}/api/chat",
                json=payload
            )
            response.raise_for_status()
            data = response.json()
            return data.get("message", {}).get("content", "")

        except httpx.HTTPError as e:
            logger.error("ollama_async_chat_failed", error=str(e))
            raise

    def analyze_code(
        self,
        code: str,
        filename: str,
        analysis_type: str = "review"
    ) -> dict[str, Any]:
        """
        Analyze code using the LLM.

        Args:
            code: The code to analyze
            filename: Name of the file for context
            analysis_type: Type of analysis (review, security, performance, etc.)

        Returns:
            Structured analysis results
        """
        from src.llm.prompts import PromptTemplates

        prompt = PromptTemplates.get_analysis_prompt(
            code=code,
            filename=filename,
            analysis_type=analysis_type
        )

        system_prompt = PromptTemplates.get_system_prompt(analysis_type)

        response = self.generate(prompt, system_prompt, temperature=0.1)

        # Parse structured response
        return self._parse_analysis_response(response)

    def _parse_analysis_response(self, response: str) -> dict[str, Any]:
        """Parse the LLM response into structured data."""
        # Try to parse as JSON first
        try:
            # Look for JSON block in response
            import re
            json_match = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", response, re.DOTALL)
            if json_match:
                return json.loads(json_match.group(1))

            # Try parsing the whole response as JSON
            return json.loads(response)
        except json.JSONDecodeError:
            pass

        # Fallback: extract structured data from text
        return {
            "raw_response": response,
            "issues": self._extract_issues_from_text(response),
            "suggestions": self._extract_suggestions_from_text(response)
        }

    def _extract_issues_from_text(self, text: str) -> list[dict[str, Any]]:
        """Extract issues from unstructured text response."""
        issues = []
        import re

        # Look for patterns like "1.", "- ", "* ", or numbered issues
        patterns = [
            r"(?:^|\n)\d+\.\s*(.+?)(?=\n\d+\.|\n\n|$)",
            r"(?:^|\n)[-*]\s*(.+?)(?=\n[-*]|\n\n|$)",
            r"(?:Issue|Problem|Error|Warning):\s*(.+?)(?=\n|$)"
        ]

        for pattern in patterns:
            matches = re.findall(pattern, text, re.MULTILINE | re.IGNORECASE)
            for match in matches:
                issues.append({
                    "description": match.strip(),
                    "severity": self._infer_severity(match)
                })

        return issues

    def _extract_suggestions_from_text(self, text: str) -> list[str]:
        """Extract suggestions from unstructured text."""
        suggestions = []
        import re

        patterns = [
            r"(?:Suggest(?:ion)?|Recommend(?:ation)?|Fix):\s*(.+?)(?=\n|$)",
            r"(?:Consider|Should|Could)\s+(.+?)(?=\n|$)"
        ]

        for pattern in patterns:
            matches = re.findall(pattern, text, re.IGNORECASE)
            suggestions.extend([m.strip() for m in matches])

        return suggestions

    def _infer_severity(self, text: str) -> str:
        """Infer severity from text content."""
        text_lower = text.lower()

        if any(word in text_lower for word in ["critical", "severe", "security", "vulnerability"]):
            return "error"
        elif any(word in text_lower for word in ["warning", "potential", "might", "could"]):
            return "warning"
        elif any(word in text_lower for word in ["suggestion", "consider", "minor"]):
            return "suggestion"
        else:
            return "info"

    def close(self):
        """Close the HTTP clients."""
        self._client.close()

    async def close_async(self):
        """Close the async HTTP client."""
        await self._async_client.aclose()
