from __future__ import annotations

import streamlit as st

from config.settings import get_settings, setup_logging
from engines.recommendation_engine import RecommendationEngine, InsufficientDataError
from services.excel_loader import ExcelLoader, ExcelLoaderError
from services.context_engine import ContextEngine
from services.intent_parser import IntentParser
from services.store_resolver import StoreResolver
from services.ui import (
    inject_theme,
    render_header,
    render_ai_request_section,
    render_ai_understanding,
    render_procurement_plan_report,
    render_growth_section,
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
                    st.session_state["session_id"] = context_engine.suggest_session(
                        workbook,
                        request,
                        parsed_intent=parsed_intent,
                        customer_id=store_resolution.customer_id,
                    )
                    st.rerun()

        render_ai_understanding(context)
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
