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


@pytest.mark.asyncio
async def test_extend_subscription(db):
    await queries.upsert_user(db, 9, None, "Ivan")
    expires = datetime.now() + timedelta(days=30)
    await queries.create_subscription(db, 9, "1m", expires)
    sub = await queries.get_active_subscription(db, 9)
    new_expires = datetime.now() + timedelta(days=60)
    await queries.extend_subscription(db, sub["id"], new_expires)
    sub_after = await queries.get_active_subscription(db, 9)
    assert sub_after is not None
    assert sub_after["in_grace"] == 0
