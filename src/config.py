"""Centralized, env-driven configuration.

Every path and secret the pipeline touches comes from an environment
variable (loaded from `.env` via python-dotenv if present, else the real
process environment). Nothing here is hardcoded to a machine-specific path,
and there is no fallback API key — if LLM_ENABLED=true and the key is
missing, `src/llm.py` degrades to deterministic templates rather than
silently using a baked-in secret.
"""

from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv
from pydantic import BaseModel

load_dotenv()  # no-op if .env doesn't exist; real env vars still win


def _env_bool(name: str, default: bool) -> bool:
    raw = os.environ.get(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


class Settings(BaseModel):
    """Runtime configuration resolved once at startup."""

    data_dir: Path
    output_dir: Path
    llm_enabled: bool
    openai_api_key: str | None
    openai_model: str
    app_port: int

    # Program-day anchors from the case brief. Quiz 1 already happened,
    # Quiz 2 has not — this is what drives "recent" windows and urgency.
    current_day: int = 14
    quiz1_day: int = 10
    quiz2_day: int = 20

    @classmethod
    def load(cls) -> "Settings":
        return cls(
            data_dir=Path(os.environ.get("DATA_DIR", "./data")),
            output_dir=Path(os.environ.get("OUTPUT_DIR", "./outputs")),
            llm_enabled=_env_bool("LLM_ENABLED", False),
            openai_api_key=os.environ.get("OPENAI_API_KEY") or None,
            openai_model=os.environ.get("OPENAI_MODEL", "gpt-4o-mini"),
            app_port=int(os.environ.get("APP_PORT", "8501")),
        )

    @property
    def llm_available(self) -> bool:
        """True only when the operator opted in AND supplied a key."""
        return self.llm_enabled and bool(self.openai_api_key)


settings = Settings.load()
