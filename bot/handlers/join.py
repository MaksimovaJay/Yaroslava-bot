import logging
from aiogram import Router, Bot
from aiogram.types import ChatJoinRequest
from aiogram.utils.keyboard import InlineKeyboardBuilder

from config import Config
from database import queries

router = Router()
logger = logging.getLogger(__name__)


@router.chat_join_request()
async def handle_join_request(
    request: ChatJoinRequest, bot: Bot, config: Config
) -> None:
    user = request.from_user
    channel_id = request.chat.id

    await queries.upsert_user(
        config.db_path, user.id, user.username, user.first_name
    )

    if await queries.is_user_banned(config.db_path, user.id):
        await request.decline()
        return

    sub = await queries.get_active_subscription(config.db_path, user.id)
    if sub:
        await request.approve()
        return

    builder = InlineKeyboardBuilder()
    builder.button(
        text="💳 1 месяц — 500 ₽",
        callback_data=f"plan:1m:{channel_id}",
    )
    builder.button(
        text="💳 2 месяца — 900 ₽",
        callback_data=f"plan:2m:{channel_id}",
    )
    builder.adjust(1)

    try:
        await bot.send_message(
            user.id,
            f"👋 Привет, {user.first_name}!\n\n"
            f"Это закрытый канал с платной подпиской.\n"
            f"Выберите тариф:",
            reply_markup=builder.as_markup(),
        )
    except Exception:
        logger.warning(
            "Cannot send DM to user %s — they haven't started the bot", user.id
        )
        await request.decline()
