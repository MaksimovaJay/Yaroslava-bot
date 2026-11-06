from urllib.parse import urlparse, parse_qs
from config import Config
from keyboards import support_keyboard, payment_keyboard


def _config(**kw):
    return Config(bot_token="t", admin_ids=frozenset({1}), channel_id=-100, db_path="x", **kw)


def test_support_keyboard_opens_chat_with_prefilled_text():
    markup = support_keyboard(_config())
    buttons = [b for row in markup.inline_keyboard for b in row]
    assert [b.text for b in buttons] == ["💳 Сложности с оплатой", "💬 Прочие вопросы"]
    for b in buttons:
        url = urlparse(b.url)
        assert url.netloc == "t.me" and url.path == "/psihogolik_help"
        assert parse_qs(url.query)["text"][0].startswith("Здравствуйте!")


def test_payment_keyboard_shows_only_configured_methods():
    bare = payment_keyboard(_config(), -100)
    assert [b.callback_data for row in bare.inline_keyboard for b in row] == [
        "plan:1m:-100", "support",
    ]
    full = payment_keyboard(
        _config(mbank_card="4177", getcourse_link_first="https://gc"), -100
    )
    assert [b.callback_data for row in full.inline_keyboard for b in row] == [
        "plan:1m:-100", "manual:mbank", "manual:getcourse", "support",
    ]
