import asyncio
import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from app.llm import LLMService, ToolLoopLimitError
from app.logging_utils import LLMCallLogger
from app.tools import ToolExecutionContext


class FakeMessage:
    def __init__(self, content: str | None = None, tool_calls: list | None = None) -> None:
        self.content = content
        self.tool_calls = tool_calls

    def model_dump(self, **_: object) -> dict:
        result: dict = {"role": "assistant", "content": self.content}
        if self.tool_calls:
            result["tool_calls"] = [
                {
                    "id": call.id,
                    "type": "function",
                    "function": {
                        "name": call.function.name,
                        "arguments": call.function.arguments,
                    },
                }
                for call in self.tool_calls
            ]
        return result


def completion(message: FakeMessage):
    usage = SimpleNamespace(prompt_tokens=10, completion_tokens=4, total_tokens=14)
    return SimpleNamespace(choices=[SimpleNamespace(message=message)], usage=usage)


def tool_call(call_id: str, name: str, arguments: str):
    return SimpleNamespace(
        id=call_id,
        function=SimpleNamespace(name=name, arguments=arguments),
    )


def context() -> ToolExecutionContext:
    return ToolExecutionContext(1, 2, "@client", 3, AsyncMock())


async def test_tool_loop_executes_multiple_calls_then_returns_answer() -> None:
    calls = [
        tool_call("a", "search_faq", '{"query":"шины"}'),
        tool_call("b", "search_faq", '{"query":"гарантия"}'),
    ]
    create = AsyncMock(
        side_effect=[completion(FakeMessage(tool_calls=calls)), completion(FakeMessage("Ответ"))]
    )
    client = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create)))
    executor = AsyncMock()
    executor.execute.return_value = {"results": []}
    call_logger = AsyncMock()
    service = LLMService(client, "model", executor, call_logger)

    answer = await service.run_conversation([], context())

    assert answer == "Ответ"
    assert executor.execute.await_count == 2
    assert create.await_count == 2
    assert call_logger.write.await_count == 2


async def test_malformed_arguments_return_tool_error_and_continue() -> None:
    call = tool_call("a", "search_faq", "{broken")
    create = AsyncMock(
        side_effect=[completion(FakeMessage(tool_calls=[call])), completion(FakeMessage("Готово"))]
    )
    client = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create)))
    executor = AsyncMock()
    service = LLMService(client, "model", executor, AsyncMock())

    assert await service.run_conversation([], context()) == "Готово"
    executor.execute.assert_not_awaited()
    second_messages = create.await_args_list[1].kwargs["messages"]
    assert "некорректный JSON" in second_messages[-1]["content"]


async def test_tool_loop_limit() -> None:
    call = tool_call("a", "search_faq", '{"query":"шины"}')
    create = AsyncMock(return_value=completion(FakeMessage(tool_calls=[call])))
    client = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create)))
    executor = AsyncMock()
    executor.execute.return_value = {"results": []}
    service = LLMService(client, "model", executor, AsyncMock(), max_iterations=2)
    with pytest.raises(ToolLoopLimitError):
        await service.run_conversation([], context())
    assert create.await_count == 2


async def test_jsonl_logger_writes_valid_records_concurrently(tmp_path: Path) -> None:
    path = tmp_path / "calls.jsonl"
    logger = LLMCallLogger(path)
    await asyncio.gather(
        *[
            logger.write(model="model", chat_id=index, tools_called=[])
            for index in range(10)
        ]
    )
    records = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]
    assert len(records) == 10
    assert {record["chat_id"] for record in records} == set(range(10))
