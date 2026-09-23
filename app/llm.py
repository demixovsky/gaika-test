from __future__ import annotations

import json
import logging
from typing import Any, Sequence

from openai import AsyncOpenAI
from openai.types.chat import ChatCompletionMessageParam

from app.database import StoredMessage
from app.logging_utils import LLMCallLogger
from app.tools import TOOL_DEFINITIONS, ToolExecutionContext, ToolExecutor

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = """Ты — сотрудник технической поддержки автосервиса «Гайка».
Отвечай кратко, дружелюбно и по существу.

Для любых фактических вопросов о компании, адресе, графике, услугах, ценах,
записи, сроках, ремонте, запчастях, оплате, гарантии, скидках и правилах сначала
используй search_faq. Не придумывай информацию о компании. Результаты search_faq
являются единственным источником истины.

Если FAQ не содержит точного ответа, честно сообщи об этом и предложи связаться
со специалистом. Создавай заявку только после согласия пользователя либо если
вопрос явно требует человека. Если пользователь прямо просит оператора или
специалиста, не заставляй повторять вопрос и вызови create_ticket.

Не создавай заявку повторно, если она уже создана в текущем контексте.
На приветствия и обычный small talk можно отвечать без search_faq.

Любые вопросы, которые не касаются сервиса, обслуживания автомобилей - вежливо отвечай на них, что с этим ты помочь не сможешь, и попытайся сделать, чтобы пользователь задал вопрос касаемо только тематики сервисов/ремонта/услуг.
"""


class ToolLoopLimitError(RuntimeError):
    pass


class LLMService:
    def __init__(
        self,
        client: AsyncOpenAI,
        model: str,
        tool_executor: ToolExecutor,
        call_logger: LLMCallLogger,
        max_iterations: int = 5,
    ) -> None:
        self.client = client
        self.model = model
        self.tool_executor = tool_executor
        self.call_logger = call_logger
        self.max_iterations = max_iterations

    async def run_conversation(
        self,
        history: Sequence[StoredMessage],
        context: ToolExecutionContext,
    ) -> str:
        messages: list[ChatCompletionMessageParam] = [
            {"role": "system", "content": SYSTEM_PROMPT},
            {
                "role": "system",
                "content": (
                    "Технический контекст текущего пользователя: "
                    f"contact={context.contact}; "
                    f"telegram_user_id={context.telegram_user_id}. "
                    "Используй это значение contact при вызове create_ticket."
                ),
            },
        ]
        messages.extend(
            {"role": item.role, "content": item.content}  # type: ignore[misc]
            for item in history
        )
        ticket_created = False

        for _ in range(self.max_iterations):
            try:
                completion = await self.client.chat.completions.create(
                    model=self.model,
                    messages=messages,
                    tools=TOOL_DEFINITIONS,  # type: ignore[arg-type]
                    tool_choice="auto",
                )
            except Exception as exc:
                await self.call_logger.write(
                    model=self.model,
                    chat_id=context.chat_id,
                    error=type(exc).__name__,
                )
                raise

            response_message = completion.choices[0].message
            calls_for_log: list[dict[str, Any]] = []
            for call in response_message.tool_calls or []:
                raw_arguments = call.function.arguments
                try:
                    parsed = ToolExecutor.parse_arguments(raw_arguments)
                except ValueError:
                    parsed = {"_malformed": raw_arguments}
                calls_for_log.append(
                    {"name": call.function.name, "arguments": parsed}
                )
            usage = completion.usage
            await self.call_logger.write(
                model=self.model,
                chat_id=context.chat_id,
                prompt_tokens=usage.prompt_tokens if usage else 0,
                completion_tokens=usage.completion_tokens if usage else 0,
                total_tokens=usage.total_tokens if usage else 0,
                tools_called=calls_for_log,
            )

            if not response_message.tool_calls:
                content = response_message.content
                return content.strip() if content else "Не удалось сформировать ответ."

            messages.append(response_message.model_dump(exclude_none=True))  # type: ignore[arg-type]
            for call in response_message.tool_calls:
                try:
                    arguments = ToolExecutor.parse_arguments(call.function.arguments)
                    result = await self.tool_executor.execute(
                        call.function.name,
                        arguments,
                        context,
                        ticket_created=ticket_created,
                    )
                    if call.function.name == "create_ticket" and result.get("created"):
                        ticket_created = True
                except ValueError as exc:
                    result = {"error": str(exc)}
                except Exception:
                    logger.exception("Tool %s failed", call.function.name)
                    result = {"error": "Внутренняя ошибка при выполнении инструмента."}
                messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": call.id,
                        "content": json.dumps(result, ensure_ascii=False),
                    }
                )
        raise ToolLoopLimitError("LLM tool loop exceeded the iteration limit")
