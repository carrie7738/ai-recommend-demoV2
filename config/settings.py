from __future__ import annotations

import logging
import os
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path

from dotenv import load_dotenv


BASE_DIR = Path(__file__).resolve().parent.parent


def load_repository_env(env_path: str | Path = BASE_DIR / ".env") -> bool:
    """Load local configuration without overriding injected environment variables."""
    return load_dotenv(dotenv_path=env_path, override=False)


load_repository_env()


@dataclass(frozen=True)
class AISettings:
    enabled: bool = True
    provider: str = "deepseek"
    api_key: str = ""
    base_url: str = "https://api.deepseek.com"
    model: str = "deepseek-chat"
    temperature: float = 0.3
    max_tokens: int = 1024
    structured_max_tokens: int = 16384
    thinking_enabled: bool = False


@dataclass(frozen=True)
class Settings:
    app_title: str = "AI Smart Procurement Assistant"
    log_level: str = "INFO"
    excel_file: str = str(BASE_DIR / "data" / "AI_Demo_Data_Pack_V2_Large.xlsx")
    default_customer_name: str = "Auckland Central Supermarket"
    ai: AISettings = field(default_factory=lambda: AISettings(
        api_key=os.getenv("DEEPSEEK_API_KEY", ""),
    ))


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    provider = os.getenv("AI_PROVIDER", "deepseek").strip().lower()
    if provider == "glm":
        api_key = os.getenv("GLM_API_KEY", "")
        base_url = os.getenv("GLM_BASE_URL", "https://open.bigmodel.cn/api/paas/v4")
        model = os.getenv("GLM_MODEL", "glm-5.2")
    elif provider == "gemini":
        api_key = os.getenv("GEMINI_API_KEY", "")
        base_url = os.getenv(
            "GEMINI_BASE_URL",
            "https://generativelanguage.googleapis.com/v1beta/openai/",
        )
        model = os.getenv("GEMINI_MODEL", "gemini-3.6-flash")
    else:
        api_key = os.getenv("DEEPSEEK_API_KEY", "")
        base_url = os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com")
        model = os.getenv("DEEPSEEK_MODEL", "deepseek-chat")

    return Settings(
        app_title=os.getenv("APP_TITLE", "AI Smart Procurement Assistant"),
        log_level=os.getenv("LOG_LEVEL", "INFO").upper(),
        excel_file=os.getenv(
            "EXCEL_FILE",
            str(BASE_DIR / "data" / "AI_Demo_Data_Pack_V2_Large.xlsx"),
        ),
        default_customer_name=os.getenv("DEFAULT_CUSTOMER_NAME", "Auckland Central Supermarket"),
        ai=AISettings(
            enabled=os.getenv("AI_ENABLED", "true").lower() == "true",
            provider=provider,
            api_key=api_key,
            base_url=base_url,
            model=model,
            temperature=float(os.getenv("AI_TEMPERATURE", "0.3")),
            max_tokens=int(os.getenv("AI_MAX_TOKENS", "1024")),
            structured_max_tokens=int(os.getenv("AI_STRUCTURED_MAX_TOKENS", "16384")),
            thinking_enabled=os.getenv("AI_THINKING_ENABLED", "false").lower() == "true",
        ),
    )


def setup_logging(log_level: str) -> logging.Logger:
    numeric_level = getattr(logging, log_level.upper(), logging.INFO)
    logging.basicConfig(
        level=numeric_level,
        format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
        force=False,
    )
    logger = logging.getLogger("procurement_demo")
    logger.setLevel(numeric_level)
    return logger
