from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


class ConfigurationError(ValueError):
    """Raised when required application configuration is invalid."""


@dataclass(frozen=True, slots=True)
class Settings:
    telegram_bot_token: str
    admin_chat_id: int
    llm_base_url: str
    llm_api_key: str
    llm_model: str
    faq_path: Path
    database_path: Path
    llm_log_path: Path

    @classmethod
    def from_env(cls) -> "Settings":
        required = (
            "TELEGRAM_BOT_TOKEN",
            "ADMIN_CHAT_ID",
            "LLM_BASE_URL",
            "LLM_API_KEY",
            "LLM_MODEL",
            "FAQ_PATH",
            "DATABASE_PATH",
            "LLM_LOG_PATH",
        )
        values = {name: os.environ.get(name, "").strip() for name in required}
        missing = [name for name, value in values.items() if not value]
        if missing:
            raise ConfigurationError(
                f"Missing required environment variables: {', '.join(missing)}"
            )
        try:
            admin_chat_id = int(values["ADMIN_CHAT_ID"])
        except ValueError as exc:
            raise ConfigurationError("ADMIN_CHAT_ID must be an integer") from exc

        return cls(
            telegram_bot_token=values["TELEGRAM_BOT_TOKEN"],
            admin_chat_id=admin_chat_id,
            llm_base_url=values["LLM_BASE_URL"],
            llm_api_key=values["LLM_API_KEY"],
            llm_model=values["LLM_MODEL"],
            faq_path=Path(values["FAQ_PATH"]),
            database_path=Path(values["DATABASE_PATH"]),
            llm_log_path=Path(values["LLM_LOG_PATH"]),
        )

