"""Command-line interface."""

from __future__ import print_function

import argparse
import sys
from typing import List, Optional

from gmail_top_senders import db
from gmail_top_senders.api import build_gmail_service, load_credentials
from gmail_top_senders.report import write_report
from gmail_top_senders.sync import DEFAULT_QUERY, run_sync


def main(argv=None):
    # type: (Optional[List[str]]) -> None
    if argv is None:
        argv = sys.argv[1:]

    parser = argparse.ArgumentParser(
        description="Gmail sender analytics (read-only): sync metadata to SQLite, then report top senders.",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    p_sync = sub.add_parser(
        "sync", help="List messages matching a query and store From + size metadata in SQLite"
    )
    p_sync.add_argument(
        "--db",
        default=db.DEFAULT_DB_FILENAME,
        help="SQLite database path (default: %(default)s)",
    )
    p_sync.add_argument(
        "--credentials",
        default="credentials.json",
        help="OAuth desktop client secrets JSON from Google Cloud (default: %(default)s)",
    )
    p_sync.add_argument(
        "--token",
        default="token.json",
        help="Saved OAuth token path (default: %(default)s)",
    )
    p_sync.add_argument(
        "--query",
        "-q",
        default=DEFAULT_QUERY,
        help="Gmail search query. Default matches all mail except Spam/Trash.",
    )
    p_sync.add_argument(
        "--max-messages",
        type=int,
        default=None,
        metavar="N",
        help="Stop after storing N messages (testing / partial sync)",
    )
    p_sync.add_argument(
        "-v",
        "--verbose",
        action="store_true",
        help="Print progress and rate-limit backoff messages to stderr",
    )
    p_sync.add_argument(
        "--max-quota-units-per-minute",
        type=float,
        default=12000.0,
        metavar="N",
        help="Throttle Gmail usage to ~N quota units/min per user (0 = no pacing). "
        "messages.get uses 5 units each; Gmail allows ~15000/min. Default: %(default)s",
    )
    p_sync.add_argument(
        "--incremental",
        action="store_true",
        help="Keep existing rows; only fetch metadata for message IDs not yet in the DB. "
        "Still lists the full mailbox (messages.list cost). Use the same -q as prior sync "
        "or run a full sync to rebuild.",
    )

    p_rep = sub.add_parser(
        "report", help="Rank senders using only the local database (no Gmail API calls)"
    )
    p_rep.add_argument("--db", default=db.DEFAULT_DB_FILENAME)
    p_rep.add_argument(
        "--group-by",
        choices=["address", "display-name"],
        default="address",
        help="Group by sending address (default) or From display name",
    )
    p_rep.add_argument(
        "--order-by",
        choices=["total-size", "sender", "message-count", "avg-size"],
        default="total-size",
        help="Order by total size (default), sender, message count, or average size",
    )
    p_rep.add_argument(
        "--top",
        type=int,
        default=50,
        metavar="N",
        help="Show only the top N senders (default: %(default)s)",
    )
    p_rep.add_argument(
        "--csv",
        action="store_true",
        help="CSV output to stdout instead of a table",
    )

    args = parser.parse_args(argv)

    if args.command == "sync":
        conn = db.connect(args.db)
        try:
            db.init_schema(conn)
            creds = load_credentials(args.credentials, args.token)
            service = build_gmail_service(creds)
            n = run_sync(
                service,
                conn,
                args.query,
                args.max_messages,
                args.verbose,
                args.max_quota_units_per_minute,
                incremental=args.incremental,
            )
            if args.incremental:
                total = db.message_count(conn)
                print(
                    "Applied %s new or updated message(s) in %s (%s in database)."
                    % (n, args.db, total)
                )
            else:
                print("Synced %s messages into %s" % (n, args.db))
        finally:
            conn.close()
    elif args.command == "report":
        conn = db.connect(args.db)
        try:
            db.init_schema(conn)
            write_report(
                conn,
                args.group_by,
                args.order_by,
                args.top,
                args.csv,
                sys.stdout,
            )
        finally:
            conn.close()
    else:
        parser.print_help()
        sys.exit(1)
