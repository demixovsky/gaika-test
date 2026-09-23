from pathlib import Path

from app.database import Database


async def test_history_is_isolated_limited_and_chronological(tmp_path: Path) -> None:
    database = Database(tmp_path / "history.db")
    await database.initialize()
    for index in range(12):
        await database.add_message(1, "user", f"message-{index}")
    await database.add_message(2, "user", "other-chat")

    history = await database.get_recent_messages(1)
    assert [item.content for item in history] == [
        f"message-{index}" for index in range(2, 12)
    ]


async def test_close_ticket_only_once(tmp_path: Path) -> None:
    database = Database(tmp_path / "tickets.db")
    await database.initialize()
    ticket_id = await database.create_ticket(
        chat_id=1,
        telegram_user_id=2,
        contact="@client",
        summary="summary",
    )
    assert await database.close_ticket(ticket_id) is True
    assert await database.close_ticket(ticket_id) is False
    ticket = await database.get_ticket(ticket_id)
    assert ticket is not None and ticket.closed_at is not None

