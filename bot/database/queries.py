from datetime import datetime
from typing import Optional
import aiosqlite


async def upsert_user(
    db_path: str, user_id: int, username: Optional[str], first_name: str
) -> None:
    async with aiosqlite.connect(db_path) as db:
        await db.execute("PRAGMA foreign_keys = ON")
        await db.execute(
            """INSERT INTO users (id, username, first_name) VALUES (?, ?, ?)
               ON CONFLICT(id) DO UPDATE SET
                 username = excluded.username,
                 first_name = excluded.first_name""",
            (user_id, username, first_name),
        )
        await db.commit()


async def get_user(db_path: str, user_id: int) -> Optional[dict]:
    async with aiosqlite.connect(db_path) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            "SELECT * FROM users WHERE id = ?", (user_id,)
        ) as cursor:
            row = await cursor.fetchone()
            return dict(row) if row else None


async def is_user_banned(db_path: str, user_id: int) -> bool:
    async with aiosqlite.connect(db_path) as db:
        async with db.execute(
            "SELECT is_banned FROM users WHERE id = ?", (user_id,)
        ) as cursor:
            row = await cursor.fetchone()
            return bool(row[0]) if row else False


async def ban_user(db_path: str, user_id: int) -> None:
    async with aiosqlite.connect(db_path) as db:
        await db.execute("PRAGMA foreign_keys = ON")
        await db.execute("UPDATE users SET is_banned = 1 WHERE id = ?", (user_id,))
        # Otherwise the scheduler would keep auto-charging a banned user
        await db.execute(
            """UPDATE subscriptions SET status = 'cancelled'
               WHERE user_id = ? AND status = 'active'""",
            (user_id,),
        )
        await db.commit()


async def get_active_subscription(db_path: str, user_id: int) -> Optional[dict]:
    async with aiosqlite.connect(db_path) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            """SELECT * FROM subscriptions
               WHERE user_id = ?
                 AND status = 'active'
                 AND datetime(expires_at) > datetime('now')
               ORDER BY expires_at DESC
               LIMIT 1""",
            (user_id,),
        ) as cursor:
            row = await cursor.fetchone()
            return dict(row) if row else None


async def create_subscription(
    db_path: str, user_id: int, plan: str, expires_at: datetime
) -> int:
    async with aiosqlite.connect(db_path) as db:
        await db.execute("PRAGMA foreign_keys = ON")
        cursor = await db.execute(
            "INSERT INTO subscriptions (user_id, plan, expires_at) VALUES (?, ?, ?)",
            (user_id, plan, expires_at.isoformat()),
        )
        await db.commit()
        return cursor.lastrowid


async def save_payment_token(db_path: str, sub_id: int, token: str) -> None:
    async with aiosqlite.connect(db_path) as db:
        await db.execute("PRAGMA foreign_keys = ON")
        await db.execute(
            "UPDATE subscriptions SET payment_token = ? WHERE id = ?",
            (token, sub_id),
        )
        await db.commit()


async def extend_subscription(
    db_path: str, sub_id: int, new_expires_at: datetime
) -> None:
    async with aiosqlite.connect(db_path) as db:
        await db.execute("PRAGMA foreign_keys = ON")
        await db.execute(
            """UPDATE subscriptions
               SET expires_at = ?, in_grace = 0, grace_ends_at = NULL
               WHERE id = ?""",
            (new_expires_at.isoformat(), sub_id),
        )
        await db.commit()


async def expire_subscription(db_path: str, sub_id: int) -> None:
    async with aiosqlite.connect(db_path) as db:
        await db.execute("PRAGMA foreign_keys = ON")
        await db.execute(
            "UPDATE subscriptions SET status = 'expired' WHERE id = ?",
            (sub_id,),
        )
        await db.commit()


async def start_grace_period(
    db_path: str, sub_id: int, grace_ends_at: datetime
) -> None:
    async with aiosqlite.connect(db_path) as db:
        await db.execute("PRAGMA foreign_keys = ON")
        await db.execute(
            """UPDATE subscriptions
               SET in_grace = 1, grace_ends_at = ?
               WHERE id = ?""",
            (grace_ends_at.isoformat(), sub_id),
        )
        await db.commit()


async def create_payment(
    db_path: str, user_id: int, amount: int, plan: str
) -> int:
    async with aiosqlite.connect(db_path) as db:
        await db.execute("PRAGMA foreign_keys = ON")
        cursor = await db.execute(
            "INSERT INTO payments (user_id, amount, plan) VALUES (?, ?, ?)",
            (user_id, amount, plan),
        )
        await db.commit()
        return cursor.lastrowid


async def update_payment(
    db_path: str,
    record_id: int,
    status: str,
    external_id: Optional[str] = None,
) -> None:
    async with aiosqlite.connect(db_path) as db:
        await db.execute("PRAGMA foreign_keys = ON")
        await db.execute(
            "UPDATE payments SET status = ?, payment_id = ? WHERE id = ?",
            (status, external_id, record_id),
        )
        await db.commit()


async def get_pending_payment_by_external_id(
    db_path: str, external_id: str
) -> Optional[dict]:
    async with aiosqlite.connect(db_path) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            "SELECT * FROM payments WHERE payment_id = ? AND status = 'pending'",
            (external_id,),
        ) as cursor:
            row = await cursor.fetchone()
            return dict(row) if row else None


async def get_subscriptions_expiring_soon(db_path: str, days: int) -> list:
    from datetime import timedelta
    cutoff = (datetime.utcnow() + timedelta(days=days)).isoformat()
    async with aiosqlite.connect(db_path) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            """SELECT s.*, u.first_name, u.username
               FROM subscriptions s
               JOIN users u ON u.id = s.user_id
               WHERE s.status = 'active'
                 AND s.in_grace = 0
                 AND datetime(s.expires_at) > datetime('now')
                 AND datetime(s.expires_at) <= datetime(?)
                 AND NOT EXISTS (
                     SELECT 1 FROM subscriptions later
                     WHERE later.user_id = s.user_id
                       AND later.status = 'active'
                       AND datetime(later.expires_at) > datetime(s.expires_at)
                 )""",
            (cutoff,),
        ) as cursor:
            return [dict(row) async for row in cursor]


async def get_expired_subscriptions(db_path: str) -> list:
    """Active subscriptions past expires_at that are NOT yet in grace period."""
    async with aiosqlite.connect(db_path) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            """SELECT s.*, u.first_name, u.username
               FROM subscriptions s
               JOIN users u ON u.id = s.user_id
               WHERE s.status = 'active'
                 AND s.in_grace = 0
                 AND datetime(s.expires_at) <= datetime('now')"""
        ) as cursor:
            return [dict(row) async for row in cursor]


async def get_grace_period_ended(db_path: str) -> list:
    """Subscriptions in grace period where grace_ends_at has passed."""
    async with aiosqlite.connect(db_path) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            """SELECT s.*, u.first_name, u.username
               FROM subscriptions s
               JOIN users u ON u.id = s.user_id
               WHERE s.status = 'active'
                 AND s.in_grace = 1
                 AND datetime(s.grace_ends_at) <= datetime('now')"""
        ) as cursor:
            return [dict(row) async for row in cursor]


async def get_all_active_subscribers(db_path: str) -> list:
    async with aiosqlite.connect(db_path) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            """SELECT s.*, u.first_name, u.username
               FROM subscriptions s
               JOIN users u ON u.id = s.user_id
               WHERE s.status = 'active'
                 AND datetime(s.expires_at) > datetime('now')
               ORDER BY s.expires_at ASC"""
        ) as cursor:
            return [dict(row) async for row in cursor]


async def create_promo_code(db_path: str, code: str, days: int = 60) -> None:
    async with aiosqlite.connect(db_path) as db:
        await db.execute("PRAGMA foreign_keys = ON")
        await db.execute(
            "INSERT OR IGNORE INTO promo_codes (code, days) VALUES (?, ?)",
            (code, days),
        )
        await db.commit()


async def get_promo_code(db_path: str, code: str) -> Optional[dict]:
    async with aiosqlite.connect(db_path) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            "SELECT * FROM promo_codes WHERE code = ?", (code,)
        ) as cursor:
            row = await cursor.fetchone()
            return dict(row) if row else None


async def use_promo_code(db_path: str, code: str, user_id: int) -> bool:
    """Marks the code as used. Returns False if someone already used it."""
    async with aiosqlite.connect(db_path) as db:
        await db.execute("PRAGMA foreign_keys = ON")
        cursor = await db.execute(
            """UPDATE promo_codes SET is_used = 1, used_by = ?, used_at = ?
               WHERE code = ? AND is_used = 0""",
            (user_id, datetime.utcnow().isoformat(), code),
        )
        await db.commit()
        return cursor.rowcount == 1


async def get_all_promo_codes(db_path: str) -> list:
    async with aiosqlite.connect(db_path) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            "SELECT * FROM promo_codes ORDER BY created_at DESC"
        ) as cursor:
            return [dict(row) async for row in cursor]


async def get_monthly_revenue(db_path: str) -> int:
    async with aiosqlite.connect(db_path) as db:
        async with db.execute(
            """SELECT COALESCE(SUM(amount), 0)
               FROM payments
               WHERE status = 'success'
                 AND created_at >= datetime('now', 'start of month')"""
        ) as cursor:
            row = await cursor.fetchone()
            return row[0] if row else 0
