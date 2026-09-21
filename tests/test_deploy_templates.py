import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
SERVICE_PATH = REPO_ROOT / "deploy" / "procurement-demo.service"


class DeployTemplateTests(unittest.TestCase):
    def test_service_uses_external_environment_file(self) -> None:
        service = SERVICE_PATH.read_text(encoding="utf-8")

        self.assertIn("EnvironmentFile=/etc/procurement-demo.env", service)
        self.assertNotIn("Environment=", service)
        self.assertNotIn("DEEPSEEK_API_KEY", service)
        self.assertNotIn("replace-with", service)

    def test_streamlit_is_bound_to_loopback(self) -> None:
        service = SERVICE_PATH.read_text(encoding="utf-8")

        self.assertIn("--server.address 127.0.0.1", service)
        self.assertNotIn("--server.address 0.0.0.0", service)
        self.assertIn("--server.headless true", service)


if __name__ == "__main__":
    unittest.main()
