import pytest
from datetime import datetime, timedelta
from unittest.mock import AsyncMock, MagicMock
from database.db import init_db
from database import queries
from config import Config
from handlers.payment import cmd_pay


@pytest.fixture
async def config(tmp_path):
    path = str(tmp_path / "test.db")
    await init_db(path)
    return Config(bot_token="t", admin_ids=frozenset({1}), channel_id=-100, db_path=path)


def _message(user_id=5):
    msg = MagicMock()
    msg.from_user = MagicMock(id=user_id, username="u", first_name="U")
    msg.answer = AsyncMock()
    return msg


@pytest.mark.asyncio
async def test_pay_shows_plan_buttons(config):
    msg = _message()
    await cmd_pay(msg, config)
    markup = msg.answer.call_args.kwargs["reply_markup"]
    callbacks = [b.callback_data for row in markup.inline_keyboard for b in row]
    assert callbacks == ["plan:1m:-100", "plan:2m:-100"]


@pytest.mark.asyncio
async def test_pay_mentions_current_expiry(config):
    await queries.upsert_user(config.db_path, 5, "u", "U")
    await queries.create_subscription(
        config.db_path, 5, "1m", datetime.utcnow() + timedelta(days=10)
    )
    msg = _message()
    await cmd_pay(msg, config)
    assert "добавится к текущему" in msg.answer.call_args.args[0]


@pytest.mark.asyncio
async def test_pay_refuses_banned_user(config):
    await queries.upsert_user(config.db_path, 5, "u", "U")
    await queries.ban_user(config.db_path, 5)
    msg = _message()
    await cmd_pay(msg, config)
    assert "reply_markup" not in msg.answer.call_args.kwargs
