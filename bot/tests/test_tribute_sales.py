import pytest
from datetime import datetime, timedelta
from unittest.mock import AsyncMock, MagicMock
from config import Config
from database.db import init_db
from database import queries
from handlers.payment import cmd_pay, handle_plan_selection
from handlers.join import handle_join_request
from handlers.start import cmd_start

LINK = "https://t.me/tribute/app?startapp=abc"


@pytest.fixture
async def config(tmp_path):
    path = str(tmp_path / "test.db")
    await init_db(path)
    return Config(
        bot_token="t", admin_ids=frozenset({1}), channel_id=-100,
        db_path=path, tribute_subscribe_link=LINK, tribute_api_key="k",
    )


def _message(user_id=5):
    msg = MagicMock()
    msg.from_user = MagicMock(id=user_id, username="u", first_name="U")
    msg.answer = AsyncMock()
    return msg


def _urls(markup):
    return [b.url for row in markup.inline_keyboard for b in row]


async def _tribute_sub(config, user_id=5):
    now = datetime.utcnow()
    await queries.ensure_user(config.db_path, user_id, None, str(user_id))
    await queries.upsert_tribute_subscription(
        config.db_path, user_id, 1, 2, "active", now + timedelta(days=10), now
    )


def _join_request(user_id=5):
    req = MagicMock()
    req.from_user = MagicMock(id=user_id, username="u", first_name="U")
    req.chat = MagicMock(id=-100)
    req.approve = AsyncMock()
    req.decline = AsyncMock()
    return req


@pytest.mark.asyncio
async def test_pay_shows_tribute_button_when_enabled(config):
    msg = _message()
    await cmd_pay(msg, config)
    assert _urls(msg.answer.call_args.kwargs["reply_markup"]) == [LINK]


@pytest.mark.asyncio
async def test_pay_with_active_tribute_has_no_buttons(config):
    await _tribute_sub(config)
    msg = _message()
    await cmd_pay(msg, config)
    assert "reply_markup" not in msg.answer.call_args.kwargs
    assert "@tribute" in msg.answer.call_args.args[0]


@pytest.mark.asyncio
async def test_plan_callback_redirects_to_tribute(config):
    callback = MagicMock()
    callback.data = "plan:1m:-100"
    callback.from_user = MagicMock(id=5)
    callback.answer = AsyncMock()
    callback.message.edit_text = AsyncMock()
    payment = AsyncMock()
    await handle_plan_selection(callback, AsyncMock(), config, payment)
    payment.create_payment.assert_not_called()
    assert _urls(callback.message.edit_text.call_args.kwargs["reply_markup"]) == [LINK]


@pytest.mark.asyncio
async def test_join_ignores_unknown_user_when_tribute_enabled(config):
    bot = AsyncMock()
    req = _join_request()
    await handle_join_request(req, bot, config)
    req.approve.assert_not_called()
    req.decline.assert_not_called()
    bot.send_message.assert_not_called()


@pytest.mark.asyncio
async def test_join_approves_legacy_subscriber(config):
    await queries.upsert_user(config.db_path, 5, "u", "U")
    await queries.create_subscription(
        config.db_path, 5, "1m", datetime.utcnow() + timedelta(days=5)
    )
    req = _join_request()
    await handle_join_request(req, AsyncMock(), config)
    req.approve.assert_called_once()


@pytest.mark.asyncio
async def test_join_leaves_tribute_subscriber_to_tribute(config):
    config.tribute_subscribe_link = ""
    await _tribute_sub(config)
    bot = AsyncMock()
    req = _join_request()
    await handle_join_request(req, bot, config)
    req.approve.assert_not_called()
    req.decline.assert_not_called()
    bot.send_message.assert_not_called()


@pytest.mark.asyncio
async def test_join_never_declines_on_dm_failure(config):
    config.tribute_subscribe_link = ""
    bot = AsyncMock()
    bot.send_message.side_effect = Exception("can't initiate conversation")
    req = _join_request()
    await handle_join_request(req, bot, config)
    req.decline.assert_not_called()


@pytest.mark.asyncio
async def test_start_shows_tribute_button_when_enabled(config):
    msg = _message()
    await cmd_start(msg, AsyncMock(), config, None)
    assert _urls(msg.answer.call_args.kwargs["reply_markup"]) == [LINK]


@pytest.mark.asyncio
async def test_start_shows_tribute_expiry(config):
    await _tribute_sub(config)
    msg = _message()
    await cmd_start(msg, AsyncMock(), config, None)
    assert "@tribute" in msg.answer.call_args.args[0]


@pytest.mark.asyncio
async def test_pay_tells_legacy_subscriber_to_wait(config):
    config.tribute_api_key = "k"
    await queries.upsert_user(config.db_path, 5, "u", "U")
    expires = datetime.utcnow() + timedelta(days=40)
    await queries.create_subscription(config.db_path, 5, "1m", expires)
    msg = _message()
    await cmd_pay(msg, config)
    text = msg.answer.call_args.args[0]
    assert expires.strftime("%d.%m.%Y") in text
    assert "reply_markup" not in msg.answer.call_args.kwargs


@pytest.mark.asyncio
async def test_start_legacy_does_not_offer_early_renewal_with_tribute(config):
    config.tribute_api_key = "k"
    await queries.upsert_user(config.db_path, 5, "u", "U")
    await queries.create_subscription(
        config.db_path, 5, "1m", datetime.utcnow() + timedelta(days=40)
    )
    msg = _message()
    await cmd_start(msg, AsyncMock(), config, None)
    assert "/pay" not in msg.answer.call_args.args[0]
