from __future__ import annotations

import streamlit as st
import pandas as pd

from config.settings import get_settings, setup_logging
from engines.recommendation_engine import RecommendationEngine, InsufficientDataError
from services.excel_loader import ExcelLoader, ExcelLoaderError
from services.context_engine import ContextEngine
from services.intent_parser import IntentParser
from services.ai_client import AIClient
from services.ai_decision import AIDecisionError, AIDecisionLayer
from services.v2_decision_pipeline import V2DecisionPipeline
from services.v2_preparation import V2PreparationPipeline
from services.store_resolver import StoreResolver
from services.event_normalization import EventNormalizer
from services.ui import (
    inject_theme,
    render_header,
    render_ai_request_section,
    render_ai_understanding,
    render_v2_runtime_status,
    render_procurement_plan_report,
    render_growth_section,
    render_v2_procurement_strategy,
    render_v2_product_decisions,
    render_v2_purchase_plan,
)


@st.cache_resource
def get_excel_loader() -> ExcelLoader:
    settings = get_settings()
    return ExcelLoader(settings.excel_file)


def get_recommendation_engine() -> RecommendationEngine:
    return RecommendationEngine()


def get_context_engine() -> ContextEngine:
    return ContextEngine()


def get_intent_parser() -> IntentParser:
    return IntentParser()


def get_store_resolver() -> StoreResolver:
    return StoreResolver()


def get_workbook() -> dict:
    return get_excel_loader().load_workbook()


def should_render_recommendations(has_user_request: bool, session_id: str | None) -> bool:
    """Only generate demo recommendations after the user submits a valid request."""
    return has_user_request and bool(session_id)


def failed_v2_fallback_status(reason: str) -> dict[str, object]:
    return {
        "pipeline_version": "V1_FALLBACK",
        "v2_status": "FAILED",
        "fallback_triggered": True,
        "fallback_reason": str(reason),
    }


def resolve_v2_as_of_date(
    workbook: dict,
    user_request: str,
    customer_id: str,
    parsed_intent: dict | None = None,
) -> pd.Timestamp:
    scenarios = workbook.get("V2TestScenarios")
    if scenarios is not None and not scenarios.empty:
        rows = scenarios.loc[
            (scenarios["CustomerId"].astype(str) == str(customer_id))
            & (scenarios["UserInput"].astype(str).str.casefold() == user_request.casefold())
        ]
        if not rows.empty:
            matched = pd.to_datetime(rows.iloc[0].get("AsOfDate"), errors="coerce")
            if pd.notna(matched):
                return pd.Timestamp(matched).normalize()

    structured = (parsed_intent or {}).get("StructuredIntent") or {}
    event_context = EventNormalizer.normalize(
        workbook,
        structured.get("occasion", "NONE"),
        pd.Timestamp.today().normalize(),
    )
    if event_context:
        return event_context["event_window_start"]

    supply = workbook.get("SupplyAvailability")
    if supply is not None and "LastUpdated" in supply.columns:
        dates = pd.to_datetime(supply["LastUpdated"], errors="coerce").dropna().sort_values()
        today = pd.Timestamp.today().normalize()
        not_future = dates.loc[dates <= today]
        if not not_future.empty:
            return pd.Timestamp(not_future.iloc[-1]).normalize()
        if not dates.empty:
            return pd.Timestamp(dates.iloc[0]).normalize()
    return pd.Timestamp.today().normalize()


def main() -> None:
    settings = get_settings()
    logger = setup_logging(settings.log_level)

    st.set_page_config(
        page_title="AI Smart Procurement Assistant",
        page_icon="🛒",
        layout="wide",
        initial_sidebar_state="collapsed",
    )

    inject_theme()

    try:
        workbook = get_workbook()
        context_engine = get_context_engine()
        intent_parser = get_intent_parser()
        store_resolver = get_store_resolver()

        if "session_id" not in st.session_state:
            st.session_state["session_id"] = None

        if "parsed_intent" not in st.session_state:
            st.session_state["parsed_intent"] = None

        if "has_user_request" not in st.session_state:
            st.session_state["has_user_request"] = False

        if "user_request" not in st.session_state:
            st.session_state["user_request"] = ""

        if "v2_result" not in st.session_state:
            st.session_state["v2_result"] = None

        if "v2_error" not in st.session_state:
            st.session_state["v2_error"] = None

        if "pipeline_status" not in st.session_state:
            st.session_state["pipeline_status"] = None

        has_user_request = st.session_state["has_user_request"]

        # The empty landing state deliberately contains no customer-specific data.
        if not should_render_recommendations(has_user_request, st.session_state.get("session_id")):
            render_header(show_context=False)
            request, request_submitted = render_ai_request_section()
            if request_submitted:
                if not request.strip():
                    st.warning("Please describe your procurement request before generating a plan.")
                    return

                store_resolution = store_resolver.resolve(workbook, request)
                if not store_resolution.is_found:
                    st.warning(store_resolution.message)
                    return

                store_context = store_resolver.build_store_context(
                    workbook,
                    store_resolution.customer_id,
                )
                parsed_intent = intent_parser.parse_intent(request, store_context=store_context)
                st.session_state["parsed_intent"] = parsed_intent
                st.session_state["user_request"] = request
                st.session_state["v2_result"] = None
                st.session_state["v2_error"] = None
                st.session_state["pipeline_status"] = None
                st.session_state["has_user_request"] = True
                st.session_state["session_id"] = context_engine.suggest_session(
                    workbook,
                    request,
                    parsed_intent=parsed_intent,
                    customer_id=store_resolution.customer_id,
                )
                st.rerun()
            return

        engine = get_recommendation_engine()
        session_id = st.session_state["session_id"]
        context_override = st.session_state.get("parsed_intent")
        clear_context_keys = set()
        if context_override:
            if context_override.get("Budget") is None:
                clear_context_keys.add("Budget")

        result = engine.generate_session_recommendations(
            workbook,
            session_id,
            context_override=context_override,
            clear_context_keys=clear_context_keys,
        )
        context = result["context"]

        # 客户信息
        customer_name = settings.default_customer_name
        customer_df = workbook.get("Customer")
        if customer_df is not None and not customer_df.empty:
            customer_row = customer_df.loc[customer_df["CustomerId"] == context.get("CustomerId", "")]
            if not customer_row.empty:
                customer_name = str(customer_row.iloc[0].get("StoreName", customer_name))

        industry = context.get("Industry", "Retail - Grocery")
        customer_row2 = workbook.get("Customer")
        if customer_row2 is not None and not customer_row2.empty:
            row = customer_row2.loc[customer_row2["CustomerId"] == context.get("CustomerId", "")]
            if not row.empty:
                industry = str(row.iloc[0].get("Industry", industry))

        render_header(customer_name, industry)
        request, request_submitted = render_ai_request_section()
        if request_submitted:
            if not request.strip():
                st.warning("Please describe your procurement request before generating a plan.")
            else:
                store_resolution = store_resolver.resolve(workbook, request)
                if not store_resolution.is_found:
                    st.warning(store_resolution.message)
                else:
                    store_context = store_resolver.build_store_context(
                        workbook,
                        store_resolution.customer_id,
                    )
                    parsed_intent = intent_parser.parse_intent(request, store_context=store_context)
                    st.session_state["parsed_intent"] = parsed_intent
                    st.session_state["user_request"] = request
                    st.session_state["v2_result"] = None
                    st.session_state["v2_error"] = None
                    st.session_state["pipeline_status"] = None
                    st.session_state["session_id"] = context_engine.suggest_session(
                        workbook,
                        request,
                        parsed_intent=parsed_intent,
                        customer_id=store_resolution.customer_id,
                    )
                    st.rerun()

        render_ai_understanding(context)
        model_client = AIClient()
        if model_client.is_available and st.session_state.get("v2_result") is None and not st.session_state.get("v2_error"):
            try:
                v2_pipeline = V2DecisionPipeline(
                    preparation=V2PreparationPipeline(intent_parser=intent_parser),
                    decision_layer=AIDecisionLayer(ai_client=model_client),
                )
                user_request = str(st.session_state.get("user_request") or context.get("UserInput") or "")
                st.session_state["v2_result"] = v2_pipeline.run(
                    workbook=workbook,
                    customer_id=str(context["CustomerId"]),
                    user_input=user_request,
                    as_of_date=resolve_v2_as_of_date(
                        workbook,
                        user_request,
                        str(context["CustomerId"]),
                        context_override,
                    ),
                    parsed_intent=context_override,
                )
                st.session_state["pipeline_status"] = {
                    key: st.session_state["v2_result"].get(key)
                    for key in (
                        "pipeline_version", "v2_status",
                        "fallback_triggered", "fallback_reason",
                    )
                }
            except (AIDecisionError, ValueError) as exc:
                logger.warning("V2 pipeline unavailable, retaining V1 result: %s", exc)
                st.session_state["v2_error"] = str(exc)
                st.session_state["pipeline_status"] = failed_v2_fallback_status(str(exc))

        v2_result = st.session_state.get("v2_result")
        if v2_result:
            render_v2_runtime_status(
                model_client.provider_name,
                model_client.settings.model,
                st.session_state.get("pipeline_status"),
                v2_result.get("safe_decision_context", {}).get("structured_intent"),
                v2_result.get("intent", {}).get("AIAnalysisStatus"),
            )
            if v2_result.get("v2_status") == "SUCCESS":
                st.success("Pipeline: V2 SUCCESS")
            else:
                st.error("Pipeline: V2 FAILED. No V2 final purchase plan was produced.")
            render_v2_procurement_strategy(
                v2_result["ai_decision"]["procurement_strategy"],
                v2_result["retry_count"],
            )
            render_v2_product_decisions(
                v2_result["decision_trace"]["candidate_decisions"],
                v2_result["final_purchase_plan"],
            )
            render_v2_purchase_plan(
                v2_result["final_purchase_plan"],
                v2_result["optimizer_result"],
                v2_result["validation_result"],
            )
        else:
            render_v2_runtime_status(
                model_client.provider_name,
                model_client.settings.model,
                st.session_state.get("pipeline_status"),
                (context_override or {}).get("StructuredIntent"),
                (context_override or {}).get("AIAnalysisStatus"),
            )
            if st.session_state.get("v2_error"):
                st.error(
                    "V2 FAILED — FALLBACK → V1. "
                    f"Reason: {st.session_state['v2_error']}"
                )
            budget = float(context["Budget"]) if context.get("Budget") is not None else None
            render_procurement_plan_report(result["procurement_plan"], budget, context)
            render_growth_section(result["growth"])

    except ExcelLoaderError as exc:
        logger.exception("Failed to load workbook.")
        st.error(f"Unable to load the demo workbook: {exc}")
    except InsufficientDataError as exc:
        logger.warning("Insufficient data: %s", exc)
        st.error(str(exc))
    except Exception as exc:
        logger.exception("Unexpected application error.")
        st.error(f"An unexpected error occurred: {exc}")


if __name__ == "__main__":
    main()
