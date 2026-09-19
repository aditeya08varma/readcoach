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

from llm_parsing import parse_json_array as _parse_json_array
from llm_parsing import parse_json_object as _parse_json_object
from llm_parsing import text_of as _text_of
from skills import comprehension_skill_ids, vocabulary_skill_ids

FAST_MODEL = "claude-haiku-4-5"  # matches backend/voice/bot.py FAST_LLM_MODEL
STRONG_MODEL = "claude-sonnet-4-5"

# Real gap found in review: bare `AsyncAnthropic()` defaults to a 10-minute
# request timeout (5s connect / no read timeout beyond that) and 2 retries
# with exponential backoff - fine for a batch job, not for a live
# conversation where the child is sitting in silence waiting for a hint or a
# grading result. REQUEST_TIMEOUT_SECONDS fails a hung request fast enough
# to still feel responsive; MAX_RETRIES=1 keeps the SDK's own well-tested
# retry policy (it already retries exactly on timeouts, connection errors,
# and 408/409/429/5xx - see anthropic._base_client._should_retry) but caps
# it at one extra attempt instead of two, so a genuinely down API fails back
# to the caller (state_machine.py, which lets the exception surface all the
# way to tutor_processor.py's ErrorFrame handling) in well under the
# pipeline's own patience budget instead of retrying twice on top of two
# separate 15s timeouts. Configuring the SDK's own client this way - rather
# than hand-rolling a retry loop around every `messages.create` call below -
# is the small, direct fix this scope calls for; a bespoke retry framework
# would just be reimplementing what `max_retries` already does correctly.
REQUEST_TIMEOUT_SECONDS = 18.0
MAX_RETRIES = 1

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

# Derived live from content/skill_taxonomy.json's own "category" field
# (via skills.py) instead of a hand-copied tuple - a hand-copied list is
# exactly what caused a real, confirmed bug: this used to be a fixed 5-id
# tuple ("literal_comprehension", "sequencing", "cause_and_effect",
# "inferential_comprehension", "main_idea_and_summarizing") that silently
# went stale when content-curator later added 4 more comprehension skills
# (character_traits_and_analysis, compare_and_contrast, predicting_outcomes,
# authors_purpose) to the taxonomy - those 4 had passages written for them
# (see content/passages/g1-character-traits-001.json etc.) but could never
# actually be tagged on a generated question, so their mastery could never
# update. Deriving this from the taxonomy at import time means a future
# taxonomy addition can't reintroduce the same gap.
COMPREHENSION_SKILL_IDS = tuple(sorted(comprehension_skill_ids()))

# The 6 vocabulary-category skills (word_categories, synonyms_and_antonyms,
# multiple_meaning_words, prefixes_and_suffixes_meaning, vocabulary_in_context,
# figurative_language) had NO classification path anywhere in backend/tutor -
# skills.py's classify_skill_for_word is explicitly phonics-only (rule-based
# letter-pattern matching against a misread reference word), and there is no
# live "phonetic miscue" a child can make that signals "this child doesn't
# know what a synonym is" or "doesn't recognize this idiom" the way mispronouncing
# "friend" signals a vowel-team miss. Vocabulary understanding is a
# comprehension-of-meaning question, not a decoding-accuracy one, so it fits
# naturally into the SAME comprehension question/answer mechanism already
# used for literal/inferential/etc. skills (generate_questions below ->
# ComprehensionQuestion.skill_id -> state_machine.py's GradedTurn ->
# `sessions.comprehension` jsonb, per contracts/db_schema.sql) rather than a
# separate live-miscue detector bolted onto alignment.py, which has no
# concept of "meaning" at all - only string edit-distance.
#
# Only used to filter which vocabulary ids are ever offered to the LLM as a
# skill_id choice (see generate_questions): content-curator's own
# `passage["skills"]` declares which specific vocabulary skill(s) a given
# passage actually exercises (contracts/passage_schema.json), so a vocabulary
# tag is only ever grounded in something the passage was curated to teach -
# e.g. g3-figurative-language-001.json declares "figurative_language", so a
# question about that passage can be tagged with it, but a plain phonics
# passage with no vocabulary skill declared never gets an ungrounded
# vocabulary tag manufactured for it. Comprehension skill types
# (literal/inferential/sequencing/...) stay unconditionally eligible for
# every passage, matching existing (tested) behavior, because they're
# generic question-style categories applicable to any passage regardless of
# what's declared, unlike a specific vocabulary feature that must actually
# be present in the text to ask about honestly.
VOCABULARY_SKILL_IDS = tuple(sorted(vocabulary_skill_ids()))


@dataclass
class ComprehensionQuestion:
    question: str
    skill_id: str
    # Short grounding note for the grader (e.g. "he skipped breakfast because he
    # overslept") - internal, never shown to the child.
    expected_answer_gist: str


def _eligible_question_skill_ids(passage_skills: list[str] | None) -> list[str]:
    """The skill ids `generate_questions` is allowed to tag a question with
    for a given passage: every comprehension-category id (always eligible,
    see VOCABULARY_SKILL_IDS's module comment for why) plus whichever of
    `passage_skills` (the passage's own declared `skills` array) are
    vocabulary-category ids. Pure/deterministic and API-free on purpose, so
    the eligibility logic itself is unit-testable without mocking the
    Anthropic client - see tests/test_claude_client.py.
    """
    vocab_eligible = [s for s in (passage_skills or []) if s in VOCABULARY_SKILL_IDS]
    return list(COMPREHENSION_SKILL_IDS) + vocab_eligible


class TutorLLMClient:
    """Thin async wrapper around the Anthropic SDK. Constructed once per
    process/session and handed to `TutorSession`. Tests never construct a
    real one - they pass a fake with the same method signatures, so the
    state machine's control flow is testable with zero API calls.
    """

    def __init__(self, api_key: str | None = None) -> None:
        self._client = AsyncAnthropic(
            api_key=api_key,
            timeout=REQUEST_TIMEOUT_SECONDS,
            max_retries=MAX_RETRIES,
        )

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
        passage_skills: list[str] | None = None,
        num_questions: int = 3,
    ) -> list[ComprehensionQuestion]:
        """Strong-tier call: 2-3 comprehension questions strictly grounded in
        `passage_text`. `hint_topics` (Passage.comprehension_hint_topics) is
        advisory only, per contracts/passage_schema.json - never authoritative
        over what's actually in the text.

        `passage_skills` is the passage's full `skills` array (contracts/
        passage_schema.json) - see `_eligible_question_skill_ids` for how
        this is used to also let a question be tagged with one of the
        passage's own declared vocabulary skills, not just a comprehension
        one (see VOCABULARY_SKILL_IDS's module comment for why vocabulary
        rides this same mechanism instead of a separate detector).
        """
        eligible_skill_ids = _eligible_question_skill_ids(passage_skills)
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
            f"{', '.join(eligible_skill_ids)}. "
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
        eligible_skill_ids_set = set(eligible_skill_ids)
        questions = []
        for item in data[:num_questions]:
            # Real, confirmed gap: this used to fall back to
            # "literal_comprehension" only when the LLM's JSON omitted the
            # skill_id key entirely - a *present* but hallucinated/off-list
            # value (never a member of eligible_skill_ids, the exact set the
            # prompt just told the LLM to pick from) was trusted as-is. That
            # value flows straight into persisted state
            # (state_machine.py's to_session_columns() -> sessions.comprehension
            # jsonb -> backend/mastery's student_skill_mastery table, which
            # has a real FK constraint on skill_id per contracts/db_schema.sql),
            # so an off-list id wouldn't just be a bad tag, it could fail
            # that FK write outright. Validate against the same eligible set
            # the prompt was given, not just "is the key present".
            skill_id = item.get("skill_id", "literal_comprehension")
            if skill_id not in eligible_skill_ids_set:
                skill_id = "literal_comprehension"
            questions.append(
                ComprehensionQuestion(
                    question=item["question"],
                    skill_id=skill_id,
                    expected_answer_gist=item.get("expected_answer_gist", ""),
                )
            )
        return questions

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
