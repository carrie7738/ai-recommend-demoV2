import unittest

from app import should_render_recommendations


class AppStateTests(unittest.TestCase):
    def test_recommendations_are_hidden_before_a_request_is_submitted(self) -> None:
        self.assertFalse(should_render_recommendations(False, None))
        self.assertFalse(should_render_recommendations(False, "S001"))

    def test_recommendations_require_a_matched_session(self) -> None:
        self.assertFalse(should_render_recommendations(True, None))
        self.assertTrue(should_render_recommendations(True, "S001"))

if __name__ == "__main__":
    unittest.main()
