import logging
from datetime import datetime, timedelta

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from aiogram import Bot

from config import Config
from database import queries
from services.subscription import renew_subscription, kick_user
from services.payment.base import PaymentProvider
from keyboards import payment_keyboard
from services.pricing import rub

logger = logging.getLogger(__name__)


async def send_expiry_reminders(bot: Bot, config: Config) -> None:
    expiring = await queries.get_subscriptions_expiring_soon(
        config.db_path, config.REMINDER_DAYS_BEFORE
    )
    for sub in expiring:
        expires_date = datetime.fromisoformat(sub["expires_at"]).strftime("%d.%m.%Y")
        if sub.get("payment_token"):
            text = (
                f"⏰ Ваша подписка истекает {expires_date}. "
                f"Мы попробуем продлить её автоматически, а если не получится — "
                f"пришлём кнопки для оплаты."
            )
            markup = None
        else:
            text = (
                f"⏰ Ваша подписка истекает {expires_date}.\n"
                f"Продлите её заранее, чтобы не потерять доступ: "
                f"продление на месяц — {rub(config.RENEWAL_PRICE)}. "
                f"Новый срок добавится к текущему."
            )
            markup = payment_keyboard(config, config.channel_id)
        try:
            await bot.send_message(sub["user_id"], text, reply_markup=markup)
        except Exception as e:
            logger.warning("Could not send reminder to %s: %s", sub["user_id"], e)


async def process_expired_subscriptions(
    bot: Bot, config: Config, payment: PaymentProvider
) -> None:
    expired = await queries.get_expired_subscriptions(config.db_path)
    for sub in expired:
        # User already bought a new subscription — just close the old one
        if await queries.get_active_subscription(config.db_path, sub["user_id"]):
            await queries.expire_subscription(config.db_path, sub["id"])
            continue
        amount = config.RENEWAL_PRICE
        result = await payment.charge_saved(
            sub["user_id"], sub.get("payment_token"), amount
        )
        if result.success:
            new_expires = await renew_subscription(config.db_path, sub, config)
            record_id = await queries.create_payment(
                config.db_path, sub["user_id"], amount, sub["plan"]
            )
            await queries.update_payment(
                config.db_path, record_id, "success", result.payment_id
            )
            try:
                await bot.send_message(
                    sub["user_id"],
                    f"✅ Подписка продлена до {new_expires.strftime('%d.%m.%Y')}!",
                )
            except Exception as e:
                logger.warning("Could not notify %s: %s", sub["user_id"], e)
        else:
            grace_ends_at = datetime.utcnow() + timedelta(days=config.GRACE_PERIOD_DAYS)
            await queries.start_grace_period(config.db_path, sub["id"], grace_ends_at)
            try:
                await bot.send_message(
                    sub["user_id"],
                    f"⚠️ Срок подписки закончился, автоматически продлить её не удалось.\n"
                    f"Доступ сохранится ещё {config.GRACE_PERIOD_DAYS} дня — "
                    f"продлите за {rub(config.RENEWAL_PRICE)}, выберите способ оплаты:",
                    reply_markup=payment_keyboard(config, config.channel_id),
                )
            except Exception as e:
                logger.warning("Could not notify %s: %s", sub["user_id"], e)


async def process_grace_period_ended(bot: Bot, config: Config) -> None:
    ended = await queries.get_grace_period_ended(config.db_path)
    for sub in ended:
        paid_again = await queries.get_active_subscription(
            config.db_path, sub["user_id"]
        )
        if sub["user_id"] in config.admin_ids or paid_again:
            await queries.expire_subscription(config.db_path, sub["id"])
            continue
        try:
            await kick_user(bot, config.channel_id, sub["user_id"])
        except Exception as e:
            logger.warning("Could not kick %s: %s", sub["user_id"], e)
        await queries.expire_subscription(config.db_path, sub["id"])
        try:
            await bot.send_message(
                sub["user_id"],
                "❌ Подписка истекла, доступ к группе закрыт.\n"
                "Чтобы вернуться — оформите подписку снова:",
                reply_markup=payment_keyboard(config, config.channel_id),
            )
        except Exception as e:
            logger.warning("Could not notify %s: %s", sub["user_id"], e)


async def resend_stale_reviews(bot: Bot, config: Config) -> None:
    from handlers.manual_payment import send_for_review
    stale = await queries.get_stale_manual_reviews(
        config.db_path, config.MANUAL_REVIEW_RESEND_HOURS
    )
    for payment in stale:
        await send_for_review(bot, config, payment, note="⏳ Ждёт проверки больше суток\n")
        await queries.mark_manual_resent(config.db_path, payment["id"])


async def daily_job(bot: Bot, config: Config, payment: PaymentProvider) -> None:
    logger.info("Running daily subscription check")
    await send_expiry_reminders(bot, config)
    await process_expired_subscriptions(bot, config, payment)
    await process_grace_period_ended(bot, config)
    await resend_stale_reviews(bot, config)


def create_scheduler(
    bot: Bot, config: Config, payment: PaymentProvider
) -> AsyncIOScheduler:
    scheduler = AsyncIOScheduler()
    scheduler.add_job(
        daily_job,
        trigger="cron",
        hour=10,
        minute=0,
        args=[bot, config, payment],
    )
    return scheduler
