from __future__ import annotations

import asyncio
import logging

from aiogram import Bot, Dispatcher
from dotenv import load_dotenv
from openai import AsyncOpenAI

from app.bot import create_router
from app.config import Settings
from app.database import Database
from app.faq import FAQRepository, load_faq
from app.llm import LLMService
from app.logging_utils import LLMCallLogger, configure_logging
from app.tools import ToolExecutor

logger = logging.getLogger(__name__)


async def run() -> None:
    load_dotenv()
    settings = Settings.from_env()
    database = Database(settings.database_path)
    await database.initialize()

    faq_entries = load_faq(settings.faq_path)
    if not faq_entries:
        raise RuntimeError(f"FAQ contains no valid entries: {settings.faq_path}")
    faq_repository = FAQRepository(database)
    await faq_repository.rebuild(faq_entries)

    bot = Bot(token=settings.telegram_bot_token)
    client = AsyncOpenAI(
        base_url=settings.llm_base_url,
        api_key=settings.llm_api_key,
        timeout=30.0,
    )
    tool_executor = ToolExecutor(database, faq_repository)
    llm_service = LLMService(
        client=client,
        model=settings.llm_model,
        tool_executor=tool_executor,
        call_logger=LLMCallLogger(settings.llm_log_path),
    )
    dispatcher = Dispatcher()
    dispatcher.include_router(create_router(settings, database, llm_service))

    logger.info("Loaded %s FAQ entries; starting polling", len(faq_entries))
    try:
        await dispatcher.start_polling(
            bot,
            allowed_updates=dispatcher.resolve_used_update_types(),
        )
    finally:
        await client.close()
        await bot.session.close()


def main() -> None:
    configure_logging()
    asyncio.run(run())


if __name__ == "__main__":
    main()

