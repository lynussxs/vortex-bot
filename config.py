"""Environment-backed application configuration."""

from __future__ import annotations

import os
import re
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True, slots=True)
class Settings:
    discord_token: str
    openrouter_api_key: str | None
    ai_model: str
    database_path: Path
    database_fallback_path: Path
    runtime_environment: str
    owner_id: int | None
    dev_guild_id: int | None
    ai_max_tokens: int
    ai_cooldown: int
    log_level: str

    @classmethod
    def from_env(cls) -> "Settings":
        token = os.getenv("DISCORD_TOKEN", "").strip()
        if not token:
            raise RuntimeError(
                "DISCORD_TOKEN is required. Add your bot token to Replit Secrets "
                "or the Railway service variables."
            )

        model = os.getenv("AI_MODEL", "openai/gpt-4o-mini").strip()
        if not re.fullmatch(r"[a-zA-Z0-9][a-zA-Z0-9._:/-]{2,127}", model):
            raise RuntimeError("AI_MODEL must be a valid OpenRouter model identifier.")
        log_level = os.getenv("LOG_LEVEL", "INFO").upper()
        if log_level not in {"CRITICAL", "ERROR", "WARNING", "INFO", "DEBUG"}:
            raise RuntimeError("LOG_LEVEL must be CRITICAL, ERROR, WARNING, INFO, or DEBUG.")

        runtime_environment = _runtime_environment()
        local_database_path = Path(
            os.getenv(
                "DATABASE_FALLBACK_PATH",
                str(Path(__file__).resolve().parent / "data" / "mybot.db"),
            )
        )
        default_database_path = Path("/data/mybot.db") if runtime_environment == "railway" else local_database_path

        return cls(
            discord_token=token,
            openrouter_api_key=os.getenv("OPENROUTER_API_KEY", "").strip() or None,
            ai_model=model,
            database_path=Path(os.getenv("DATABASE_PATH", str(default_database_path))),
            database_fallback_path=local_database_path,
            runtime_environment=runtime_environment,
            owner_id=_optional_int("OWNER_ID"),
            dev_guild_id=_optional_int("DEV_GUILD_ID"),
            ai_max_tokens=_bounded_int("AI_MAX_TOKENS", default=500, minimum=1, maximum=8192),
            ai_cooldown=_bounded_int("AI_COOLDOWN", default=10, minimum=1, maximum=3600),
            log_level=log_level,
        )


def _runtime_environment() -> str:
    if any(os.getenv(name, "").strip() for name in ("RAILWAY_ENVIRONMENT", "RAILWAY_PROJECT_ID", "RAILWAY_SERVICE_ID")):
        return "railway"
    if any(os.getenv(name, "").strip() for name in ("REPL_ID", "REPLIT_DEV_DOMAIN", "REPLIT_DOMAINS")):
        return "replit"
    return "local"


def _optional_int(name: str) -> int | None:
    value = os.getenv(name, "").strip()
    if not value:
        return None
    try:
        parsed = int(value)
    except ValueError as exc:
        raise RuntimeError(f"{name} must be a positive integer.") from exc
    if parsed <= 0:
        raise RuntimeError(f"{name} must be a positive integer.")
    return parsed


def _bounded_int(name: str, *, default: int, minimum: int, maximum: int) -> int:
    value = os.getenv(name, "").strip()
    try:
        parsed = int(value) if value else default
    except ValueError as exc:
        raise RuntimeError(f"{name} must be an integer.") from exc
    if not minimum <= parsed <= maximum:
        raise RuntimeError(f"{name} must be between {minimum} and {maximum}.")
    return parsed
