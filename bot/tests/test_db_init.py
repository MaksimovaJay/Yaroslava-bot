import pytest
import aiosqlite
from database.db import init_db


@pytest.mark.asyncio
async def test_init_creates_all_three_tables(tmp_path):
    path = str(tmp_path / "test.db")
    await init_db(path)
    async with aiosqlite.connect(path) as db:
        async with db.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ) as cursor:
            tables = {row[0] async for row in cursor}
    assert "users" in tables
    assert "subscriptions" in tables
    assert "payments" in tables


@pytest.mark.asyncio
async def test_init_is_idempotent(tmp_path):
    path = str(tmp_path / "test.db")
    await init_db(path)
    await init_db(path)  # must not raise


@pytest.mark.asyncio
async def test_subscriptions_table_has_required_columns(tmp_path):
    path = str(tmp_path / "test.db")
    await init_db(path)
    async with aiosqlite.connect(path) as db:
        async with db.execute("PRAGMA table_info(subscriptions)") as cursor:
            columns = {row[1] async for row in cursor}
    required = {"id", "user_id", "plan", "started_at", "expires_at", "status",
                "payment_token", "in_grace", "grace_ends_at"}
    assert required.issubset(columns)
