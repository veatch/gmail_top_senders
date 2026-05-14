"""Fetch message metadata from Gmail and persist to SQLite."""

import datetime
import sys
import time
from typing import Any, Dict, List, Optional

from googleapiclient.errors import HttpError

from gmail_top_senders import db
from gmail_top_senders.api import execute_with_retry
from gmail_top_senders.parsing import parse_from_header

DEFAULT_QUERY = "in:anywhere -in:spam -in:trash"
LIST_PAGE_SIZE = 500
# Gmail batch limit is 50 requests per batch.
BATCH_GET_SIZE = 50
# Per https://developers.google.com/workspace/gmail/api/reference/quota
QUOTA_UNITS_MESSAGES_LIST = 5
QUOTA_UNITS_MESSAGES_GET = 5
# Per-user limit is 15_000 units/min; default leaves headroom for bursts / retries.
DEFAULT_MAX_QUOTA_UNITS_PER_MINUTE = 12000


def _pace_after_quota_units(
    units,  # type: int
    max_units_per_minute,  # type: Optional[float]
    verbose,  # type: bool
):
    # type: (...) -> None
    """Sleep long enough to average at most ``max_units_per_minute`` quota units."""
    if not max_units_per_minute or max_units_per_minute <= 0 or units <= 0:
        return
    delay = (float(units) / float(max_units_per_minute)) * 60.0
    if delay <= 0:
        return
    if verbose and delay >= 1.0:
        print(
            "Pacing: sleeping %.1fs (~%s quota units toward %s/min cap)..."
            % (delay, units, int(max_units_per_minute)),
            file=sys.stderr,
        )
    time.sleep(delay)


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
    quota_cap,  # type: Optional[float]
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
                _pace_after_quota_units(
                    QUOTA_UNITS_MESSAGES_GET, quota_cap, verbose
                )
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
    max_quota_units_per_minute=None,  # type: Optional[float]
    incremental=False,  # type: bool
):
    # type: (...) -> int
    """List + fetch + store. Returns number of message rows written this run."""
    if max_quota_units_per_minute is None:
        cap = float(DEFAULT_MAX_QUOTA_UNITS_PER_MINUTE)
    elif max_quota_units_per_minute <= 0:
        cap = None  # type: Optional[float]
    else:
        cap = float(max_quota_units_per_minute)

    if incremental:
        prev_query = db.get_sync_meta(conn, "last_query")
        if prev_query is not None and prev_query != query and verbose:
            print(
                "Note: --query differs from last sync (%r). "
                "The database may mix results from multiple queries; "
                "run a full sync without --incremental to rebuild."
                % (prev_query,),
                file=sys.stderr,
            )
    else:
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
        _pace_after_quota_units(QUOTA_UNITS_MESSAGES_LIST, cap, verbose)
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

        if incremental:
            have = db.ids_present(conn, ids)
            missing = [mid for mid in ids if mid not in have]
        else:
            missing = ids

        for i in range(0, len(missing), BATCH_GET_SIZE):
            chunk = missing[i : i + BATCH_GET_SIZE]
            if not chunk:
                continue
            by_id = _fetch_batch(service, chunk, verbose=verbose, quota_cap=cap)
            _pace_after_quota_units(
                len(chunk) * QUOTA_UNITS_MESSAGES_GET,
                cap,
                verbose,
            )
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
                        "Stored %s messages (written this run: %s)..."
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
