import tempfile
import pytest
import aiosqlite
from database.db import init_db


@pytest.mark.asyncio
async def test_init_creates_all_three_tables():
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        path = f.name
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
async def test_init_is_idempotent():
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        path = f.name
    await init_db(path)
    await init_db(path)  # must not raise
