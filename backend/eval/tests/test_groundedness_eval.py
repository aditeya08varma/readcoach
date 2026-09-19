"""Unit tests for `groundedness_eval.aggregate_per_passage_results()` - the
pure aggregation math (groundedness ratio, skill-tagging accuracy, and the
ungrounded/missed-tag example lists) that runs over already-scored
per-passage results. No API calls: the fixtures below are plain dicts
shaped exactly like `_score_one_passage`'s real return value, so this
exercises the real aggregation logic without needing a live Claude call.

Per an audit finding that the eval harness had zero unit test coverage of
its own logic, despite this being the one piece of real, pure, easily
mocked logic in `groundedness_eval.py` worth covering directly.
"""

from groundedness_eval import aggregate_per_passage_results


def _question(skill_id: str, grounded: bool, reasoning: str = "because reasons") -> dict:
    return {
        "question": f"A question tagged {skill_id}?",
        "skill_id": skill_id,
        "grounded": grounded,
        "judge_reasoning": reasoning,
    }


def _passage(
    passage_id: str,
    primary_skill: str,
    questions: list[dict],
    skill_check_applicable: bool,
    skill_gap_identified: bool | None,
) -> dict:
    return {
        "passage_id": passage_id,
        "primary_skill": primary_skill,
        "questions": questions,
        "grounded_count": sum(1 for q in questions if q["grounded"]),
        "total_count": len(questions),
        "skill_check_applicable": skill_check_applicable,
        "skill_gap_identified": skill_gap_identified,
    }


def test_all_grounded_all_skill_matches_scores_perfect():
    per_passage = [
        _passage(
            "p1", "literal_comprehension",
            [_question("literal_comprehension", True), _question("literal_comprehension", True)],
            skill_check_applicable=True, skill_gap_identified=True,
        ),
        _passage(
            "p2", "sequencing",
            [_question("sequencing", True)],
            skill_check_applicable=True, skill_gap_identified=True,
        ),
    ]
    result = aggregate_per_passage_results(per_passage)

    assert result["total_questions"] == 3
    assert result["grounded_count"] == 3
    assert result["groundedness"] == 1.0
    assert result["ungrounded_examples"] == []
    assert result["skill_tagging_accuracy"] == 1.0
    assert result["skill_tagging_matches"] == 2
    assert result["skill_tagging_checkable"] == 2
    assert result["skill_tagging_misses"] == []


def test_ungrounded_question_is_reported_with_passage_id_and_reasoning():
    per_passage = [
        _passage(
            "g3-inferential-001", "inferential_comprehension",
            [
                _question("inferential_comprehension", True),
                _question("inferential_comprehension", False, reasoning="invents a motive not in the text"),
            ],
            skill_check_applicable=True, skill_gap_identified=True,
        ),
    ]
    result = aggregate_per_passage_results(per_passage)

    assert result["total_questions"] == 2
    assert result["grounded_count"] == 1
    assert result["groundedness"] == 0.5
    assert len(result["ungrounded_examples"]) == 1
    ex = result["ungrounded_examples"][0]
    assert ex["passage_id"] == "g3-inferential-001"
    assert ex["grounded"] is False
    assert ex["judge_reasoning"] == "invents a motive not in the text"


def test_phonics_passages_are_excluded_from_skill_tagging_denominator():
    """A phonics-primary passage's `skill_check_applicable` is False (see
    groundedness_eval.py's module docstring: comparing its primary_skill
    against a comprehension skill_id would be a category error) - it must
    not be counted in `skill_tagging_checkable` at all, matched or missed.
    """
    per_passage = [
        _passage(
            "g1-short-vowels-001", "short_vowels",
            [_question("literal_comprehension", True)],
            skill_check_applicable=False, skill_gap_identified=None,
        ),
        _passage(
            "g2-vocab-context-001", "vocabulary_in_context",
            [_question("vocabulary_in_context", True)],
            skill_check_applicable=True, skill_gap_identified=True,
        ),
    ]
    result = aggregate_per_passage_results(per_passage)

    assert result["skill_tagging_checkable"] == 1
    assert result["skill_tagging_matches"] == 1
    assert result["skill_tagging_accuracy"] == 1.0


def test_missed_skill_tag_reports_expected_and_actual_tags():
    per_passage = [
        _passage(
            "g1-word-categories-001", "word_categories",
            [_question("literal_comprehension", True), _question("cause_and_effect", True)],
            skill_check_applicable=True, skill_gap_identified=False,
        ),
    ]
    result = aggregate_per_passage_results(per_passage)

    assert result["skill_tagging_accuracy"] == 0.0
    assert result["skill_tagging_matches"] == 0
    assert result["skill_tagging_misses"] == [
        {
            "passage_id": "g1-word-categories-001",
            "expected_skill_id": "word_categories",
            "tagged_skill_ids": ["cause_and_effect", "literal_comprehension"],
        }
    ]


def test_no_checkable_passages_gives_none_not_a_crash():
    """All-phonics sample: skill_tagging_accuracy should be None (n/a), not
    a ZeroDivisionError.
    """
    per_passage = [
        _passage(
            "g1-blends-001", "consonant_blends",
            [_question("literal_comprehension", True)],
            skill_check_applicable=False, skill_gap_identified=None,
        ),
    ]
    result = aggregate_per_passage_results(per_passage)

    assert result["skill_tagging_checkable"] == 0
    assert result["skill_tagging_accuracy"] is None
    assert result["skill_tagging_misses"] == []


def test_zero_questions_gives_none_groundedness_not_a_crash():
    result = aggregate_per_passage_results([])
    assert result["total_questions"] == 0
    assert result["groundedness"] is None
    assert result["ungrounded_examples"] == []
