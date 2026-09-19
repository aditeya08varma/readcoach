"""Makes `backend/voice`'s flat modules (voice_events, mastery_client,
tutor_processor, bot) importable from the tests directory, matching the same
flat-script-not-package convention `backend/tutor/tests/conftest.py` uses.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
