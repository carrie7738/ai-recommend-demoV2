from __future__ import annotations

import json
import logging
from typing import Any

from openai import OpenAI, APIError, APITimeoutError

from config.settings import get_settings, AISettings

logger = logging.getLogger(__name__)


class AIClientError(Exception):
    """Raised when AI client encounters an error."""


class AIClient:
    """DeepSeek API client with fallback support."""

    def __init__(self, settings: AISettings | None = None) -> None:
        self.settings = settings or get_settings().ai
        self._client: OpenAI | None = None

    @property
    def is_available(self) -> bool:
        return self.settings.enabled and bool(self.settings.api_key)

    def _get_client(self) -> OpenAI:
        if self._client is None:
            if not self.is_available:
                raise AIClientError("AI client is not configured. Set DEEPSEEK_API_KEY in config.")
            self._client = OpenAI(
                api_key=self.settings.api_key,
                base_url=self.settings.base_url,
            )
        return self._client

    def chat_completion(
        self,
        messages: list[dict[str, str]],
        response_format: dict[str, Any] | None = None,
    ) -> str:
        if not self.is_available:
            raise AIClientError("AI client is not available.")

        try:
            client = self._get_client()
            kwargs: dict[str, Any] = {
                "model": self.settings.model,
                "messages": messages,
                "temperature": self.settings.temperature,
                "max_tokens": self.settings.max_tokens,
            }
            if response_format:
                kwargs["response_format"] = response_format

            response = client.chat.completions.create(**kwargs)
            return response.choices[0].message.content or ""

        except APITimeoutError as exc:
            logger.error("AI API timeout: %s", exc)
            raise AIClientError("AI request timed out.") from exc
        except APIError as exc:
            logger.error("AI API error: %s", exc)
            raise AIClientError(f"AI API error: {exc}") from exc
        except Exception as exc:
            logger.exception("Unexpected AI client error.")
            raise AIClientError(f"Unexpected error: {exc}") from exc

    def chat_completion_json(
        self,
        messages: list[dict[str, str]],
    ) -> dict[str, Any]:
        response = self.chat_completion(
            messages,
            response_format={"type": "json_object"},
        )
        try:
            return json.loads(response)
        except json.JSONDecodeError as exc:
            logger.error("Failed to parse AI JSON response: %s", response)
            raise AIClientError(f"Invalid JSON response from AI: {exc}") from exc
