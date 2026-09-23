from pathlib import Path
from unittest.mock import AsyncMock

import pytest

from app.database import Database
from app.faq import FAQRepository
from app.tools import ToolExecutionContext, ToolExecutor


@pytest.fixture
async def tool_setup(tmp_path: Path) -> tuple[Database, ToolExecutor, AsyncMock]:
    database = Database(tmp_path / "test.db")
    await database.initialize()
    bot = AsyncMock()
    return database, ToolExecutor(database, FAQRepository(database)), bot


async def test_create_ticket_uses_trusted_context(
    tool_setup: tuple[Database, ToolExecutor, AsyncMock],
) -> None:
    database, executor, bot = tool_setup
    context = ToolExecutionContext(
        chat_id=101,
        telegram_user_id=202,
        contact="@trusted",
        admin_chat_id=303,
        bot=bot,
    )
    result = await executor.execute(
        "create_ticket",
        {"summary": "Нужен специалист", "contact": "@untrusted"},
        context,
    )
    ticket = await database.get_ticket(result["ticket_id"])
    assert result["created"] is True
    assert ticket is not None
    assert ticket.chat_id == 101
    assert ticket.telegram_user_id == 202
    assert ticket.contact == "@trusted"
    bot.send_message.assert_awaited_once()
    assert bot.send_message.await_args.args[0] == 303


async def test_duplicate_ticket_is_rejected_in_same_loop(
    tool_setup: tuple[Database, ToolExecutor, AsyncMock],
) -> None:
    _, executor, bot = tool_setup
    context = ToolExecutionContext(1, 2, "telegram_user_id:2", 3, bot)
    result = await executor.execute(
        "create_ticket",
        {"summary": "Повтор", "contact": "telegram_user_id:2"},
        context,
        ticket_created=True,
    )
    assert result["created"] is False
    bot.send_message.assert_not_awaited()


async def test_ticket_remains_open_if_admin_notification_fails(
    tool_setup: tuple[Database, ToolExecutor, AsyncMock],
) -> None:
    database, executor, bot = tool_setup
    bot.send_message.side_effect = RuntimeError("offline")
    context = ToolExecutionContext(1, 2, "@client", 3, bot)
    result = await executor.create_ticket("Проблема", context)
    ticket = await database.get_ticket(result["ticket_id"])
    assert result["admin_notified"] is False
    assert ticket is not None and ticket.status == "open"


def test_malformed_tool_arguments() -> None:
    with pytest.raises(ValueError, match="JSON"):
        ToolExecutor.parse_arguments("{broken")

