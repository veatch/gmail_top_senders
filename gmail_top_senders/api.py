"""Gmail API client: OAuth and retried requests."""

import json
import os
import random
import time
from typing import Any, Optional

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

SCOPES = ["https://www.googleapis.com/auth/gmail.readonly"]


def load_credentials(
    credentials_path: str,
    token_path: str,
) -> Credentials:
    creds = None  # type: Optional[Credentials]
    if os.path.exists(token_path):
        try:
            creds = Credentials.from_authorized_user_file(token_path, SCOPES)
        except (ValueError, OSError):
            creds = None

    if creds and creds.valid:
        return creds

    if creds and creds.expired and creds.refresh_token:
        creds.refresh(Request())
        _save_token(creds, token_path)
        return creds

    flow = InstalledAppFlow.from_client_secrets_file(credentials_path, SCOPES)
    creds = flow.run_local_server(port=0)
    _save_token(creds, token_path)
    return creds


def _save_token(creds: Credentials, token_path: str) -> None:
    with open(token_path, "w") as f:
        f.write(creds.to_json())


def build_gmail_service(credentials):
    # type: (Credentials) -> Any
    return build("gmail", "v1", credentials=credentials, cache_discovery=False)


def _retry_after_seconds(err):
    # type: (HttpError) -> float
    try:
        if err.resp is not None:
            ra = err.resp.get("retry-after")
            if ra is not None:
                return float(ra)
    except (TypeError, ValueError):
        pass
    return 0.0


def _http_error_reasons(err):
    # type: (HttpError) -> list
    """Parse error reasons from an HttpError body (best-effort)."""
    raw = getattr(err, "content", None) or b""
    if not raw:
        return []
    try:
        if isinstance(raw, bytes):
            raw = raw.decode("utf-8", errors="replace")
        data = json.loads(raw)
    except (TypeError, ValueError):
        return []
    err_obj = data.get("error") if isinstance(data, dict) else None
    if not isinstance(err_obj, dict):
        return []
    out = []
    for item in err_obj.get("errors") or []:
        if isinstance(item, dict):
            r = item.get("reason")
            if r:
                out.append(str(r))
    return out


def _is_retryable_rate_limit(err):
    # type: (HttpError) -> bool
    """True for 429/503 or 403 Gmail quota (rateLimitExceeded / userRateLimitExceeded)."""
    status = err.resp.status if err.resp else None
    if status in (429, 503):
        return True
    if status != 403:
        return False
    for reason in _http_error_reasons(err):
        if reason in ("rateLimitExceeded", "userRateLimitExceeded"):
            return True
    return False


def execute_with_retry(
    request,
    max_attempts=8,
    base_delay=1.5,
    max_delay=120.0,
    verbose=False,
):
    """Call ``request.execute()`` with exponential backoff on rate limits."""
    attempt = 0
    while True:
        attempt += 1
        try:
            return request.execute()
        except HttpError as e:
            status = e.resp.status if e.resp else None
            if _is_retryable_rate_limit(e) and attempt < max_attempts:
                ra = _retry_after_seconds(e)
                exp = min(max_delay, max(ra, base_delay * (2.0 ** (attempt - 1))))
                jitter = random.uniform(0, 0.25 * exp)
                delay = exp + jitter
                if verbose:
                    print(
                        "Rate limited (HTTP %s). Sleeping %.1fs before retry %s/%s..."
                        % (status, delay, attempt, max_attempts)
                    )
                time.sleep(delay)
                continue
            raise
