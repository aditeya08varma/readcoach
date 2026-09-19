"""Unit tests for mastery.compute_direct_skill_scores.

This is the pure, DB-free half of the mastery update rule (no `cur` argument,
no network) - previously the only coverage of this function was
test_scenario.py, a manual end-to-end script against a real/scratch database.
That's exactly why the "unearned clean-read credit for comprehension skills"
bug (see the real regression test below, and mastery.py's own comment at the
fix site) shipped and stayed live: nothing exercised this function in
isolation with a case that would have caught it. A live audit found it by
hand-constructing a session and posting it to a running server; these tests
reproduce the same failure with a plain function call instead.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from mastery import compute_direct_skill_scores  # noqa: E402


def test_phonics_skill_with_no_miscues_gets_clean_read_bonus():
    # A phonics skill tagged on the passage, with zero miscue entries for
    # it at all, is genuine positive evidence (a flawless read of that
    # skill's target words) and should score 1.0 - this is the original,
    # intentional "clean read" fix this function's docstring describes.
    scores = compute_direct_skill_scores(
        miscues=[],
        comprehension=[],
        passage_skill_ids={"short_vowels"},
    )
    assert scores == {"short_vowels": 1.0}


def test_comprehension_skill_never_asked_about_gets_no_unearned_credit():
    # Real, reproduced bug: a passage tagged with a comprehension skill
    # that nobody was even asked a question about this session used to
    # still get a full, unearned 1.0 "clean read" score and a direct
    # mastery bump, purely because it appeared in the passage's `skills`
    # array. Comprehension skills should ONLY ever get a score from an
    # actual answered question (the loop below in the real function),
    # never from silently assuming success like a phonics skill can.
    scores = compute_direct_skill_scores(
        miscues=[],
        comprehension=[],
        passage_skill_ids={"literal_comprehension"},
    )
    assert "literal_comprehension" not in scores


def test_wrong_comprehension_answer_is_not_inflated_by_phantom_credit():
    # Real, reproduced bug: a WRONG answer on a passage-tagged
    # comprehension skill used to get its real 0.0 averaged against a
    # phantom 1.0 from the clean-read fill, inflating it to 0.5. The real
    # score for one wrong answer out of one asked is 0.0, full stop.
    scores = compute_direct_skill_scores(
        miscues=[],
        comprehension=[{"skill_id": "vocabulary_in_context", "correct": False}],
        passage_skill_ids={"vocabulary_in_context"},
    )
    assert scores == {"vocabulary_in_context": 0.0}


def test_mixed_passage_scores_phonics_and_comprehension_independently():
    # A passage tagged with one clean phonics skill and one correctly
    # answered comprehension skill should score each on its own real
    # evidence, with no cross-contamination between the two categories.
    scores = compute_direct_skill_scores(
        miscues=[],
        comprehension=[{"skill_id": "predicting_outcomes", "correct": True}],
        passage_skill_ids={"short_vowels", "predicting_outcomes"},
    )
    assert scores == {"short_vowels": 1.0, "predicting_outcomes": 1.0}


def test_phonics_skill_with_a_real_miscue_is_not_overwritten_by_clean_read_fill():
    # A phonics skill that DID get a miscue this session has real,
    # evidence-based penalized score - the clean-read fill must never
    # clobber that back up to a phantom 1.0 just because it's also in
    # passage_skill_ids.
    scores = compute_direct_skill_scores(
        miscues=[{"skill_id": "short_vowels", "type": "substitution"}],
        comprehension=[],
        passage_skill_ids={"short_vowels"},
    )
    assert scores == {"short_vowels": 0.85}
