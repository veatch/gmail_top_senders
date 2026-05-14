"""Fetch message metadata from Gmail and persist to SQLite."""

import datetime
import sys
from typing import Any, Dict, List, Optional

from googleapiclient.errors import HttpError

from gmail_top_senders import db
from gmail_top_senders.api import execute_with_retry
from gmail_top_senders.parsing import parse_from_header

DEFAULT_QUERY = "in:anywhere -in:spam -in:trash"
LIST_PAGE_SIZE = 500
# Gmail batch limit is 50 requests per batch.
BATCH_GET_SIZE = 50


def _utc_now_iso():
    return datetime.datetime.utcnow().replace(microsecond=0).isoformat() + "Z"


def _extract_from_header(message):  # type: (Dict[str, Any]) -> str
    payload = message.get("payload") or {}
    headers = payload.get("headers") or []
    for h in headers:
        if (h.get("name") or "").lower() == "from":
            return h.get("value") or ""
    return ""


def _message_to_row(
    message,  # type: Dict[str, Any]
    fetched_at,  # type: str
):
    mid = message.get("id") or ""
    thread_id = message.get("threadId")
    internal_date = message.get("internalDate")
    if internal_date is not None:
        internal_date = int(internal_date)
    size_est = message.get("sizeEstimate")
    if size_est is not None:
        size_est = int(size_est)
    raw_from = _extract_from_header(message)
    _raw, display, addr_norm = parse_from_header(raw_from)
    return (
        mid,
        thread_id,
        internal_date,
        raw_from,
        addr_norm,
        display,
        size_est,
        fetched_at,
    )


def _fetch_batch(
    service,  # type: Any
    message_ids,  # type: List[str]
    verbose,  # type: bool
):
    # type: (...) -> Dict[str, Dict[str, Any]]
    """Return message id -> full message resource (metadata)."""
    results = {}  # type: Dict[str, Dict[str, Any]]

    def callback(request_id, response, exception):
        if exception is None and response is not None:
            results[request_id] = response

    batch = service.new_batch_http_request(callback=callback)
    for mid in message_ids:
        batch.add(
            service.users().messages().get(
                userId="me",
                id=mid,
                format="metadata",
                metadataHeaders=["From"],
            ),
            request_id=mid,
        )
    try:
        execute_with_retry(batch, verbose=verbose)
    except HttpError:
        if verbose:
            print(
                "Batch metadata fetch failed; retrying individually for this chunk...",
                file=sys.stderr,
            )

    for mid in message_ids:
        if mid not in results:
            try:
                req = service.users().messages().get(
                    userId="me",
                    id=mid,
                    format="metadata",
                    metadataHeaders=["From"],
                )
                results[mid] = execute_with_retry(req, verbose=verbose)
            except HttpError as e:
                if verbose:
                    print("Failed to fetch %s: %s" % (mid, e), file=sys.stderr)
    return results


def run_sync(
    service,  # type: Any
    conn,  # type: Any
    query,  # type: str
    max_messages,  # type: Optional[int]
    verbose,  # type: bool
):
    # type: (...) -> int
    """List + fetch + store. Returns number of messages stored."""
    db.clear_messages(conn)
    conn.commit()

    total_stored = 0
    page_token = None  # type: Optional[str]
    fetched_at = _utc_now_iso()

    while True:
        req = service.users().messages().list(
            userId="me",
            q=query,
            pageToken=page_token,
            maxResults=LIST_PAGE_SIZE,
        )
        resp = execute_with_retry(req, verbose=verbose)
        messages = resp.get("messages") or []
        ids = [m.get("id") for m in messages if m.get("id")]
        page_token = resp.get("nextPageToken")

        if max_messages is not None:
            remaining = max_messages - total_stored
            if remaining <= 0:
                break
            if len(ids) > remaining:
                ids = ids[:remaining]

        if not ids:
            if not page_token:
                break
            continue

        for i in range(0, len(ids), BATCH_GET_SIZE):
            chunk = ids[i : i + BATCH_GET_SIZE]
            by_id = _fetch_batch(service, chunk, verbose=verbose)
            rows = []
            for mid in chunk:
                msg = by_id.get(mid)
                if not msg:
                    continue
                rows.append(_message_to_row(msg, fetched_at))
            if rows:
                db.insert_many(conn, rows)
                conn.commit()
                total_stored += len(rows)
                if verbose:
                    print(
                        "Stored %s messages (total %s)..."
                        % (len(rows), total_stored),
                        file=sys.stderr,
                    )

        if not page_token:
            break
        if max_messages is not None and total_stored >= max_messages:
            break

    db.set_sync_meta(conn, "last_query", query)
    db.set_sync_meta(conn, "last_sync_at", fetched_at)
    return total_stored
