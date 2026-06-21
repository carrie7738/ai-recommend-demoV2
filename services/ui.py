from __future__ import annotations

import logging
from html import escape
from typing import Any

import pandas as pd
import streamlit as st

from config.settings import get_settings

logger = logging.getLogger(__name__)


def inject_theme() -> None:
    st.markdown(
        """
        <style>
        @import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&display=swap');

        * {
            box-sizing: border-box;
        }

        html, body, [class*="css"] {
            font-family: "Inter", -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
            color: #1a1a2e;
        }

        [data-testid="stAppViewContainer"] {
            background: #f8f9fa;
        }

        [data-testid="stSidebar"] {
            display: none;
        }

        .block-container {
            padding-top: 1.5rem;
            padding-bottom: 2rem;
            max-width: 1120px;
        }

        [data-testid="stHeader"] {
            background: transparent;
        }

        /* Header */
        .app-header {
            display: flex;
            justify-content: space-between;
            align-items: flex-start;
            margin-bottom: 1.5rem;
            padding-bottom: 1rem;
            border-bottom: 1px solid #e9ecef;
        }

        .app-header-left h1 {
            font-size: 1.25rem;
            font-weight: 700;
            margin: 0 0 0.3rem;
            color: #1a1a2e;
        }

        .app-header-meta {
            display: flex;
            align-items: center;
            gap: 0.5rem;
            font-size: 0.82rem;
            color: #6c757d;
        }

        .app-header-meta span {
            display: flex;
            align-items: center;
            gap: 0.3rem;
        }

        .app-header-meta .dot {
            width: 3px;
            height: 3px;
            border-radius: 50%;
            background: #adb5bd;
        }

        .app-header-right {
            text-align: right;
            font-size: 0.78rem;
            color: #6c757d;
        }

        .app-header-right .analysis-label {
            display: flex;
            align-items: center;
            justify-content: flex-end;
            gap: 0.3rem;
            margin-bottom: 0.15rem;
        }

        .app-header-right .analysis-time {
            font-weight: 600;
            color: #1a1a2e;
        }

        /* Section card */
        .section-card {
            background: #fff;
            border: 1px solid #e9ecef;
            border-radius: 12px;
            padding: 1.25rem 1.5rem;
            margin-bottom: 1.25rem;
        }

        .section-card-header {
            display: flex;
            align-items: center;
            gap: 0.6rem;
            margin-bottom: 0.8rem;
        }

        .section-icon {
            width: 32px;
            height: 32px;
            border-radius: 8px;
            display: flex;
            align-items: center;
            justify-content: center;
            font-size: 0.9rem;
        }

        .section-icon-purple {
            background: #e8e0f0;
            color: #7c3aed;
        }

        .section-icon-blue {
            background: #dbeafe;
            color: #2563eb;
        }

        .section-icon-green {
            background: #dcfce7;
            color: #16a34a;
        }

        .section-icon-amber {
            background: #fef3c7;
            color: #d97706;
        }

        .section-icon-red {
            background: #fee2e2;
            color: #dc2626;
        }

        .section-title {
            font-size: 1rem;
            font-weight: 700;
            color: #1a1a2e;
            margin: 0;
        }

        .section-subtitle {
            font-size: 0.82rem;
            color: #6c757d;
            margin: 0;
        }

        /* Text area */
        div[data-testid="stTextArea"] textarea {
            border-radius: 10px !important;
            border: 1px solid #dee2e6 !important;
            background: #fff !important;
            color: #1a1a2e !important;
            font-size: 0.9rem !important;
            padding: 0.85rem 1rem !important;
            line-height: 1.5 !important;
        }

        div[data-testid="stTextArea"] textarea:focus {
            border-color: #7c3aed !important;
            box-shadow: 0 0 0 3px rgba(124, 58, 237, 0.1) !important;
        }

        /* Button */
        div[data-testid="stButton"] > button {
            border-radius: 10px !important;
            font-weight: 600 !important;
            font-size: 0.88rem !important;
            min-height: 42px !important;
        }

        div[data-testid="stButton"] > button[kind="primary"] {
            background: #7c3aed !important;
            border: none !important;
            color: #fff !important;
        }

        div[data-testid="stButton"] > button[kind="primary"]:hover {
            background: #6d28d9 !important;
        }

        /* AI Understanding pills */
        .understanding-pills {
            display: flex;
            flex-wrap: wrap;
            gap: 0.5rem;
            margin-top: 0.8rem;
        }

        .understanding-pill {
            display: inline-flex;
            align-items: center;
            gap: 0.4rem;
            padding: 0.35rem 0.7rem;
            border-radius: 20px;
            font-size: 0.8rem;
            font-weight: 500;
            border: 1px solid;
        }

        .pill-blue {
            background: #eff6ff;
            border-color: #bfdbfe;
            color: #1d4ed8;
        }

        .pill-green {
            background: #f0fdf4;
            border-color: #bbf7d0;
            color: #15803d;
        }

        .pill-purple {
            background: #faf5ff;
            border-color: #e9d5ff;
            color: #7c3aed;
        }

        .pill-amber {
            background: #fffbeb;
            border-color: #fde68a;
            color: #b45309;
        }

        .pill-red {
            background: #fef2f2;
            border-color: #fecaca;
            color: #dc2626;
        }

        .pill-remove {
            cursor: pointer;
            font-size: 0.7rem;
            opacity: 0.6;
            margin-left: 0.1rem;
        }

        .pill-remove:hover {
            opacity: 1;
        }

        .understanding-card {
            border-color: #dbeafe;
            box-shadow: 0 10px 30px rgba(37, 99, 235, 0.06);
        }

        .understanding-grid {
            display: grid;
            grid-template-columns: repeat(4, minmax(0, 1fr));
            gap: 0.75rem;
        }

        .understanding-panel {
            background: #f8fafc;
            border: 1px solid #e2e8f0;
            border-radius: 12px;
            padding: 0.9rem 1rem;
        }

        .understanding-panel-title {
            font-size: 0.72rem;
            text-transform: uppercase;
            letter-spacing: 0.06em;
            font-weight: 700;
            color: #64748b;
            margin-bottom: 0.45rem;
        }

        .understanding-primary {
            font-size: 0.95rem;
            font-weight: 800;
            color: #0f172a;
            margin-bottom: 0.25rem;
        }

        .understanding-secondary {
            font-size: 0.78rem;
            color: #64748b;
            line-height: 1.45;
        }

        .understanding-missing {
            margin-top: 0.85rem;
            padding: 0.9rem 1rem;
            border-radius: 12px;
            background: #fff;
            border: 1px solid #e2e8f0;
        }

        .understanding-mini-row {
            display: flex;
            gap: 0.75rem;
            padding: 0.35rem 0;
            font-size: 0.82rem;
            border-top: 1px solid #f1f5f9;
        }

        .understanding-mini-row:first-of-type {
            border-top: none;
        }

        .understanding-mini-label {
            min-width: 120px;
            color: #0f172a;
            font-weight: 700;
        }

        .understanding-mini-value {
            color: #64748b;
        }

        .understanding-follow-up {
            margin-top: 0.7rem;
            padding: 0.7rem 0.85rem;
            border-radius: 10px;
            background: #fff7ed;
            color: #9a3412;
            font-size: 0.82rem;
        }

        @media (max-width: 900px) {
            .understanding-grid {
                grid-template-columns: repeat(2, minmax(0, 1fr));
            }
        }

        @media (max-width: 640px) {
            .understanding-grid {
                grid-template-columns: 1fr;
            }

            .understanding-mini-row {
                flex-direction: column;
                gap: 0.2rem;
            }
        }

        /* Replenishment cards */
        .replenishment-list {
            display: flex;
            flex-direction: column;
            gap: 0.75rem;
        }

        .replenishment-card {
            background: #fff;
            border: 1px solid #e9ecef;
            border-radius: 12px;
            padding: 1rem 1.25rem;
            transition: box-shadow 0.15s ease;
        }

        .replenishment-card:hover {
            box-shadow: 0 2px 8px rgba(0,0,0,0.04);
        }

        .replenishment-card-top {
            display: flex;
            align-items: center;
            gap: 0.6rem;
            margin-bottom: 0.5rem;
        }

        .replenishment-product {
            font-size: 0.95rem;
            font-weight: 700;
            color: #1a1a2e;
        }

        .action-tag {
            padding: 0.2rem 0.6rem;
            border-radius: 20px;
            font-size: 0.72rem;
            font-weight: 600;
        }

        .tag-immediate {
            background: #fee2e2;
            color: #dc2626;
        }

        .tag-this-week {
            background: #fef3c7;
            color: #b45309;
        }

        .tag-monitor {
            background: #f3f4f6;
            color: #6b7280;
        }

        .replenishment-desc {
            font-size: 0.82rem;
            color: #6c757d;
            line-height: 1.5;
            margin-bottom: 0.75rem;
        }

        .replenishment-metrics {
            display: grid;
            grid-template-columns: repeat(4, 1fr);
            gap: 1rem;
        }

        .metric-label {
            font-size: 0.72rem;
            color: #adb5bd;
            font-weight: 500;
            margin-bottom: 0.2rem;
        }

        .metric-value {
            font-size: 0.9rem;
            font-weight: 700;
            color: #1a1a2e;
        }

        .metric-value.highlight {
            color: #0f766e;
        }

        .metric-value.urgent {
            color: #dc2626;
        }

        .strength-very-high { color: #16a34a; }
        .strength-high { color: #16a34a; }
        .strength-medium { color: #d97706; }
        .strength-low { color: #6b7280; }

        /* Growth cards */
        .growth-list {
            display: flex;
            flex-direction: column;
            gap: 0.75rem;
        }

        .growth-card {
            background: #fff;
            border: 1px solid #e9ecef;
            border-radius: 12px;
            padding: 1rem 1.25rem;
        }

        .growth-card-top {
            display: flex;
            align-items: center;
            gap: 0.5rem;
            margin-bottom: 0.4rem;
        }

        .growth-product {
            font-size: 0.95rem;
            font-weight: 700;
            color: #1a1a2e;
        }

        .growth-category {
            font-size: 0.75rem;
            color: #adb5bd;
            font-weight: 400;
        }

        .growth-potential {
            font-size: 0.78rem;
            font-weight: 600;
            display: flex;
            align-items: center;
            gap: 0.25rem;
        }

        .potential-high { color: #16a34a; }
        .potential-very-high { color: #16a34a; }
        .potential-medium { color: #d97706; }

        .growth-desc {
            font-size: 0.82rem;
            color: #6c757d;
            line-height: 1.5;
        }

        /* Risk tabs */
        .risk-tabs {
            display: flex;
            border-bottom: 2px solid #e9ecef;
            margin-bottom: 1rem;
        }

        .risk-tab {
            flex: 1;
            text-align: center;
            padding: 0.7rem 0;
            font-size: 0.85rem;
            font-weight: 600;
            color: #6c757d;
            cursor: pointer;
            border-bottom: 2px solid transparent;
            margin-bottom: -2px;
            transition: all 0.15s ease;
        }

        .risk-tab.active {
            color: #7c3aed;
            border-bottom-color: #7c3aed;
        }

        .risk-tab:hover {
            color: #1a1a2e;
        }

        .risk-list {
            display: flex;
            flex-direction: column;
            gap: 0.5rem;
        }

        .risk-item {
            display: flex;
            align-items: center;
            justify-content: space-between;
            padding: 0.85rem 1rem;
            background: #fff;
            border: 1px solid #e9ecef;
            border-radius: 10px;
        }

        .risk-item-left {
            display: flex;
            align-items: center;
            gap: 0.75rem;
        }

        .risk-icon {
            width: 36px;
            height: 36px;
            border-radius: 8px;
            display: flex;
            align-items: center;
            justify-content: center;
            font-size: 1rem;
        }

        .risk-icon-critical {
            background: #fee2e2;
            color: #dc2626;
        }

        .risk-icon-high {
            background: #fef3c7;
            color: #d97706;
        }

        .risk-icon-medium {
            background: #fef3c7;
            color: #d97706;
        }

        .risk-product {
            font-size: 0.9rem;
            font-weight: 600;
            color: #1a1a2e;
        }

        .risk-product-unit {
            font-size: 0.75rem;
            color: #adb5bd;
            font-weight: 400;
        }

        .risk-level-tag {
            padding: 0.15rem 0.5rem;
            border-radius: 12px;
            font-size: 0.7rem;
            font-weight: 600;
            margin-top: 0.2rem;
            display: inline-block;
        }

        .level-critical {
            background: #fee2e2;
            color: #dc2626;
        }

        .level-high {
            background: #fef3c7;
            color: #b45309;
        }

        .level-medium {
            background: #fef3c7;
            color: #b45309;
        }

        .risk-item-right {
            text-align: right;
        }

        .risk-coverage-label {
            font-size: 0.72rem;
            color: #adb5bd;
        }

        .risk-coverage-value {
            font-size: 0.88rem;
            font-weight: 700;
            color: #dc2626;
            display: flex;
            align-items: center;
            justify-content: flex-end;
            gap: 0.25rem;
        }

        .risk-action-btn {
            padding: 0.3rem 0.7rem;
            border-radius: 8px;
            font-size: 0.75rem;
            font-weight: 600;
            border: 1px solid;
            background: #fff;
            margin-top: 0.3rem;
            display: inline-block;
        }

        .risk-action-immediate {
            border-color: #fecaca;
            color: #dc2626;
        }

        .risk-action-week {
            border-color: #fde68a;
            color: #b45309;
        }

        /* Procurement Plan */
        .procurement-table {
            width: 100%;
            border-collapse: collapse;
            margin-top: 0.75rem;
            font-size: 0.85rem;
        }

        .procurement-table th {
            text-align: left;
            padding: 0.6rem 0.75rem;
            font-weight: 600;
            color: #6c757d;
            font-size: 0.78rem;
            border-bottom: 1px solid #e9ecef;
        }

        .procurement-table td {
            padding: 0.6rem 0.75rem;
            border-bottom: 1px solid #f1f3f5;
            color: #1a1a2e;
        }

        .procurement-table tr:last-child td {
            border-bottom: none;
        }

        .procurement-table .total-row td {
            font-weight: 700;
            border-top: 2px solid #e9ecef;
            border-bottom: none;
            padding-top: 0.75rem;
        }

        .procurement-table .total-label {
            color: #1a1a2e;
        }

        .procurement-table .total-value {
            color: #1a1a2e;
            font-weight: 700;
        }

        .procurement-report {
            border: 1px solid #d8e6e2;
            box-shadow: 0 18px 45px rgba(15, 118, 110, 0.08);
        }

        .procurement-summary-header {
            display: flex;
            justify-content: space-between;
            gap: 1rem;
            align-items: flex-start;
            margin-bottom: 1rem;
        }

        .procurement-summary-title {
            font-size: 1.12rem;
            font-weight: 800;
            color: #102a43;
            margin-bottom: 0.25rem;
        }

        .procurement-summary-subtitle {
            font-size: 0.82rem;
            color: #64748b;
        }

        .procurement-status-row {
            display: flex;
            flex-wrap: wrap;
            gap: 0.5rem;
            justify-content: flex-end;
        }

        .procurement-status {
            display: inline-flex;
            align-items: center;
            padding: 0.35rem 0.65rem;
            border-radius: 999px;
            font-size: 0.76rem;
            font-weight: 700;
            background: #ecfdf5;
            color: #047857;
            border: 1px solid #a7f3d0;
        }

        .procurement-summary-grid {
            display: grid;
            grid-template-columns: repeat(4, 1fr);
            gap: 0.85rem;
            margin-bottom: 1.25rem;
        }

        .procurement-summary-metric {
            background: #f8fafc;
            border: 1px solid #e2e8f0;
            border-radius: 12px;
            padding: 0.9rem 1rem;
        }

        .procurement-summary-metric.primary {
            background: linear-gradient(135deg, #ecfdf5, #f8fafc);
            border-color: #99f6e4;
        }

        .procurement-subheading {
            font-size: 0.82rem;
            font-weight: 800;
            letter-spacing: 0.04em;
            color: #475569;
            text-transform: uppercase;
            margin: 1.25rem 0 0.65rem;
        }

        .priority-badge {
            display: inline-flex;
            padding: 0.25rem 0.55rem;
            border-radius: 999px;
            font-size: 0.72rem;
            font-weight: 700;
            background: #ecfdf5;
            color: #047857;
        }

        .why-selected-grid {
            display: grid;
            grid-template-columns: repeat(2, minmax(0, 1fr));
            gap: 0.75rem;
        }

        .why-selected-card {
            background: #f8fafc;
            border: 1px solid #e2e8f0;
            border-radius: 12px;
            padding: 0.9rem 1rem;
        }

        .why-selected-product {
            font-size: 0.9rem;
            font-weight: 800;
            color: #102a43;
            margin-bottom: 0.45rem;
        }

        .why-selected-card ul {
            margin: 0;
            padding-left: 1.1rem;
            color: #475569;
            font-size: 0.82rem;
            line-height: 1.5;
        }

        .procurement-notes {
            background: #f0fdfa;
            border: 1px solid #99f6e4;
            color: #134e4a;
            border-radius: 12px;
            padding: 0.9rem 1rem;
            font-size: 0.88rem;
            font-weight: 600;
            line-height: 1.5;
        }

        @media (max-width: 760px) {
            .procurement-summary-header {
                flex-direction: column;
            }

            .procurement-status-row {
                justify-content: flex-start;
            }

            .procurement-summary-grid,
            .replenishment-metrics,
            .why-selected-grid {
                grid-template-columns: 1fr;
            }
        }

        div[data-testid="stTextInput"] input {
            border-radius: 10px !important;
            border: 1px solid #dee2e6 !important;
            background: #fff !important;
            color: #1a1a2e !important;
            font-size: 0.88rem !important;
            min-height: 44px !important;
        }

        div[data-testid="stTextInput"] input:focus {
            border-color: #7c3aed !important;
            box-shadow: 0 0 0 3px rgba(124, 58, 237, 0.1) !important;
        }

        div[data-testid="stForm"] {
            display: block;
            margin-top: 0.5rem;
            padding-top: 0.75rem;
            border-top: 1px solid #e9ecef;
        }

        div[data-testid="stForm"] > div:first-child {
            width: 100%;
        }

        div[data-testid="stForm"] button[kind="secondary"],
        div[data-testid="stForm"] button[kind="primary"] {
            background: #7c3aed !important;
            border: none !important;
            color: #fff !important;
            min-height: 44px !important;
            border-radius: 10px !important;
            font-weight: 600 !important;
            white-space: nowrap !important;
            padding: 0 1.2rem !important;
        }

        div[data-testid="stForm"] button[kind="secondary"]:hover,
        div[data-testid="stForm"] button[kind="primary"]:hover {
            background: #6d28d9 !important;
        }

        /* Section heading */
        .section-heading {
            font-size: 1.05rem;
            font-weight: 700;
            color: #1a1a2e;
            margin-bottom: 1rem;
        }

        /* Hide sidebar nav */
        [data-testid="stSidebarNav"] {
            display: none;
        }
        </style>
        """,
        unsafe_allow_html=True,
    )


def render_header(
    customer_name: str | None = None,
    industry: str = "Retail - Grocery",
) -> None:
    if customer_name is None:
        customer_name = get_settings().default_customer_name
    from datetime import datetime
    now = datetime.now()
    html = (
        '<div class="app-header">'
        '<div class="app-header-left">'
        f'<h1>AI Smart Procurement Assistant</h1>'
        '<div class="app-header-meta">'
        f'<span>🏪 {escape(customer_name)}</span>'
        '<span class="dot"></span>'
        f'<span> {escape(industry)}</span>'
        '</div>'
        '</div>'
        '<div class="app-header-right">'
        '<div class="analysis-label">📋 Analysis Time</div>'
        f'<div class="analysis-time">{now.strftime("%B %d, %Y")} · {now.strftime("%H:%M")}</div>'
        '</div>'
        '</div>'
    )
    st.markdown(html, unsafe_allow_html=True)


def render_ai_request_section() -> tuple[str, bool]:
    st.markdown(
        '<div class="section-card">',
        unsafe_allow_html=True,
    )
    st.markdown(
        '<div class="section-card-header">'
        '<div class="section-icon section-icon-purple">✦</div>'
        '<div>'
        '<div class="section-title">AI Procurement Request</div>'
        '<div class="section-subtitle">Describe your needs in natural language</div>'
        '</div>'
        '</div>',
        unsafe_allow_html=True,
    )
    with st.form("ai_procurement_request_form"):
        request = st.text_area(
            "Request",
            value=st.session_state.get(
                "ai_request",
                "Traffic is expected to increase next week. Budget is NZD 1000. Avoid short shelf-life products.",
            ),
            key="ai_request",
            height=90,
            label_visibility="collapsed",
        )
        submitted = st.form_submit_button("Generate procurement plan", type="primary")
    st.markdown('</div>', unsafe_allow_html=True)
    return request, submitted


def _titleize_signal(value: Any) -> str:
    if value is None or value == "":
        return "Not provided"
    return str(value).replace("_", " ").title()


def _confidence_class(level: str) -> str:
    normalized = (level or "").lower()
    if normalized == "high":
        return "pill-green"
    if normalized == "medium":
        return "pill-amber"
    return "pill-red"


def render_ai_understanding(context: dict[str, Any]) -> None:
    business_intent = context.get("BusinessIntent") or {}
    decision_signals = context.get("DecisionSignals") or {}
    uncertainty = context.get("Uncertainty") or {}
    missing_information = context.get("MissingInformation") or []
    readiness = context.get("RecommendationReadiness") or {}

    primary_intent = _titleize_signal(business_intent.get("PrimaryIntent", "general_planning"))
    urgency = _titleize_signal(business_intent.get("Urgency", "medium"))
    decision_type = _titleize_signal(business_intent.get("DecisionType", "planning"))
    confidence_level = str(readiness.get("ConfidenceLevel", "medium")).title()
    confidence_score = readiness.get("ConfidenceScore")
    confidence_display = confidence_level
    if isinstance(confidence_score, (int, float)):
        confidence_display = f"{confidence_level} · {confidence_score:.0%}"

    budget = context.get("Budget")
    budget_mode = "No Budget Constraint" if budget is None else f"Budget NZD {budget}"

    missing_items = []
    for item in missing_information[:3]:
        field = item.get("Field", "")
        importance = item.get("Importance", "optional")
        impact = item.get("Impact", "")
        if not field:
            continue
        missing_items.append(
            '<div class="understanding-mini-row">'
            f'<span class="understanding-mini-label">{escape(_titleize_signal(field))}</span>'
            f'<span class="understanding-mini-value">{escape(_titleize_signal(importance))}: {escape(impact)}</span>'
            '</div>'
        )

    if not missing_items:
        missing_items.append(
            '<div class="understanding-mini-row">'
            '<span class="understanding-mini-label">Missing Info</span>'
            '<span class="understanding-mini-value">No major blocking information detected.</span>'
            '</div>'
        )

    follow_up = readiness.get("FollowUpQuestion") if readiness.get("ShouldAskFollowUp") else ""
    follow_up_html = ""
    if follow_up:
        follow_up_html = (
            '<div class="understanding-follow-up">'
            f'<strong>Suggested follow-up:</strong> {escape(str(follow_up))}'
            '</div>'
        )

    field_sources = uncertainty.get("FieldSources") or {}
    source_summary = ", ".join(
        f"{_titleize_signal(key)}: {_titleize_signal(value)}"
        for key, value in field_sources.items()
        if key in {"budget", "traffic_level", "promotion_flag", "shelf_life_preference"}
    )

    st.markdown(
        '<div class="section-card understanding-card">'
        '<div class="section-card-header">'
        '<div class="section-icon section-icon-blue">AI</div>'
        '<div>'
        '<div class="section-title">AI Understanding</div>'
        '<div class="section-subtitle">Procurement consultant view of the request</div>'
        '</div>'
        '</div>'
        '<div class="understanding-grid">'
        '<div class="understanding-panel">'
        '<div class="understanding-panel-title">Business Intent</div>'
        f'<div class="understanding-primary">{escape(primary_intent)}</div>'
        f'<div class="understanding-secondary">Urgency: {escape(urgency)} · Decision: {escape(decision_type)}</div>'
        '</div>'
        '<div class="understanding-panel">'
        '<div class="understanding-panel-title">Decision Signals</div>'
        f'<div class="understanding-primary">{escape(_titleize_signal(decision_signals.get("ExpectedDemandChange", "unknown")))} Demand</div>'
        f'<div class="understanding-secondary">Driver: {escape(_titleize_signal(decision_signals.get("DemandDriver", "unknown")))} · {escape(budget_mode)}</div>'
        '</div>'
        '<div class="understanding-panel">'
        '<div class="understanding-panel-title">Risk Sensitivity</div>'
        f'<div class="understanding-primary">Stockout {escape(_titleize_signal(decision_signals.get("StockoutSensitivity", "medium")))}</div>'
        f'<div class="understanding-secondary">Waste: {escape(_titleize_signal(decision_signals.get("WasteSensitivity", "medium")))} · Price: {escape(_titleize_signal(decision_signals.get("PriceSensitivity", "medium")))}</div>'
        '</div>'
        '<div class="understanding-panel">'
        '<div class="understanding-panel-title">Recommendation Confidence</div>'
        f'<div class="understanding-primary"><span class="understanding-pill {_confidence_class(str(readiness.get("ConfidenceLevel", "medium")))}">{escape(confidence_display)}</span></div>'
        f'<div class="understanding-secondary">{escape(source_summary)}</div>'
        '</div>'
        '</div>'
        '<div class="understanding-missing">'
        '<div class="understanding-panel-title">Missing Information</div>'
        f'{"".join(missing_items)}'
        f'{follow_up_html}'
        '</div>'
        '</div>',
        unsafe_allow_html=True,
    )


def _get_action_tag(strength: str, coverage_days: float | None) -> tuple[str, str]:
    if strength in ("Very High", "High"):
        if coverage_days is not None and coverage_days <= 3:
            return "Order Immediately", "tag-immediate"
        return "Order This Week", "tag-this-week"
    return "Monitor", "tag-monitor"


def render_replenishment_section(replenishment: list[dict[str, Any]]) -> None:
    st.markdown('<h2 class="section-heading">Recommended Replenishment</h2>', unsafe_allow_html=True)

    if not replenishment:
        st.markdown(
            '<div class="section-card" style="color:#6c757d;font-size:0.88rem;padding:1rem 1.25rem;">'
            'No replenishment recommendations for the current session. Try adjusting your request.'
            '</div>',
            unsafe_allow_html=True,
        )
        return

    html_parts = ['<div class="replenishment-list">']
    for item in replenishment[:8]:
        action_label, action_class = _get_action_tag(item.get("recommendation_strength", ""), item.get("coverage_days"))
        coverage = item.get("coverage_days")
        coverage_display = f"{coverage:.0f} Days" if coverage is not None else "N/A"
        if coverage is not None and coverage < 1:
            coverage_display = "< 1 Day"

        strength = item.get("recommendation_strength", "Low")
        strength_class = f"strength-{strength.lower().replace(' ', '-')}"
        score = item.get("score", 0)

        html_parts.append(
            f'<div class="replenishment-card">'
            f'<div class="replenishment-card-top">'
            f'<span class="replenishment-product">{escape(item["product"])}</span>'
            f'<span class="action-tag {action_class}">{escape(action_label)}</span>'
            f'</div>'
            f'<div class="replenishment-desc">{escape(item["why"][0] if item.get("why") else "Recommended based on current inventory and demand analysis.")}</div>'
            f'<div class="replenishment-metrics">'
            f'<div><div class="metric-label">Current Inventory</div><div class="metric-value">{escape(str(item.get("current_stock", "N/A")))}</div></div>'
            f'<div><div class="metric-label">Suggested Purchase</div><div class="metric-value highlight">{escape(str(item.get("quantity", 0)))} {escape(item.get("unit", ""))}</div></div>'
            f'<div><div class="metric-label">Inventory Coverage</div><div class="metric-value">🕐 {coverage_display}</div></div>'
            f'<div><div class="metric-label">Recommendation Strength</div><div class="metric-value {strength_class}">{escape(strength)} ({score:.0f}%)</div></div>'
            f'</div>'
            f'</div>'
        )
    html_parts.append('</div>')
    st.markdown("".join(html_parts), unsafe_allow_html=True)


def render_growth_section(growth: list[dict[str, Any]]) -> None:
    st.markdown('<h2 class="section-heading" style="margin-top:1.5rem;">Growth Opportunities</h2>', unsafe_allow_html=True)

    if not growth:
        st.markdown(
            '<div class="section-card" style="color:#6c757d;font-size:0.88rem;padding:1rem 1.25rem;">'
            'No growth opportunities found for the current session.'
            '</div>',
            unsafe_allow_html=True,
        )
        return

    html_parts = ['<div class="growth-list">']
    for item in growth[:6]:
        strength = item.get("recommendation_strength", "Low")
        potential_class = f"potential-{strength.lower().replace(' ', '-')}"
        potential_label = f"{strength} Potential"

        html_parts.append(
            f'<div class="growth-card">'
            f'<div class="growth-card-top">'
            f'<span class="growth-product">{escape(item["product"])}</span>'
            f'<span class="growth-category">({escape(item.get("unit", ""))})</span>'
            f'<span class="growth-potential {potential_class}">↗ {escape(potential_label)}</span>'
            f'</div>'
            f'<div class="growth-desc">{escape(item["why"][0] if item.get("why") else "Growing trend with strong market potential.")}</div>'
            f'</div>'
        )
    html_parts.append('</div>')
    st.markdown("".join(html_parts), unsafe_allow_html=True)


def classify_risks(risks: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    """Classify risks into out_of_stock, overstock, and near_expiry categories.

    No position-based fallback: if a category has no items, it stays empty.
    """
    out_of_stock = [r for r in risks if r.get("risk_level") in ("Critical", "High")]
    overstock = [
        r for r in risks
        if r.get("coverage_days") is not None and r.get("coverage_days", 0) > 30
    ]
    near_expiry = [r for r in risks if r.get("risk_level") == "Medium"]
    return {
        "out_of_stock": out_of_stock,
        "overstock": overstock,
        "near_expiry": near_expiry,
    }


def render_risks_section(risks: list[dict[str, Any]]) -> None:
    st.markdown('<h2 class="section-heading" style="margin-top:1.5rem;">Inventory Risks</h2>', unsafe_allow_html=True)

    classified = classify_risks(risks)
    out_of_stock = classified["out_of_stock"]
    overstock = classified["overstock"]
    near_expiry = classified["near_expiry"]

    tab1, tab2, tab3 = st.tabs([
        f"Out of Stock Risk ({len(out_of_stock)})",
        f"Overstock Risk ({len(overstock)})",
        f"Near Expiry ({len(near_expiry)})",
    ])

    with tab1:
        _render_risk_list(out_of_stock[:5] if out_of_stock else risks[:5])

    with tab2:
        _render_risk_list(overstock[:5] if overstock else risks[:5])

    with tab3:
        _render_risk_list(near_expiry[:5] if near_expiry else risks[-5:])


def _render_risk_list(display_risks: list[dict[str, Any]]) -> None:
    if not display_risks:
        st.markdown('<div style="padding:1rem;color:#6c757d;font-size:0.88rem;">No items in this category.</div>', unsafe_allow_html=True)
        return

    html_parts = ['<div class="risk-list">']
    for item in display_risks:
        risk_level = item.get("risk_level", "Medium")
        icon_class = f"risk-icon-{risk_level.lower()}"
        level_class = f"level-{risk_level.lower()}"
        coverage = item.get("coverage_days")
        coverage_display = f"< 1 Day" if coverage is not None and coverage < 1 else f"{coverage:.0f} Days" if coverage is not None else "N/A"

        if risk_level in ("Critical", "High"):
            action_class = "risk-action-immediate"
            action_label = "Order Immediately"
        else:
            action_class = "risk-action-week"
            action_label = "Order This Week"

        html_parts.append(
            f'<div class="risk-item">'
            f'<div class="risk-item-left">'
            f'<div class="risk-icon {icon_class}">⚠</div>'
            f'<div>'
            f'<div class="risk-product">{escape(item["product"])} <span class="risk-product-unit">({escape(item.get("unit", ""))})</span></div>'
            f'<span class="risk-level-tag {level_class}">{escape(risk_level)}</span>'
            f'</div>'
            f'</div>'
            f'<div class="risk-item-right">'
            f'<div class="risk-coverage-label">Inventory Coverage</div>'
            f'<div class="risk-coverage-value">🕐 {coverage_display}</div>'
            f'<span class="risk-action-btn {action_class}">{escape(action_label)}</span>'
            f'</div>'
            f'</div>'
        )
    html_parts.append('</div>')
    st.markdown("".join(html_parts), unsafe_allow_html=True)


def render_procurement_plan_report(
    plan: list[dict[str, Any]],
    budget: float | None,
    context: dict[str, Any],
) -> None:
    """Render an AI-generated procurement decision report."""
    st.markdown('<h2 class="section-heading" style="margin-top:1.5rem;">Procurement Plan</h2>', unsafe_allow_html=True)

    total_investment = sum(float(item.get("estimated_cost", 0)) for item in plan)
    has_budget = budget is not None
    remaining = max(budget - total_investment, 0) if has_budget else None
    is_optimized = has_budget and total_investment > 0 and remaining / max(budget, 1) <= 0.2
    budget_display = f"NZD {budget:.0f}" if has_budget else "No constraint"
    remaining_display = f"NZD {remaining:.0f}" if remaining is not None else "Not constrained"
    status_primary = "Within Budget" if has_budget else "No Budget Constraint"
    status_secondary = "Budget Optimized" if is_optimized else ("Budget Protected" if has_budget else "Priority Ranked")
    notes = (
        "This plan prioritizes high-demand products while remaining within budget and reducing stockout risk."
        if has_budget
        else "This plan prioritizes high-demand products without applying a budget constraint."
    )

    html_parts = ['<div class="section-card procurement-report">']

    html_parts.append(
        '<div class="procurement-summary-header">'
        '<div>'
        '<div class="procurement-summary-title">Procurement Summary</div>'
        '<div class="procurement-summary-subtitle">AI-generated purchase decision report for the selected business request.</div>'
        '</div>'
        '<div class="procurement-status-row">'
        f'<span class="procurement-status">{status_primary}</span>'
        f'<span class="procurement-status">{status_secondary}</span>'
        '</div>'
        '</div>'
        '<div class="procurement-summary-grid">'
        f'<div class="procurement-summary-metric primary"><div class="metric-label">Budget</div><div class="metric-value">{budget_display}</div></div>'
        f'<div class="procurement-summary-metric primary"><div class="metric-label">Total Investment</div><div class="metric-value highlight">NZD {total_investment:.0f}</div></div>'
        f'<div class="procurement-summary-metric"><div class="metric-label">Remaining Budget</div><div class="metric-value">{remaining_display}</div></div>'
        f'<div class="procurement-summary-metric"><div class="metric-label">Recommended Products</div><div class="metric-value">{len(plan)}</div></div>'
        '</div>'
    )

    if plan:
        table_rows = ""
        for item in plan[:8]:
            table_rows += (
                f'<tr>'
                f'<td>{escape(item["product"])}</td>'
                f'<td>{int(item.get("quantity", 0))}</td>'
                f'<td>{escape(item.get("unit", ""))}</td>'
                f'<td style="font-weight:700;">NZD {float(item.get("estimated_cost", 0)):.0f}</td>'
                f'<td><span class="priority-badge">{escape(item.get("action") or item.get("priority") or item.get("recommendation_strength", ""))}</span></td>'
                f'</tr>'
            )

        html_parts.append(
            '<div class="procurement-subheading">Recommended Products Table</div>'
            f'<table class="procurement-table">'
            f'<tr><th>Product</th><th>Quantity</th><th>Unit</th><th>Estimated Cost</th><th>Priority</th></tr>'
            f'{table_rows}'
            f'<tr class="total-row"><td class="total-label" colspan="3">Total Investment</td><td class="total-value">NZD {total_investment:.0f}</td><td></td></tr>'
            f'</table>'
        )

        html_parts.append('<div class="procurement-subheading">Why Selected</div><div class="why-selected-grid">')
        for item in plan[:6]:
            reasons = _procurement_reasons(item, context)
            reason_items = "".join(f'<li>{escape(reason)}</li>' for reason in reasons[:3])
            html_parts.append(
                '<div class="why-selected-card">'
                f'<div class="why-selected-product">{escape(item["product"])}</div>'
                f'<ul>{reason_items}</ul>'
                '</div>'
            )
        html_parts.append('</div>')

        html_parts.append(
            '<div class="procurement-subheading">Procurement Notes</div>'
            '<div class="procurement-notes">'
            f'{notes}'
            '</div>'
        )
    else:
        html_parts.append(
            '<div style="color:#6c757d;font-size:0.88rem;">No procurement plan available for the current session.</div>'
        )

    html_parts.append('</div>')
    st.markdown("".join(html_parts), unsafe_allow_html=True)


def _procurement_reasons(item: dict[str, Any], context: dict[str, Any]) -> list[str]:
    business_reasons: list[str] = []

    action = item.get("action")
    if action:
        business_reasons.append(f"Recommended action: {action}.")

    coverage = item.get("coverage_days")
    if coverage is not None:
        if coverage < 1:
            business_reasons.append("Inventory is critically low with less than 1 day of coverage.")
        elif coverage <= 3:
            business_reasons.append(f"Inventory covers only {coverage:.0f} days, creating stockout risk.")
        elif coverage <= 7:
            business_reasons.append(f"Inventory covers {coverage:.0f} days, so replenishment should happen this week.")

    price_trend = item.get("price_trend") or {}
    price_signal = price_trend.get("price_signal")
    if price_signal == "Buy Now":
        business_reasons.append("Current price is near the 90-day low, making this a favorable buying window.")
    elif price_signal == "Wait":
        business_reasons.append("Current price is high, so quantity is controlled unless stockout risk is urgent.")
    elif price_signal == "Fair Price":
        business_reasons.append("Current price is close to the recent average, supporting a normal purchase decision.")

    if item.get("priority") == "Trial Buy":
        business_reasons.append("Small trial quantity limits risk while testing a growth opportunity.")

    if context.get("TrafficLevel") == "HIGH":
        business_reasons.append("Expected high traffic increases near-term demand.")

    if context.get("PromotionFlag"):
        business_reasons.append("Promotion or holiday signal supports higher demand readiness.")

    for raw_reason in item.get("why", []):
        if len(business_reasons) >= 3:
            break
        converted = _business_reason_from_raw(str(raw_reason))
        if converted and converted not in business_reasons:
            business_reasons.append(converted)

    if not business_reasons:
        business_reasons.append("Selected because it has the strongest combined demand, inventory, price, and budget fit.")

    return business_reasons[:3]


def _business_reason_from_raw(reason: str) -> str | None:
    if "Purchased" in reason and "last 90 days" in reason:
        return "Recent purchase history shows proven customer demand."
    if "Average cycle" in reason:
        return "Purchase cycle indicates this item is due for review."
    if "Inventory covers" in reason:
        return None
    if "Industry coverage rate" in reason:
        return "Strong adoption across similar businesses indicates whitespace potential."
    if "Popularity score" in reason:
        return "High industry popularity supports a low-risk trial."
    if "Profit margin" in reason:
        return "Margin profile supports testing this product commercially."
    if "Trial quantity recommended" in reason:
        return "Trial quantity limits risk while validating demand."
    if "Favorited" in reason:
        return "Customer preference signal supports prioritizing this product."
    if "90-day low" in reason:
        return "Current price is near the 90-day low, making this a favorable buying window."
    if "90-day high" in reason:
        return "Current price is high, so quantity is controlled unless stockout risk is urgent."
    return reason if reason else None
