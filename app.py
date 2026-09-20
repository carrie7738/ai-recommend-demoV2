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
from services.request_constraints import RequestClarificationError
from services.debug_ui import debug_trace_enabled, render_debug_trace
from services.runtime_trace import capture_trace, record, snapshot
from services.ui import (
    inject_theme,
    render_header,
    render_ai_request_section,
    render_ai_understanding,
    render_v2_runtime_status,
    render_unvalidated_fallback_plan,
    render_potential_opportunities,
    render_v2_procurement_strategy,
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


def _clear_request_runtime_state() -> None:
    """Drop the previous request before attempting to parse a new one."""
    st.session_state["session_id"] = None
    st.session_state["parsed_intent"] = None
    st.session_state["user_request"] = ""
    st.session_state["v2_result"] = None
    st.session_state["fallback_result"] = None
    st.session_state["v2_error"] = None
    st.session_state["pipeline_status"] = None
    st.session_state["has_user_request"] = False
    st.session_state["debug_trace"] = None


def _parse_intent_with_trace(
    intent_parser: IntentParser,
    request: str,
    store_context: dict,
) -> dict:
    """Parse one submitted request once and retain even a partial trace on failure."""
    if not debug_trace_enabled():
        st.session_state["debug_trace"] = None
        return intent_parser.parse_intent(request, store_context=store_context)

    trace = None
    try:
        with capture_trace() as trace:
            record(
                "request",
                "User",
                input={"user_request": request, "store_context": store_context},
            )
            parsed_intent = intent_parser.parse_intent(request, store_context=store_context)
    except Exception as exc:
        if trace is not None:
            trace.setdefault("metadata", {}).update(snapshot({"status": "failed", "error": str(exc)}))
            st.session_state["debug_trace"] = trace
        raise
    st.session_state["debug_trace"] = trace
    return parsed_intent


def _run_pipeline_with_trace(
    pipeline: V2DecisionPipeline,
    trace: dict | None,
    as_of_date_source: str | None = None,
    **kwargs,
) -> tuple[dict | None, dict | None]:
    """Run V2 once while appending events to the intent trace."""
    if not debug_trace_enabled():
        st.session_state["debug_trace"] = None
        return pipeline.run(**kwargs), None

    active_trace = trace
    pipeline_result = None
    try:
        with capture_trace(existing=active_trace) as active_trace:
            record("business_context", "Workflow", operation="date_resolution", output={
                "as_of_date": kwargs.get("as_of_date"),
                "as_of_date_source": as_of_date_source,
            })
            pipeline_result = pipeline.run(**kwargs)
    finally:
        # The decorator records exceptions before this context exits.  Saving in
        # finally keeps those events available to the debug panel as well.
        if active_trace is not None:
            st.session_state["debug_trace"] = active_trace
    return pipeline_result, active_trace


def _run_fallback_with_trace(
    engine: RecommendationEngine,
    workbook: dict,
    session_id: str,
    context_override: dict | None,
    clear_context_keys: set[str],
    trace: dict | None,
) -> tuple[dict, dict | None]:
    """Capture the rules fallback once without changing its business output."""
    if not debug_trace_enabled():
        st.session_state["debug_trace"] = None
        return engine.generate_session_recommendations(
            workbook,
            session_id,
            context_override=context_override,
            clear_context_keys=clear_context_keys,
        ), None

    active_trace = trace
    fallback_result = None
    try:
        with capture_trace(existing=active_trace) as active_trace:
            try:
                fallback_result = engine.generate_session_recommendations(
                    workbook,
                    session_id,
                    context_override=context_override,
                    clear_context_keys=clear_context_keys,
                )
            except Exception as exc:
                record(
                    "final",
                    "V1 fallback",
                    status="failed",
                    error=str(exc),
                    operation="rules_fallback",
                )
                raise
            record(
                "final",
                "V1 fallback",
                status="fallback",
                output={
                    "pipeline_version": "V1_FALLBACK",
                    "fallback_triggered": True,
                    "fallback_reason": st.session_state.get("v2_error"),
                    "fallback_result": fallback_result,
                },
                operation="rules_fallback",
            )
    finally:
        if active_trace is not None:
            st.session_state["debug_trace"] = active_trace
    return fallback_result, active_trace


def failed_v2_fallback_status(reason: str) -> dict[str, object]:
    return {
        "pipeline_version": "V1_FALLBACK",
        "v2_status": "FAILED",
        "fallback_triggered": True,
        "fallback_reason": str(reason),
        "intent_fallback_triggered": None,
        "decision_mode": "V1_FALLBACK",
    }


def build_v2_display_context(
    session_context: dict,
    parsed_intent: dict | None,
) -> dict:
    """Build UI/store context without running the V1 recommendation engine."""
    context = dict(session_context)
    if parsed_intent:
        context.update(parsed_intent)
        trusted_store = parsed_intent.get("StoreContext") or {}
        if trusted_store.get("CustomerId"):
            context["CustomerId"] = str(trusted_store["CustomerId"])
    return context


def resolve_v2_as_of_date(
    workbook: dict,
    user_request: str,
    customer_id: str,
    parsed_intent: dict | None = None,
) -> pd.Timestamp:
    return resolve_v2_date_context(workbook, user_request, customer_id, parsed_intent)[0]


def resolve_v2_date_context(
    workbook: dict,
    user_request: str,
    customer_id: str,
    parsed_intent: dict | None = None,
) -> tuple[pd.Timestamp, str]:
    scenarios = workbook.get("V2TestScenarios")
    if scenarios is not None and not scenarios.empty:
        rows = scenarios.loc[
            (scenarios["CustomerId"].astype(str) == str(customer_id))
            & (scenarios["UserInput"].astype(str).str.casefold() == user_request.casefold())
        ]
        if not rows.empty:
            matched = pd.to_datetime(rows.iloc[0].get("AsOfDate"), errors="coerce")
            if pd.notna(matched):
                return pd.Timestamp(matched).normalize(), "V2TestScenarios.AsOfDate"

    structured = (parsed_intent or {}).get("StructuredIntent") or {}
    event_context = EventNormalizer.normalize(
        workbook,
        structured.get("occasion", "NONE"),
        pd.Timestamp.today().normalize(),
    )
    if event_context:
        return event_context["event_window_start"], "EventConfig.EventWindowStart"

    supply = workbook.get("SupplyAvailability")
    if supply is not None and "LastUpdated" in supply.columns:
        dates = pd.to_datetime(supply["LastUpdated"], errors="coerce").dropna().sort_values()
        today = pd.Timestamp.today().normalize()
        not_future = dates.loc[dates <= today]
        if not not_future.empty:
            return pd.Timestamp(not_future.iloc[-1]).normalize(), "SupplyAvailability.LastUpdated.latest_not_future"
        if not dates.empty:
            return pd.Timestamp(dates.iloc[0]).normalize(), "SupplyAvailability.LastUpdated.earliest_future"
    return pd.Timestamp.today().normalize(), "System.today"


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

        if "debug_trace" not in st.session_state:
            st.session_state["debug_trace"] = None

        if "fallback_result" not in st.session_state:
            st.session_state["fallback_result"] = None

        has_user_request = st.session_state["has_user_request"]

        # The empty landing state deliberately contains no customer-specific data.
        if not should_render_recommendations(has_user_request, st.session_state.get("session_id")):
            render_header(show_context=False)
            request, request_submitted = render_ai_request_section()
            if request_submitted:
                # A newly submitted request must never display the previous
                # request's trace, including when validation below returns.
                _clear_request_runtime_state()
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
                with st.spinner("Understanding your request..."):
                    parsed_intent = _parse_intent_with_trace(
                        intent_parser,
                        request,
                        store_context,
                    )
                parsed_intent['UserInput'] = request
                st.session_state["parsed_intent"] = parsed_intent
                st.session_state["user_request"] = request
                st.session_state["v2_result"] = None
                st.session_state["fallback_result"] = None
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
            if debug_trace_enabled() and st.session_state.get("debug_trace"):
                render_debug_trace(st.session_state["debug_trace"])
            return

        session_id = st.session_state["session_id"]
        context_override = st.session_state.get("parsed_intent")
        clear_context_keys = set()
        if context_override:
            if context_override.get("Budget") is None:
                clear_context_keys.add("Budget")

        context = build_v2_display_context(
            context_engine.build_context(workbook, session_id),
            context_override,
        )

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
            # Clear before resolving/parsing so a failed new request cannot
            # leave a stale trace associated with the old result.
            _clear_request_runtime_state()
            if not request.strip():
                st.warning("Please describe your procurement request before generating a plan.")
                return
            else:
                store_resolution = store_resolver.resolve(workbook, request)
                if not store_resolution.is_found:
                    st.warning(store_resolution.message)
                    return
                else:
                    store_context = store_resolver.build_store_context(
                        workbook,
                        store_resolution.customer_id,
                    )
                    with st.spinner("Understanding your request..."):
                        parsed_intent = _parse_intent_with_trace(
                            intent_parser,
                            request,
                            store_context,
                        )
                    parsed_intent['UserInput'] = request
                    st.session_state["parsed_intent"] = parsed_intent
                    st.session_state["user_request"] = request
                    st.session_state["v2_result"] = None
                    st.session_state["fallback_result"] = None
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

        render_ai_understanding(context_override or {})
        model_client = AIClient()
        if model_client.is_available and st.session_state.get("v2_result") is None and not st.session_state.get("v2_error"):
            try:
                v2_pipeline = V2DecisionPipeline(
                    preparation=V2PreparationPipeline(intent_parser=intent_parser),
                    decision_layer=AIDecisionLayer(ai_client=model_client),
                )
                user_request = str(st.session_state.get("user_request") or context.get("UserInput") or "")
                as_of_date, as_of_date_source = resolve_v2_date_context(
                    workbook, user_request, str(context["CustomerId"]), context_override,
                )
                with st.spinner("Building purchase plan..."):
                    pipeline_result, _ = _run_pipeline_with_trace(
                        v2_pipeline,
                        st.session_state.get("debug_trace"),
                        workbook=workbook,
                        customer_id=str(context["CustomerId"]),
                        user_input=user_request,
                        as_of_date=as_of_date,
                        as_of_date_source=as_of_date_source,
                        parsed_intent=context_override,
                    )
                    st.session_state["v2_result"] = pipeline_result
                st.session_state["pipeline_status"] = {
                    key: st.session_state["v2_result"].get(key)
                    for key in (
                        "pipeline_version", "v2_status",
                        "fallback_triggered", "fallback_reason",
                        "intent_fallback_triggered", "decision_mode",
                    )
                }
            except (AIDecisionError, ValueError) as exc:
                logger.warning("V2 pipeline failed; V1 fallback will run: %s", exc)
                st.session_state["v2_error"] = str(exc)
                st.session_state["pipeline_status"] = failed_v2_fallback_status(str(exc))
        elif not model_client.is_available and st.session_state.get("v2_result") is None:
            reason = "AI decision provider is not configured."
            st.session_state["v2_error"] = reason
            st.session_state["pipeline_status"] = failed_v2_fallback_status(reason)

        v2_result = st.session_state.get("v2_result")
        debug_display_result = v2_result
        if v2_result:
            structured_intent = v2_result.get("safe_decision_context", {}).get("structured_intent") or {}
            render_v2_purchase_plan(
                v2_result["final_purchase_plan"],
                v2_result["optimizer_result"],
                v2_result["validation_result"],
                budget=structured_intent.get("budget"),
            )
            render_potential_opportunities()
            with st.expander("Technical details", expanded=False):
                render_v2_runtime_status(
                    model_client.provider_name,
                    model_client.settings.model,
                    st.session_state.get("pipeline_status"),
                    structured_intent,
                    v2_result.get("intent", {}).get("AIAnalysisStatus"),
                )
                render_v2_procurement_strategy(
                    v2_result["ai_decision"]["procurement_strategy"],
                    v2_result["retry_count"],
                )
        else:
            if st.session_state.get("v2_error"):
                st.warning("The AI purchase plan could not be generated. A rules-based fallback is shown below; its validation result is unavailable.")
            # V1 is deliberately lazy: it is executed only after the original
            # V2 failure has been captured and surfaced above.
            fallback_result = st.session_state.get("fallback_result")
            if fallback_result is None:
                fallback_result, _ = _run_fallback_with_trace(
                    get_recommendation_engine(),
                    workbook,
                    session_id,
                    context_override,
                    clear_context_keys,
                    st.session_state.get("debug_trace"),
                )
                st.session_state["fallback_result"] = fallback_result
            debug_display_result = fallback_result
            fallback_context = fallback_result["context"]
            budget = (
                float(fallback_context["Budget"])
                if fallback_context.get("Budget") is not None
                else None
            )
            render_unvalidated_fallback_plan(
                fallback_result["procurement_plan"],
                budget,
            )
            selected_ids = {item["product_id"] for item in fallback_result["procurement_plan"]}
            render_potential_opportunities([
                item for item in fallback_result["growth"]
                if item.get("product_id") and item["product_id"] not in selected_ids
            ])
            with st.expander("Technical details", expanded=False):
                render_v2_runtime_status(
                    model_client.provider_name,
                    model_client.settings.model,
                    st.session_state.get("pipeline_status"),
                    (context_override or {}).get("StructuredIntent"),
                    (context_override or {}).get("AIAnalysisStatus"),
                )

        if debug_trace_enabled():
            render_debug_trace(
                st.session_state.get("debug_trace"),
                result=debug_display_result,
            )

    except RequestClarificationError as exc:
        st.warning(str(exc))
    except ExcelLoaderError as exc:
        logger.exception("Failed to load workbook.")
        st.error(f"Unable to load the demo workbook: {exc}")
        if debug_trace_enabled():
            render_debug_trace(st.session_state.get("debug_trace"))
    except InsufficientDataError as exc:
        logger.warning("Insufficient data: %s", exc)
        st.error(str(exc))
        if debug_trace_enabled():
            render_debug_trace(st.session_state.get("debug_trace"))
    except Exception as exc:
        logger.exception("Unexpected application error.")
        st.error(f"An unexpected error occurred: {exc}")
        if debug_trace_enabled():
            render_debug_trace(
                st.session_state.get("debug_trace"),
                result=st.session_state.get("v2_result"),
            )


if __name__ == "__main__":
    main()
