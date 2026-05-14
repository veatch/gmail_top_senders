"""Aggregate and print reports from the local SQLite database."""

import csv
import sqlite3
from typing import List, Optional, TextIO, Tuple

from gmail_top_senders import db


def _format_bytes(num):
    # type: (Optional[int]) -> str
    if num is None:
        return "-"
    n = float(num)
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if abs(n) < 1024.0 or unit == "TB":
            if unit == "B":
                return "%d B" % int(n)
            return "%.1f %s" % (n, unit)
        n /= 1024.0
    return "%.1f TB" % n


def write_report(
    conn,  # type: sqlite3.Connection
    group_by,  # type: str
    top_n,  # type: int
    as_csv,  # type: bool
    out,  # type: TextIO
):
    # type: (...) -> None
    """Print top senders to ``out``."""
    rows = db.aggregate_by_sender(conn, group_by)
    if top_n:
        rows = rows[:top_n]

    if not rows:
        out.write("No messages in database. Run `sync` first.\n")
        return

    if as_csv:
        w = csv.writer(out)
        w.writerow(["sender_key", "message_count", "total_size_bytes", "avg_size_bytes"])
        for sender_key, cnt, total_sz, avg_sz in rows:
            w.writerow([sender_key, cnt, total_sz, avg_sz if avg_sz is not None else ""])
        return

    # column widths
    hdr_sender = "sender"
    hdr_count = "msgs"
    hdr_total = "total size"
    hdr_avg = "avg size"

    lines = []  # type: List[Tuple[str, str, str, str]]
    for sender_key, cnt, total_sz, avg_sz in rows:
        lines.append(
            (
                sender_key,
                str(cnt),
                _format_bytes(total_sz) if total_sz is not None else "-",
                _format_bytes(avg_sz),
            )
        )

    w0 = max(len(hdr_sender), max(len(l[0]) for l in lines))
    w1 = max(len(hdr_count), max(len(l[1]) for l in lines))
    w2 = max(len(hdr_total), max(len(l[2]) for l in lines))
    w3 = max(len(hdr_avg), max(len(l[3]) for l in lines))

    fmt = "%%-%ds  %%-%ds  %%-%ds  %%-%ds\n" % (w0, w1, w2, w3)
    out.write(
        fmt
        % (
            hdr_sender[:w0],
            hdr_count[:w1],
            hdr_total[:w2],
            hdr_avg[:w3],
        )
    )
    out.write("-" * (w0 + w1 + w2 + w3 + 6) + "\n")
    for line in lines:
        out.write(fmt % line)
