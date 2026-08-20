# AGENTS.md

## Cursor Cloud specific instructions

Single service: a **Telegram bot** ("C-55") built with `aiogram` 3.x on Python 3.12, using an
async SQLite database (SQLAlchemy + `aiosqlite`) and an `apscheduler` job scheduler. There is no
web frontend. User/admin behaviour is documented in `BOT_GUIDE.md` (Ukrainian).

Python dependencies are installed by the startup update script (system `pip3` with
`--break-system-packages`), so no `venv` or `apt` step is needed at session start. Use plain
`python3` to run everything.

### Required configuration to run the bot

`core/config.py` calls `load_dotenv()` and then **raises `ValueError` if `BOT_TOKEN` is not set**.
Provide config via a `.env` file (see `.env.example`) or environment variables. Minimum:
`BOT_TOKEN` (from BotFather); for group features also `GROUP_CHAT_ID` and `ADMIN_IDS`.

- A **real** end-to-end run (the bot actually polling Telegram) needs a real `BOT_TOKEN`; without
  it the app boots fully (DB init, scheduler, routers, `🚀 Бот запущений!`) and only the first
  Telegram API call fails with `Unauthorized`.
- To exercise DB / handler logic **without** Telegram, set a placeholder token, e.g.
  `BOT_TOKEN=0000000000:PLACEHOLDER python3 <script>`.

### Run / test / build

- Run the bot (long-polling, foreground): `python3 main.py` (needs `.env` / env vars above).
- No lint or test framework is configured. For a quick sanity "lint", byte-compile everything:
  `python3 -m py_compile main.py import_data.py core/*.py database/*.py handlers/*.py schedule_system/*.py`.
- There is no build step (pure Python).
- `schedule_system/main_test.py` is a manual PDF-parsing check and needs a PDF at
  `schedule_system/data/current_schedule.pdf` (not in the repo). The pure formatter functions in
  `schedule_system/formatter.py` (`parse_lesson`, `extract_subject_code`, `expand_teacher`) can be
  tested without a PDF.

### Database

- SQLite file `c55_data.db` at the repo root (gitignored). `database.requests.init_db()` creates
  the schema and runs idempotent in-place migrations on every startup — no separate migration tool.
- Seed cadets in bulk with `python3 import_data.py`, which reads a `users_data.json`
  (`{ "<tg_id>": {"full_name", "username", "in_dorm", ...} }`) in the repo root. `users_data.json`
  is **not** gitignored, so remove any test seed file before committing.
- `users_backup.json` is written automatically by user-write operations (gitignored).

### Non-obvious gotcha

Brand-new-user registration via `add_or_update_user(..., update_existing=False)` (the `/start`
path) **commits the new user to the DB and then raises** `sqlalchemy.exc.MissingGreenlet` inside
`backup_user_to_json`: a freshly-constructed `User` triggers a synchronous lazy-load of its
`discipline` relationship in async context. Users loaded via a query/`get` are fine (the
relationship is `selectin`-loaded), so the update path and admin-approval path work. This is
pre-existing app behaviour, not an environment issue.
