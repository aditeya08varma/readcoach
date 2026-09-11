"""
Next-passage selection for GET /students/{id}/next_passage.

Rule (plain terms):
1. Compute every skill's real mastery weight (0.0 if never assessed).
2. Any skill below WEAK_THRESHOLD is a candidate "weak skill." Sort these
   weak skills by weight ascending -- the single genuinely weakest skill is
   tried first, full stop (a real, explicit request: this used to try
   skills in topological/foundational order instead, and could recommend a
   skill that wasn't the weakest just because it came earlier in that
   order). Ties (several skills sitting at a real, untouched 0.0) keep
   their original topological/foundational order relative to each other,
   so among equally-weak skills the more foundational one still wins.
3. Take the weakest skill that has at least one passage tagged with it as
   primary_skill -- ANY grade, not just the student's own (see
   _passages_for_skill's own comment for the real bug this fixes: content
   is real but spread across grades 1-3, one passage per skill, so
   grade-restricting this used to silently disqualify most of the weaker,
   more foundational skills from ever being picked at all). Recency decides
   WHICH passage to hand back once the skill is chosen -- prefer one the
   student hasn't read in their last RECENCY_WINDOW sessions; if every
   matching passage for that skill was read recently, fall back to the
   least-recently-used one for that same skill (repeats are better than
   abandoning the weakest skill).
4. If somehow no weak skill has any matching passage at all (shouldn't
   happen now that every skill has a real passage), fall back to the same
   rule over ALL skills, weakest-first (maintenance mode -- the student has
   nothing weak enough to flag, but we still want a sensible passage). If
   that also comes up empty, return any passage at the student's grade so
   the endpoint never 404s.
"""
import json
import sys
from pathlib import Path

from mastery import _decode_prerequisite_of, get_weights, topological_skill_order

# Cross-service import, same precedented pattern backend/voice already uses
# to reach backend/tutor (see backend/voice/tutor_processor.py's own comment
# on this) - classify_skill_for_word is pure/stateless (no I/O, no AI call),
# so importing it directly avoids maintaining a second copy of the same
# phonics-pattern logic just to pick a "challenge word" (see
# docs/FEATURE_IDEAS.md's gameplay ideation).
_TUTOR_DIR = Path(__file__).resolve().parents[1] / "tutor"
if str(_TUTOR_DIR) not in sys.path:
    sys.path.insert(0, str(_TUTOR_DIR))

from skills import classify_skill_for_word  # noqa: E402

CONTENT_DIR = Path(__file__).resolve().parent.parent.parent / "content"
PASSAGES_DIR = CONTENT_DIR / "passages"

WEAK_THRESHOLD = 0.6
RECENCY_WINDOW = 5  # don't repeat a passage the student read in their last 5 sessions


def load_passages() -> list[dict]:
    passages = []
    for path in sorted(PASSAGES_DIR.glob("*.json")):
        passages.append(json.loads(path.read_text()))
    return passages


_PASSAGES_CACHE: list[dict] | None = None


def get_passages() -> list[dict]:
    global _PASSAGES_CACHE
    if _PASSAGES_CACHE is None:
        _PASSAGES_CACHE = load_passages()
    return _PASSAGES_CACHE


def get_recent_passage_ids(cur, student_id: str, limit: int = RECENCY_WINDOW) -> set[str]:
    cur.execute(
        "select passage_id from sessions where student_id = ? order by started_at desc limit ?",
        (student_id, limit),
    )
    return {row["passage_id"] for row in cur.fetchall()}


def _passages_for_skill(skill_id: str) -> list[dict]:
    # Real bug found from a real report ("it always picks The Boat Trip,
    # which is already done"): this used to also require p["grade"] ==
    # the student's own grade. The 18-skill taxonomy's passage library has
    # exactly one primary passage per skill, spread across grades 1 to 3 -
    # so for a grade-2 student, every grade-1-tagged foundational skill
    # (short_vowels, consonant_blends, consonant_digraphs, closed_syllables,
    # silent_e, inflectional_endings) had NO passage that could ever match
    # here, no matter how weak that skill genuinely was. The priority loop
    # below always takes the first weak skill WITH a matching passage, so
    # every one of those weaker, more foundational skills was silently
    # skipped every single time, and the same one grade-2 skill that
    # happened to have a passage (vowel_teams, "The Boat Trip") kept
    # winning by default even after the student had already read it - not
    # because it was actually the weakest skill, only because it was the
    # first one the grade filter let through. Matching on skill_id alone
    # fixes this the same way the story map's own grade filter was already
    # fixed (see docs/BUILD_LOG.md) - reading a story tagged for a
    # different grade to shore up a real, genuine weak spot is a normal
    # part of a reading journey, not a mismatch to avoid.
    return [p for p in get_passages() if p.get("primary_skill") == skill_id]


def _best_passage_for_skill(cur, student_id: str, sid: str, recent_ids: set[str]) -> dict | None:
    candidates = _passages_for_skill(sid)
    if not candidates:
        return None
    fresh = [p for p in candidates if p["id"] not in recent_ids]
    if fresh:
        return sorted(fresh, key=lambda p: p["id"])[0]
    return _least_recently_used(cur, student_id, candidates)  # every match was recent -- repeat is fine


def _skill_label(cur, skill_id: str) -> str:
    cur.execute("select label from skills where id = ?", (skill_id,))
    row = cur.fetchone()
    return row["label"] if row else skill_id


def _strongest_ready_prerequisite_label(cur, student_id: str, target_skill_id: str) -> str | None:
    """Among the skills that list `target_skill_id` in their own
    prerequisite_of (i.e. target_skill_id's immediate prerequisites), return
    the label of whichever one the student is already strong at (highest
    weight, at or above WEAK_THRESHOLD), if any. Used only to make the
    "why this story" explanation name a concrete skill the student has
    actually built on, rather than an abstract priority-order fact -
    purely cosmetic, never changes which passage gets picked.
    """
    cur.execute("select id, label, prerequisite_of from skills")
    rows = cur.fetchall()
    weights = get_weights(cur, student_id)
    best_label, best_weight = None, -1.0
    for row in rows:
        if target_skill_id not in _decode_prerequisite_of(row["prerequisite_of"]):
            continue
        weight = weights.get(row["id"], 0.0)
        if weight >= WEAK_THRESHOLD and weight > best_weight:
            best_label, best_weight = row["label"], weight
    return best_label


def _build_selection_reason(cur, student_id: str, target_skill_id: str | None, mode: str) -> dict:
    """Plain templating over numbers the mastery engine already computed -
    no AI call needed, the reasoning behind a pick is already deterministic
    (see docs/FEATURE_IDEAS.md's "why this story" idea). `mode` is one of
    "priority_weak" (a real weak/unassessed skill was targeted),
    "maintenance" (nothing's weak, keeping a skill sharp), or "fallback"
    (grade-only, no skill reasoning available at all).
    """
    if target_skill_id is None:
        return {
            "target_skill_id": None,
            "target_skill_label": None,
            "mode": "fallback",
            "explanation": "This story matches your reading level.",
        }

    label = _skill_label(cur, target_skill_id)
    if mode == "priority_weak":
        base_label = _strongest_ready_prerequisite_label(cur, student_id, target_skill_id)
        if base_label:
            explanation = (
                f"This story builds on {base_label}, which is going well, and "
                f"practices {label} next."
            )
        else:
            explanation = f"This story practices {label}, a skill that's still developing."
    elif mode == "maintenance":
        explanation = f"Everything tracked is in good shape, so this story keeps {label} sharp."
    elif mode == "chosen":
        explanation = f"You picked this story yourself! It practices {label}."
    else:
        explanation = f"This story practices {label}."

    return {
        "target_skill_id": target_skill_id,
        "target_skill_label": label,
        "mode": mode,
        "explanation": explanation,
    }


def pick_challenge_word_index(passage: dict) -> int | None:
    """Pick one word in the passage to visually flag as a "challenge word" -
    the reading screen marks it specially before it's read and celebrates
    when it's cleared (read correctly or self-corrected), see
    docs/FEATURE_IDEAS.md's gameplay ideation. Purely cosmetic: never
    affects passage selection or scoring, only which word gets a highlight.

    Scans the passage's words for the first one whose own phonics pattern
    matches the passage's declared primary_skill - the same reasoning a
    human content-curator would use to pick "the word this story is really
    about." Falls back to the single longest word when nothing matches
    (a real, known limitation of the phonics classifier - see
    backend/eval's benchmark findings on this classifier - not a bug in
    this function), so every passage still gets a sensible highlight.
    """
    words = passage.get("words") or []
    primary_skill = passage.get("primary_skill")
    if primary_skill:
        for i, word in enumerate(words):
            if classify_skill_for_word(word) == primary_skill:
                return i
    if not words:
        return None
    return max(range(len(words)), key=lambda i: len(words[i]))


def get_chosen_passage(cur, student_id: str, passage_id: str) -> tuple[dict, dict] | None:
    """A real person explicitly picked this exact passage (the story map's
    tap-a-node flow, or the voice bot's own passage_id override - see
    docs/FEATURE_IDEAS.md's gameplay ideation and contracts/api_contract.md's
    GET /students/{id}/passages/{passage_id}). Returns the same
    (passage, selection_reason) shape pick_next_passage does, so every
    consumer (main.py's response model, the reading screen) handles both
    identically - just with mode="chosen" instead of an auto-selection rule
    explaining the pick. None if no passage with that id exists at all.
    """
    passage = next((p for p in get_passages() if p["id"] == passage_id), None)
    if passage is None:
        return None
    return passage, _build_selection_reason(cur, student_id, passage.get("primary_skill"), "chosen")


def pick_next_passage(cur, student_id: str, grade: int) -> tuple[dict, dict]:
    """Returns (passage, selection_reason). `selection_reason` is additive,
    cosmetic explanation data (see _build_selection_reason) - it never
    influences which passage gets picked, only describes why afterward.
    """
    priority_skills = topological_skill_order(cur)
    recent_ids = get_recent_passage_ids(cur, student_id)
    weights = get_weights(cur, student_id)

    # Real, explicit request: always target the genuinely weakest mastery %,
    # not just the first weak skill in foundational/topological order. Sort
    # weak skills by real weight ascending; Python's sort is stable, so ties
    # (several skills sitting at a real, untouched 0.0) keep their original
    # topological order relative to each other, still preferring the more
    # foundational one among equally-weak skills rather than an arbitrary one.
    weak_skills = sorted(
        (sid for sid in priority_skills if weights.get(sid, 0.0) < WEAK_THRESHOLD),
        key=lambda sid: weights.get(sid, 0.0),
    )

    # Priority pass: the single weakest skill that has ANY matching passage
    # wins, repeat or not.
    for sid in weak_skills:
        passage = _best_passage_for_skill(cur, student_id, sid, recent_ids)
        if passage:
            return passage, _build_selection_reason(cur, student_id, sid, "priority_weak")

    # Maintenance mode: no weak skill has a matching passage (should be rare
    # now that every skill has a real passage regardless of grade - this is
    # the "everything's already mastered" case) -- same rule over ALL
    # skills, weakest-first.
    for sid in sorted(priority_skills, key=lambda sid: weights.get(sid, 0.0)):
        passage = _best_passage_for_skill(cur, student_id, sid, recent_ids)
        if passage:
            return passage, _build_selection_reason(cur, student_id, sid, "maintenance")

    # Last resort: nothing in the taxonomy matches this grade at all (shouldn't
    # happen with the current 20-passage library spanning grades 1-3) -- any
    # passage at the student's grade so the endpoint never 404s.
    grade_passages = [p for p in get_passages() if p["grade"] == grade]
    if grade_passages:
        passage = _least_recently_used(cur, student_id, grade_passages)
        return passage, _build_selection_reason(cur, student_id, passage.get("primary_skill"), "fallback")

    raise ValueError(f"No passages available for grade {grade}")


def _iso(value) -> str:
    """`started_at` is a plain ISO-8601 string on SQLite but a native
    Postgres timestamptz, which psycopg2 hands back as a real `datetime` -
    normalize both to a string so they sort against each other (and against
    the "" never-read sentinel below) without a str/datetime TypeError."""
    return value.isoformat() if hasattr(value, "isoformat") else value


def _least_recently_used(cur, student_id: str, candidates: list[dict]) -> dict:
    """Among candidates, pick the one least recently read by this student (never-read
    passages first, in id order; then by oldest started_at)."""
    cur.execute(
        "select passage_id, max(started_at) as last_read from sessions where student_id = ? group by passage_id",
        (student_id,),
    )
    last_read = {row["passage_id"]: _iso(row["last_read"]) for row in cur.fetchall()}

    def sort_key(p):
        return (last_read.get(p["id"], ""), p["id"])  # "" sorts before any timestamp -> never-read first

    return sorted(candidates, key=sort_key)[0]
