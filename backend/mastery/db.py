"""
DB setup for the mastery service.

Local dev (no DATABASE_URL set): SQLite file, schema in schema_sqlite.sql (a
syntax translation of ../../contracts/db_schema.sql -- see the comment at the
top of that file for exactly what changed and why; no table shape changed).

Production (DATABASE_URL set to a Supabase/Postgres connection string): real
Postgres, schema is contracts/db_schema.sql as-is. This module picks the
backend automatically based on whether DATABASE_URL is set, so nothing above
it (mastery.py, passage_selection.py, main.py) needs to know which one is
live -- with one honest exception: mastery.py's two `json.loads(row[
"prerequisite_of"])` calls now handle either a JSON string (SQLite, where
the column is plain text) or a native Python list (Postgres, where the
column is a real `text[]` and psycopg2 hands it back already parsed) --
see the comment at those two call sites. An earlier version of this
module's docstring claimed nothing above it would need to change at all;
that turned out to be very close but not quite true, so this note
corrects it rather than leaving a comment that no longer matches reality.
"""
import json
import os
import sqlite3
from contextlib import contextmanager
from pathlib import Path

import psycopg2
import psycopg2.extras
from dotenv import load_dotenv

# Real incident, fixed after it happened (see docs/BUILD_LOG.md):
# `override=True` here meant .env's DATABASE_URL always won over the shell's
# own environment, not the other way around - so `DATABASE_URL= python
# some_test_script.py`, the standard way to force the SQLite fallback for a
# genuinely isolated test run, silently did nothing once .env had a real
# DATABASE_URL in it, and every "isolated" test run actually hit the real,
# shared production database instead. `override=False` (load_dotenv's own
# default - explicit here so this doesn't quietly regress if someone "cleans
# up" this line later) only fills in a variable that ISN'T already set,
# which is the safe, standard precedence: the shell's own environment wins.
load_dotenv(override=False)

BACKEND_DIR = Path(__file__).resolve().parent
CONTRACTS_DIR = BACKEND_DIR.parent.parent / "contracts"
CONTENT_DIR = BACKEND_DIR.parent.parent / "content"
SQLITE_SCHEMA_PATH = BACKEND_DIR / "schema_sqlite.sql"
POSTGRES_SCHEMA_PATH = CONTRACTS_DIR / "db_schema.sql"
TAXONOMY_PATH = CONTENT_DIR / "skill_taxonomy.json"

DB_PATH = os.environ.get("MASTERY_DB_PATH", str(BACKEND_DIR / "mastery_dev.db"))
DATABASE_URL = os.environ.get("DATABASE_URL")


class _PlaceholderTranslatingCursor:
    """Wraps a real psycopg2 cursor so the sqlite-style `?` placeholders
    already written throughout mastery.py/passage_selection.py/main.py keep
    working unchanged against Postgres, which expects `%s`. A plain
    str.replace is safe here because no SQL string literal anywhere in this
    codebase contains a literal `?` character (verified by inspection, not
    assumed) -- there's nothing for the replace to corrupt.
    """

    def __init__(self, cur):
        self._cur = cur

    def execute(self, query, params=()):
        self._cur.execute(query.replace("?", "%s"), params)
        return self

    def executescript(self, script: str) -> None:
        # sqlite3.Cursor has executescript(); psycopg2 doesn't need a separate
        # method for it -- a plain execute() with no params already runs a
        # whole semicolon-separated batch via Postgres's simple query
        # protocol. This lets init_db() below call cur.executescript(...)
        # the same way regardless of which backend is live.
        self._cur.execute(script)

    def __getattr__(self, name):
        return getattr(self._cur, name)


def _sqlite_connection() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def _postgres_connection():
    return psycopg2.connect(DATABASE_URL, cursor_factory=psycopg2.extras.RealDictCursor)


def get_connection():
    return _postgres_connection() if DATABASE_URL else _sqlite_connection()


@contextmanager
def get_cursor():
    conn = get_connection()
    try:
        cur = conn.cursor()
        if DATABASE_URL:
            cur = _PlaceholderTranslatingCursor(cur)
        yield cur
        conn.commit()
    finally:
        conn.close()


def init_db() -> None:
    """Create tables (if needed) and load the skill taxonomy into `skills`.

    Safe to call every startup: table creation is idempotent (IF NOT EXISTS) and the
    taxonomy load is an upsert keyed on skill id, so re-running it just refreshes
    labels/categories/prerequisite_of edges from content/skill_taxonomy.json.
    """
    schema_path = POSTGRES_SCHEMA_PATH if DATABASE_URL else SQLITE_SCHEMA_PATH
    with get_cursor() as cur:
        cur.executescript(schema_path.read_text())
        _load_taxonomy(cur)


def _load_taxonomy(cur) -> None:
    taxonomy = json.loads(TAXONOMY_PATH.read_text())
    for skill in taxonomy:
        prerequisite_of = skill.get("prerequisite_of", [])
        cur.execute(
            """
            insert into skills (id, label, category, prerequisite_of)
            values (?, ?, ?, ?)
            on conflict(id) do update set
                label = excluded.label,
                category = excluded.category,
                prerequisite_of = excluded.prerequisite_of
            """,
            (
                skill["id"],
                skill["label"],
                skill["category"],
                # Postgres's prerequisite_of is a real text[] -- psycopg2 adapts a
                # plain Python list to it directly. SQLite's column is plain text,
                # so it still needs the JSON-encoding schema_sqlite.sql documents.
                prerequisite_of if DATABASE_URL else json.dumps(prerequisite_of),
            ),
        )


def reset_db_for_tests() -> None:
    """Wipe and rebuild storage. Only ever used by the dev test script."""
    if DATABASE_URL:
        with get_cursor() as cur:
            cur.execute(
                "truncate table sessions, student_skill_mastery, skills, students restart identity cascade"
            )
        init_db()
    else:
        try:
            os.remove(DB_PATH)
        except FileNotFoundError:
            pass
        init_db()
