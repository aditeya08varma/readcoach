"""
Scripted verification: drives the ACTUAL running FastAPI service (not unit-testing
functions in isolation) through a sequence of fake sessions for one grade-1 student,
and asserts mastery weights and next_passage's implied skill priority move in the
expected direction.

REAL INCIDENT, fixed after it happened (see docs/BUILD_LOG.md): setting only
MASTERY_DB_PATH to a throwaway file used NOT to isolate this from the real
database. db.py used to call load_dotenv(override=True), which meant
backend/mastery/.env's real Supabase DATABASE_URL always won over the shell's
own environment - so even explicitly setting `DATABASE_URL=` in the shell to
force the SQLite fallback did nothing, and every "isolated" run of this script
was actually writing fake students and fake sessions straight into the real,
shared production database. db.py now uses load_dotenv(override=False) (the
library's own default, made explicit there), so the shell's own environment
correctly wins - always set BOTH of the following for a genuinely isolated
run, not just MASTERY_DB_PATH alone:

Usage:
    (from backend/mastery/, with the service already running via
     `DATABASE_URL= MASTERY_DB_PATH=/tmp/scratch.db uvicorn main:app --port 8123`
     - the leading `DATABASE_URL=` with nothing after it is required)
    python test_scenario.py
"""
import sys

import httpx

BASE = "http://127.0.0.1:8123"


def get_weight(mastery: list[dict], skill_id: str) -> float:
    return next(m["weight"] for m in mastery if m["skill_id"] == skill_id)


def main():
    client = httpx.Client(base_url=BASE, timeout=10)

    student = client.post("/students", json={"display_name": "Scenario Kid", "grade": 1}).json()
    sid = student["id"]
    print(f"created student {sid} (grade {student['grade']})")

    # --- 0. Baseline: nothing practiced yet -> every skill is tied at a real 0.0,
    #         so the topological tiebreak picks short_vowels, first in that order ---
    passage = client.get(f"/students/{sid}/next_passage").json()
    print(f"[0] baseline next_passage -> {passage['id']} (primary_skill={passage['primary_skill']})")
    assert passage["primary_skill"] == "short_vowels", "expected the untouched foundational skill first"

    mastery0 = client.get(f"/students/{sid}/mastery").json()
    assert get_weight(mastery0, "short_vowels") == 0.0

    # --- 1. Three consecutive BAD sessions on short_vowels: lots of errors, no self-corrections ---
    bad_session = {
        "student_id": sid,
        "passage_id": "g1-short-vowels-001",
        "wcpm": 40,
        "accuracy": 0.6,
        "self_corrections": 0,
        "miscues": [
            {"word": "hat", "index": 4, "type": "substitution", "skill_id": "short_vowels"},
            {"word": "duck", "index": 15, "type": "substitution", "skill_id": "short_vowels"},
            {"word": "sits", "index": 16, "type": "omission", "skill_id": "short_vowels"},
        ],
        "comprehension": [],
    }
    for i in range(3):
        result = client.post("/sessions", json=bad_session).json()
        upd = next(u for u in result["updates"] if u["skill_id"] == "short_vowels")
        print(f"[1.{i}] bad session -> short_vowels weight {upd['old_weight']:.3f} -> {upd['new_weight']:.3f} "
              f"(session_score={upd['session_score']:.3f})")

    mastery1 = client.get(f"/students/{sid}/mastery").json()
    w_after_bad = get_weight(mastery1, "short_vowels")
    print(f"short_vowels weight after 3 bad sessions: {w_after_bad:.3f}")
    assert w_after_bad < 0.4, "repeated poor performance should keep short_vowels weight low"

    # Weakest-first targeting (a real, explicit request after this exact
    # scenario kept recommending an already-completed story in practice -
    # see docs/BUILD_LOG.md and passage_selection.py's own comment): these
    # three bad sessions raised short_vowels itself to w_after_bad, but its
    # own downstream skills (step 2 below) only picked up SMALLER, partial
    # propagated credit, and every other skill in the taxonomy is still a
    # real, untouched 0.0 - genuinely weaker than short_vowels now. The next
    # passage should go to one of those, not straight back to short_vowels.
    passage1 = client.get(f"/students/{sid}/next_passage").json()
    print(f"[1] next_passage after bad sessions -> {passage1['id']} (primary_skill={passage1['primary_skill']})")
    assert passage1["primary_skill"] != "short_vowels", "should target the genuinely weaker, still-untouched skill"
    weights_after_bad = {m["skill_id"]: m["weight"] for m in mastery1}
    assert weights_after_bad.get(passage1["primary_skill"], 0.0) <= w_after_bad, (
        "whichever skill got picked should be no stronger than short_vowels itself"
    )

    # --- 2. Prerequisite propagation check: consonant_blends (downstream of short_vowels)
    #         should have picked up a little partial credit even though it was never
    #         practiced directly. ---
    blends_weight = get_weight(mastery1, "consonant_blends")
    print(f"consonant_blends weight (never practiced directly) after bad short_vowels sessions: {blends_weight:.3f}")
    assert 0.0 < blends_weight < w_after_bad, "prereq propagation should give a small, partial (not full) nudge"

    # --- 3. Several consecutive GOOD sessions on short_vowels: no errors, plus self-corrections ---
    good_session = {
        "student_id": sid,
        "passage_id": "g1-short-vowels-001",
        "wcpm": 70,
        "accuracy": 0.98,
        "self_corrections": 1,
        "miscues": [
            {"word": "log", "index": 19, "type": "self_correction", "skill_id": "short_vowels"},
        ],
        "comprehension": [],
    }
    for i in range(6):
        result = client.post("/sessions", json=good_session).json()
        upd = next(u for u in result["updates"] if u["skill_id"] == "short_vowels")
        print(f"[3.{i}] good session -> short_vowels weight {upd['old_weight']:.3f} -> {upd['new_weight']:.3f} "
              f"(session_score={upd['session_score']:.3f})")

    mastery2 = client.get(f"/students/{sid}/mastery").json()
    w_after_good = get_weight(mastery2, "short_vowels")
    print(f"short_vowels weight after 6 good sessions: {w_after_good:.3f}")
    assert w_after_good > w_after_bad, "good sessions should raise the weight back up"
    assert w_after_good >= 0.6, "should have crossed the WEAK_THRESHOLD after sustained good performance"

    # --- 4. Priority should now have shifted off short_vowels, now mastered, to
    #         whichever remaining skill is genuinely weakest. ---
    passage2 = client.get(f"/students/{sid}/next_passage").json()
    print(f"[4] next_passage after mastering short_vowels -> {passage2['id']} "
          f"(primary_skill={passage2['primary_skill']})")
    assert passage2["primary_skill"] != "short_vowels", "priority should have moved off the now-mastered skill"

    # --- 5. Comprehension-skill update sanity check on a second student, since
    #         comprehension uses correct/total rather than the miscue penalty formula. ---
    student2 = client.post("/students", json={"display_name": "Comp Kid", "grade": 3}).json()
    sid2 = student2["id"]
    comp_session_good = {
        "student_id": sid2,
        "passage_id": "g3-main-idea-001",
        "accuracy": 0.95,
        "miscues": [],
        "comprehension": [
            {"question": "What was the main idea?", "answer_given": "correct answer", "correct": True,
             "skill_id": "main_idea_and_summarizing"},
        ],
    }
    for _ in range(3):
        client.post("/sessions", json=comp_session_good)
    mastery3 = client.get(f"/students/{sid2}/mastery").json()
    w_comp = get_weight(mastery3, "main_idea_and_summarizing")
    print(f"main_idea_and_summarizing weight after 3 correct answers: {w_comp:.3f}")
    assert w_comp > 0.6, "3 consecutive correct comprehension answers should push weight up substantially"

    print("\nALL ASSERTIONS PASSED")


if __name__ == "__main__":
    try:
        main()
    except AssertionError as e:
        print(f"\nASSERTION FAILED: {e}")
        sys.exit(1)
