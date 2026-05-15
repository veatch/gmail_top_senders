# Gmail sender analytics (read-only)

Small local tool: pull **metadata only** (From header + `sizeEstimate`) from Gmail via the API, store rows in **SQLite**, and print **who sends you the most mail**—by SMTP address or by **From display name** (useful for marketing mail that rotates addresses).

Deleting or changing mail in Gmail is **out of scope**; use Gmail yourself after you’ve decided what to remove.

## Requirements

- **Python 3.7+** (project metadata: `requires-python` in `pyproject.toml`)
- [**uv**](https://docs.astral.sh/uv/) for installing dependencies (see below). You can still use plain `pip install .` if you must—this repo declares deps in **`pyproject.toml`** only (there is no `requirements.txt`).
- A Google Cloud project with the **Gmail API** enabled and an **OAuth 2.0 Client ID** of type **Desktop app**
- Download the client JSON as `credentials.json` in this directory (or pass `--credentials`)

### One-time Google Cloud setup (summary)

Use a project you own (often easiest under a **personal** Google account so the app is not locked to a company Workspace org).

1. [Google Cloud Console](https://console.cloud.google.com/) → **APIs & Services** → **Enable Gmail API** for your project.
2. **OAuth / Google Auth Platform** — configure the app users will trust when the browser opens:
   - Open **[Google Auth Platform → Audience](https://console.cloud.google.com/auth/audience)** (or **APIs & Services → OAuth consent screen** and follow the same wizard). Set **Audience** to **External** if you use a normal **@gmail.com** account. **Internal** only allows accounts in the same Google Cloud **organization**; personal Gmail will show an error like “restricted to users within its organization.”
   - Set **Publishing status** to **Testing** for a private script (no verification needed for just you).
   - While in **Testing**, add your own Google account under **Test users** (the exact address you sign in with in the browser). Only listed test users can grant access until you publish the app more broadly.
3. **APIs & Services** → **Credentials** → **Create credentials** → **OAuth client ID** → Application type **Desktop app** → Download JSON and save as `credentials.json` in this directory.

If you change OAuth client or fixed a misconfigured consent screen, delete any existing **`token.json`** in this directory and run **sync** again so authorization starts clean.

Keep `credentials.json` and `token.json` private (both are gitignored).

## Install (uv)

Install uv (pick one):

- **macOS / Linux:** `curl -LsSf https://astral.sh/uv/install.sh | sh` (then restart your shell or add `~/.local/bin` to `PATH`)
- **Homebrew:** `brew install uv`

In the project directory:

```bash
cd gmail_top_senders

# Optional: pin interpreter (example: 3.12). Omit to use a default uv-managed Python.
# uv python install 3.12
# uv venv --python 3.12

uv sync
```

That creates a **`.venv`** (if needed) and installs this package plus dependencies from `pyproject.toml`. Commit **`uv.lock`** when you run `uv lock` so installs stay reproducible.

Run the CLI via **`uv run`** (no need to activate the venv):

```bash
uv run python -m gmail_top_senders sync --db gmail_metadata.sqlite
# same as: uv run gmail-top-senders sync --db gmail_metadata.sqlite
```

If you prefer activating the environment: `source .venv/bin/activate` (Unix) or `.venv\Scripts\activate` (Windows), then use `python -m gmail_top_senders ...` as usual.

### Without uv (pip)

Note: I haven't tested this installation method. If you try it, let me know if
you have any issues, or if it works as expected.

From the repo root, with a virtualenv activated:

```bash
pip install .
```

Dependencies are read from `pyproject.toml`.

## Usage

**Sync** metadata from Gmail into SQLite (default query = all mail **except** Spam and Trash, including Archive—aligned with quota usage):

```bash
uv run python -m gmail_top_senders sync --db gmail_metadata.sqlite
```

First run opens a browser to authorize **read-only** access. A refresh token is stored in `token.json`.

Options:

- `-q` / `--query` — Gmail search string (default: `in:anywhere -in:spam -in:trash`)
- `--max-messages N` — stop after N messages (testing)
- `-v` / `--verbose` — progress on stderr + rate-limit backoff messages
- `--incremental` - skip fetching metadata for message IDs already
  in the DB (still performs a full messages.list pass)
- `--max-quota-units-per-minute` - (default 12000) to pace requests
  below the Gmail per-user quota ceiling of 15000 units/min

**Report** from the local database only (no API calls; safe to rerun with different grouping):

```bash
uv run python -m gmail_top_senders report --db gmail_metadata.sqlite
uv run python -m gmail_top_senders report --db gmail_metadata.sqlite --group-by display-name --top 30
uv run python -m gmail_top_senders report --db gmail_metadata.sqlite --sender alice@example.com
uv run python -m gmail_top_senders report --db gmail_metadata.sqlite --sender alice@example.com --top 40
uv run python -m gmail_top_senders report --db gmail_metadata.sqlite --csv > top.csv
```

## Privacy

The SQLite file contains message ids, From headers, and sizes—treat it like your mailbox metadata. Do not commit `*.sqlite`, `token.json`, or `credentials.json`.

## Default search query

The default `q` is **`in:anywhere -in:spam -in:trash`**, so archived mail is included. Override with `-q` if you only want e.g. `in:inbox`.
