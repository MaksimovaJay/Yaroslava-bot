from aiogram import Router
from aiogram.filters import CommandStart
from aiogram.types import Message

from config import Config
from database import queries

router = Router()


@router.message(CommandStart())
async def cmd_start(message: Message, config: Config) -> None:
    await queries.upsert_user(
        config.db_path,
        message.from_user.id,
        message.from_user.username,
        message.from_user.first_name,
    )
    sub = await queries.get_active_subscription(config.db_path, message.from_user.id)
    if sub:
        expires = sub["expires_at"][:10]
        await message.answer(
            f"👋 Привет, {message.from_user.first_name}!\n\n"
            f"Ваша подписка активна до {expires}."
        )
    else:
        await message.answer(
            f"👋 Привет, {message.from_user.first_name}!\n\n"
            f"Чтобы получить доступ к каналу — перейдите по ссылке на канал "
            f"и подайте заявку на вступление."
        )
