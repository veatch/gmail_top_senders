"""Aggregate and print reports from the local SQLite database."""

import csv
import datetime
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


def _format_date(internal_date):
    # type: (Optional[int]) -> str
    if internal_date is None:
        return "-"
    try:
        dt = datetime.datetime.utcfromtimestamp(internal_date / 1000.0)
        return dt.strftime("%Y-%m-%d")
    except Exception:
        return str(internal_date)


def write_report(
    conn,  # type: sqlite3.Connection
    group_by,  # type: str
    order_by,  # type: str
    top_n,  # type: int
    as_csv,  # type: bool
    sender,  # type: Optional[str]
    out,  # type: TextIO
    include_deleted=False,  # type: bool
):
    # type: (...) -> None
    """Print top senders or largest messages for a specific sender to ``out``."""
    if sender:
        rows = db.messages_by_sender(conn, sender, top_n, include_deleted=include_deleted)
    else:
        rows = db.aggregate_by_sender(conn, group_by, order_by, include_deleted=include_deleted)
        if top_n:
            rows = rows[:top_n]

    if not rows:
        if sender:
            out.write("No messages found for sender: %s\n" % sender)
        else:
            out.write("No messages in database. Run `sync` first.\n")
        return

    if as_csv:
        w = csv.writer(out)
        if sender:
            w.writerow(["subject", "date", "size_bytes", "status"])
            for _, subject, size, internal_date, _, _, deleted_at, kept_at in rows:
                status = "deleted" if deleted_at else ("kept" if kept_at else "")
                w.writerow([subject, _format_date(internal_date), size, status])
        else:
            w.writerow(["sender_key", "message_count", "total_size_bytes", "avg_size_bytes", "kept_count"])
            for sender_key, cnt, total_sz, avg_sz, kept_count in rows:
                w.writerow([sender_key, cnt, total_sz, avg_sz if avg_sz is not None else "", kept_count])
        return

    if sender:
        out.write("Largest messages from %s\n" % sender)
        hdr_subject = "subject"
        hdr_date = "date"
        hdr_size = "size"
        hdr_status = "status"

        lines = []  # type: List[Tuple[str, str, str, str]]
        for _, subject, size, internal_date, _, _, deleted_at, kept_at in rows:
            status = "[deleted]" if deleted_at else ("[kept]" if kept_at else "")
            lines.append((subject or "", _format_date(internal_date), _format_bytes(size), status))

        show_status = any(l[3] for l in lines)
        w0 = max(len(hdr_subject), max(len(l[0]) for l in lines))
        w1 = max(len(hdr_date), max(len(l[1]) for l in lines))
        w2 = max(len(hdr_size), max(len(l[2]) for l in lines))

        if show_status:
            w3 = max(len(hdr_status), max(len(l[3]) for l in lines))
            fmt = "%%-%ds  %%-%ds  %%-%ds  %%-%ds\n" % (w0, w1, w2, w3)
            out.write(fmt % (hdr_subject, hdr_date, hdr_size, hdr_status))
            out.write("-" * (w0 + w1 + w2 + w3 + 6) + "\n")
            for line in lines:
                out.write(fmt % line)
        else:
            fmt = "%%-%ds  %%-%ds  %%-%ds\n" % (w0, w1, w2)
            out.write(fmt % (hdr_subject, hdr_date, hdr_size))
            out.write("-" * (w0 + w1 + w2 + 4) + "\n")
            for line in lines:
                out.write(fmt % (line[0], line[1], line[2]))
        return

    hdr_sender = "sender"
    hdr_count = "msgs"
    hdr_total = "total size"
    hdr_avg = "avg size"
    hdr_kept = "kept"

    lines2 = []  # type: List[Tuple[str, str, str, str, str]]
    for sender_key, cnt, total_sz, avg_sz, kept_count in rows:
        lines2.append(
            (
                sender_key,
                str(cnt),
                _format_bytes(total_sz) if total_sz is not None else "-",
                _format_bytes(avg_sz),
                str(kept_count) if kept_count else "",
            )
        )

    show_kept = any(l[4] for l in lines2)
    w0 = max(len(hdr_sender), max(len(l[0]) for l in lines2))
    w1 = max(len(hdr_count), max(len(l[1]) for l in lines2))
    w2 = max(len(hdr_total), max(len(l[2]) for l in lines2))
    w3 = max(len(hdr_avg), max(len(l[3]) for l in lines2))

    if show_kept:
        w4 = max(len(hdr_kept), max(len(l[4]) for l in lines2))
        fmt = "%%-%ds  %%-%ds  %%-%ds  %%-%ds  %%-%ds\n" % (w0, w1, w2, w3, w4)
        out.write(fmt % (hdr_sender, hdr_count, hdr_total, hdr_avg, hdr_kept))
        out.write("-" * (w0 + w1 + w2 + w3 + w4 + 8) + "\n")
        for line in lines2:
            out.write(fmt % line)
    else:
        fmt = "%%-%ds  %%-%ds  %%-%ds  %%-%ds\n" % (w0, w1, w2, w3)
        out.write(fmt % (hdr_sender, hdr_count, hdr_total, hdr_avg))
        out.write("-" * (w0 + w1 + w2 + w3 + 6) + "\n")
        for line in lines2:
            out.write(fmt % (line[0], line[1], line[2], line[3]))
