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


async def init_db(db_path: str) -> None:
    Path(db_path).parent.mkdir(parents=True, exist_ok=True)
    async with aiosqlite.connect(db_path) as db:
        await db.execute("PRAGMA foreign_keys = ON")
        await db.execute(_CREATE_USERS)
        await db.execute(_CREATE_SUBSCRIPTIONS)
        await db.execute(_CREATE_PAYMENTS)
        await db.commit()
