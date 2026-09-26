import pytest
from services.payment.yookassa import YooKassaPaymentProvider

OK = (200, {"id": "p1", "confirmation": {"confirmation_url": "https://pay"}})


@pytest.mark.asyncio
async def test_create_payment_asks_to_save_card():
    provider = YooKassaPaymentProvider("shop", "key")
    sent = []

    async def fake_post(payload):
        sent.append(dict(payload))
        return OK

    provider._post_payment = fake_post
    result = await provider.create_payment(1, 500, "1m")
    assert result.payment_url == "https://pay"
    assert sent[0]["save_payment_method"] is True
    assert len(sent) == 1


@pytest.mark.asyncio
async def test_create_payment_falls_back_when_saving_is_forbidden():
    provider = YooKassaPaymentProvider("shop", "key")
    sent = []

    async def fake_post(payload):
        sent.append(dict(payload))
        if payload.get("save_payment_method"):
            return 403, {"code": "forbidden", "description": "not allowed"}
        return OK

    provider._post_payment = fake_post
    result = await provider.create_payment(1, 500, "1m")
    assert result.payment_url == "https://pay"
    assert len(sent) == 2
    assert "save_payment_method" not in sent[1]
