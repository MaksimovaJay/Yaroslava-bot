import aiosqlite
import pytest
from datetime import datetime, timedelta
from unittest.mock import AsyncMock, MagicMock
from database.db import init_db
from database import queries
from scheduler import (
    send_expiry_reminders,
    process_expired_subscriptions,
    process_grace_period_ended,
)


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
    expires = datetime.utcnow() + timedelta(days=2)
    await queries.create_subscription(db, 100, "1m", expires)
    bot = AsyncMock()
    await send_expiry_reminders(bot, config)
    bot.send_message.assert_called_once()
    call_args = bot.send_message.call_args
    assert call_args[0][0] == 100


@pytest.mark.asyncio
async def test_no_reminder_for_non_expiring_subscription(db, config):
    expires = datetime.utcnow() + timedelta(days=10)
    await queries.create_subscription(db, 100, "1m", expires)
    bot = AsyncMock()
    await send_expiry_reminders(bot, config)
    bot.send_message.assert_not_called()


@pytest.mark.asyncio
async def test_successful_charge_extends_subscription(db, config):
    expires = datetime.utcnow() - timedelta(hours=1)
    await queries.create_subscription(db, 100, "1m", expires)
    bot = AsyncMock()
    payment = AsyncMock()
    payment.charge_saved.return_value = MagicMock(success=True, payment_id="p1")
    await process_expired_subscriptions(bot, config, payment)
    sub = await queries.get_active_subscription(db, 100)
    assert sub is not None
    new_expires = datetime.fromisoformat(sub["expires_at"])
    assert new_expires > datetime.utcnow() + timedelta(days=28)


@pytest.mark.asyncio
async def test_failed_charge_starts_grace_period(db, config):
    expires = datetime.utcnow() - timedelta(hours=1)
    await queries.create_subscription(db, 100, "1m", expires)
    bot = AsyncMock()
    payment = AsyncMock()
    payment.charge_saved.return_value = MagicMock(success=False, error="no token")
    await process_expired_subscriptions(bot, config, payment)
    async with aiosqlite.connect(db) as conn:
        async with conn.execute(
            "SELECT in_grace FROM subscriptions WHERE user_id = 100"
        ) as cur:
            row = await cur.fetchone()
    assert row[0] == 1


@pytest.mark.asyncio
async def test_grace_period_ended_kicks_user(db, config):
    expires = datetime.utcnow() - timedelta(days=4)
    sub_id = await queries.create_subscription(db, 100, "1m", expires)
    grace_end = datetime.utcnow() - timedelta(hours=1)
    await queries.start_grace_period(db, sub_id, grace_end)
    bot = AsyncMock()
    await process_grace_period_ended(bot, config)
    bot.ban_chat_member.assert_called_once_with(-100, 100)
    bot.unban_chat_member.assert_called_once_with(-100, 100)
    sub = await queries.get_active_subscription(db, 100)
    assert sub is None


@pytest.mark.asyncio
async def test_grace_period_ended_does_not_kick_if_paid_again(db, config):
    old_id = await queries.create_subscription(
        db, 100, "1m", datetime.utcnow() - timedelta(days=4)
    )
    await queries.start_grace_period(db, old_id, datetime.utcnow() - timedelta(hours=1))
    await queries.create_subscription(db, 100, "1m", datetime.utcnow() + timedelta(days=30))
    bot = AsyncMock()
    await process_grace_period_ended(bot, config)
    bot.ban_chat_member.assert_not_called()
    assert await queries.get_active_subscription(db, 100) is not None


@pytest.mark.asyncio
async def test_failed_charge_offers_plan_buttons(db, config):
    await queries.create_subscription(db, 100, "1m", datetime.utcnow() - timedelta(hours=1))
    bot = AsyncMock()
    payment = AsyncMock()
    payment.charge_saved.return_value = MagicMock(success=False, error="no token")
    await process_expired_subscriptions(bot, config, payment)
    markup = bot.send_message.call_args.kwargs["reply_markup"]
    callbacks = [b.callback_data for row in markup.inline_keyboard for b in row]
    assert callbacks == ["plan:1m:-100", "plan:2m:-100"]
