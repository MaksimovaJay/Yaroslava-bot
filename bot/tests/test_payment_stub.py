import pytest
from services.payment.stub import StubPaymentProvider


@pytest.mark.asyncio
async def test_stub_create_payment_always_succeeds():
    provider = StubPaymentProvider()
    result = await provider.create_payment(123, 500, "1m")
    assert result.success is True
    assert result.payment_id is not None
    assert result.error is None


@pytest.mark.asyncio
async def test_stub_charge_saved_always_succeeds():
    provider = StubPaymentProvider()
    result = await provider.charge_saved(123, "any_token", 500)
    assert result.success is True
    assert result.payment_id is not None


@pytest.mark.asyncio
async def test_stub_charge_saved_with_none_token():
    provider = StubPaymentProvider()
    result = await provider.charge_saved(123, None, 500)
    assert result.success is True
