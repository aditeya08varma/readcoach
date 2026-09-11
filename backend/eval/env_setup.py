"""Loads the real ANTHROPIC_API_KEY already configured for this project.

No new secrets are created here: `backend/voice/.env` is the existing file
with real keys (Daily/Deepgram/Anthropic/Cartesia) proven working in the
Stage 0 + integration checkpoints per docs/BUILD_LOG.md. This harness only
needs ANTHROPIC_API_KEY (the LLM-judge and the real backend/tutor Claude
calls it drives), so it loads that one .env rather than duplicating it.
"""

from __future__ import annotations

from pathlib import Path

from dotenv import load_dotenv

_VOICE_ENV_PATH = Path(__file__).resolve().parents[1] / "voice" / ".env"


def load_real_api_keys() -> None:
    if _VOICE_ENV_PATH.exists():
        load_dotenv(dotenv_path=_VOICE_ENV_PATH, override=False)
    else:
        # Fall back to whatever's already in the environment / a local .env,
        # e.g. if backend/voice ever moves. Don't fail hard here - the
        # calling script gives a clear error the moment it actually tries an
        # API call with no key.
        load_dotenv(override=False)
