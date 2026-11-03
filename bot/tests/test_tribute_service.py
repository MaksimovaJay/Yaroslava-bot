import hashlib
import hmac
import pytest
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock
from config import Config
from database.db import init_db
from database import queries
from services.tribute import verify_signature, parse_dt, handle_event


@pytest.fixture
async def config(tmp_path):
    path = str(tmp_path / "test.db")
    await init_db(path)
    return Config(bot_token="t", admin_ids=frozenset({1}), channel_id=-100, db_path=path)


def _event(name="new_subscription", created_at="2026-11-03T10:00:00Z", user_id=55, days=30):
    expires = datetime.now(timezone.utc) + timedelta(days=days)
    return {
        "name": name,
        "created_at": created_at,
        "sent_at": created_at,
        "payload": {
            "subscription_name": "Журнал Психоголика",
            "subscription_id": 1,
            "period_id": 2,
            "period": "monthly",
            "price": 100000,
            "amount": 100000,
            "currency": "rub",
            "user_id": 9,
            "trb_user_id": "T-9",
            "telegram_user_id": user_id,
            "telegram_username": "reader",
            "channel_id": 3,
            "channel_name": "Журнал",
            "expires_at": expires.isoformat().replace("+00:00", "Z"),
            "type": "regular",
        },
    }


def test_verify_signature_accepts_valid():
    body = '{"a":"я"}'.encode()
    sig = hmac.new(b"k", body, hashlib.sha256).hexdigest()
    assert verify_signature(body, sig, "k") is True
    assert verify_signature(body + b" ", sig, "k") is False
    assert verify_signature(body, None, "k") is False
    assert verify_signature(body, sig, "") is False


def test_parse_dt_normalizes_timezone():
    assert parse_dt("2026-12-03T10:00:00Z") == datetime(2026, 12, 3, 10, 0)
    assert parse_dt("2026-12-03T13:00:00+03:00") == datetime(2026, 12, 3, 10, 0)


@pytest.mark.asyncio
async def test_new_subscription_creates_sub_and_welcomes(config):
    bot = AsyncMock()
    await handle_event(_event(), bot, config)
    assert await queries.get_active_tribute_subscription(config.db_path, 55) is not None
    bot.send_message.assert_called_once()
    assert bot.send_message.call_args.args[0] == 55


@pytest.mark.asyncio
async def test_duplicate_event_is_ignored(config):
    bot = AsyncMock()
    await handle_event(_event(), bot, config)
    await handle_event(_event(), bot, config)
    assert bot.send_message.call_count == 1
    assert await queries.get_monthly_revenue(config.db_path) == 1000


@pytest.mark.asyncio
async def test_cancelled_marks_cancelled_keeps_access(config):
    bot = AsyncMock()
    await handle_event(_event(), bot, config)
    await handle_event(
        _event("cancelled_subscription", created_at="2026-11-04T10:00:00Z"), bot, config
    )
    sub = await queries.get_active_tribute_subscription(config.db_path, 55)
    assert sub["status"] == "cancelled"


@pytest.mark.asyncio
async def test_welcome_failure_does_not_raise(config):
    bot = AsyncMock()
    bot.send_message.side_effect = Exception("blocked")
    await handle_event(_event(), bot, config)
    assert await queries.get_active_tribute_subscription(config.db_path, 55) is not None


@pytest.mark.asyncio
async def test_unrelated_event_is_ignored(config):
    bot = AsyncMock()
    event = _event("newDonation")
    await handle_event(event, bot, config)
    assert await queries.get_user(config.db_path, 55) is None


@pytest.mark.asyncio
async def test_retry_after_failed_write_still_applies(config, monkeypatch):
    bot = AsyncMock()
    real_upsert = queries.upsert_tribute_subscription
    failing = AsyncMock(side_effect=Exception("db locked"))
    monkeypatch.setattr(queries, "upsert_tribute_subscription", failing)
    with pytest.raises(Exception):
        await handle_event(_event(), bot, config)
    monkeypatch.setattr(queries, "upsert_tribute_subscription", real_upsert)
    await handle_event(_event(), bot, config)
    assert await queries.get_active_tribute_subscription(config.db_path, 55) is not None
    bot.send_message.assert_called_once()
