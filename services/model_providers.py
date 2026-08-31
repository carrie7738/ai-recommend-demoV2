from __future__ import annotations

import json
import logging
import time
from typing import Any, Protocol

from openai import APIError, APITimeoutError, OpenAI

from config.settings import AISettings, get_settings

logger = logging.getLogger(__name__)


class ModelProviderError(Exception):
    """Raised when a configured model provider cannot complete a request."""


class ModelProvider(Protocol):
    """Small provider-neutral contract used by business services."""

    provider_name: str
    last_call_metrics: dict[str, Any]

    @property
    def is_available(self) -> bool: ...

    @property
    def supports_json_schema(self) -> bool: ...

    def chat_completion(
        self,
        messages: list[dict[str, str]],
        response_format: dict[str, Any] | None = None,
        max_tokens: int | None = None,
    ) -> str: ...

    def chat_completion_json(
        self,
        messages: list[dict[str, str]],
        json_schema: dict[str, Any] | None = None,
        schema_name: str = "structured_response",
    ) -> dict[str, Any]: ...


class OpenAICompatibleProvider:
    """Shared transport for providers exposing OpenAI-compatible chat completions."""

    provider_name = "openai-compatible"

    def __init__(
        self,
        settings: AISettings,
        client_factory: Any = OpenAI,
    ) -> None:
        self.settings = settings
        self._client_factory = client_factory
        self._client: Any | None = None
        self.last_call_metrics: dict[str, Any] = {}

    @property
    def is_available(self) -> bool:
        return self.settings.enabled and bool(self.settings.api_key)

    @property
    def supports_json_schema(self) -> bool:
        return False

    def _get_client(self) -> Any:
        if self._client is None:
            if not self.is_available:
                raise ModelProviderError(
                    f"{self.provider_name} is not configured. Set its API key in config."
                )
            self._client = self._client_factory(
                api_key=self.settings.api_key,
                base_url=self.settings.base_url,
            )
        return self._client

    def chat_completion(
        self,
        messages: list[dict[str, str]],
        response_format: dict[str, Any] | None = None,
        max_tokens: int | None = None,
    ) -> str:
        if not self.is_available:
            raise ModelProviderError(f"{self.provider_name} is not available.")

        try:
            started = time.perf_counter()
            kwargs: dict[str, Any] = {
                "model": self.settings.model,
                "messages": messages,
                "temperature": self.settings.temperature,
                "max_tokens": max_tokens or self.settings.max_tokens,
            }
            kwargs.update(self._provider_request_options())
            if response_format:
                kwargs["response_format"] = response_format
            response = self._get_client().chat.completions.create(**kwargs)
            elapsed_ms = round((time.perf_counter() - started) * 1000, 1)
            usage = getattr(response, "usage", None)
            details = getattr(usage, "completion_tokens_details", None)
            finish_reason = getattr(response.choices[0], "finish_reason", None)
            output_truncated = str(finish_reason or "").casefold() in {
                "length",
                "max_tokens",
            }
            self.last_call_metrics = {
                "provider": self.provider_name,
                "model": str(getattr(response, "model", None) or self.settings.model),
                "api_success": True,
                "latency_ms": elapsed_ms,
                "input_tokens": getattr(usage, "prompt_tokens", None),
                "output_tokens": getattr(usage, "completion_tokens", None),
                "reasoning_tokens": getattr(details, "reasoning_tokens", None),
                "finish_reason": finish_reason,
                "output_truncated": output_truncated,
                "json_parse_success": None,
            }
            content = response.choices[0].message.content or ""
            if output_truncated:
                raise ModelProviderError(
                    "AI structured response was truncated at the configured output-token limit "
                    f"(finish_reason={finish_reason}, max_tokens={kwargs['max_tokens']})."
                )
            if not content.strip():
                raise ModelProviderError(
                    f"AI returned empty content (finish_reason={finish_reason})."
                )
            return content
        except APITimeoutError as exc:
            logger.error("%s API timeout: %s", self.provider_name, exc)
            raise ModelProviderError("AI request timed out.") from exc
        except APIError as exc:
            logger.error("%s API error: %s", self.provider_name, exc)
            raise ModelProviderError(f"AI API error: {exc}") from exc
        except ModelProviderError:
            raise
        except Exception as exc:
            logger.exception("Unexpected %s client error.", self.provider_name)
            raise ModelProviderError(f"Unexpected AI error: {exc}") from exc

    def chat_completion_json(
        self,
        messages: list[dict[str, str]],
        json_schema: dict[str, Any] | None = None,
        schema_name: str = "structured_response",
    ) -> dict[str, Any]:
        response = self.chat_completion(
            messages,
            response_format=self._json_response_format(json_schema, schema_name),
            max_tokens=self.settings.structured_max_tokens,
        )
        try:
            payload = json.loads(response)
        except json.JSONDecodeError as exc:
            self.last_call_metrics["json_parse_success"] = False
            logger.error("Failed to parse %s JSON response: %s", self.provider_name, response)
            raise ModelProviderError(f"Invalid JSON response from AI: {exc}") from exc
        if not isinstance(payload, dict):
            raise ModelProviderError("AI JSON response must be an object.")
        self.last_call_metrics["json_parse_success"] = True
        return payload

    def _json_response_format(
        self,
        json_schema: dict[str, Any] | None,
        schema_name: str,
    ) -> dict[str, Any]:
        return {"type": "json_object"}

    def _provider_request_options(self) -> dict[str, Any]:
        return {}


class DeepSeekAdapter(OpenAICompatibleProvider):
    provider_name = "deepseek"

    def _provider_request_options(self) -> dict[str, Any]:
        return {
            "extra_body": {
                "thinking": {
                    "type": "enabled" if self.settings.thinking_enabled else "disabled"
                }
            }
        }


class GLMAdapter(OpenAICompatibleProvider):
    provider_name = "glm"


class GeminiAdapter(OpenAICompatibleProvider):
    provider_name = "gemini"

    @property
    def supports_json_schema(self) -> bool:
        return True

    def _json_response_format(
        self,
        json_schema: dict[str, Any] | None,
        schema_name: str,
    ) -> dict[str, Any]:
        if json_schema is None:
            return super()._json_response_format(json_schema, schema_name)
        return {
            "type": "json_schema",
            "json_schema": {
                "name": schema_name,
                "strict": True,
                "schema": json_schema,
            },
        }


def create_model_provider(
    settings: AISettings | None = None,
    client_factory: Any = OpenAI,
) -> ModelProvider:
    resolved = settings or get_settings().ai
    provider = resolved.provider.strip().lower()
    adapters = {
        "deepseek": DeepSeekAdapter,
        "gemini": GeminiAdapter,
        "glm": GLMAdapter,
    }
    adapter = adapters.get(provider)
    if adapter is None:
        supported = ", ".join(sorted(adapters))
        raise ModelProviderError(
            f"Unsupported AI provider: {resolved.provider!r}. Supported providers: {supported}."
        )
    return adapter(resolved, client_factory=client_factory)
