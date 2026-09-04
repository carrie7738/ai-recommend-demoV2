"""Exercise Streamlit's actual rendering runtime without network calls."""
import unittest

from streamlit.testing.v1 import AppTest


class V2UIRuntimeTests(unittest.TestCase):
    def render(self, body):
        app = AppTest.from_string(
            'from services.ui import render_v2_purchase_plan, render_v2_runtime_status\n' + body
        ).run(timeout=15)
        self.assertEqual(len(app.exception), 0)
        return app

    def test_valid_empty_plan_remains_a_valid_zero_purchase_result(self):
        app = self.render(
            "render_v2_purchase_plan([], {'total_cost': 0, 'remaining_budget': 1000}, "
            "{'status': 'PASS', 'valid': True})"
        )
        html = '\n'.join(element.value for element in app.markdown)
        self.assertIn('No executable purchase quantities.', html)
        self.assertIn('Validated', html)
        self.assertIn('NZD 0.00', html)
        self.assertEqual(len(app.error), 0)

    def test_failed_validator_exposes_violation_and_hides_executable_plan(self):
        app = self.render(
            "render_v2_purchase_plan([{'candidate_id':'TEST', 'final_qty':25}], {}, "
            "{'status':'FAIL','valid':False,'violations':[{'code':'AVAILABLE_STOCK_EXCEEDED'}]})"
        )
        self.assertEqual(len(app.markdown), 0)
        self.assertIn('AVAILABLE_STOCK_EXCEEDED', app.error[0].value)
        self.assertIn('No final purchase plan', app.error[0].value)

    def test_fallback_preserves_original_v2_error_in_runtime_output(self):
        app = self.render(
            "render_v2_runtime_status('deepseek', 'test-model', "
            "{'pipeline_version':'V1_FALLBACK','v2_status':'FAILED',"
            "'fallback_triggered':True,'fallback_reason':'schema <violation>'}, {}, 'fallback')"
        )
        html = '\n'.join(element.value for element in app.markdown)
        self.assertIn('V1_FALLBACK', html)
        self.assertIn('FAILED', html)
        self.assertIn('schema &lt;violation&gt;', html)
        self.assertIn('Intent: fallback', html)


if __name__ == '__main__':
    unittest.main()
