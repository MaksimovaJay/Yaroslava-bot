from urllib.parse import quote

from aiogram.types import InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder

from config import Config

SUPPORT_PAYMENT_TEXT = (
    "Здравствуйте! Я пытаюсь оформить подписку на журнал, "
    "но у меня возникли сложности с оплатой. Подскажите, пожалуйста, что делать?"
)
SUPPORT_OTHER_TEXT = "Здравствуйте! У меня вопрос по журналу:"


def payment_keyboard(config: Config, channel_id: int) -> InlineKeyboardMarkup:
    """Payment methods; the price is in the message text since it depends on the user."""
    builder = InlineKeyboardBuilder()
    builder.button(text="💳 Картой РФ", callback_data=f"plan:1m:{channel_id}")
    if config.mbank_card:
        builder.button(text="🌍 Карта Кыргызстана (МБанк)", callback_data="manual:mbank")
    if config.getcourse_link_first or config.getcourse_link_renewal:
        builder.button(text="📚 Через GetCourse", callback_data="manual:getcourse")
    builder.button(text="🆘 Связаться с поддержкой", callback_data="support")
    builder.adjust(1)
    return builder.as_markup()


def support_keyboard(config: Config) -> InlineKeyboardMarkup:
    base = f"https://t.me/{config.support_username}?text="
    builder = InlineKeyboardBuilder()
    builder.button(text="💳 Сложности с оплатой", url=base + quote(SUPPORT_PAYMENT_TEXT))
    builder.button(text="💬 Прочие вопросы", url=base + quote(SUPPORT_OTHER_TEXT))
    builder.adjust(1)
    return builder.as_markup()
