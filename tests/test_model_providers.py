from __future__ import annotations

import os
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from config.settings import AISettings, get_settings, load_repository_env
from services.ai_client import AIClient
from services.intent_parser import IntentParser
from services.model_providers import (
    DeepSeekAdapter,
    GeminiAdapter,
    GLMAdapter,
    ModelProviderError,
    create_model_provider,
)


class RecordingClientFactory:
    def __init__(
        self,
        content: str = '{"ok": true}',
        finish_reason: str = "stop",
    ) -> None:
        self.content = content
        self.finish_reason = finish_reason
        self.init_kwargs: dict = {}
        self.request_kwargs: dict = {}

    def __call__(self, **kwargs):
        self.init_kwargs = kwargs

        def create(**request_kwargs):
            self.request_kwargs = request_kwargs
            return SimpleNamespace(
                model=request_kwargs["model"],
                usage=SimpleNamespace(
                    prompt_tokens=10,
                    completion_tokens=5,
                    completion_tokens_details=SimpleNamespace(reasoning_tokens=0),
                ),
                choices=[SimpleNamespace(
                    finish_reason=self.finish_reason,
                    message=SimpleNamespace(content=self.content),
                )]
            )

        return SimpleNamespace(
            chat=SimpleNamespace(completions=SimpleNamespace(create=create))
        )


class ModelProviderTests(unittest.TestCase):
    def test_repository_dotenv_loads_without_overriding_process_environment(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            env_path = Path(directory) / ".env"
            env_path.write_text(
                "EXISTING_SETTING=from-file\nNEW_DOTENV_SETTING=loaded\n",
                encoding="utf-8",
            )
            with patch.dict(os.environ, {"EXISTING_SETTING": "from-process"}, clear=False):
                load_repository_env(env_path)
                self.assertEqual(os.getenv("EXISTING_SETTING"), "from-process")
                self.assertEqual(os.getenv("NEW_DOTENV_SETTING"), "loaded")

    def test_deepseek_adapter_uses_selected_configuration(self) -> None:
        factory = RecordingClientFactory()
        settings = AISettings(
            provider="deepseek",
            api_key="deepseek-test-key",
            base_url="https://deepseek.test/v1",
            model="deepseek-test-model",
        )

        provider = create_model_provider(settings, client_factory=factory)
        payload = provider.chat_completion_json([{"role": "user", "content": "test"}])

        self.assertIsInstance(provider, DeepSeekAdapter)
        self.assertEqual(payload, {"ok": True})
        self.assertEqual(factory.init_kwargs["api_key"], "deepseek-test-key")
        self.assertEqual(factory.init_kwargs["base_url"], "https://deepseek.test/v1")
        self.assertEqual(factory.request_kwargs["model"], "deepseek-test-model")
        self.assertEqual(factory.request_kwargs["response_format"], {"type": "json_object"})
        self.assertEqual(factory.request_kwargs["max_tokens"], 16384)
        self.assertEqual(
            factory.request_kwargs["extra_body"],
            {"thinking": {"type": "disabled"}},
        )
        self.assertTrue(provider.last_call_metrics["api_success"])
        self.assertTrue(provider.last_call_metrics["json_parse_success"])
        self.assertEqual(provider.last_call_metrics["input_tokens"], 10)
        self.assertEqual(provider.last_call_metrics["output_tokens"], 5)
        self.assertEqual(provider.last_call_metrics["reasoning_tokens"], 0)

    def test_glm_adapter_uses_selected_configuration(self) -> None:
        factory = RecordingClientFactory()
        settings = AISettings(
            provider="glm",
            api_key="glm-test-key",
            base_url="https://glm.test/v4",
            model="glm-test-model",
        )

        provider = create_model_provider(settings, client_factory=factory)
        provider.chat_completion_json([{"role": "user", "content": "test"}])

        self.assertIsInstance(provider, GLMAdapter)
        self.assertEqual(factory.init_kwargs["api_key"], "glm-test-key")
        self.assertEqual(factory.init_kwargs["base_url"], "https://glm.test/v4")
        self.assertEqual(factory.request_kwargs["model"], "glm-test-model")
        self.assertEqual(factory.request_kwargs["response_format"], {"type": "json_object"})
        self.assertNotIn("extra_body", factory.request_kwargs)

    def test_gemini_adapter_uses_selected_configuration(self) -> None:
        factory = RecordingClientFactory()
        settings = AISettings(
            provider="gemini",
            api_key="gemini-test-key",
            base_url="https://generativelanguage.googleapis.test/v1beta/openai/",
            model="gemini-test-model",
        )

        provider = create_model_provider(settings, client_factory=factory)
        payload = provider.chat_completion_json([{"role": "user", "content": "Return JSON."}])

        self.assertIsInstance(provider, GeminiAdapter)
        self.assertEqual(payload, {"ok": True})
        self.assertEqual(factory.init_kwargs["api_key"], "gemini-test-key")
        self.assertEqual(
            factory.init_kwargs["base_url"],
            "https://generativelanguage.googleapis.test/v1beta/openai/",
        )
        self.assertEqual(factory.request_kwargs["model"], "gemini-test-model")
        self.assertEqual(factory.request_kwargs["response_format"], {"type": "json_object"})
        self.assertNotIn("extra_body", factory.request_kwargs)

    def test_gemini_adapter_sends_strict_json_schema_when_supplied(self) -> None:
        factory = RecordingClientFactory()
        provider = GeminiAdapter(
            AISettings(provider="gemini", api_key="test"),
            client_factory=factory,
        )
        schema = {
            "type": "object",
            "additionalProperties": False,
            "required": ["ok"],
            "properties": {"ok": {"type": "boolean"}},
        }

        provider.chat_completion_json(
            [{"role": "user", "content": "Return JSON."}],
            json_schema=schema,
            schema_name="smoke_contract",
        )

        self.assertTrue(provider.supports_json_schema)
        self.assertEqual(
            factory.request_kwargs["response_format"],
            {
                "type": "json_schema",
                "json_schema": {
                    "name": "smoke_contract",
                    "strict": True,
                    "schema": schema,
                },
            },
        )

    def test_truncated_structured_response_fails_with_explicit_error(self) -> None:
        factory = RecordingClientFactory(
            content='{"partial": "unterminated',
            finish_reason="length",
        )
        provider = GeminiAdapter(
            AISettings(provider="gemini", api_key="test"),
            client_factory=factory,
        )

        with self.assertRaisesRegex(ModelProviderError, "structured response was truncated"):
            provider.chat_completion_json(
                [{"role": "user", "content": "Return JSON."}],
                json_schema={"type": "object"},
            )

        self.assertTrue(provider.last_call_metrics["output_truncated"])
        self.assertEqual(provider.last_call_metrics["finish_reason"], "length")

    def test_deepseek_thinking_mode_can_be_enabled_by_configuration(self) -> None:
        factory = RecordingClientFactory()
        provider = DeepSeekAdapter(
            AISettings(api_key="test", thinking_enabled=True),
            client_factory=factory,
        )

        provider.chat_completion_json([{"role": "user", "content": "Return JSON."}])

        self.assertEqual(
            factory.request_kwargs["extra_body"],
            {"thinking": {"type": "enabled"}},
        )

    def test_ai_client_facade_exposes_selected_provider(self) -> None:
        provider = GLMAdapter(
            AISettings(provider="glm", api_key="test"),
            client_factory=RecordingClientFactory(),
        )
        client = AIClient(provider=provider)

        self.assertTrue(client.is_available)
        self.assertEqual(client.provider_name, "glm")
        self.assertEqual(client.chat_completion_json([]), {"ok": True})

    def test_unknown_provider_fails_fast(self) -> None:
        with self.assertRaisesRegex(ModelProviderError, "Unsupported AI provider"):
            create_model_provider(AISettings(provider="unknown", api_key="test"))

    def test_environment_switches_to_glm_credentials(self) -> None:
        env = {
            "AI_PROVIDER": "glm",
            "GLM_API_KEY": "glm-env-key",
            "GLM_BASE_URL": "https://glm.env/v4",
            "GLM_MODEL": "glm-env-model",
            "DEEPSEEK_API_KEY": "must-not-be-selected",
        }
        get_settings.cache_clear()
        try:
            with patch.dict(os.environ, env, clear=False):
                settings = get_settings().ai
                self.assertEqual(settings.provider, "glm")
                self.assertEqual(settings.api_key, "glm-env-key")
                self.assertEqual(settings.base_url, "https://glm.env/v4")
                self.assertEqual(settings.model, "glm-env-model")
        finally:
            get_settings.cache_clear()

    def test_environment_switches_to_deepseek_credentials(self) -> None:
        env = {
            "AI_PROVIDER": "deepseek",
            "DEEPSEEK_API_KEY": "deepseek-env-key",
            "DEEPSEEK_BASE_URL": "https://deepseek.env/v1",
            "DEEPSEEK_MODEL": "deepseek-env-model",
            "GLM_API_KEY": "must-not-be-selected",
        }
        get_settings.cache_clear()
        try:
            with patch.dict(os.environ, env, clear=False):
                settings = get_settings().ai
                self.assertEqual(settings.provider, "deepseek")
                self.assertEqual(settings.api_key, "deepseek-env-key")
                self.assertEqual(settings.base_url, "https://deepseek.env/v1")
                self.assertEqual(settings.model, "deepseek-env-model")
        finally:
            get_settings.cache_clear()

    def test_environment_switches_to_gemini_credentials(self) -> None:
        env = {
            "AI_PROVIDER": "gemini",
            "GEMINI_API_KEY": "gemini-env-key",
            "GEMINI_BASE_URL": "https://gemini.env/v1beta/openai/",
            "GEMINI_MODEL": "gemini-env-model",
            "DEEPSEEK_API_KEY": "must-not-be-selected",
            "GLM_API_KEY": "must-not-be-selected",
        }
        get_settings.cache_clear()
        try:
            with patch.dict(os.environ, env, clear=False):
                settings = get_settings().ai
                self.assertEqual(settings.provider, "gemini")
                self.assertEqual(settings.api_key, "gemini-env-key")
                self.assertEqual(settings.base_url, "https://gemini.env/v1beta/openai/")
                self.assertEqual(settings.model, "gemini-env-model")
        finally:
            get_settings.cache_clear()

    def test_intent_parser_reports_gemini_without_business_logic_changes(self) -> None:
        class GeminiIntentClient:
            is_available = True
            provider_name = "gemini"

            @staticmethod
            def chat_completion_json(messages):
                return {
                    "budget": None,
                    "traffic_level": "NORMAL",
                    "promotion_flag": False,
                    "shelf_life_preference": "NORMAL",
                    "preferred_category": None,
                    "excluded_category": None,
                    "time_range": "normal",
                    "expected_intent": "Normal replenishment.",
                }

        result = IntentParser(ai_client=GeminiIntentClient()).parse_intent(
            "Normal replenishment"
        )

        self.assertEqual(result["AIAnalysisStatus"], "live")
        self.assertEqual(result["AIAnalysisSource"], "Gemini")

    def test_intent_parser_reports_glm_without_business_logic_changes(self) -> None:
        class GLMIntentClient:
            is_available = True
            provider_name = "glm"

            @staticmethod
            def chat_completion_json(messages):
                return {
                    "budget": None,
                    "traffic_level": "NORMAL",
                    "promotion_flag": False,
                    "shelf_life_preference": "NORMAL",
                    "preferred_category": None,
                    "excluded_category": None,
                    "time_range": "normal",
                    "expected_intent": "Normal replenishment.",
                }

        result = IntentParser(ai_client=GLMIntentClient()).parse_intent("Normal replenishment")

        self.assertEqual(result["AIAnalysisStatus"], "live")
        self.assertEqual(result["AIAnalysisSource"], "GLM")


if __name__ == "__main__":
    unittest.main()
