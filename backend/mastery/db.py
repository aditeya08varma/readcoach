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
import psycopg2.pool
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


class PoolExhaustedError(Exception):
    """Raised when every connection in the pg pool is checked out. A typed
    exception (rather than letting the raw psycopg2.pool.PoolError through)
    so main.py can register one FastAPI exception handler for it instead of
    needing every single `with db.get_cursor()` call site to remember to
    catch it individually."""


_pg_pool: psycopg2.pool.ThreadedConnectionPool | None = None


def _get_pg_pool() -> psycopg2.pool.ThreadedConnectionPool:
    # Real, measured incident: every request used to open its own fresh
    # psycopg2.connect() against Supabase and close it again at the end of
    # get_cursor() - a plain `select 1` on a brand-new connection measured
    # at ~520ms (mostly TLS + Postgres auth handshake), on every single API
    # call, some endpoints (ingest_session) paying it twice. A pool opens a
    # small number of real connections once, at first use, and hands them
    # out/back per request instead - the handshake cost is paid a handful
    # of times total instead of once per request. ThreadedConnectionPool
    # specifically (not SimpleConnectionPool) because FastAPI runs sync def
    # endpoints in a worker threadpool, so concurrent requests really can
    # call getconn/putconn from different threads at once.
    #
    # maxconn=3, not 10: a second real, live-reproduced incident. dev.sh
    # runs this service as 4 separate OS processes (--workers 4), each with
    # its OWN pool (pools are per-process, per the comment there) - so the
    # old maxconn=10 meant up to 40 possible real connections to Postgres
    # at once. DATABASE_URL here points at Supabase's session-mode pooler
    # (port 5432), which caps concurrent clients at 15 total, well under
    # 40. A 60-request concurrent burst against the old settings reproduced
    # this directly: 46 connection-refused, 13 bare 500s, 1 success, with
    # Postgres itself rejecting the connection ("FATAL: (EMAXCONNSESSION)
    # max clients reached in session mode - max clients are limited to
    # pool_size: 15"). 4 workers x maxconn=3 = 12 possible connections,
    # safely under the real 15-client ceiling with margin for a manual
    # psql session or another tool connecting at the same time. If this
    # service ever needs more real throughput than that, the correct fix
    # is switching DATABASE_URL to Supabase's transaction-mode pooler (port
    # 6543), which multiplexes many app connections onto far fewer physical
    # backend connections instead of 1:1 - not done here since it drops
    # session-level features (SET, advisory locks held across statements)
    # this module hasn't been audited against, and 12 connections is ample
    # for this project's actual demo-scale traffic.
    global _pg_pool
    if _pg_pool is None:
        _pg_pool = psycopg2.pool.ThreadedConnectionPool(
            1, 3, DATABASE_URL, cursor_factory=psycopg2.extras.RealDictCursor
        )
    return _pg_pool


@contextmanager
def get_cursor():
    if not DATABASE_URL:
        conn = _sqlite_connection()
        try:
            yield conn.cursor()
            conn.commit()
        finally:
            conn.close()
        return

    pool = _get_pg_pool()
    # Real bug found live (reproduced directly against this pool: 10
    # concurrent getconn()s succeed, an 11th raises immediately): getconn()
    # used to sit OUTSIDE this try block entirely. Unlike a real database
    # query timing out, ThreadedConnectionPool.getconn() raises
    # psycopg2.pool.PoolError the instant every connection is checked out -
    # it doesn't block or queue - and with no try around it, that exception
    # went straight up through get_cursor() uncaught. That's the exact same
    # failure shape this module's own docstring and main.py's
    # _validate_student_id_shape already document for the UUID bug: an
    # exception raised too deep for CORSMiddleware to attach headers to, so
    # the browser sees a plain network failure instead of a real, readable
    # error. Catching it here and re-raising as the typed PoolExhaustedError
    # lets main.py turn it into an honest 503 with CORS headers intact via
    # one exception handler, instead of a 500 with none.
    try:
        conn = pool.getconn()
    except psycopg2.pool.PoolError as e:
        raise PoolExhaustedError(str(e)) from e
    except psycopg2.OperationalError as e:
        # The other real shape this can fail in: getconn() successfully
        # gets past the LOCAL pool's own maxconn check but then opens a
        # brand-new physical connection (the pool's first-use / replace-a-
        # broken-connection path) and Supabase's own upstream pooler
        # refuses it - "max clients reached in session mode". This is a
        # genuine DB-side rejection, not a Python-level pool state, so
        # psycopg2 raises OperationalError here, not PoolError - the old
        # handler above only caught the latter, so this exact failure fell
        # through uncaught into a bare 500 with no CORS headers, live-
        # reproduced under a concurrent burst (see maxconn's comment
        # above). Folded into the same PoolExhaustedError/503 path since
        # from the caller's point of view it's the same "try again in a
        # moment" situation, whichever side actually said no.
        raise PoolExhaustedError(str(e)) from e
    broken = False
    try:
        yield _PlaceholderTranslatingCursor(conn.cursor())
        conn.commit()
    except psycopg2.Error as e:
        # Real, reproduced incident: Supabase silently closes a connection
        # that's sat idle in the pool for a while ("server closed the
        # connection unexpectedly") - putconn()'ing it back healthy would
        # hand that same dead connection to the next request, and the one
        # after that, every one of them 500ing the same way until the pool
        # happened to cycle it out. `pgcode` is the distinguishing signal:
        # a real SQL-level error (a unique violation, a bad cast) always
        # carries a SQLSTATE code because the server actually responded;
        # a connection that died before/during the round trip never got a
        # response at all, so pgcode is None. Only that second case means
        # the connection itself, not the query, is what's broken.
        broken = e.pgcode is None
        if not broken:
            conn.rollback()
        raise
    except Exception:
        # A connection returned to the pool mid-transaction would still be
        # in Postgres's "aborted transaction" state for whoever borrows it
        # next - every query on it would fail until it's rolled back, so
        # this has to happen before putconn, not left for the next caller.
        conn.rollback()
        raise
    finally:
        pool.putconn(conn, close=broken)


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
