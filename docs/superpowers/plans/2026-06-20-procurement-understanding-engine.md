# Procurement Understanding Engine 实施计划

> **给执行代理的要求：** 实施本计划时必须使用 `superpowers:subagent-driven-development`（推荐）或 `superpowers:executing-plans`。所有步骤使用 checkbox（`- [ ]`）追踪执行状态。

**目标：** 将当前 DeepSeek 语义抽取从“字段提取器”升级为“采购顾问式语义理解层”，识别业务意图、决策信号、不确定性、缺失信息和推荐可信度。

**架构：** AI 负责理解用户采购请求并形成结构化语义；规则引擎继续负责确定性推荐、数量计算、预算合规和采购计划生成。新增 `services/procurement_understanding.py` 承载语义归一化、fallback 语义构建和安全类型转换，避免继续扩大 `services/intent_parser.py` 的职责。UI 仍然使用英文展示，例如 `Business Intent`、`Decision Signals`、`Missing Information`、`Recommendation Confidence`。

**技术栈：** Python、Streamlit、Pandas、DeepSeek OpenAI-compatible client、unittest。

---

## 1. 范围和边界

### 本轮要做

- 扩展 DeepSeek prompt，使其输出采购顾问式语义结构。
- 保留现有兼容字段：`Budget`、`TrafficLevel`、`PromotionFlag`、`ShelfLifePreference`、`PreferredCategory`、`ExcludedCategory`、`TimeRange`、`ExpectedIntent`。
- 新增语义字段：`BusinessIntent`、`DecisionSignals`、`Uncertainty`、`MissingInformation`、`RecommendationReadiness`。
- 新增 `ProcurementUnderstandingBuilder`，负责把 AI 原始 JSON 或 fallback 基础字段归一化为稳定结构。
- 实现 C 模式缺失信息处理：高风险缺失信息显示追问和降低信心，但不阻塞当前推荐。
- 避免一次用户请求重复调用 DeepSeek。
- 重构 `AI Understanding` 区域，英文展示采购顾问视角理解结果。
- 更新内部开发文档和客户演示文档。文档说明文字统一中文，代码标识和 UI 文案可保留英文。

### 本轮不做

- 不让 AI 直接决定推荐商品、数量、预算分配。
- 不重写推荐引擎评分逻辑。
- 不引入多轮聊天状态机。
- 不接入新数据源。
- 不实现真实审批流或订单提交。

---

## 2. C 模式定义

本项目采用混合模式：

```text
高风险缺失信息：显示一个建议追问，降低 Recommendation Confidence，但不阻塞推荐。
普通缺失信息：只提示影响，继续推荐。
可选缺失信息：作为上下文说明，继续推荐。
基础数据缺失：由现有 workbook 校验阻塞，例如缺 Customer、Product、Inventory、OrderHistory。
```

当前 demo 的缺失信息等级：

- `budget`：可选。未提供时不使用测试场景预算，采购计划显示 `No Budget Constraint`。
- `time_horizon`：普通。未提供时推荐继续，但降低信心。
- `business_goal`、`demand_driver` 同时缺失：高风险。显示追问：`Are you optimizing for stockout prevention, budget control, or growth?`
- 客户、商品、订单、库存基础数据缺失：阻塞，由现有异常处理负责。

---

## 3. 目标语义结构

归一化后的 Python 字典必须保留旧字段：

```python
{
    "Budget": None,
    "TrafficLevel": "HIGH",
    "PromotionFlag": False,
    "ShelfLifePreference": "LONG",
    "PreferredCategory": None,
    "ExcludedCategory": None,
    "TimeRange": "next_week",
    "ExpectedIntent": "Prepare for high traffic next week while avoiding short shelf-life risk.",
}
```

同时新增采购顾问式字段：

```python
{
    "BusinessIntent": {
        "PrimaryIntent": "stockout_prevention",
        "SecondaryIntents": ["waste_reduction"],
        "DecisionType": "planning",
        "Urgency": "high",
        "IntentSummary": "Prepare for high traffic next week while avoiding short shelf-life risk.",
    },
    "DecisionSignals": {
        "ExpectedDemandChange": "increase",
        "DemandDriver": "traffic",
        "StockoutSensitivity": "high",
        "WasteSensitivity": "high",
        "PriceSensitivity": "medium",
        "GrowthAppetite": "medium",
        "BudgetStrictness": "none",
        "SubstitutionAllowed": True,
    },
    "Uncertainty": {
        "OverallConfidence": 0.82,
        "FieldSources": {
            "budget": "missing",
            "traffic_level": "explicit",
            "promotion_flag": "missing",
            "shelf_life_preference": "explicit",
            "category": "missing",
            "time_horizon": "explicit",
        },
        "LowConfidenceFields": ["promotion_flag"],
    },
    "MissingInformation": [
        {
            "Field": "budget",
            "Importance": "optional",
            "Impact": "Procurement plan will not be budget-constrained.",
            "SuggestedQuestion": "Do you want to set a budget limit for this plan?",
        }
    ],
    "RecommendationReadiness": {
        "CanGenerateRecommendation": True,
        "ShouldAskFollowUp": False,
        "ConfidenceLevel": "high",
        "ConfidenceScore": 0.82,
        "ConfidenceDrivers": [
            "Traffic increase is clear.",
            "Shelf-life preference is clear.",
        ],
        "ConfidenceRisks": [
            "Budget was not provided.",
        ],
        "FollowUpQuestion": "",
    },
}
```

---

## 4. 文件职责

- 新建 `services/procurement_understanding.py`：语义理解结构构建、AI 输出归一化、fallback consultant logic、安全类型转换。
- 修改 `services/intent_parser.py`：更新 prompt；调用 `ProcurementUnderstandingBuilder`；保持 `parse_intent()` 对外接口不变。
- 修改 `services/context_engine.py`：`suggest_session()` 支持复用已解析的 `parsed_intent`，避免重复调用 DeepSeek。
- 修改 `app.py`：提交请求后只解析一次，将同一个 `parsed_intent` 用于 session matching 和 recommendation context。
- 修改 `services/ui.py`：将 `AI Understanding` 改成英文的采购顾问视图。
- 修改 `tests/test_recommendation_engine.py`：增加 fallback、AI normalization、重复调用避免相关测试。
- 修改 `CUSTOMER_DEMO_GUIDE.md`：中文说明新 AI Understanding 行为。
- 修改 `docs/DEMO_LESSONS_AND_RECOMMENDATION_GUIDE.md`：中文说明采购顾问式语义层。

---

## Task 1：新增语义理解 Builder 的测试

**文件：**

- 新建：`services/procurement_understanding.py`
- 修改：`tests/test_recommendation_engine.py`

- [ ] **Step 1：添加 fake AI client 和测试用例**

在 `tests/test_recommendation_engine.py` 中 `OfflineAIClient` 后添加：

```python
class FakeAvailableAIClient:
    is_available = True

    def __init__(self, payload: dict) -> None:
        self.payload = payload
        self.calls = 0

    def chat_completion_json(self, messages):
        self.calls += 1
        return self.payload
```

在 `test_intent_parser_fallback_extracts_nzd_budget` 后添加：

```python
    def test_intent_parser_fallback_returns_procurement_understanding(self) -> None:
        parser = IntentParser(ai_client=OfflineAIClient())
        intent = parser.parse_intent(
            "high traffic next week, avoid short shelf-life products"
        )

        self.assertIsNone(intent["Budget"])
        self.assertEqual(intent["TrafficLevel"], "HIGH")
        self.assertEqual(intent["ShelfLifePreference"], "LONG")
        self.assertEqual(intent["BusinessIntent"]["PrimaryIntent"], "stockout_prevention")
        self.assertEqual(intent["BusinessIntent"]["Urgency"], "high")
        self.assertEqual(intent["DecisionSignals"]["ExpectedDemandChange"], "increase")
        self.assertEqual(intent["DecisionSignals"]["WasteSensitivity"], "high")
        self.assertEqual(intent["DecisionSignals"]["BudgetStrictness"], "none")
        self.assertEqual(intent["Uncertainty"]["FieldSources"]["budget"], "missing")
        self.assertFalse(intent["RecommendationReadiness"]["ShouldAskFollowUp"])
        self.assertTrue(intent["RecommendationReadiness"]["CanGenerateRecommendation"])

    def test_intent_parser_fallback_flags_vague_request_for_follow_up(self) -> None:
        parser = IntentParser(ai_client=OfflineAIClient())
        intent = parser.parse_intent("I need some products for next month")

        self.assertEqual(intent["BusinessIntent"]["PrimaryIntent"], "general_planning")
        self.assertEqual(intent["DecisionSignals"]["ExpectedDemandChange"], "unknown")
        self.assertEqual(intent["RecommendationReadiness"]["ConfidenceLevel"], "low")
        self.assertTrue(intent["RecommendationReadiness"]["ShouldAskFollowUp"])
        self.assertTrue(intent["RecommendationReadiness"]["CanGenerateRecommendation"])
        self.assertEqual(
            intent["RecommendationReadiness"]["FollowUpQuestion"],
            "Are you optimizing for stockout prevention, budget control, or growth?",
        )
        missing_fields = [item["Field"] for item in intent["MissingInformation"]]
        self.assertIn("business_goal", missing_fields)
        self.assertIn("demand_driver", missing_fields)

    def test_intent_parser_normalizes_ai_response_safely(self) -> None:
        ai_client = FakeAvailableAIClient(
            {
                "budget": "500",
                "traffic_level": "HIGH",
                "promotion_flag": "false",
                "shelf_life_preference": "LONG",
                "preferred_category": None,
                "excluded_category": "Fresh",
                "time_range": "next_week",
                "expected_intent": "Prepare for high traffic next week.",
                "business_intent": {
                    "primary_intent": "stockout_prevention",
                    "secondary_intents": ["waste_reduction"],
                    "decision_type": "planning",
                    "urgency": "high",
                    "intent_summary": "Prepare for high traffic next week.",
                },
                "decision_signals": {
                    "expected_demand_change": "increase",
                    "demand_driver": "traffic",
                    "stockout_sensitivity": "high",
                    "waste_sensitivity": "high",
                    "price_sensitivity": "medium",
                    "growth_appetite": "medium",
                    "budget_strictness": "strict",
                    "substitution_allowed": "true",
                },
                "uncertainty": {
                    "overall_confidence": "0.82",
                    "field_sources": {
                        "budget": "explicit",
                        "traffic_level": "explicit",
                        "promotion_flag": "missing",
                        "shelf_life_preference": "explicit",
                        "category": "explicit",
                        "time_horizon": "explicit",
                    },
                    "low_confidence_fields": ["promotion_flag"],
                },
                "missing_information": [],
                "recommendation_readiness": {
                    "can_generate_recommendation": "true",
                    "should_ask_follow_up": "false",
                    "confidence_level": "high",
                    "confidence_score": "0.82",
                    "confidence_drivers": ["Traffic increase is clear."],
                    "confidence_risks": [],
                    "follow_up_question": "",
                },
            }
        )

        intent = IntentParser(ai_client=ai_client).parse_intent(
            "Budget NZD 500, high traffic next week, avoid fresh products"
        )

        self.assertEqual(ai_client.calls, 1)
        self.assertEqual(intent["Budget"], 500.0)
        self.assertFalse(intent["PromotionFlag"])
        self.assertTrue(intent["DecisionSignals"]["SubstitutionAllowed"])
        self.assertEqual(intent["RecommendationReadiness"]["ConfidenceScore"], 0.82)
        self.assertFalse(intent["RecommendationReadiness"]["ShouldAskFollowUp"])
```

- [ ] **Step 2：运行测试，确认失败**

```bash
PYTHONPYCACHEPREFIX=/private/tmp/python-cache .venv/bin/python -m unittest tests/test_recommendation_engine.py
```

预期：

```text
FAILED
KeyError: 'BusinessIntent'
```

---

## Task 2：实现 `ProcurementUnderstandingBuilder`

**文件：**

- 新建：`services/procurement_understanding.py`
- 修改：`services/intent_parser.py`

- [ ] **Step 1：创建 `services/procurement_understanding.py`**

新增文件：

```python
from __future__ import annotations

from typing import Any


FOLLOW_UP_QUESTION = "Are you optimizing for stockout prevention, budget control, or growth?"


class ProcurementUnderstandingBuilder:
    """Builds a procurement-consultant understanding model from AI or fallback intent."""

    def normalize_ai_response(self, raw: dict[str, Any]) -> dict[str, Any]:
        base = self.normalize_base_fields(raw)
        base.update(self.normalize_understanding(raw, base))
        return base

    def build_from_base(self, base: dict[str, Any]) -> dict[str, Any]:
        enriched = dict(base)
        enriched.update(self._build_understanding_from_base(base))
        return enriched

    def normalize_base_fields(self, raw: dict[str, Any]) -> dict[str, Any]:
        return {
            "Budget": self._as_optional_float(raw.get("budget")),
            "TrafficLevel": self._as_choice(raw.get("traffic_level"), {"HIGH", "NORMAL"}, "NORMAL"),
            "PromotionFlag": self._as_bool(raw.get("promotion_flag"), False),
            "ShelfLifePreference": self._as_choice(raw.get("shelf_life_preference"), {"LONG", "NORMAL"}, "NORMAL"),
            "PreferredCategory": self._as_optional_text(raw.get("preferred_category")),
            "ExcludedCategory": self._as_optional_text(raw.get("excluded_category")),
            "TimeRange": self._as_choice(
                raw.get("time_range"),
                {"today", "this_week", "next_week", "holiday_window", "normal", "unknown"},
                "normal",
            ),
            "ExpectedIntent": self._as_optional_text(raw.get("expected_intent")) or "",
        }

    def normalize_understanding(self, raw: dict[str, Any], base: dict[str, Any]) -> dict[str, Any]:
        defaults = self._build_understanding_from_base(base)
        business = raw.get("business_intent") if isinstance(raw.get("business_intent"), dict) else {}
        signals = raw.get("decision_signals") if isinstance(raw.get("decision_signals"), dict) else {}
        uncertainty = raw.get("uncertainty") if isinstance(raw.get("uncertainty"), dict) else {}
        readiness = raw.get("recommendation_readiness") if isinstance(raw.get("recommendation_readiness"), dict) else {}
        missing = raw.get("missing_information")
        if not isinstance(missing, list):
            missing = defaults["MissingInformation"]

        return {
            "BusinessIntent": {
                "PrimaryIntent": self._as_choice(
                    business.get("primary_intent"),
                    {
                        "stockout_prevention",
                        "seasonal_preparation",
                        "promotion_support",
                        "trial_growth",
                        "budget_optimization",
                        "waste_reduction",
                        "supplier_planning",
                        "general_planning",
                    },
                    defaults["BusinessIntent"]["PrimaryIntent"],
                ),
                "SecondaryIntents": self._as_text_list(
                    business.get("secondary_intents"),
                    defaults["BusinessIntent"]["SecondaryIntents"],
                ),
                "DecisionType": self._as_choice(
                    business.get("decision_type"),
                    {"routine_reorder", "urgent_action", "planning", "exploratory", "optimization"},
                    defaults["BusinessIntent"]["DecisionType"],
                ),
                "Urgency": self._as_choice(
                    business.get("urgency"),
                    {"low", "medium", "high", "critical"},
                    defaults["BusinessIntent"]["Urgency"],
                ),
                "IntentSummary": self._as_optional_text(business.get("intent_summary"))
                or base.get("ExpectedIntent")
                or defaults["BusinessIntent"]["IntentSummary"],
            },
            "DecisionSignals": {
                "ExpectedDemandChange": self._as_choice(
                    signals.get("expected_demand_change"),
                    {"increase", "decrease", "stable", "unknown"},
                    defaults["DecisionSignals"]["ExpectedDemandChange"],
                ),
                "DemandDriver": self._as_choice(
                    signals.get("demand_driver"),
                    {"traffic", "holiday", "promotion", "seasonality", "event", "unknown"},
                    defaults["DecisionSignals"]["DemandDriver"],
                ),
                "StockoutSensitivity": self._as_choice(
                    signals.get("stockout_sensitivity"),
                    {"low", "medium", "high"},
                    defaults["DecisionSignals"]["StockoutSensitivity"],
                ),
                "WasteSensitivity": self._as_choice(
                    signals.get("waste_sensitivity"),
                    {"low", "medium", "high"},
                    defaults["DecisionSignals"]["WasteSensitivity"],
                ),
                "PriceSensitivity": self._as_choice(
                    signals.get("price_sensitivity"),
                    {"low", "medium", "high"},
                    defaults["DecisionSignals"]["PriceSensitivity"],
                ),
                "GrowthAppetite": self._as_choice(
                    signals.get("growth_appetite"),
                    {"low", "medium", "high"},
                    defaults["DecisionSignals"]["GrowthAppetite"],
                ),
                "BudgetStrictness": self._as_choice(
                    signals.get("budget_strictness"),
                    {"none", "soft", "strict"},
                    defaults["DecisionSignals"]["BudgetStrictness"],
                ),
                "SubstitutionAllowed": self._as_bool(
                    signals.get("substitution_allowed"),
                    defaults["DecisionSignals"]["SubstitutionAllowed"],
                ),
            },
            "Uncertainty": {
                "OverallConfidence": self._as_float_range(
                    uncertainty.get("overall_confidence"),
                    defaults["Uncertainty"]["OverallConfidence"],
                ),
                "FieldSources": self._normalize_field_sources(
                    uncertainty.get("field_sources"),
                    defaults["Uncertainty"]["FieldSources"],
                ),
                "LowConfidenceFields": self._as_text_list(
                    uncertainty.get("low_confidence_fields"),
                    defaults["Uncertainty"]["LowConfidenceFields"],
                ),
            },
            "MissingInformation": [self._normalize_missing_item(item) for item in missing if isinstance(item, dict)],
            "RecommendationReadiness": {
                "CanGenerateRecommendation": self._as_bool(
                    readiness.get("can_generate_recommendation"),
                    defaults["RecommendationReadiness"]["CanGenerateRecommendation"],
                ),
                "ShouldAskFollowUp": self._as_bool(
                    readiness.get("should_ask_follow_up"),
                    defaults["RecommendationReadiness"]["ShouldAskFollowUp"],
                ),
                "ConfidenceLevel": self._as_choice(
                    readiness.get("confidence_level"),
                    {"low", "medium", "high"},
                    defaults["RecommendationReadiness"]["ConfidenceLevel"],
                ),
                "ConfidenceScore": self._as_float_range(
                    readiness.get("confidence_score"),
                    defaults["RecommendationReadiness"]["ConfidenceScore"],
                ),
                "ConfidenceDrivers": self._as_text_list(
                    readiness.get("confidence_drivers"),
                    defaults["RecommendationReadiness"]["ConfidenceDrivers"],
                ),
                "ConfidenceRisks": self._as_text_list(
                    readiness.get("confidence_risks"),
                    defaults["RecommendationReadiness"]["ConfidenceRisks"],
                ),
                "FollowUpQuestion": self._as_optional_text(readiness.get("follow_up_question"))
                or defaults["RecommendationReadiness"]["FollowUpQuestion"],
            },
        }

    def _build_understanding_from_base(self, base: dict[str, Any]) -> dict[str, Any]:
        traffic_high = str(base.get("TrafficLevel") or "").upper() == "HIGH"
        long_shelf_life = str(base.get("ShelfLifePreference") or "").upper() == "LONG"
        has_budget = base.get("Budget") is not None
        has_category = bool(base.get("PreferredCategory") or base.get("ExcludedCategory"))
        has_promotion = bool(base.get("PromotionFlag"))
        time_range = base.get("TimeRange") or "normal"
        has_time = time_range not in {"normal", "unknown", ""}
        has_business_signal = traffic_high or has_promotion or long_shelf_life or has_category or has_budget

        primary_intent = "general_planning"
        secondary_intents: list[str] = []
        decision_type = "planning"
        urgency = "medium"

        if traffic_high:
            primary_intent = "stockout_prevention"
            urgency = "high"
        if has_promotion:
            primary_intent = "promotion_support"
            secondary_intents.append("seasonal_preparation")
            urgency = "high"
        if long_shelf_life:
            secondary_intents.append("waste_reduction")
        if has_budget and not traffic_high and not has_promotion:
            primary_intent = "budget_optimization"
            decision_type = "optimization"

        expected_demand_change = "increase" if traffic_high or has_promotion else "unknown"
        demand_driver = "traffic" if traffic_high else ("promotion" if has_promotion else "unknown")
        should_ask_follow_up = not has_business_signal

        confidence_score = 0.45
        if traffic_high:
            confidence_score += 0.2
        if long_shelf_life:
            confidence_score += 0.15
        if has_budget:
            confidence_score += 0.1
        if has_time:
            confidence_score += 0.1
        confidence_score = min(confidence_score, 0.9)
        if should_ask_follow_up:
            confidence_score = 0.35

        confidence_level = "high" if confidence_score >= 0.75 else ("medium" if confidence_score >= 0.5 else "low")
        field_sources = {
            "budget": "explicit" if has_budget else "missing",
            "traffic_level": "explicit" if traffic_high else "missing",
            "promotion_flag": "explicit" if has_promotion else "missing",
            "shelf_life_preference": "explicit" if long_shelf_life else "missing",
            "category": "explicit" if has_category else "missing",
            "time_horizon": "explicit" if has_time else "missing",
        }

        missing_information = []
        if not has_budget:
            missing_information.append({
                "Field": "budget",
                "Importance": "optional",
                "Impact": "Procurement plan will not be budget-constrained.",
                "SuggestedQuestion": "Do you want to set a budget limit for this plan?",
            })
        if not has_time:
            missing_information.append({
                "Field": "time_horizon",
                "Importance": "recommended",
                "Impact": "The recommendation can run, but lead-time and demand timing are less precise.",
                "SuggestedQuestion": "When do you need the products delivered?",
            })
        if should_ask_follow_up:
            missing_information.extend([
                {
                    "Field": "business_goal",
                    "Importance": "high_risk",
                    "Impact": "The system cannot tell whether to optimize for stockout risk, budget control, or growth.",
                    "SuggestedQuestion": FOLLOW_UP_QUESTION,
                },
                {
                    "Field": "demand_driver",
                    "Importance": "high_risk",
                    "Impact": "Demand assumptions are unclear.",
                    "SuggestedQuestion": "Is this request driven by traffic, promotion, seasonality, or routine replenishment?",
                },
            ])

        confidence_drivers = []
        if traffic_high:
            confidence_drivers.append("Traffic increase is clear.")
        if long_shelf_life:
            confidence_drivers.append("Shelf-life preference is clear.")
        if has_budget:
            confidence_drivers.append("Budget constraint is explicit.")
        if not confidence_drivers:
            confidence_drivers.append("The request can be processed using available customer and inventory data.")

        confidence_risks = []
        if not has_budget:
            confidence_risks.append("Budget was not provided.")
        if not has_time:
            confidence_risks.append("Time horizon was not provided.")
        if should_ask_follow_up:
            confidence_risks.append("Business goal and demand driver are unclear.")

        return {
            "BusinessIntent": {
                "PrimaryIntent": primary_intent,
                "SecondaryIntents": secondary_intents,
                "DecisionType": decision_type,
                "Urgency": urgency,
                "IntentSummary": base.get("ExpectedIntent") or "General procurement planning request.",
            },
            "DecisionSignals": {
                "ExpectedDemandChange": expected_demand_change,
                "DemandDriver": demand_driver,
                "StockoutSensitivity": "high" if traffic_high else "medium",
                "WasteSensitivity": "high" if long_shelf_life else "medium",
                "PriceSensitivity": "medium",
                "GrowthAppetite": "medium",
                "BudgetStrictness": "strict" if has_budget else "none",
                "SubstitutionAllowed": True,
            },
            "Uncertainty": {
                "OverallConfidence": confidence_score,
                "FieldSources": field_sources,
                "LowConfidenceFields": [
                    field for field, source in field_sources.items()
                    if source == "missing" and field != "budget"
                ],
            },
            "MissingInformation": missing_information,
            "RecommendationReadiness": {
                "CanGenerateRecommendation": True,
                "ShouldAskFollowUp": should_ask_follow_up,
                "ConfidenceLevel": confidence_level,
                "ConfidenceScore": confidence_score,
                "ConfidenceDrivers": confidence_drivers,
                "ConfidenceRisks": confidence_risks,
                "FollowUpQuestion": FOLLOW_UP_QUESTION if should_ask_follow_up else "",
            },
        }

    def _normalize_missing_item(self, item: dict[str, Any]) -> dict[str, str]:
        return {
            "Field": self._as_optional_text(item.get("field") or item.get("Field")) or "",
            "Importance": self._as_choice(
                item.get("importance") or item.get("Importance"),
                {"optional", "recommended", "high_risk"},
                "optional",
            ),
            "Impact": self._as_optional_text(item.get("impact") or item.get("Impact")) or "",
            "SuggestedQuestion": self._as_optional_text(
                item.get("suggested_question") or item.get("SuggestedQuestion")
            ) or "",
        }

    def _normalize_field_sources(self, raw: Any, default: dict[str, str]) -> dict[str, str]:
        if not isinstance(raw, dict):
            return default
        result = dict(default)
        for key in ["budget", "traffic_level", "promotion_flag", "shelf_life_preference", "category", "time_horizon"]:
            result[key] = self._as_choice(raw.get(key), {"explicit", "inferred", "missing"}, default.get(key, "missing"))
        return result

    @staticmethod
    def _as_optional_text(value: Any) -> str | None:
        if value is None:
            return None
        text = str(value).strip()
        return text if text else None

    @classmethod
    def _as_choice(cls, value: Any, allowed: set[str], default: str) -> str:
        text = cls._as_optional_text(value)
        if text is None:
            return default
        normalized = text.lower()
        if normalized.upper() in allowed:
            return normalized.upper()
        return normalized if normalized in allowed else default

    @classmethod
    def _as_optional_float(cls, value: Any) -> float | None:
        if value is None or value == "":
            return None
        try:
            return float(value)
        except (TypeError, ValueError):
            return None

    @classmethod
    def _as_float_range(cls, value: Any, default: float) -> float:
        parsed = cls._as_optional_float(value)
        if parsed is None:
            return default
        return min(max(parsed, 0.0), 1.0)

    @classmethod
    def _as_bool(cls, value: Any, default: bool) -> bool:
        if isinstance(value, bool):
            return value
        text = cls._as_optional_text(value)
        if text is None:
            return default
        return text.lower() in {"true", "1", "yes", "y"}

    @classmethod
    def _as_text_list(cls, value: Any, default: list[str]) -> list[str]:
        if not isinstance(value, list):
            return list(default)
        return [str(item).strip() for item in value if str(item).strip()]
```

- [ ] **Step 2：更新 `services/intent_parser.py` 导入**

在导入区增加：

```python
from services.procurement_understanding import ProcurementUnderstandingBuilder
```

- [ ] **Step 3：更新 `IntentParser.__init__()`**

替换：

```python
    def __init__(self, ai_client: AIClient | None = None) -> None:
        self.ai_client = ai_client or AIClient()
```

为：

```python
    def __init__(
        self,
        ai_client: AIClient | None = None,
        understanding_builder: ProcurementUnderstandingBuilder | None = None,
    ) -> None:
        self.ai_client = ai_client or AIClient()
        self.understanding_builder = understanding_builder or ProcurementUnderstandingBuilder()
```

- [ ] **Step 4：更新 `_normalize_intent()`**

替换当前 `_normalize_intent()`：

```python
    def _normalize_intent(self, raw: dict[str, Any]) -> dict[str, Any]:
        return self.understanding_builder.normalize_ai_response(raw)
```

- [ ] **Step 5：更新 `_fallback_parse()` 返回逻辑**

将 `_fallback_parse()` 末尾：

```python
        intent["ExpectedIntent"] = user_input[:100]
        return intent
```

替换为：

```python
        intent["ExpectedIntent"] = user_input[:100]
        return self.understanding_builder.build_from_base(intent)
```

- [ ] **Step 6：更新 DeepSeek prompt**

将 `INTENT_SYSTEM_PROMPT` 替换为英文 prompt。prompt 必须要求输出字段：

```text
budget
traffic_level
promotion_flag
shelf_life_preference
preferred_category
excluded_category
time_range
expected_intent
business_intent
decision_signals
uncertainty
missing_information
recommendation_readiness
```

并明确规则：

```text
Missing budget is optional and must not block recommendations.
High-risk missing information should set should_ask_follow_up=true but can_generate_recommendation must remain true.
If the request is vague and lacks business goal, demand driver, category and budget, use this exact follow-up question:
Are you optimizing for stockout prevention, budget control, or growth?
```

- [ ] **Step 7：运行测试**

```bash
PYTHONPYCACHEPREFIX=/private/tmp/python-cache .venv/bin/python -m unittest tests/test_recommendation_engine.py
```

预期：

```text
OK
```

---

## Task 3：避免重复调用 DeepSeek

**文件：**

- 修改：`services/context_engine.py`
- 修改：`app.py`
- 修改：`tests/test_recommendation_engine.py`

- [ ] **Step 1：添加 counting parser**

在 `tests/test_recommendation_engine.py` 中添加：

```python
class CountingIntentParser:
    def __init__(self) -> None:
        self.calls = 0

    def parse_intent(self, user_input: str) -> dict:
        self.calls += 1
        return {
            "Budget": None,
            "TrafficLevel": "HIGH",
            "PromotionFlag": False,
            "ShelfLifePreference": "LONG",
            "PreferredCategory": None,
            "ExcludedCategory": None,
            "TimeRange": "next_week",
            "ExpectedIntent": user_input,
        }
```

- [ ] **Step 2：添加复用 parsed intent 的测试**

```python
    def test_context_engine_reuses_parsed_intent_for_session_matching(self) -> None:
        parser = CountingIntentParser()
        engine = ContextEngine(intent_parser=parser)
        parsed_intent = parser.parse_intent(
            "high traffic next week, avoid short shelf-life products"
        )

        session_id = engine.suggest_session(
            self.workbook,
            "high traffic next week, avoid short shelf-life products",
            parsed_intent=parsed_intent,
        )

        self.assertEqual(session_id, "S1")
        self.assertEqual(parser.calls, 1)
```

- [ ] **Step 3：运行测试，确认失败**

```bash
PYTHONPYCACHEPREFIX=/private/tmp/python-cache .venv/bin/python -m unittest tests.test_recommendation_engine.RecommendationEngineTests.test_context_engine_reuses_parsed_intent_for_session_matching
```

预期：

```text
TypeError: ContextEngine.suggest_session() got an unexpected keyword argument 'parsed_intent'
```

- [ ] **Step 4：修改 `ContextEngine.suggest_session()`**

将签名改为：

```python
    def suggest_session(
        self,
        workbook: dict[str, pd.DataFrame],
        user_input: str,
        parsed_intent: dict[str, Any] | None = None,
    ) -> str:
```

将内部解析逻辑改为：

```python
        if parsed_intent is None:
            parsed_intent = self.intent_parser.parse_intent(user_input)
        logger.info("Parsed intent for session matching: %s", parsed_intent)
```

- [ ] **Step 5：修改 `app.py`**

将：

```python
            st.session_state["session_id"] = context_engine.suggest_session(workbook, request)
```

替换为：

```python
            st.session_state["session_id"] = context_engine.suggest_session(
                workbook,
                request,
                parsed_intent=parsed_intent,
            )
```

- [ ] **Step 6：运行测试**

```bash
PYTHONPYCACHEPREFIX=/private/tmp/python-cache .venv/bin/python -m unittest tests/test_recommendation_engine.py
```

预期：

```text
OK
```

---

## Task 4：重构 `AI Understanding` UI

**文件：**

- 修改：`services/ui.py`

**展示语言要求：**

- UI 面向英文 demo，标题和字段展示保持英文。
- 内部代码注释和文档说明可以中文，但建议代码注释尽量少。

- [ ] **Step 1：添加 UI helper**

在 `render_ai_understanding()` 前添加：

```python
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
```

- [ ] **Step 2：替换 `render_ai_understanding()`**

新的 UI 必须展示四块英文内容：

```text
Business Intent
Decision Signals
Risk Sensitivity
Recommendation Confidence
```

下方展示：

```text
Missing Information
Suggested follow-up
```

实现时读取这些 normalized keys：

```python
business_intent = context.get("BusinessIntent") or {}
decision_signals = context.get("DecisionSignals") or {}
uncertainty = context.get("Uncertainty") or {}
missing_information = context.get("MissingInformation") or []
readiness = context.get("RecommendationReadiness") or {}
```

UI 验收输入：

```text
high traffic next week, avoid short shelf-life products
```

预期英文展示：

```text
Business Intent: Stockout Prevention
Decision Signals: Increase Demand
Risk Sensitivity: Stockout High / Waste High
Recommendation Confidence: High or Medium
Missing Information: Budget optional
```

UI 验收输入：

```text
I need some products for next month
```

预期英文展示：

```text
Business Intent: General Planning
Recommendation Confidence: Low
Suggested follow-up: Are you optimizing for stockout prevention, budget control, or growth?
```

- [ ] **Step 3：添加 CSS**

在 `inject_theme()` 中新增样式，类名建议：

```css
.understanding-card
.understanding-grid
.understanding-panel
.understanding-panel-title
.understanding-primary
.understanding-secondary
.understanding-missing
.understanding-mini-row
.understanding-mini-label
.understanding-mini-value
.understanding-follow-up
```

移动端断点：

```css
@media (max-width: 900px) {
    .understanding-grid {
        grid-template-columns: repeat(2, minmax(0, 1fr));
    }
}

@media (max-width: 640px) {
    .understanding-grid {
        grid-template-columns: 1fr;
    }
}
```

- [ ] **Step 4：运行语法检查**

```bash
PYTHONPYCACHEPREFIX=/private/tmp/python-cache .venv/bin/python -m py_compile services/ui.py
```

预期：无输出，退出码为 0。

---

## Task 5：更新中文开发和演示文档

**文件：**

- 修改：`CUSTOMER_DEMO_GUIDE.md`
- 修改：`docs/DEMO_LESSONS_AND_RECOMMENDATION_GUIDE.md`

- [ ] **Step 1：更新 `CUSTOMER_DEMO_GUIDE.md`**

替换 `### AI Understanding` 小节为中文说明：

```markdown
### AI Understanding

系统会把用户输入解析成采购顾问视角的结构化理解，而不是只抽取字段。

该区域在 UI 中使用英文展示，包含：

- Business Intent：用户真正的采购目的，例如补货、防缺货、节日备货、预算优化或增长试采。
- Decision Signals：需求变化、需求驱动因素、预算模式和关键风险偏好。
- Risk Sensitivity：系统判断用户更关注缺货、损耗、价格还是增长机会。
- Missing Information：缺失但会影响推荐质量的信息。
- Recommendation Confidence：当前输入是否足够支持高质量推荐。

当前采用混合模式：

- 普通缺失信息不会阻塞推荐，例如用户未输入预算时，系统仍会生成无预算约束的采购建议。
- 高风险缺失信息会显示一个建议追问并降低推荐可信度，但不会阻塞当前推荐。

该区域用于向客户说明：AI 不只是生成文字回复，而是在像采购顾问一样判断业务意图、决策信号和推荐可信度。
```

- [ ] **Step 2：更新 `docs/DEMO_LESSONS_AND_RECOMMENDATION_GUIDE.md`**

在 `## 4. AI 作用边界` 下补充：

```markdown
### 4.1.1 采购顾问式语义理解

DeepSeek 的目标不是只抽取字段，而是形成采购顾问式理解。

新的语义理解包含：

- Business Intent：采购目的和紧急程度。
- Decision Signals：需求变化、需求驱动、预算严格度、缺货敏感度、损耗敏感度。
- Uncertainty：哪些字段是用户明确输入，哪些是推断，哪些缺失。
- Missing Information：缺失信息的重要性和对推荐的影响。
- Recommendation Readiness：是否可以生成推荐、是否应该追问、当前推荐可信度。

系统采用混合追问模式：

- 高风险缺失信息显示追问并降低可信度，但不阻塞当前推荐。
- 普通缺失信息只提示，不阻塞推荐。
- 可选缺失信息只作为上下文说明。

UI 面向英文 demo 展示，因此模块名称保留英文；内部开发文档统一使用中文说明。
```

- [ ] **Step 3：验证文档**

```bash
rg -n "采购顾问|混合模式|高风险缺失|UI 面向英文" CUSTOMER_DEMO_GUIDE.md docs/DEMO_LESSONS_AND_RECOMMENDATION_GUIDE.md
```

预期：两个文档都能搜索到相关内容。

---

## Task 6：最终验证

**文件：**

- 验证所有修改文件。

- [ ] **Step 1：运行全部单元测试**

```bash
PYTHONPYCACHEPREFIX=/private/tmp/python-cache .venv/bin/python -m unittest tests/test_recommendation_engine.py
```

预期：

```text
OK
```

- [ ] **Step 2：运行语法检查**

```bash
PYTHONPYCACHEPREFIX=/private/tmp/python-cache .venv/bin/python -m py_compile app.py services/intent_parser.py services/context_engine.py services/procurement_understanding.py services/ui.py
```

预期：无输出，退出码为 0。

- [ ] **Step 3：验证没有重复调用 DeepSeek 的路径**

```bash
rg -n "parse_intent\\(|suggest_session\\(" app.py services/context_engine.py
```

预期关键结果：

```text
app.py: parsed_intent = intent_parser.parse_intent(request)
app.py: context_engine.suggest_session(..., parsed_intent=parsed_intent)
services/context_engine.py: if parsed_intent is None:
services/context_engine.py: parsed_intent = self.intent_parser.parse_intent(user_input)
```

- [ ] **Step 4：手动验证 Streamlit**

启动：

```bash
.venv/bin/streamlit run app.py --server.port 8501
```

访问：

```text
http://localhost:8501
```

输入：

```text
high traffic next week, avoid short shelf-life products
```

预期：

```text
Dashboard 正常渲染。
AI Understanding 显示英文采购顾问式理解。
Procurement Plan 正常显示推荐。
预算不会默认显示为 NZD 1000。
```

输入：

```text
I need some products for next month
```

预期：

```text
Dashboard 仍然生成推荐。
AI Understanding 显示 Low confidence。
AI Understanding 显示 Suggested follow-up。
推荐流程不被阻塞。
```

---

## 自检结果

### 覆盖范围

- 业务意图：Task 1、Task 2、Task 4。
- 决策信号：Task 1、Task 2、Task 4。
- 不确定性处理：Task 1、Task 2、Task 4。
- 缺失信息检测：Task 1、Task 2、Task 4。
- 推荐可信度：Task 1、Task 2、Task 4。
- C 模式：Task 1、Task 2、Task 4、Task 6。
- 避免重复 DeepSeek 调用：Task 3。
- 中文内部文档：Task 5。

### 语言规范

- 内部计划文档和开发说明使用中文。
- UI 展示文案保留英文。
- 代码字段名、函数名、命令、JSON key 保留英文。

### 主要风险

- DeepSeek 仍可能返回不完整或类型不稳定的 JSON，因此 `ProcurementUnderstandingBuilder` 必须做安全归一化。
- 语义字段暂时主要用于 UI 和解释，不应在本轮直接改变推荐排序。
- 如果未来要让 `DecisionSignals` 影响推荐权重，需要单独设计和测试。
