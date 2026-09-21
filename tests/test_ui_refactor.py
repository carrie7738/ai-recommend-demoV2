"""Offline presentation checks; fixture plans do not represent model acceptance."""
import json
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from streamlit.testing.v1 import AppTest
from services.intent_parser import IntentParser


ROOT = Path(__file__).resolve().parents[1]


class ProcurementPageTests(unittest.TestCase):
    def test_header_identifies_demo_mode_and_business_date(self):
        from services.ui import render_header

        with patch("services.ui.st.markdown") as markdown:
            render_header(
                "Cafe Store 001",
                "Cafe",
                business_date="2026-06-02",
                date_source="SupplyAvailability.LastUpdated.latest_not_future",
                run_time=datetime(2026, 9, 20, 17, 43),
            )

        html = markdown.call_args.args[0]
        self.assertIn("DEMO MODE", html)
        self.assertIn("Business Data Date", html)
        self.assertIn("June 02, 2026", html)
        self.assertIn("Supply snapshot", html)
        self.assertIn("Run Sep 20, 2026 17:43 local", html)
        self.assertNotIn("Analysis Time", html)

    def test_landing_header_marks_date_as_pending(self):
        from services.ui import render_header

        with patch("services.ui.st.markdown") as markdown:
            render_header(show_context=False, run_time=datetime(2026, 9, 20, 17, 43))

        html = markdown.call_args.args[0]
        self.assertIn("DEMO MODE", html)
        self.assertIn("Selected after request", html)
        self.assertIn("Workbook-backed demo data", html)

    def test_inline_reason_tags_require_matching_structured_evidence(self):
        from services.ui import _inline_reasons, _plan_markup
        reasons = ['Frequently purchased by this store.', 'Existing reason <two>', 'Remaining reason']
        item = {'product_name': 'Test product', 'why_selected': reasons,
                'decision_signals': ['PURCHASE_FREQUENCY=HIGH']}
        html = _inline_reasons(item)
        self.assertIn('>Frequent purchase</span>', html)
        self.assertIn('Existing reason &lt;two&gt;', html)
        self.assertIn('+1 more', html)
        self.assertIn('<li>Remaining reason</li>', html)
        self.assertNotIn('>Frequent purchase</span>', _inline_reasons({'why_selected': reasons}))
        table = _plan_markup([item], 0, None, None, True)
        self.assertIn('<th>Why Selected</th>', table)
        self.assertNotIn('<h3>Why Selected</h3>', table)
        self.assertEqual(table.count('Test product'), 1)

    def render_result(self, request, budget, valid=True):
        intent = IntentParser(ai_client=SimpleNamespace(is_available=False)).parse_intent(request)
        result = {
            'safe_decision_context': {'structured_intent': intent['StructuredIntent']},
            'intent': intent,
            'final_purchase_plan': [{
                'candidate_id': 'TEST', 'product_name': 'Fixture product',
                'final_qty': 2, 'unit': 'pack', 'unit_cost': 5,
                'estimated_cost': 10, 'priority': 'HIGH',
                'why_selected': ['Verified fixture evidence.'],
            }],
            'optimizer_result': {'total_cost': 10, 'remaining_budget': None if budget is None else budget - 10},
            'validation_result': {'status': 'PASS' if valid else 'FAIL', 'valid': valid,
                                  'violations': [] if valid else [{'code': 'TEST_FAILURE'}]},
            'ai_decision': {'procurement_strategy': {}}, 'retry_count': 0,
            'v2_status': 'SUCCESS' if valid else 'FAILED',
        }
        script = '''
import streamlit as st
import pandas as pd
from unittest.mock import patch
from types import SimpleNamespace
import app as page
st.session_state.update(STATE)
with patch.object(page, 'get_workbook', return_value={}), \
     patch.object(page, 'get_context_engine', return_value=SimpleNamespace(build_context=lambda *a: {})), \
     patch.object(page, 'AIClient', return_value=SimpleNamespace(is_available=True, provider_name='offline', settings=SimpleNamespace(model='fixture'))):
    page.main()
'''.replace('STATE', repr({
            'session_id': 'TEST', 'has_user_request': True,
            'parsed_intent': intent, 'user_request': request,
            'v2_result': result, 'v2_error': None,
        }))
        app = AppTest.from_string(script).run(timeout=20)
        self.assertEqual(len(app.exception), 0)
        return app, '\n'.join(x.value for x in app.markdown if '<style>' not in x.value)

    def test_six_requests_preserve_page_order_and_budget_display(self):
        scenarios = json.loads((ROOT / 'videos/procurement-scenarios/media/scenarios.json').read_text())
        budgets = [1000, 1000, 300, 1000, 800, None]
        for scenario, budget in zip(scenarios, budgets):
            with self.subTest(scenario=scenario['slug']):
                app, html = self.render_result(scenario['request'], budget)
                self.assertLess(html.index('Business Request'), html.index('AI Understanding'))
                self.assertLess(html.index('AI Understanding'), html.index('Purchase Plan'))
                self.assertLess(html.index('Purchase Plan'), html.index('Potential Opportunities'))
                self.assertNotIn('AI Product Decisions', html)
                self.assertIn('Fixture product', html)
                self.assertEqual(len(app.error), 0)
                if budget is None:
                    self.assertIn('Not specified', html)
                    self.assertNotIn('Not constrained', html)

    def test_failed_validation_hides_plan_and_selected_evidence(self):
        app, html = self.render_result('For C001, budget NZD 1000.', 1000, valid=False)
        self.assertGreater(len(app.error), 0)
        self.assertNotIn('Fixture product', html)
        self.assertNotIn('Verified fixture evidence.', html)

    def test_missing_values_do_not_become_zero_or_priority(self):
        app = AppTest.from_string('''
from services.ui import render_v2_purchase_plan
render_v2_purchase_plan([{'product_name':'Incomplete'}], {}, {'status':'PASS','valid':True})
''').run(timeout=15)
        self.assertEqual(len(app.exception), 0)
        html = '\n'.join(x.value for x in app.markdown)
        self.assertNotIn('NZD 0.00', html)
        self.assertNotIn('HIGH', html)

    def test_fallback_does_not_claim_validation_or_invent_reasons(self):
        app = AppTest.from_string('''
from services.ui import render_unvalidated_fallback_plan
render_unvalidated_fallback_plan([{'product':'Fallback product','quantity':2,
    'unit_cost':5,'estimated_cost':10,'action':'Buy Now'}], None)
''').run(timeout=15)
        self.assertEqual(len(app.exception), 0)
        html = '\n'.join(x.value for x in app.markdown)
        self.assertIn('Fallback product', html)
        self.assertIn('Not specified', html)
        self.assertNotIn('Within Budget', html)
        self.assertNotIn('Validated', html)
        self.assertNotIn('strongest combined', html)

    def test_missing_understanding_fields_are_not_filled_by_ui(self):
        app = AppTest.from_string('''
from services.ui import render_ai_understanding
render_ai_understanding({'StructuredIntent': {'traffic_expectation':'NORMAL'},
    'Uncertainty': {'FieldSources': {'traffic_level':'missing'}}})
''').run(timeout=15)
        self.assertEqual(len(app.exception), 0)
        html = '\n'.join(x.value for x in app.markdown)
        self.assertNotIn('Normal', html)
        self.assertNotIn('Ready for recommendation', html)
        self.assertNotIn('General Planning', html)


if __name__ == '__main__':
    unittest.main()
