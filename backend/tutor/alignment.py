"""Deterministic alignment/miscue-classification engine.

Owned by `tutor-logic-engineer`. No LLM, no network calls - this is a pure
edit-distance diff between a passage's reference `words` array
(`contracts/passage_schema.json`) and the stream of `word_recognized` events
(`contracts/voice_events.md`) Deepgram finalizes as the child reads. It is
the thing that produces `miscue_detected` events and the numbers
(`wcpm`, `accuracy`, `self_corrections`) that go into `passage_complete` and
the `sessions.miscues`/`sessions.wcpm`/`sessions.accuracy` columns
(`contracts/db_schema.sql`).

Kept fully unit-testable: everything here operates on plain strings/dicts,
so a test can hand-write a reference word list and a fake recognized-word
list with known injected errors and assert exact miscue output, with zero
API calls. See `tests/test_alignment.py`.

Algorithm
---------
1. Normalize both word lists (lowercase, strip punctuation) and run a
   standard Wagner-Fischer edit-distance DP over them (cost 0 for an exact
   normalized match, cost 1 for substitute/insert/delete), then trace back
   the lowest-cost path to get a raw sequence of ops: match, substitution,
   omission (reference word with nothing said), insertion (extra spoken
   word with no reference counterpart).
2. Post-process that raw op sequence to fold "false start -> correct retry"
   patterns into `self_correction` instead of counting them as a hard
   error twice, in either shape the DP can produce it:
     a. substitution(ref_i) immediately followed by insertion(word) where
        `word` closely matches ref_i, e.g. child says "fren", then "friend".
        (Already guaranteed to be a real miscue: `substitution` only fires
        when the first word differs from ref_i.)
     b. insertion(word) immediately followed by match(ref_i) where `word`
        is a genuine near-miss of ref_i (NOT identical to it), e.g. child
        says "fr-", then "friend" (which aligns as the correct word for
        ref_i). Deliberately excludes an exact-match "false start": that
        shape is plain word repetition with no actual miscue (e.g. "the the
        dog ran" for reference "the dog ran"), not a self-correction - see
        `_is_uncorrected_miscue_retry`'s docstring for the real bug this
        exclusion fixes.
   "Closely matches"/"near-miss" = exact normalized match (shape a's retry
   only) or a normalized Levenshtein distance of exactly 1 that touches at
   most `MAX_FUZZY_EDIT_RATIO` of the longer word's letters (catches
   near-miss STT transcription of the retry itself, without also catching
   two different short words that happen to be one edit apart - see that
   constant's comment for why the ratio gate is required).

Known limitation: plain edit-distance has no notion of "this word is more
likely to be the SAME occurrence" beyond total cost, so when the reference
has repeated words (e.g. "the", "frog" twice in a short passage) and a large
block of the passage is still unread, two alignments with identical total
cost can exist - one matching the intuitive nearby occurrence, another
matching a later occurrence of the same word and mis-explaining everything
in between. This was previously believed to be rare in practice; a real
recording proved otherwise (see docs/BUILD_LOG.md) - a perfectly correct
read of a real passage got its first word falsely flagged as omitted,
because that word recurred later in the story and, with almost the entire
passage still unread, the DP tied on matching it there instead. Repeated
short/common words this early are the normal case for grade 1-3 writing,
not an edge case, so state_machine.py's incremental caller now bounds how
far into the reference it even lets the aligner look
(INCREMENTAL_REFERENCE_WINDOW) rather than relying on tie-breaking luck -
this function itself is unchanged and still used unbounded for the final,
authoritative end-of-passage score, where the full reference is exactly
what's wanted.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from enum import Enum

from skills import classify_skill_for_word


class MiscueType(str, Enum):
    SUBSTITUTION = "substitution"
    OMISSION = "omission"
    INSERTION = "insertion"
    SELF_CORRECTION = "self_correction"


@dataclass
class Miscue:
    reference_index: int
    reference_word: str
    spoken_word: str | None
    miscue_type: MiscueType
    skill_id: str | None = None
    t: int | None = None  # ms, filled in by the caller from the triggering word_recognized event

    def to_event(self) -> dict:
        """`miscue_detected` event shape per contracts/voice_events.md."""
        return {
            "type": "miscue_detected",
            "t": self.t,
            "reference_index": self.reference_index,
            "reference_word": self.reference_word,
            "spoken_word": self.spoken_word,
            "miscue_type": self.miscue_type.value,
            "skill_id": self.skill_id,
        }


@dataclass
class AlignmentResult:
    miscues: list[Miscue]
    total_reference_words: int
    correct_count: int  # exact matches, not counting self-corrected words
    self_correction_count: int
    substitution_count: int
    omission_count: int
    insertion_count: int
    elapsed_ms: int | None = None
    wcpm: float | None = None
    accuracy: float | None = None


def _normalize(word: str) -> str:
    return re.sub(r"[^a-z']", "", word.lower())


def _levenshtein(a: str, b: str) -> int:
    if a == b:
        return 0
    if not a:
        return len(b)
    if not b:
        return len(a)
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, start=1):
        cur = [i] + [0] * len(b)
        for j, cb in enumerate(b, start=1):
            cost = 0 if ca == cb else 1
            cur[j] = min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + cost)
        prev = cur
    return prev[-1]


# Maximum fraction of the longer word's letters a single-character edit is
# allowed to touch before a Levenshtein distance of 1 is trusted as "the
# same word, slightly misheard/mistranscribed" rather than "a different,
# unrelated word".
#
# Real, confirmed bug: an unqualified `distance <= 1` check is
# length-insensitive, but a single-character edit is not a fixed-size signal
# - it's a fraction of the word, and that fraction swings wildly with word
# length. On a 3-letter word, one edit changes 33% of the letters, which is
# well within the distance between two entirely different short words: CVC
# short-vowel words (cat/bat/hat/mat/sat/rat/fat/pat - per
# content/skill_taxonomy.json, the single most common grade-1 phonics word
# family) are ALL pairwise Levenshtein distance 1 from each other and all
# exactly 3 letters, so any two of them hit this same 33% ratio. Repro that
# motivated this fix: `_closely_matches("hat", "cat")` returned True, so
# `align(["the","cat","sat","on","a","mat"], ["the","hat","cat","sat","on",
# "a","mat"])` folded a stray, unrelated inserted word ("hat") into a false
# self_correction of "cat" - and because `_is_uncorrected_miscue_retry`
# shares this same core check and state_machine.py:355 reuses
# `_closely_matches` directly for end-of-passage review-retry grading, a
# child who missed "cat" and, on retry, said the wrong word "hat" would have
# had that wrong retry marked CORRECT.
#
# A flat higher absolute distance threshold isn't the fix either - it would
# make genuinely-close longer words (e.g. "elephant"/"elephants", distance
# 1) fail to match once the threshold no longer covers them, and a flat
# minimum-length gate of 5 (rejecting any word under 5 letters outright)
# overshoots: it would also reject "fog"/"frog" (3 vs 4 letters, distance 1
# - dropping the blend's "r" is a genuine, common consonant-blend near-miss,
# and tests/test_state_machine.py already has a real, correct
# self-correction test built on exactly this pair). What actually
# distinguishes "same word, one letter off" from "different word" is the
# *fraction* of the word an edit touches, not its absolute count or a flat
# length cutoff. A quarter (25%) is the threshold that draws the line
# exactly where the reported bug needs it drawn: it rejects every 3-letter/
# 3-letter CVC pair (1 edit / 3 letters = 33% > 25%) while still accepting
# "fog"/"frog" (1/4 = 25%, right at the line - a real single-sound edit on a
# real word), "frend"/"friend" (1/6 = 17%), and "elephant"/"elephants"
# (1/9 = 11%).
MAX_FUZZY_EDIT_RATIO = 0.25


def _closely_matches(spoken: str, reference: str) -> bool:
    s, r = _normalize(spoken), _normalize(reference)
    if not s or not r:
        return False
    if s == r:
        return True
    if _levenshtein(s, r) != 1:
        return False
    return (1 / max(len(s), len(r))) <= MAX_FUZZY_EDIT_RATIO


def _is_uncorrected_miscue_retry(spoken: str, reference: str) -> bool:
    """True when `spoken` is a genuine near-miss of `reference` (a real
    misread attempt) but NOT an exact match of it.

    Used only by `_fold_self_corrections` shape b below, where `spoken` is
    an insertion op's word and `reference` is the very next op's (already
    exactly-matched) reference word. A self-correction is, by definition, a
    real miscue that gets caught and fixed - the "false start" half of the
    pattern must itself have actually been wrong. Without excluding the
    exact-match case here, a plain repeated word with no error at all (e.g.
    the child just says "the the dog ran" for reference "the dog ran") was
    misclassified as a self-correction: the insertion "the" trivially
    "closely matches" (exact match) the next match op's reference word
    "the", even though nothing was ever misread. Confirmed via
    align(["the", "dog", "ran"], ["the", "the", "dog", "ran"]), which
    returned self_correction_count=1 before this fix. Shape a doesn't need
    this: its first op is already classified as a `substitution`, which by
    construction only fires when the spoken word differs from the reference
    word, so a real miscue is already guaranteed there.

    Same `MAX_FUZZY_EDIT_RATIO` gate as `_closely_matches` applies to the
    fuzzy (non-exact) branch here too, for the same reason - see that
    constant's comment.
    """
    s, r = _normalize(spoken), _normalize(reference)
    if not s or not r or s == r:
        return False
    if _levenshtein(s, r) != 1:
        return False
    return (1 / max(len(s), len(r))) <= MAX_FUZZY_EDIT_RATIO


# One raw op before self-correction folding.
@dataclass
class _RawOp:
    kind: str  # "match" | "substitution" | "omission" | "insertion"
    ref_index: int | None
    ref_word: str | None
    spoken_word: str | None


def _edit_distance_align(ref_words: list[str], spoken_words: list[str]) -> list[_RawOp]:
    n, m = len(ref_words), len(spoken_words)
    ref_norm = [_normalize(w) for w in ref_words]
    spk_norm = [_normalize(w) for w in spoken_words]

    # dp[i][j] = min edit cost aligning ref[:i] with spoken[:j]
    dp = [[0] * (m + 1) for _ in range(n + 1)]
    for i in range(1, n + 1):
        dp[i][0] = i
    for j in range(1, m + 1):
        dp[0][j] = j
    for i in range(1, n + 1):
        for j in range(1, m + 1):
            match_cost = 0 if ref_norm[i - 1] == spk_norm[j - 1] else 1
            dp[i][j] = min(
                dp[i - 1][j - 1] + match_cost,  # match/substitution
                dp[i - 1][j] + 1,  # omission (ref word not said)
                dp[i][j - 1] + 1,  # insertion (extra spoken word)
            )

    # Traceback, preferring diagonal (match/sub) on ties so we don't
    # manufacture spurious insertion+omission pairs for a plain substitution.
    ops: list[_RawOp] = []
    i, j = n, m
    while i > 0 or j > 0:
        if i > 0 and j > 0:
            match_cost = 0 if ref_norm[i - 1] == spk_norm[j - 1] else 1
            if dp[i][j] == dp[i - 1][j - 1] + match_cost:
                kind = "match" if match_cost == 0 else "substitution"
                ops.append(_RawOp(kind, i - 1, ref_words[i - 1], spoken_words[j - 1]))
                i, j = i - 1, j - 1
                continue
        if i > 0 and dp[i][j] == dp[i - 1][j] + 1:
            ops.append(_RawOp("omission", i - 1, ref_words[i - 1], None))
            i -= 1
            continue
        if j > 0 and dp[i][j] == dp[i][j - 1] + 1:
            ops.append(_RawOp("insertion", None, None, spoken_words[j - 1]))
            j -= 1
            continue
        break  # pragma: no cover - defensive, dp construction guarantees a path
    ops.reverse()
    return ops


def _fold_self_corrections(ops: list[_RawOp]) -> list[_RawOp]:
    """Collapse false-start/retry patterns into self_correction ops.

    See module docstring for the two shapes this handles.
    """
    folded: list[_RawOp] = []
    i = 0
    while i < len(ops):
        op = ops[i]
        nxt = ops[i + 1] if i + 1 < len(ops) else None

        # Shape a: substitution(ref_i) then insertion matching ref_i.
        if (
            op.kind == "substitution"
            and nxt is not None
            and nxt.kind == "insertion"
            and _closely_matches(nxt.spoken_word or "", op.ref_word or "")
        ):
            folded.append(
                _RawOp("self_correction", op.ref_index, op.ref_word, op.spoken_word)
            )
            i += 2
            continue

        # Shape b: insertion (false start) then a match for the same word.
        # Requires the "false start" to be a genuine near-miss of the
        # reference word, NOT an exact repeat of it - see
        # _is_uncorrected_miscue_retry's docstring for the real bug this
        # guards against (plain word repetition with no actual miscue was
        # being folded into a self-correction).
        if (
            op.kind == "insertion"
            and nxt is not None
            and nxt.kind == "match"
            and _is_uncorrected_miscue_retry(op.spoken_word or "", nxt.ref_word or "")
        ):
            folded.append(
                _RawOp("self_correction", nxt.ref_index, nxt.ref_word, op.spoken_word)
            )
            i += 2
            continue

        folded.append(op)
        i += 1
    return folded


def align(
    reference_words: list[str],
    spoken_words: list[str],
) -> AlignmentResult:
    """Diff `reference_words` (passage order) against `spoken_words` (the
    words the child actually said, in the order recognized) and return
    classified miscues plus correctness counts.

    `spoken_words` is plain strings here (the alignment core doesn't need
    timing) - `align_events` below is the timing-aware wrapper used by the
    tutor state machine against real `word_recognized` events.
    """
    raw_ops = _edit_distance_align(reference_words, spoken_words)
    ops = _fold_self_corrections(raw_ops)

    miscues: list[Miscue] = []
    correct = substitutions = omissions = insertions = self_corrections = 0

    for op in ops:
        if op.kind == "match":
            correct += 1
        elif op.kind == "self_correction":
            self_corrections += 1
            miscues.append(
                Miscue(
                    reference_index=op.ref_index,
                    reference_word=op.ref_word,
                    spoken_word=op.spoken_word,
                    miscue_type=MiscueType.SELF_CORRECTION,
                    skill_id=classify_skill_for_word(op.ref_word),
                )
            )
        elif op.kind == "substitution":
            substitutions += 1
            miscues.append(
                Miscue(
                    reference_index=op.ref_index,
                    reference_word=op.ref_word,
                    spoken_word=op.spoken_word,
                    miscue_type=MiscueType.SUBSTITUTION,
                    skill_id=classify_skill_for_word(op.ref_word),
                )
            )
        elif op.kind == "omission":
            omissions += 1
            miscues.append(
                Miscue(
                    reference_index=op.ref_index,
                    reference_word=op.ref_word,
                    spoken_word=None,
                    miscue_type=MiscueType.OMISSION,
                    skill_id=None,
                )
            )
        elif op.kind == "insertion":
            insertions += 1
            miscues.append(
                Miscue(
                    reference_index=None,
                    reference_word=None,
                    spoken_word=op.spoken_word,
                    miscue_type=MiscueType.INSERTION,
                    skill_id=None,
                )
            )

    return AlignmentResult(
        miscues=miscues,
        total_reference_words=len(reference_words),
        correct_count=correct,
        self_correction_count=self_corrections,
        substitution_count=substitutions,
        omission_count=omissions,
        insertion_count=insertions,
    )


def compute_wcpm_and_accuracy(
    result: AlignmentResult, elapsed_ms: int
) -> AlignmentResult:
    """Fill in `wcpm`/`accuracy`/`elapsed_ms` on an AlignmentResult.

    Standard oral-reading-fluency convention (DIBELS-style):
      - correct words = exact matches + self-corrections (a self-correction
        is, by definition, not counted against the child).
      - errors = substitutions + omissions (insertions and self-corrections
        are not counted as errors).
      - accuracy = correct_words / total_reference_words.
      - WCPM = correct_words / elapsed_minutes.
    Split out from `align()` because elapsed time comes from the caller's
    word_recognized timestamps, not from the alignment itself.
    """
    correct_words = result.correct_count + result.self_correction_count
    minutes = max(elapsed_ms, 1) / 60000.0
    result.elapsed_ms = elapsed_ms
    result.wcpm = round(correct_words / minutes, 1)
    result.accuracy = (
        round(correct_words / result.total_reference_words, 4)
        if result.total_reference_words
        else 0.0
    )
    return result


def align_events(
    reference_words: list[str],
    recognized_events: list[dict],
) -> AlignmentResult:
    """Convenience wrapper: align against raw `word_recognized` event dicts
    (contracts/voice_events.md shape) instead of plain strings, and derive
    `elapsed_ms` from the first/last event's timing so wcpm/accuracy are
    filled in automatically.
    """
    spoken_words = [e["word"] for e in recognized_events]
    result = align(reference_words, spoken_words)
    if recognized_events:
        elapsed_ms = recognized_events[-1]["end_ms"] - recognized_events[0]["start_ms"]
    else:
        elapsed_ms = 0
    return compute_wcpm_and_accuracy(result, elapsed_ms)
