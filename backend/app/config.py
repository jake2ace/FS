"""Runtime configuration, read from environment variables.

Every secret (AI API key) is read from the environment only. Nothing here is
ever sent to the frontend.
"""
from __future__ import annotations

import os
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parent.parent          # backend/
REPO_DIR = BACKEND_DIR.parent                                  # repository root

# Where the official participant bundle lives (committed to the repo) and
# where it gets extracted at startup.
DATA_ZIP = Path(os.getenv("DATA_ZIP", str(REPO_DIR / "data" / "sdoc-hackathon-bundle.zip")))
DATA_DIR = Path(os.getenv("DATA_DIR", str(BACKEND_DIR / ".data" / "bundle")))
CACHE_DIR = Path(os.getenv("CACHE_DIR", str(BACKEND_DIR / ".cache")))

# AI provider: openai | anthropic | gemini | none
AI_PROVIDER = os.getenv("AI_PROVIDER", "none").strip().lower()
AI_API_KEY = os.getenv("AI_API_KEY", "").strip()
AI_MODEL = os.getenv("AI_MODEL", "").strip()
# full   = AI classifies every email and extracts every document (rules cross-check)
# assist = AI only when the rule engine is not confident
# off    = rules only
AI_MODE = os.getenv("AI_MODE", "full").strip().lower()
AI_TIMEOUT = float(os.getenv("AI_TIMEOUT", "60"))

BATCH_CONCURRENCY = int(os.getenv("BATCH_CONCURRENCY", "4"))
CORS_ORIGINS = [o.strip() for o in os.getenv("CORS_ORIGINS", "*").split(",") if o.strip()]

# standard | strict  (see pipeline.automation_decision)
DEFAULT_POLICY = os.getenv("AUTOMATION_POLICY", "standard").strip().lower()

DEFAULT_MODELS = {
    "openai": "gpt-4.1-mini",
    "anthropic": "claude-3-5-haiku-latest",
    "gemini": "gemini-2.5-flash",
}


def resolved_model() -> str:
    return AI_MODEL or DEFAULT_MODELS.get(AI_PROVIDER, "")
