import asyncio
import logging

from aiogram import Bot

from config import Config
from database import queries
from keyboards import payment_keyboard
from services.pricing import rub

logger = logging.getLogger(__name__)

# One-time message; a new key would send a new announcement to everyone again
ANNOUNCEMENT_KEY = "new_payment_methods_2026_11"


def _methods(config: Config) -> list:
    methods = []
    if config.mbank_card:
        methods.append("перевод на карту МБанк (Кыргызстан)")
    if config.getcourse_link_first or config.getcourse_link_renewal:
        methods.append("оплата через GetCourse")
    return methods


def new_methods_line(config: Config) -> str:
    methods = _methods(config)
    if not methods:
        return ""
    return "Теперь, кроме российской карты, можно: " + " и ".join(methods) + "."


def announcement_text(config: Config) -> str:
    lines = []
    if config.mbank_card:
        lines.append(
            "• 🌍 переводом на карту МБанк (Кыргызстан) — для граждан Кыргызстана "
            "и всех, кто за рубежом;"
        )
    if config.getcourse_link_first or config.getcourse_link_renewal:
        lines.append("• 📚 через GetCourse;")
    lines.append("• 💳 и, как раньше, российской картой.")
    return (
        "Здравствуйте! 🌿\n\n"
        "Уже 9 ноября в «Журнале Психоголика» — встреча в Zoom "
        "с Ириной Астафьевой:\n"
        "🎤 «Как организовывать мероприятия: от идеи до реализации»\n\n"
        "Встреча только для участников журнала — попасть на неё можно "
        "с подпиской.\n\n"
        "И хорошая новость: оформить подписку стало проще. Теперь оплатить можно:\n"
        + "\n".join(lines)
        + f"\n\nПервый месяц — {rub(config.FIRST_MONTH_PRICE)}, "
        f"дальше {rub(config.RENEWAL_PRICE)} в месяц.\n\n"
        "Выберите способ ниже 👇 После оплаты пришлите скриншот — мы откроем доступ, "
        "и вы успеете на встречу."
    )


async def announcement_recipients(config: Config) -> list:
    return await queries.get_announcement_recipients(
        config.db_path, ANNOUNCEMENT_KEY, config.admin_ids
    )


async def send_announcement(bot: Bot, config: Config) -> tuple:
    """Returns (sent, failed). Each person is claimed before sending, so two
    admins pressing the button at once can't message anyone twice."""
    text = announcement_text(config)
    markup = payment_keyboard(config, config.channel_id)
    sent = failed = 0
    for user_id in await announcement_recipients(config):
        if not await queries.claim_announcement(config.db_path, user_id, ANNOUNCEMENT_KEY):
            continue
        try:
            await bot.send_message(user_id, text, reply_markup=markup)
            sent += 1
        except Exception as e:
            # Usually the person blocked the bot; retrying wouldn't help
            logger.warning("Announcement to %s failed: %s", user_id, e)
            failed += 1
        await asyncio.sleep(0.05)  # stay well under Telegram's 30 msg/s limit
    return sent, failed
