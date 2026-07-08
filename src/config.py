"""Central configuration. Every path, secret, and tunable comes from the
environment (see .env.example) — nothing here is hardcoded per the case-study
requirement that the app must be configurable without touching code."""
from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import date
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()


def _bool(name: str, default: str) -> bool:
    return os.getenv(name, default).strip().lower() in {"1", "true", "yes", "on"}


def _date(name: str, default: str) -> date:
    return date.fromisoformat(os.getenv(name, default))


@dataclass(frozen=True)
class Settings:
    data_dir: Path
    output_dir: Path
    database_url: str
    as_of_date: date
    quiz1_date: date
    quiz2_date: date
    llm_enabled: bool
    openai_api_key: str
    openai_model: str
    openai_base_url: str
    app_port: int
    notification_mode: str
    seed_admin_email: str
    seed_admin_password: str
    seed_facilitator_password: str

    @property
    def days_until_quiz2(self) -> int:
        return (self.quiz2_date - self.as_of_date).days

    @property
    def days_since_quiz1(self) -> int:
        return (self.as_of_date - self.quiz1_date).days


def load_settings() -> Settings:
    return Settings(
        data_dir=Path(os.getenv("DATA_DIR", "./data")),
        output_dir=Path(os.getenv("OUTPUT_DIR", "./outputs")),
        database_url=os.getenv("DATABASE_URL", "sqlite:///./boon.db"),
        as_of_date=_date("AS_OF_DATE", "2025-10-14"),
        quiz1_date=_date("QUIZ1_DATE", "2025-10-10"),
        quiz2_date=_date("QUIZ2_DATE", "2025-10-20"),
        llm_enabled=_bool("LLM_ENABLED", "true"),
        openai_api_key=os.getenv("OPENAI_API_KEY", "").strip(),
        openai_model=os.getenv("OPENAI_MODEL", "gpt-4o-mini").strip(),
        # Blank = real OpenAI. The OpenAI SDK works against any
        # OpenAI-compatible endpoint (e.g. Groq) by overriding base_url only.
        openai_base_url=os.getenv("OPENAI_BASE_URL", "").strip(),
        app_port=int(os.getenv("APP_PORT", "8501")),
        notification_mode=os.getenv("NOTIFICATION_MODE", "dry_run"),
        seed_admin_email=os.getenv("SEED_ADMIN_EMAIL", "admin@boonacademy.demo"),
        seed_admin_password=os.getenv("SEED_ADMIN_PASSWORD", ""),
        seed_facilitator_password=os.getenv("SEED_FACILITATOR_PASSWORD", ""),
    )


SETTINGS = load_settings()

# Business constants defined by the case study itself (not derived from data).
TARGET_COVERAGE = 0.80
RISK_LEVELS = (
    ("Critical", 70, 100),
    ("High", 50, 69),
    ("Medium", 30, 49),
    ("Low", 0, 29),
)


def risk_level_for(score: float) -> str:
    for label, lo, hi in RISK_LEVELS:
        if lo <= score <= hi:
            return label
    return "Low"


# --- Shared design-system palette -----------------------------------------
# One source of truth for color so the live app (app.py) and generated
# documents (src/reports.py — parent reports, facilitator_dashboard.html)
# never drift apart. Values are a fixed status/categorical palette (not
# user-configurable) validated for colorblind-safe adjacent contrast — see
# the project's dataviz skill reference for the derivation.

# Status colors are reserved for state (never reused as a generic series
# color) and always paired with an icon/label, never color alone.
RISK_COLORS = {"Critical": "#d03b3b", "High": "#ec835a", "Medium": "#fab219", "Low": "#0ca30c"}
RISK_ICONS = {"Critical": "🔴", "High": "🟠", "Medium": "🟡", "Low": "🟢"}

# Parent-report status labels reuse the same status steps; "Improving" is a
# distinct trend signal, not a severity level, so it takes the brand blue
# instead of borrowing a severity color it doesn't mean.
REPORT_STATUS_COLORS = {
    "Critical": RISK_COLORS["Critical"],
    "Needs Attention": RISK_COLORS["High"],
    "Watch": RISK_COLORS["Medium"],
    "Stable": RISK_COLORS["Low"],
    "Improving": "#2a78d6",
}
REPORT_STATUS_ICONS = {
    "Critical": "🔴", "Needs Attention": "🟠", "Watch": "🟡", "Stable": "🟢", "Improving": "🔵",
}

# Fixed-order categorical hues (never cycled/reassigned) for multi-series
# charts such as per-facilitator workload.
CATEGORICAL_COLORS = [
    "#2a78d6", "#1baf7a", "#eda100", "#008300",
    "#4a3aa7", "#e34948", "#e87ba4", "#eb6834",
]

INK = {"primary": "#0b0b0b", "secondary": "#52514e", "muted": "#898781"}
CHART_SURFACE = "#fcfcfb"
PAGE_PLANE = "#f9f9f7"
GRIDLINE = "#e1e0d9"
BRAND_BLUE = "#2a78d6"

# --- Dark theme (the live Streamlit app) ----------------------------------
# Derived from analyzing motion.dev's actual computed styles (background,
# text, and surface colors extracted programmatically, not eyeballed): a
# warm near-black charcoal with a faint green undertone, rather than pure
# black, plus a muted sage-gray secondary ink. Their signature accent is a
# vivid yellow — reused here would collide with our own "Medium risk =
# yellow" status color, so the app keeps its existing validated brand blue
# (brightened one step for dark-surface contrast) instead of copying their
# exact hue. Parent-facing documents (src/reports.py) stay on the light
# palette above — this dark set is for the facilitator/admin app chrome only.
DARK_BG = "#0b0f0e"           # page canvas
DARK_BG_DEEP = "#070a09"      # header strip / deepest recess
DARK_SURFACE = "#141a18"      # cards, inputs
DARK_SURFACE_RAISED = "#1a2220"  # hovered/raised cards
DARK_BORDER = "rgba(237, 237, 236, 0.09)"
DARK_INK = {"primary": "#ededec", "secondary": "#958d82", "muted": "#7c8e86"}
DARK_ACCENT = "#3987e5"      # dark-surface step of the brand blue (validated, not the light-mode hex)
DARK_GRIDLINE = "rgba(237, 237, 236, 0.08)"
MONO_FONT = "ui-monospace, SFMono-Regular, 'Geist Mono', Menlo, Consolas, monospace"
