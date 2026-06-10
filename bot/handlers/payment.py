import logging
from aiogram import Router, Bot, F
from aiogram.types import CallbackQuery

from config import Config
from database import queries
from services.subscription import create_subscription
from services.payment.base import PaymentProvider

router = Router()
logger = logging.getLogger(__name__)


@router.callback_query(F.data.startswith("plan:"))
async def handle_plan_selection(
    callback: CallbackQuery,
    bot: Bot,
    config: Config,
    payment: PaymentProvider,
) -> None:
    _, plan, channel_id_str = callback.data.split(":")
    channel_id = int(channel_id_str)
    user = callback.from_user
    amount = config.PLAN_1M_PRICE if plan == "1m" else config.PLAN_2M_PRICE
    plan_label = "1 месяц" if plan == "1m" else "2 месяца"

    await callback.message.edit_text("⏳ Обрабатываем оплату...")

    pay_rec_id = await queries.create_payment(config.db_path, user.id, amount, plan)
    result = await payment.create_payment(user.id, amount, plan)

    if not result.success:
        await queries.update_payment(config.db_path, pay_rec_id, "failed")
        await callback.message.edit_text(
            f"❌ Ошибка оплаты: {result.error or 'попробуйте позже'}.\n\n"
            f"Напишите /start чтобы попробовать снова."
        )
        return

    await queries.update_payment(
        config.db_path, pay_rec_id, "success", result.payment_id
    )
    sub = await create_subscription(config.db_path, user.id, plan, config)

    try:
        await bot.approve_chat_join_request(channel_id, user.id)
    except Exception as e:
        logger.warning("Could not approve join request for %s: %s", user.id, e)

    expires_str = sub["expires_at"].strftime("%d.%m.%Y")
    await callback.message.edit_text(
        f"✅ Оплата прошла успешно!\n\n"
        f"Тариф: {plan_label}\n"
        f"Подписка активна до: {expires_str}\n\n"
        f"Добро пожаловать в канал! 🎉"
    )
