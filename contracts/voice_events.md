# Voice Pipeline Event Contract

Owned by `voice-pipeline-engineer`. This is the event stream the Pipecat bot process
(`backend/voice/`) emits internally and forwards to the frontend over the Pipecat/Daily
data channel. `tutor-logic-engineer` and `frontend-engineer` consume these — do not
rename fields or change types without flagging the orchestrator, since both of those
modules are built against this shape.

All events are JSON objects with a `type` discriminator and a `t` field (ms since
session start, monotonic).

## `passage_loaded`
Emitted once, immediately on connection (before the greeting), carrying the exact
passage the bot picked via its own `GET /students/{id}/next_passage` call. Real bug
this fixes, found during real testing: the frontend used to fetch its own passage
independently (from a placeholder student id that doesn't exist in the real database,
so it silently rendered a local mock story), completely unrelated to whatever the bot
actually picked for the live session - meaning the child would see one story on
screen while the bot compared their speech against a *different* one, misreading
nearly every word as a miscue. The frontend must treat this event's `passage` as
authoritative the moment it arrives, replacing whatever it rendered initially.
```json
{ "type": "passage_loaded", "t": 0, "passage": { "...": "full Passage object, same shape GET /students/{id}/next_passage returns, including its additive selection_reason/challenge_word_index fields" } }
```

## `word_recognized`
Emitted by the STT stage the moment Deepgram finalizes a word (not on interim/partial
results — only finalized words drive alignment and highlighting).
```json
{
  "type": "word_recognized",
  "t": 1234,
  "word": "fox",
  "start_ms": 1180,
  "end_ms": 1234,
  "confidence": 0.93
}
```

## `miscue_detected`
Emitted by the alignment engine (backend/tutor, but travels back through the voice
event stream so the frontend can highlight live) after diffing `word_recognized`
against the passage's `words` array from `contracts/passage_schema.json`.
```json
{
  "type": "miscue_detected",
  "t": 1240,
  "reference_index": 12,
  "reference_word": "friend",
  "spoken_word": "fren",
  "miscue_type": "substitution",
  "skill_id": "vowel_teams"
}
```
`miscue_type` is one of: `substitution`, `omission`, `insertion`, `self_correction`.
Purely for live visual tracking during reading now (the frontend's word-by-word
highlight) - nothing is spoken off of this live anymore, see `hint_spoken` below.

## `hint_pending` (removed)
Used to fire the moment a hint was deliberately delayed under the old mastery-aware
mid-read pacing. Removed along with that whole mechanism (see `hint_spoken` below) -
real feedback from a real reading session, not a guess: interjecting a spoken
correction mid-word ("boat", "paddled") read as talking over the child, not helping,
even with the delay. No replacement event; a client that still expects this will
simply never receive it.

## `hint_spoken`
Emitted twice now, not once: once per LLM-generated line of encouragement/feedback
during the post-passage comprehension turn (unchanged), and once per word during the
new end-of-passage review pass (see `review_word_result` below) - teaching one real,
uncorrected stumble at a time, in passage order, only after the whole passage has been
read, never mid-sentence. Same shape either way; the frontend's existing coach-bubble
UI needs no changes to show either kind.
```json
{ "type": "hint_spoken", "t": 1500, "skill_id": "vowel_teams", "text": "Let's sound that one out: f-r-ie-nd." }
```

## `review_word_result`
Emitted once per word during the end-of-passage review, right after the child says a
previously-missed word again in response to a `hint_spoken` teaching it. `correct`
reflects a fuzzy match (tolerant of minor STT noise, not exact), not a full second
alignment pass. Not currently rendered by the frontend (the spoken encouragement line
covers it live) - kept in the contract as real, useful per-word signal for a future
UI (e.g. re-coloring the word once confirmed) rather than only living in a TTS line
nobody can see after the fact.
```json
{ "type": "review_word_result", "t": 1620, "reference_index": 12, "reference_word": "friend", "correct": true }
```

## `passage_complete`
Emitted when the child finishes the passage (silence timeout after the last reference
word, or explicit "done" turn signal).
```json
{ "type": "passage_complete", "t": 42000, "wcpm": 58.2, "accuracy": 0.91, "self_corrections": 2 }
```

## `comprehension_turn`
One per answer submitted in the post-passage phase - usually one per question, but a
wrong first attempt gets exactly one retry (the same question repeated, see
`state_machine.py`'s `submit_answer`), which emits a second `comprehension_turn` for
that same question before it's finalized. Only the FINAL attempt for a given question
is ever persisted to the `sessions` table's `comprehension` column (`session_ended`
below) - a retried question still contributes exactly one row there, never two.
```json
{
  "type": "comprehension_turn",
  "t": 45000,
  "question": "Why was the fox hungry?",
  "answer_given": "because he didn't eat breakfast",
  "correct": true,
  "skill_id": "inferential_comprehension",
  "feedback_text": "That's right, nice work!"
}
```
`feedback_text` (optional, added during integration) is the warm spoken response to
play back to the child via TTS, produced by the same grading call that decided
`correct` - added so the voice pipeline doesn't need a second LLM call just to have
something to say after grading.

## `session_ended`
Terminal event; carries the full summary tutor-logic-engineer/mastery-engineer persist
to the `sessions` table (see `contracts/db_schema.sql`) and mastery-engineer consumes
to update `student_skill_mastery`.
```json
{
  "type": "session_ended",
  "t": 52000,
  "session_id": "uuid",
  "passage_id": "g2-blends-003",
  "pipeline_latency_ms": { "stt_ms": 180, "llm_ms": 420, "tts_ms": 90 }
}
```

## Turn-based fallback mode

If the Stage 0 checkpoint determines full-duplex streaming isn't reliable, the bot
runs in push-to-talk mode instead: the same event types are still emitted, just in
batches after each recorded turn completes rather than incrementally word-by-word.
Consumers should not assume `word_recognized` events arrive strictly one at a time in
real time — treat gaps as normal in fallback mode.
