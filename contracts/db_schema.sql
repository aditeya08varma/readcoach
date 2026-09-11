-- ReadCoach database schema (Postgres / Supabase)
-- Owned by mastery-engineer. Read by tutor-logic-engineer (writes session rows,
-- reads mastery for passage selection) and frontend-engineer (dashboards read-only).
-- Any change to this file is a breaking contract change: flag it to the orchestrator
-- before editing table shapes other agents already depend on.

create table if not exists students (
    id            uuid primary key default gen_random_uuid(),
    display_name  text not null,
    grade         integer not null check (grade between 1 and 3),
    created_at    timestamptz not null default now()
);

-- One row per skill in the taxonomy (content/skill_taxonomy.json is the source of
-- truth for *which* skills exist and their prerequisite edges; this table is the
-- queryable mirror content-curator's taxonomy gets loaded into).
create table if not exists skills (
    id              text primary key,          -- matches taxonomy skill id, e.g. "short_vowels"
    label           text not null,
    category        text not null,             -- "phonics" | "vocabulary" | "comprehension"
    prerequisite_of text[] not null default '{}'  -- array of skill ids this skill unlocks
);

-- Current mastery weight per student per skill. Updated after every session by the
-- mastery-engineer's update rule. Weight is a float in [0, 1]; 0 = unassessed/weak,
-- 1 = mastered.
create table if not exists student_skill_mastery (
    student_id  uuid not null references students(id) on delete cascade,
    skill_id    text not null references skills(id),
    weight      real not null default 0.0 check (weight between 0.0 and 1.0),
    updated_at  timestamptz not null default now(),
    primary key (student_id, skill_id)
);

-- One row per completed reading session. `miscues` and `comprehension` are jsonb so
-- tutor-logic-engineer can evolve their internal shape without a migration, but the
-- top-level keys below are the stable contract other agents may rely on.
create table if not exists sessions (
    id                  uuid primary key default gen_random_uuid(),
    student_id          uuid not null references students(id) on delete cascade,
    passage_id          text not null,          -- matches Passage.id from contracts/passage_schema.json
    started_at          timestamptz not null default now(),
    ended_at            timestamptz,
    wcpm                real,                   -- words correct per minute
    accuracy            real,                   -- 0..1
    self_corrections    integer default 0,
    -- jsonb array of {word, index, type: "substitution"|"omission"|"insertion"|"self_correction", skill_id, timestamp_ms}
    miscues             jsonb not null default '[]',
    -- jsonb array of {question, answer_given, correct, skill_id}
    comprehension       jsonb not null default '[]',
    -- per-stage latency in ms, e.g. {"stt_ms": 180, "llm_ms": 420, "tts_ms": 90}, for the engineering dashboard
    pipeline_latency_ms jsonb,
    -- additive, added for the auto-generated parent recap idea (docs/FEATURE_IDEAS.md):
    -- a short Claude-written summary of this session for the parent dashboard. Null if
    -- generated before this column existed, or if that best-effort call failed.
    session_recap text,
    -- additive, added to surface the mastery-aware hint pacing decision
    -- (docs/FEATURE_IDEAS.md) outside the live moment it happens: how many times a
    -- hint was deliberately delayed this session, and how many of those resolved on
    -- their own (a self-correction) before the delay ran out.
    hints_delayed_count integer not null default 0,
    hints_delayed_self_corrected_count integer not null default 0
);

-- Idempotent migrations for a database created before these columns existed
-- (CREATE TABLE IF NOT EXISTS above doesn't retroactively add columns to an
-- already-existing table) - safe to re-run against a fresh database too.
alter table sessions add column if not exists session_recap text;
alter table sessions add column if not exists hints_delayed_count integer not null default 0;
alter table sessions add column if not exists hints_delayed_self_corrected_count integer not null default 0;

create index if not exists idx_sessions_student on sessions(student_id, started_at desc);
