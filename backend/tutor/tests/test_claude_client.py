"""Unit tests for the skill-id plumbing in claude_client.py - no API calls
(these exercise the pure, deterministic pieces around the LLM call, per
`_eligible_question_skill_ids`'s own docstring on why it's split out).

Covers two real, confirmed gaps from a prior audit of backend/tutor/:

1. COMPREHENSION_SKILL_IDS used to be a hand-copied 5-of-9 tuple that never
   got updated when content-curator added 4 more comprehension skills to
   content/skill_taxonomy.json (character_traits_and_analysis,
   compare_and_contrast, predicting_outcomes, authors_purpose) - those 4
   could never be tagged on a generated question.
2. None of the 6 vocabulary-category skills had any classification path at
   all anywhere in backend/tutor.
"""

import pytest

from claude_client import (
    COMPREHENSION_SKILL_IDS,
    VOCABULARY_SKILL_IDS,
    TutorLLMClient,
    _eligible_question_skill_ids,
)
from skills import comprehension_skill_ids, taxonomy_skill_ids, vocabulary_skill_ids


def test_comprehension_skill_ids_covers_all_nine_real_taxonomy_skills():
    """The specific regression this audit flagged: these 4 used to be
    missing from the hardcoded tuple even though they're real ids in
    content/skill_taxonomy.json with real passages written for them
    (e.g. content/passages/g1-character-traits-001.json).
    """
    previously_missing = {
        "character_traits_and_analysis",
        "compare_and_contrast",
        "predicting_outcomes",
        "authors_purpose",
    }
    assert previously_missing <= set(COMPREHENSION_SKILL_IDS)
    # And it's exactly the taxonomy's comprehension category - not a
    # hand-maintained list that can drift from it again.
    assert set(COMPREHENSION_SKILL_IDS) == comprehension_skill_ids()
    assert set(COMPREHENSION_SKILL_IDS) <= taxonomy_skill_ids()


def test_vocabulary_skill_ids_covers_all_six_real_taxonomy_skills():
    assert set(VOCABULARY_SKILL_IDS) == vocabulary_skill_ids()
    assert len(VOCABULARY_SKILL_IDS) == 6
    assert "figurative_language" in VOCABULARY_SKILL_IDS
    assert "word_categories" in VOCABULARY_SKILL_IDS


def test_a_previously_unclassifiable_vocabulary_skill_is_now_eligible():
    """This is the concrete proof that a vocabulary skill - e.g.
    figurative_language, exercised by content/passages/
    g3-figurative-language-001.json - can now actually be offered as a
    skill_id for a generated question, where before generate_questions only
    ever offered the 5 (now 9) comprehension ids and nothing else.
    """
    eligible = _eligible_question_skill_ids(["figurative_language", "vocabulary_in_context"])
    assert "figurative_language" in eligible
    assert "vocabulary_in_context" in eligible
    # comprehension ids remain unconditionally eligible too
    assert "literal_comprehension" in eligible


def test_vocabulary_skill_not_declared_by_the_passage_is_not_offered():
    """A vocabulary tag should only ever be grounded in what content-curator
    actually declared this passage exercises (contracts/passage_schema.json
    `skills`) - a passage that never declares figurative_language shouldn't
    have it manufactured as an eligible tag.
    """
    eligible = _eligible_question_skill_ids(["consonant_blends", "short_vowels"])
    assert "figurative_language" not in eligible
    assert "word_categories" not in eligible
    # phonics ids are never offered as a comprehension-question skill_id
    assert "consonant_blends" not in eligible
    assert "short_vowels" not in eligible
    # the comprehension pool is still fully available as a fallback
    assert set(eligible) == set(COMPREHENSION_SKILL_IDS)


def test_no_passage_skills_falls_back_to_full_comprehension_pool():
    assert _eligible_question_skill_ids(None) == list(COMPREHENSION_SKILL_IDS)
    assert _eligible_question_skill_ids([]) == list(COMPREHENSION_SKILL_IDS)


# --------------------------------------------------------------------------- generate_questions skill_id validation


class _FakeTextBlock:
    def __init__(self, text: str) -> None:
        self.type = "text"
        self.text = text


class _FakeMessage:
    def __init__(self, text: str) -> None:
        self.content = [_FakeTextBlock(text)]


@pytest.mark.asyncio
async def test_generate_questions_sanitizes_a_hallucinated_skill_id(monkeypatch):
    """Real, confirmed gap: `generate_questions` only fell back to
    "literal_comprehension" when the LLM's JSON omitted the skill_id key
    entirely - a *present* but hallucinated/off-list skill_id (never a
    member of eligible_skill_ids, the exact set the prompt told the LLM to
    pick from) was trusted as-is and would have flowed straight into
    persisted state (state_machine.py's to_session_columns() ->
    sessions.comprehension jsonb -> backend/mastery's
    student_skill_mastery table, which has a real FK constraint on
    skill_id per contracts/db_schema.sql). Constructs a fake LLM response
    with a made-up skill_id and confirms it gets sanitized to the fallback
    instead of passed through, with zero real API calls.
    """
    client = TutorLLMClient(api_key="fake-key-not-used")

    fake_response_json = (
        '[{"question": "What did the cat do?", '
        '"skill_id": "totally_made_up_skill_id", '
        '"expected_answer_gist": "it sat on the mat"}]'
    )

    async def fake_create(**kwargs):
        return _FakeMessage(fake_response_json)

    monkeypatch.setattr(client._client.messages, "create", fake_create)

    questions = await client.generate_questions(
        passage_text="A cat sat on a mat.", num_questions=1
    )

    assert len(questions) == 1
    assert questions[0].skill_id == "literal_comprehension"
    assert questions[0].skill_id not in ("totally_made_up_skill_id",)


@pytest.mark.asyncio
async def test_generate_questions_keeps_a_valid_eligible_skill_id(monkeypatch):
    """Companion to the sanitization test above: a skill_id that IS in the
    eligible set (here, a vocabulary id explicitly declared by the passage)
    must be passed through untouched, not clobbered by the new validation.
    """
    client = TutorLLMClient(api_key="fake-key-not-used")

    fake_response_json = (
        '[{"question": "What does \\"hopping mad\\" mean here?", '
        '"skill_id": "figurative_language", '
        '"expected_answer_gist": "very angry"}]'
    )

    async def fake_create(**kwargs):
        return _FakeMessage(fake_response_json)

    monkeypatch.setattr(client._client.messages, "create", fake_create)

    questions = await client.generate_questions(
        passage_text="The cat was hopping mad.",
        passage_skills=["figurative_language"],
        num_questions=1,
    )

    assert questions[0].skill_id == "figurative_language"
