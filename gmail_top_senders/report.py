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
):
    # type: (...) -> None
    """Print top senders or largest messages for a specific sender to ``out``."""
    if sender:
        rows = db.messages_by_sender(conn, sender, top_n)
    else:
        rows = db.aggregate_by_sender(conn, group_by, order_by)
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
            w.writerow([
                "subject",
                "date",
                "size_bytes",
            ])
            for _, subject, size, internal_date, _, _ in rows:
                w.writerow([subject, _format_date(internal_date), size])
        else:
            w.writerow(["sender_key", "message_count", "total_size_bytes", "avg_size_bytes"])
            for sender_key, cnt, total_sz, avg_sz in rows:
                w.writerow([sender_key, cnt, total_sz, avg_sz if avg_sz is not None else ""])
        return

    if sender:
        out.write("Largest messages from %s\n" % sender)
        hdr_subject = "subject"
        hdr_date = "date"
        hdr_size = "size"

        lines = []  # type: List[Tuple[str, str, str]]
        for _, subject, size, internal_date, _, _ in rows:
            lines.append((subject or "", _format_date(internal_date), _format_bytes(size)))

        w0 = max(len(hdr_subject), max(len(l[0]) for l in lines))
        w1 = max(len(hdr_date), max(len(l[1]) for l in lines))
        w2 = max(len(hdr_size), max(len(l[2]) for l in lines))

        fmt = "%%-%ds  %%-%ds  %%-%ds\n" % (w0, w1, w2)
        out.write(fmt % (hdr_subject, hdr_date, hdr_size))
        out.write("-" * (w0 + w1 + w2 + 4) + "\n")
        for line in lines:
            out.write(fmt % line)
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
