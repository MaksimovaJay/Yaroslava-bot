import logging
from aiogram import Router, Bot, F
from aiogram.types import ChatJoinRequest, Message
from config import Config
from database import queries
from keyboards import payment_keyboard
from services.pricing import offer_text

router = Router()
logger = logging.getLogger(__name__)


@router.message(F.new_chat_members)
async def delete_join_message(message: Message) -> None:
    try:
        await message.delete()
    except Exception:
        pass


@router.message(F.left_chat_member)
async def delete_leave_message(message: Message) -> None:
    try:
        await message.delete()
    except Exception:
        pass


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

    try:
        await bot.send_message(
            user.id,
            f"👋 Привет, {user.first_name}!\n\n"
            f"Это закрытая группа «Журнал Психоголика» с платной подпиской.\n"
            f"{await offer_text(config, user.id)}",
            reply_markup=payment_keyboard(config, channel_id),
        )
    except Exception:
        logger.warning(
            "Cannot send DM to user %s — they haven't started the bot", user.id
        )
        await request.decline()
