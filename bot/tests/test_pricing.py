import pytest
from datetime import datetime, timedelta
from config import Config
from database.db import init_db
from database import queries
from services.pricing import price_for


@pytest.fixture
async def config(tmp_path):
    path = str(tmp_path / "test.db")
    await init_db(path)
    await queries.upsert_user(path, 5, "u", "U")
    return Config(bot_token="t", admin_ids=frozenset({1}), channel_id=-100, db_path=path)


@pytest.mark.asyncio
async def test_new_user_pays_first_month_price(config):
    assert await price_for(config.db_path, 5, config) == 1000


@pytest.mark.asyncio
async def test_active_subscriber_pays_renewal_price(config):
    await queries.create_subscription(
        config.db_path, 5, "1m", datetime.utcnow() + timedelta(days=10)
    )
    assert await price_for(config.db_path, 5, config) == 500


@pytest.mark.asyncio
async def test_grace_period_still_counts_as_renewal(config):
    sub_id = await queries.create_subscription(
        config.db_path, 5, "1m", datetime.utcnow() - timedelta(days=1)
    )
    await queries.start_grace_period(
        config.db_path, sub_id, datetime.utcnow() + timedelta(days=2)
    )
    assert await price_for(config.db_path, 5, config) == 500


@pytest.mark.asyncio
async def test_lapsed_subscriber_pays_first_month_again(config):
    sub_id = await queries.create_subscription(
        config.db_path, 5, "1m", datetime.utcnow() - timedelta(days=10)
    )
    await queries.expire_subscription(config.db_path, sub_id)
    assert await price_for(config.db_path, 5, config) == 1000
