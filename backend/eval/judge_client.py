"""LLM-judge client for question groundedness scoring.

Owned by `eval-engineer`. This is a *new* Claude touchpoint - there is no
existing "is this question grounded" call in `backend/tutor/claude_client.py`
to import - but it deliberately mirrors that module's established pattern
exactly (thin `AsyncAnthropic` wrapper, one narrow-purpose method, plain
system+user prompt, "respond with ONLY JSON" instruction) rather than
inventing a new client shape, per this agent's role brief instruction to
reuse the pattern already established for the LLM touchpoints this pipeline
owns. The response-unwrap helpers (`_text_of`/`_parse_json_object`) used to
be copy-pasted here verbatim from `claude_client.py`; both now import them
from the shared `backend/tutor/llm_parsing.py` module instead (see that
module's own docstring for why it lives there).

Judge model: STRONG_MODEL (imported from backend/tutor/claude_client, same
constant tutor-logic-engineer uses for its own grounding-critical calls -
comprehension question generation and answer grading) - a groundedness
check is exactly that kind of grounding-critical judgment call, so it gets
the same tier, not the fast tier.
"""

from __future__ import annotations

import sys
from dataclasses import dataclass
from pathlib import Path

from anthropic import AsyncAnthropic

_TUTOR_DIR = Path(__file__).resolve().parents[1] / "tutor"
if str(_TUTOR_DIR) not in sys.path:
    sys.path.insert(0, str(_TUTOR_DIR))

from claude_client import STRONG_MODEL  # noqa: E402  (reuse tutor-logic-engineer's model tier constant)
from llm_parsing import parse_json_object as _parse_json_object  # noqa: E402
from llm_parsing import text_of as _text_of  # noqa: E402

JUDGE_SYSTEM_PROMPT = (
    "You are a strict fact-checker for a children's reading-comprehension quiz. "
    "You will be given the FULL TEXT of a passage and one comprehension question "
    "written about it. Your only job is to judge whether the question is "
    "STRICTLY answerable using only facts, characters, and events literally "
    "present in the passage text - not outside knowledge, not a plausible-"
    "sounding inference the text doesn't actually support, and not a detail "
    "that was invented. Literal questions must have their answer stated "
    "directly in the text. Inferential questions must have their answer "
    "logically follow from things the text actually says, with no invented "
    "premise. Be strict: if you would need to guess or assume something not "
    "in the text to answer it, the question is NOT grounded. Respond with "
    "ONLY a JSON object, no prose before or after it, no markdown code fences."
)


@dataclass
class GroundednessVerdict:
    grounded: bool
    reasoning: str


class GroundednessJudge:
    """Constructed once per benchmark run. Tests can substitute a fake with
    the same `judge` method signature, same convention as
    `TutorLLMClient`/`FakeLLMClient` in backend/tutor/tests.
    """

    def __init__(self, api_key: str | None = None) -> None:
        self._client = AsyncAnthropic(api_key=api_key)

    async def judge(self, *, passage_text: str, question: str) -> GroundednessVerdict:
        prompt = (
            f'PASSAGE TEXT:\n"""\n{passage_text}\n"""\n\n'
            f'QUESTION: "{question}"\n\n'
            "Is this question strictly answerable from the passage text alone? "
            'Respond with ONLY this JSON: {"grounded": true/false, "reasoning": '
            '"<one short sentence citing the specific text evidence, or the specific '
            'invented/unsupported detail if not grounded>"}'
        )
        response = await self._client.messages.create(
            model=STRONG_MODEL,
            max_tokens=200,
            system=JUDGE_SYSTEM_PROMPT,
            messages=[{"role": "user", "content": prompt}],
        )
        data = _parse_json_object(_text_of(response))
        return GroundednessVerdict(
            grounded=bool(data.get("grounded", False)),
            reasoning=str(data.get("reasoning", "")).strip(),
        )
