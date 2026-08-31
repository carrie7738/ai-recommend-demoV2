from __future__ import annotations

from typing import Any

from config.settings import get_settings, AISettings
from services.model_providers import (
    ModelProvider,
    ModelProviderError,
    create_model_provider,
)

AIClientError = ModelProviderError


class AIClient:
    """Backward-compatible facade over the configured model provider."""

    def __init__(
        self,
        settings: AISettings | None = None,
        provider: ModelProvider | None = None,
    ) -> None:
        self.settings = settings or get_settings().ai
        self.provider = provider or create_model_provider(self.settings)

    @property
    def provider_name(self) -> str:
        return self.provider.provider_name

    @property
    def is_available(self) -> bool:
        return self.provider.is_available

    @property
    def supports_json_schema(self) -> bool:
        return bool(getattr(self.provider, "supports_json_schema", False))

    @property
    def last_call_metrics(self) -> dict[str, Any]:
        return dict(getattr(self.provider, "last_call_metrics", {}))

    def chat_completion(
        self,
        messages: list[dict[str, str]],
        response_format: dict[str, Any] | None = None,
    ) -> str:
        return self.provider.chat_completion(messages, response_format=response_format)

    def chat_completion_json(
        self,
        messages: list[dict[str, str]],
        json_schema: dict[str, Any] | None = None,
        schema_name: str = "structured_response",
    ) -> dict[str, Any]:
        return self.provider.chat_completion_json(
            messages,
            json_schema=json_schema,
            schema_name=schema_name,
        )
