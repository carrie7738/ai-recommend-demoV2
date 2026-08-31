from __future__ import annotations

from typing import Any


FOLLOW_UP_QUESTION = "Are you optimizing for stockout prevention, budget control, or growth?"


class ProcurementUnderstandingBuilder:
    """Builds a procurement-consultant understanding model from AI or fallback intent."""

    def normalize_ai_response(self, raw: dict[str, Any]) -> dict[str, Any]:
        base = self.normalize_base_fields(raw)
        base.update(self.normalize_understanding(raw, base))
        base["StructuredIntent"] = self.normalize_structured_intent(raw, base)
        return base

    def build_from_base(self, base: dict[str, Any]) -> dict[str, Any]:
        enriched = dict(base)
        enriched.update(self._build_understanding_from_base(base))
        enriched["StructuredIntent"] = self.normalize_structured_intent(base, enriched)
        return enriched

    def normalize_structured_intent(
        self,
        raw: dict[str, Any],
        normalized: dict[str, Any],
    ) -> dict[str, Any]:
        """Build the V2 intent contract while retaining all V1 top-level fields."""
        supplied = raw.get("structured_intent")
        if not isinstance(supplied, dict):
            supplied = raw.get("StructuredIntent")
        if not isinstance(supplied, dict):
            supplied = {}

        business_intent = normalized.get("BusinessIntent") or {}
        preferred_category = normalized.get("PreferredCategory")
        excluded_category = normalized.get("ExcludedCategory")
        shelf_preference = normalized.get("ShelfLifePreference")

        hard_constraints = self._normalize_constraints(
            supplied.get("hard_constraints", raw.get("hard_constraints", raw.get("HardConstraints")))
        )
        soft_preferences = self._normalize_preferences(
            supplied.get("soft_preferences", raw.get("soft_preferences", raw.get("SoftPreferences")))
        )

        if excluded_category and not self._contains_constraint(hard_constraints, "CATEGORY", excluded_category):
            hard_constraints.append({
                "type": "CATEGORY",
                "operator": "EXCLUDE",
                "values": [excluded_category],
            })
        if preferred_category and not self._contains_preference(soft_preferences, "CATEGORY", preferred_category):
            soft_preferences.append({"type": "CATEGORY", "value": preferred_category})
        if shelf_preference == "LONG" and not self._contains_preference(soft_preferences, "SHELF_LIFE", "LONG"):
            soft_preferences.append({"type": "SHELF_LIFE", "value": "LONG"})

        category_preferences = self._as_text_list(
            supplied.get("category_preference", raw.get("category_preference")),
            [],
        )
        if preferred_category and preferred_category not in category_preferences:
            category_preferences.append(preferred_category)

        return {
            "store_id": self._as_optional_text(
                supplied.get("store_id", raw.get("store_id", raw.get("StoreId")))
            ) or "",
            "budget": normalized.get("Budget"),
            "objective": self._normalize_objective(
                supplied.get("objective", raw.get("objective", raw.get("Objective"))),
                business_intent,
            ),
            "traffic_expectation": self._as_choice(
                supplied.get("traffic_expectation", raw.get("traffic_expectation", normalized.get("TrafficLevel"))),
                {"HIGH", "NORMAL", "LOW"},
                "NORMAL",
            ),
            "occasion": self._normalize_occasion(
                supplied.get("occasion", raw.get("occasion", raw.get("Occasion"))),
                normalized,
            ),
            "category_preference": category_preferences,
            "hard_constraints": hard_constraints,
            "soft_preferences": soft_preferences,
            "explicit_products": self._normalize_explicit_products(
                supplied.get("explicit_products", raw.get("explicit_products", raw.get("ExplicitProducts")))
            ),
        }

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

    @classmethod
    def _normalize_constraints(cls, value: Any) -> list[dict[str, Any]]:
        if not isinstance(value, list):
            return []
        normalized: list[dict[str, Any]] = []
        for item in value:
            if not isinstance(item, dict):
                continue
            constraint_type = str(item.get("type") or "").strip().upper()
            if constraint_type not in {"CATEGORY", "SHELF_LIFE"}:
                continue
            operator = str(item.get("operator") or "").strip().upper()
            if constraint_type == "CATEGORY" and operator not in {"INCLUDE_ONLY", "EXCLUDE"}:
                continue
            if constraint_type == "SHELF_LIFE" and operator != "REQUIRE_LEVEL":
                continue
            entry: dict[str, Any] = {"type": constraint_type, "operator": operator}
            if constraint_type == "CATEGORY":
                raw_values = item.get("values")
                if not isinstance(raw_values, list):
                    raw_values = [item.get("value")] if item.get("value") is not None else []
                entry["values"] = [str(raw).strip() for raw in raw_values if str(raw).strip()]
                if not entry["values"]:
                    continue
            else:
                level = str(item.get("value") or "").strip().upper()
                if level not in {"LONG", "MEDIUM", "SHORT"}:
                    continue
                entry["value"] = level
            normalized.append(entry)
        return normalized

    @classmethod
    def _normalize_preferences(cls, value: Any) -> list[dict[str, str]]:
        if not isinstance(value, list):
            return []
        normalized: list[dict[str, str]] = []
        for item in value:
            if not isinstance(item, dict):
                continue
            preference_type = str(item.get("type") or "").strip().upper()
            preference_value = str(item.get("value") or "").strip()
            if preference_type not in {"CATEGORY", "SHELF_LIFE"} or not preference_value:
                continue
            if preference_type == "SHELF_LIFE":
                preference_value = preference_value.upper()
                if preference_value not in {"LONG", "MEDIUM", "SHORT"}:
                    continue
            normalized.append({"type": preference_type, "value": preference_value})
        return normalized

    @classmethod
    def _normalize_explicit_products(cls, value: Any) -> list[dict[str, str]]:
        if not isinstance(value, list):
            return []
        normalized: list[dict[str, str]] = []
        seen: set[tuple[str, str]] = set()
        for item in value:
            if isinstance(item, str):
                item = {"sku": item}
            if not isinstance(item, dict):
                continue
            sku = str(item.get("sku") or item.get("product_id") or "").strip().upper()
            product_name = str(item.get("product_name") or item.get("name") or "").strip()
            if not sku and not product_name:
                continue
            quantity_intent = str(item.get("quantity_intent") or "NORMAL").strip().upper()
            if quantity_intent not in {"LOW", "NORMAL", "HIGH"}:
                quantity_intent = "NORMAL"
            key = (sku, product_name.casefold())
            if key in seen:
                continue
            seen.add(key)
            normalized.append({
                "sku": sku,
                "product_name": product_name,
                "quantity_intent": quantity_intent,
            })
        return normalized

    @staticmethod
    def _contains_constraint(constraints: list[dict[str, Any]], kind: str, value: str) -> bool:
        wanted = value.casefold()
        return any(
            item.get("type") == kind
            and (
                str(item.get("value") or "").casefold() == wanted
                or wanted in {str(raw).casefold() for raw in item.get("values", [])}
            )
            for item in constraints
        )

    @staticmethod
    def _contains_preference(preferences: list[dict[str, str]], kind: str, value: str) -> bool:
        wanted = value.casefold()
        return any(
            item.get("type") == kind and str(item.get("value") or "").casefold() == wanted
            for item in preferences
        )

    @staticmethod
    def _normalize_occasion(value: Any, normalized: dict[str, Any]) -> str:
        text = str(value or "").strip().upper()
        expected = str(normalized.get("ExpectedIntent") or "").casefold()
        if "CHRISTMAS" in text or "christmas" in expected:
            return "CHRISTMAS"
        if "HOLIDAY" in text or (
            not text
            and (
                normalized.get("TimeRange") == "holiday_window"
                or normalized.get("PromotionFlag")
            )
        ):
            return "HOLIDAY"
        return "NONE"

    @classmethod
    def _normalize_objective(
        cls,
        value: Any,
        business_intent: dict[str, Any],
    ) -> str:
        text = str(value or "").strip().upper().replace("-", "_").replace(" ", "_")
        aliases = {
            "PREVENT_STOCKOUT": "PREVENT_STOCKOUT",
            "PREVENT_STOCKOUTS": "PREVENT_STOCKOUT",
            "STOCKOUT_PREVENTION": "PREVENT_STOCKOUT",
            "SEASONAL_PREPARATION": "SEASONAL_PREPARATION",
            "PROMOTION_SUPPORT": "SEASONAL_PREPARATION",
            "DISCOVER_NEW_OPPORTUNITY": "DISCOVER_NEW_OPPORTUNITY",
            "TRIAL_GROWTH": "DISCOVER_NEW_OPPORTUNITY",
            "BUDGET_OPTIMIZATION": "BUDGET_OPTIMIZATION",
            "REDUCE_WASTE": "REDUCE_WASTE",
            "WASTE_REDUCTION": "REDUCE_WASTE",
            "SUPPLIER_PLANNING": "SUPPLIER_PLANNING",
            "GENERAL_PLANNING": "GENERAL_PLANNING",
        }
        if text in aliases:
            return aliases[text]
        if "STOCKOUT" in text:
            return "PREVENT_STOCKOUT"
        if "CHRISTMAS" in text or "SEASON" in text or "PROMOTION" in text:
            return "SEASONAL_PREPARATION"
        return cls._objective_from_business_intent(business_intent)

    @staticmethod
    def _objective_from_business_intent(business_intent: dict[str, Any]) -> str:
        primary = str(business_intent.get("PrimaryIntent") or "general_planning").casefold()
        return {
            "stockout_prevention": "PREVENT_STOCKOUT",
            "seasonal_preparation": "SEASONAL_PREPARATION",
            "promotion_support": "SEASONAL_PREPARATION",
            "trial_growth": "DISCOVER_NEW_OPPORTUNITY",
            "budget_optimization": "BUDGET_OPTIMIZATION",
            "waste_reduction": "REDUCE_WASTE",
            "supplier_planning": "SUPPLIER_PLANNING",
            "general_planning": "GENERAL_PLANNING",
        }.get(primary, "GENERAL_PLANNING")

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
