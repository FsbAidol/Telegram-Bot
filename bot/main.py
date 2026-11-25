"""Точка запуска: сборка Bot, Dispatcher и центральной таблицы маршрутов."""
from __future__ import annotations

import asyncio
import logging
import sys
from pathlib import Path

from aiogram import Bot, Dispatcher
from aiogram.client.bot import DefaultBotProperties

from bot.config import Settings
from bot.entry import callback_entry, message_entry, register_commands
from bot.registry import App, RouterRegistry
from bot.routers import commands, menu, router_control
from bot.services.tplink import RouterService

logger = logging.getLogger(__name__)


def build_registry() -> RouterRegistry:
    """Собирает единую таблицу маршрутов из всех разделов."""
    registry = RouterRegistry()
    menu.register(registry)
    router_control.register(registry)
    commands.register(registry)
    logger.info("Таблица маршрутов готова: %d маршрутов", registry.routes)
    return registry


async def setup_logging() -> None:
    Path("logs").mkdir(exist_ok=True)
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)-8s %(name)s: %(message)s",
        handlers=[
            logging.StreamHandler(sys.stdout),
            logging.FileHandler("logs/bot.log", encoding="utf-8"),
        ],
    )


async def _log_message(handler, message, data) -> None:
    text = (message.text or message.caption or "").strip()
    if text:
        logger.info("📨 Сообщение от %s: %s", message.from_user.id if message.from_user else "?", text[:120])
    await handler(message, data)


async def _log_callback(handler, callback, data) -> None:
    logger.info("🖱️ Кнопка от %s: %s", callback.from_user.id if callback.from_user else "?", callback.data)
    await handler(callback, data)


async def create_dispatcher(app: App) -> Dispatcher:
    # kwargs конструктора Dispatcher раздаются хендлерам по имени — app попадает в entry.
    dp = Dispatcher(app=app)
    dp.message.outer_middleware(_log_message)
    dp.callback_query.outer_middleware(_log_callback)
    dp.message.register(message_entry)
    dp.callback_query.register(callback_entry)
    return dp


async def start_stats_worker(app: App) -> None:
    """Регулярное обновление кэша статуса роутера в фоне."""
    while True:
        await asyncio.sleep(app.settings.stats_interval)
        try:
            await app.service.get_status(force=True)
            logger.info("🔄 Статус роутера обновлён (%s)", app.service.mode)
        except Exception:
            logger.warning("Не удалось обновить статус роутера", exc_info=True)


async def run() -> None:
    settings = Settings.from_env()
    await setup_logging()

    app = App(
        settings=settings,
        registry=build_registry(),
        service=RouterService(settings),
    )
    logger.info("Запуск бота (режим роутера: %s — %s)", app.service.mode, app.service.mode_reason())

    bot = Bot(
        token=settings.bot_token,
        default=DefaultBotProperties(parse_mode="HTML"),
    )
    dp = await create_dispatcher(app)

    async with bot:
        await register_commands(bot)
        stats_task = asyncio.create_task(start_stats_worker(app))
        try:
            await dp.start_polling(bot)
        finally:
            stats_task.cancel()


if __name__ == "__main__":
    asyncio.run(run())
