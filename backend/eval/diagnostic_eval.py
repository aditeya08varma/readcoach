"""Runs the synthetic benchmark cases from `benchmark_cases.py` through the
REAL alignment/diagnostic engine (`backend/tutor/alignment.py`,
`backend/tutor/skills.py`) and scores diagnostic accuracy.

No reimplementation: this module imports `align` from `backend/tutor` the
same way `backend/tutor/tests/test_alignment.py` does (sys.path insert, flat
module import, matching that package's "flat scripts, not a package"
convention) and never re-derives miscue classification itself.

No LLM calls here - `alignment.py` is pure stdlib, so this whole eval is
fast and free, which is why the benchmark set is larger (~100 cases) than
the "~30-50" suggested in this agent's role brief: there's no cost reason
not to.
"""

from __future__ import annotations

import sys
from dataclasses import dataclass
from pathlib import Path

_TUTOR_DIR = Path(__file__).resolve().parents[1] / "tutor"
if str(_TUTOR_DIR) not in sys.path:
    sys.path.insert(0, str(_TUTOR_DIR))

from alignment import Miscue, align  # noqa: E402  (import after sys.path patch, matches tutor/tests convention)

from benchmark_cases import DiagnosticCase, build_diagnostic_cases  # noqa: E402


@dataclass
class CaseResult:
    case_id: str
    category: str
    passed: bool
    expected_miscue_type: str
    actual_miscue_type: str | None
    expected_skill_id: str | None
    actual_skill_id: str | None
    note: str


def _find_miscue(miscues: list[Miscue], expected_index: int | None, expected_type: str) -> Miscue | None:
    """Locate the miscue this case is asking about. Substitution/omission/
    self_correction cases key off `reference_index`; insertion cases have no
    reference_index (per contracts/voice_events.md), so key off type + the
    fact there's exactly one in these small hand-built cases.
    """
    if expected_index is not None:
        for m in miscues:
            if m.reference_index == expected_index:
                return m
        return None
    # insertion case: no reference index to match on
    for m in miscues:
        if m.miscue_type.value == expected_type:
            return m
    return None


def score_case(case: DiagnosticCase) -> CaseResult:
    result = align(case.reference_words, case.spoken_words)
    miscue = _find_miscue(result.miscues, case.expected_reference_index, case.expected_miscue_type)

    actual_type = miscue.miscue_type.value if miscue else None
    actual_skill = miscue.skill_id if miscue else None

    type_ok = actual_type == case.expected_miscue_type
    skill_ok = True
    if case.expected_skill_id is not None:
        skill_ok = actual_skill == case.expected_skill_id

    return CaseResult(
        case_id=case.case_id,
        category=case.category,
        passed=type_ok and skill_ok,
        expected_miscue_type=case.expected_miscue_type,
        actual_miscue_type=actual_type,
        expected_skill_id=case.expected_skill_id,
        actual_skill_id=actual_skill,
        note=case.note,
    )


def run_diagnostic_eval() -> dict:
    cases = build_diagnostic_cases()
    results = [score_case(c) for c in cases]

    total = len(results)
    passed = sum(1 for r in results if r.passed)

    by_category: dict[str, dict] = {}
    for r in results:
        bucket = by_category.setdefault(r.category, {"total": 0, "passed": 0, "failures": []})
        bucket["total"] += 1
        bucket["passed"] += int(r.passed)
        if not r.passed:
            bucket["failures"].append({
                "case_id": r.case_id,
                "expected_miscue_type": r.expected_miscue_type,
                "actual_miscue_type": r.actual_miscue_type,
                "expected_skill_id": r.expected_skill_id,
                "actual_skill_id": r.actual_skill_id,
                "note": r.note,
            })
    for bucket in by_category.values():
        bucket["accuracy"] = round(bucket["passed"] / bucket["total"], 4) if bucket["total"] else None

    return {
        "sample_size": total,
        "passed": passed,
        "accuracy": round(passed / total, 4) if total else None,
        "by_category": by_category,
    }


if __name__ == "__main__":
    import json
    print(json.dumps(run_diagnostic_eval(), indent=2))
