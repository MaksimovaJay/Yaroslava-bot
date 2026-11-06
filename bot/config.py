import os
from dataclasses import dataclass, field
from dotenv import load_dotenv


def _ids(value: str) -> frozenset:
    return frozenset(int(x.strip()) for x in value.split(",") if x.strip())


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
    mbank_card: str = ""
    mbank_recipient: str = ""
    getcourse_link_first: str = ""
    getcourse_link_renewal: str = ""
    support_username: str = "psihogolik_help"
    payment_reviewer_ids: frozenset = frozenset()

    FIRST_MONTH_PRICE: int = field(default=1000, init=False)
    RENEWAL_PRICE: int = field(default=500, init=False)
    PLAN_1M_PRICE: int = field(default=500, init=False)
    PLAN_2M_PRICE: int = field(default=900, init=False)
    PLAN_1M_DAYS: int = field(default=30, init=False)
    PLAN_2M_DAYS: int = field(default=60, init=False)
    PROMO_DAYS: int = field(default=60, init=False)
    TRIAL_DAYS: int = field(default=14, init=False)
    GRACE_PERIOD_DAYS: int = field(default=3, init=False)
    REMINDER_DAYS_BEFORE: int = field(default=3, init=False)
    MANUAL_REVIEW_RESEND_HOURS: int = field(default=24, init=False)

    @property
    def reviewer_ids(self) -> frozenset:
        return self.payment_reviewer_ids or self.admin_ids


def load_config() -> Config:
    load_dotenv()
    primary = int(os.environ["ADMIN_ID"])
    extra_ids = _ids(os.environ.get("EXTRA_ADMIN_IDS", ""))
    return Config(
        bot_token=os.environ["BOT_TOKEN"],
        admin_ids=frozenset({primary} | extra_ids),
        channel_id=int(os.environ["CHANNEL_ID"]),
        invite_link=os.environ.get("INVITE_LINK", ""),
        db_path=os.environ.get("DB_PATH", "data/bot.db"),
        yookassa_shop_id=os.environ.get("YOOKASSA_SHOP_ID", ""),
        yookassa_secret_key=os.environ.get("YOOKASSA_SECRET_KEY", ""),
        use_stub_payments=os.environ.get("PAYMENT_STUB", "") == "1",
        mbank_card=os.environ.get("MBANK_CARD", ""),
        mbank_recipient=os.environ.get("MBANK_RECIPIENT", ""),
        getcourse_link_first=os.environ.get("GETCOURSE_LINK_FIRST", ""),
        getcourse_link_renewal=os.environ.get("GETCOURSE_LINK_RENEWAL", ""),
        support_username=os.environ.get("SUPPORT_USERNAME", "psihogolik_help").lstrip("@"),
        payment_reviewer_ids=_ids(os.environ.get("PAYMENT_REVIEWER_IDS", "")),
    )
