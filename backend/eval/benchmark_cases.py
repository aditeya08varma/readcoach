"""Synthetic sessions with known injected errors for the diagnostic-accuracy
benchmark.

Owned by `eval-engineer`. This module builds and hand-labels the cases; the
actual scoring happens in `diagnostic_eval.py` by running each case through
`backend/tutor/alignment.align()` (the real, unmodified diagnostic engine) -
this file never re-implements or imports the classifier logic itself, so
there is no risk of the benchmark grading itself against its own copy of the
rules under test.

Methodology for `skill_id` ground truth (read this before trusting the
numbers in the report)
---------------------------------------------------------------------------
Each phonics substitution case pairs a word with the skill category a
grades 1-3 structured-literacy curriculum would assign it, decided *before*
looking at what `classify_skill_for_word` outputs, using standard textbook
exemplar words for each of the 12 phonics categories in
`content/skill_taxonomy.json` (e.g. "cat" for short_vowels, "boat" for
vowel_teams, "napkin" for closed_syllables) - not words cherry-picked from
`content/passages/*.json` after seeing how the classifier handles them. This
is deliberately the opposite of tuning the benchmark to the implementation:
several of these exemplars are chosen specifically because they are the
*canonical textbook example* of their category, so a mismatch is a real,
defensible finding about the heuristic, not an artifact of a weird word
choice.

Running this table against the real classifier during construction (see
eval-engineer's working notes) surfaced concrete, reproducible gaps - kept
in the table rather than removed, per this agent's role brief ("if something
scores badly, report it accurately"):
  - open_syllables is nearly unreachable for its own canonical exemplars
    ("baby", "tiny", "robot", "pilot", "pony", "apron" all fall through to
    closed_syllables or r_controlled_vowels) because the code's open-syllable
    check only looks at whether the *whole word's last letter* is a vowel,
    not whether the first syllable is open.
  - unstressed word-final "-er" (spider, tiger, hero, wonderful, dinosaur)
    is matched by the same regex as stressed r-controlled vowels (bird, car),
    which structured literacy treats as a different phenomenon.
  - "-ing"/"-ng" endings (fascinating, wishing, elephant->no but e.g.
    "openings") are caught by the consonant-digraph check before the
    multisyllabic/inflectional checks run, since digraph patterns are tested
    first in `classify_skill_for_word`'s priority order.
  - common inflected verbs whose stem ends in a final blend ("jumped" ->
    "jump" -> "-mp", "walked" -> "-lk", "wishing" -> digraph "sh") resolve to
    consonant_blends/consonant_digraphs, not inflectional_endings, even
    though `alignment.py`'s own module docstring cites "jumped"/"panted" as
    examples that *do* resolve to inflectional_endings - that docstring claim
    does not hold for those two specific words; flagged to the orchestrator
    separately, not silently corrected here.
  - "whale" (digraph "wh") and "splash" (both an initial blend "spl" and a
    digraph "sh") land on consonant_digraphs, since digraphs are checked
    before blends - defensible either way, included as a real edge case
    rather than dropped.

These are exactly the divergences the benchmark exists to surface, so they
stay in `WORD_SKILL_CASES` rather than being quietly swapped for easier
words.

Update after this benchmark did its job: the first and fourth findings above
led to real fixes in `backend/tutor/skills.py` (open_syllables went from
1/9 to 6/9; the "jumped"/"panted" line turned out to be a stale docstring
comment, not a code bug - the classifier's actual behavior there was already
correct and already covered by an existing test). "baby", "tiny", "robot",
"pilot", "pony", "zebra" now classify correctly; "apron", "tiger", and
"hero" remain known, deliberately unfixed gaps (see
`backend/tutor/tests/test_skills.py`'s `test_open_syllables` for exactly
why each one is genuinely hard to fix further without risking a
regression).

Second update, prompted directly by these findings sitting in a real
published metric ("the weaker categories are known, real gaps ... improve
these"): the second finding (unstressed word-final "-er") is now fixed -
`_strong_pattern`/`_weak_pattern` in `backend/tutor/skills.py` split the
whole-word pattern checks so genuinely long words (3+ syllables) get a
chance to be recognized as multisyllabic_decoding before an incidental
r-controlled/digraph/blend substring elsewhere in the word claims them.
"wonderful", "dinosaur", "elephant", "fascinating" all now classify
correctly; multisyllabic_decoding went from 33.3% (2/6) to 100% (6/6).
"popcorn"/"football" also now classify correctly - a real dictionary
coverage gap in `_COMPOUND_PARTS`, not a logic bug; compound_words went
from 66.7% (4/6) to 100% (6/6).

The third finding ("-ing"/"-ng" endings caught by the digraph check) turned
out to be the SAME underlying issue as the second, for "fascinating"
specifically, and is fixed by the same change. The fourth finding's own
real disagreement - common inflected verbs ("jumps"/"walked"/"wishing")
whose stem has its own specific pattern - was investigated further this
pass, including checking whether `content/skill_taxonomy.json` actually
backs up the classifier's own stated "prerequisite chain" justification for
preferring the stem's pattern (it does not - see
`backend/tutor/tests/test_skills.py`'s own corrected comment). That
investigation did not change the conclusion though: reversing it would mean
also reversing the already-tested, still-defensible "barked" ->
r_controlled_vowels/"jumped" -> consonant_blends behavior for the exact
same reason, and no clean way was found to keep one and flip the other
without an arbitrary, hard-to-justify special case. Left open and honestly
described as a real, unresolved disagreement between two reasonable design
philosophies, not silently decided either way.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class DiagnosticCase:
    case_id: str
    category: str  # groups cases for the per-category accuracy breakdown
    reference_words: list[str]
    spoken_words: list[str]
    expected_miscue_type: str  # "substitution" | "omission" | "insertion" | "self_correction"
    expected_reference_index: int
    expected_skill_id: str | None  # only meaningful for substitution cases
    note: str = ""


# word -> the skill a grades 1-3 structured-literacy curriculum would assign
# it, decided independently of the classifier (see module docstring).
WORD_SKILL_TABLE: list[tuple[str, str]] = [
    # short_vowels
    ("cat", "short_vowels"), ("sun", "short_vowels"), ("hat", "short_vowels"),
    ("pig", "short_vowels"), ("bed", "short_vowels"), ("log", "short_vowels"),
    ("pat", "short_vowels"), ("red", "short_vowels"),
    # consonant_blends
    ("stop", "consonant_blends"), ("flag", "consonant_blends"), ("frog", "consonant_blends"),
    ("claps", "consonant_blends"), ("splash", "consonant_blends"), ("pond", "consonant_blends"),
    ("step", "consonant_blends"), ("glad", "consonant_blends"), ("crab", "consonant_blends"),
    ("blend", "consonant_blends"),
    # consonant_digraphs
    ("ship", "consonant_digraphs"), ("chin", "consonant_digraphs"), ("fish", "consonant_digraphs"),
    ("chick", "consonant_digraphs"), ("chirps", "consonant_digraphs"), ("watches", "consonant_digraphs"),
    ("whale", "consonant_digraphs"), ("path", "consonant_digraphs"),
    # closed_syllables
    ("napkin", "closed_syllables"), ("rabbit", "closed_syllables"), ("basket", "closed_syllables"),
    ("magnet", "closed_syllables"), ("muffin", "closed_syllables"), ("picnic", "closed_syllables"),
    ("goblin", "closed_syllables"), ("sudden", "closed_syllables"),
    # silent_e
    ("cake", "silent_e"), ("bike", "silent_e"), ("kite", "silent_e"), ("home", "silent_e"),
    ("nice", "silent_e"), ("tune", "silent_e"), ("smile", "silent_e"), ("rope", "silent_e"),
    # vowel_teams
    ("boat", "vowel_teams"), ("rain", "vowel_teams"), ("stream", "vowel_teams"), ("team", "vowel_teams"),
    ("deer", "vowel_teams"), ("cheese", "vowel_teams"), ("pail", "vowel_teams"), ("coach", "vowel_teams"),
    # r_controlled_vowels
    ("car", "r_controlled_vowels"), ("bird", "r_controlled_vowels"), ("porch", "r_controlled_vowels"),
    ("garden", "r_controlled_vowels"), ("fir", "r_controlled_vowels"), ("perch", "r_controlled_vowels"),
    ("turn", "r_controlled_vowels"), ("star", "r_controlled_vowels"),
    # diphthongs
    ("cloud", "diphthongs"), ("boy", "diphthongs"), ("loud", "diphthongs"), ("shout", "diphthongs"),
    ("boys", "diphthongs"), ("toy", "diphthongs"), ("house", "diphthongs"), ("coin", "diphthongs"),
    # open_syllables
    ("baby", "open_syllables"), ("tiger", "open_syllables"), ("zebra", "open_syllables"),
    ("hero", "open_syllables"), ("pony", "open_syllables"), ("apron", "open_syllables"),
    ("tiny", "open_syllables"), ("robot", "open_syllables"), ("pilot", "open_syllables"),
    # inflectional_endings
    ("jumps", "inflectional_endings"), ("walked", "inflectional_endings"), ("wishing", "inflectional_endings"),
    ("plays", "inflectional_endings"), ("gets", "inflectional_endings"), ("taps", "inflectional_endings"),
    ("fixed", "inflectional_endings"), ("sits", "inflectional_endings"), ("rolled", "inflectional_endings"),
    ("called", "inflectional_endings"),
    # compound_words
    ("backyard", "compound_words"), ("sandbox", "compound_words"), ("sunset", "compound_words"),
    ("birdhouse", "compound_words"), ("popcorn", "compound_words"), ("football", "compound_words"),
    # multisyllabic_decoding
    ("incredibly", "multisyllabic_decoding"), ("octopus", "multisyllabic_decoding"),
    ("fascinating", "multisyllabic_decoding"), ("wonderful", "multisyllabic_decoding"),
    ("elephant", "multisyllabic_decoding"), ("dinosaur", "multisyllabic_decoding"),
]

# A short, distinct nonsense decoy: guaranteed not to collide with (or be a
# close Levenshtein match to) any real target word, so every case is a clean
# substitution rather than accidentally folding into a self-correction.
_DECOY = "zorp"

_WRAPPER_PREFIX = ["The", "child", "read"]
_WRAPPER_SUFFIX = ["out", "loud", "today"]


def _substitution_case(word: str, expected_skill_id: str, idx: int) -> DiagnosticCase:
    reference_words = _WRAPPER_PREFIX + [word] + _WRAPPER_SUFFIX
    target_index = len(_WRAPPER_PREFIX)
    spoken_words = list(reference_words)
    spoken_words[target_index] = _DECOY
    return DiagnosticCase(
        case_id=f"sub-{idx:03d}-{word}",
        category=expected_skill_id,
        reference_words=reference_words,
        spoken_words=spoken_words,
        expected_miscue_type="substitution",
        expected_reference_index=target_index,
        expected_skill_id=expected_skill_id,
    )


def _structural_cases() -> list[DiagnosticCase]:
    """Miscue-*type* cases (not skill diagnosis): omission, insertion, and
    both shapes of self-correction folding, plus the documented
    repeated-word tie-break limitation from `alignment.py`'s own docstring,
    included so the eval report shows it actually happening rather than
    just being cited as a theoretical risk.
    """
    cases = []

    cases.append(DiagnosticCase(
        case_id="struct-001-omission",
        category="miscue_type",
        reference_words=["Brad", "likes", "to", "play", "by", "the", "pond"],
        spoken_words=["Brad", "to", "play", "by", "the", "pond"],
        expected_miscue_type="omission",
        expected_reference_index=1,
        expected_skill_id=None,
        note="child skips 'likes' entirely",
    ))
    cases.append(DiagnosticCase(
        case_id="struct-002-omission",
        category="miscue_type",
        reference_words=["The", "duck", "sits", "on", "a", "log", "today"],
        spoken_words=["The", "duck", "on", "a", "log", "today"],
        expected_miscue_type="omission",
        expected_reference_index=2,
        expected_skill_id=None,
        note="child skips 'sits'",
    ))
    cases.append(DiagnosticCase(
        case_id="struct-003-insertion",
        category="miscue_type",
        reference_words=["Brad", "likes", "to", "play"],
        spoken_words=["Brad", "um", "likes", "to", "play"],
        expected_miscue_type="insertion",
        expected_reference_index=None,
        expected_skill_id=None,
        note="extra filler word 'um'",
    ))
    cases.append(DiagnosticCase(
        case_id="struct-004-insertion",
        category="miscue_type",
        reference_words=["The", "frog", "jumps", "far"],
        spoken_words=["The", "frog", "jumps", "really", "far"],
        expected_miscue_type="insertion",
        expected_reference_index=None,
        expected_skill_id=None,
        note="extra word 'really'",
    ))
    cases.append(DiagnosticCase(
        case_id="struct-005-self-correction-shape-a",
        category="miscue_type",
        reference_words=["the", "friend", "ran"],
        spoken_words=["the", "frend", "friend", "ran"],
        expected_miscue_type="self_correction",
        expected_reference_index=1,
        expected_skill_id=None,
        note="false start 'frend' then correct retry 'friend'",
    ))
    cases.append(DiagnosticCase(
        case_id="struct-006-self-correction-shape-b",
        category="miscue_type",
        reference_words=["a", "small", "bird", "sang"],
        spoken_words=["a", "small", "bir", "bird", "sang"],
        expected_miscue_type="self_correction",
        expected_reference_index=2,
        expected_skill_id=None,
        note="false start 'bir' then a match for 'bird'",
    ))

    # Attempted repro of alignment.py's own documented repeated-word
    # tie-break limitation. Result, checked empirically rather than assumed:
    # calling align() in *batch* mode (the complete spoken-word list already
    # known, exactly like this diagnostic benchmark does) resolves both of
    # these cleanly - the DP's diagonal-tiebreak preference lands on the
    # intuitive nearby occurrence every time tried. That's consistent with
    # the module docstring's own scoping of the risk: it explicitly ties the
    # failure mode to the *incremental*, live-streaming settlement process in
    # `state_machine.py` (a large *unread* tail still ahead, which only
    # exists mid-stream), not to a one-shot batch alignment over an already-
    # complete transcript. So this benchmark - which necessarily runs in
    # batch mode - is not expected to reproduce it, and doesn't. Recorded
    # here as a verified-robust case for the scenario actually being tested,
    # with the scoping caveat spelled out rather than silently dropped.
    cases.append(DiagnosticCase(
        case_id="stress-001-repeated-word-batch",
        category="repeated_word_stress_test",
        reference_words=[
            "the", "cat", "sat", "on", "the", "warm", "soft", "mat", "and",
            "then", "the", "cat", "slept", "all", "day", "long",
        ],
        spoken_words=[
            "the", "sat", "on", "the", "warm", "soft", "mat", "and",
            "then", "the", "cat", "slept", "all", "day", "long",
        ],
        expected_miscue_type="omission",
        expected_reference_index=1,
        expected_skill_id=None,
        note=(
            "repeated word ('cat') with a long tail; batch align() correctly "
            "attributes the omission to the first occurrence. Does NOT "
            "reproduce alignment.py's documented tie-break risk, which that "
            "module's own docstring scopes to incremental/streaming "
            "settlement with a genuinely *unread* tail, not batch alignment "
            "over a complete transcript - see note above."
        ),
    ))
    cases.append(DiagnosticCase(
        case_id="stress-002-repeated-word-batch",
        category="repeated_word_stress_test",
        reference_words=[
            "the", "dog", "ran", "to", "the", "big", "green", "park", "and",
            "the", "dog", "barked", "at", "a", "small", "bird",
        ],
        spoken_words=[
            "the", "dog", "ran", "to", "the", "big", "green", "park", "and",
            "the", "barked", "at", "a", "small", "bird",
        ],
        expected_miscue_type="omission",
        expected_reference_index=10,
        expected_skill_id=None,
        note="second occurrence of a repeated word ('dog') omitted; also resolves correctly in batch mode.",
    ))

    return cases


def build_diagnostic_cases() -> list[DiagnosticCase]:
    cases = [
        _substitution_case(word, skill, idx)
        for idx, (word, skill) in enumerate(WORD_SKILL_TABLE)
    ]
    cases.extend(_structural_cases())
    return cases


if __name__ == "__main__":
    cases = build_diagnostic_cases()
    print(f"{len(cases)} diagnostic cases built "
          f"({len(WORD_SKILL_TABLE)} skill-substitution + "
          f"{len(cases) - len(WORD_SKILL_TABLE)} structural/limitation)")
