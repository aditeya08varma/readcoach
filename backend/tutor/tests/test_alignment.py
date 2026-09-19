"""Unit tests for the deterministic alignment/miscue engine (alignment.py).

Every test hand-writes a reference word list plus a spoken word list with a
known injected error and asserts the exact classified output - no API calls,
no fixtures beyond plain Python lists (some cases pull real passage `words`
arrays from content/passages/*.json purely as realistic reference data, not
because they need the LLM half of the module).
"""

import json
from pathlib import Path

import pytest

from alignment import (
    MiscueType,
    _closely_matches,
    _fold_self_corrections,
    _is_uncorrected_miscue_retry,
    _RawOp,
    align,
    align_events,
    compute_wcpm_and_accuracy,
)

PASSAGES_DIR = Path(__file__).resolve().parents[3] / "content" / "passages"


def _load_passage(passage_id: str) -> dict:
    with open(PASSAGES_DIR / f"{passage_id}.json", encoding="utf-8") as f:
        return json.load(f)


# --------------------------------------------------------------------------- perfect read


def test_perfect_read_has_no_miscues():
    ref = ["Brad", "likes", "to", "play", "by", "the", "pond"]
    result = align(ref, ref)
    assert result.miscues == []
    assert result.correct_count == len(ref)
    assert result.substitution_count == 0
    assert result.omission_count == 0
    assert result.insertion_count == 0
    assert result.self_correction_count == 0


def test_perfect_read_is_case_and_punctuation_insensitive():
    ref = ["The", "frog", "jumps."]
    spoken = ["the", "FROG", "jumps"]
    result = align(ref, spoken)
    assert result.miscues == []
    assert result.correct_count == 3


# --------------------------------------------------------------------------- substitution + skill tagging


def test_substitution_is_classified_and_skill_tagged():
    ref = ["the", "friend", "ran"]
    spoken = ["the", "fren", "ran"]  # "friend" (vowel team "ie") misread as "fren"
    result = align(ref, spoken)
    assert len(result.miscues) == 1
    m = result.miscues[0]
    assert m.miscue_type is MiscueType.SUBSTITUTION
    assert m.reference_index == 1
    assert m.reference_word == "friend"
    assert m.spoken_word == "fren"
    assert m.skill_id == "vowel_teams"
    assert result.correct_count == 2
    assert result.substitution_count == 1


def test_substitution_skill_tag_consonant_blend():
    ref = ["a", "green", "frog", "jumps"]
    spoken = ["a", "green", "fog", "jumps"]  # "frog" (initial blend "fr") -> "fog"
    result = align(ref, spoken)
    assert len(result.miscues) == 1
    assert result.miscues[0].miscue_type is MiscueType.SUBSTITUTION
    assert result.miscues[0].skill_id == "consonant_blends"


def test_substitution_skill_tag_r_controlled():
    ref = ["a", "small", "bird", "sang"]
    spoken = ["a", "small", "bid", "sang"]  # "bird" (r-controlled "ir") -> "bid"
    result = align(ref, spoken)
    assert result.miscues[0].skill_id == "r_controlled_vowels"


# --------------------------------------------------------------------------- omission


def test_omission_when_word_is_skipped():
    ref = ["Brad", "likes", "to", "play"]
    spoken = ["Brad", "to", "play"]  # "likes" skipped entirely
    result = align(ref, spoken)
    assert len(result.miscues) == 1
    m = result.miscues[0]
    assert m.miscue_type is MiscueType.OMISSION
    assert m.reference_index == 1
    assert m.reference_word == "likes"
    assert m.spoken_word is None
    assert m.skill_id is None  # omissions aren't phonics-tagged
    assert result.omission_count == 1
    assert result.correct_count == 3


# --------------------------------------------------------------------------- insertion


def test_insertion_when_extra_word_is_said():
    ref = ["Brad", "likes", "to", "play"]
    spoken = ["Brad", "um", "likes", "to", "play"]  # extra filler word "um"
    result = align(ref, spoken)
    assert len(result.miscues) == 1
    m = result.miscues[0]
    assert m.miscue_type is MiscueType.INSERTION
    assert m.reference_index is None
    assert m.reference_word is None
    assert m.spoken_word == "um"
    assert result.insertion_count == 1
    assert result.correct_count == 4  # the 4 real reference words are all still correct


# --------------------------------------------------------------------------- self-correction


def test_self_correction_false_start_then_correct_retry():
    """Child says a near-miss ("frend"), catches themselves, says the
    correct word right after ("friend"). This is the shape the DP naturally
    produces (insertion-then-match is cheaper than substitution-then-
    insertion whenever the retry is an exact match), so it exercises the
    real align() path end to end, not just the folding helper.
    """
    ref = ["the", "friend", "ran"]
    spoken = ["the", "frend", "friend", "ran"]
    result = align(ref, spoken)
    assert len(result.miscues) == 1
    m = result.miscues[0]
    assert m.miscue_type is MiscueType.SELF_CORRECTION
    assert m.reference_index == 1
    assert m.reference_word == "friend"
    assert m.spoken_word == "frend"  # the false-start attempt is recorded
    assert m.skill_id == "vowel_teams"
    # self-corrections count toward correct words, not substitution errors
    assert result.substitution_count == 0
    assert result.self_correction_count == 1
    assert result.correct_count == 2  # "the" and "ran"


def test_self_correction_does_not_double_count_as_error_in_accuracy():
    ref = ["the", "friend", "ran", "fast"]
    spoken = ["the", "frend", "friend", "ran", "fast"]
    result = align(ref, spoken)
    compute_wcpm_and_accuracy(result, elapsed_ms=4000)
    # correct_words = correct_count(3: the/ran/fast) + self_corrections(1) = 4 / 4 total
    assert result.accuracy == 1.0


def test_plain_word_repetition_is_not_misclassified_as_self_correction():
    """Real, confirmed bug repro: a child who simply repeats a word they
    read correctly the first time ("the the dog ran" for reference "the dog
    ran") has made no miscue at all - there is nothing to "self-correct".
    Before the fix, this exact call returned self_correction_count=1
    because shape b's fold only checked whether the false-start word
    "closely matches" (which includes an exact match) the next match op's
    reference word, without requiring the false start to have actually been
    wrong.
    """
    result = align(["the", "dog", "ran"], ["the", "the", "dog", "ran"])
    assert result.self_correction_count == 0
    assert result.correct_count == 3
    assert result.insertion_count == 1
    assert len(result.miscues) == 1
    assert result.miscues[0].miscue_type is MiscueType.INSERTION
    assert result.miscues[0].spoken_word == "the"


def test_fold_self_corrections_shape_b_does_not_fold_exact_repeat():
    """White-box test of the folding helper directly: an insertion that is
    an EXACT repeat of the very next match's reference word must stay a
    plain insertion, not get folded into a self_correction - see
    `_is_uncorrected_miscue_retry`'s docstring in alignment.py.
    """
    raw_ops = [
        _RawOp("insertion", None, None, "the"),
        _RawOp("match", 0, "the", "the"),
        _RawOp("match", 1, "dog", "dog"),
        _RawOp("match", 2, "ran", "ran"),
    ]
    folded = _fold_self_corrections(raw_ops)
    kinds = [op.kind for op in folded]
    assert kinds == ["insertion", "match", "match", "match"]


def test_fold_self_corrections_shape_a_substitution_then_matching_insertion():
    """White-box test of the folding helper directly for the other shape a
    substitution op can arrive in (substitution immediately followed by an
    insertion that closely matches the same reference word) - constructing
    this scenario as raw ops directly since the full DP prefers the other
    shape (insertion-then-match) whenever the retry is an exact match, per
    the DP's own cost minimization (see module docstring in alignment.py).
    """
    raw_ops = [
        _RawOp("match", 0, "the", "the"),
        _RawOp("substitution", 1, "friend", "fren"),
        _RawOp("insertion", None, None, "friend"),
        _RawOp("match", 2, "ran", "ran"),
    ]
    folded = _fold_self_corrections(raw_ops)
    kinds = [op.kind for op in folded]
    assert kinds == ["match", "self_correction", "match"]
    self_corr = folded[1]
    assert self_corr.ref_index == 1
    assert self_corr.ref_word == "friend"
    assert self_corr.spoken_word == "fren"  # false-start attempt preserved


# --------------------------------------------------------------------------- closely-matches length gate


def test_closely_matches_rejects_unrelated_short_words_one_edit_apart():
    """Real, confirmed bug repro: CVC short-vowel words (cat/bat/hat/mat/
    sat/rat/fat/pat - per content/skill_taxonomy.json, the single most
    common grade-1 phonics word family) are ALL pairwise Levenshtein
    distance 1 from each other, so an unqualified `distance <= 1` check
    treats any two of them as "the same word, slightly misheard" even
    though they're unrelated words. "hat" and "cat" must NOT closely-match.
    """
    assert _closely_matches("hat", "cat") is False
    assert _is_uncorrected_miscue_retry("hat", "cat") is False


def test_closely_matches_accepts_genuine_near_miss_on_a_longer_word():
    """True-positive that must keep working after the length gate: a
    plausible STT mishearing/mistranscription of a longer word (one
    inserted/dropped/swapped letter) is still exactly the case this
    function exists to catch.
    """
    assert _closely_matches("elephant", "elephants") is True
    assert _is_uncorrected_miscue_retry("elephant", "elephants") is True


def test_align_does_not_fold_a_stray_unrelated_short_word_into_self_correction():
    """End-to-end repro of the real bug (not just the unit-level helper): a
    stray, unrelated word ("hat") inserted right before the correct next
    reference word ("cat") must NOT be folded into a false self_correction
    of "cat" just because "hat" and "cat" are one edit apart. This is a
    genuine insertion with no self-correction anywhere in the read.
    """
    ref = ["the", "cat", "sat", "on", "a", "mat"]
    spoken = ["the", "hat", "cat", "sat", "on", "a", "mat"]
    result = align(ref, spoken)
    assert result.self_correction_count == 0
    assert result.insertion_count == 1
    assert result.correct_count == len(ref)
    assert len(result.miscues) == 1
    assert result.miscues[0].miscue_type is MiscueType.INSERTION
    assert result.miscues[0].spoken_word == "hat"


# --------------------------------------------------------------------------- WCPM / accuracy


def test_wcpm_and_accuracy_basic_numbers():
    ref = [f"word{i}" for i in range(10)]
    spoken = list(ref)
    spoken[3] = "wrong"  # one substitution, one error
    result = align(ref, spoken)
    compute_wcpm_and_accuracy(result, elapsed_ms=30_000)  # 30s = 0.5 min
    # 9 correct words / 0.5 min = 18 wcpm
    assert result.wcpm == 18.0
    assert result.accuracy == 0.9


def test_wcpm_zero_elapsed_does_not_divide_by_zero():
    ref = ["one", "two"]
    result = align(ref, ref)
    compute_wcpm_and_accuracy(result, elapsed_ms=0)
    assert result.wcpm is not None  # clamps elapsed to 1ms internally, no crash


def test_align_events_wrapper_derives_elapsed_ms_from_timestamps():
    ref = ["one", "two", "three"]
    events = [
        {"word": "one", "start_ms": 0, "end_ms": 300, "confidence": 0.9},
        {"word": "two", "start_ms": 300, "end_ms": 600, "confidence": 0.9},
        {"word": "three", "start_ms": 600, "end_ms": 6000, "confidence": 0.9},
    ]
    result = align_events(ref, events)
    assert result.elapsed_ms == 6000  # last end_ms - first start_ms
    assert result.wcpm == pytest.approx(30.0)  # 3 correct words / 0.1 min


# --------------------------------------------------------------------------- realistic full-passage transcript


def test_realistic_transcript_against_real_passage_with_mixed_errors():
    """Uses the real g1-blends-001 passage (content/passages/) with a
    hand-labeled transcript containing one of each error type, and checks
    both the miscue list and the resulting wcpm/accuracy.
    """
    passage = _load_passage("g1-blends-001")
    ref = passage["words"]
    assert ref[:7] == ["Brad", "likes", "to", "play", "by", "the", "pond"]
    assert ref[10:12] == ["green", "frog"]
    assert ref[17:21] == ["Brad", "claps", "his", "hands"]

    spoken = list(ref)
    # 1. substitution: "frog" (idx 11) -> "fog" (drops the initial blend)
    spoken[11] = "fog"
    # 2. omission: drop "his" (idx 19) entirely
    del spoken[19]
    # (all subsequent reference indices shift left by one in `spoken` from here,
    #  but align() re-discovers correspondence itself - we don't track that by hand)
    # 3. insertion: add a filler "um" right before the last word
    spoken.insert(len(spoken) - 1, "um")

    result = align(ref, spoken)
    compute_wcpm_and_accuracy(result, elapsed_ms=60_000)  # pretend it took 1 minute

    types = sorted(m.miscue_type.value for m in result.miscues)
    assert types == ["insertion", "omission", "substitution"]

    substitution = next(m for m in result.miscues if m.miscue_type is MiscueType.SUBSTITUTION)
    assert substitution.reference_word == "frog"
    assert substitution.skill_id == "consonant_blends"

    omission = next(m for m in result.miscues if m.miscue_type is MiscueType.OMISSION)
    assert omission.reference_word == "his"

    total = len(ref)
    # correct = total - substitution - omission (insertion/self-correction don't count as errors)
    assert result.correct_count == total - 2
    assert result.accuracy == pytest.approx((total - 2) / total, abs=1e-4)
    assert result.wcpm == pytest.approx((total - 2), abs=1e-6)  # 1 minute elapsed


def test_multiple_real_passages_align_perfectly_against_their_own_words():
    """Sanity check across several real passages: a perfect read of a
    passage's own `words` array must always come back with zero miscues -
    this is the ground truth every live session is measured against.
    """
    for passage_id in [
        "g1-short-vowels-001",
        "g2-vowel-teams-001",
        "g3-multisyllabic-001",
        "g3-compound-words-001",
    ]:
        passage = _load_passage(passage_id)
        result = align(passage["words"], passage["words"])
        assert result.miscues == [], f"{passage_id} should have zero miscues on a perfect read"
        assert result.correct_count == len(passage["words"])
