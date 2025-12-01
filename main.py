import asyncio
import logging
import sys

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.fsm.storage.memory import MemoryStorage

from app.config import TELEGRAM_BOT_TOKEN
from app.bot.handlers import basic, task

async def main() -> None:
    storage = MemoryStorage()
    
    default_properties = DefaultBotProperties(parse_mode=ParseMode.HTML)
    bot = Bot(token=TELEGRAM_BOT_TOKEN, default=default_properties)
    
    # Передаем storage в диспетчер
    dp = Dispatcher(storage=storage)
    
    dp.include_router(basic.router)
    dp.include_router(task.router)
    
    # Удаляем все вебхуки и запускаем polling
    await bot.delete_webhook(drop_pending_updates=True)
    await dp.start_polling(bot)


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        stream=sys.stdout,
        format="%(asctime)s - %(levelname)s - %(name)s - %(message)s",
    )
    asyncio.run(main())
