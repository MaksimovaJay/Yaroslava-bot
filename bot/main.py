import asyncio
import logging

from aiogram import Bot, Dispatcher
from aiogram.fsm.storage.memory import MemoryStorage

from config import load_config
from database.db import init_db
from services.payment.stub import StubPaymentProvider
from handlers.start import router as start_router
from handlers.join import router as join_router
from handlers.payment import router as payment_router
from handlers.admin import router as admin_router
from scheduler import create_scheduler

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(name)s %(levelname)s %(message)s",
)
logger = logging.getLogger(__name__)


async def main() -> None:
    config = load_config()
    await init_db(config.db_path)

    bot = Bot(token=config.bot_token)
    dp = Dispatcher(storage=MemoryStorage())

    payment = StubPaymentProvider()

    dp.include_router(start_router)
    dp.include_router(join_router)
    dp.include_router(payment_router)
    dp.include_router(admin_router)

    scheduler = create_scheduler(bot, config, payment)
    scheduler.start()
    logger.info("Scheduler started")

    try:
        logger.info("Bot starting (long polling)")
        await dp.start_polling(bot, config=config, payment=payment)
    finally:
        scheduler.shutdown()
        await bot.session.close()
        logger.info("Bot stopped")


if __name__ == "__main__":
    asyncio.run(main())
