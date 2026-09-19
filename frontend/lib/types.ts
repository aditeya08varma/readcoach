// Types mirror contracts/api_contract.md, contracts/passage_schema.json,
// contracts/voice_events.md, and contracts/db_schema.sql exactly.
// Keep these in lockstep with the contracts — if a contract changes, update here first.

export interface Student {
  id: string;
  display_name: string;
  grade: 1 | 2 | 3;
}

export interface Passage {
  id: string;
  grade: 1 | 2 | 3;
  title: string;
  source?: string;
  text: string;
  words: string[];
  skills: string[];
  primary_skill?: string;
  comprehension_hint_topics?: string[];
  // Additive - see docs/FEATURE_IDEAS.md's "why this story" idea. Absent on
  // older/mocked responses; render nothing when it's missing.
  selection_reason?: SelectionReason;
  // Additive - see docs/FEATURE_IDEAS.md's gameplay ideation. Index into
  // `words` for the reading screen's "challenge word" highlight/celebration.
  challenge_word_index?: number | null;
}

export interface SelectionReason {
  target_skill_id: string | null;
  target_skill_label: string | null;
  // "chosen" (a child picking their own story from the map, per
  // backend/mastery/passage_selection.py) was missing here - see the
  // matching note on lib/schemas.ts's SelectionReasonSchema for the real
  // bug this caused.
  mode: "priority_weak" | "maintenance" | "fallback" | "chosen";
  explanation: string;
}

export interface VoiceToken {
  session_id: string;
  daily_room_url: string;
  daily_token: string;
}

// GET /students/{id}/sessions
export interface SessionSummary {
  id: string;
  passage_id: string;
  started_at: string; // iso8601
  wcpm: number;
  accuracy: number;
  self_corrections: number;
  // Additive - see docs/FEATURE_IDEAS.md's "auto-generated parent session
  // recap" idea. Null for sessions ingested before this field existed, or
  // if the best-effort generation call failed.
  session_recap?: string | null;
}

// GET /students/{id}/mastery
export interface MasterySkill {
  skill_id: string;
  label: string;
  category: "phonics" | "vocabulary" | "comprehension" | string;
  weight: number; // 0..1
}

// GET /students/{id}/map
export interface MapPassageRef {
  id: string;
  title: string;
  grade: 1 | 2 | 3;
  attempted: boolean;
}

export interface MapSkillNode {
  skill_id: string;
  label: string;
  category: "phonics" | "vocabulary" | "comprehension" | string;
  weight: number; // 0..1
  passages: MapPassageRef[];
}

export interface MapCategory {
  category: "phonics" | "vocabulary" | "comprehension" | string;
  skills: MapSkillNode[];
}

export interface StoryMap {
  categories: MapCategory[];
}

// GET /admin/engineering_dashboard
export interface EngineeringDashboard {
  // stt_ms/tts_ms are genuinely null in real data today - no code anywhere
  // in the voice pipeline records per-stage timing yet, see main.py's
  // GET /admin/engineering_dashboard docstring. Honest gap, not a bug.
  latency_p50_ms: { stt_ms: number | null; llm_ms: number; tts_ms: number | null };
  latency_p95_ms: { stt_ms: number | null; llm_ms: number; tts_ms: number | null };
  eval: {
    diagnostic_accuracy: number;
    question_groundedness: number;
    sample_size: number;
  };
}

// ---- contracts/voice_events.md ----

export type MiscueType =
  | "substitution"
  | "omission"
  | "insertion"
  | "self_correction";

export interface PassageLoadedEvent {
  type: "passage_loaded";
  t: number;
  // Real bug this fixes, found during real testing: the frontend used to
  // fetch its own passage independently from a placeholder student id, with
  // no relation to whatever the bot actually picked for this live session -
  // see contracts/voice_events.md's passage_loaded entry for the full story.
  passage: Passage;
}

export interface WordRecognizedEvent {
  type: "word_recognized";
  t: number;
  word: string;
  start_ms: number;
  end_ms: number;
  confidence: number;
}

export interface MiscueDetectedEvent {
  type: "miscue_detected";
  t: number;
  reference_index: number;
  reference_word: string;
  spoken_word: string;
  miscue_type: MiscueType;
  skill_id: string;
}

export interface HintSpokenEvent {
  type: "hint_spoken";
  t: number;
  skill_id: string;
  text: string;
}

// Emitted once per word during the end-of-passage review pass (see
// backend/tutor/state_machine.py's REVIEW state and contracts/
// voice_events.md) - not currently rendered (the spoken encouragement line
// covers it live), kept in the union so a future per-word confirmation UI
// doesn't need a contract change to add it.
export interface ReviewWordResultEvent {
  type: "review_word_result";
  t: number;
  reference_index: number;
  reference_word: string | null;
  correct: boolean;
}

export interface PassageCompleteEvent {
  type: "passage_complete";
  t: number;
  wcpm: number;
  accuracy: number;
  self_corrections: number;
}

export interface ComprehensionTurnEvent {
  type: "comprehension_turn";
  t: number;
  question: string;
  answer_given: string;
  correct: boolean;
  skill_id: string;
}

export interface SessionEndedEvent {
  type: "session_ended";
  t: number;
  session_id: string;
  passage_id: string;
  pipeline_latency_ms: { stt_ms: number; llm_ms: number; tts_ms: number };
}

export type VoiceEvent =
  | PassageLoadedEvent
  | WordRecognizedEvent
  | MiscueDetectedEvent
  | HintSpokenEvent
  | ReviewWordResultEvent
  | PassageCompleteEvent
  | ComprehensionTurnEvent
  | SessionEndedEvent;

// Data source indicator, surfaced in the UI so it's always clear whether a
// screen is looking at the real backend or a local mock.
export type DataSource = "live" | "mock";

export interface Sourced<T> {
  data: T;
  source: DataSource;
}
