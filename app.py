import streamlit as st

from config.settings import get_settings, setup_logging
from engines.recommendation_engine import RecommendationEngine, InsufficientDataError
from services.excel_loader import ExcelLoader, ExcelLoaderError
from services.context_engine import ContextEngine
from services.intent_parser import IntentParser
from services.ui import (
    inject_theme,
    render_header,
    render_ai_request_section,
    render_ai_understanding,
    render_procurement_plan_report,
    render_replenishment_section,
    render_growth_section,
    render_risks_section,
)


@st.cache_resource
def get_excel_loader() -> ExcelLoader:
    settings = get_settings()
    return ExcelLoader(settings.excel_file)


@st.cache_resource
def get_recommendation_engine() -> RecommendationEngine:
    return RecommendationEngine()


@st.cache_resource
def get_context_engine() -> ContextEngine:
    return ContextEngine()


@st.cache_resource
def get_intent_parser() -> IntentParser:
    return IntentParser()


def get_workbook() -> dict:
    return get_excel_loader().load_workbook()


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
        engine = get_recommendation_engine()

        sessions = context_engine.list_sessions(workbook)
        if not sessions:
            st.error("No conversation sessions found in the workbook.")
            return

        default_session_id = sessions[0]["SessionId"]

        if "session_id" not in st.session_state:
            st.session_state["session_id"] = default_session_id

        if "parsed_intent" not in st.session_state:
            st.session_state["parsed_intent"] = None

        if "has_user_request" not in st.session_state:
            st.session_state["has_user_request"] = False

        # 获取当前会话的推荐结果
        session_id = st.session_state["session_id"]
        context_override = st.session_state.get("parsed_intent")
        clear_context_keys = set()
        if st.session_state.get("has_user_request") and context_override:
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
        if request_submitted and request.strip():
            parsed_intent = intent_parser.parse_intent(request)
            st.session_state["parsed_intent"] = parsed_intent
            st.session_state["has_user_request"] = True
            st.session_state["session_id"] = context_engine.suggest_session(
                workbook,
                request,
                parsed_intent=parsed_intent,
            )
            st.rerun()

        render_ai_understanding(context)
        budget = float(context["Budget"]) if context.get("Budget") is not None else None
        render_procurement_plan_report(result["procurement_plan"], budget, context)
        render_replenishment_section(result["replenishment"])
        render_growth_section(result["growth"])
        render_risks_section(result["risks"])

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
