"""Small additive migrations shared by the resource stores."""
import sqlite3


def ensure_week_column(con: sqlite3.Connection, table: str) -> None:
    if table not in {"documents", "resources"}:
        raise ValueError("Unsupported resource table.")
    columns = {row[1] for row in con.execute(f"PRAGMA table_info({table})")}
    if "week" in columns:
        return
    try:
        con.execute(f"ALTER TABLE {table} ADD COLUMN week INTEGER NOT NULL DEFAULT 0 CHECK(week BETWEEN 0 AND 52)")
        con.commit()
    except sqlite3.OperationalError:
        # Another worker may have applied the same migration after our check.
        if "week" not in {row[1] for row in con.execute(f"PRAGMA table_info({table})")}:
            raise
