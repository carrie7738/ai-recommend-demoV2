import unittest
from pathlib import Path
from unittest.mock import patch
from types import SimpleNamespace

import pandas as pd

from services.intent_parser import IntentParser
from services.v2_preparation import V2PreparationPipeline
from services.candidate_pool import CandidatePoolBuilder


class IntentCorrectnessTests(unittest.TestCase):
    def setUp(self):
        self.parser = IntentParser(ai_client=SimpleNamespace(is_available=False))

    def test_thousands_and_chinese_budget_constraints(self):
        for request in ['C001 budget 1,000 NZD, only fruit', 'C001 预算1000，只采购水果']:
            with self.subTest(request=request):
                intent = self.parser.parse_intent(request)['StructuredIntent']
                self.assertEqual(intent['budget'], 1000)
                self.assertIn({'type': 'CATEGORY', 'operator': 'INCLUDE_ONLY', 'values': ['Fruit']}, intent['hard_constraints'])

    def test_invalid_budget_is_not_silently_unlimited(self):
        for request in ['budget 1,00', 'budget -100', 'budget approximately a thousand', 'budget 1e3', 'budget 1.2.3']:
            with self.subTest(request=request), self.assertRaises(ValueError):
                self.parser.parse_intent(request)

    def test_budget_zero_decimal_and_absent(self):
        for request, expected in [('budget 0', 0), ('budget NZD 1,000.50', 1000.5), ('预算1万', 10000), ('no budget limit', None), ('buy P001', None)]:
            with self.subTest(request=request):
                self.assertEqual(self.parser.parse_intent(request)['StructuredIntent']['budget'], expected)

    def test_conflicting_or_partly_unparsed_budgets_require_clarification(self):
        for request in ['no budget limit, budget 100', 'budget 100 and budget unclear',
                        'budget 100 and budget 1e3', 'budget 100 and NZD unknown']:
            with self.subTest(request=request), self.assertRaises(ValueError):
                self.parser.parse_intent(request)

    def test_repeated_equivalent_budget_and_currency_suffix_are_valid(self):
        for request in ['budget NZD 1,000, budget 1000 NZD', 'budget 1000 dollars']:
            with self.subTest(request=request):
                self.assertEqual(self.parser.parse_intent(request)['StructuredIntent']['budget'], 1000)

    def test_negated_sku_is_excluded(self):
        intent = self.parser.parse_intent('C001 budget 100, do not buy P001')['StructuredIntent']
        self.assertEqual(intent['explicit_products'], [])
        self.assertIn({'type': 'PRODUCT', 'operator': 'EXCLUDE', 'values': ['P001']}, intent['hard_constraints'])

    def test_catalog_negation_overrides_existing_positive_reference(self):
        products = pd.DataFrame([{'ProductId': 'P001', 'ProductName': 'Apples'}])
        for request in ['Do not buy Apples', '不要采购Apples']:
            with self.subTest(request=request):
                result = V2PreparationPipeline._resolve_catalog_mentions(request, products, [{'sku': 'P001', 'product_name': 'Apples', 'quantity_intent': 'NORMAL'}])
                self.assertEqual(result, [])

    def test_product_exclusion_is_a_hard_filter(self):
        self.assertFalse(CandidatePoolBuilder._passes_hard_constraints(
            {'ProductId': 'P001', 'ProductName': 'Apples'},
            [{'type': 'PRODUCT', 'operator': 'EXCLUDE', 'values': ['P001']}],
        ))

    def test_product_exclusion_schema_is_strict(self):
        from jsonschema import Draft202012Validator
        from services.intent_parser import INTENT_JSON_SCHEMA
        schema = INTENT_JSON_SCHEMA['properties']['structured_intent']['properties']['hard_constraints']
        validator = Draft202012Validator(schema)
        self.assertTrue(validator.is_valid([{'type': 'PRODUCT', 'operator': 'EXCLUDE', 'values': ['P001']}]))
        self.assertFalse(validator.is_valid([{'type': 'PRODUCT', 'operator': 'INCLUDE_ONLY', 'values': ['P001']}]))

    def test_catalog_name_matching_does_not_match_inside_another_word(self):
        result = V2PreparationPipeline._resolve_catalog_mentions(
            'Please buy Pineapples', pd.DataFrame([{'ProductId': 'P001', 'ProductName': 'Apples'}]), [],
        )
        self.assertEqual(result, [])

    def test_negated_list_does_not_swallow_next_positive_instruction(self):
        intent = self.parser.parse_intent('Do not buy P001 and P002, buy P003')['StructuredIntent']
        self.assertEqual([item['sku'] for item in intent['explicit_products']], ['P003'])

    def test_real_preparation_filters_negated_catalog_product(self):
        workbook = pd.read_excel(Path(__file__).resolve().parents[1] / 'data/AI_Demo_Data_Pack_V2_Large.xlsx', sheet_name=None)
        product = workbook['Product'].set_index('ProductId').loc['P201']['ProductName']
        result = V2PreparationPipeline(intent_parser=self.parser).prepare(workbook, 'C051', f'Do not buy {product}', '2026-06-02')
        self.assertNotIn('P201', [item['candidate_id'] for item in result['candidate_pool']['eligible_candidates']])
        rejected = {item['candidate_id']: item for item in result['candidate_pool']['rejected_candidates']}
        self.assertEqual(rejected['P201']['rejection_code'], 'HARD_CONSTRAINT_FILTER')

    def test_fallback_respects_negated_name_after_summary_limit(self):
        from tests.test_recommendation_engine import RecommendationEngineTests
        from engines.recommendation_engine import RecommendationEngine
        fixture = RecommendationEngineTests()
        fixture.setUp()
        request = 'Please plan replenishment. ' * 8 + 'Do not buy Banana.'
        result = RecommendationEngine().generate_session_recommendations(
            fixture.workbook, 'S1', context_override={'UserInput': request},
        )
        self.assertNotIn('P1', [item['product_id'] for item in result['procurement_plan']])

    def test_unknown_inventory_warning_is_visible(self):
        from services.ui import render_v2_purchase_plan
        with patch('services.ui.st.markdown'), patch('services.ui.st.warning') as warning:
            render_v2_purchase_plan([], {'unallocated_candidates': [{'candidate_id': 'P1', 'reason': 'INVENTORY_UNAVAILABLE'}]}, {'status': 'PASS', 'valid': True})
        self.assertIn('P1', warning.call_args.args[0])


if __name__ == '__main__':
    unittest.main()
