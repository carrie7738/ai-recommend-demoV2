"""Exercise the learning view with real captured pipeline data, without network."""
import json
import os
from pathlib import Path
import unittest
from unittest.mock import patch

import streamlit as st
from streamlit.testing.v1 import AppTest

import tests.test_runtime_trace as trace_fixtures


ROOT = Path(__file__).resolve().parents[1]


class DebugTraceUITests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        fixture = trace_fixtures.RuntimeTracePipelineTests()
        fixture.setUpClass()
        cls.result, cls.trace = fixture._run_success(captured=True)

    def render(self, enabled=True):
        app = AppTest.from_string(
            'import streamlit as st\n'
            'from services.debug_ui import render_debug_trace\n'
            'render_debug_trace(st.session_state["fixture_trace"])\n'
        )
        app.session_state['fixture_trace'] = self.trace
        with patch.dict(os.environ, {'PROCUREMENT_DEBUG': str(enabled).lower()}):
            app.run(timeout=25)
        self.assertEqual(len(app.exception), 0)
        return app

    def test_real_pipeline_trace_renders_and_filtering_preserves_snapshot(self):
        app = self.render()
        headings = [item.value for item in app.markdown if item.value.startswith('### ')]
        self.assertEqual(len(headings), 11)
        self.assertGreaterEqual(len(app.dataframe), 5)
        self.assertEqual(len(app.get('download_button')), 1)
        before = json.dumps(app.session_state['fixture_trace'], sort_keys=True)
        with patch.dict(os.environ, {'PROCUREMENT_DEBUG': 'true'}):
            app.text_input(key='debug_trace_sku_filter').set_value('P209').run(timeout=25)
        self.assertEqual(len(app.exception), 0)
        self.assertEqual(json.dumps(app.session_state['fixture_trace'], sort_keys=True), before)

    def test_ai_rejection_is_not_confused_with_empty_candidate_pool(self):
        from services.debug_ui import _no_purchase_message
        message = _no_purchase_message({"v2_status": "SUCCESS"}, ["RULE_REJECTED", "AI_NOT_SELECTED"])
        self.assertIn("AI", message)
        self.assertNotIn("没有候选商品通过", message)
        self.assertIn("失败", _no_purchase_message({"v2_status": "FAILED"}, []))

    def test_environment_gate_hides_trace_even_when_snapshot_exists(self):
        app = self.render(enabled=False)
        self.assertEqual(len(app.dataframe), 0)
        self.assertEqual(len(app.get('download_button')), 0)
        self.assertEqual(len(app.text_input), 0)

    def test_two_submissions_and_fallback_filter_rerun_are_isolated(self):
        with patch.dict(os.environ, {'PROCUREMENT_DEBUG': 'true', 'AI_ENABLED': 'false'}):
            st.cache_resource.clear()
            try:
                app = AppTest.from_file(str(ROOT / 'app.py')).run(timeout=25)
                for budget in (1000, 300):
                    app.text_area(key='ai_request').set_value(
                        f'For Cafe Store 001, high traffic is expected next week. Budget is NZD {budget}.'
                    )
                    app.button[0].click().run(timeout=25)
                    self.assertEqual(len(app.exception), 0)
                    self.assertTrue(app.session_state['has_user_request'])
                    trace = app.session_state['debug_trace']
                    if budget == 1000:
                        first_id = trace['run_id']
                    else:
                        self.assertNotEqual(trace['run_id'], first_id)
                    before = json.dumps(trace, sort_keys=True)
                    app.text_input(key='debug_trace_sku_filter').set_value('P001').run(timeout=25)
                    self.assertEqual(len(app.exception), 0)
                    self.assertEqual(json.dumps(app.session_state['debug_trace'], sort_keys=True), before)
                    self.assertEqual(sum(e.get('operation') == 'rules_fallback' for e in trace['events']), 1)
            finally:
                st.cache_resource.clear()


if __name__ == '__main__':
    unittest.main()
