from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

import aiosqlite


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


@dataclass(frozen=True, slots=True)
class StoredMessage:
    role: str
    content: str


@dataclass(frozen=True, slots=True)
class Ticket:
    id: int
    chat_id: int
    telegram_user_id: int
    contact: str
    summary: str
    status: str
    created_at: str
    closed_at: str | None


class Database:
    def __init__(self, path: Path | str) -> None:
        self.path = Path(path)

    async def connect(self) -> aiosqlite.Connection:
        connection = await aiosqlite.connect(self.path)
        connection.row_factory = aiosqlite.Row
        await connection.execute("PRAGMA foreign_keys = ON")
        await connection.execute("PRAGMA busy_timeout = 5000")
        return connection

    async def initialize(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        connection = await self.connect()
        try:
            await connection.execute("PRAGMA journal_mode = WAL")
            await connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS messages (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    chat_id INTEGER NOT NULL,
                    role TEXT NOT NULL CHECK (role IN ('user', 'assistant')),
                    content TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_messages_chat_id_id
                    ON messages(chat_id, id);

                CREATE TABLE IF NOT EXISTS tickets (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    chat_id INTEGER NOT NULL,
                    telegram_user_id INTEGER NOT NULL,
                    contact TEXT NOT NULL,
                    summary TEXT NOT NULL,
                    status TEXT NOT NULL DEFAULT 'open'
                        CHECK (status IN ('open', 'closed')),
                    created_at TEXT NOT NULL,
                    closed_at TEXT
                );
                CREATE INDEX IF NOT EXISTS idx_tickets_chat_id_status
                    ON tickets(chat_id, status);

                CREATE VIRTUAL TABLE IF NOT EXISTS faq_fts USING fts5(
                    section,
                    question,
                    answer,
                    tokenize = 'unicode61 remove_diacritics 2'
                );
                """
            )
            await connection.commit()
        finally:
            await connection.close()

    async def add_message(self, chat_id: int, role: str, content: str) -> int:
        connection = await self.connect()
        try:
            cursor = await connection.execute(
                "INSERT INTO messages(chat_id, role, content, created_at) "
                "VALUES (?, ?, ?, ?)",
                (chat_id, role, content, utc_now()),
            )
            await connection.commit()
            return int(cursor.lastrowid)
        finally:
            await connection.close()

    async def get_recent_messages(
        self, chat_id: int, limit: int = 10
    ) -> list[StoredMessage]:
        connection = await self.connect()
        try:
            cursor = await connection.execute(
                """
                SELECT role, content
                FROM (
                    SELECT id, role, content FROM messages
                    WHERE chat_id = ? ORDER BY id DESC LIMIT ?
                )
                ORDER BY id ASC
                """,
                (chat_id, limit),
            )
            rows = await cursor.fetchall()
            return [StoredMessage(row["role"], row["content"]) for row in rows]
        finally:
            await connection.close()

    async def create_ticket(
        self,
        *,
        chat_id: int,
        telegram_user_id: int,
        contact: str,
        summary: str,
    ) -> int:
        connection = await self.connect()
        try:
            cursor = await connection.execute(
                """
                INSERT INTO tickets(
                    chat_id, telegram_user_id, contact, summary, status, created_at
                ) VALUES (?, ?, ?, ?, 'open', ?)
                """,
                (chat_id, telegram_user_id, contact, summary, utc_now()),
            )
            await connection.commit()
            return int(cursor.lastrowid)
        finally:
            await connection.close()

    async def get_ticket(self, ticket_id: int) -> Ticket | None:
        connection = await self.connect()
        try:
            cursor = await connection.execute(
                "SELECT * FROM tickets WHERE id = ?", (ticket_id,)
            )
            row = await cursor.fetchone()
            return Ticket(**dict(row)) if row else None
        finally:
            await connection.close()

    async def close_ticket(self, ticket_id: int) -> bool:
        connection = await self.connect()
        try:
            cursor = await connection.execute(
                """
                UPDATE tickets SET status = 'closed', closed_at = ?
                WHERE id = ? AND status = 'open'
                """,
                (utc_now(), ticket_id),
            )
            await connection.commit()
            return cursor.rowcount == 1
        finally:
            await connection.close()
