"""
Database schema and migration runner for autowebprompt.

Provides raw SQL schema (no ORM dependency) so that `autowebprompt db migrate`
works with just psycopg2.  The schema is intentionally compatible with the
SQLAlchemy models in models.py.

Install with: pip install autowebprompt[storage]
"""

import logging
from textwrap import dedent

logger = logging.getLogger(__name__)

SCHEMA_VERSION = "1"

# -- Meta table to track schema version ----------------------------------------

META_TABLE_SQL = dedent("""\
    CREATE TABLE IF NOT EXISTS _autowebprompt_meta (
        key   VARCHAR(255) PRIMARY KEY,
        value TEXT NOT NULL
    );
""")

# -- Application tables --------------------------------------------------------

TASKS_TABLE_SQL = dedent("""\
    CREATE TABLE IF NOT EXISTS tasks (
        id                  SERIAL PRIMARY KEY,
        task_name           VARCHAR(255) NOT NULL,
        task_starting_files JSON,
        task_solution_files JSON,
        task_source         VARCHAR(50),
        deprecated          BOOLEAN DEFAULT FALSE,
        created_at          TIMESTAMPTZ DEFAULT NOW(),
        updated_at          TIMESTAMPTZ DEFAULT NOW()
    );
""")

TASKS_INDEX_SQL = (
    "CREATE INDEX IF NOT EXISTS idx_tasks_task_name ON tasks (task_name);"
)

TASK_ATTEMPTS_TABLE_SQL = dedent("""\
    CREATE TABLE IF NOT EXISTS task_attempts (
        id                SERIAL PRIMARY KEY,
        task_id           INTEGER NOT NULL REFERENCES tasks(id),
        prompt_files      JSON,
        start_end_times   JSON,
        agent_model_name  VARCHAR(255),
        agent_model_type  VARCHAR(50),
        attempt_files     JSON,
        time_taken_mins   DOUBLE PRECISION,
        cost              DOUBLE PRECISION,
        created_at        TIMESTAMPTZ DEFAULT NOW(),
        updated_at        TIMESTAMPTZ DEFAULT NOW()
    );
""")

TASK_ATTEMPTS_INDEX_SQL = (
    "CREATE INDEX IF NOT EXISTS idx_task_attempts_task_id ON task_attempts (task_id);"
)

# Ordered list of all migration statements for v1.
MIGRATION_SQL = [
    META_TABLE_SQL,
    TASKS_TABLE_SQL,
    TASKS_INDEX_SQL,
    TASK_ATTEMPTS_TABLE_SQL,
    TASK_ATTEMPTS_INDEX_SQL,
]

# Insert / update schema version (last step).
SET_VERSION_SQL = dedent("""\
    INSERT INTO _autowebprompt_meta (key, value) VALUES ('schema_version', %s)
    ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value;
""")


def get_migration_sql() -> list[str]:
    """Return the full list of SQL statements for the current schema version."""
    return list(MIGRATION_SQL)


def run_migration(database_url: str) -> str:
    """Run schema migration against *database_url*.

    Returns the schema version string after migration.
    Raises ``RuntimeError`` if psycopg2 is not installed.
    """
    try:
        import psycopg2
    except ImportError:
        raise RuntimeError(
            "psycopg2 is required for migrations. "
            "Install with: pip install autowebprompt[storage]"
        )

    conn = psycopg2.connect(database_url)
    try:
        conn.autocommit = False
        cur = conn.cursor()
        for stmt in MIGRATION_SQL:
            cur.execute(stmt)
        cur.execute(SET_VERSION_SQL, (SCHEMA_VERSION,))
        conn.commit()
        logger.info("Migration complete — schema version %s", SCHEMA_VERSION)
        return SCHEMA_VERSION
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def check_connection(database_url: str) -> bool:
    """Return ``True`` if we can execute ``SELECT 1`` against *database_url*."""
    try:
        import psycopg2
    except ImportError:
        raise RuntimeError(
            "psycopg2 is required. Install with: pip install autowebprompt[storage]"
        )

    try:
        conn = psycopg2.connect(database_url)
        cur = conn.cursor()
        cur.execute("SELECT 1")
        cur.close()
        conn.close()
        return True
    except Exception as exc:
        logger.debug("Connection test failed: %s", exc)
        return False


def get_table_status(database_url: str) -> dict:
    """Return a dict with table existence and row counts.

    Example return::

        {
            "schema_version": "1",
            "tables": {
                "tasks": {"exists": True, "rows": 42},
                "task_attempts": {"exists": True, "rows": 108},
            },
        }
    """
    try:
        import psycopg2
    except ImportError:
        raise RuntimeError(
            "psycopg2 is required. Install with: pip install autowebprompt[storage]"
        )

    conn = psycopg2.connect(database_url)
    cur = conn.cursor()

    # Schema version
    version = None
    try:
        cur.execute(
            "SELECT value FROM _autowebprompt_meta WHERE key = 'schema_version'"
        )
        row = cur.fetchone()
        if row:
            version = row[0]
    except Exception:
        conn.rollback()

    # Table status
    tables = {}
    for table_name in ("tasks", "task_attempts"):
        try:
            cur.execute(
                "SELECT EXISTS ("
                "  SELECT 1 FROM information_schema.tables"
                "  WHERE table_name = %s"
                ")",
                (table_name,),
            )
            exists = cur.fetchone()[0]
            rows = 0
            if exists:
                cur.execute(f"SELECT COUNT(*) FROM {table_name}")  # noqa: S608
                rows = cur.fetchone()[0]
            tables[table_name] = {"exists": exists, "rows": rows}
        except Exception:
            conn.rollback()
            tables[table_name] = {"exists": False, "rows": 0}

    cur.close()
    conn.close()

    return {"schema_version": version, "tables": tables}
