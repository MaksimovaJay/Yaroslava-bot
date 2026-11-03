import hashlib
import hmac
import logging
from datetime import datetime, timezone
from typing import Optional

from aiogram import Bot

from config import Config
from database import queries

logger = logging.getLogger(__name__)

_STATUS_BY_EVENT = {
    "new_subscription": "active",
    "renewed_subscription": "active",
    "cancelled_subscription": "cancelled",
}


def verify_signature(body: bytes, signature: Optional[str], api_key: str) -> bool:
    """Tribute signs the raw body with HMAC-SHA256 keyed by the API key."""
    if not api_key or not signature:
        return False
    expected = hmac.new(api_key.encode(), body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, signature)


def parse_dt(value: str) -> datetime:
    """ISO 8601 from Tribute -> naive UTC, the format the rest of the DB uses."""
    dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if dt.tzinfo is not None:
        dt = dt.astimezone(timezone.utc).replace(tzinfo=None)
    return dt


async def handle_event(event: dict, bot: Bot, config: Config) -> None:
    name = event.get("name")
    status = _STATUS_BY_EVENT.get(name)
    if status is None:
        return
    payload = event["payload"]
    user_id = payload["telegram_user_id"]
    username = payload.get("telegram_username")

    await queries.ensure_user(config.db_path, user_id, username, username or str(user_id))
    # The upsert is idempotent, so it goes first: if anything below fails,
    # Tribute's retry must not be mistaken for an already handled event.
    expires_at = parse_dt(payload["expires_at"])
    await queries.upsert_tribute_subscription(
        config.db_path, user_id,
        payload.get("subscription_id"), payload.get("period_id"),
        status, expires_at, parse_dt(event["created_at"]),
    )
    is_new = await queries.record_tribute_event(
        config.db_path, name, user_id, event["created_at"],
        payload.get("amount"), payload.get("currency"),
    )

    if is_new and name == "new_subscription":
        try:
            await bot.send_message(
                user_id,
                f"✅ Подписка оформлена!\n\n"
                f"Доступ к группе открыт до {expires_at.strftime('%d.%m.%Y')}.\n"
                f"Управлять подпиской можно в @tribute.",
            )
        except Exception as e:
            logger.warning("Could not welcome Tribute subscriber %s: %s", user_id, e)
