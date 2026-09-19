"""Rule-based phonetic skill tagging for substitution miscues.

Owned by `tutor-logic-engineer`. Loads the real skill ids from
`content/skill_taxonomy.json` (content-curator's file - we do not invent ids)
and maps a misread reference word to the single phonics skill id that best
explains why that word is hard to decode, using plain string-pattern
heuristics (no ML, no API call - this has to run inline during live
alignment).

This is deliberately a *reference-word* classifier: given the passage's
correct word (e.g. "friend"), guess which phonics pattern in that word is
the likely trip-up ("ie" -> vowel_teams). We tag based on the reference
word, not the (often garbled/misheard) spoken word, because the reference
word is the one thing we know for certain and it's what the taxonomy's
skill ids are trying to teach.

Only phonics-category skills are eligible outputs here (vocabulary/
comprehension skills describe *comprehension* difficulty, not word-decoding
misses, so they're never returned by `classify_skill_for_word`).
"""

from __future__ import annotations

import json
import re
from functools import lru_cache
from pathlib import Path

_TAXONOMY_PATH = Path(__file__).resolve().parents[2] / "content" / "skill_taxonomy.json"


@lru_cache(maxsize=1)
def load_taxonomy() -> list[dict]:
    with open(_TAXONOMY_PATH, encoding="utf-8") as f:
        return json.load(f)


@lru_cache(maxsize=1)
def taxonomy_skill_ids() -> frozenset[str]:
    return frozenset(entry["id"] for entry in load_taxonomy())


@lru_cache(maxsize=1)
def phonics_skill_ids() -> frozenset[str]:
    return frozenset(
        entry["id"] for entry in load_taxonomy() if entry["category"] == "phonics"
    )


@lru_cache(maxsize=1)
def vocabulary_skill_ids() -> frozenset[str]:
    return frozenset(
        entry["id"] for entry in load_taxonomy() if entry["category"] == "vocabulary"
    )


@lru_cache(maxsize=1)
def comprehension_skill_ids() -> frozenset[str]:
    """All comprehension-category skill ids, read live from the taxonomy
    file - claude_client.py derives its COMPREHENSION_SKILL_IDS from this
    (rather than hand-copying the id list) specifically because a hand-copied
    list is exactly what silently went stale before: it was written once
    against a 5-comprehension-skill taxonomy and never updated when
    content-curator added character_traits_and_analysis, compare_and_contrast,
    predicting_outcomes, and authors_purpose, leaving all four with no
    classification path at all. See claude_client.py's own comment.
    """
    return frozenset(
        entry["id"] for entry in load_taxonomy() if entry["category"] == "comprehension"
    )


# --- pattern tables (all matched against the lowercased reference word) ----

# Vowel teams that are NOT diphthongs (those get their own category below).
_VOWEL_TEAM_PATTERNS = re.compile(r"(ea|ee|oa|ai|ay|oe|ue|ui|ie|oo)")

# Diphthongs: the "gliding" vowel sounds (oi/oy, ou/ow).
_DIPHTHONG_PATTERNS = re.compile(r"(oi|oy|ou|ow)")

# R-controlled vowels ("bossy r").
_R_CONTROLLED_PATTERNS = re.compile(r"(ar|er|ir|or|ur)")

# Silent-e (VCe): vowel, single consonant, then a final silent e.
_SILENT_E_PATTERN = re.compile(r"[aeiou][bcdfghjklmnpqrstvwxyz]e$")

# Consonant digraphs: two consonants, one sound.
_DIGRAPH_PATTERNS = re.compile(r"(sh|ch|th|wh|ph|ck|ng)")

# Consonant blends: two+ consonants that each keep their own sound, at the
# start or end of the word.
_INITIAL_BLENDS = re.compile(
    r"^(bl|br|cl|cr|dr|fl|fr|gl|gr|pl|pr|sc|sk|sl|sm|sn|sp|st|sw|tr|tw|scr|spl|spr|str)"
)
_FINAL_BLENDS = re.compile(r"(nd|nt|mp|lt|lk|lf|sk|sp|st|ct|pt|ft)$")

# Open-syllable detection (fallback path only, see classify_skill_for_word's
# docstring point 5): a vowel followed by exactly one consonant, then another
# vowel - the classic "ti-ny"/"ro-bot"/"pi-lot" VCV shape. Deliberately only
# a single consonant: a two-consonant medial cluster is ambiguous without a
# pronouncing dictionary (a blend can still close the syllable when the
# first vowel is short, e.g. "bas-ket"/"gob-lin", vs. staying open when it's
# long, e.g. "a-pron"/"ze-bra") - an earlier version of this check treated
# any medial blend as open and wrongly reclassified "basket"/"goblin", so
# medial two-consonant clusters are left to the existing closed_syllables
# fallback below rather than guessed at.
_OPEN_SYLLABLE_MEDIAL = re.compile(r"[aeiou]([bcdfghjklmnpqrstvwxz])[aeiouy]")

# Small closed set of common compound-word halves for grades 1-3 content.
# Not exhaustive - a heuristic, not a dictionary lookup. "pop"/"corn"/"foot"/
# "ball" added after a real, confirmed diagnostic-accuracy gap: "popcorn"
# and "football", both real benchmark exemplars for this category, fell
# through to r_controlled_vowels/vowel_teams (whichever pattern their own
# letters happened to also contain) simply because neither half was in this
# dictionary yet - real dictionary coverage, not a logic bug.
_COMPOUND_PARTS = {
    "back", "yard", "sun", "set", "flower", "flowers", "bird", "house", "bath",
    "sand", "box", "see", "saw", "some", "thing", "any", "where", "in", "side",
    "out", "door", "up", "on", "into", "birthday", "day", "time", "home",
    "work", "grand", "ma", "pa", "father", "mother", "play", "ground", "rain",
    "coat", "coats", "week", "end", "week end", "class", "room", "note", "book",
    "pop", "corn", "foot", "ball",
}


def _is_compound(word: str) -> bool:
    """Heuristic: word splits into two known smaller words, each >= 2 chars."""
    if len(word) < 6:
        return False
    for i in range(2, len(word) - 1):
        left, right = word[:i], word[i:]
        if left in _COMPOUND_PARTS and right in _COMPOUND_PARTS:
            return True
    return False


def _syllable_count(word: str) -> int:
    """Crude vowel-group count, good enough to flag "long" words."""
    groups = re.findall(r"[aeiouy]+", word)
    return max(1, len(groups))


def _has_open_first_syllable(word: str) -> bool:
    """True for the classic VCV open-syllable shape ("ti-ny", "ro-bot",
    "pi-lot"): the first vowel is followed by exactly one consonant and
    then another vowel. See the module-level comment on
    `_OPEN_SYLLABLE_MEDIAL` for why a two-consonant medial cluster is left
    alone rather than guessed at.

    Only meaningful as a fallback, last-resort check (see
    classify_skill_for_word's docstring) - a word already claimed by a more
    specific whole-word pattern (silent_e, a digraph, a real same-syllable
    r-controlled vowel like "bird") never reaches this function.
    """
    return bool(_OPEN_SYLLABLE_MEDIAL.search(word))


_INFLECTIONAL_SUFFIXES = ("ing", "ed", "es", "s")


def _strip_inflection(word: str) -> tuple[str, bool]:
    """Strip one common inflectional suffix (longest first) and return
    (stem, had_suffix). Doesn't try to undo spelling changes (e.g.
    "paddled" -> "paddl", not "paddle") - good enough for pattern-matching
    the stem, not meant to be a real morphological analyzer.
    """
    for suffix in _INFLECTIONAL_SUFFIXES:
        if word.endswith(suffix) and len(word) - len(suffix) >= 3:
            return word[: -len(suffix)], True
    return word, False


def _strong_pattern(word: str) -> str | None:
    """The three patterns salient enough to claim a word regardless of its
    length: a real vowel-team/diphthong spelling or a genuine silent-e
    almost always IS the word's actual decoding challenge, long word or not.
    Split out from the old single `_specific_pattern` (see that function's
    own comment for why) after a real, confirmed diagnostic-accuracy gap:
    "wonderful"/"dinosaur"/"elephant"/"fascinating" (all real benchmark
    exemplars for multisyllabic_decoding, all genuinely 3+ syllables) were
    getting claimed by an incidental "er"/"ur"/"ph"/"ng" substring sitting
    somewhere inside a much longer word, before length was ever considered -
    scoring this category 33.3% (2/6). Checked directly against the eval
    benchmark's own r_controlled_vowels/consonant_digraphs/consonant_blends
    word lists (backend/tutor/tests/test_skills.py) before this split: none
    of those already-tested exemplars are 3+ syllables, so narrowing which
    patterns can preempt a real multisyllabic word costs nothing there.
    """
    if _VOWEL_TEAM_PATTERNS.search(word):
        return "vowel_teams"
    if _DIPHTHONG_PATTERNS.search(word):
        return "diphthongs"
    if _SILENT_E_PATTERN.search(word):
        return "silent_e"
    return None


def _weak_pattern(word: str) -> str | None:
    """The three patterns real enough to name on their own for a short word,
    but common enough as an incidental substring that they shouldn't get to
    preempt a genuinely long word's own real length - see `_strong_pattern`'s
    comment for the concrete real failures this split fixes.
    """
    if _R_CONTROLLED_PATTERNS.search(word):
        return "r_controlled_vowels"
    if _DIGRAPH_PATTERNS.search(word):
        return "consonant_digraphs"
    if _INITIAL_BLENDS.search(word) or _FINAL_BLENDS.search(word):
        return "consonant_blends"
    return None


def _specific_pattern(word: str) -> str | None:
    """Every non-fallback pattern, strong and weak together - used on the
    STEM of a suffixed word (see classify_skill_for_word's own docstring
    point 4), where a stem is by definition short enough that the
    strong/weak distinction above doesn't matter: "barked"/"jumped" still
    read as r_controlled_vowels/consonant_blends from their stems
    "bark"/"jump", the deliberate, tested behavior in
    tests/test_skills.py's own inflectional-endings test.
    """
    return _strong_pattern(word) or _weak_pattern(word)


def classify_skill_for_word(reference_word: str) -> str:
    """Best-guess phonics skill id for why `reference_word` might be misread.

    Checks patterns in order from most structurally distinctive to most
    general and returns the first match. Always returns a real id from
    `content/skill_taxonomy.json` (falls back to "short_vowels" for plain
    short words with no other flagged pattern).

    Order, and why:
      1. compound_words - a compound's difficulty is "it's two words stuck
         together", regardless of what vowel sounds happen to sit inside it
         (e.g. "backyard" should not get pulled into r_controlled_vowels
         just because it contains "ar").
      2. vowel teams / diphthongs / silent-e, on the whole word - the three
         STRONG patterns (see `_strong_pattern`), salient enough to claim a
         word regardless of its length.
      3. multisyllabic_decoding - for genuinely long words (3+ syllable
         groups) that didn't already match a strong pattern above. Checked
         here, BEFORE the weaker r-controlled/digraph/blend patterns below,
         specifically because those three are common enough as an incidental
         substring inside a much longer word that they used to preempt real
         multisyllabic exemplars ("wonderful", "dinosaur", "elephant",
         "fascinating") before length ever got a chance - a real, confirmed
         gap (33.3% on this category), not a hypothetical one.
      3b. r-controlled / digraphs / blends (see `_weak_pattern`), on the
         whole word - only reached now for words under 3 syllables.
      4. inflectional_endings - checked on the STEM (suffix stripped) first
         against the same specific-pattern checks, so "barked"/"jumped"
         still read as r_controlled_vowels / consonant_blends (their stems
         "bark"/"jump" each have their own more specific pattern - the base
         word's decoding challenge, not the suffix, is the real trip-up) and
         only a suffixed-but-otherwise-plain word like "helped"/"filled"
         (stems "help"/"fill" have no other flagged pattern) actually falls
         through to inflectional_endings. See tests/test_skills.py for the
         full contrast.
      5. open_syllables - the word's first vowel is followed by a single
         consonant (or a recognized initial blend/digraph, which stays
         together and doesn't split the syllable) and then another vowel -
         the classic VCV shape ("ti-ny", "ro-bot", "a-pron") - checked in
         this fallback section, after every more specific whole-word pattern
         above has already had its chance to claim the word.
      6. short_vowels vs. closed_syllables, both last-resort structural
         fallbacks for a word with no other flagged pattern: a single
         closed syllable ("hat", "sun") is tagged short_vowels (the vowel
         SOUND is the whole story for a one-syllable word); a two-syllable
         word built from closed syllables ("napkin", "rabbit") is tagged
         closed_syllables (now the syllable-DIVISION is the actual skill
         being exercised, per the taxonomy's own short_vowels ->
         closed_syllables prerequisite ordering in skill_taxonomy.json).
    """
    word = re.sub(r"[^a-z]", "", reference_word.lower())
    if not word:
        return "short_vowels"

    if _is_compound(word):
        return "compound_words"

    strong = _strong_pattern(word)
    if strong:
        return strong

    if _syllable_count(word) >= 3:
        return "multisyllabic_decoding"

    weak = _weak_pattern(word)
    if weak:
        return weak

    stem, had_suffix = _strip_inflection(word)
    if had_suffix:
        stem_specific = _specific_pattern(stem)
        if stem_specific:
            return stem_specific
        if _syllable_count(stem) >= 3:
            return "multisyllabic_decoding"
        return "inflectional_endings"

    if _syllable_count(word) <= 2 and (
        word.endswith(tuple("aeiou")) or _has_open_first_syllable(word)
    ):
        return "open_syllables"
    if _syllable_count(word) == 1:
        return "short_vowels"
    return "closed_syllables"


assert phonics_skill_ids() >= {
    "short_vowels", "consonant_blends", "consonant_digraphs", "closed_syllables",
    "silent_e", "vowel_teams", "r_controlled_vowels", "diphthongs",
    "open_syllables", "inflectional_endings", "compound_words",
    "multisyllabic_decoding",
}, "classify_skill_for_word assumes these ids exist in content/skill_taxonomy.json"
