from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Optional


@dataclass
class PaymentResult:
    success: bool
    payment_id: Optional[str] = None
    payment_url: Optional[str] = None
    error: Optional[str] = None


class PaymentProvider(ABC):
    @abstractmethod
    async def create_payment(
        self, user_id: int, amount: int, plan: str
    ) -> PaymentResult: ...

    @abstractmethod
    async def charge_saved(
        self, user_id: int, payment_token: Optional[str], amount: int
    ) -> PaymentResult: ...
