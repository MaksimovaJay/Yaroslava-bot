# Telegram Subscription Bot — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a Python Telegram bot that manages paid subscriptions for a private channel — users pay 500₽/month or 900₽/2 months, auto-renewal with 3-day grace period, admin panel in Telegram.

**Architecture:** Modular aiogram 3 bot with SQLite via aiosqlite, APScheduler for daily subscription checks, and a payment abstraction layer (stub now → ЮKassa later). Long polling on a VPS (Beget Ubuntu 24.04).

**Tech Stack:** Python 3.11+, aiogram 3.x, aiosqlite, APScheduler, python-dotenv, pytest, pytest-asyncio

---

## File Map

```
bot/
├── main.py                        # Entry point — wires everything together
├── config.py                      # Config dataclass loaded from .env
├── database/
│   ├── __init__.py
│   ├── db.py                      # init_db(): creates all tables
│   └── queries.py                 # All SQL — upsert_user, subscriptions, payments
├── services/
│   ├── __init__.py
│   ├── subscription.py            # create_subscription, renew_subscription, kick_user
│   └── payment/
│       ├── __init__.py
│       ├── base.py                # PaymentProvider ABC + PaymentResult dataclass
│       └── stub.py                # StubPaymentProvider — always succeeds
├── handlers/
│   ├── __init__.py
│   ├── start.py                   # /start command
│   ├── join.py                    # ChatJoinRequest handler
│   ├── payment.py                 # plan selection + payment confirmation callbacks
│   └── admin.py                   # /admin command + inline menu + FSM for ban/add
├── scheduler.py                   # daily_job + exposed functions for testing
├── requirements.txt
├── .env.example
├── pytest.ini
├── deploy/
│   └── bot.service                # systemd unit file
└── tests/
    ├── __init__.py
    ├── conftest.py                # shared pytest fixtures
    ├── test_db_init.py
    ├── test_queries.py
    ├── test_payment_stub.py
    ├── test_subscription.py
    └── test_scheduler.py
```

---

## Task 1: Project scaffolding

**Files:**
- Create: `bot/requirements.txt`
- Create: `bot/.env.example`
- Create: `bot/config.py`

- [ ] **Step 1: Create `bot/` directory and `requirements.txt`**

```
aiogram==3.13.1
aiosqlite==0.20.0
APScheduler==3.10.4
python-dotenv==1.0.1
pytest==8.3.3
pytest-asyncio==0.24.0
```

- [ ] **Step 2: Create `pytest.ini`**

```ini
[pytest]
asyncio_mode = auto
```

- [ ] **Step 3: Create `.env.example`**

```
BOT_TOKEN=7123456789:AAFxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
ADMIN_ID=123456789
CHANNEL_ID=-1001234567890
DB_PATH=data/bot.db
```

- [ ] **Step 4: Create `config.py`**

```python
import os
from dataclasses import dataclass, field
from dotenv import load_dotenv

load_dotenv()


@dataclass
class Config:
    bot_token: str
    admin_id: int
    channel_id: int
    db_path: str

    PLAN_1M_PRICE: int = field(default=500, init=False)
    PLAN_2M_PRICE: int = field(default=900, init=False)
    PLAN_1M_DAYS: int = field(default=30, init=False)
    PLAN_2M_DAYS: int = field(default=60, init=False)
    GRACE_PERIOD_DAYS: int = field(default=3, init=False)
    REMINDER_DAYS_BEFORE: int = field(default=3, init=False)


def load_config() -> Config:
    return Config(
        bot_token=os.environ["BOT_TOKEN"],
        admin_id=int(os.environ["ADMIN_ID"]),
        channel_id=int(os.environ["CHANNEL_ID"]),
        db_path=os.environ.get("DB_PATH", "data/bot.db"),
    )
```

- [ ] **Step 5: Install dependencies**

```bash
cd bot
python -m venv venv
source venv/bin/activate          # Linux/Mac
# venv\Scripts\activate           # Windows
pip install -r requirements.txt
```

Expected: all packages install without errors.

- [ ] **Step 6: Commit**

```bash
git init
git add .
git commit -m "feat: project scaffolding — config, requirements, pytest config"
```

---

## Task 2: Database init

**Files:**
- Create: `bot/database/__init__.py`
- Create: `bot/database/db.py`
- Create: `bot/tests/__init__.py`
- Create: `bot/tests/conftest.py`
- Create: `bot/tests/test_db_init.py`

- [ ] **Step 1: Write the failing test**

`tests/test_db_init.py`:
```python
import tempfile
import pytest
import aiosqlite
from database.db import init_db


@pytest.mark.asyncio
async def test_init_creates_all_three_tables():
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        path = f.name
    await init_db(path)
    async with aiosqlite.connect(path) as db:
        async with db.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ) as cursor:
            tables = {row[0] async for row in cursor}
    assert "users" in tables
    assert "subscriptions" in tables
    assert "payments" in tables


@pytest.mark.asyncio
async def test_init_is_idempotent():
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        path = f.name
    await init_db(path)
    await init_db(path)  # must not raise
```

`tests/conftest.py`: (empty file — `asyncio_mode = auto` in `pytest.ini` handles async fixtures)

`tests/__init__.py`: (empty file)

- [ ] **Step 2: Run test — expect FAIL**

```bash
cd bot && python -m pytest tests/test_db_init.py -v
```

Expected: `ModuleNotFoundError: No module named 'database'`

- [ ] **Step 3: Create `database/__init__.py`** (empty)

- [ ] **Step 4: Create `database/db.py`**

```python
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
    plan       TEXT NOT NULL,
    status     TEXT NOT NULL DEFAULT 'pending'
               CHECK(status IN ('pending', 'success', 'failed')),
    payment_id TEXT,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP
)
"""


async def init_db(db_path: str) -> None:
    Path(db_path).parent.mkdir(parents=True, exist_ok=True)
    async with aiosqlite.connect(db_path) as db:
        await db.execute(_CREATE_USERS)
        await db.execute(_CREATE_SUBSCRIPTIONS)
        await db.execute(_CREATE_PAYMENTS)
        await db.commit()
```

- [ ] **Step 5: Run test — expect PASS**

```bash
python -m pytest tests/test_db_init.py -v
```

Expected: `2 passed`

- [ ] **Step 6: Commit**

```bash
git add database/ tests/
git commit -m "feat: database schema — users, subscriptions, payments tables"
```

---

## Task 3: Database queries

**Files:**
- Create: `bot/database/queries.py`
- Create: `bot/tests/test_queries.py`

- [ ] **Step 1: Write failing tests**

`tests/test_queries.py`:
```python
import tempfile
import pytest
from datetime import datetime, timedelta
from database.db import init_db
from database import queries


@pytest.fixture
async def db(tmp_path):
    path = str(tmp_path / "test.db")
    await init_db(path)
    return path


@pytest.mark.asyncio
async def test_upsert_and_get_user(db):
    await queries.upsert_user(db, 1, "alice", "Alice")
    user = await queries.get_user(db, 1)
    assert user["id"] == 1
    assert user["first_name"] == "Alice"
    assert user["username"] == "alice"
    assert user["is_banned"] == 0


@pytest.mark.asyncio
async def test_upsert_updates_existing_user(db):
    await queries.upsert_user(db, 1, "alice", "Alice")
    await queries.upsert_user(db, 1, "alice2", "Alice Updated")
    user = await queries.get_user(db, 1)
    assert user["first_name"] == "Alice Updated"
    assert user["username"] == "alice2"


@pytest.mark.asyncio
async def test_ban_user(db):
    await queries.upsert_user(db, 2, None, "Bob")
    assert not await queries.is_user_banned(db, 2)
    await queries.ban_user(db, 2)
    assert await queries.is_user_banned(db, 2)


@pytest.mark.asyncio
async def test_get_active_subscription(db):
    await queries.upsert_user(db, 3, None, "Carol")
    expires = datetime.now() + timedelta(days=30)
    await queries.create_subscription(db, 3, "1m", expires)
    sub = await queries.get_active_subscription(db, 3)
    assert sub is not None
    assert sub["plan"] == "1m"
    assert sub["status"] == "active"


@pytest.mark.asyncio
async def test_expired_subscription_not_returned_as_active(db):
    await queries.upsert_user(db, 4, None, "Dave")
    expires = datetime.now() - timedelta(days=1)
    await queries.create_subscription(db, 4, "1m", expires)
    sub = await queries.get_active_subscription(db, 4)
    assert sub is None


@pytest.mark.asyncio
async def test_create_payment_and_update(db):
    await queries.upsert_user(db, 5, None, "Eve")
    pay_id = await queries.create_payment(db, 5, 500, "1m")
    assert pay_id is not None
    await queries.update_payment(db, pay_id, "success", "ext_123")


@pytest.mark.asyncio
async def test_expire_subscription(db):
    await queries.upsert_user(db, 6, None, "Frank")
    expires = datetime.now() + timedelta(days=30)
    await queries.create_subscription(db, 6, "1m", expires)
    sub = await queries.get_active_subscription(db, 6)
    await queries.expire_subscription(db, sub["id"])
    assert await queries.get_active_subscription(db, 6) is None


@pytest.mark.asyncio
async def test_start_grace_period(db):
    await queries.upsert_user(db, 7, None, "Grace")
    expires = datetime.now() - timedelta(hours=1)
    await queries.create_subscription(db, 7, "1m", expires)
    subs = await queries.get_expired_subscriptions(db)
    assert len(subs) == 1
    grace_end = datetime.now() + timedelta(days=3)
    await queries.start_grace_period(db, subs[0]["id"], grace_end)
    expired_now = await queries.get_expired_subscriptions(db)
    assert len(expired_now) == 0


@pytest.mark.asyncio
async def test_get_monthly_revenue(db):
    await queries.upsert_user(db, 8, None, "Hannah")
    pay_id = await queries.create_payment(db, 8, 500, "1m")
    await queries.update_payment(db, pay_id, "success", "ext_1")
    pay_id2 = await queries.create_payment(db, 8, 500, "1m")
    await queries.update_payment(db, pay_id2, "failed", None)
    revenue = await queries.get_monthly_revenue(db)
    assert revenue == 500
```

- [ ] **Step 2: Run tests — expect FAIL**

```bash
python -m pytest tests/test_queries.py -v
```

Expected: `ModuleNotFoundError` or `AttributeError`

- [ ] **Step 3: Create `database/queries.py`**

```python
from datetime import datetime
from typing import Optional
import aiosqlite


async def upsert_user(
    db_path: str, user_id: int, username: Optional[str], first_name: str
) -> None:
    async with aiosqlite.connect(db_path) as db:
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
        await db.execute("UPDATE users SET is_banned = 1 WHERE id = ?", (user_id,))
        await db.commit()


async def get_active_subscription(db_path: str, user_id: int) -> Optional[dict]:
    async with aiosqlite.connect(db_path) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            """SELECT * FROM subscriptions
               WHERE user_id = ?
                 AND status = 'active'
                 AND expires_at > datetime('now')
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
        cursor = await db.execute(
            "INSERT INTO subscriptions (user_id, plan, expires_at) VALUES (?, ?, ?)",
            (user_id, plan, expires_at.isoformat()),
        )
        await db.commit()
        return cursor.lastrowid


async def extend_subscription(
    db_path: str, sub_id: int, new_expires_at: datetime
) -> None:
    async with aiosqlite.connect(db_path) as db:
        await db.execute(
            """UPDATE subscriptions
               SET expires_at = ?, in_grace = 0, grace_ends_at = NULL
               WHERE id = ?""",
            (new_expires_at.isoformat(), sub_id),
        )
        await db.commit()


async def expire_subscription(db_path: str, sub_id: int) -> None:
    async with aiosqlite.connect(db_path) as db:
        await db.execute(
            "UPDATE subscriptions SET status = 'expired' WHERE id = ?",
            (sub_id,),
        )
        await db.commit()


async def start_grace_period(
    db_path: str, sub_id: int, grace_ends_at: datetime
) -> None:
    async with aiosqlite.connect(db_path) as db:
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
        cursor = await db.execute(
            "INSERT INTO payments (user_id, amount, plan) VALUES (?, ?, ?)",
            (user_id, amount, plan),
        )
        await db.commit()
        return cursor.lastrowid


async def update_payment(
    db_path: str,
    payment_id: int,
    status: str,
    external_id: Optional[str] = None,
) -> None:
    async with aiosqlite.connect(db_path) as db:
        await db.execute(
            "UPDATE payments SET status = ?, payment_id = ? WHERE id = ?",
            (status, external_id, payment_id),
        )
        await db.commit()


async def get_subscriptions_expiring_soon(db_path: str, days: int) -> list:
    async with aiosqlite.connect(db_path) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            """SELECT s.*, u.first_name, u.username
               FROM subscriptions s
               JOIN users u ON u.id = s.user_id
               WHERE s.status = 'active'
                 AND s.in_grace = 0
                 AND s.expires_at > datetime('now')
                 AND s.expires_at <= datetime('now', ? || ' days')""",
            (str(days),),
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
                 AND s.expires_at <= datetime('now')"""
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
                 AND s.grace_ends_at <= datetime('now')"""
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
                 AND s.expires_at > datetime('now')
               ORDER BY s.expires_at ASC"""
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
```

- [ ] **Step 4: Run tests — expect PASS**

```bash
python -m pytest tests/test_queries.py -v
```

Expected: `9 passed`

- [ ] **Step 5: Commit**

```bash
git add database/queries.py tests/test_queries.py
git commit -m "feat: database queries — users, subscriptions, payments CRUD"
```

---

## Task 4: Payment abstraction

**Files:**
- Create: `bot/services/__init__.py`
- Create: `bot/services/payment/__init__.py`
- Create: `bot/services/payment/base.py`
- Create: `bot/services/payment/stub.py`
- Create: `bot/tests/test_payment_stub.py`

- [ ] **Step 1: Write failing test**

`tests/test_payment_stub.py`:
```python
import pytest
from services.payment.stub import StubPaymentProvider


@pytest.mark.asyncio
async def test_stub_create_payment_always_succeeds():
    provider = StubPaymentProvider()
    result = await provider.create_payment(123, 500, "1m")
    assert result.success is True
    assert result.payment_id is not None
    assert result.error is None


@pytest.mark.asyncio
async def test_stub_charge_saved_always_succeeds():
    provider = StubPaymentProvider()
    result = await provider.charge_saved(123, "any_token", 500)
    assert result.success is True
    assert result.payment_id is not None
```

- [ ] **Step 2: Run test — expect FAIL**

```bash
python -m pytest tests/test_payment_stub.py -v
```

Expected: `ModuleNotFoundError`

- [ ] **Step 3: Create `services/__init__.py`** (empty)

- [ ] **Step 4: Create `services/payment/__init__.py`** (empty)

- [ ] **Step 5: Create `services/payment/base.py`**

```python
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Optional


@dataclass
class PaymentResult:
    success: bool
    payment_id: Optional[str] = None
    payment_url: Optional[str] = None
    error: Optional[str] = None


class PaymentProvider(ABC):
    @abstractmethod
    async def create_payment(
        self, user_id: int, amount: int, plan: str
    ) -> PaymentResult: ...

    @abstractmethod
    async def charge_saved(
        self, user_id: int, payment_token: Optional[str], amount: int
    ) -> PaymentResult: ...
```

- [ ] **Step 6: Create `services/payment/stub.py`**

```python
from typing import Optional
from .base import PaymentProvider, PaymentResult


class StubPaymentProvider(PaymentProvider):
    async def create_payment(
        self, user_id: int, amount: int, plan: str
    ) -> PaymentResult:
        return PaymentResult(
            success=True,
            payment_id=f"stub_{user_id}_{plan}",
        )

    async def charge_saved(
        self, user_id: int, payment_token: Optional[str], amount: int
    ) -> PaymentResult:
        return PaymentResult(
            success=True,
            payment_id=f"stub_renew_{user_id}",
        )
```

- [ ] **Step 7: Run test — expect PASS**

```bash
python -m pytest tests/test_payment_stub.py -v
```

Expected: `2 passed`

- [ ] **Step 8: Commit**

```bash
git add services/ tests/test_payment_stub.py
git commit -m "feat: payment abstraction — PaymentProvider interface and stub"
```

---

## Task 5: Subscription service

**Files:**
- Create: `bot/services/subscription.py`
- Create: `bot/tests/test_subscription.py`

- [ ] **Step 1: Write failing tests**

`tests/test_subscription.py`:
```python
import pytest
from datetime import datetime, timedelta
from database.db import init_db
from database import queries
from services.subscription import (
    create_subscription,
    renew_subscription,
)


@pytest.fixture
async def db(tmp_path):
    path = str(tmp_path / "test.db")
    await init_db(path)
    await queries.upsert_user(path, 1, None, "TestUser")
    return path


@pytest.fixture
def config(db):
    from config import Config
    c = Config(bot_token="x", admin_id=1, channel_id=-100, db_path=db)
    return c


@pytest.mark.asyncio
async def test_create_1m_subscription_expiry(db, config):
    sub = await create_subscription(db, 1, "1m", config)
    diff = (sub["expires_at"] - datetime.now()).days
    assert 29 <= diff <= 30


@pytest.mark.asyncio
async def test_create_2m_subscription_expiry(db, config):
    sub = await create_subscription(db, 1, "2m", config)
    diff = (sub["expires_at"] - datetime.now()).days
    assert 59 <= diff <= 60


@pytest.mark.asyncio
async def test_renew_subscription_extends_from_expiry(db, config):
    sub = await create_subscription(db, 1, "1m", config)
    old_expires = sub["expires_at"]
    db_sub = await queries.get_active_subscription(db, 1)
    new_expires = await renew_subscription(db, db_sub, config)
    assert new_expires > old_expires
    diff = (new_expires - old_expires).days
    assert 29 <= diff <= 30


@pytest.mark.asyncio
async def test_renew_expired_subscription_starts_from_now(db, config):
    past = datetime.now() - timedelta(days=5)
    sub_id = await queries.create_subscription(db, 1, "1m", past)
    db_sub = {"id": sub_id, "plan": "1m", "expires_at": past.isoformat()}
    new_expires = await renew_subscription(db, db_sub, config)
    diff = (new_expires - datetime.now()).days
    assert 29 <= diff <= 30
```

- [ ] **Step 2: Run test — expect FAIL**

```bash
python -m pytest tests/test_subscription.py -v
```

Expected: `ModuleNotFoundError`

- [ ] **Step 3: Create `services/subscription.py`**

```python
from datetime import datetime, timedelta
from typing import Optional
from aiogram import Bot

from config import Config
from database import queries


async def create_subscription(
    db_path: str, user_id: int, plan: str, config: Config
) -> dict:
    days = config.PLAN_1M_DAYS if plan == "1m" else config.PLAN_2M_DAYS
    expires_at = datetime.now() + timedelta(days=days)
    sub_id = await queries.create_subscription(db_path, user_id, plan, expires_at)
    return {"id": sub_id, "expires_at": expires_at, "plan": plan}


async def renew_subscription(
    db_path: str, sub: dict, config: Config
) -> datetime:
    days = config.PLAN_1M_DAYS if sub["plan"] == "1m" else config.PLAN_2M_DAYS
    old_expires = datetime.fromisoformat(sub["expires_at"])
    base = max(datetime.now(), old_expires)
    new_expires = base + timedelta(days=days)
    await queries.extend_subscription(db_path, sub["id"], new_expires)
    return new_expires


async def kick_user(bot: Bot, channel_id: int, user_id: int) -> None:
    await bot.ban_chat_member(channel_id, user_id)
    await bot.unban_chat_member(channel_id, user_id)
```

- [ ] **Step 4: Run test — expect PASS**

```bash
python -m pytest tests/test_subscription.py -v
```

Expected: `4 passed`

- [ ] **Step 5: Commit**

```bash
git add services/subscription.py tests/test_subscription.py
git commit -m "feat: subscription service — create, renew, kick"
```

---

## Task 6: Scheduler

**Files:**
- Create: `bot/scheduler.py`
- Create: `bot/tests/test_scheduler.py`

- [ ] **Step 1: Write failing tests**

`tests/test_scheduler.py`:
```python
import pytest
from datetime import datetime, timedelta
from unittest.mock import AsyncMock, MagicMock
from database.db import init_db
from database import queries
from scheduler import send_expiry_reminders, process_expired_subscriptions, process_grace_period_ended


@pytest.fixture
async def db(tmp_path):
    path = str(tmp_path / "test.db")
    await init_db(path)
    await queries.upsert_user(path, 100, None, "TestUser")
    return path


@pytest.fixture
def config(db):
    c = MagicMock()
    c.db_path = db
    c.channel_id = -100
    c.PLAN_1M_PRICE = 500
    c.PLAN_2M_PRICE = 900
    c.PLAN_1M_DAYS = 30
    c.PLAN_2M_DAYS = 60
    c.GRACE_PERIOD_DAYS = 3
    c.REMINDER_DAYS_BEFORE = 3
    return c


@pytest.mark.asyncio
async def test_send_reminder_for_expiring_subscription(db, config):
    expires = datetime.now() + timedelta(days=2)
    await queries.create_subscription(db, 100, "1m", expires)
    bot = AsyncMock()
    await send_expiry_reminders(bot, config)
    bot.send_message.assert_called_once()
    call_args = bot.send_message.call_args
    assert call_args[0][0] == 100


@pytest.mark.asyncio
async def test_no_reminder_for_non_expiring_subscription(db, config):
    expires = datetime.now() + timedelta(days=10)
    await queries.create_subscription(db, 100, "1m", expires)
    bot = AsyncMock()
    await send_expiry_reminders(bot, config)
    bot.send_message.assert_not_called()


@pytest.mark.asyncio
async def test_successful_charge_extends_subscription(db, config):
    expires = datetime.now() - timedelta(hours=1)
    await queries.create_subscription(db, 100, "1m", expires)
    bot = AsyncMock()
    payment = AsyncMock()
    payment.charge_saved.return_value = MagicMock(success=True, payment_id="p1")
    await process_expired_subscriptions(bot, config, payment)
    sub = await queries.get_active_subscription(db, 100)
    assert sub is not None
    new_expires = datetime.fromisoformat(sub["expires_at"])
    assert new_expires > datetime.now() + timedelta(days=28)


@pytest.mark.asyncio
async def test_failed_charge_starts_grace_period(db, config):
    expires = datetime.now() - timedelta(hours=1)
    await queries.create_subscription(db, 100, "1m", expires)
    bot = AsyncMock()
    payment = AsyncMock()
    payment.charge_saved.return_value = MagicMock(success=False, error="no token")
    await process_expired_subscriptions(bot, config, payment)
    active = await queries.get_all_active_subscribers(db)
    assert len(active) == 0
    async import aiosqlite
    async with aiosqlite.connect(db) as conn:
        async with conn.execute(
            "SELECT in_grace FROM subscriptions WHERE user_id = 100"
        ) as cur:
            row = await cur.fetchone()
    assert row[0] == 1


@pytest.mark.asyncio
async def test_grace_period_ended_kicks_user(db, config):
    expires = datetime.now() - timedelta(days=4)
    sub_id = await queries.create_subscription(db, 100, "1m", expires)
    grace_end = datetime.now() - timedelta(hours=1)
    await queries.start_grace_period(db, sub_id, grace_end)
    bot = AsyncMock()
    await process_grace_period_ended(bot, config)
    bot.ban_chat_member.assert_called_once_with(-100, 100)
    bot.unban_chat_member.assert_called_once_with(-100, 100)
    sub = await queries.get_active_subscription(db, 100)
    assert sub is None
```

- [ ] **Step 2: Run test — expect FAIL**

```bash
python -m pytest tests/test_scheduler.py -v
```

Expected: `ModuleNotFoundError: No module named 'scheduler'`

Note: `test_failed_charge_starts_grace_period` uses `async import` which is invalid — fix to use `import aiosqlite` at the top.

- [ ] **Step 3: Fix the import in test** — move `import aiosqlite` to the top of `tests/test_scheduler.py`:

```python
import aiosqlite
import pytest
from datetime import datetime, timedelta
from unittest.mock import AsyncMock, MagicMock
from database.db import init_db
from database import queries
from scheduler import send_expiry_reminders, process_expired_subscriptions, process_grace_period_ended
```

And update the test body to remove the `async import`:
```python
@pytest.mark.asyncio
async def test_failed_charge_starts_grace_period(db, config):
    expires = datetime.now() - timedelta(hours=1)
    await queries.create_subscription(db, 100, "1m", expires)
    bot = AsyncMock()
    payment = AsyncMock()
    payment.charge_saved.return_value = MagicMock(success=False, error="no token")
    await process_expired_subscriptions(bot, config, payment)
    active = await queries.get_all_active_subscribers(db)
    assert len(active) == 0
    async with aiosqlite.connect(db) as conn:
        async with conn.execute(
            "SELECT in_grace FROM subscriptions WHERE user_id = 100"
        ) as cur:
            row = await cur.fetchone()
    assert row[0] == 1
```

- [ ] **Step 4: Create `scheduler.py`**

```python
from datetime import datetime, timedelta
import logging

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from aiogram import Bot

from config import Config
from database import queries
from services.subscription import renew_subscription, kick_user
from services.payment.base import PaymentProvider

logger = logging.getLogger(__name__)


async def send_expiry_reminders(bot: Bot, config: Config) -> None:
    expiring = await queries.get_subscriptions_expiring_soon(
        config.db_path, config.REMINDER_DAYS_BEFORE
    )
    for sub in expiring:
        expires_date = sub["expires_at"][:10]
        try:
            await bot.send_message(
                sub["user_id"],
                f"⏰ Ваша подписка истекает {expires_date}.\n"
                f"Она продлится автоматически — ничего делать не нужно.",
            )
        except Exception as e:
            logger.warning("Could not send reminder to %s: %s", sub["user_id"], e)


async def process_expired_subscriptions(
    bot: Bot, config: Config, payment: PaymentProvider
) -> None:
    expired = await queries.get_expired_subscriptions(config.db_path)
    for sub in expired:
        amount = (
            config.PLAN_1M_PRICE if sub["plan"] == "1m" else config.PLAN_2M_PRICE
        )
        result = await payment.charge_saved(
            sub["user_id"], sub.get("payment_token"), amount
        )
        if result.success:
            new_expires = await renew_subscription(config.db_path, sub, config)
            await queries.create_payment(config.db_path, sub["user_id"], amount, sub["plan"])
            try:
                await bot.send_message(
                    sub["user_id"],
                    f"✅ Подписка продлена до {new_expires.strftime('%d.%m.%Y')}!",
                )
            except Exception as e:
                logger.warning("Could not notify %s: %s", sub["user_id"], e)
        else:
            grace_ends_at = datetime.now() + timedelta(days=config.GRACE_PERIOD_DAYS)
            await queries.start_grace_period(config.db_path, sub["id"], grace_ends_at)
            try:
                await bot.send_message(
                    sub["user_id"],
                    f"⚠️ Не удалось списать оплату за подписку.\n"
                    f"У вас есть {config.GRACE_PERIOD_DAYS} дня, чтобы оплатить вручную.\n"
                    f"Напишите /pay для оплаты.",
                )
            except Exception as e:
                logger.warning("Could not notify %s: %s", sub["user_id"], e)


async def process_grace_period_ended(bot: Bot, config: Config) -> None:
    ended = await queries.get_grace_period_ended(config.db_path)
    for sub in ended:
        try:
            await kick_user(bot, config.channel_id, sub["user_id"])
        except Exception as e:
            logger.warning("Could not kick %s: %s", sub["user_id"], e)
        await queries.expire_subscription(config.db_path, sub["id"])
        try:
            await bot.send_message(
                sub["user_id"],
                "❌ Подписка истекла, доступ к каналу закрыт.\n"
                "Чтобы подписаться снова — перейдите по ссылке на канал.",
            )
        except Exception as e:
            logger.warning("Could not notify %s: %s", sub["user_id"], e)


async def daily_job(bot: Bot, config: Config, payment: PaymentProvider) -> None:
    logger.info("Running daily subscription check")
    await send_expiry_reminders(bot, config)
    await process_expired_subscriptions(bot, config, payment)
    await process_grace_period_ended(bot, config)


def create_scheduler(
    bot: Bot, config: Config, payment: PaymentProvider
) -> AsyncIOScheduler:
    scheduler = AsyncIOScheduler()
    scheduler.add_job(
        daily_job,
        trigger="cron",
        hour=10,
        minute=0,
        args=[bot, config, payment],
    )
    return scheduler
```

- [ ] **Step 5: Run tests — expect PASS**

```bash
python -m pytest tests/test_scheduler.py -v
```

Expected: `5 passed`

- [ ] **Step 6: Commit**

```bash
git add scheduler.py tests/test_scheduler.py
git commit -m "feat: scheduler — daily reminders, auto-renewal, grace period, kicking"
```

---

## Task 7: Start + Join handlers

**Files:**
- Create: `bot/handlers/__init__.py`
- Create: `bot/handlers/start.py`
- Create: `bot/handlers/join.py`

**Important note:** For `ChatJoinRequest` to work, the bot must be admin of the channel with "Add members" right, and "Join requests" must be enabled in channel settings.

- [ ] **Step 1: Create `handlers/__init__.py`** (empty)

- [ ] **Step 2: Create `handlers/start.py`**

```python
from aiogram import Router
from aiogram.filters import CommandStart
from aiogram.types import Message

from config import Config
from database import queries

router = Router()


@router.message(CommandStart())
async def cmd_start(message: Message, config: Config) -> None:
    await queries.upsert_user(
        config.db_path,
        message.from_user.id,
        message.from_user.username,
        message.from_user.first_name,
    )
    sub = await queries.get_active_subscription(config.db_path, message.from_user.id)
    if sub:
        expires = sub["expires_at"][:10]
        await message.answer(
            f"👋 Привет, {message.from_user.first_name}!\n\n"
            f"Ваша подписка активна до {expires}."
        )
    else:
        await message.answer(
            f"👋 Привет, {message.from_user.first_name}!\n\n"
            f"Чтобы получить доступ к каналу — перейдите по ссылке на канал "
            f"и подайте заявку на вступление."
        )
```

- [ ] **Step 3: Create `handlers/join.py`**

```python
import logging
from aiogram import Router, Bot
from aiogram.types import ChatJoinRequest
from aiogram.utils.keyboard import InlineKeyboardBuilder

from config import Config
from database import queries

router = Router()
logger = logging.getLogger(__name__)


@router.chat_join_request()
async def handle_join_request(
    request: ChatJoinRequest, bot: Bot, config: Config
) -> None:
    user = request.from_user
    channel_id = request.chat.id

    await queries.upsert_user(
        config.db_path, user.id, user.username, user.first_name
    )

    if await queries.is_user_banned(config.db_path, user.id):
        await request.decline()
        return

    sub = await queries.get_active_subscription(config.db_path, user.id)
    if sub:
        await request.approve()
        return

    builder = InlineKeyboardBuilder()
    builder.button(
        text="💳 1 месяц — 500 ₽",
        callback_data=f"plan:1m:{channel_id}",
    )
    builder.button(
        text="💳 2 месяца — 900 ₽",
        callback_data=f"plan:2m:{channel_id}",
    )
    builder.adjust(1)

    try:
        await bot.send_message(
            user.id,
            f"👋 Привет, {user.first_name}!\n\n"
            f"Это закрытый канал с платной подпиской.\n"
            f"Выберите тариф:",
            reply_markup=builder.as_markup(),
        )
    except Exception:
        logger.warning(
            "Cannot send DM to user %s — they haven't started the bot", user.id
        )
        await request.decline()
```

- [ ] **Step 4: Verify syntax**

```bash
python -c "from handlers.start import router; from handlers.join import router; print('OK')"
```

Expected: `OK`

- [ ] **Step 5: Commit**

```bash
git add handlers/
git commit -m "feat: start and join request handlers"
```

---

## Task 8: Payment handlers

**Files:**
- Create: `bot/handlers/payment.py`

- [ ] **Step 1: Create `handlers/payment.py`**

```python
import logging
from aiogram import Router, Bot, F
from aiogram.types import CallbackQuery

from config import Config
from database import queries
from services.subscription import create_subscription
from services.payment.base import PaymentProvider

router = Router()
logger = logging.getLogger(__name__)


@router.callback_query(F.data.startswith("plan:"))
async def handle_plan_selection(
    callback: CallbackQuery,
    bot: Bot,
    config: Config,
    payment: PaymentProvider,
) -> None:
    _, plan, channel_id_str = callback.data.split(":")
    channel_id = int(channel_id_str)
    user = callback.from_user
    amount = config.PLAN_1M_PRICE if plan == "1m" else config.PLAN_2M_PRICE
    plan_label = "1 месяц" if plan == "1m" else "2 месяца"

    await callback.message.edit_text(f"⏳ Обрабатываем оплату...")

    pay_rec_id = await queries.create_payment(config.db_path, user.id, amount, plan)
    result = await payment.create_payment(user.id, amount, plan)

    if not result.success:
        await queries.update_payment(config.db_path, pay_rec_id, "failed")
        await callback.message.edit_text(
            f"❌ Ошибка оплаты: {result.error or 'попробуйте позже'}.\n\n"
            f"Напишите /start чтобы попробовать снова."
        )
        return

    await queries.update_payment(config.db_path, pay_rec_id, "success", result.payment_id)
    sub = await create_subscription(config.db_path, user.id, plan, config)

    try:
        await bot.approve_chat_join_request(channel_id, user.id)
    except Exception as e:
        logger.warning("Could not approve join request for %s: %s", user.id, e)

    expires_str = sub["expires_at"].strftime("%d.%m.%Y")
    await callback.message.edit_text(
        f"✅ Оплата прошла успешно!\n\n"
        f"Тариф: {plan_label}\n"
        f"Подписка активна до: {expires_str}\n\n"
        f"Добро пожаловать в канал! 🎉"
    )
```

- [ ] **Step 2: Verify syntax**

```bash
python -c "from handlers.payment import router; print('OK')"
```

Expected: `OK`

- [ ] **Step 3: Commit**

```bash
git add handlers/payment.py
git commit -m "feat: payment callback handler — plan selection and subscription creation"
```

---

## Task 9: Admin handlers

**Files:**
- Create: `bot/handlers/admin.py`

The admin panel uses FSM for multi-step flows (ban a user, add a user manually).

- [ ] **Step 1: Create `handlers/admin.py`**

```python
import logging
from datetime import datetime, timedelta
from aiogram import Router, Bot, F
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import Message, CallbackQuery
from aiogram.utils.keyboard import InlineKeyboardBuilder

from config import Config
from database import queries
from services.subscription import kick_user, create_subscription

router = Router()
logger = logging.getLogger(__name__)


class BanState(StatesGroup):
    waiting_for_user_id = State()


class AddState(StatesGroup):
    waiting_for_user_id = State()
    waiting_for_plan = State()


def _admin_keyboard():
    builder = InlineKeyboardBuilder()
    builder.button(text="📊 Статистика", callback_data="admin:stats")
    builder.button(text="👥 Подписчики", callback_data="admin:subs:0")
    builder.button(text="🚫 Заблокировать", callback_data="admin:ban")
    builder.button(text="➕ Добавить вручную", callback_data="admin:add")
    builder.adjust(2)
    return builder.as_markup()


def _is_admin(user_id: int, config: Config) -> bool:
    return user_id == config.admin_id


@router.message(Command("admin"))
async def cmd_admin(message: Message, config: Config) -> None:
    if not _is_admin(message.from_user.id, config):
        return
    await message.answer("Панель администратора:", reply_markup=_admin_keyboard())


@router.callback_query(F.data == "admin:back")
async def admin_back(callback: CallbackQuery, config: Config) -> None:
    if not _is_admin(callback.from_user.id, config):
        return
    await callback.message.edit_text(
        "Панель администратора:", reply_markup=_admin_keyboard()
    )


@router.callback_query(F.data == "admin:stats")
async def admin_stats(callback: CallbackQuery, config: Config) -> None:
    if not _is_admin(callback.from_user.id, config):
        return
    subs = await queries.get_all_active_subscribers(config.db_path)
    revenue = await queries.get_monthly_revenue(config.db_path)
    expiring = await queries.get_subscriptions_expiring_soon(
        config.db_path, config.REMINDER_DAYS_BEFORE
    )
    builder = InlineKeyboardBuilder()
    builder.button(text="◀️ Назад", callback_data="admin:back")
    await callback.message.edit_text(
        f"📊 Статистика\n\n"
        f"Активных подписчиков: {len(subs)}\n"
        f"Выручка за месяц: {revenue} ₽\n"
        f"Истекает в ближайшие {config.REMINDER_DAYS_BEFORE} дня: {len(expiring)} чел.",
        reply_markup=builder.as_markup(),
    )


@router.callback_query(F.data.startswith("admin:subs:"))
async def admin_subscribers(callback: CallbackQuery, config: Config) -> None:
    if not _is_admin(callback.from_user.id, config):
        return
    page = int(callback.data.split(":")[2])
    per_page = 10
    all_subs = await queries.get_all_active_subscribers(config.db_path)
    total = len(all_subs)
    subs = all_subs[page * per_page: (page + 1) * per_page]

    if not subs:
        await callback.answer("Нет активных подписчиков", show_alert=True)
        return

    lines = [f"👥 Подписчики (стр. {page + 1}/{(total - 1) // per_page + 1}):\n"]
    for sub in subs:
        name = sub["first_name"]
        uname = f" @{sub['username']}" if sub.get("username") else ""
        plan = "1 мес" if sub["plan"] == "1m" else "2 мес"
        exp = sub["expires_at"][:10]
        lines.append(f"• {name}{uname} — {plan}, до {exp}")
    text = "\n".join(lines)

    builder = InlineKeyboardBuilder()
    if page > 0:
        builder.button(text="◀️", callback_data=f"admin:subs:{page - 1}")
    if (page + 1) * per_page < total:
        builder.button(text="▶️", callback_data=f"admin:subs:{page + 1}")
    builder.button(text="◀️ Меню", callback_data="admin:back")
    builder.adjust(2, 1)
    await callback.message.edit_text(text, reply_markup=builder.as_markup())


@router.callback_query(F.data == "admin:ban")
async def admin_ban_start(
    callback: CallbackQuery, config: Config, state: FSMContext
) -> None:
    if not _is_admin(callback.from_user.id, config):
        return
    await state.set_state(BanState.waiting_for_user_id)
    builder = InlineKeyboardBuilder()
    builder.button(text="Отмена", callback_data="admin:cancel")
    await callback.message.edit_text(
        "Введите Telegram ID пользователя для блокировки:",
        reply_markup=builder.as_markup(),
    )


@router.message(BanState.waiting_for_user_id)
async def admin_ban_execute(
    message: Message, bot: Bot, config: Config, state: FSMContext
) -> None:
    if not _is_admin(message.from_user.id, config):
        return
    await state.clear()
    text = message.text.strip()
    if not text.isdigit():
        await message.answer("❌ Неверный формат. Введите числовой Telegram ID.")
        return
    target_id = int(text)
    await queries.upsert_user(config.db_path, target_id, None, "banned_user")
    await queries.ban_user(config.db_path, target_id)
    try:
        await kick_user(bot, config.channel_id, target_id)
    except Exception as e:
        logger.warning("Could not kick %s from channel: %s", target_id, e)
    await message.answer(
        f"✅ Пользователь {target_id} заблокирован и удалён из канала.",
        reply_markup=_admin_keyboard(),
    )


@router.callback_query(F.data == "admin:add")
async def admin_add_start(
    callback: CallbackQuery, config: Config, state: FSMContext
) -> None:
    if not _is_admin(callback.from_user.id, config):
        return
    await state.set_state(AddState.waiting_for_user_id)
    builder = InlineKeyboardBuilder()
    builder.button(text="Отмена", callback_data="admin:cancel")
    await callback.message.edit_text(
        "Введите Telegram ID пользователя которого хотите добавить:",
        reply_markup=builder.as_markup(),
    )


@router.message(AddState.waiting_for_user_id)
async def admin_add_get_id(
    message: Message, config: Config, state: FSMContext
) -> None:
    if not _is_admin(message.from_user.id, config):
        return
    text = message.text.strip()
    if not text.isdigit():
        await message.answer("❌ Неверный формат. Введите числовой Telegram ID.")
        return
    await state.update_data(target_id=int(text))
    await state.set_state(AddState.waiting_for_plan)
    builder = InlineKeyboardBuilder()
    builder.button(text="1 месяц (500 ₽)", callback_data="admin_add_plan:1m")
    builder.button(text="2 месяца (900 ₽)", callback_data="admin_add_plan:2m")
    builder.adjust(1)
    await message.answer("Выберите тариф:", reply_markup=builder.as_markup())


@router.callback_query(F.data.startswith("admin_add_plan:"), AddState.waiting_for_plan)
async def admin_add_execute(
    callback: CallbackQuery, bot: Bot, config: Config, state: FSMContext
) -> None:
    if not _is_admin(callback.from_user.id, config):
        return
    data = await state.get_data()
    await state.clear()
    target_id = data["target_id"]
    plan = callback.data.split(":")[1]

    await queries.upsert_user(config.db_path, target_id, None, str(target_id))
    sub = await create_subscription(config.db_path, target_id, plan, config)

    try:
        invite = await bot.create_chat_invite_link(
            config.channel_id,
            member_limit=1,
            expire_date=datetime.now() + timedelta(hours=24),
        )
        link = invite.invite_link
        status_msg = f"✅ Подписка создана.\nСсылка для пользователя (действует 24ч):\n{link}"
    except Exception as e:
        logger.warning("Could not create invite link: %s", e)
        link = None
        status_msg = "✅ Подписка создана в базе, но не удалось создать ссылку-приглашение. Убедитесь, что бот является администратором канала."

    expires_str = sub["expires_at"].strftime("%d.%m.%Y")
    await callback.message.edit_text(
        f"{status_msg}\n\nID: {target_id}\nТариф: {'1 месяц' if plan == '1m' else '2 месяца'}\nДо: {expires_str}",
        reply_markup=_admin_keyboard(),
    )


@router.callback_query(F.data == "admin:cancel")
async def admin_cancel(
    callback: CallbackQuery, config: Config, state: FSMContext
) -> None:
    if not _is_admin(callback.from_user.id, config):
        return
    await state.clear()
    await callback.message.edit_text(
        "Отменено.", reply_markup=_admin_keyboard()
    )
```

- [ ] **Step 2: Verify syntax**

```bash
python -c "from handlers.admin import router; print('OK')"
```

Expected: `OK`

- [ ] **Step 3: Commit**

```bash
git add handlers/admin.py
git commit -m "feat: admin handlers — stats, subscribers, ban, add manually"
```

---

## Task 10: Main entry point

**Files:**
- Create: `bot/main.py`

- [ ] **Step 1: Create `main.py`**

```python
import asyncio
import logging

from aiogram import Bot, Dispatcher
from aiogram.fsm.storage.memory import MemoryStorage

from config import load_config
from database.db import init_db
from services.payment.stub import StubPaymentProvider
from handlers.start import router as start_router
from handlers.join import router as join_router
from handlers.payment import router as payment_router
from handlers.admin import router as admin_router
from scheduler import create_scheduler

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(name)s %(levelname)s %(message)s",
)
logger = logging.getLogger(__name__)


async def main() -> None:
    config = load_config()
    await init_db(config.db_path)

    bot = Bot(token=config.bot_token)
    dp = Dispatcher(storage=MemoryStorage())

    payment = StubPaymentProvider()

    dp.include_router(start_router)
    dp.include_router(join_router)
    dp.include_router(payment_router)
    dp.include_router(admin_router)

    scheduler = create_scheduler(bot, config, payment)
    scheduler.start()
    logger.info("Scheduler started")

    try:
        logger.info("Bot starting (long polling)")
        await dp.start_polling(bot, config=config, payment=payment)
    finally:
        scheduler.shutdown()
        await bot.session.close()
        logger.info("Bot stopped")


if __name__ == "__main__":
    asyncio.run(main())
```

- [ ] **Step 2: Create `.env` from example**

```bash
cp .env.example .env
# Edit .env: fill in BOT_TOKEN, ADMIN_ID, CHANNEL_ID
```

- [ ] **Step 3: Run the bot locally to verify it starts**

```bash
python main.py
```

Expected output:
```
INFO  Bot starting (long polling)
INFO  Scheduler started
```

No errors in the first 5 seconds. Stop with Ctrl+C.

- [ ] **Step 4: Run all tests**

```bash
python -m pytest tests/ -v
```

Expected: all tests pass (no failures).

- [ ] **Step 5: Commit**

```bash
git add main.py .env.example
git commit -m "feat: main entry point — wires bot, handlers, and scheduler"
```

---

## Task 11: VPS deployment

**Files:**
- Create: `bot/deploy/bot.service`

- [ ] **Step 1: Create `deploy/bot.service`**

```ini
[Unit]
Description=Telegram Subscription Bot
After=network.target

[Service]
Type=simple
User=ubuntu
WorkingDirectory=/home/ubuntu/bot
ExecStart=/home/ubuntu/bot/venv/bin/python main.py
Restart=always
RestartSec=10
EnvironmentFile=/home/ubuntu/bot/.env

[Install]
WantedBy=multi-user.target
```

- [ ] **Step 2: Upload code to VPS**

From local machine (replace `1.2.3.4` with your VPS IP):
```bash
scp -r bot/ ubuntu@1.2.3.4:/home/ubuntu/bot
```

- [ ] **Step 3: On VPS — install Python and dependencies**

SSH into VPS:
```bash
ssh ubuntu@1.2.3.4
```

Then:
```bash
sudo apt update && sudo apt install -y python3.11 python3.11-venv python3-pip
cd /home/ubuntu/bot
python3.11 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

- [ ] **Step 4: Create `.env` on VPS**

```bash
nano /home/ubuntu/bot/.env
```

Paste the contents from `.env.example` and fill in real values.

- [ ] **Step 5: Install and start systemd service**

```bash
sudo cp /home/ubuntu/bot/deploy/bot.service /etc/systemd/system/bot.service
sudo systemctl daemon-reload
sudo systemctl enable bot
sudo systemctl start bot
```

- [ ] **Step 6: Verify the service is running**

```bash
sudo systemctl status bot
```

Expected: `Active: active (running)`

```bash
sudo journalctl -u bot -f
```

Expected: log lines showing bot started and polling.

- [ ] **Step 7: Setup Telegram channel**

1. Open your channel settings in Telegram
2. Add the bot as administrator → give it "Add members" permission
3. In channel settings → "Subscribers" → enable "Join requests"
4. Test: open the channel link in a different account → click "Request to join" → the bot should DM you with payment options

- [ ] **Step 8: Final commit**

```bash
git add deploy/
git commit -m "feat: systemd deploy config and VPS setup instructions"
```

---

## Running all tests

```bash
cd bot
source venv/bin/activate
python -m pytest tests/ -v --tb=short
```

Expected: all tests pass.

---

## What to do when ЮKassa is ready

1. Install SDK: `pip install yookassa` → add to `requirements.txt`
2. Create `services/payment/yookassa.py` implementing `PaymentProvider`
3. In `main.py`: replace `StubPaymentProvider()` with `YooKassaPaymentProvider(shop_id, secret_key)`
4. Add `YOOKASSA_SHOP_ID` and `YOOKASSA_SECRET_KEY` to `.env`

Nothing else changes — the abstraction handles it.
