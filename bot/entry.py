"""Входные точки aiogram — единственные хендлеры, которые платкаются в Dispatcher.

Обе части (команды и inline-кнопки) сводятся к единой таблице маршрутов
и единой защите прав администратора.
"""
from __future__ import annotations

import logging
import time

from aiogram import Bot, Dispatcher
from aiogram.fsm.context import FSMContext
from aiogram.types import BotCommand, CallbackQuery, Message

from bot.registry import App, AppContext, RouteArgs, RouterRegistry, SENSITIVE_ROUTES
from bot.routers.wifi_fsm import WifiConfigFSM, wifi_fsm_input

logger = logging.getLogger(__name__)

COMMAND_HELP = "❓ Неизвестная команда. Нажми кнопку 🎮 ниже или /menu"


async def _build_context(bot: Bot, state: FSMContext, app: App, user_id: int) -> AppContext:
    return AppContext(
        bot=bot,
        state=state,
        settings=app.settings,
        registry=app.registry,
        service=app.service,
        user_id=user_id,
    )


async def message_entry(message: Message, bot: Bot, state: FSMContext, app: App) -> None:
    """Вход для сообщений: команды, ввод FSM, подсказка по умолчанию."""
    if message.from_user is None:
        return

    ctx = await _build_context(bot, state, app, message.from_user.id)
    text = (message.text or "").strip()

    # 1) Ввод из FSM (SSID / пароль) обрабатывается до команд.
    if await state.get_state() in {WifiConfigFSM.ssid.state, WifiConfigFSM.password.state}:
        await wifi_fsm_input(message, ctx)
        return

    if text.startswith("/"):
        cmd = text.split()[0][1:].split("@")[0]
        handler = ctx.registry.match_command(cmd)
        if handler is not None:
            await handler(message, ctx, RouteArgs("cmd", cmd, ()))
        else:
            await message.answer(COMMAND_HELP)
        return

    await message.answer(COMMAND_HELP)


async def callback_entry(callback: CallbackQuery, bot: Bot, state: FSMContext, app: App) -> None:
    """Вход для inline-кнопок: разбор c:<area>:<action>[:args] и роутинг."""
    if callback.from_user is None:
        await callback.answer("❓ Не удалось обработать")
        return

    parsed = RouterRegistry.parse_callback(callback.data or "")
    if parsed is None:
        await callback.answer("❓ Некорректная кнопка")
        return

    area, action, args = parsed
    ctx = await _build_context(bot, state, app, callback.from_user.id)
    handler = ctx.registry.match(area, action)
    if handler is None:
        await callback.answer("❓ Неизвестное действие")
        return

    if (area, action) in SENSITIVE_ROUTES and not ctx.is_admin:
        await callback.answer("🔒 Эти действия доступны только администратору", show_alert=True)
        return

    await handler(callback, ctx, RouteArgs(area, action, args))


BOT_COMMANDS: list[BotCommand] = [
    BotCommand(command="/start", description="Запустить бота и открыть меню"),
    BotCommand(command="/menu", description="Открыть главное меню"),
    BotCommand(command="/status", description="Статус роутера"),
    BotCommand(command="/help", description="Помощь и список команд"),
    BotCommand(command="/id", description="Ваш Telegram ID"),
    BotCommand(command="/ping", description="Проверить отклик бота"),
]


async def register_commands(bot: Bot) -> None:
    await bot.set_my_commands(BOT_COMMANDS)
    logger.info("Список команд бота обновлён (%d команд)", len(BOT_COMMANDS))
