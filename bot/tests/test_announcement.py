import pytest
from datetime import datetime, timedelta
from unittest.mock import AsyncMock, MagicMock
from config import Config
from database.db import init_db
from database import queries
from services.announcement import (
    announcement_recipients,
    announcement_text,
    new_methods_line,
    send_announcement,
)
from handlers.admin import admin_announce_preview, admin_announce_send

ADMIN = 1


@pytest.fixture
async def config(tmp_path):
    path = str(tmp_path / "test.db")
    await init_db(path)
    return Config(
        bot_token="t", admin_ids=frozenset({ADMIN}), channel_id=-100, db_path=path,
        mbank_card="4177", mbank_recipient="X",
        getcourse_link_first="https://gc.example/first",
    )


async def _users(config):
    """5 never paid, 6 lapsed, 7 active, 8 banned, 1 admin."""
    for uid in (1, 5, 6, 7, 8):
        await queries.upsert_user(config.db_path, uid, None, f"U{uid}")
    old = await queries.create_subscription(
        config.db_path, 6, "1m", datetime.utcnow() - timedelta(days=40)
    )
    await queries.expire_subscription(config.db_path, old)
    await queries.create_subscription(
        config.db_path, 7, "1m", datetime.utcnow() + timedelta(days=10)
    )
    await queries.ban_user(config.db_path, 8)


def _callback(data, user_id=ADMIN):
    cb = MagicMock()
    cb.data = data
    cb.from_user = MagicMock(id=user_id, first_name="Admin")
    cb.answer = AsyncMock()
    cb.message = MagicMock()
    cb.message.edit_text = AsyncMock()
    return cb


def test_text_names_configured_methods(config):
    text = announcement_text(config)
    assert "МБанк" in text and "GetCourse" in text
    assert "1 000 ₽" in text and "500 ₽" in text
    assert "Ириной Астафьевой" in text and "CEU" in text and "арт-зоны" in text


def test_new_methods_line_skips_unconfigured(config):
    config.getcourse_link_first = ""
    line = new_methods_line(config)
    assert "МБанк" in line and "GetCourse" not in line
    config.mbank_card = ""
    assert new_methods_line(config) == ""


@pytest.mark.asyncio
async def test_recipients_are_people_without_subscription(config):
    await _users(config)
    assert sorted(await announcement_recipients(config)) == [5, 6]


@pytest.mark.asyncio
async def test_send_reaches_each_person_once(config):
    await _users(config)
    bot = AsyncMock()
    assert await send_announcement(bot, config) == (2, 0)
    assert sorted(c.args[0] for c in bot.send_message.call_args_list) == [5, 6]
    markup = bot.send_message.call_args.kwargs["reply_markup"]
    assert "manual:mbank" in [b.callback_data for row in markup.inline_keyboard for b in row]
    bot.send_message.reset_mock()
    assert await send_announcement(bot, config) == (0, 0)
    bot.send_message.assert_not_called()


@pytest.mark.asyncio
async def test_blocked_bot_counted_and_not_retried(config):
    await _users(config)
    bot = AsyncMock()
    bot.send_message.side_effect = [Exception("blocked"), None]
    sent, failed = await send_announcement(bot, config)
    assert (sent, failed) == (1, 1)
    bot.send_message.reset_mock(side_effect=True)
    assert await send_announcement(bot, config) == (0, 0)


@pytest.mark.asyncio
async def test_admin_preview_shows_count_and_needs_confirmation(config):
    await _users(config)
    cb = _callback("admin:announce")
    bot = AsyncMock()
    await admin_announce_preview(cb, config)
    text = cb.message.edit_text.call_args.args[0]
    assert "Получателей: 2" in text and "МБанк" in text
    bot.send_message.assert_not_called()


@pytest.mark.asyncio
async def test_admin_send_reports_result(config):
    await _users(config)
    cb = _callback("admin:announce_go")
    bot = AsyncMock()
    await admin_announce_send(cb, bot, config)
    assert "Отправлено: 2" in cb.message.edit_text.call_args.args[0]


@pytest.mark.asyncio
async def test_non_admin_cannot_send(config):
    await _users(config)
    bot = AsyncMock()
    await admin_announce_send(_callback("admin:announce_go", user_id=5), bot, config)
    bot.send_message.assert_not_called()
