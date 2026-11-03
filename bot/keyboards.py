from aiogram.types import InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder

from config import Config


def plans_keyboard(config: Config, channel_id: int) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(
        text=f"💳 1 месяц — {config.PLAN_1M_PRICE} ₽",
        callback_data=f"plan:1m:{channel_id}",
    )
    builder.button(
        text=f"💳 2 месяца — {config.PLAN_2M_PRICE} ₽",
        callback_data=f"plan:2m:{channel_id}",
    )
    builder.adjust(1)
    return builder.as_markup()


def tribute_keyboard(config: Config) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text="💳 Оформить подписку", url=config.tribute_subscribe_link)
    return builder.as_markup()


def sales_keyboard(config: Config, channel_id: int) -> InlineKeyboardMarkup:
    if config.tribute_enabled:
        return tribute_keyboard(config)
    return plans_keyboard(config, channel_id)
