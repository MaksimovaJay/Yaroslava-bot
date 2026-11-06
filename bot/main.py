import asyncio
import logging

from aiohttp import web
from aiogram import Bot, Dispatcher
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import BotCommand

from config import load_config
from database.db import init_db
from services.payment.stub import StubPaymentProvider
from services.payment.yookassa import YooKassaPaymentProvider
from handlers.start import router as start_router
from handlers.join import router as join_router
from handlers.payment import router as payment_router
from handlers.admin import router as admin_router
from handlers.manual_payment import router as manual_payment_router
from scheduler import create_scheduler
from webhook_server import create_webhook_app

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(name)s %(levelname)s %(message)s",
)
logger = logging.getLogger(__name__)


async def main() -> None:
    config = load_config()
    await init_db(config.db_path)

    bot = Bot(token=config.bot_token)
    try:
        await bot.set_my_commands([
            BotCommand(command="start", description="Начало"),
            BotCommand(command="pay", description="Оформить или продлить подписку"),
            BotCommand(command="help", description="Связаться с поддержкой"),
        ])
    except Exception as e:
        logger.warning("Could not set bot commands: %s", e)
    dp = Dispatcher(storage=MemoryStorage())

    if config.yookassa_shop_id and config.yookassa_secret_key:
        payment = YooKassaPaymentProvider(config.yookassa_shop_id, config.yookassa_secret_key)
        logger.info("Using YooKassa payment provider")
    elif config.use_stub_payments:
        payment = StubPaymentProvider()
        logger.warning("Using Stub payment provider — all payments are FREE")
    else:
        raise RuntimeError(
            "YOOKASSA_SHOP_ID/YOOKASSA_SECRET_KEY не заданы. "
            "Для локальной разработки без оплаты укажите PAYMENT_STUB=1."
        )

    dp.include_router(start_router)
    dp.include_router(join_router)
    dp.include_router(payment_router)
    dp.include_router(admin_router)
    dp.include_router(manual_payment_router)

    scheduler = create_scheduler(bot, config, payment)
    scheduler.start()
    logger.info("Scheduler started")

    webhook_app = create_webhook_app(bot, config, payment)
    runner = web.AppRunner(webhook_app)
    await runner.setup()
    site = web.TCPSite(runner, "0.0.0.0", 8080)
    await site.start()
    logger.info("Webhook server started on port 8080")

    try:
        logger.info("Bot starting (long polling)")
        await dp.start_polling(bot, config=config, payment=payment)
    finally:
        await runner.cleanup()
        scheduler.shutdown()
        await bot.session.close()
        logger.info("Bot stopped")


if __name__ == "__main__":
    asyncio.run(main())
