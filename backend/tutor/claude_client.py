"""Claude API wrapper for the two LLM touchpoints the tutor state machine
owns: in-the-moment phonics hints (fast tier) and post-passage comprehension
question generation + grading (strong tier).

Owned by `tutor-logic-engineer`. Kept as narrow, single-purpose calls (not a
general chat loop / agent framework) so `state_machine.py` stays a plain,
debuggable state machine per this agent's role brief - the state machine
decides *when* to call these; this module only knows *how*.

`FAST_MODEL` matches `backend/voice/bot.py`'s `FAST_LLM_MODEL` exactly
(same latency/cost tradeoff, already proven live in the Stage 0 checkpoint).
`STRONG_MODEL` is a step up for the grounding-critical/judgment-critical
comprehension calls.
"""

from __future__ import annotations

import json
from dataclasses import dataclass

from anthropic import AsyncAnthropic

FAST_MODEL = "claude-haiku-4-5"  # matches backend/voice/bot.py FAST_LLM_MODEL
STRONG_MODEL = "claude-sonnet-4-5"

HINT_SYSTEM_PROMPT = (
    "You are a warm, patient reading tutor helping a child in grades 1-3 who just "
    "stumbled on a word while reading aloud. Give ONE short spoken hint (max 20 "
    "words, one or two sentences) to help them decode the word themselves - do NOT "
    "just say the word for them. Reference the specific phonics pattern named. "
    "No emojis, asterisks, or other formatting - your reply is read aloud by "
    "text-to-speech."
)

QUESTION_SYSTEM_PROMPT = (
    "You are a reading comprehension question writer for a child in grades 1-3. "
    "You will be given the FULL TEXT of a passage the child just read aloud. Write "
    "comprehension questions using ONLY facts, characters, and events that literally "
    "appear in that text. Never invent plot details, characters, settings, or facts "
    "that are not present in the text. Respond with ONLY a JSON array, no prose "
    "before or after it, no markdown code fences."
)

GRADE_SYSTEM_PROMPT = (
    "You are a warm, encouraging reading tutor grading a child's (grades 1-3) "
    "spoken answer to a comprehension question about a passage they just read. "
    "Judge correctness generously: partial or paraphrased answers that capture the "
    "right idea count as correct. Base your judgment ONLY on the passage text given, "
    "never on outside/prior knowledge. Respond with ONLY a JSON object, no prose "
    "before or after it, no markdown code fences."
)

# Real, explicit request (see docs/BUILD_LOG.md): a fixed silence timeout
# can't tell "the child finished their answer" from "the child paused to
# think," and kids this age pause to think a lot. This judges the
# accumulated transcript-so-far for semantic completeness instead of timing
# silence - state_machine.py's hear_partial_answer calls this once per
# Deepgram-finalized fragment while a comprehension answer is still being
# spoken, and only commits the answer once this says it's actually done.
COMPLETENESS_SYSTEM_PROMPT = (
    "You are listening to a child in grades 1-3 answer a reading comprehension "
    "question out loud. Speech-to-text has captured what they've said SO FAR - "
    "they may have paused and be about to keep talking, or they may be finished. "
    "Judge whether this sounds like a complete, finished answer, or like the "
    "child is still thinking and likely to add more (trails off, ends mid-clause "
    "or mid-word, is just a filler sound like 'um' or 'the', etc). When genuinely "
    "unsure, prefer 'complete' rather than making a child wait who has actually "
    "finished. Respond with ONLY this JSON, no prose, no markdown code fences: "
    '{"complete": true/false}'
)

COMPREHENSION_SKILL_IDS = (
    "literal_comprehension",
    "sequencing",
    "cause_and_effect",
    "inferential_comprehension",
    "main_idea_and_summarizing",
)


@dataclass
class ComprehensionQuestion:
    question: str
    skill_id: str
    # Short grounding note for the grader (e.g. "he skipped breakfast because he
    # overslept") - internal, never shown to the child.
    expected_answer_gist: str


class TutorLLMClient:
    """Thin async wrapper around the Anthropic SDK. Constructed once per
    process/session and handed to `TutorSession`. Tests never construct a
    real one - they pass a fake with the same method signatures, so the
    state machine's control flow is testable with zero API calls.
    """

    def __init__(self, api_key: str | None = None) -> None:
        self._client = AsyncAnthropic(api_key=api_key)

    async def generate_hint(
        self,
        *,
        reference_word: str,
        spoken_word: str,
        skill_id: str,
        skill_label: str,
    ) -> str:
        """Fast-tier call: one short spoken hint for a stumbled word."""
        prompt = (
            f'The child is reading aloud and stumbled on the word "{reference_word}" '
            f'(they said "{spoken_word}"). The phonics skill this word exercises is '
            f'"{skill_label}" ({skill_id}). Give a short spoken hint that helps them '
            "sound it out themselves."
        )
        response = await self._client.messages.create(
            model=FAST_MODEL,
            max_tokens=60,
            system=HINT_SYSTEM_PROMPT,
            messages=[{"role": "user", "content": prompt}],
        )
        return _text_of(response).strip()

    async def generate_questions(
        self,
        *,
        passage_text: str,
        hint_topics: list[str] | None = None,
        num_questions: int = 3,
    ) -> list[ComprehensionQuestion]:
        """Strong-tier call: 2-3 comprehension questions strictly grounded in
        `passage_text`. `hint_topics` (Passage.comprehension_hint_topics) is
        advisory only, per contracts/passage_schema.json - never authoritative
        over what's actually in the text.
        """
        topics_note = (
            f"Topics you may probe if useful (advisory only, do not treat as facts "
            f"beyond what the text says): {', '.join(hint_topics)}.\n"
            if hint_topics
            else ""
        )
        prompt = (
            "PASSAGE TEXT (the only source of truth - do not add anything not in "
            f'here):\n"""\n{passage_text}\n"""\n\n'
            f"{topics_note}"
            f"Write exactly {num_questions} short comprehension questions about this "
            "passage for a grades 1-3 child, mixing literal (directly stated in the "
            "text) and inferential (requires connecting ideas in the text) questions. "
            "For each question pick a skill_id from exactly this set: "
            f"{', '.join(COMPREHENSION_SKILL_IDS)}. "
            'Respond with ONLY a JSON array like: [{"question": "...", '
            '"skill_id": "...", "expected_answer_gist": "..."}]'
        )
        response = await self._client.messages.create(
            model=STRONG_MODEL,
            max_tokens=700,
            system=QUESTION_SYSTEM_PROMPT,
            messages=[{"role": "user", "content": prompt}],
        )
        data = _parse_json_array(_text_of(response))
        return [
            ComprehensionQuestion(
                question=item["question"],
                skill_id=item.get("skill_id", "literal_comprehension"),
                expected_answer_gist=item.get("expected_answer_gist", ""),
            )
            for item in data[:num_questions]
        ]

    async def grade_answer(
        self,
        *,
        passage_text: str,
        question: str,
        expected_answer_gist: str,
        answer_given: str,
    ) -> tuple[bool, str]:
        """Strong-tier call: grade one spoken/typed answer against the passage
        text. Returns (correct, warm_spoken_response).
        """
        prompt = (
            f'PASSAGE TEXT:\n"""\n{passage_text}\n"""\n\n'
            f"QUESTION: {question}\n"
            f"WHAT A GOOD ANSWER TOUCHES ON: {expected_answer_gist}\n"
            f'CHILD\'S ANSWER: "{answer_given}"\n\n'
            "Is the child's answer correct, even if partial or paraphrased, as long "
            "as it captures the right idea from the passage? Respond with ONLY this "
            'JSON: {"correct": true/false, "response": "<one warm, short, age-'
            "appropriate spoken sentence for the child - if correct, celebrate "
            "briefly; if wrong, gently point them back to the passage without just "
            'giving the answer away>"}'
        )
        response = await self._client.messages.create(
            model=STRONG_MODEL,
            max_tokens=150,
            system=GRADE_SYSTEM_PROMPT,
            messages=[{"role": "user", "content": prompt}],
        )
        data = _parse_json_object(_text_of(response))
        return bool(data.get("correct", False)), str(data.get("response", "")).strip()

    async def is_answer_complete(self, *, question: str, partial_answer: str) -> bool:
        """Fast-tier call (same tier as generate_hint - this needs to come back
        quickly since it's judged in the middle of a live pause, not after the
        child is done talking). Returns True on a parse failure, matching the
        prompt's own "when unsure, prefer complete" instruction - a genuinely
        ambiguous case should never leave a finished answer waiting forever.
        """
        prompt = (
            f"QUESTION ASKED: {question}\n"
            f'WHAT THE CHILD HAS SAID SO FAR: "{partial_answer}"\n\n'
            "Is this a complete answer, or does it sound cut off mid-thought?"
        )
        response = await self._client.messages.create(
            model=FAST_MODEL,
            max_tokens=20,
            system=COMPLETENESS_SYSTEM_PROMPT,
            messages=[{"role": "user", "content": prompt}],
        )
        try:
            data = _parse_json_object(_text_of(response))
            return bool(data.get("complete", True))
        except (json.JSONDecodeError, ValueError):
            return True


def _text_of(response) -> str:
    return "".join(block.text for block in response.content if block.type == "text")


def _strip_code_fence(text: str) -> str:
    text = text.strip()
    if text.startswith("```"):
        text = text.split("\n", 1)[1] if "\n" in text else text
        if text.endswith("```"):
            text = text[:-3]
    return text.strip()


def _parse_json_array(text: str) -> list[dict]:
    text = _strip_code_fence(text)
    start, end = text.find("["), text.rfind("]")
    return json.loads(text[start : end + 1])


def _parse_json_object(text: str) -> dict:
    text = _strip_code_fence(text)
    start, end = text.find("{"), text.rfind("}")
    return json.loads(text[start : end + 1])
