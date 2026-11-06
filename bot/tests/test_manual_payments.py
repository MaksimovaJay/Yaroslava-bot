import pytest
from datetime import datetime, timedelta
from unittest.mock import AsyncMock, MagicMock
from config import Config
from database.db import init_db
from database import queries
from handlers.manual_payment import (
    choose_manual_method,
    receive_screenshot,
    review_payment,
    receive_payer_info,
)

CARD = "4177 4901 6679 6831"
REVIEWER = 1


@pytest.fixture
async def config(tmp_path):
    path = str(tmp_path / "test.db")
    await init_db(path)
    return Config(
        bot_token="t", admin_ids=frozenset({REVIEWER}), channel_id=-100, db_path=path,
        invite_link="https://t.me/+group",
        mbank_card=CARD, mbank_recipient="MESHERIAKOV ARSENII",
        getcourse_link_first="https://gc.example/first",
        getcourse_link_renewal="https://gc.example/renew",
    )


def _user(user_id=5):
    return MagicMock(id=user_id, username="u", first_name="U")


def _callback(data, user_id=5):
    cb = MagicMock()
    cb.data = data
    cb.from_user = _user(user_id)
    cb.answer = AsyncMock()
    cb.message = MagicMock()
    cb.message.edit_text = AsyncMock()
    cb.message.edit_caption = AsyncMock()
    cb.message.caption = "Оплата"
    return cb


def _photo_message(user_id=5, caption="Иванова Анна Сергеевна"):
    msg = MagicMock()
    msg.from_user = _user(user_id)
    msg.photo = [MagicMock(file_id="small"), MagicMock(file_id="big")]
    msg.document = None
    msg.caption = caption
    msg.answer = AsyncMock()
    return msg


def _text_message(text, user_id=5):
    msg = MagicMock()
    msg.from_user = _user(user_id)
    msg.text = text
    msg.answer = AsyncMock()
    return msg


async def _choose(config, method="mbank", user_id=5):
    cb = _callback(f"manual:{method}", user_id)
    await choose_manual_method(cb, config)
    return cb


async def _submit(config, bot, user_id=5):
    await _choose(config, user_id=user_id)
    await receive_screenshot(_photo_message(user_id), bot, config)
    return bot.send_photo.call_args.kwargs["reply_markup"]


def _callbacks(markup):
    return [b.callback_data for row in markup.inline_keyboard for b in row]


@pytest.mark.asyncio
async def test_mbank_shows_card_and_first_month_price(config):
    cb = await _choose(config)
    text = cb.message.edit_text.call_args.args[0]
    assert CARD in text and "MESHERIAKOV ARSENII" in text
    assert "1 000 ₽" in text
    assert "скриншот" in text


@pytest.mark.asyncio
async def test_getcourse_uses_renewal_link_for_subscriber(config):
    await queries.upsert_user(config.db_path, 5, "u", "U")
    await queries.create_subscription(
        config.db_path, 5, "1m", datetime.utcnow() + timedelta(days=5)
    )
    cb = await _choose(config, "getcourse")
    text = cb.message.edit_text.call_args.args[0]
    assert "https://gc.example/renew" in text and "500 ₽" in text


@pytest.mark.asyncio
async def test_screenshot_goes_to_reviewers_with_buttons(config):
    bot = AsyncMock()
    markup = await _submit(config, bot)
    assert bot.send_photo.call_args.args[0] == REVIEWER
    assert bot.send_photo.call_args.kwargs["photo"] == "big"
    assert "1 000 ₽" in bot.send_photo.call_args.kwargs["caption"]
    assert [c.split(":")[1] for c in _callbacks(markup)] == ["ok", "no"]


@pytest.mark.asyncio
async def test_screenshot_as_file_is_accepted(config):
    bot = AsyncMock()
    await _choose(config)
    msg = _photo_message()
    msg.photo = None
    msg.document = MagicMock(file_id="doc1")
    await receive_screenshot(msg, bot, config)
    assert bot.send_document.call_args.kwargs["document"] == "doc1"


@pytest.mark.asyncio
async def test_screenshot_without_chosen_method_hints_pay(config):
    bot = AsyncMock()
    msg = _photo_message()
    await receive_screenshot(msg, bot, config)
    bot.send_photo.assert_not_called()
    assert "/pay" in msg.answer.call_args.args[0]


@pytest.mark.asyncio
async def test_approve_grants_month_and_welcomes_user(config):
    bot = AsyncMock()
    markup = await _submit(config, bot)
    ok = _callbacks(markup)[0]
    await review_payment(_callback(ok, REVIEWER), bot, config)
    sub = await queries.get_active_subscription(config.db_path, 5)
    expires = datetime.fromisoformat(sub["expires_at"])
    assert timedelta(days=29) < expires - datetime.utcnow() <= timedelta(days=30)
    assert await queries.get_monthly_revenue(config.db_path) == 1000
    user_msg = bot.send_message.call_args.args
    assert user_msg[0] == 5 and "подтверждена" in user_msg[1]
    assert config.invite_link in user_msg[1]


@pytest.mark.asyncio
async def test_second_approve_does_nothing(config):
    bot = AsyncMock()
    markup = await _submit(config, bot)
    ok = _callbacks(markup)[0]
    await review_payment(_callback(ok, REVIEWER), bot, config)
    await review_payment(_callback(ok, REVIEWER), bot, config)
    subs = await queries.get_all_active_subscribers(config.db_path)
    assert len(subs) == 1
    assert await queries.get_monthly_revenue(config.db_path) == 1000


@pytest.mark.asyncio
async def test_reject_tells_user_and_offers_support(config):
    bot = AsyncMock()
    markup = await _submit(config, bot)
    no = _callbacks(markup)[1]
    await review_payment(_callback(no, REVIEWER), bot, config)
    assert await queries.get_active_subscription(config.db_path, 5) is None
    kwargs = bot.send_message.call_args.kwargs
    urls = [b.url for row in kwargs["reply_markup"].inline_keyboard for b in row]
    assert all("t.me/psihogolik_help" in u for u in urls)


@pytest.mark.asyncio
async def test_non_reviewer_cannot_approve(config):
    bot = AsyncMock()
    markup = await _submit(config, bot)
    ok = _callbacks(markup)[0]
    await review_payment(_callback(ok, 999), bot, config)
    assert await queries.get_active_subscription(config.db_path, 5) is None


@pytest.mark.asyncio
async def test_price_is_fixed_when_method_chosen(config):
    # Shown 1 000 ₽; a subscription appearing meanwhile must not change the amount
    bot = AsyncMock()
    await _choose(config)
    await queries.create_subscription(
        config.db_path, 5, "1m", datetime.utcnow() + timedelta(days=5)
    )
    await receive_screenshot(_photo_message(), bot, config)
    assert "1 000 ₽" in bot.send_photo.call_args.kwargs["caption"]


@pytest.mark.asyncio
async def test_method_message_asks_for_payer_in_caption(config):
    cb = await _choose(config)
    assert "ФИО" in cb.message.edit_text.call_args.args[0]
    cb = await _choose(config, "getcourse")
    assert "email" in cb.message.edit_text.call_args.args[0]


@pytest.mark.asyncio
async def test_caption_payer_reaches_reviewers(config):
    bot = AsyncMock()
    await _submit(config, bot)
    kwargs = bot.send_photo.call_args.kwargs
    assert "Плательщик: Иванова Анна Сергеевна" in kwargs["caption"]


@pytest.mark.asyncio
async def test_reviewer_sees_clickable_escaped_name(config):
    bot = AsyncMock()
    await queries.upsert_user(config.db_path, 5, None, "<Аня>")
    await _choose(config)
    msg = _photo_message()
    msg.from_user = MagicMock(id=5, username=None, first_name="<Аня>")
    await receive_screenshot(msg, bot, config)
    kwargs = bot.send_photo.call_args.kwargs
    assert kwargs["parse_mode"] == "HTML"
    assert '<a href="tg://user?id=5">&lt;Аня&gt;</a>' in kwargs["caption"]


@pytest.mark.asyncio
async def test_reviewer_sees_first_month(config):
    bot = AsyncMock()
    await _submit(config, bot)
    assert "первый месяц" in bot.send_photo.call_args.kwargs["caption"]


@pytest.mark.asyncio
async def test_reviewer_sees_renewal_and_current_expiry(config):
    await queries.upsert_user(config.db_path, 5, "u", "U")
    expires = datetime.utcnow() + timedelta(days=4)
    await queries.create_subscription(config.db_path, 5, "1m", expires)
    bot = AsyncMock()
    await _submit(config, bot)
    caption = bot.send_photo.call_args.kwargs["caption"]
    assert "продление" in caption and expires.strftime("%d.%m.%Y") in caption


@pytest.mark.asyncio
async def test_missing_payer_is_asked_but_screenshot_still_sent(config):
    bot = AsyncMock()
    await _choose(config)
    msg = _photo_message(caption=None)
    await receive_screenshot(msg, bot, config)
    bot.send_photo.assert_called_once()
    assert "ФИО" in msg.answer.call_args.args[0]


@pytest.mark.asyncio
async def test_payer_sent_later_goes_to_reviewers_with_buttons(config):
    bot = AsyncMock()
    await _choose(config)
    await receive_screenshot(_photo_message(caption=None), bot, config)
    reply = _text_message("Петров Пётр")
    await receive_payer_info(reply, bot, config)
    args, kwargs = bot.send_message.call_args
    assert args[0] == REVIEWER and "Петров Пётр" in args[1]
    assert [c.split(":")[1] for c in _callbacks(kwargs["reply_markup"])] == ["ok", "no"]
    assert "Спасибо" in reply.answer.call_args.args[0]


@pytest.mark.asyncio
async def test_text_without_waiting_payment_is_ignored(config):
    bot = AsyncMock()
    reply = _text_message("привет")
    await receive_payer_info(reply, bot, config)
    bot.send_message.assert_not_called()
    reply.answer.assert_not_called()


@pytest.mark.asyncio
async def test_payer_not_asked_again_once_given(config):
    bot = AsyncMock()
    await _submit(config, bot)  # caption already had the payer
    reply = _text_message("ещё вопрос")
    await receive_payer_info(reply, bot, config)
    bot.send_message.assert_not_called()
