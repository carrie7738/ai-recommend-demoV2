from __future__ import annotations

import json
import argparse
import os
from dataclasses import replace
from pathlib import Path
import sys


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
if str(REPOSITORY_ROOT) not in sys.path:
    sys.path.insert(0, str(REPOSITORY_ROOT))

from config.settings import AISettings, get_settings  # noqa: E402
from services.ai_client import AIClient  # noqa: E402
from services.ai_decision import AIDecisionLayer  # noqa: E402
from services.intent_parser import IntentParser  # noqa: E402


def _settings_for(provider: str) -> AISettings:
    current = get_settings().ai
    if provider == current.provider:
        return current
    if provider == "glm":
        return AISettings(
            provider="glm",
            api_key=os.getenv("GLM_API_KEY", ""),
            base_url=os.getenv("GLM_BASE_URL", "https://open.bigmodel.cn/api/paas/v4"),
            model=os.getenv("GLM_MODEL", "glm-5.2"),
            temperature=current.temperature,
            max_tokens=current.max_tokens,
            structured_max_tokens=current.structured_max_tokens,
            thinking_enabled=current.thinking_enabled,
        )
    if provider == "gemini":
        return AISettings(
            provider="gemini",
            api_key=os.getenv("GEMINI_API_KEY", ""),
            base_url=os.getenv(
                "GEMINI_BASE_URL",
                "https://generativelanguage.googleapis.com/v1beta/openai/",
            ),
            model=os.getenv("GEMINI_MODEL", "gemini-3.6-flash"),
            temperature=current.temperature,
            max_tokens=current.max_tokens,
            structured_max_tokens=current.structured_max_tokens,
            thinking_enabled=current.thinking_enabled,
        )
    return AISettings(
        provider="deepseek",
        api_key=os.getenv("DEEPSEEK_API_KEY", ""),
        base_url=os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com"),
        model=os.getenv("DEEPSEEK_MODEL", "deepseek-v4-flash"),
        temperature=current.temperature,
        max_tokens=current.max_tokens,
        structured_max_tokens=current.structured_max_tokens,
        thinking_enabled=current.thinking_enabled,
    )


def main() -> int:
    parser = argparse.ArgumentParser(description="Run provider-neutral structured V2 smoke checks.")
    parser.add_argument(
        "--provider",
        choices=["deepseek", "glm", "gemini"],
        default=get_settings().ai.provider,
    )
    parser.add_argument("--model", help="Optional model override for this smoke run only.")
    args = parser.parse_args()
    settings = _settings_for(args.provider)
    if args.model:
        settings = replace(settings, model=args.model)
    client = AIClient(settings=settings)
    report: dict[str, object] = {
        "provider": client.provider_name,
        "model": client.settings.model,
        "key_loaded": bool(client.settings.api_key),
        "intent": None,
        "decision": None,
        "retry": False,
        "fallback": False,
    }
    if not client.is_available:
        report["status"] = "PENDING_KEY"
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return 2

    intent = IntentParser(ai_client=client).parse_intent(
        "For Cafe Store 001, high traffic is expected next week. Budget is NZD 1000."
    )
    report["intent"] = {
        **client.last_call_metrics,
        "analysis_status": intent.get("AIAnalysisStatus"),
        "json_object": isinstance(intent, dict),
        "semantic_contract": {
            "budget": intent.get("StructuredIntent", {}).get("budget"),
            "traffic_expectation": intent.get("StructuredIntent", {}).get(
                "traffic_expectation"
            ),
        },
    }
    if intent.get("AIAnalysisStatus") != "live":
        report["fallback"] = True
        report["status"] = "FAIL"
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return 1
    structured = intent.get("StructuredIntent", {})
    if (
        structured.get("budget") != 1000.0
        or structured.get("traffic_expectation") != "HIGH"
    ):
        report["status"] = "FAIL"
        report["failure_reason"] = "STRUCTURED_INTENT_SEMANTIC_MISMATCH"
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return 1

    decision = AIDecisionLayer(ai_client=client).decide({
        "structured_intent": intent["StructuredIntent"],
        "candidates": [{
            "candidate_id": "P001",
            "recommendation_type": "REPLENISHMENT",
            "candidate_source": "STORE_HISTORY",
            "features": {
                "purchase_frequency": "HIGH",
                "stockout_risk": "HIGH",
            },
            "signals": ["PURCHASE_FREQUENCY=HIGH", "STOCKOUT_RISK=HIGH"],
        }],
    })
    report["decision"] = {
        **client.last_call_metrics,
        "json_object": isinstance(decision, dict),
        "schema_valid": True,
    }
    report["status"] = "PASS"
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
