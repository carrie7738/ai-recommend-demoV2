from __future__ import annotations

import logging
import os
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path


BASE_DIR = Path(__file__).resolve().parent.parent


@dataclass(frozen=True)
class AISettings:
    enabled: bool = True
    api_key: str = ""
    base_url: str = "https://api.deepseek.com"
    model: str = "deepseek-v4-flash"
    temperature: float = 0.3
    max_tokens: int = 1024


@dataclass(frozen=True)
class Settings:
    app_title: str = "AI Smart Procurement Assistant"
    log_level: str = "INFO"
    excel_file: str = str(BASE_DIR / "data" / "AI_Demo_Data_Pack_V2_Large.xlsx")
    ai: AISettings = field(default_factory=lambda: AISettings(
        api_key=os.getenv("DEEPSEEK_API_KEY", ""),
    ))


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings(
        app_title=os.getenv("APP_TITLE", "AI Smart Procurement Assistant"),
        log_level=os.getenv("LOG_LEVEL", "INFO").upper(),
        excel_file=os.getenv(
            "EXCEL_FILE",
            str(BASE_DIR / "data" / "AI_Demo_Data_Pack_V2_Large.xlsx"),
        ),
        ai=AISettings(
            enabled=os.getenv("AI_ENABLED", "true").lower() == "true",
            api_key=os.getenv("DEEPSEEK_API_KEY", ""),
            base_url=os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com"),
            model=os.getenv("DEEPSEEK_MODEL", "deepseek-chat"),
            temperature=float(os.getenv("AI_TEMPERATURE", "0.3")),
            max_tokens=int(os.getenv("AI_MAX_TOKENS", "1024")),
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
