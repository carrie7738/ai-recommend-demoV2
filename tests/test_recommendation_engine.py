import unittest

import pandas as pd

from engines.growth_engine import GrowthEngine
from engines.recommendation_engine import InsufficientDataError, RecommendationEngine
from engines.replenishment_engine import ReplenishmentEngine
from engines.risk_engine import RiskEngine
from services.context_engine import ContextEngine
from services.intent_parser import IntentParser


class OfflineAIClient:
    is_available = False


class FakeAvailableAIClient:
    is_available = True

    def __init__(self, payload: dict) -> None:
        self.payload = payload
        self.calls = 0

    def chat_completion_json(self, messages):
        self.calls += 1
        return self.payload


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


class RecommendationEngineTests(unittest.TestCase):
    def setUp(self) -> None:
        order_dates = pd.to_datetime(
            [
                "2026-03-10",
                "2026-03-17",
                "2026-03-24",
                "2026-04-01",
                "2026-04-08",
                "2026-04-15",
                "2026-04-22",
                "2026-04-29",
                "2026-05-06",
                "2026-05-13",
                "2026-05-20",
                "2026-05-27",
                "2026-05-30",
                "2026-05-10",
                "2026-04-10",
            ]
        )
        self.workbook = {
            "Customer": pd.DataFrame(
                [
                    {
                        "CustomerId": "C1",
                        "StoreName": "Test Cafe",
                        "Industry": "Cafe",
                        "Region": "NZ",
                    }
                ]
            ),
            "Product": pd.DataFrame(
                [
                    {
                        "ProductId": "P1",
                        "ProductName": "Banana",
                        "Category": "Fruit",
                        "ProductType": "Fresh",
                        "ShelfLifeDays": 7,
                        "Unit": "KG",
                        "AvgCost": 5.0,
                        "ProfitMargin": 0.20,
                    },
                    {
                        "ProductId": "P2",
                        "ProductName": "Lemon Variant",
                        "Category": "Fruit",
                        "ProductType": "Fresh",
                        "ShelfLifeDays": 12,
                        "Unit": "KG",
                        "AvgCost": 6.0,
                        "ProfitMargin": 0.30,
                    },
                    {
                        "ProductId": "P3",
                        "ProductName": "Frozen Fries",
                        "Category": "Frozen",
                        "ProductType": "Frozen",
                        "ShelfLifeDays": 180,
                        "Unit": "KG",
                        "AvgCost": 4.0,
                        "ProfitMargin": 0.15,
                    },
                ]
            ),
            "OrderHistory": pd.DataFrame(
                [
                    {
                        "OrderId": f"O{i:03d}",
                        "CustomerId": "C1",
                        "ProductId": "P1",
                        "OrderDate": order_dates[i - 1],
                        "Quantity": 10 + (i % 3),
                        "UnitPrice": 5.5,
                    }
                    for i in range(1, 13)
                ]
                + [
                    {
                        "OrderId": "O013",
                        "CustomerId": "C1",
                        "ProductId": "P3",
                        "OrderDate": order_dates[12],
                        "Quantity": 4,
                        "UnitPrice": 4.5,
                    },
                    {
                        "OrderId": "O014",
                        "CustomerId": "C1",
                        "ProductId": "P3",
                        "OrderDate": order_dates[13],
                        "Quantity": 5,
                        "UnitPrice": 4.5,
                    },
                    {
                        "OrderId": "O015",
                        "CustomerId": "C1",
                        "ProductId": "P3",
                        "OrderDate": order_dates[14],
                        "Quantity": 6,
                        "UnitPrice": 4.5,
                    },
                ]
            ),
            "Inventory": pd.DataFrame(
                [
                    {
                        "CustomerId": "C1",
                        "ProductId": "P1",
                        "CurrentStock": 2,
                        "LastUpdated": pd.Timestamp("2026-06-01"),
                        "BatchExpiryDate": pd.Timestamp("2026-06-05"),
                        "InventoryScenario": "LowStock",
                    },
                    {
                        "CustomerId": "C1",
                        "ProductId": "P3",
                        "CurrentStock": 80,
                        "LastUpdated": pd.Timestamp("2026-06-01"),
                        "BatchExpiryDate": pd.NaT,
                        "InventoryScenario": "Overstock",
                    },
                ]
            ),
            "Favorites": pd.DataFrame(
                [{"CustomerId": "C1", "ProductId": "P1", "FavoriteDate": "2026-01-01"}]
            ),
            "IndustryTrend": pd.DataFrame(
                [
                    {
                        "Industry": "Cafe",
                        "ProductId": "P2",
                        "CoverageRate": 91,
                        "PopularityScore": 88,
                        "TrendDirection": "Up",
                    },
                    {
                        "Industry": "Cafe",
                        "ProductId": "P3",
                        "CoverageRate": 75,
                        "PopularityScore": 60,
                        "TrendDirection": "Stable",
                    },
                ]
            ),
            "HolidayConfig": pd.DataFrame(
                [
                    {
                        "HolidayName": "Christmas",
                        "HolidayDate": "2026-12-25",
                        "AdvanceDays": 14,
                        "Region": "NZ",
                    }
                ]
            ),
            "HolidayProduct": pd.DataFrame(
                [
                    {
                        "HolidayName": "Christmas",
                        "ProductId": "P2",
                        "Weight": 90,
                        "Reason": "Seasonal demand",
                    }
                ]
            ),
            "ConversationContext": pd.DataFrame(
                [
                    {
                        "SessionId": "S1",
                        "CustomerId": "C1",
                        "Budget": 50.0,
                        "TimeRange": "holiday_window",
                        "TrafficLevel": "HIGH",
                        "PromotionFlag": True,
                        "PreferredCategory": "Fruit",
                        "ExcludedCategory": None,
                        "ShelfLifePreference": "LONG",
                    }
                ]
            ),
        }

    def _add_price_history(self) -> None:
        self.workbook["PriceHistory"] = pd.DataFrame(
            [
                {
                    "ProductId": "P1",
                    "PriceDate": pd.Timestamp("2026-03-15"),
                    "StoreName": "Demo Store",
                    "UnitPrice": 8.0,
                    "PromoFlag": False,
                    "Source": "test",
                },
                {
                    "ProductId": "P1",
                    "PriceDate": pd.Timestamp("2026-04-15"),
                    "StoreName": "Demo Store",
                    "UnitPrice": 6.5,
                    "PromoFlag": False,
                    "Source": "test",
                },
                {
                    "ProductId": "P1",
                    "PriceDate": pd.Timestamp("2026-06-01"),
                    "StoreName": "Demo Store",
                    "UnitPrice": 5.0,
                    "PromoFlag": True,
                    "Source": "test",
                },
                {
                    "ProductId": "P2",
                    "PriceDate": pd.Timestamp("2026-03-15"),
                    "StoreName": "Demo Store",
                    "UnitPrice": 7.0,
                    "PromoFlag": False,
                    "Source": "test",
                },
                {
                    "ProductId": "P2",
                    "PriceDate": pd.Timestamp("2026-04-15"),
                    "StoreName": "Demo Store",
                    "UnitPrice": 6.5,
                    "PromoFlag": False,
                    "Source": "test",
                },
                {
                    "ProductId": "P2",
                    "PriceDate": pd.Timestamp("2026-06-01"),
                    "StoreName": "Demo Store",
                    "UnitPrice": 5.5,
                    "PromoFlag": True,
                    "Source": "test",
                },
            ]
        )

    def _add_frozen_buy_now_price_history(self) -> None:
        self.workbook["Inventory"].loc[
            self.workbook["Inventory"]["ProductId"] == "P3",
            "CurrentStock",
        ] = 1
        self.workbook["PriceHistory"] = pd.DataFrame(
            [
                {
                    "ProductId": "P3",
                    "PriceDate": pd.Timestamp("2026-03-15"),
                    "StoreName": "Demo Store",
                    "UnitPrice": 7.0,
                    "PromoFlag": False,
                    "Source": "test",
                },
                {
                    "ProductId": "P3",
                    "PriceDate": pd.Timestamp("2026-04-15"),
                    "StoreName": "Demo Store",
                    "UnitPrice": 5.0,
                    "PromoFlag": False,
                    "Source": "test",
                },
                {
                    "ProductId": "P3",
                    "PriceDate": pd.Timestamp("2026-06-01"),
                    "StoreName": "Demo Store",
                    "UnitPrice": 3.0,
                    "PromoFlag": True,
                    "Source": "test",
                },
            ]
        )

    def test_replenishment_recommends_high_priority_low_stock_product(self) -> None:
        context = ContextEngine().build_context(self.workbook, "S1")
        recommendations = ReplenishmentEngine().generate_recommendations(
            self.workbook,
            customer_id="C1",
            context=context,
        )

        self.assertEqual(recommendations[0]["product_id"], "P1")
        self.assertGreaterEqual(recommendations[0]["score"], 75)
        self.assertGreater(recommendations[0]["quantity"], 0)
        self.assertTrue(
            any("Inventory covers" in reason for reason in recommendations[0]["why"])
        )

    def test_growth_recommends_unpurchased_industry_products(self) -> None:
        context = ContextEngine().build_context(self.workbook, "S1")
        opportunities = GrowthEngine().generate_opportunities(
            self.workbook,
            customer_id="C1",
            context=context,
        )

        self.assertEqual(opportunities[0]["product_id"], "P2")
        self.assertNotIn("P1", [item["product_id"] for item in opportunities])
        self.assertGreater(opportunities[0]["quantity"], 0)
        self.assertGreater(opportunities[0]["estimated_cost"], 0)
        self.assertEqual(opportunities[0]["priority"], "Trial Buy")

    def test_risk_engine_flags_low_coverage_inventory(self) -> None:
        risks = RiskEngine().generate_risks(self.workbook, customer_id="C1")
        by_product = {item["product_id"]: item for item in risks}

        self.assertIn(by_product["P1"]["risk_level"], {"Critical", "High"})
        self.assertEqual(by_product["P3"]["risk_level"], "Low")

    def test_procurement_plan_respects_budget(self) -> None:
        engine = RecommendationEngine()
        result = engine.generate_session_recommendations(self.workbook, "S1")

        total_cost = sum(item["estimated_cost"] for item in result["procurement_plan"])
        self.assertLessEqual(total_cost, 50.0)
        self.assertLessEqual(result["remaining_budget"], 50.0)

    def test_procurement_plan_uses_user_budget_override(self) -> None:
        engine = RecommendationEngine()
        result = engine.generate_session_recommendations(
            self.workbook,
            "S1",
            context_override={"Budget": 10.0},
        )

        total_cost = sum(item["estimated_cost"] for item in result["procurement_plan"])
        self.assertEqual(result["context"]["Budget"], 10.0)
        self.assertLessEqual(total_cost, 10.0)
        self.assertLessEqual(result["remaining_budget"], 10.0)

    def test_missing_user_budget_removes_scenario_budget_constraint(self) -> None:
        engine = RecommendationEngine()
        result = engine.generate_session_recommendations(
            self.workbook,
            "S1",
            context_override={"Budget": None},
            clear_context_keys={"Budget"},
        )

        total_cost = sum(item["estimated_cost"] for item in result["procurement_plan"])
        self.assertIsNone(result["context"]["Budget"])
        self.assertIsNone(result["remaining_budget"])
        self.assertGreater(total_cost, 0)
        self.assertGreater(len(result["procurement_plan"]), 0)

    def test_price_history_enriches_procurement_plan(self) -> None:
        self._add_price_history()

        result = RecommendationEngine().generate_session_recommendations(self.workbook, "S1")
        first_item = next(
            item for item in result["procurement_plan"] if item["product_id"] == "P1"
        )

        self.assertEqual(first_item["product_id"], "P1")
        self.assertEqual(first_item["price_trend"]["price_signal"], "Buy Now")
        self.assertEqual(first_item["unit_cost"], 5.0)
        self.assertEqual(first_item["estimated_cost"], first_item["quantity"] * 5.0)
        self.assertTrue(any("90-day low" in reason for reason in first_item["why"]))

    def test_fresh_buy_now_does_not_increase_quantity_above_historical_average(self) -> None:
        self._add_price_history()

        result = RecommendationEngine().generate_session_recommendations(self.workbook, "S1")
        first_item = result["procurement_plan"][0]

        self.assertEqual(first_item["product_type"], "Fresh")
        self.assertLessEqual(first_item["quantity"], 11)

    def test_non_fresh_buy_now_can_increase_quantity_and_use_latest_price(self) -> None:
        self._add_frozen_buy_now_price_history()

        recommendations = [
            {
                "product": "Frozen Fries",
                "product_id": "P3",
                "quantity": 10,
                "unit": "KG",
                "product_type": "Frozen",
                "score": 70.0,
                "recommendation_strength": "Medium",
                "why": [],
                "estimated_cost": 40.0,
                "unit_cost": 4.0,
                "coverage_days": 5.0,
                "historical_avg_qty": 5.0,
            }
        ]
        enriched = RecommendationEngine().price_trend_engine.enrich_recommendations(
            recommendations,
            self.workbook,
        )
        frozen_item = next(item for item in enriched if item["product_id"] == "P3")

        self.assertEqual(frozen_item["product_type"], "Frozen")
        self.assertEqual(frozen_item["price_trend"]["price_signal"], "Buy Now")
        self.assertEqual(frozen_item["unit_cost"], 3.0)
        self.assertEqual(frozen_item["estimated_cost"], frozen_item["quantity"] * 3.0)
        self.assertTrue(
            any("Quantity increased modestly" in reason for reason in frozen_item["why"])
        )

    def test_high_score_growth_trial_buy_can_enter_procurement_plan(self) -> None:
        self._add_price_history()

        result = RecommendationEngine().generate_session_recommendations(
            self.workbook,
            "S1",
            context_override={"Budget": 1000.0},
        )
        growth_item = next(
            item for item in result["procurement_plan"] if item["product_id"] == "P2"
        )

        self.assertEqual(growth_item["priority"], "Trial Buy")
        self.assertGreater(growth_item["quantity"], 0)
        self.assertGreater(growth_item["estimated_cost"], 0)
        self.assertEqual(growth_item["price_trend"]["price_signal"], "Buy Now")

    def test_budget_allocation_prioritizes_replenishment_before_trial_buy(self) -> None:
        plan, _ = RecommendationEngine._build_procurement_plan(
            replenishment=[
                {
                    "product": "Urgent Banana",
                    "product_id": "P1",
                    "quantity": 2,
                    "unit": "KG",
                    "estimated_cost": 10.0,
                    "recommendation_strength": "Medium",
                    "score": 65.0,
                    "coverage_days": 2.0,
                }
            ],
            growth=[
                {
                    "product": "High Score Trial",
                    "product_id": "P2",
                    "quantity": 2,
                    "unit": "KG",
                    "estimated_cost": 10.0,
                    "recommendation_strength": "High",
                    "priority": "Trial Buy",
                    "score": 95.0,
                }
            ],
            budget=10.0,
        )

        self.assertEqual(len(plan), 1)
        self.assertEqual(plan[0]["product_id"], "P1")
        self.assertEqual(plan[0]["action"], "Order Now")

    def test_intent_parser_fallback_extracts_nzd_budget(self) -> None:
        parser = IntentParser(ai_client=OfflineAIClient())
        intent = parser.parse_intent(
            "Budget NZD 100, high traffic next week, avoid short shelf-life products"
        )

        self.assertEqual(intent["Budget"], 100.0)
        self.assertEqual(intent["TrafficLevel"], "HIGH")
        self.assertEqual(intent["ShelfLifePreference"], "LONG")

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

    def test_missing_order_history_raises_insufficient_data(self) -> None:
        workbook = dict(self.workbook)
        workbook["OrderHistory"] = self.workbook["OrderHistory"].iloc[0:0].copy()

        with self.assertRaises(InsufficientDataError):
            RecommendationEngine().generate_session_recommendations(workbook, "S1")


if __name__ == "__main__":
    unittest.main()
