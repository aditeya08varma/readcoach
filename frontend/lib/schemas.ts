// Zod runtime-validation schemas mirroring lib/types.ts, which itself
// mirrors contracts/api_contract.md, contracts/passage_schema.json, and
// contracts/voice_events.md exactly. Keep these in lockstep with lib/types.ts
// the same way that file is kept in lockstep with the contracts.
//
// Both lib/api.ts (backend HTTP responses) and lib/voiceEventStream.ts (live
// WebRTC server messages) used to do a bare `as T`/`as VoiceEvent` cast with
// zero runtime check - a real gap found by audit, since `zod` was already a
// listed dependency nothing actually used. A backend/contract drift, or a
// malformed live message, would previously corrupt in-memory state (or throw
// deeper inside a component with a confusing stack) instead of being caught
// right at the boundary and handled the same deliberate way an unreachable
// backend already is.

import { z } from "zod";

export const GradeSchema = z.union([z.literal(1), z.literal(2), z.literal(3)]);

export const StudentSchema = z.object({
  id: z.string(),
  display_name: z.string(),
  grade: GradeSchema,
});

export const SelectionReasonSchema = z.object({
  target_skill_id: z.string().nullable(),
  target_skill_label: z.string().nullable(),
  // Real bug found live while staging a demo recording: passage_selection.py
  // emits a 4th real mode, "chosen" (backend/mastery/passage_selection.py:171)
  // - fired whenever a child picks their own story from the map instead of
  // getting an auto-selected one - that this schema didn't list. Every
  // "chosen" passage therefore failed validation and silently fell back to
  // mock data, which is exactly backwards: the schema should be as complete
  // as the real contract, not narrower than it.
  mode: z.enum(["priority_weak", "maintenance", "fallback", "chosen"]),
  explanation: z.string(),
});

export const PassageSchema = z.object({
  id: z.string(),
  grade: GradeSchema,
  title: z.string(),
  source: z.string().optional(),
  text: z.string(),
  words: z.array(z.string()),
  skills: z.array(z.string()),
  primary_skill: z.string().optional(),
  comprehension_hint_topics: z.array(z.string()).optional(),
  selection_reason: SelectionReasonSchema.optional(),
  challenge_word_index: z.number().nullable().optional(),
});

export const VoiceTokenSchema = z.object({
  session_id: z.string(),
  daily_room_url: z.string(),
  daily_token: z.string(),
});

export const SessionSummarySchema = z.object({
  id: z.string(),
  passage_id: z.string(),
  started_at: z.string(),
  wcpm: z.number(),
  accuracy: z.number(),
  self_corrections: z.number(),
  session_recap: z.string().nullable().optional(),
});
export const SessionSummaryListSchema = z.array(SessionSummarySchema);

export const MasterySkillSchema = z.object({
  skill_id: z.string(),
  label: z.string(),
  category: z.string(),
  weight: z.number(),
});
export const MasterySkillListSchema = z.array(MasterySkillSchema);

const MapPassageRefSchema = z.object({
  id: z.string(),
  title: z.string(),
  grade: GradeSchema,
  attempted: z.boolean(),
});

const MapSkillNodeSchema = z.object({
  skill_id: z.string(),
  label: z.string(),
  category: z.string(),
  weight: z.number(),
  passages: z.array(MapPassageRefSchema),
});

const MapCategorySchema = z.object({
  category: z.string(),
  skills: z.array(MapSkillNodeSchema),
});

export const StoryMapSchema = z.object({
  categories: z.array(MapCategorySchema),
});

const LatencyStatsSchema = z.object({
  stt_ms: z.number().nullable(),
  llm_ms: z.number(),
  tts_ms: z.number().nullable(),
});

export const EngineeringDashboardSchema = z.object({
  latency_p50_ms: LatencyStatsSchema,
  latency_p95_ms: LatencyStatsSchema,
  eval: z.object({
    diagnostic_accuracy: z.number(),
    question_groundedness: z.number(),
    sample_size: z.number(),
  }),
});

// ---- contracts/voice_events.md ----

const MiscueTypeSchema = z.enum([
  "substitution",
  "omission",
  "insertion",
  "self_correction",
]);

const PassageLoadedEventSchema = z.object({
  type: z.literal("passage_loaded"),
  t: z.number(),
  passage: PassageSchema,
});

const WordRecognizedEventSchema = z.object({
  type: z.literal("word_recognized"),
  t: z.number(),
  word: z.string(),
  start_ms: z.number(),
  end_ms: z.number(),
  confidence: z.number(),
});

const MiscueDetectedEventSchema = z.object({
  type: z.literal("miscue_detected"),
  t: z.number(),
  reference_index: z.number(),
  reference_word: z.string(),
  spoken_word: z.string(),
  miscue_type: MiscueTypeSchema,
  skill_id: z.string(),
});

const HintSpokenEventSchema = z.object({
  type: z.literal("hint_spoken"),
  t: z.number(),
  skill_id: z.string(),
  text: z.string(),
});

const ReviewWordResultEventSchema = z.object({
  type: z.literal("review_word_result"),
  t: z.number(),
  reference_index: z.number(),
  reference_word: z.string().nullable(),
  correct: z.boolean(),
});

const PassageCompleteEventSchema = z.object({
  type: z.literal("passage_complete"),
  t: z.number(),
  wcpm: z.number(),
  accuracy: z.number(),
  self_corrections: z.number(),
});

const ComprehensionTurnEventSchema = z.object({
  type: z.literal("comprehension_turn"),
  t: z.number(),
  question: z.string(),
  answer_given: z.string(),
  correct: z.boolean(),
  skill_id: z.string(),
});

const SessionEndedEventSchema = z.object({
  type: z.literal("session_ended"),
  t: z.number(),
  session_id: z.string(),
  passage_id: z.string(),
  pipeline_latency_ms: z.object({
    stt_ms: z.number(),
    llm_ms: z.number(),
    tts_ms: z.number(),
  }),
});

export const VoiceEventSchema = z.discriminatedUnion("type", [
  PassageLoadedEventSchema,
  WordRecognizedEventSchema,
  MiscueDetectedEventSchema,
  HintSpokenEventSchema,
  ReviewWordResultEventSchema,
  PassageCompleteEventSchema,
  ComprehensionTurnEventSchema,
  SessionEndedEventSchema,
]);
