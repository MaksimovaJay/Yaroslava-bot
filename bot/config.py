import os
from dataclasses import dataclass, field
from dotenv import load_dotenv

@dataclass
class Config:
    bot_token: str
    admin_id: int
    channel_id: int
    db_path: str

    PLAN_1M_PRICE: int = field(default=500, init=False)
    PLAN_2M_PRICE: int = field(default=900, init=False)
    PLAN_1M_DAYS: int = field(default=30, init=False)
    PLAN_2M_DAYS: int = field(default=60, init=False)
    GRACE_PERIOD_DAYS: int = field(default=3, init=False)
    REMINDER_DAYS_BEFORE: int = field(default=3, init=False)


def load_config() -> Config:
    load_dotenv()
    return Config(
        bot_token=os.environ["BOT_TOKEN"],
        admin_id=int(os.environ["ADMIN_ID"]),
        channel_id=int(os.environ["CHANNEL_ID"]),
        db_path=os.environ.get("DB_PATH", "data/bot.db"),
    )
