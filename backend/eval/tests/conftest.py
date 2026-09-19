"""Makes `backend/eval`'s flat modules (report, groundedness_eval,
diagnostic_eval, latency_eval, judge_client, benchmark_cases, env_setup)
importable from the tests directory, matching the same flat-script-not-
package convention `backend/tutor/tests/conftest.py` already uses for
`backend/tutor`.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
