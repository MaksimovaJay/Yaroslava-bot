import pytest
from datetime import datetime, timedelta
from database.db import init_db
from database import queries
from services.subscription import create_subscription, renew_subscription
from config import Config


@pytest.fixture
async def db(tmp_path):
    path = str(tmp_path / "test.db")
    await init_db(path)
    await queries.upsert_user(path, 1, None, "TestUser")
    return path


@pytest.fixture
def config(db):
    return Config(
        bot_token="test_token",
        admin_ids=frozenset({1}),
        channel_id=-100,
        db_path=db,
    )


@pytest.mark.asyncio
async def test_create_1m_subscription_expiry(db, config):
    sub = await create_subscription(db, 1, "1m", config)
    diff = (sub["expires_at"] - datetime.utcnow()).days
    assert 29 <= diff <= 30


@pytest.mark.asyncio
async def test_create_2m_subscription_expiry(db, config):
    await queries.upsert_user(db, 2, None, "User2")
    sub = await create_subscription(db, 2, "2m", config)
    diff = (sub["expires_at"] - datetime.utcnow()).days
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
    past = datetime.utcnow() - timedelta(days=5)
    sub_id = await queries.create_subscription(db, 1, "1m", past)
    db_sub = {"id": sub_id, "plan": "1m", "expires_at": past.isoformat()}
    new_expires = await renew_subscription(db, db_sub, config)
    diff = (new_expires - datetime.utcnow()).days
    assert 29 <= diff <= 30


@pytest.mark.asyncio
async def test_create_subscription_with_custom_days(db, config):
    sub = await create_subscription(db, 1, "1m", config, days=14)
    diff = (sub["expires_at"] - datetime.utcnow()).days
    assert 13 <= diff <= 14


def test_days_label():
    from services.subscription import days_label
    assert days_label(14) == "2 недели"
    assert days_label(60) == "2 месяца"
    assert days_label(30) == "1 месяц"


@pytest.mark.asyncio
async def test_paying_early_adds_to_current_subscription(db, config):
    first = await create_subscription(db, 1, "1m", config)
    second = await create_subscription(db, 1, "1m", config)
    diff = (second["expires_at"] - first["expires_at"]).days
    assert 29 <= diff <= 30
