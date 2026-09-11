-- Auth-only table, owned by the frontend, living in the same Supabase
-- Postgres instance backend/mastery already uses (see contracts/db_schema.sql
-- for the real, shared contract - that file is owned by mastery-engineer and
-- this table is never read by backend/mastery or backend/voice, so it does
-- not belong there).
--
-- One row per parent login. One login = one student (hackathon scope - no
-- multi-child-per-parent support, matching the app's existing
-- single-student-everywhere architecture). student_id is a normal FK into
-- the real students table, created via the existing POST /students endpoint
-- at signup time (frontend/lib/api.ts's createStudent()), not duplicated
-- here - display_name/grade are cached alongside it purely so the session
-- object can be built from one query instead of two.
--
-- Applied once, by hand: psql "$DATABASE_URL" -f frontend/db/schema.sql
create table if not exists app_users (
    id            uuid primary key default gen_random_uuid(),
    email         text not null unique,
    password_hash text not null,
    student_id    uuid not null references students(id) on delete cascade,
    display_name  text not null,
    grade         integer not null check (grade between 1 and 3),
    created_at    timestamptz not null default now()
);
