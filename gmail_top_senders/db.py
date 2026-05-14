"""SQLite persistence for per-message metadata."""

import sqlite3
from typing import List, Optional, Tuple


DEFAULT_DB_FILENAME = "gmail_metadata.sqlite"


def connect(db_path: str) -> sqlite3.Connection:
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    return conn


def init_schema(conn: sqlite3.Connection) -> None:
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS messages (
            message_id TEXT PRIMARY KEY,
            thread_id TEXT,
            internal_date INTEGER,
            from_raw TEXT,
            from_address_normalized TEXT,
            from_display_name TEXT,
            size_estimate INTEGER,
            fetched_at TEXT
        );
        CREATE INDEX IF NOT EXISTS idx_messages_addr ON messages (from_address_normalized);
        CREATE INDEX IF NOT EXISTS idx_messages_date ON messages (internal_date);

        CREATE TABLE IF NOT EXISTS sync_meta (
            key TEXT PRIMARY KEY,
            value TEXT
        );
        """
    )
    conn.commit()


def clear_messages(conn: sqlite3.Connection) -> None:
    conn.execute("DELETE FROM messages")
    conn.commit()


def insert_many(
    conn: sqlite3.Connection,
    rows: List[
        Tuple[
            str,
            Optional[str],
            Optional[int],
            str,
            str,
            str,
            Optional[int],
            str,
        ]
    ],
) -> None:
    conn.executemany(
        """
        INSERT OR REPLACE INTO messages (
            message_id, thread_id, internal_date, from_raw,
            from_address_normalized, from_display_name, size_estimate, fetched_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        rows,
    )


def set_sync_meta(conn: sqlite3.Connection, key: str, value: str) -> None:
    conn.execute(
        "INSERT OR REPLACE INTO sync_meta (key, value) VALUES (?, ?)", (key, value)
    )
    conn.commit()


def aggregate_by_sender(
    conn: sqlite3.Connection,
    group_by: str,
) -> List[Tuple[str, int, int, Optional[int]]]:
    """Return rows: (sender_key, message_count, total_size, avg_size).

    ``sender_key`` is normalized address or display label for ``group_by``.
    """
    if group_by == "address":
        sql = """
            SELECT
                CASE
                    WHEN TRIM(IFNULL(from_address_normalized, '')) = '' THEN '(empty)'
                    ELSE from_address_normalized
                END AS sender_key,
                COUNT(*) AS cnt,
                COALESCE(SUM(size_estimate), 0) AS total_size,
                CAST(ROUND(COALESCE(AVG(size_estimate), 0)) AS INTEGER) AS avg_size
            FROM messages
            GROUP BY 1
            ORDER BY 2 DESC, 3 DESC
        """
    elif group_by == "display-name":
        sql = """
            SELECT
                CASE
                    WHEN TRIM(IFNULL(from_display_name, '')) = '' THEN '(empty)'
                    ELSE from_display_name
                END AS sender_key,
                COUNT(*) AS cnt,
                COALESCE(SUM(size_estimate), 0) AS total_size,
                CAST(ROUND(COALESCE(AVG(size_estimate), 0)) AS INTEGER) AS avg_size
            FROM messages
            GROUP BY 1
            ORDER BY 2 DESC, 3 DESC
        """
    else:
        raise ValueError("group_by must be 'address' or 'display-name'")

    cur = conn.execute(sql)
    rows = []
    for r in cur.fetchall():
        rows.append((r["sender_key"], int(r["cnt"]), int(r["total_size"]), r["avg_size"]))
    return rows


def message_count(conn: sqlite3.Connection) -> int:
    row = conn.execute("SELECT COUNT(*) AS c FROM messages").fetchone()
    return int(row["c"]) if row else 0


def ids_present(conn: sqlite3.Connection, ids: List[str]) -> set:
    """Return the subset of ``ids`` that already exist as ``message_id`` rows."""
    if not ids:
        return set()
    present = set()
    # SQLite bind parameter limit is often 999; stay under with smaller chunks.
    chunk_size = 400
    for i in range(0, len(ids), chunk_size):
        chunk = ids[i : i + chunk_size]
        placeholders = ",".join("?" * len(chunk))
        cur = conn.execute(
            "SELECT message_id FROM messages WHERE message_id IN (%s)"
            % placeholders,
            chunk,
        )
        for row in cur.fetchall():
            present.add(row["message_id"])
    return present


def get_sync_meta(conn: sqlite3.Connection, key: str) -> Optional[str]:
    row = conn.execute(
        "SELECT value FROM sync_meta WHERE key = ?", (key,)
    ).fetchone()
    return str(row["value"]) if row else None
