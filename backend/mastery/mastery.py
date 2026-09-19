"""
The mastery update rule.

In plain terms: after a session comes in, for every skill the session actually
touched (via a miscue's skill_id or a comprehension question's skill_id), compute a
0..1 "session score" for that skill from the raw signal, then fold it into the
student's stored weight for that skill with an exponential moving average (EMA):

    new_weight = (1 - ALPHA) * old_weight + ALPHA * session_score

ALPHA=0.3 means each session moves the weight 30% of the way toward how the student
just did on that skill -- enough to react within a few sessions, not so much that one
noisy session swings the number wildly.

Per-skill session_score:
  - Phonics/decoding skills (signalled via miscues): start at 1.0 (perfect) and
    subtract a fixed penalty (0.15) for every miscue tagged with that skill
    (substitution/omission/insertion), add back a smaller bonus (0.05) for every
    self_correction tagged with that skill (catching your own mistake shows partial
    competency), then clamp to [0, 1].
  - Comprehension skills (signalled via comprehension answers): session_score =
    (# correct) / (# asked) for that skill_id in this session.

Prerequisite partial credit: content/skill_taxonomy.json's prerequisite_of edges say
"mastering skill A helps unlock skill B" (A -> B, A is a prerequisite of B). When a
skill A gets a direct EMA update from a session, we also nudge every skill B that A
is a prerequisite of, using the SAME session_score but at half strength
(PREREQ_ALPHA = 0.5 * ALPHA = 0.15). This is a small, explicit "if you're doing well
on the foundational skill, you're probably making a little quiet progress on what it
unlocks too" signal -- not full credit, since the student never actually practiced B
this session.
"""
import json
from dataclasses import dataclass
from datetime import datetime, timezone

import db

ALPHA = 0.3
PREREQ_ALPHA = 0.5 * ALPHA  # 0.15

_taxonomy_ids_cache: list[str] | None = None
_phonics_ids_cache: frozenset[str] | None = None


def _taxonomy_skill_ids() -> list[str]:
    """content/skill_taxonomy.json's own listed skill order - the same file
    db._load_taxonomy seeds the `skills` table from. Cached at module level;
    this file doesn't change at runtime."""
    global _taxonomy_ids_cache
    if _taxonomy_ids_cache is None:
        taxonomy = json.loads(db.TAXONOMY_PATH.read_text())
        _taxonomy_ids_cache = [skill["id"] for skill in taxonomy]
    return _taxonomy_ids_cache


def _phonics_skill_ids() -> frozenset[str]:
    """The subset of taxonomy skill ids whose `category` is "phonics" - see
    compute_direct_skill_scores's clean-read bonus for why this matters:
    only phonics/decoding skills have a genuine "silent success" case
    (a passage read with zero miscues on that skill). Cached like
    _taxonomy_skill_ids, same reasoning."""
    global _phonics_ids_cache
    if _phonics_ids_cache is None:
        taxonomy = json.loads(db.TAXONOMY_PATH.read_text())
        _phonics_ids_cache = frozenset(
            s["id"] for s in taxonomy if s.get("category") == "phonics"
        )
    return _phonics_ids_cache

MISCUE_ERROR_TYPES = {"substitution", "omission", "insertion"}
MISCUE_PENALTY = 0.15
SELF_CORRECTION_BONUS = 0.05


@dataclass
class SkillUpdate:
    skill_id: str
    session_score: float
    old_weight: float
    new_weight: float
    direct: bool  # True if the skill was actually practiced this session,
    # False if it only received propagated prerequisite credit


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def compute_direct_skill_scores(
    miscues: list[dict],
    comprehension: list[dict],
    passage_skill_ids: set[str] | None = None,
) -> dict[str, float]:
    """Turn one session's raw miscue/comprehension records into a per-skill 0..1 score.

    Returns {skill_id: session_score} for every skill referenced in this session's
    data, plus (via `passage_skill_ids`) every phonics/decoding skill the passage
    itself is tagged as practicing (Passage.skills, contracts/passage_schema.json)
    that came back with zero miscues at all - a genuinely clean read of that skill's
    words. Real bug found by hand-tracing a real student's real mastery numbers (see
    docs/BUILD_LOG.md): before this, a skill only ever appeared here via a mistake -
    a perfect, error-free read of a passage produced no miscue entries for its own
    target skill at all, so that skill's own dedicated story could be read flawlessly
    and move its mastery weight by exactly nothing, while a passage read with a
    mistake at least generated a (penalized) score. Comprehension skills aren't
    included in this treatment: there's no silent-success case there, since a
    comprehension_correct=True answer is already itself a real, explicit signal in
    `comprehension`, unlike phonics skills, which only ever emit an entry on failure.
    """
    scores: dict[str, float] = {}

    # --- phonics/decoding skills, from miscues ---
    miscue_skills: dict[str, dict[str, int]] = {}
    for m in miscues:
        skill_id = m.get("skill_id")
        if not skill_id:
            continue
        bucket = miscue_skills.setdefault(skill_id, {"errors": 0, "self_corrections": 0})
        if m.get("type") == "self_correction":
            bucket["self_corrections"] += 1
        elif m.get("type") in MISCUE_ERROR_TYPES:
            bucket["errors"] += 1

    for skill_id, counts in miscue_skills.items():
        score = 1.0 - counts["errors"] * MISCUE_PENALTY + counts["self_corrections"] * SELF_CORRECTION_BONUS
        scores[skill_id] = max(0.0, min(1.0, score))

    # A passage-tagged PHONICS skill that never shows up in miscue_skills at all
    # was read with zero mistakes on it - real positive evidence, previously
    # dropped entirely (see docstring above). Only fills in skills with no miscue
    # entry of any kind; a skill already scored above (even from a self-correction
    # alone) keeps its real, evidence-based score instead of being overwritten by
    # this.
    #
    # Real bug found live (see docs/BUILD_LOG.md): this used to loop over ALL of
    # passage_skill_ids with no category filter, so a passage's vocabulary/
    # comprehension skill_ids (Passage.skills routinely mixes categories, per
    # contracts/passage_schema.json) got the same "assume 1.0" treatment as
    # phonics ones - directly contradicting this function's own docstring, which
    # already said comprehension skills aren't included in this treatment.
    # Concretely, a session with a WRONG comprehension answer on a passage-tagged
    # skill got that wrong answer's real 0.0 averaged against a phantom 1.0 below
    # (inflating it to 0.5), and a passage-tagged skill nobody was even asked
    # about this session got a full, unearned 1.0 "direct" update. Fixed by
    # restricting this fill to _phonics_skill_ids() - comprehension/vocabulary
    # skills only ever get a score from an actual answered question, in the loop
    # below, exactly as the docstring always claimed.
    phonics_ids = _phonics_skill_ids()
    for skill_id in passage_skill_ids or ():
        if skill_id in phonics_ids and skill_id not in miscue_skills:
            scores[skill_id] = 1.0

    # --- comprehension skills, from comprehension answers ---
    comp_skills: dict[str, dict[str, int]] = {}
    for c in comprehension:
        skill_id = c.get("skill_id")
        if not skill_id:
            continue
        bucket = comp_skills.setdefault(skill_id, {"correct": 0, "total": 0})
        bucket["total"] += 1
        if c.get("correct"):
            bucket["correct"] += 1

    for skill_id, counts in comp_skills.items():
        if counts["total"] == 0:
            continue
        score = counts["correct"] / counts["total"]
        # If a skill shows up in both miscues and comprehension (shouldn't normally
        # happen given the taxonomy's phonics/comprehension split, but stay safe),
        # average the two signals rather than clobbering one.
        if skill_id in scores:
            scores[skill_id] = (scores[skill_id] + score) / 2
        else:
            scores[skill_id] = score

    return scores


def _decode_prerequisite_of(value) -> list[str]:
    """`prerequisite_of` is JSON-encoded text on SQLite (schema_sqlite.sql's
    text column) but a native Postgres text[] in production, which psycopg2
    hands back already parsed as a Python list -- accept either so this
    function works unchanged against both backends (see db.py's docstring)."""
    return value if isinstance(value, list) else json.loads(value)


def get_prerequisite_edges(cur) -> dict[str, list[str]]:
    """skill_id -> list of skill ids it is a prerequisite of (forward edges)."""
    cur.execute("select id, prerequisite_of from skills")
    edges = {}
    for row in cur.fetchall():
        edges[row["id"]] = _decode_prerequisite_of(row["prerequisite_of"])
    return edges


def get_weight(cur, student_id: str, skill_id: str) -> float:
    cur.execute(
        "select weight from student_skill_mastery where student_id = ? and skill_id = ?",
        (student_id, skill_id),
    )
    row = cur.fetchone()
    return row["weight"] if row else 0.0


def get_weights(cur, student_id: str) -> dict[str, float]:
    """All of a student's skill weights in one query. Real bug found twice
    now from real recordings (see docs/BUILD_LOG.md): calling get_weight in
    a loop over every skill is 18 separate real round trips to the remote
    database instead of one, slow enough on its own to trip a caller's fetch
    timeout and silently fall back to worse data. Use this instead of
    get_weight whenever more than one skill's weight is needed at once."""
    cur.execute(
        "select skill_id, weight from student_skill_mastery where student_id = ?",
        (student_id,),
    )
    return {row["skill_id"]: row["weight"] for row in cur.fetchall()}


def _blend_weight_atomic(cur, student_id: str, skill_id: str, alpha: float, score: float) -> float:
    """The actual EMA write (new_weight = (1-alpha)*old + alpha*score), done
    as one atomic upsert instead of a Python-side read-then-write.

    Real, confirmed race found in a concurrency audit (see docs/BUILD_LOG.md):
    apply_session_to_mastery used to read the current weight, compute the
    blend in Python, then write it back as two separate round trips. Two
    sessions for the SAME student landing close together (two tabs, a
    retried request) could both read the same stale weight before either
    wrote, and the second write would silently clobber the first - a
    genuine lost update, not hypothetical.

    `weight` on the right of `do update set weight = ...` refers to "this
    row's value as it stands the instant this statement's own conflict
    resolution runs" - not a value read earlier in Python, so there is no
    window for another transaction to change it out from under this one.
    No explicit clamping is needed: `score` is already clamped to [0, 1] by
    every caller before it gets here, `alpha` is a fixed in-range constant,
    and a convex combination ((1-alpha)*x + alpha*y) of two already-in-[0,1]
    values can never itself leave [0, 1].

    Real bug found live (see docs/BUILD_LOG.md): an unqualified `weight` on
    the right-hand side used to raise `psycopg2.errors.AmbiguousColumn` on
    real Postgres - ON CONFLICT DO UPDATE puts both the target table's own
    row AND the special `excluded` pseudo-row in scope, and `excluded` also
    has a `weight` column (it mirrors every column of the table), so a bare
    `weight` is genuinely ambiguous between "the existing row" and
    "excluded.weight," not resolvable by a default. SQLite has no such
    ambiguity (its `excluded.` rows aren't a second same-named relation in
    scope the same way), which is exactly why this went unnoticed until a
    real session hit the real production Postgres database - every session
    ingested before this fix silently failed the whole request with a 500,
    including the mastery update the entire pipeline depends on. Qualifying
    the existing-row reference with the table's own name resolves it.
    """
    cur.execute(
        """
        insert into student_skill_mastery (student_id, skill_id, weight, updated_at)
        values (?, ?, ?, ?)
        on conflict(student_id, skill_id) do update set
            weight = (1 - ?) * student_skill_mastery.weight + ? * ?,
            updated_at = excluded.updated_at
        returning weight
        """,
        (student_id, skill_id, alpha * score, _now(), alpha, alpha, score),
    )
    return cur.fetchone()["weight"]


def apply_session_to_mastery(
    cur,
    student_id: str,
    miscues: list[dict],
    comprehension: list[dict],
    passage_skill_ids: set[str] | None = None,
) -> list[SkillUpdate]:
    """The full update rule for one session. Returns every SkillUpdate applied
    (direct + propagated) so callers/tests can see exactly what moved and why.
    `passage_skill_ids` is optional and defaults to the old, miscues-only
    behavior - see compute_direct_skill_scores for what it adds."""
    direct_scores = compute_direct_skill_scores(miscues, comprehension, passage_skill_ids)
    edges = get_prerequisite_edges(cur)
    updates: list[SkillUpdate] = []

    # `old` here is read just for the response payload's own "how much did
    # this move" field - informational, not load-bearing. The actual write
    # below (_blend_weight_atomic) never uses this Python-held value to
    # compute the new weight, so even in a genuine concurrent race, the
    # persisted weight itself is always computed correctly; only this
    # reported `old_weight` number could, in that rare case, reflect a
    # slightly earlier moment than the literal instant just before the
    # write - a real, honest, and much lower-stakes tradeoff than the lost
    # update this replaced.

    # Direct EMA updates for skills actually practiced this session.
    for skill_id, score in direct_scores.items():
        old = get_weight(cur, student_id, skill_id)
        new = _blend_weight_atomic(cur, student_id, skill_id, ALPHA, score)
        updates.append(SkillUpdate(skill_id, score, old, new, direct=True))

    # Real, confirmed bug (live-reproduced): the taxonomy is a DAG, not a tree, so
    # the SAME downstream skill_id can appear in more than one directly-practiced
    # skill's own prerequisite_of list in one request (e.g. both vowel_teams and
    # diphthongs list multisyllabic_decoding downstream). The old code below
    # looped over every direct skill and unconditionally called
    # _blend_weight_atomic again for each of its downstream skills, so a shared
    # downstream skill got one separate, sequential blend per contributing direct
    # skill, each one reading the row the previous write just left behind -
    # confirmed live as multisyllabic_decoding compounding 0.582 -> 0.645 -> 0.698
    # in a single request that touched both vowel_teams and diphthongs, instead of
    # moving once.
    #
    # Fix: first collect, per downstream skill_id, the score of every direct
    # skill that feeds it - without writing anything yet - then blend each
    # unique downstream skill_id exactly once. When more than one direct skill
    # feeds the same downstream skill, the combined score is their AVERAGE: the
    # same choice this file already makes a few lines up in
    # compute_direct_skill_scores when one skill_id shows up in both miscues and
    # comprehension ("average the two signals rather than clobbering one") - an
    # average is the principled pick here too, since each contributing direct
    # skill is equally real evidence of "quiet progress on what this unlocks,"
    # and picking a max or an arbitrary first-seen score would let one skill's
    # score silently overrule another's instead of blending both.
    #
    # A downstream skill that was ALSO practiced directly this session is
    # excluded from this pass entirely: it already has a real, observed direct
    # score from the loop above, which is strictly better evidence than an
    # inferred prerequisite nudge, so direct evidence wins outright rather than
    # being averaged with or overwritten by a propagated one.
    downstream_scores: dict[str, list[float]] = {}
    for skill_id, score in direct_scores.items():
        for downstream_id in edges.get(skill_id, []):
            if downstream_id in direct_scores:
                continue
            downstream_scores.setdefault(downstream_id, []).append(score)

    for downstream_id, scores in downstream_scores.items():
        combined_score = sum(scores) / len(scores)
        old = get_weight(cur, student_id, downstream_id)
        new = _blend_weight_atomic(cur, student_id, downstream_id, PREREQ_ALPHA, combined_score)
        updates.append(SkillUpdate(downstream_id, combined_score, old, new, direct=False))

    return updates


def topological_skill_order(cur) -> list[str]:
    """Kahn's algorithm over the prerequisite_of edges: foundational skills (no
    prerequisites of their own) first, most-downstream skills last. This is the
    priority order passage_selection.py walks to find the highest-priority weak
    skill -- foundations block everything built on them, so they're fixed first."""
    # Real bug found while testing a separate fix: this query had no
    # `order by`, so which foundational skill actually comes out on top of a
    # tie was left to whatever row order SQLite or Postgres happened to
    # return that connection - not actually deterministic despite this
    # function's own docstring claiming it is, and despite the "ready"
    # round below already being carefully written to prefer the taxonomy's
    # own listed order. Sorting by `taxonomy_order`, the same order
    # content/skill_taxonomy.json lists skills in and the same file
    # db._load_taxonomy seeds this table from, is what "the taxonomy's own
    # listed order" actually means - not the query's incidental row order.
    cur.execute("select id, prerequisite_of from skills")
    rows = cur.fetchall()
    taxonomy_order = {sid: i for i, sid in enumerate(_taxonomy_skill_ids())}
    rows = sorted(rows, key=lambda r: taxonomy_order.get(r["id"], len(taxonomy_order)))
    all_ids = [row["id"] for row in rows]
    forward_edges = {row["id"]: _decode_prerequisite_of(row["prerequisite_of"]) for row in rows}

    in_degree = {sid: 0 for sid in all_ids}
    for sid, downstream in forward_edges.items():
        for d in downstream:
            if d in in_degree:
                in_degree[d] += 1

    # Stable order: process available (in_degree == 0) nodes in the taxonomy's own
    # listed order each round, so the result is deterministic.
    remaining = list(all_ids)
    order: list[str] = []
    while remaining:
        ready = [sid for sid in remaining if in_degree[sid] == 0]
        if not ready:
            # Cycle guard (shouldn't happen with a real prerequisite DAG) -- just
            # drain whatever's left in listed order rather than infinite-looping.
            order.extend(remaining)
            break
        for sid in ready:
            order.append(sid)
            remaining.remove(sid)
            for d in forward_edges.get(sid, []):
                if d in in_degree:
                    in_degree[d] -= 1
    return order
