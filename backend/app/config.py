"""Runtime configuration, read from environment variables.

Every secret (AI API key) is read from the environment only. Nothing here is
ever sent to the frontend.
"""
from __future__ import annotations

import os
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parent.parent          # backend/
REPO_DIR = BACKEND_DIR.parent                                  # repository root


def _load_dotenv(path: Path) -> None:
    """Load KEY=VALUE lines from backend/.env for local runs (no extra dependency).

    Real environment variables always win, so Render / Vercel settings are never
    overridden. The file is gitignored; values are never logged.
    """
    if not path.is_file():
        return
    for raw in path.read_text(encoding="utf-8", errors="ignore").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.split(" #", 1)[0].strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = value


_load_dotenv(BACKEND_DIR / ".env")

# Where the official participant bundle lives (committed to the repo) and
# where it gets extracted at startup.
DATA_ZIP = Path(os.getenv("DATA_ZIP", str(REPO_DIR / "data" / "sdoc-hackathon-bundle.zip")))
DATA_DIR = Path(os.getenv("DATA_DIR", str(BACKEND_DIR / ".data" / "bundle")))
CACHE_DIR = Path(os.getenv("CACHE_DIR", str(BACKEND_DIR / ".cache")))

# AI provider: openai | anthropic | gemini | deepseek | none
AI_PROVIDER = os.getenv("AI_PROVIDER", "none").strip().lower()
AI_API_KEY = os.getenv("AI_API_KEY", "").strip()
AI_MODEL = os.getenv("AI_MODEL", "").strip()
# full = AI classifies emails and judges documents; off = analysis unavailable.
# No rule-based fallback.
AI_MODE = os.getenv("AI_MODE", "full").strip().lower()
AI_TIMEOUT = float(os.getenv("AI_TIMEOUT", "60"))
AI_THINKING = os.getenv('AI_THINKING', 'false').lower() == 'true'
AI_REASONING_EFFORT = os.getenv('AI_REASONING_EFFORT', 'high').strip()
# Optional second model of the SAME provider used when the primary one is overloaded
# (HTTP 429 / 503) or times out. "none" disables the fallback.
AI_FALLBACK_MODEL = os.getenv("AI_FALLBACK_MODEL", "").strip()
AI_FALLBACK_COOLDOWN = float(os.getenv("AI_FALLBACK_COOLDOWN", "60"))   # seconds the primary is rested after an overload
# Requests per minute allowed PER MODEL (free Gemini tier ~15). 0 = no pacing (paid tier).
AI_MAX_RPM = os.getenv("AI_MAX_RPM", "").strip()

# Senior reviews uncertain or unusable primary output once; no key means human handoff.
AI_SENIOR_PROVIDER = os.getenv("AI_SENIOR_PROVIDER", "openai").strip().lower()
AI_SENIOR_API_KEY = os.getenv("AI_SENIOR_API_KEY", "").strip() or (AI_API_KEY if AI_SENIOR_PROVIDER == AI_PROVIDER else "")
AI_SENIOR_MODEL = os.getenv("AI_SENIOR_MODEL", "gpt-6-astra" if AI_SENIOR_PROVIDER == "openai" else "").strip()
AI_SENIOR_FALLBACK_MODEL = os.getenv("AI_SENIOR_FALLBACK_MODEL", "").strip()
AI_SENIOR_MAX_RPM = os.getenv("AI_SENIOR_MAX_RPM", "").strip()
AI_SENIOR_TIMEOUT = float(os.getenv("AI_SENIOR_TIMEOUT", "120"))
AI_SENIOR_THINKING = os.getenv('AI_SENIOR_THINKING', 'false').lower() == 'true'
AI_SENIOR_REASONING_EFFORT = os.getenv('AI_SENIOR_REASONING_EFFORT', 'high').strip()

BATCH_CONCURRENCY = int(os.getenv("BATCH_CONCURRENCY", "4"))
CORS_ORIGINS = [o.strip() for o in os.getenv("CORS_ORIGINS", "*").split(",") if o.strip()]

# standard | strict  (see pipeline.automation_decision)
DEFAULT_POLICY = os.getenv("AUTOMATION_POLICY", "standard").strip().lower()

DEFAULT_MODELS = {
    "deepseek": "deepseek-flash",
    "openai": "gpt-4.1-mini",
    "anthropic": "claude-3-5-haiku-latest",
    "gemini": "gemini-3.8-flash",
}
DEFAULT_FALLBACK_MODELS = {
    "gemini": "gemini-3.5-flash-lite",
}
DEFAULT_MAX_RPM = {
    "gemini": 15.0,
}


def resolved_model() -> str:
    return AI_MODEL or DEFAULT_MODELS.get(AI_PROVIDER, "")


def resolved_fallback_model() -> str:
    if AI_FALLBACK_MODEL.lower() == "none":
        return ""
    fb = AI_FALLBACK_MODEL or DEFAULT_FALLBACK_MODELS.get(AI_PROVIDER, "")
    return "" if fb == resolved_model() else fb


def resolved_max_rpm() -> float:
    try:
        return max(0.0, float(AI_MAX_RPM)) if AI_MAX_RPM else DEFAULT_MAX_RPM.get(AI_PROVIDER, 0.0)
    except ValueError:
        return DEFAULT_MAX_RPM.get(AI_PROVIDER, 0.0)


def senior_max_rpm() -> float:
    default = DEFAULT_MAX_RPM.get(AI_SENIOR_PROVIDER, 0.0) / 3 if AI_SENIOR_MODEL else 0.0
    try:
        return max(0.0, float(AI_SENIOR_MAX_RPM)) if AI_SENIOR_MAX_RPM else default
    except ValueError:
        return default
