import logging
from aiohttp import web
from aiogram import Bot

from config import Config
from database import queries
from services.subscription import create_subscription
from services.payment.yookassa import YooKassaPaymentProvider

logger = logging.getLogger(__name__)


async def handle_webhook(request: web.Request) -> web.Response:
    bot: Bot = request.app["bot"]
    config: Config = request.app["config"]
    payment: YooKassaPaymentProvider = request.app["payment"]

    try:
        body = await request.json()
    except Exception:
        return web.Response(status=400)

    if body.get("event") != "payment.succeeded":
        return web.Response(status=200)

    yookassa_payment_id = body.get("object", {}).get("id")
    if not yookassa_payment_id:
        return web.Response(status=400)

    if not hasattr(payment, "get_payment_status"):
        logger.warning("Webhook received but payment provider can't verify it")
        return web.Response(status=200)

    status = await payment.get_payment_status(yookassa_payment_id)
    if status != "succeeded":
        logger.warning("Webhook for %s but status=%s", yookassa_payment_id, status)
        return web.Response(status=200)

    record = await queries.get_pending_payment_by_external_id(
        config.db_path, yookassa_payment_id
    )
    if not record:
        logger.warning("No pending record for payment %s", yookassa_payment_id)
        return web.Response(status=200)

    user_id = record["user_id"]
    plan = record["plan"]

    await queries.update_payment(config.db_path, record["id"], "success", yookassa_payment_id)
    sub = await create_subscription(config.db_path, user_id, plan, config)

    # An unsaved method can't be charged again, so don't pretend we can renew
    payment_method = body.get("object", {}).get("payment_method", {})
    if payment_method.get("id") and payment_method.get("saved"):
        await queries.save_payment_token(config.db_path, sub["id"], payment_method["id"])

    try:
        await bot.approve_chat_join_request(config.channel_id, user_id)
    except Exception as e:
        logger.warning("Could not approve join request for %s: %s", user_id, e)

    expires_str = sub["expires_at"].strftime("%d.%m.%Y")
    plan_label = "1 месяц" if plan == "1m" else "2 месяца"
    try:
        await bot.send_message(
            user_id,
            f"✅ Оплата прошла успешно!\n\n"
            f"Тариф: {plan_label}\n"
            f"Подписка активна до: {expires_str}\n\n"
            f"Добро пожаловать в группу! 🎉",
        )
    except Exception as e:
        logger.warning("Could not notify user %s: %s", user_id, e)

    return web.Response(status=200)


def create_webhook_app(bot: Bot, config: Config, payment) -> web.Application:
    app = web.Application()
    app["bot"] = bot
    app["config"] = config
    app["payment"] = payment
    app.router.add_post("/webhook", handle_webhook)
    return app
