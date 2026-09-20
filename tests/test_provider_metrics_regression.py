from __future__ import annotations

from types import SimpleNamespace
import unittest
from unittest.mock import patch

from openai import APITimeoutError

from config.settings import AISettings
from services.model_providers import DeepSeekAdapter, ModelProviderError


class SequentialClientFactory:
    def __init__(self, *outcomes) -> None:
        self.outcomes = list(outcomes)

    def __call__(self, **kwargs):
        def create(**request_kwargs):
            outcome = self.outcomes.pop(0)
            if isinstance(outcome, BaseException):
                raise outcome
            return SimpleNamespace(
                model=request_kwargs["model"],
                usage=SimpleNamespace(
                    prompt_tokens=3,
                    completion_tokens=4,
                    completion_tokens_details=SimpleNamespace(reasoning_tokens=0),
                ),
                choices=[SimpleNamespace(
                    finish_reason="stop",
                    message=SimpleNamespace(content=outcome),
                )],
            )

        return SimpleNamespace(
            chat=SimpleNamespace(completions=SimpleNamespace(create=create)),
        )


class ProviderMetricsRegressionTests(unittest.TestCase):
    @staticmethod
    def _provider(factory: SequentialClientFactory) -> DeepSeekAdapter:
        return DeepSeekAdapter(
            AISettings(provider="deepseek", api_key="test-key"),
            client_factory=factory,
        )

    def test_failed_call_starts_fresh_metrics_and_records_latency_and_error(self) -> None:
        factory = SequentialClientFactory('{"ok": true}', APITimeoutError(request=None))
        provider = self._provider(factory)

        self.assertEqual(provider.chat_completion_json([]), {"ok": True})
        with self.assertRaisesRegex(ModelProviderError, "AI request timed out"):
            provider.chat_completion_json([])

        metrics = provider.last_call_metrics
        self.assertFalse(metrics["api_success"])
        self.assertIsNone(metrics["json_parse_success"])
        self.assertIsNone(metrics["input_tokens"])
        self.assertIsNone(metrics["output_tokens"])
        self.assertIsInstance(metrics["latency_ms"], float)
        self.assertGreaterEqual(metrics["latency_ms"], 0)
        self.assertIn("timed out", metrics["error"])

    def test_non_object_json_marks_parse_failure(self) -> None:
        factory = SequentialClientFactory('{"ok": true}', '[1, 2, 3]')
        provider = self._provider(factory)

        provider.chat_completion_json([])
        with self.assertRaisesRegex(ModelProviderError, "must be an object"):
            provider.chat_completion_json([])

        metrics = provider.last_call_metrics
        self.assertTrue(metrics["api_success"])
        self.assertFalse(metrics["json_parse_success"])
        self.assertIn("must be an object", metrics["error"])
        self.assertIsInstance(metrics["latency_ms"], float)

    def test_error_logs_are_redacted_and_bounded(self) -> None:
        response = "safe-prefix-" + ("x" * 900) + "PRIVATE_RESPONSE_SENTINEL"
        provider = self._provider(SequentialClientFactory(response))

        with patch("services.model_providers.logger") as logger:
            with self.assertRaises(ModelProviderError):
                provider.chat_completion_json([])

        logger.error.assert_called()
        rendered = " ".join(str(part) for call in logger.error.call_args_list for part in call.args)
        self.assertNotIn("PRIVATE_RESPONSE_SENTINEL", rendered)
        self.assertLess(len(rendered), 1200)

    def test_unexpected_exception_logs_are_redacted_and_bounded(self) -> None:
        exception = RuntimeError("sk-provider-exception-" + ("x" * 900))
        provider = self._provider(SequentialClientFactory(exception))

        with patch("services.model_providers.logger") as logger:
            with self.assertRaisesRegex(ModelProviderError, "Unexpected AI error"):
                provider.chat_completion_json([])

        logger.error.assert_called()
        rendered = " ".join(str(part) for call in logger.error.call_args_list for part in call.args)
        self.assertNotIn("sk-provider-exception", rendered)
        self.assertLess(len(rendered), 1200)


if __name__ == "__main__":
    unittest.main()
