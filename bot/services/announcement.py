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
        "В «Блокноте Психоголика» появились новые материалы!\n\n"
        "🎤 Запись встречи с Ириной Астафьевой «Как организовывать мероприятия: "
        "от идеи до реализации» с возможностью получить баллы CEU за просмотр.\n\n"
        "🎨 Большой чек-лист со ссылками для организации арт-зоны в ABA-кабинете. "
        "Скоро — чек-лист для экспериментальной зоны!\n\n"
        "🔒 Все материалы доступны только подписчикам журнала.\n\n"
        f"💳 Первый месяц — {rub(config.FIRST_MONTH_PRICE)}, каждый следующий — "
        f"{rub(config.RENEWAL_PRICE)} при продлении.\n\n"
        "И хорошая новость: оформить подписку стало проще. Теперь оплатить можно:\n"
        + "\n".join(lines)
        + "\n\nВыберите способ ниже 👇"
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
