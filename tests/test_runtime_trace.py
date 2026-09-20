from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
import json
from pathlib import Path
import unittest

import pandas as pd

from config.settings import AISettings
from services.ai_decision import AIDecisionLayer
from services.hard_validator import HardValidator
from services.intent_parser import IntentParser
from services.model_providers import (
    DeepSeekAdapter,
    ModelProviderError,
)
from services.runtime_trace import (
    _active,
    capture_trace,
    model_stage,
    observed,
    record,
    snapshot,
)
from services.v2_decision_pipeline import V2DecisionPipeline
from services.v2_preparation import V2PreparationPipeline
from tests.test_ai_decision import ContractDecisionClient, OfflineAIClient
from tests.test_model_providers import RecordingClientFactory
from tests.test_v2_resilience import StaticClientFactory
from openai import APITimeoutError


WORKBOOK_PATH = Path(__file__).resolve().parents[1] / "data" / "AI_Demo_Data_Pack_V2_Large.xlsx"


class RuntimeTraceUnitTests(unittest.TestCase):
    def test_record_and_observed_are_no_ops_without_capture(self) -> None:
        calls = []

        @observed("unit", "Test")
        def identity(value):
            calls.append(value)
            return value

        payload = {"api_key": "kept-in-function-input"}
        self.assertIsNone(_active.get())
        self.assertIs(identity(payload), payload)
        record("unit", "Test", input=payload, output=payload)

        self.assertEqual(calls, [payload])
        self.assertIsNone(_active.get())
        self.assertEqual(model_stage(), "decision")

    def test_record_snapshots_inputs_before_the_original_is_mutated(self) -> None:
        payload = {
            "nested": {"items": ["before"], "mutable": {"value": 1}},
            "tuple": ("first", {"value": 2}),
        }

        with capture_trace() as trace:
            record("snapshot", "Test", input=payload)
            payload["nested"]["items"].append("after")
            payload["nested"]["mutable"]["value"] = 99
            payload["tuple"][1]["value"] = 100

        event_input = trace["events"][0]["input"]
        self.assertEqual(event_input["nested"], {
            "items": ["before"],
            "mutable": {"value": 1},
        })
        self.assertEqual(event_input["tuple"], ["first", {"value": 2}])

    def test_nested_capture_contexts_are_isolated_and_restore_the_outer_trace(self) -> None:
        with capture_trace() as outer:
            record("outer_before", "Test")

            with capture_trace() as inner:
                record("inner", "Test")
                self.assertEqual(
                    [event["stage"] for event in outer["events"]],
                    ["outer_before"],
                )

            record("outer_after", "Test")

        self.assertEqual(
            [event["stage"] for event in outer["events"]],
            ["outer_before", "outer_after"],
        )
        self.assertEqual([event["stage"] for event in inner["events"]], ["inner"])

    def test_exception_is_preserved_and_context_is_restored(self) -> None:
        observed_stages = []

        @observed("intent_output", "Test")
        def fail_inside_capture():
            observed_stages.append(model_stage())
            raise RuntimeError("trace failure")

        with capture_trace() as outer:
            record("outer_before", "Test")
            with self.assertRaisesRegex(RuntimeError, "trace failure"):
                with capture_trace() as inner:
                    record("inner_before_failure", "Test")
                    fail_inside_capture()

            self.assertEqual(model_stage(), "decision")
            record("outer_after", "Test")

        self.assertEqual(observed_stages, ["intent"])
        self.assertEqual(
            [event["stage"] for event in outer["events"]],
            ["outer_before", "outer_after"],
        )
        self.assertEqual(
            [event["stage"] for event in inner["events"]],
            ["inner_before_failure", "intent_output"],
        )
        self.assertEqual(inner["events"][-1]["status"], "failed")
        self.assertEqual(inner["events"][-1]["error"], "trace failure")
        self.assertEqual(model_stage(), "decision")

    def test_snapshot_failure_does_not_replace_a_successful_result(self) -> None:
        class SnapshotFailure:
            def __str__(self):
                raise RuntimeError("snapshot failure")

        @observed("unit", "Test")
        def successful_business_function():
            return {"payload": SnapshotFailure()}

        with capture_trace() as trace:
            result = successful_business_function()

        self.assertIsInstance(result["payload"], SnapshotFailure)
        self.assertEqual(
            trace["events"][-1]["output"]["payload"],
            "[REDACTED: snapshot unavailable]",
        )

    def test_validation_snapshot_failure_does_not_prevent_business_function(self) -> None:
        class SnapshotFailure:
            def __str__(self):
                raise RuntimeError("snapshot failure")

        called = []

        @observed("validation", "Test")
        def validate(optimizer_result, violations, structured_intent):
            called.append(True)
            return {"valid": True}

        with capture_trace() as trace:
            result = validate({"value": SnapshotFailure()}, [], {})

        self.assertEqual(called, [True])
        self.assertEqual(result, {"valid": True})
        self.assertEqual(
            trace["events"][-1]["input"]["optimizer_result"]["value"],
            "[REDACTED: snapshot unavailable]",
        )

    def test_exception_with_failing_string_conversion_is_not_replaced(self) -> None:
        class OriginalFailure(Exception):
            def __str__(self):
                raise RuntimeError("error rendering failure")

        @observed("unit", "Test")
        def fail():
            raise OriginalFailure()

        with capture_trace() as trace:
            with self.assertRaises(OriginalFailure):
                fail()

        self.assertEqual(
            trace["events"][-1]["error"],
            "[REDACTED: error unavailable]",
        )

    def test_sensitive_fields_and_inline_tokens_are_redacted(self) -> None:
        payload = {
            "api_key": "plain-api-key",
            "authorization": "Bearer auth-token",
            "private_key": "private-key-field-value",
            "nested": {
                "password": "password-value",
                "access_token": "access-value",
                "header": "Authorization: Bearer bearer-value",
            },
            "notes": "raw sk-proj-ABC_123 appears here; private_key=inline-private-key",
            "pem": (
                "before -----BEGIN PRIVATE KEY-----\n"
                "private-pem-value\n"
                "-----END PRIVATE KEY----- after"
            ),
        }

        with capture_trace() as trace:
            record("sensitive", "Test", input=payload, output=payload)

        event = trace["events"][0]
        serialized = json.dumps(trace, ensure_ascii=False)
        for secret in (
            "plain-api-key",
            "auth-token",
            "password-value",
            "access-value",
            "bearer-value",
            "sk-proj-ABC_123",
            "private-key-field-value",
            "inline-private-key",
            "private-pem-value",
        ):
            self.assertNotIn(secret, serialized)

        self.assertEqual(event["input"]["api_key"], "[REDACTED]")
        self.assertEqual(event["input"]["authorization"], "[REDACTED]")
        self.assertEqual(event["input"]["private_key"], "[REDACTED]")
        self.assertEqual(event["input"]["nested"]["password"], "[REDACTED]")
        self.assertIn("[REDACTED]", event["input"]["nested"]["header"])
        self.assertIn("[REDACTED]", event["input"]["notes"])

    def test_trace_snapshot_is_json_serializable(self) -> None:
        payload = {
            "when": datetime(2026, 9, 4, 12, 30, tzinfo=timezone.utc),
            "timestamp": pd.Timestamp("2026-09-04 12:30"),
            "nan": float("nan"),
            "infinity": float("inf"),
            "tuple": ("value", 2),
        }

        with capture_trace() as trace:
            record("json", "Test", input=payload)

        json.dumps(trace, ensure_ascii=False)
        self.assertIsNone(trace["events"][0]["input"]["nan"])
        self.assertIsNone(trace["events"][0]["input"]["infinity"])

    def test_validation_argument_binding_failure_is_recorded(self) -> None:
        with capture_trace() as trace:
            with self.assertRaises(TypeError):
                HardValidator().validate({}, {}, [], {})

        validation_events = [
            event for event in trace["events"]
            if event["stage"] == "validation" and event["owner"] == "Validator"
        ]
        self.assertEqual(len(validation_events), 1)
        self.assertEqual(validation_events[0]["operation"], "validate")
        self.assertEqual(validation_events[0]["status"], "failed")
        self.assertIn("missing", validation_events[0]["error"])
        self.assertIsNone(validation_events[0]["input"])
        self.assertEqual(model_stage(), "decision")

    def test_inline_auth_forms_and_stringified_objects_are_redacted(self) -> None:
        class StringifiedSecret:
            def __str__(self):
                return (
                    "token=object-token cookie=object-cookie "
                    "credential=object-credential"
                )

        payload = {
            "notes": (
                "token=inline-token cookie=inline-cookie "
                "credential=inline-credential "
                "Authorization: Basic dXNlcjpwYXNz"
            ),
            "object": StringifiedSecret(),
        }

        with capture_trace() as trace:
            record("sensitive_inline", "Test", input=payload)

        serialized = json.dumps(trace, ensure_ascii=False)
        for secret in (
            "inline-token",
            "inline-cookie",
            "inline-credential",
            "dXNlcjpwYXNz",
            "object-token",
            "object-cookie",
            "object-credential",
        ):
            self.assertNotIn(secret, serialized)
        self.assertIn("[REDACTED]", serialized)


class RetryDecisionClient(ContractDecisionClient):
    """Use the existing decision fixture, then drop the conflicting candidate on retry."""

    def __init__(self) -> None:
        super().__init__()
        self.calls = 0

    def chat_completion_json(self, messages):
        self.calls += 1
        result = super().chat_completion_json(messages)
        for decision in result["candidate_decisions"]:
            if self.calls == 1:
                decision["recommended"] = True
                decision["priority"] = "HIGH"
            else:
                decision["recommended"] = False
                decision["priority"] = "LOW"
        return result


class RuntimeTracePipelineTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.workbook = pd.read_excel(WORKBOOK_PATH, sheet_name=None, engine="openpyxl")

    @staticmethod
    def _success_pipeline() -> V2DecisionPipeline:
        return V2DecisionPipeline(
            preparation=V2PreparationPipeline(
                intent_parser=IntentParser(ai_client=OfflineAIClient())
            ),
            decision_layer=AIDecisionLayer(ai_client=ContractDecisionClient()),
        )

    def _run_success(self, captured: bool):
        pipeline = self._success_pipeline()
        workbook = deepcopy(self.workbook)
        if captured:
            with capture_trace() as trace:
                result = pipeline.run(
                    workbook,
                    "C051",
                    "Please purchase V2 Requested Specialty Drink.",
                    "2026-06-02",
                )
            return result, trace
        return pipeline.run(
            workbook,
            "C051",
            "Please purchase V2 Requested Specialty Drink.",
            "2026-06-02",
        ), None

    def test_capture_toggle_keeps_success_result_and_stage_events(self) -> None:
        without_trace, _ = self._run_success(captured=False)
        with_trace, trace = self._run_success(captured=True)

        self.assertEqual(with_trace, without_trace)
        self.assertEqual(with_trace["v2_status"], "SUCCESS")
        self.assertTrue(any(
            event["stage"] == "decision_input" and event["owner"] == "AI"
            for event in trace["events"]
        ))
        self.assertTrue(any(
            event["stage"] == "decision_output" and event["owner"] == "AI"
            for event in trace["events"]
        ))
        self.assertTrue(any(
            event["stage"] == "validation" and event["owner"] == "Validator"
            for event in trace["events"]
        ))
        self.assertTrue(any(
            event["stage"] == "final"
            and event["owner"] == "Workflow"
            and event.get("operation") == "run"
            for event in trace["events"]
        ))
        json.dumps(trace, ensure_ascii=False)

    def _run_retry(self, captured: bool):
        client = RetryDecisionClient()
        pipeline = V2DecisionPipeline(
            preparation=V2PreparationPipeline(
                intent_parser=IntentParser(ai_client=OfflineAIClient())
            ),
            decision_layer=AIDecisionLayer(ai_client=client),
        )
        workbook = deepcopy(self.workbook)
        if captured:
            with capture_trace() as trace:
                result = pipeline.run(
                    workbook,
                    "C051",
                    "Please purchase P209. Budget NZD 1.",
                    "2026-06-02",
                )
            return result, trace, client
        return pipeline.run(
            workbook,
            "C051",
            "Please purchase P209. Budget NZD 1.",
            "2026-06-02",
        ), None, client

    def test_capture_toggle_keeps_retry_result_and_retains_validation_decision_events(self) -> None:
        without_trace, _, without_client = self._run_retry(captured=False)
        with_trace, trace, with_client = self._run_retry(captured=True)

        self.assertEqual(with_trace, without_trace)
        self.assertEqual(with_trace["retry_count"], 1)
        self.assertEqual(without_client.calls, 2)
        self.assertEqual(with_client.calls, 2)

        validation_events = [
            event for event in trace["events"]
            if event["stage"] == "validation" and event["owner"] == "Validator"
        ]
        validation_statuses = [event["status"] for event in validation_events]
        self.assertIn("failed", validation_statuses)
        self.assertIn("success", validation_statuses)
        decision_requests = [
            event for event in trace["events"]
            if event["stage"] == "decision_output"
            and event["owner"] == "AI"
            and event.get("operation") == "_request_and_validate"
        ]
        self.assertEqual(len(decision_requests), 2)
        self.assertGreaterEqual(len(validation_events), 2)
        json.dumps(trace, ensure_ascii=False)


class RuntimeTraceProviderTests(unittest.TestCase):
    def test_provider_request_event_matches_sdk_kwargs_and_captures_raw_non_json_output(self) -> None:
        raw_content = "raw provider output sk-provider-secret"
        factory = RecordingClientFactory(content=raw_content)
        provider = DeepSeekAdapter(
            AISettings(
                provider="deepseek",
                api_key="provider-api-key",
                model="trace-test-model",
            ),
            client_factory=factory,
        )
        messages = [{
            "role": "user",
            "content": "Authorization: Bearer bearer-secret sk-inline-secret",
        }]

        with capture_trace() as trace:
            with self.assertRaisesRegex(ModelProviderError, "Invalid JSON response from AI"):
                provider.chat_completion_json(messages)

        request_events = [
            event for event in trace["events"]
            if event["owner"] == "Provider"
            and event.get("operation") == "actual_provider_request"
        ]
        self.assertEqual(len(request_events), 1)
        self.assertEqual(request_events[0]["status"], "started")
        self.assertEqual(request_events[0]["input"], snapshot(factory.request_kwargs))
        self.assertEqual(request_events[0]["input"]["messages"], snapshot(messages))

        response_events = [
            event for event in trace["events"]
            if event["owner"] == "Provider"
            and event.get("operation") == "actual_provider_response"
        ]
        self.assertEqual(len(response_events), 1)
        self.assertEqual(
            response_events[0]["output"]["raw_content"],
            "raw provider output [REDACTED]",
        )
        self.assertNotIn("sk-provider-secret", json.dumps(response_events[0]))
        self.assertFalse(provider.last_call_metrics["json_parse_success"])
        parse_events = [
            event for event in trace["events"]
            if event["owner"] == "Provider" and event.get("operation") == "json_parse"
        ]
        self.assertEqual(len(parse_events), 1)
        self.assertEqual(parse_events[0]["status"], "failed")
        json.dumps(trace, ensure_ascii=False)

    def test_provider_transport_failure_has_a_failed_provider_event(self) -> None:
        factory = StaticClientFactory(error=APITimeoutError(request=None))
        provider = DeepSeekAdapter(
            AISettings(provider="deepseek", api_key="provider-api-key"),
            client_factory=factory,
        )

        with capture_trace() as trace:
            with self.assertRaisesRegex(ModelProviderError, "AI request timed out"):
                provider.chat_completion_json([{"role": "user", "content": "Return JSON."}])

        request_events = [
            event for event in trace["events"]
            if event["owner"] == "Provider"
            and event.get("operation") == "actual_provider_request"
        ]
        failure_events = [
            event for event in trace["events"]
            if event["owner"] == "Provider"
            and event.get("operation") == "provider_failure"
        ]
        self.assertEqual(len(request_events), 1)
        self.assertEqual(request_events[0]["status"], "started")
        self.assertEqual(len(failure_events), 1)
        self.assertEqual(failure_events[0]["status"], "failed")
        self.assertIn("timed out", failure_events[0]["error"].casefold())

    def test_provider_response_failures_have_failed_provider_events(self) -> None:
        cases = (
            ("truncated", '{"partial": "unterminated', "length", "truncated"),
            ("empty", "   ", "stop", "empty content"),
        )

        for case_name, content, finish_reason, message in cases:
            with self.subTest(case_name=case_name):
                factory = RecordingClientFactory(
                    content=content,
                    finish_reason=finish_reason,
                )
                provider = DeepSeekAdapter(
                    AISettings(provider="deepseek", api_key="provider-api-key"),
                    client_factory=factory,
                )

                with capture_trace() as trace:
                    with self.assertRaisesRegex(ModelProviderError, message):
                        provider.chat_completion_json([
                            {"role": "user", "content": "Return JSON."}
                        ])

                response_events = [
                    event for event in trace["events"]
                    if event["owner"] == "Provider"
                    and event.get("operation") == "actual_provider_response"
                ]
                failure_events = [
                    event for event in trace["events"]
                    if event["owner"] == "Provider"
                    and event.get("operation") == "provider_failure"
                ]
                self.assertEqual(len(response_events), 1)
                self.assertEqual(len(failure_events), 1)
                self.assertEqual(failure_events[0]["status"], "failed")
                self.assertIn(message, failure_events[0]["error"])


if __name__ == "__main__":
    unittest.main()
