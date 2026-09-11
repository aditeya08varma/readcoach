"""Makes `backend/tutor`'s flat modules (alignment, skills, events,
state_machine, claude_client) importable from the tests directory,
matching the same flat-script-not-package convention `backend/voice` uses.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
