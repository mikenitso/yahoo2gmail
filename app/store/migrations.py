import os
import sqlite3
from typing import List


def _list_migration_files(migrations_dir: str) -> List[str]:
    entries = []
    for name in os.listdir(migrations_dir):
        if name.endswith(".sql"):
            entries.append(name)
    return sorted(entries)


def _ensure_schema_migrations(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS schema_migrations (
          version TEXT PRIMARY KEY,
          applied_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        );
        """
    )


def _applied_versions(conn: sqlite3.Connection) -> set:
    _ensure_schema_migrations(conn)
    rows = conn.execute("SELECT version FROM schema_migrations").fetchall()
    return {row[0] for row in rows}


def apply_migrations(db_path: str, migrations_dir: str, logger=None) -> None:
    os.makedirs(os.path.dirname(db_path), exist_ok=True)
    conn = sqlite3.connect(db_path)
    try:
        conn.execute("PRAGMA foreign_keys = ON")
        applied = _applied_versions(conn)
        for filename in _list_migration_files(migrations_dir):
            if filename in applied:
                continue
            path = os.path.join(migrations_dir, filename)
            with open(path, "r", encoding="utf-8") as f:
                sql = f.read()
            with conn:
                conn.executescript(sql)
                conn.execute(
                    "INSERT INTO schema_migrations(version) VALUES (?)",
                    (filename,),
                )
            if logger:
                logger.info(
                    "migration applied",
                    extra={"event": "migration", "extra_fields": {"version": filename}},
                )
    finally:
        conn.close()
