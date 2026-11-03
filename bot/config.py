import os
from dataclasses import dataclass, field
from dotenv import load_dotenv

@dataclass
class Config:
    bot_token: str
    admin_ids: frozenset
    channel_id: int
    db_path: str
    invite_link: str = ""
    yookassa_shop_id: str = ""
    yookassa_secret_key: str = ""
    use_stub_payments: bool = False
    tribute_api_key: str = ""
    tribute_subscribe_link: str = ""

    PLAN_1M_PRICE: int = field(default=500, init=False)
    PLAN_2M_PRICE: int = field(default=900, init=False)
    PLAN_1M_DAYS: int = field(default=30, init=False)
    PLAN_2M_DAYS: int = field(default=60, init=False)
    PROMO_DAYS: int = field(default=60, init=False)
    TRIAL_DAYS: int = field(default=14, init=False)
    GRACE_PERIOD_DAYS: int = field(default=3, init=False)
    REMINDER_DAYS_BEFORE: int = field(default=3, init=False)

    @property
    def tribute_enabled(self) -> bool:
        # Selling switches to Tribute as soon as the subscription link is set
        return bool(self.tribute_subscribe_link)


def load_config() -> Config:
    load_dotenv()
    primary = int(os.environ["ADMIN_ID"])
    extra = os.environ.get("EXTRA_ADMIN_IDS", "")
    extra_ids = {int(x.strip()) for x in extra.split(",") if x.strip()}
    return Config(
        bot_token=os.environ["BOT_TOKEN"],
        admin_ids=frozenset({primary} | extra_ids),
        channel_id=int(os.environ["CHANNEL_ID"]),
        invite_link=os.environ.get("INVITE_LINK", ""),
        db_path=os.environ.get("DB_PATH", "data/bot.db"),
        yookassa_shop_id=os.environ.get("YOOKASSA_SHOP_ID", ""),
        yookassa_secret_key=os.environ.get("YOOKASSA_SECRET_KEY", ""),
        use_stub_payments=os.environ.get("PAYMENT_STUB", "") == "1",
        tribute_api_key=os.environ.get("TRIBUTE_API_KEY", ""),
        tribute_subscribe_link=os.environ.get("TRIBUTE_SUBSCRIBE_LINK", ""),
    )
