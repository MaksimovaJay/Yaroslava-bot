import pytest
from datetime import datetime, timedelta
from unittest.mock import AsyncMock, MagicMock
from config import Config
from database.db import init_db
from database import queries
from handlers.admin import admin_ban_execute, admin_stats, admin_subscribers


@pytest.fixture
async def config(tmp_path):
    path = str(tmp_path / "test.db")
    await init_db(path)
    return Config(bot_token="t", admin_ids=frozenset({1}), channel_id=-100, db_path=path)


async def _tribute_sub(config, user_id=55, status="active"):
    now = datetime.utcnow()
    await queries.ensure_user(config.db_path, user_id, "reader", "Читатель")
    await queries.upsert_tribute_subscription(
        config.db_path, user_id, 1, 2, status, now + timedelta(days=10), now
    )


def _callback(data):
    cb = MagicMock()
    cb.data = data
    cb.from_user = MagicMock(id=1)
    cb.answer = AsyncMock()
    cb.message.edit_text = AsyncMock()
    return cb


@pytest.mark.asyncio
async def test_ban_warns_about_tribute_subscription(config):
    await _tribute_sub(config)
    msg = MagicMock()
    msg.from_user = MagicMock(id=1)
    msg.text = "55"
    msg.answer = AsyncMock()
    await admin_ban_execute(msg, AsyncMock(), config, AsyncMock())
    assert await queries.is_user_banned(config.db_path, 55)
    assert "Tribute" in msg.answer.call_args.args[0]


@pytest.mark.asyncio
async def test_stats_counts_tribute(config):
    await _tribute_sub(config)
    await queries.upsert_user(config.db_path, 7, None, "Old")
    await queries.create_subscription(
        config.db_path, 7, "1m", datetime.utcnow() + timedelta(days=5)
    )
    cb = _callback("admin:stats")
    await admin_stats(cb, config)
    text = cb.message.edit_text.call_args.args[0]
    assert "Активных подписчиков: 2" in text
    assert "Tribute: 1" in text


@pytest.mark.asyncio
async def test_subscribers_list_marks_tribute(config):
    await _tribute_sub(config, status="cancelled")
    cb = _callback("admin:subs:0")
    await admin_subscribers(cb, config)
    text = cb.message.edit_text.call_args.args[0]
    assert "Читатель @reader — Tribute, отменена" in text
