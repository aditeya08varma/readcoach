"""Unit tests for the rule-based phonetic skill-tagging heuristic
(skills.py). Anchors are words chosen to be unambiguous for their pattern
(verified empirically against the full skill_taxonomy.json id set) - this
is a heuristic, not a dictionary lookup, so tests target clear cases rather
than every word in every real passage (a passage's declared `primary_skill`
describes the passage as a whole, not a guarantee that literally every word
in it hits that one pattern).
"""

from skills import classify_skill_for_word, phonics_skill_ids, taxonomy_skill_ids


def test_all_returned_ids_are_real_taxonomy_phonics_ids():
    sample_words = [
        "hat", "friend", "frog", "kite", "napkin", "jumped", "cloudy", "bird",
        "piano", "backyard", "octopus", "chip", "team", "helped",
    ]
    for word in sample_words:
        skill_id = classify_skill_for_word(word)
        assert skill_id in taxonomy_skill_ids(), f"{word} -> unknown id {skill_id}"
        assert skill_id in phonics_skill_ids(), f"{word} -> non-phonics id {skill_id}"


def test_vowel_teams():
    for word in ["team", "stream", "deer", "near", "trees", "reached", "cheese", "heading", "friend"]:
        assert classify_skill_for_word(word) == "vowel_teams", word


def test_diphthongs():
    for word in ["cloudy", "Joy", "Roy", "toy", "loud", "found", "boys"]:
        assert classify_skill_for_word(word) == "diphthongs", word


def test_r_controlled_vowels():
    for word in [
        "bird", "porch", "morning", "short", "sister", "scared", "turned",
        "garden", "perch", "fir", "barked",
    ]:
        assert classify_skill_for_word(word) == "r_controlled_vowels", word


def test_consonant_digraphs():
    for word in ["Chip", "chick", "peck", "scratch", "fish"]:
        assert classify_skill_for_word(word) == "consonant_digraphs", word


def test_consonant_blends():
    for word in ["Brad", "frog", "claps", "grins"]:
        assert classify_skill_for_word(word) == "consonant_blends", word


def test_silent_e():
    for word in ["kite", "home", "nice", "smile"]:
        assert classify_skill_for_word(word) == "silent_e", word


def test_compound_words():
    for word in [
        "backyard", "seesaw", "sandbox", "sunflowers", "birdhouse",
        "birdbath", "sunset", "homework",
    ]:
        assert classify_skill_for_word(word) == "compound_words", word


def test_multisyllabic_decoding():
    for word in ["octopus", "incredibly"]:
        assert classify_skill_for_word(word) == "multisyllabic_decoding", word


def test_open_syllables():
    assert classify_skill_for_word("piano") == "open_syllables"

    # Canonical open-syllable exemplars ("first syllable ends on the vowel
    # sound") with a single medial consonant. These used to all fall
    # through to closed_syllables/short_vowels because the old check only
    # looked at the whole word's last letter - caught by the eval
    # benchmark, which scored this category at 1/9 (11%) before this fix.
    for word in ["baby", "zebra", "pony", "tiny", "robot", "pilot"]:
        assert classify_skill_for_word(word) == "open_syllables", word

    # Known, accepted remaining gaps, deliberately not special-cased:
    #
    # "apron" has an open first syllable too, but its medial cluster is a
    # two-consonant blend ("pr"), which is genuinely ambiguous without a
    # pronouncing dictionary: the same blend shape closes the syllable in a
    # short-vowel word ("bas-ket", "gob-lin") but stays open in a
    # long-vowel one ("a-pron", "ze-bra"). An earlier version of this fix
    # treated any medial blend as open and wrongly flipped "basket"/
    # "goblin" to open_syllables as a result - see test_closed_syllables.
    # Trading "apron" for that regression isn't worth it.
    #
    # "tiger" and "hero" also have an open first syllable, but their medial
    # "er" is caught first by the r_controlled_vowels substring scan
    # (checked earlier, on the whole word, since it can't tell that this
    # particular "er" starts a new syllable rather than closing the
    # current one - same substring shape as a real same-syllable case like
    # "sister" or "under"). Fixing this without a real syllable-boundary
    # model risks regressing test_r_controlled_vowels.
    #
    # Asserted explicitly so a future change notices if either flips.
    assert classify_skill_for_word("apron") == "closed_syllables"
    assert classify_skill_for_word("tiger") == "r_controlled_vowels"
    assert classify_skill_for_word("hero") == "r_controlled_vowels"


def test_closed_syllables():
    for word in ["napkin", "rabbit", "sudden", "muffin"]:
        assert classify_skill_for_word(word) == "closed_syllables", word

    # Regression guard: "basket"/"goblin" have a short first vowel closed
    # by a two-consonant medial blend ("sk"/"bl"), which looks structurally
    # identical to open-syllable blend cases like "apron"'s "pr" (also a
    # vowel-blend-vowel shape) without knowing the vowel is short here and
    # long there. The open-syllable check deliberately only matches a
    # single medial consonant precisely so it can't claim these.
    for word in ["basket", "goblin"]:
        assert classify_skill_for_word(word) == "closed_syllables", word


def test_short_vowels_fallback_for_simple_one_syllable_words():
    for word in ["hat", "red", "sun", "job", "fix"]:
        assert classify_skill_for_word(word) == "short_vowels", word


def test_inflectional_endings_only_when_stem_has_no_more_specific_pattern():
    # stems (help/fill/miss/pass/call/roll/pup) have no other flagged pattern
    for word in ["helped", "filled", "missed", "passed", "called", "rolled", "pups"]:
        assert classify_skill_for_word(word) == "inflectional_endings", word

    # but "barked"/"jumped" stems (bark/jump) DO have a more specific pattern
    # (r-controlled "ar", final blend "mp"), so the stem's own pattern wins.
    #
    # A real, honest correction: this used to justify that choice by
    # claiming "the taxonomy's own prerequisite chain treats the base
    # pattern as the more fundamental skill" - checked directly against
    # content/skill_taxonomy.json (see docs/BUILD_LOG.md) and that claim
    # does not actually hold. r_controlled_vowels and consonant_blends are
    # NOT prerequisites of inflectional_endings there - all eleven phonics
    # skills sit as parallel siblings, each a prerequisite of
    # multisyllabic_decoding, with no edge between any two of them. This
    # remains a real, deliberate design choice (a real structured-literacy
    # curriculum genuinely disagrees, per backend/eval/benchmark_cases.py's
    # own careful "textbook exemplar" ground truth for exactly these two
    # words), just not one the taxonomy itself backs up - left as an open,
    # honestly-flagged tension rather than a settled one.
    assert classify_skill_for_word("barked") == "r_controlled_vowels"
    assert classify_skill_for_word("jumped") == "consonant_blends"


def test_empty_or_punctuation_only_word_falls_back_safely():
    assert classify_skill_for_word("") == "short_vowels"
    assert classify_skill_for_word("...") == "short_vowels"
