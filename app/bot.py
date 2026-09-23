from __future__ import annotations

import asyncio
import logging
import re
from collections import defaultdict
from contextlib import asynccontextmanager
from typing import AsyncIterator

import aiosqlite
from aiogram import Bot, F, Router
from aiogram.exceptions import TelegramAPIError
from aiogram.filters import Command
from aiogram.types import Message
from openai import APIConnectionError, APIError, APITimeoutError

from app.config import Settings
from app.database import Database
from app.llm import LLMService, ToolLoopLimitError
from app.tools import ToolExecutionContext

logger = logging.getLogger(__name__)
REPLY_RE = re.compile(r"^/reply(?:@\w+)?\s+(\d+)\s+([\s\S]+)$")
TEMPORARY_ERROR = "Сейчас не получается получить ответ. Попробуйте ещё раз чуть позже."


class ChatLockPool:
    """Serializes messages within one chat without retaining unused locks."""

    def __init__(self) -> None:
        self._locks: dict[int, asyncio.Lock] = {}
        self._users: defaultdict[int, int] = defaultdict(int)
        self._guard = asyncio.Lock()

    @asynccontextmanager
    async def hold(self, chat_id: int) -> AsyncIterator[None]:
        async with self._guard:
            lock = self._locks.setdefault(chat_id, asyncio.Lock())
            self._users[chat_id] += 1
        try:
            async with lock:
                yield
        finally:
            async with self._guard:
                self._users[chat_id] -= 1
                if self._users[chat_id] == 0 and not lock.locked():
                    del self._users[chat_id]
                    self._locks.pop(chat_id, None)


def create_router(
    settings: Settings,
    database: Database,
    llm_service: LLMService,
) -> Router:
    router = Router(name="support")
    chat_locks = ChatLockPool()
    ticket_locks = ChatLockPool()

    @router.message(Command("reply"))
    async def reply_to_ticket(message: Message, bot: Bot) -> None:
        if message.chat.id != settings.admin_chat_id:
            await message.answer("Эта команда доступна только администратору.")
            return
        match = REPLY_RE.match(message.text or "")
        if not match:
            await message.answer("Использование: /reply <ticket_id> <текст ответа>")
            return
        ticket_id = int(match.group(1))
        response_text = match.group(2).strip()
        # A ticket-scoped lock prevents two simultaneous admin commands from
        # delivering duplicate replies in this bot process.
        async with ticket_locks.hold(ticket_id):
            try:
                ticket = await database.get_ticket(ticket_id)
                if ticket is None:
                    await message.answer(f"Заявка #{ticket_id} не найдена.")
                    return
                if ticket.status != "open":
                    await message.answer(f"Заявка #{ticket_id} уже закрыта.")
                    return
                try:
                    await bot.send_message(ticket.chat_id, response_text)
                except TelegramAPIError:
                    logger.exception("Could not deliver reply for ticket %s", ticket_id)
                    await message.answer(
                        "Не удалось отправить ответ пользователю. Заявка не закрыта."
                    )
                    return
                if not await database.close_ticket(ticket_id):
                    await message.answer(
                        "Ответ доставлен, но статус заявки уже был изменён."
                    )
                    return
                await message.answer(
                    f"Ответ по заявке #{ticket_id} отправлен. Заявка закрыта."
                )
            except aiosqlite.Error:
                logger.exception("Database operation failed for ticket %s", ticket_id)
                await _safe_answer(message, "Не удалось обработать заявку. Попробуйте позже.")

    @router.message(F.text)
    async def handle_text(message: Message, bot: Bot) -> None:
        if message.text is None or message.from_user is None:
            return
        chat_id = message.chat.id
        # Административный чат — это очередь заявок, а не клиентский диалог.
        # Команду /reply обрабатывает зарегистрированный выше обработчик;
        # весь остальной текст в этом чате нужно игнорировать.
        if chat_id == settings.admin_chat_id:
            return
        user_id = message.from_user.id
        contact = (
            f"@{message.from_user.username}"
            if message.from_user.username
            else f"telegram_user_id:{user_id}"
        )
        context = ToolExecutionContext(
            chat_id=chat_id,
            telegram_user_id=user_id,
            contact=contact,
            admin_chat_id=settings.admin_chat_id,
            bot=bot,
        )
        async with chat_locks.hold(chat_id):
            try:
                await database.add_message(chat_id, "user", message.text)
                history = await database.get_recent_messages(chat_id, limit=10)
                answer = await llm_service.run_conversation(history, context)
                await message.answer(answer)
                await database.add_message(chat_id, "assistant", answer)
            except (APITimeoutError, APIConnectionError, APIError, ToolLoopLimitError):
                logger.exception("LLM request failed for chat %s", chat_id)
                await _safe_answer(message, TEMPORARY_ERROR)
            except aiosqlite.Error:
                logger.exception("Database operation failed for chat %s", chat_id)
                await _safe_answer(message, TEMPORARY_ERROR)
            except TelegramAPIError:
                logger.exception("Telegram operation failed for chat %s", chat_id)
            except Exception:
                logger.exception("Unexpected message handling error for chat %s", chat_id)
                await _safe_answer(message, TEMPORARY_ERROR)

    return router


async def _safe_answer(message: Message, text: str) -> None:
    try:
        await message.answer(text)
    except TelegramAPIError:
        logger.exception("Could not send an error message to chat %s", message.chat.id)
