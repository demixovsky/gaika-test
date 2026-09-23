from __future__ import annotations

import asyncio
import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def configure_logging() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )


class LLMCallLogger:
    def __init__(self, path: Path) -> None:
        self.path = path
        self._lock = asyncio.Lock()

    async def write(
        self,
        *,
        model: str,
        chat_id: int,
        prompt_tokens: int = 0,
        completion_tokens: int = 0,
        total_tokens: int = 0,
        tools_called: list[dict[str, Any]] | None = None,
        error: str | None = None,
    ) -> None:
        record: dict[str, Any] = {
            "time": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
            "model": model,
            "chat_id": chat_id,
            "prompt_tokens": prompt_tokens,
            "completion_tokens": completion_tokens,
            "total_tokens": total_tokens,
            "tools_called": tools_called or [],
        }
        if error:
            record["error"] = error
        line = json.dumps(record, ensure_ascii=False, separators=(",", ":")) + "\n"
        async with self._lock:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            await asyncio.to_thread(self._append, line)

    def _append(self, line: str) -> None:
        with self.path.open("a", encoding="utf-8") as file:
            file.write(line)
            file.flush()

