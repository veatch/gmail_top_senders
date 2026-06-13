# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Commands

```bash
# Install dependencies (creates .venv)
uv sync

# Run sync (requires credentials.json)
uv run mail-room sync --db gmail_metadata.sqlite
uv run mail-room sync --db gmail_metadata.sqlite --incremental -v

# Run web interface (no API calls needed)
uv run mail-room serve --db gmail_metadata.sqlite
# then open http://127.0.0.1:5000

# Run report (no API calls needed)
uv run mail-room report --db gmail_metadata.sqlite
uv run mail-room report --db gmail_metadata.sqlite --group-by display-name --top 30
uv run mail-room report --db gmail_metadata.sqlite --sender alice@example.com
uv run mail-room report --db gmail_metadata.sqlite --csv > top.csv
```

There are no tests or linting configured in this project.

## Architecture

This is a two-phase CLI tool: **sync** pulls metadata from the Gmail API into SQLite, **report** reads from SQLite only (no API calls).

**Module layout:**

- `cli.py` — `argparse` entry point; parses args and calls into sync or report
- `api.py` — OAuth credential loading/refresh (`load_credentials`), Gmail service construction (`build_gmail_service`), and `execute_with_retry` (exponential backoff for rate limits and transient network errors)
- `sync.py` — `run_sync` orchestrates `messages.list` pagination → batched `messages.get` (50 per batch via `new_batch_http_request`) → `db.insert_many`. Includes quota pacing via `_pace_after_quota_units` and incremental mode (skip already-stored IDs)
- `db.py` — SQLite schema (`messages` + `sync_meta` tables), CRUD helpers, and the `aggregate_by_sender` / `messages_by_sender` query functions
- `parsing.py` — `parse_from_header` normalizes raw `From:` headers into `(raw, display_name, address_normalized)` using stdlib `email.utils.parseaddr`
- `report.py` — `write_report` formats aggregated or per-sender rows as an aligned text table or CSV

**SQLite schema** (`messages` table): `message_id` (PK), `thread_id`, `internal_date` (epoch ms), `from_raw`, `from_address_normalized`, `from_display_name`, `subject`, `size_estimate`, `fetched_at`. `sync_meta` stores `last_query` and `last_sync_at`.

**Gmail quota:** `messages.list` costs 5 units; `messages.get` costs 5 units. Default cap is 12,000 units/min (Gmail limit is 15,000). The sync code paces after each list page and after each batch fetch.

**Incremental sync:** passes `--incremental` to skip fetching metadata for message IDs already in the DB, but still does a full `messages.list` pass to find new IDs.

**Sensitive files** (gitignored): `credentials.json` (OAuth client secret), `token.json` (saved refresh token), `*.sqlite` (mailbox metadata).
