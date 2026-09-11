"""Claude wrapper for the auto-generated parent session recap (see
docs/FEATURE_IDEAS.md's "Auto-generated parent session recap" quick win).

A small, single-purpose call over data POST /sessions already receives, not
a new data pipeline - mirrors backend/tutor/claude_client.py's pattern (same
fast model tier, same "one narrow call, not a chat loop" philosophy) rather
than introducing a second, different way of calling Claude in this project.
"""

from __future__ import annotations

from anthropic import AsyncAnthropic

FAST_MODEL = "claude-haiku-4-5"  # matches backend/tutor/claude_client.py's FAST_MODEL

RECAP_SYSTEM_PROMPT = (
    "You are writing a two or three sentence summary of a child's (grades 1-3) "
    "reading practice session for their parent. Warm, plain language, no jargon, "
    "no emojis. Mention what skill or skills they worked on and one specific "
    "positive (a self-correction, a comprehension answer, strong accuracy) if "
    "the facts support it. Use ONLY the facts given below - never invent a "
    "detail that isn't there. Respond with ONLY the summary text, no preamble, "
    "no markdown."
)


async def generate_session_recap(
    *,
    api_key: str,
    passage_title: str,
    wcpm: float | None,
    accuracy: float | None,
    self_corrections: int,
    skill_labels_practiced: list[str],
    comprehension_correct: int,
    comprehension_total: int,
    hints_delayed_count: int = 0,
    hints_delayed_self_corrected_count: int = 0,
) -> str:
    client = AsyncAnthropic(api_key=api_key)
    facts = (
        f"Story: {passage_title}\n"
        f"Words correct per minute: {wcpm if wcpm is not None else 'not measured'}\n"
        f"Reading accuracy: {f'{accuracy:.0%}' if accuracy is not None else 'not measured'}\n"
        f"Self-corrections (child caught their own mistake): {self_corrections}\n"
        f"Skills practiced: {', '.join(skill_labels_practiced) if skill_labels_practiced else 'general reading'}\n"
        f"Comprehension questions: {comprehension_correct} correct out of {comprehension_total}\n"
    )
    # Additive, see docs/FEATURE_IDEAS.md's hint-pacing surfacing idea. Only
    # mention this when it actually happened - testing found the "caught it
    # themselves after waiting" case is real but rare with the current
    # aligner, so the fact given here is deliberately just "we gave extra
    # time," never a claim that the child caught it, unless that count is
    # itself nonzero.
    if hints_delayed_count > 0:
        facts += (
            f"The tutor deliberately gave extra time before hinting on "
            f"{hints_delayed_count} tricky word(s) this child is already fairly "
            f"strong at, instead of jumping in right away"
        )
        if hints_delayed_self_corrected_count > 0:
            facts += f", and the child caught {hints_delayed_self_corrected_count} of those on their own"
        facts += ".\n"
    resp = await client.messages.create(
        model=FAST_MODEL,
        max_tokens=150,
        system=RECAP_SYSTEM_PROMPT,
        messages=[{"role": "user", "content": facts}],
    )
    return resp.content[0].text.strip()
