import hashlib
import hmac
import json
import pytest
from datetime import datetime, timedelta
from unittest.mock import AsyncMock, MagicMock
from config import Config
from database.db import init_db
from database import queries
import webhook_server
from webhook_server import handle_tribute_webhook, create_webhook_app

KEY = "secret-key"


@pytest.fixture
async def config(tmp_path):
    path = str(tmp_path / "test.db")
    await init_db(path)
    return Config(
        bot_token="t", admin_ids=frozenset({1}), channel_id=-100,
        db_path=path, tribute_api_key=KEY,
    )


def _body():
    expires = (datetime.utcnow() + timedelta(days=30)).isoformat() + "Z"
    return json.dumps({
        "name": "new_subscription",
        "created_at": "2026-11-03T10:00:00Z",
        "sent_at": "2026-11-03T10:00:01Z",
        "payload": {
            "subscription_id": 1, "period_id": 2, "amount": 100000,
            "currency": "rub", "telegram_user_id": 55, "expires_at": expires,
        },
    }, ensure_ascii=False).encode()


def _request(config, body, signature=None):
    req = MagicMock()
    req.read = AsyncMock(return_value=body)
    sig = signature if signature is not None else hmac.new(
        KEY.encode(), body, hashlib.sha256
    ).hexdigest()
    req.headers = {"trbt-signature": sig}
    req.app = {"bot": AsyncMock(), "config": config}
    return req


@pytest.mark.asyncio
async def test_no_api_key_returns_503(config):
    config.tribute_api_key = ""
    resp = await handle_tribute_webhook(_request(config, _body(), "x"))
    assert resp.status == 503


@pytest.mark.asyncio
async def test_bad_signature_returns_401(config):
    resp = await handle_tribute_webhook(_request(config, _body(), "bad"))
    assert resp.status == 401
    assert await queries.get_user(config.db_path, 55) is None


@pytest.mark.asyncio
async def test_valid_event_is_stored(config):
    resp = await handle_tribute_webhook(_request(config, _body()))
    assert resp.status == 200
    assert await queries.get_active_tribute_subscription(config.db_path, 55) is not None


@pytest.mark.asyncio
async def test_signed_garbage_returns_400(config):
    resp = await handle_tribute_webhook(_request(config, b"not json"))
    assert resp.status == 400


@pytest.mark.asyncio
async def test_handler_error_returns_500(config, monkeypatch):
    monkeypatch.setattr(webhook_server, "handle_event", AsyncMock(side_effect=Exception("x")))
    resp = await handle_tribute_webhook(_request(config, _body()))
    assert resp.status == 500


def test_route_registered(config):
    app = create_webhook_app(MagicMock(), config, None)
    paths = {r.resource.canonical for r in app.router.routes()}
    assert "/tribute" in paths and "/webhook" in paths
