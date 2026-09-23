from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from typing import Any, Protocol

from app.database import Database
from app.faq import FAQRepository

logger = logging.getLogger(__name__)


class MessageSender(Protocol):
    async def send_message(self, chat_id: int, text: str, **kwargs: Any) -> Any: ...


@dataclass(frozen=True, slots=True)
class ToolExecutionContext:
    chat_id: int
    telegram_user_id: int
    contact: str
    admin_chat_id: int
    bot: MessageSender


TOOL_DEFINITIONS: list[dict[str, Any]] = [
    {
        "type": "function",
        "function": {
            "name": "search_faq",
            "description": (
                "Ищет информацию в FAQ автосервиса. Используй для любых "
                "фактических вопросов о сервисе, услугах, ценах, записи, "
                "гарантии и правилах."
            ),
            "parameters": {
                "type": "object",
                "properties": {"query": {"type": "string"}},
                "required": ["query"],
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "create_ticket",
            "description": (
                "Создаёт заявку оператору поддержки. Используй, если ответа "
                "в FAQ нет, требуется решение человека или пользователь прямо "
                "просит оператора."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "summary": {"type": "string"},
                    "contact": {"type": "string"},
                },
                "required": ["summary", "contact"],
                "additionalProperties": False,
            },
        },
    },
]


class ToolExecutor:
    def __init__(self, database: Database, faq: FAQRepository) -> None:
        self.database = database
        self.faq = faq

    async def execute(
        self,
        name: str,
        arguments: dict[str, Any],
        context: ToolExecutionContext,
        *,
        ticket_created: bool = False,
    ) -> dict[str, Any]:
        if name == "search_faq":
            query = self._required_string(arguments, "query")
            results = await self.faq.search_faq(query)
            return {"results": [result.to_dict() for result in results]}
        if name == "create_ticket":
            if ticket_created:
                return {
                    "created": False,
                    "reason": "Заявка уже создана в рамках текущего запроса.",
                }
            summary = self._required_string(arguments, "summary")
            # Contact from the model is validated but the trusted context wins.
            self._required_string(arguments, "contact")
            return await self.create_ticket(summary, context)
        return {"error": f"Неизвестный инструмент: {name}"}

    async def create_ticket(
        self, summary: str, context: ToolExecutionContext
    ) -> dict[str, Any]:
        ticket_id = await self.database.create_ticket(
            chat_id=context.chat_id,
            telegram_user_id=context.telegram_user_id,
            contact=context.contact,
            summary=summary,
        )
        notification = (
            f"🆕 Заявка #{ticket_id}\n\n"
            f"Клиент: {context.contact}\n"
            f"Telegram ID: {context.telegram_user_id}\n\n"
            f"Проблема:\n{summary}\n\n"
            f"Для ответа:\n/reply {ticket_id} Текст ответа"
        )
        try:
            await context.bot.send_message(context.admin_chat_id, notification)
        except Exception:
            logger.exception("Could not notify admin about ticket %s", ticket_id)
            return {
                "created": True,
                "ticket_id": ticket_id,
                "admin_notified": False,
                "message": "Заявка сохранена, но уведомление оператору временно не доставлено.",
            }
        return {
            "created": True,
            "ticket_id": ticket_id,
            "admin_notified": True,
            "message": "Заявка создана и передана специалисту.",
        }

    @staticmethod
    def parse_arguments(raw_arguments: str) -> dict[str, Any]:
        try:
            value = json.loads(raw_arguments)
        except json.JSONDecodeError as exc:
            raise ValueError("Аргументы инструмента содержат некорректный JSON") from exc
        if not isinstance(value, dict):
            raise ValueError("Аргументы инструмента должны быть JSON-объектом")
        return value

    @staticmethod
    def _required_string(arguments: dict[str, Any], key: str) -> str:
        value = arguments.get(key)
        if not isinstance(value, str) or not value.strip():
            raise ValueError(f"Поле {key} должно быть непустой строкой")
        return value.strip()

