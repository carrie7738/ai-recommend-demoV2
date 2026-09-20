"""Developer only rendering for request-local procurement traces.

The trace is deliberately treated as an observation.  This module never feeds
the trace back into the recommendation workflow and never invents a captured
event when one is absent.
"""

from __future__ import annotations

import json
import os
from html import escape
from typing import Any, Iterable

import pandas as pd
import streamlit as st

from services.runtime_trace import snapshot


TRACE_STAGES: tuple[tuple[str, str, str], ...] = (
    ("request", "请求", "接收本次采购请求及运行参数。"),
    ("intent_input", "意图输入", "发送给意图理解器的输入和约束。"),
    ("intent_output", "意图输出", "意图理解器返回的结构化结果。"),
    ("business_context", "业务上下文", "用于本次决策的门店、事件和业务背景。"),
    ("candidate_pool", "候选池", "按确定性规则生成的候选商品及淘汰原因。"),
    ("features", "决策特征", "为候选商品计算的需求、库存和相关性特征。"),
    ("decision_input", "决策输入", "提交给决策模型的安全输入。"),
    ("decision_output", "决策输出", "决策模型返回的商品选择和采购策略。"),
    ("optimizer", "本地优化", "将决策转换为数量、成本和预算结果。"),
    ("validation", "校验", "独立校验和必要的本地修复结果。"),
    ("final", "最终结果", "最终采购结果及其来源、状态。"),
)

def debug_trace_enabled() -> bool:
    """Return whether developer trace UI is allowed for this process.

    The environment flag is the safety gate.  A query parameter is deliberately
    not required, so local developers can turn the panel on for every request
    with ``PROCUREMENT_DEBUG=true``.  ``debug=true`` therefore remains an
    optional URL convention without allowing a URL to bypass the environment
    gate.
    """

    return os.getenv("PROCUREMENT_DEBUG", "").strip().casefold() == "true"


def render_debug_trace(trace: dict[str, Any] | None, result: dict[str, Any] | None = None) -> None:
    """Render an observed trace as a compact, inspectable eleven-step view.

    ``result`` is only a display fallback for the final step when no captured
    ``final`` event contains an output.  It is never copied into ``trace`` or
    used to fill a missing intermediate stage.
    """

    if not debug_trace_enabled():
        return
    if not isinstance(trace, dict):
        st.info("当前请求还没有可用的 Debug Trace。")
        return

    safe_trace = _safe_snapshot(trace)
    if not isinstance(safe_trace, dict):
        safe_trace = {
            "run_id": "[REDACTED]",
            "started_at": "[REDACTED]",
            "events": [],
            "metadata": {"snapshot_status": "failed"},
        }
    raw_events = safe_trace.get("events")
    events = [event for event in raw_events if isinstance(event, dict)] if isinstance(raw_events, list) else []
    safe_result = _safe_snapshot(result) if isinstance(result, dict) else None
    if not isinstance(safe_result, dict):
        safe_result = None

    st.markdown("## Debug Trace")
    run_id = safe_trace.get("run_id") or "未提供"
    started_at = safe_trace.get("started_at") or "未提供"
    st.caption(f"运行 ID：{run_id} · 开始时间：{started_at} · 已捕获事件：{len(events)}")

    sku_filter = st.text_input(
        "按 SKU 筛选事件（字符串匹配）",
        key="debug_trace_sku_filter",
        placeholder="例如 P001",
    ).strip()
    visible_events = _filter_events(events, sku_filter)
    if sku_filter:
        st.caption("当前筛选按事件 JSON 字符串匹配，可能命中商品名称或其他字段；仅影响展示，不会重新运行请求。")
        st.caption(f"筛选结果：{len(visible_events)}/{len(events)} 个事件")

    event_groups = _group_events(visible_events)
    all_event_groups = _group_events(events)
    final_event = _latest_event(all_event_groups.get("final", []))
    final_payload, final_source = _final_payload(all_event_groups.get("final", []), safe_result)
    _render_trace_overview(events, final_event, final_payload)

    for index, (stage, label, description) in enumerate(TRACE_STAGES, start=1):
        stage_events = event_groups.get(stage, [])
        st.markdown(f"### {index}. {label} `{stage}`")
        st.caption(description)
        if not stage_events:
            if sku_filter and all_event_groups.get(stage):
                st.info("按当前 SKU 筛选后没有匹配事件。")
            elif stage == "final" and final_payload is not None and final_source != "captured":
                _render_final_step(
                    final_payload,
                    final_source,
                    final_event,
                    all_event_groups.get("final", []),
                )
            else:
                st.info("未采集：当前请求未覆盖此步骤。")
            continue

        _render_stage_events(stage, stage_events)
        if stage == "candidate_pool":
            _render_candidate_pool_summary(stage_events)
        elif stage == "features":
            _render_features_summary(stage_events)
        elif stage == "decision_output":
            _render_decision_summary(stage_events)
        elif stage == "optimizer":
            _render_optimizer_summary(stage_events)
        elif stage == "validation":
            _render_validation_summary(stage_events)
        elif stage == "final":
            _render_final_step(final_payload, final_source, final_event, stage_events)

    with st.expander("原始 JSON", expanded=False):
        st.json(safe_trace)

    download_data = json.dumps(safe_trace, ensure_ascii=False, indent=2, default=str)
    st.download_button(
        "下载脱敏 Trace JSON",
        data=download_data,
        file_name=f"procurement-trace-{run_id}.json",
        mime="application/json",
        key="download_debug_trace",
    )


def _safe_snapshot(value: Any) -> Any:
    """Snapshot again at the UI boundary, then guarantee JSON compatibility."""

    try:
        return snapshot(value)
    except Exception:
        # Never fall back to rendering an arbitrary object: it may contain a
        # secret that the runtime snapshot could not traverse safely.
        return "[REDACTED: snapshot unavailable]"


def _filter_events(events: Iterable[dict[str, Any]], sku_filter: str) -> list[dict[str, Any]]:
    if not sku_filter:
        return list(events)
    needle = sku_filter.casefold()
    filtered: list[dict[str, Any]] = []
    for event in events:
        encoded = json.dumps(_safe_snapshot(event), ensure_ascii=False, default=str).casefold()
        if needle in encoded:
            filtered.append(event)
    return filtered


def _group_events(events: Iterable[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    groups: dict[str, list[dict[str, Any]]] = {}
    for event in events:
        stage = str(event.get("stage") or "").strip()
        if stage:
            groups.setdefault(stage, []).append(event)
    return groups


def _latest_event(events: list[dict[str, Any]]) -> dict[str, Any] | None:
    if not events:
        return None
    return events[-1]


def _render_stage_events(stage: str, events: list[dict[str, Any]]) -> None:
    latest = events[-1]
    owner = str(latest.get("owner") or "未知")
    status = str(latest.get("status") or "未知")
    duration = latest.get("duration_ms")
    duration_text = f" · 耗时 {duration} ms" if duration is not None else ""
    st.markdown(f"**负责人：**{escape(owner)}　**状态：**{escape(status)}{duration_text}")
    if len(events) > 1:
        st.caption(f"本步骤共捕获 {len(events)} 个事件，以下显示全部事件详情。")
    for event_index, event in enumerate(events, start=1):
        event_status = str(event.get("status") or "未知")
        event_owner = str(event.get("owner") or "未知")
        operation = str(event.get("operation") or "")
        suffix = f" · {operation}" if operation else ""
        title = (
            f"事件 {event_index} · {event_status} · {event_owner}{suffix}"
            if len(events) > 1
            else f"事件详情 · {event_status} · {event_owner}{suffix}"
        )
        with st.expander(title, expanded=False):
            sequence = event.get("sequence")
            duration = event.get("duration_ms")
            detail = f"序号：{sequence if sequence is not None else '未知'}"
            if duration is not None:
                detail += f" · 耗时：{duration} ms"
            st.caption(detail)
            st.markdown(f"**负责人：**{escape(event_owner)}　**状态：**{escape(event_status)}")
            _render_event_payload(event)


def _render_trace_overview(
    events: list[dict[str, Any]],
    final_event: dict[str, Any] | None,
    final_payload: dict[str, Any] | None,
) -> None:
    """Surface only values observed in the trace, with explicit gaps."""
    groups = _group_events(events)
    request_event = _latest_event(groups.get("request", []))
    request_input = request_event.get("input") if request_event else {}
    if not isinstance(request_input, dict):
        request_input = {}

    provider_event = _latest_event(groups.get("actual_provider_request", []))
    # Provider records use a stage named intent_input/decision_input and expose
    # operation=actual_provider_request, so inspect both the stage and operation.
    if provider_event is None:
        provider_event = next(
            (event for event in reversed(events) if event.get("operation") == "actual_provider_request"),
            None,
        )
    provider = provider_event.get("provider") if provider_event else None
    provider_input = provider_event.get("input") if provider_event else {}
    if isinstance(provider_input, dict):
        provider = provider or provider_input.get("provider")
    model = provider_input.get("model") if isinstance(provider_input, dict) else None

    intent_event = _latest_event(groups.get("intent_output", []))
    intent_output = intent_event.get("output") if intent_event else None
    intent_status = None
    if isinstance(intent_output, dict):
        intent_status = intent_output.get("AIAnalysisStatus")
        raw_json = intent_output.get("raw_json")
        if intent_status is None and isinstance(raw_json, dict):
            intent_status = raw_json.get("AIAnalysisStatus")
    if intent_status is None and intent_event:
        intent_status = "fallback" if intent_event.get("status") == "fallback" else intent_event.get("status")

    pipeline_status = final_payload.get("pipeline_status", {}) if isinstance(final_payload, dict) else {}
    decision_mode = (
        final_payload.get("decision_mode") if isinstance(final_payload, dict) else None
    ) or (pipeline_status.get("decision_mode") if isinstance(pipeline_status, dict) else None)
    retry_count = final_payload.get("retry_count") if isinstance(final_payload, dict) else None
    final_status = final_event.get("status") if final_event else None

    date_context = {}
    for event in groups.get("business_context", []):
        output = event.get("output")
        if isinstance(output, dict):
            for key in ("as_of_date_source", "effective_as_of_date"):
                if output.get(key) is not None:
                    date_context[key] = output[key]
    if "effective_as_of_date" not in date_context and isinstance(final_payload, dict):
        date_context["effective_as_of_date"] = final_payload.get("effective_as_of_date")

    values = [
        f"Customer ID：{request_input.get('customer_id') or '未采集'}",
        f"as_of_date：{request_input.get('as_of_date') or '未采集'}",
        f"as_of_date_source：{date_context.get('as_of_date_source') or '未采集'}",
        f"effective_as_of_date：{date_context.get('effective_as_of_date') or '未采集'}",
        f"Provider：{provider or '未采集'}",
        f"Model：{model or '未采集'}",
        f"Intent：{intent_status or '未采集'}",
        f"决策模式：{decision_mode or '未采集'}",
        f"Retry：{retry_count if retry_count is not None else '未采集'}",
        f"最终状态：{final_status or '未采集'}",
    ]
    st.caption("运行概览 · " + " · ".join(values))


def _render_event_payload(event: dict[str, Any]) -> None:
    input_value = event.get("input")
    output_value = event.get("output")
    error = event.get("error")
    if input_value is not None:
        st.markdown("**输入**")
        st.json(_safe_snapshot(input_value))
    if output_value is not None:
        st.markdown("**输出**")
        st.json(_safe_snapshot(output_value))
    if error:
        st.error(f"错误：{error}")
    extras = {
        key: value
        for key, value in event.items()
        if key not in {"sequence", "stage", "owner", "status", "input", "output", "error"}
    }
    if extras:
        st.markdown("**附加信息**")
        st.json(_safe_snapshot(extras))


def _payloads(events: list[dict[str, Any]]) -> list[Any]:
    payloads: list[Any] = []
    for event in reversed(events):
        for key in ("output", "input"):
            value = event.get(key)
            if value is not None:
                payloads.append(value)
    return payloads


def _list_from_payload(payload: Any, keys: tuple[str, ...]) -> list[Any]:
    if isinstance(payload, list):
        return payload
    if not isinstance(payload, dict):
        return []
    for key in keys:
        value = payload.get(key)
        if isinstance(value, list):
            return value
    return []


def _render_candidate_pool_summary(events: list[dict[str, Any]]) -> None:
    rows: list[dict[str, Any]] = []
    for payload in _payloads(events):
        if not isinstance(payload, dict):
            continue
        if payload.get("candidate_id") or payload.get("sku"):
            rows.append(_candidate_row(payload, payload.get("eligible") is not False))
            continue
        eligible = _list_from_payload(payload, ("eligible_candidates", "eligible", "candidates"))
        rejected = _list_from_payload(payload, ("rejected_candidates", "rejected"))
        if not eligible and not rejected:
            nested = payload.get("candidate_pool")
            if isinstance(nested, dict):
                eligible = _list_from_payload(nested, ("eligible_candidates", "eligible"))
                rejected = _list_from_payload(nested, ("rejected_candidates", "rejected"))
        for candidate in eligible:
            if isinstance(candidate, dict):
                rows.append(_candidate_row(candidate, True))
        for candidate in rejected:
            if isinstance(candidate, dict):
                rows.append(_candidate_row(candidate, False))
        if rows:
            break
    if rows:
        st.markdown("**候选池摘要**")
        st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)


def _candidate_row(candidate: dict[str, Any], eligible: bool) -> dict[str, Any]:
    return {
        "SKU": candidate.get("candidate_id") or candidate.get("sku") or "",
        "商品": candidate.get("product_name") or candidate.get("product") or "",
        "类别": candidate.get("category") or "",
        "是否入池": "是" if eligible else "否",
        "来源": candidate.get("candidate_source") or candidate.get("recommendation_type") or "",
        "淘汰原因": candidate.get("rejection_code") or "",
        "可用库存": candidate.get("available_stock", ""),
    }


def _render_features_summary(events: list[dict[str, Any]]) -> None:
    candidates: list[Any] = []
    for payload in _payloads(events):
        if isinstance(payload, dict):
            # The runtime collector may emit one feature event per SKU:
            # {candidate_id, features, signals, raw_evidence}.
            if payload.get("candidate_id") and isinstance(payload.get("features"), dict):
                candidates.append(payload)
                continue
            nested = _list_from_payload(
                payload,
                ("candidates", "decision_features", "feature_rows", "features"),
            )
            if nested:
                candidates.extend(nested)
        elif isinstance(payload, list):
            candidates.extend(payload)
    rows: list[dict[str, Any]] = []
    for candidate in candidates:
        if not isinstance(candidate, dict):
            continue
        features = candidate.get("features")
        if not isinstance(features, dict):
            features = {}
        rows.append({
            "SKU": candidate.get("candidate_id") or candidate.get("sku") or "",
            "来源": candidate.get("candidate_source") or candidate.get("recommendation_type") or "",
            **{str(key): value for key, value in features.items()},
            "信号": ", ".join(str(item) for item in candidate.get("signals", []) or []),
            "原始证据": _compact_json(candidate.get("raw_evidence")),
        })
    if rows:
        st.markdown("**特征摘要**")
        st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)


def _decision_payload(events: list[dict[str, Any]]) -> dict[str, Any] | None:
    for payload in _payloads(events):
        if isinstance(payload, dict):
            if isinstance(payload.get("raw_json"), dict):
                return payload["raw_json"]
            return payload
    return None


def _render_decision_summary(events: list[dict[str, Any]]) -> None:
    payload = _decision_payload(events)
    decisions = _list_from_payload(payload, ("candidate_decisions", "decisions"))
    rows: list[dict[str, Any]] = []
    for decision in decisions:
        if isinstance(decision, dict):
            rows.append({
                "SKU": decision.get("candidate_id") or decision.get("sku") or "",
                "商品": decision.get("product_name") or "",
                "推荐": "是" if decision.get("recommended") is True else "否",
                "类型": decision.get("recommendation_type") or "",
                "优先级": decision.get("priority") or "",
                "补货强度": decision.get("replenishment_intensity") or "",
                "决策信号": ", ".join(str(item) for item in decision.get("decision_signals", []) or []),
            })
    if rows:
        st.markdown("**AI 决策摘要**")
        st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)


def _optimizer_payload(events: list[dict[str, Any]]) -> dict[str, Any] | None:
    for payload in _payloads(events):
        if isinstance(payload, dict):
            nested = payload.get("optimizer_result")
            if isinstance(nested, dict):
                return nested
            return payload
    return None


def _plan_rows(plan: Any) -> list[dict[str, Any]]:
    if not isinstance(plan, list):
        return []
    rows: list[dict[str, Any]] = []
    for item in plan:
        if not isinstance(item, dict):
            continue
        rows.append({
            "SKU": item.get("candidate_id") or item.get("product_id") or item.get("sku") or "",
            "商品": item.get("product_name") or item.get("product") or "",
            "数量": item.get("final_qty", item.get("quantity", "")),
            "单位": item.get("unit") or item.get("sales_unit") or "",
            "单位成本": item.get("unit_cost", ""),
            "预估成本": item.get("estimated_cost", ""),
            "优先级": item.get("priority") or item.get("action") or "",
            "类型": item.get("recommendation_type") or "",
        })
    return rows


def _compact_json(value: Any) -> str:
    if value is None or value == "":
        return ""
    try:
        return json.dumps(_safe_snapshot(value), ensure_ascii=False, default=str)
    except Exception:
        return "[不可显示]"


def _render_optimizer_summary(events: list[dict[str, Any]]) -> None:
    payload = _optimizer_payload(events)
    if not payload:
        return
    rows = _plan_rows(payload.get("purchase_plan"))
    st.markdown(
        f"**优化摘要** · 总成本：{_display_number(payload.get('total_cost'))} · "
        f"剩余预算：{_display_number(payload.get('remaining_budget'))}"
    )
    if rows:
        st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)
    elif isinstance(payload.get("purchase_plan"), list):
        st.caption("优化器未产生可执行采购数量。")


def _render_validation_summary(events: list[dict[str, Any]]) -> None:
    payload = None
    for candidate in _payloads(events):
        if isinstance(candidate, dict):
            nested = candidate.get("validation_result")
            payload = nested if isinstance(nested, dict) else candidate
            break
    if not payload:
        return
    status = payload.get("status") or ("PASS" if payload.get("valid") is True else "FAIL" if payload.get("valid") is False else "未知")
    violations = payload.get("violations") or []
    st.markdown(f"**校验摘要** · 状态：`{escape(str(status))}` · 违规数：{len(violations)}")
    if violations:
        violation_rows = [
            {
                "代码": item.get("code", "") if isinstance(item, dict) else str(item),
                "SKU": ", ".join(str(value) for value in item.get("candidate_ids", []) or []) if isinstance(item, dict) else "",
            }
            for item in violations
        ]
        st.dataframe(pd.DataFrame(violation_rows), use_container_width=True, hide_index=True)


def _final_payload(
    final_events: list[dict[str, Any]] | dict[str, Any] | None,
    result: dict[str, Any] | None,
) -> tuple[dict[str, Any] | None, str]:
    if isinstance(final_events, dict):
        candidates = [final_events]
    elif isinstance(final_events, list):
        candidates = final_events
    else:
        candidates = []
    for event in reversed(candidates):
        output = event.get("output") if isinstance(event, dict) else None
        if isinstance(output, dict) and _looks_like_final_result(output):
            return output, "captured"
    if isinstance(result, dict):
        return result, "页面结果（未捕获 final 输出）"
    return None, "未产生最终结果"


def _looks_like_final_result(output: dict[str, Any]) -> bool:
    return any(
        key in output
        for key in (
            "final_purchase_plan",
            "purchase_plan",
            "procurement_plan",
            "fallback_result",
            "v2_status",
            "pipeline_status",
        )
    )


def _render_final_step(
    payload: dict[str, Any] | None,
    source: str,
    final_event: dict[str, Any] | None,
    final_events: list[dict[str, Any]] | None = None,
) -> None:
    if payload is None:
        st.info("未产生最终结果。")
        return

    if source == "captured":
        st.success("结果来源：运行时 Trace 捕获的 final 事件。")
    else:
        if final_event is not None and final_event.get("status") in {"failed", "fallback"}:
            st.warning(f"结果来源：{source}；final 事件状态为 {final_event.get('status')}。")
        else:
            st.info(f"结果来源：{source}。")

    status = payload.get("v2_status") or payload.get("pipeline_status", {}).get("v2_status")
    if status:
        st.caption(f"流水线状态：{status}")
    outcome_codes = _render_candidate_outcomes(final_events or [])
    result_payload = payload
    plan = result_payload.get("final_purchase_plan")
    if plan is None:
        plan = result_payload.get("purchase_plan")
    if plan is None:
        plan = result_payload.get("procurement_plan")
    if plan is None and isinstance(payload.get("fallback_result"), dict):
        result_payload = payload["fallback_result"]
        plan = result_payload.get("final_purchase_plan")
        if plan is None:
            plan = result_payload.get("purchase_plan")
        if plan is None:
            plan = result_payload.get("procurement_plan")
    rows = _plan_rows(plan)
    if rows:
        st.markdown("**最终采购计划摘要**")
        st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)
    else:
        st.info(_no_purchase_message(payload, outcome_codes))

    validation = payload.get("validation_result")
    if isinstance(validation, dict) and validation.get("valid") is False:
        st.warning("最终结果校验未通过，采购计划不可执行。")
    if payload.get("fallback_triggered") or payload.get("pipeline_version") == "V1_FALLBACK":
        st.warning("本次结果来自规则 fallback。")


def _render_candidate_outcomes(events: list[dict[str, Any]]) -> list[str]:
    """Show where each candidate went when the pipeline captured that detail."""
    rows: list[dict[str, Any]] = []
    outcome_codes: list[str] = []
    for event in events:
        output = event.get("output")
        if not isinstance(output, dict):
            continue
        outcomes = output.get("candidate_outcomes")
        if not isinstance(outcomes, list):
            continue
        for item in outcomes:
            if isinstance(item, dict):
                outcome = str(item.get("outcome") or "")
                if outcome:
                    outcome_codes.append(outcome)
                rows.append({
                    "SKU": item.get("candidate_id") or item.get("sku") or "",
                    "去向": _outcome_label(outcome),
                    "原因": _display_reason(item.get("reason")),
                })
    if rows:
        st.markdown("**候选去向**")
        st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)
    return outcome_codes


def _outcome_label(value: Any) -> str:
    labels = {
        "RULE_REJECTED": "规则淘汰",
        "AI_NOT_SELECTED": "AI 未选中",
        "PURCHASED": "进入采购计划",
        "OPTIMIZER_UNALLOCATED": "优化器未分配数量",
        "VALIDATION_BLOCKED": "校验拦截",
        "NOT_IN_FINAL_PLAN": "未进入最终计划",
    }
    return labels.get(str(value or ""), str(value or "未说明"))


def _display_reason(value: Any) -> str:
    if value is None or value == "":
        return ""
    if isinstance(value, (list, tuple, set)):
        return ", ".join(str(item) for item in value)
    if isinstance(value, dict):
        return _compact_json(value)
    return str(value)


def _no_purchase_message(payload: dict[str, Any], outcome_codes: list[str]) -> str:
    """Explain an empty result without collapsing failure and no-op outcomes."""
    status = str(
        payload.get("v2_status")
        or payload.get("pipeline_status", {}).get("v2_status")
        or ""
    ).upper()
    decision_mode = str(
        payload.get("decision_mode")
        or payload.get("pipeline_status", {}).get("decision_mode")
        or ""
    ).upper()
    if payload.get("fallback_triggered") or payload.get("pipeline_version") == "V1_FALLBACK":
        return "规则 fallback 没有生成可执行采购数量。"
    if status == "FAILED":
        return "V2 流水线失败，未生成可执行采购计划。"
    if "VALIDATION_BLOCKED" in outcome_codes:
        return "候选结果被校验拦截，未生成可执行采购计划。"
    if "OPTIMIZER_UNALLOCATED" in outcome_codes:
        return "候选进入本地优化，但没有分配可执行数量。"
    if decision_mode == "LOCAL_NO_ELIGIBLE_CANDIDATES" or (outcome_codes and all(code == "RULE_REJECTED" for code in outcome_codes)):
        return "没有候选商品通过确定性规则，未生成采购项。"
    if "AI_NOT_SELECTED" in outcome_codes and all(code in {"AI_NOT_SELECTED", "RULE_REJECTED"} for code in outcome_codes):
        return "候选商品均未被 AI 选中，未生成采购项。"
    return "本次决策没有可执行采购数量。"


def _display_number(value: Any) -> str:
    if value is None or value == "":
        return "未提供"
    try:
        return f"{float(value):,.2f}"
    except (TypeError, ValueError):
        return str(value)
