import aiosqlite
import pytest
from datetime import datetime, timedelta
from config import Config
from database.db import init_db
from database import queries


@pytest.fixture
async def db(tmp_path):
    path = str(tmp_path / "test.db")
    await init_db(path)
    return path


async def _tribute_sub(db, user_id, status, expires_at, event_at):
    await queries.ensure_user(db, user_id, None, str(user_id))
    await queries.upsert_tribute_subscription(
        db, user_id, 1, 2, status, expires_at, event_at
    )


@pytest.mark.asyncio
async def test_ensure_user_creates_and_keeps_name(db):
    await queries.ensure_user(db, 7, None, "id7")
    assert (await queries.get_user(db, 7))["first_name"] == "id7"
    await queries.upsert_user(db, 7, "a", "Аня")
    await queries.ensure_user(db, 7, "b", "id7")
    user = await queries.get_user(db, 7)
    assert user["first_name"] == "Аня"
    assert user["username"] == "b"


@pytest.mark.asyncio
async def test_record_event_is_idempotent(db):
    await queries.ensure_user(db, 7, None, "id7")
    args = ("new_subscription", 7, "2026-11-03T10:00:00Z", 100000, "rub")
    assert await queries.record_tribute_event(db, *args) is True
    assert await queries.record_tribute_event(db, *args) is False


@pytest.mark.asyncio
async def test_upsert_ignores_older_event(db):
    t1 = datetime(2026, 11, 3, 10, 0)
    t2 = t1 + timedelta(hours=1)
    expires = datetime.utcnow() + timedelta(days=20)
    await _tribute_sub(db, 7, "cancelled", expires, t2)
    await _tribute_sub(db, 7, "active", expires, t1)
    sub = await queries.get_active_tribute_subscription(db, 7)
    assert sub["status"] == "cancelled"


@pytest.mark.asyncio
async def test_cancelled_still_active_until_expiry(db):
    now = datetime.utcnow()
    await _tribute_sub(db, 7, "cancelled", now + timedelta(days=5), now)
    assert await queries.get_active_tribute_subscription(db, 7) is not None
    await _tribute_sub(db, 7, "cancelled", now - timedelta(hours=1), now + timedelta(minutes=1))
    assert await queries.get_active_tribute_subscription(db, 7) is None


@pytest.mark.asyncio
async def test_active_tribute_subscribers_listed_with_names(db):
    now = datetime.utcnow()
    await _tribute_sub(db, 7, "active", now + timedelta(days=5), now)
    subs = await queries.get_all_active_tribute_subscribers(db)
    assert [s["user_id"] for s in subs] == [7]
    assert subs[0]["first_name"] == "7"


@pytest.mark.asyncio
async def test_monthly_revenue_includes_tribute(db):
    await queries.ensure_user(db, 7, None, "id7")
    pay_id = await queries.create_payment(db, 7, 500, "1m")
    await queries.update_payment(db, pay_id, "success", "ext")
    await queries.record_tribute_event(
        db, "renewed_subscription", 7, "2026-11-03T10:00:00Z", 50000, "rub"
    )
    await queries.record_tribute_event(
        db, "cancelled_subscription", 7, "2026-11-03T11:00:00Z", 50000, "rub"
    )
    assert await queries.get_monthly_revenue(db) == 1000


def test_tribute_needs_key_too():
    base = dict(bot_token="t", admin_ids=frozenset({1}), channel_id=-100, db_path="x")
    link = "https://t.me/tribute/app?startapp=x"
    assert Config(**base, tribute_subscribe_link=link).tribute_enabled is False
    assert Config(
        **base, tribute_subscribe_link=link, tribute_api_key="k"
    ).tribute_enabled is True
