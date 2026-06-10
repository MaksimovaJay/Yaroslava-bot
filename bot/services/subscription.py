from datetime import datetime, timedelta
from typing import Optional
from aiogram import Bot

from config import Config
from database import queries


async def create_subscription(
    db_path: str, user_id: int, plan: str, config: Config
) -> dict:
    days = config.PLAN_1M_DAYS if plan == "1m" else config.PLAN_2M_DAYS
    expires_at = datetime.now() + timedelta(days=days)
    sub_id = await queries.create_subscription(db_path, user_id, plan, expires_at)
    return {"id": sub_id, "expires_at": expires_at, "plan": plan}


async def renew_subscription(
    db_path: str, sub: dict, config: Config
) -> datetime:
    days = config.PLAN_1M_DAYS if sub["plan"] == "1m" else config.PLAN_2M_DAYS
    old_expires = datetime.fromisoformat(sub["expires_at"])
    base = max(datetime.now(), old_expires)
    new_expires = base + timedelta(days=days)
    await queries.extend_subscription(db_path, sub["id"], new_expires)
    return new_expires


async def kick_user(bot: Bot, channel_id: int, user_id: int) -> None:
    await bot.ban_chat_member(channel_id, user_id)
    await bot.unban_chat_member(channel_id, user_id)
