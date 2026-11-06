from config import Config
from database import queries


async def price_for(db_path: str, user_id: int, config: Config) -> int:
    """1 000 ₽ for a newcomer or someone who lapsed, 500 ₽ to renew on time.

    A subscription in its grace period is still 'active', so it renews at 500.
    """
    if await queries.has_current_subscription(db_path, user_id):
        return config.RENEWAL_PRICE
    return config.FIRST_MONTH_PRICE


def rub(amount: int) -> str:
    """1000 -> '1 000 ₽'"""
    return f"{amount:,}".replace(",", " ") + " ₽"


async def offer_text(config: Config, user_id: int) -> str:
    amount = await price_for(config.db_path, user_id, config)
    if amount == config.RENEWAL_PRICE:
        what = f"Продление на месяц — {rub(amount)}."
    else:
        what = (
            f"Первый месяц — {rub(config.FIRST_MONTH_PRICE)}, "
            f"дальше {rub(config.RENEWAL_PRICE)} в месяц."
        )
    return f"{what}\nВыберите способ оплаты:"
