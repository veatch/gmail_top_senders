# Implementation Plan

## Step 1: DB schema — deleted_at / kept_at columns

Add `deleted_at TEXT` (nullable ISO 8601 timestamp) and `kept_at TEXT` to the `messages` table.
No migration needed for existing DBs — drop and re-sync after schema changes.

Test: fresh sync, verify columns exist with NULL values on all rows.

## Step 2: CLI report filtering

Update `report` to exclude `deleted_at IS NOT NULL` rows by default.
Add `--include-deleted` flag to opt back in.
For `kept_at IS NOT NULL` rows, add a visual marker in the text table (e.g. `[K]` column).

Test: manually set `deleted_at` / `kept_at` on a few rows via `sqlite3`, re-run report, verify filtering and markers.

## Step 3: Flask web app — read-only reports

Stand up a minimal Flask app with a `serve` subcommand added to the existing CLI:
```
uv run gmail-top-senders serve --db gmail_metadata.sqlite --port 5000
```

Routes mirroring existing CLI reports:
- Sender list ordered by total size
- Largest messages across all senders
- Per-sender drill-down

Plain HTML with Jinja2 templates, one embedded `<style>` block, no npm/CDN/build step.
Deleted rows hidden by default; a toggle link at the top of relevant pages adds `?show_deleted=1`
to show them with strikethrough styling.

Test: all existing report views render correctly, deleted toggle works.

## Step 4: Gmail links and sender navigation

- In sender list: each sender is a link to its drill-down page.
- In per-sender view: each subject is a link to `https://mail.google.com/mail/u/0/#all/<message_id>`.

Pure template work, no new backend logic.

Test: links open correct Gmail threads.

## Step 5: Mark deleted / mark kept UI

Add POST endpoints:
- `POST /message/<id>/delete` — sets `deleted_at` to current UTC timestamp
- `POST /message/<id>/keep` — sets `kept_at` to current UTC timestamp
- `POST /message/<id>/unmark` — clears both `deleted_at` and `kept_at`

In the per-sender view, add "Delete" / "Keep" / "Unmark" buttons next to each message row.
Buttons submit a small HTML form (no JavaScript required).

Test: mark/unmark rows, verify they appear/disappear from default report view.

## Step 6: Sync performance investigation and tuning

Current batch size (50) and page size (500) are already at Gmail API maximums.

Issues to address:
1. **Smarter quota pacing**: current approach sleeps a fixed amount after every call,
   ignoring time already spent waiting for the API response. Switch to a token-bucket
   or elapsed-time approach that only sleeps the *remaining* time needed to stay under
   the cap.
2. **Double-counting in fallback path**: when `_fetch_batch` falls back to individual
   fetches, it calls `_pace_after_quota_units` per message inside the function; then
   `run_sync` calls it again for the full chunk size — double-counting quota for any
   messages that hit the fallback path.

Test: measure total sync time before and after on a mailbox of known size.

---

## Lower Priority

### Credentials in home directory
Move `credentials.json` / `token.json` default paths to `~/.config/gmail-top-senders/`,
with fallback to project directory for backwards compatibility. Prevents credential leakage
when zipping/sharing the project or report directory.

### Setup / onboarding page
Static HTML route in the Flask app walking through Google Cloud project creation,
OAuth consent screen config, and credential download.

### Sync progress indicator
Investigate whether `messages.list` `resultSizeEstimate` (approximate total) is reliable
enough for a progress bar. If not, check whether listing proceeds newest-first so the
UI can at least show the oldest date seen so far. Add progress output to the `sync`
command and/or a status indicator in the web UI.
