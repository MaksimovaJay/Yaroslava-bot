import uuid
import logging
import aiohttp
from typing import Optional
from .base import PaymentProvider, PaymentResult

logger = logging.getLogger(__name__)


class YooKassaPaymentProvider(PaymentProvider):
    def __init__(self, shop_id: str, secret_key: str):
        self.shop_id = shop_id
        self.secret_key = secret_key
        self._base_url = "https://api.yookassa.ru/v3"

    async def create_payment(self, user_id: int, amount: int, plan: str) -> PaymentResult:
        description = "Подписка на 1 месяц" if plan == "1m" else "Подписка на 2 месяца"
        payload = {
            "amount": {"value": f"{amount}.00", "currency": "RUB"},
            "confirmation": {
                "type": "redirect",
                "return_url": "https://t.me/assistant_unicorn_bot",
            },
            "capture": True,
            "description": description,
            "metadata": {"user_id": str(user_id), "plan": plan},
            # Needed for auto-renewal: without it charge_saved is rejected
            "save_payment_method": True,
        }
        try:
            status, data = await self._post_payment(payload)
            if status != 200:
                # Shop may not have recurring payments enabled — a one-off
                # payment is better than no payment at all.
                logger.warning(
                    "YooKassa refused save_payment_method (%s: %s), retrying without it",
                    status, data,
                )
                payload.pop("save_payment_method")
                status, data = await self._post_payment(payload)
            if status == 200:
                return PaymentResult(
                    success=False,
                    payment_id=data["id"],
                    payment_url=data["confirmation"]["confirmation_url"],
                )
            logger.error("YooKassa error %s: %s", status, data)
            return PaymentResult(
                success=False,
                error=data.get("description", "Ошибка создания платежа"),
            )
        except Exception as e:
            logger.exception("YooKassa create_payment failed")
            return PaymentResult(success=False, error=str(e))

    async def _post_payment(self, payload: dict) -> tuple[int, dict]:
        async with aiohttp.ClientSession() as session:
            async with session.post(
                f"{self._base_url}/payments",
                json=payload,
                auth=aiohttp.BasicAuth(self.shop_id, self.secret_key),
                headers={"Idempotence-Key": str(uuid.uuid4())},
            ) as resp:
                return resp.status, await resp.json()

    async def charge_saved(
        self, user_id: int, payment_token: Optional[str], amount: int
    ) -> PaymentResult:
        if not payment_token:
            return PaymentResult(success=False, error="Нет сохранённого способа оплаты")
        payload = {
            "amount": {"value": f"{amount}.00", "currency": "RUB"},
            "payment_method_id": payment_token,
            "capture": True,
            "description": "Автопродление подписки",
            "metadata": {"user_id": str(user_id)},
        }
        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(
                    f"{self._base_url}/payments",
                    json=payload,
                    auth=aiohttp.BasicAuth(self.shop_id, self.secret_key),
                    headers={"Idempotence-Key": str(uuid.uuid4())},
                ) as resp:
                    data = await resp.json()
                    if resp.status == 200 and data.get("status") == "succeeded":
                        return PaymentResult(success=True, payment_id=data["id"])
                    logger.error("YooKassa charge_saved error %s: %s", resp.status, data)
                    return PaymentResult(
                        success=False,
                        error=data.get("description", "Ошибка автосписания"),
                    )
        except Exception as e:
            logger.exception("YooKassa charge_saved failed")
            return PaymentResult(success=False, error=str(e))

    async def get_payment_status(self, yookassa_payment_id: str) -> Optional[str]:
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(
                    f"{self._base_url}/payments/{yookassa_payment_id}",
                    auth=aiohttp.BasicAuth(self.shop_id, self.secret_key),
                ) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        return data.get("status")
                    return None
        except Exception:
            logger.exception("YooKassa get_payment_status failed")
            return None
