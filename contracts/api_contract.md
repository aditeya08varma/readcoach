# Frontend <-> Backend API Contract

Owned jointly: `frontend-engineer` consumes this; whichever backend agent implements an
endpoint (mostly `mastery-engineer` and `tutor-logic-engineer`) must match it exactly or
flag the orchestrator to change it here first. `frontend-engineer` may build against a
mock server matching this contract before the real backend exists.

Base URL: backend FastAPI service, e.g. `http://localhost:8000` in dev.

## `POST /students`
Create a student profile.
Request: `{ "display_name": string, "grade": 1|2|3 }`
Response: `{ "id": uuid, "display_name": string, "grade": int }`

## `GET /students/{id}/next_passage`
Mastery-engine picks the next passage for this student (highest-priority weak
prerequisite skill with an available tagged passage — see the mastery update rule).
Response: a full `Passage` object per `contracts/passage_schema.json`, plus one
additive optional field:
```json
"selection_reason": {
  "target_skill_id": "string|null",
  "target_skill_label": "string|null",
  "mode": "priority_weak|maintenance|fallback",
  "explanation": "string"
}
```
Plain-language explanation of why this passage was picked (see
docs/FEATURE_IDEAS.md's "why this story" idea) — purely descriptive, computed by
templating over numbers the mastery engine already has, no AI call. Frontend should
render it if present and degrade gracefully (e.g. show nothing) if absent, since
older/mocked responses won't have it.

Also additive: `"challenge_word_index": integer|null`, an index into `words` for the
reading screen's "challenge word" highlight/celebration (see docs/FEATURE_IDEAS.md's
gameplay ideation) — purely cosmetic, never affects selection or scoring.

## `POST /sessions/{id}/voice_token`
Still not built — this was the originally planned Daily-room-based flow (backend
creates a Daily room + token, frontend joins with the Daily client SDK, bot is started
for that room). Superseded for now by a simpler real connection, documented honestly
below rather than left silently unbuilt with no explanation.

**What actually connects the frontend to the voice bot today:** the bot process
(`backend/voice/bot.py`, run with `-t webrtc`) serves its own local dev server with a
`POST /api/offer` WebRTC signaling endpoint (Pipecat's own dev runner, not custom
code). The frontend (`frontend/lib/voiceEventStream.ts`'s `createLiveVoiceEventSource`)
connects to it directly using `@pipecat-ai/client-js` + `@pipecat-ai/small-webrtc-transport`,
at `NEXT_PUBLIC_VOICE_BOT_URL` (default `http://localhost:7860`) — no room, no token,
no `student_id`/`passage_id` request needed, since there's exactly one bot process and
it already self-selects a passage via its own `GET /students/{id}/next_passage` call
(see the map-choosable-passage note above for why that self-selection still can't be
overridden). This is a real, working, tested connection — not a stand-in — chosen
because it reuses the exact bot process already proven correct rather than requiring
Daily room orchestration (creating rooms via Daily's API, managing bot process
lifecycle per session) that was never built. Revisit `POST /sessions/{id}/voice_token`
and real Daily rooms only if this ever needs to support more than one concurrent
session.

Once connected, the frontend receives the `contracts/voice_events.md` event stream as
real-time `serverMessage`s over the same connection — Pipecat's RTVIProcessor is what
makes this transport-agnostic (works the same whether the bot ends up running on
webrtc or Daily later). A real, previously undiscovered bug was found and fixed while
wiring this up for the first time: `backend/voice/tutor_processor.py`'s `_emit` used
to build a Daily-specific message frame directly, which the webrtc transport (the only
one ever actually tested with a live client before now) had no way to deliver — audio
worked, but not one event ever reached a browser. See `docs/BUILD_LOG.md` for the full
story and how this was proven fixed.

## `GET /students/{id}/sessions`
Session history for the parent/teacher dashboard. Was documented but not yet
implemented as of the first integration pass — implemented for real alongside the
auto-generated recap feature below. Ordered oldest first (ascending `started_at`) —
`frontend-engineer`'s dashboard picks the latest session as the last array element;
this was a real ordering mismatch caught when the endpoint went from mocked to real.
Response: array of
```json
{
  "id": uuid,
  "passage_id": string,
  "started_at": iso8601,
  "wcpm": number,
  "accuracy": number,
  "self_corrections": number,
  "session_recap": "string|null"
}
```
`session_recap` is additive: a short, warm, plain-language Claude-written summary of
the session for a parent (see docs/FEATURE_IDEAS.md's "auto-generated parent session
recap" idea), generated once at ingestion time in `POST /sessions` and stored. Null
for sessions ingested before this field existed, or if that best-effort generation
call failed — frontend should hide the recap block rather than show an empty one in
that case.

## `GET /students/{id}/mastery`
Current skill mastery vector for the dashboard's radar/bar chart.
Response: array of `{ "skill_id": string, "label": string, "category": string, "weight": number }`

## `GET /students/{id}/passages/{passage_id}`
A real person explicitly picked this exact passage — the story map's tap-a-node flow
(see docs/FEATURE_IDEAS.md's gameplay ideation), rather than the mastery engine
auto-selecting one. Same response shape as `GET /students/{id}/next_passage`
(`NextPassageResponse`), with `selection_reason.mode` = `"chosen"` instead of an
auto-selection rule. 404 if `passage_id` doesn't exist in the content library.

**How the voice bot actually learns of an explicit story choice.** The originally
planned mechanism — passing `passage_id` as `requestData` on the WebRTC connection
request (`client.connect({ webrtcRequestParams: { endpoint, requestData } })`),
forwarded by Pipecat's runner as `runner_args.body` — was built, tested for real with
a live bot and a real connection, and confirmed empirically broken: `runner_args.body`
arrived as `None` on every real attempt in this client/server version combination
(client-js 1.13.1 / small-webrtc-transport 1.10.7 / pipecat-ai 1.8.1), not a config
mistake on this project's side. Rather than depend on an upstream passthrough that
doesn't work, the bot exposes its own small custom route instead, added directly to
Pipecat's runner `app` (a documented extension point — see `pipecat.runner.run.app`):

```
POST /choose_passage   { "passage_id": "string" }   -> { "ok": true, "passage_id": "string" }
```

The frontend calls this on the bot's own server (same host/port as `/api/offer`)
immediately before opening the WebRTC connection. The bot reads it once, for the very
next connection only, then clears it — an honest fit for this project's existing
scope (one bot process, one session at a time; no concurrent-session support exists
anywhere else in this project either). If never called, the bot auto-selects exactly
as before — this is additive, not a replacement for auto-selection.

## `GET /students/{id}/map`
Story map data for the "gameplay" reading screen (see docs/FEATURE_IDEAS.md's
gameplay ideation) — skills grouped by category, in priority order, each with the
student's real mastery weight and which of that skill's passages (at the student's
own grade) they've attempted. Pure aggregation of data that already exists
elsewhere; no new data model, no AI call.

Response:
```json
{
  "categories": [
    {
      "category": "phonics|vocabulary|comprehension",
      "skills": [
        {
          "skill_id": "string",
          "label": "string",
          "category": "string",
          "weight": number,
          "passages": [
            { "id": "string", "title": "string", "grade": integer, "attempted": boolean }
          ]
        }
      ]
    }
  ]
}
```

Update: tapping a node's passage now does start a session with that specific
passage — see `GET /students/{id}/passages/{passage_id}` above for how a chosen
`passage_id` reaches the voice bot without needing `POST /sessions/{id}/voice_token`
(still not built) or real Daily room orchestration at all.

## `GET /admin/engineering_dashboard`
Aggregate pipeline latency (P50/P95 per stage) and eval scores across recent sessions,
for the engineering view. Not student-specific.
Response:
```json
{
  "latency_p50_ms": { "stt_ms": number, "llm_ms": number, "tts_ms": number },
  "latency_p95_ms": { "stt_ms": number, "llm_ms": number, "tts_ms": number },
  "eval": { "diagnostic_accuracy": number, "question_groundedness": number, "sample_size": number }
}
```

## `POST /sessions`
Delivers a completed reading session's scored data into storage and triggers the
mastery update rule. Called by `tutor-logic-engineer`'s tutor state machine once a
passage/comprehension turn finishes. Implemented by `mastery-engineer` (this was
originally a gap in this contract; `mastery-engineer` flagged it and built a stand-in
at `POST /internal/sessions` which this entry formalizes at its real path, same shape,
no changes needed on that side).

Request:
```json
{
  "student_id": "uuid",
  "passage_id": "string",
  "wcpm": number | null,
  "accuracy": number | null,
  "self_corrections": integer,
  "miscues": [
    { "word": "string", "index": integer, "type": "substitution|omission|insertion|self_correction", "skill_id": "string|null", "timestamp_ms": integer|null }
  ],
  "comprehension": [
    { "question": "string", "answer_given": "string", "correct": boolean, "skill_id": "string|null" }
  ],
  "pipeline_latency_ms": { "stt_ms": number, "llm_ms": number, "tts_ms": number } | null,
  "hints_delayed_count": integer,
  "hints_delayed_self_corrected_count": integer
}
```
The last two fields are additive (default `0`), surfacing the mastery-aware hint pacing
decision (see `contracts/voice_events.md`'s `hint_pending` event) outside the live
session it happens in — used by the auto-generated recap and, later, an engineering
metric. Both default to `0` so older callers that don't send them keep working.

Response:
```json
{
  "session_id": "uuid",
  "updates": [
    { "skill_id": "string", "session_score": number, "old_weight": number, "new_weight": number, "direct": boolean }
  ]
}
```

## `GET /admin/eval_report`
Owned by `eval-engineer`. Returns the latest scored benchmark run (see Stage 6 of the
build plan). Response shape is up to `eval-engineer` to define, but must include at
minimum `diagnostic_accuracy`, `question_groundedness`, and `latency_percentiles` so
`/admin/engineering_dashboard` can summarize it.
