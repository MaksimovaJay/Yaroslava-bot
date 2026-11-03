from pathlib import Path
import aiosqlite

_CREATE_USERS = """
CREATE TABLE IF NOT EXISTS users (
    id          INTEGER PRIMARY KEY,
    username    TEXT,
    first_name  TEXT NOT NULL,
    created_at  DATETIME DEFAULT CURRENT_TIMESTAMP,
    is_banned   INTEGER DEFAULT 0
)
"""

_CREATE_SUBSCRIPTIONS = """
CREATE TABLE IF NOT EXISTS subscriptions (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id       INTEGER NOT NULL REFERENCES users(id),
    plan          TEXT NOT NULL CHECK(plan IN ('1m', '2m')),
    started_at    DATETIME DEFAULT CURRENT_TIMESTAMP,
    expires_at    DATETIME NOT NULL,
    status        TEXT NOT NULL DEFAULT 'active'
                  CHECK(status IN ('active', 'expired', 'cancelled')),
    payment_token TEXT,
    in_grace      INTEGER DEFAULT 0,
    grace_ends_at DATETIME
)
"""

_CREATE_PAYMENTS = """
CREATE TABLE IF NOT EXISTS payments (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id    INTEGER NOT NULL REFERENCES users(id),
    amount     INTEGER NOT NULL,
    plan       TEXT NOT NULL CHECK(plan IN ('1m', '2m')),
    status     TEXT NOT NULL DEFAULT 'pending'
               CHECK(status IN ('pending', 'success', 'failed')),
    payment_id TEXT,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP
)
"""


_CREATE_PROMO_CODES = """
CREATE TABLE IF NOT EXISTS promo_codes (
    code       TEXT PRIMARY KEY,
    is_used    INTEGER DEFAULT 0,
    used_by    INTEGER REFERENCES users(id),
    used_at    DATETIME,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    days       INTEGER NOT NULL DEFAULT 60
)
"""


# One row per user: Tribute keeps a single subscription per channel
_CREATE_TRIBUTE_SUBSCRIPTIONS = """
CREATE TABLE IF NOT EXISTS tribute_subscriptions (
    user_id         INTEGER PRIMARY KEY REFERENCES users(id),
    subscription_id INTEGER,
    period_id       INTEGER,
    status          TEXT NOT NULL CHECK(status IN ('active', 'cancelled')),
    expires_at      DATETIME NOT NULL,
    last_event_at   DATETIME NOT NULL
)
"""

# Tribute retries webhooks for ~24h, the unique key drops repeats
_CREATE_TRIBUTE_EVENTS = """
CREATE TABLE IF NOT EXISTS tribute_events (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    name             TEXT NOT NULL,
    user_id          INTEGER NOT NULL,
    event_created_at TEXT NOT NULL,
    amount           INTEGER,
    currency         TEXT,
    received_at      DATETIME DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(name, user_id, event_created_at)
)
"""


async def _add_column_if_missing(db, table: str, column: str, ddl: str) -> None:
    async with db.execute(f"PRAGMA table_info({table})") as cursor:
        columns = {row[1] async for row in cursor}
    if column not in columns:
        await db.execute(f"ALTER TABLE {table} ADD COLUMN {column} {ddl}")


async def init_db(db_path: str) -> None:
    Path(db_path).parent.mkdir(parents=True, exist_ok=True)
    async with aiosqlite.connect(db_path) as db:
        await db.execute("PRAGMA foreign_keys = ON")
        await db.execute(_CREATE_USERS)
        await db.execute(_CREATE_SUBSCRIPTIONS)
        await db.execute(_CREATE_PAYMENTS)
        await db.execute(_CREATE_PROMO_CODES)
        await db.execute(_CREATE_TRIBUTE_SUBSCRIPTIONS)
        await db.execute(_CREATE_TRIBUTE_EVENTS)
        await _add_column_if_missing(
            db, "promo_codes", "days", "INTEGER NOT NULL DEFAULT 60"
        )
        await db.commit()
