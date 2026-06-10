from typing import Optional
from .base import PaymentProvider, PaymentResult


class StubPaymentProvider(PaymentProvider):
    async def create_payment(
        self, user_id: int, amount: int, plan: str
    ) -> PaymentResult:
        return PaymentResult(
            success=True,
            payment_id=f"stub_{user_id}_{plan}",
        )

    async def charge_saved(
        self, user_id: int, payment_token: Optional[str], amount: int
    ) -> PaymentResult:
        return PaymentResult(
            success=True,
            payment_id=f"stub_renew_{user_id}",
        )
