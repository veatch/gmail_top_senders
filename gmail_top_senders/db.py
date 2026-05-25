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
            subject TEXT,
            size_estimate INTEGER,
            fetched_at TEXT,
            deleted_at TEXT,
            kept_at TEXT
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
            from_address_normalized, from_display_name, subject, size_estimate, fetched_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
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
    order_by: str,
    include_deleted: bool = False,
    subject_filter: Optional[str] = None,
) -> List[Tuple[str, int, int, Optional[int], int, int]]:
    """Return rows: (sender_key, message_count, total_size, avg_size, kept_count, remaining_size).

    ``remaining_size`` is total size of messages not yet marked as reviewed.
    ``sender_key`` is normalized address or display label for ``group_by``.
    Excludes deleted messages unless ``include_deleted`` is True.
    """
    order_by_clause = ""
    if order_by == "remaining-size":
        order_by_clause = "ORDER BY remaining_size DESC"
    elif order_by == "total-size":
        order_by_clause = "ORDER BY total_size DESC"
    elif order_by == "sender":
        order_by_clause = "ORDER BY sender_key"
    elif order_by == "message-count":
        order_by_clause = "ORDER BY cnt DESC"
    elif order_by == "avg-size":
        order_by_clause = "ORDER BY avg_size DESC"

    conditions = []
    params: List = []
    if not include_deleted:
        conditions.append("deleted_at IS NULL")
    if subject_filter:
        conditions.append("LOWER(COALESCE(subject, '')) LIKE '%' || LOWER(?) || '%'")
        params.append(subject_filter)
    where = ("WHERE " + " AND ".join(conditions)) if conditions else ""

    remaining_expr = "COALESCE(SUM(CASE WHEN kept_at IS NULL THEN size_estimate ELSE 0 END), 0)"

    if group_by == "address":
        sql = """
            SELECT
                CASE
                    WHEN TRIM(IFNULL(from_address_normalized, '')) = '' THEN '(empty)'
                    ELSE from_address_normalized
                END AS sender_key,
                COALESCE(SUM(size_estimate), 0) AS total_size,
                COUNT(*) AS cnt,
                CAST(ROUND(COALESCE(AVG(size_estimate), 0)) AS INTEGER) AS avg_size,
                SUM(CASE WHEN kept_at IS NOT NULL THEN 1 ELSE 0 END) AS kept_count,
                %s AS remaining_size
            FROM messages
            %s
            GROUP BY 1
            %s
        """ % (remaining_expr, where, order_by_clause)
    elif group_by == "display-name":
        sql = """
            SELECT
                CASE
                    WHEN TRIM(IFNULL(from_display_name, '')) = '' THEN '(empty)'
                    ELSE from_display_name
                END AS sender_key,
                COUNT(*) AS cnt,
                COALESCE(SUM(size_estimate), 0) AS total_size,
                CAST(ROUND(COALESCE(AVG(size_estimate), 0)) AS INTEGER) AS avg_size,
                SUM(CASE WHEN kept_at IS NOT NULL THEN 1 ELSE 0 END) AS kept_count,
                %s AS remaining_size
            FROM messages
            %s
            GROUP BY 1
            %s
        """ % (remaining_expr, where, order_by_clause)
    else:
        raise ValueError("group_by must be 'address' or 'display-name'")

    cur = conn.execute(sql, params)
    rows = []
    for r in cur.fetchall():
        rows.append((r["sender_key"], int(r["cnt"]), int(r["total_size"]), r["avg_size"], int(r["kept_count"]), int(r["remaining_size"])))
    return rows


def messages_by_sender(
    conn: sqlite3.Connection,
    sender: str,
    top_n: Optional[int] = None,
    include_deleted: bool = False,
    subject_filter: Optional[str] = None,
) -> List[Tuple[str, Optional[str], int, Optional[int], str, str, Optional[str], Optional[str]]]:
    """Return rows of individual messages matching a sender string.

    Rows are ordered by size descending.
    Each row: (message_id, thread_id, subject, size_estimate, internal_date,
               from_address_normalized, from_display_name, deleted_at, kept_at).
    Excludes deleted messages unless ``include_deleted`` is True.
    """
    sender_key = sender.strip()
    if not sender_key:
        return []

    extra_conditions = []
    params: List = [sender_key, sender_key]
    if not include_deleted:
        extra_conditions.append("deleted_at IS NULL")
    if subject_filter:
        extra_conditions.append("LOWER(COALESCE(subject, '')) LIKE '%' || LOWER(?) || '%'")
        params.append(subject_filter)
    extra = (" AND " + " AND ".join(extra_conditions)) if extra_conditions else ""

    sql = """
        SELECT
            message_id,
            thread_id,
            subject,
            COALESCE(size_estimate, 0) AS size_estimate,
            internal_date,
            COALESCE(from_address_normalized, '') AS from_address_normalized,
            COALESCE(from_display_name, '') AS from_display_name,
            deleted_at,
            kept_at
        FROM messages
        WHERE (
            TRIM(IFNULL(from_address_normalized, '')) = ?
            OR LOWER(TRIM(IFNULL(from_display_name, ''))) = LOWER(?)
        )%s
        ORDER BY size_estimate DESC
    """ % extra
    if top_n is not None:
        sql += "LIMIT ?"
        params.append(top_n)

    cur = conn.execute(sql, params)
    rows = []
    for r in cur.fetchall():
        rows.append(
            (
                r["message_id"],
                r["thread_id"],
                r["subject"],
                int(r["size_estimate"]),
                int(r["internal_date"]) if r["internal_date"] is not None else None,
                r["from_address_normalized"],
                r["from_display_name"],
                r["deleted_at"],
                r["kept_at"],
            )
        )
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


def all_messages(
    conn: sqlite3.Connection,
    include_deleted: bool = False,
    subject_filter: Optional[str] = None,
) -> List[Tuple[str, Optional[str], str, int, Optional[int], str, str, Optional[str], Optional[str]]]:
    """Return all messages ordered by size descending.

    Each row: (message_id, thread_id, subject, size_estimate, internal_date,
               from_address_normalized, from_display_name, deleted_at, kept_at).
    """
    conditions = []
    params: List = []
    if not include_deleted:
        conditions.append("deleted_at IS NULL")
    if subject_filter:
        conditions.append("LOWER(COALESCE(subject, '')) LIKE '%' || LOWER(?) || '%'")
        params.append(subject_filter)
    where = ("WHERE " + " AND ".join(conditions)) if conditions else ""

    sql = """
        SELECT
            message_id,
            thread_id,
            subject,
            COALESCE(size_estimate, 0) AS size_estimate,
            internal_date,
            COALESCE(from_address_normalized, '') AS from_address_normalized,
            COALESCE(from_display_name, '') AS from_display_name,
            deleted_at,
            kept_at
        FROM messages
        %s
        ORDER BY size_estimate DESC
    """ % where

    cur = conn.execute(sql, params)
    rows = []
    for r in cur.fetchall():
        rows.append((
            r["message_id"],
            r["thread_id"],
            r["subject"],
            int(r["size_estimate"]),
            int(r["internal_date"]) if r["internal_date"] is not None else None,
            r["from_address_normalized"],
            r["from_display_name"],
            r["deleted_at"],
            r["kept_at"],
        ))
    return rows


def mark_deleted(conn: sqlite3.Connection, message_id: str) -> None:
    conn.execute(
        "UPDATE messages SET deleted_at = datetime('now') WHERE message_id = ?",
        (message_id,),
    )
    conn.commit()


def mark_kept(conn: sqlite3.Connection, message_id: str, kept: bool) -> None:
    if kept:
        conn.execute(
            "UPDATE messages SET kept_at = datetime('now') WHERE message_id = ?",
            (message_id,),
        )
    else:
        conn.execute(
            "UPDATE messages SET kept_at = NULL WHERE message_id = ?",
            (message_id,),
        )
    conn.commit()


def get_sync_meta(conn: sqlite3.Connection, key: str) -> Optional[str]:
    row = conn.execute(
        "SELECT value FROM sync_meta WHERE key = ?", (key,)
    ).fetchone()
    return str(row["value"]) if row else None
