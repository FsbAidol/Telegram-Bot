"""Раздел команд: /start /status /id /ping."""
from __future__ import annotations

import time

from bot.keyboards.emoji import Emoji
from bot.keyboards.menus import MAIN_MENU
from bot.registry import AppContext, RouteArgs, RouterRegistry
from bot.render import home_text, status_text
from bot.routers._common import render


def register(registry: RouterRegistry) -> None:
    @registry.command("start")
    async def cmd_start(actor, ctx: AppContext, args: RouteArgs) -> None:
        status = await ctx.service.get_status()
        await render(actor, f"{Emoji.SHINE} <b>Добро пожаловать!</b>\n" + home_text(status), MAIN_MENU)

    @registry.command("status")
    async def cmd_status(actor, ctx: AppContext, args: RouteArgs) -> None:
        status = await ctx.service.get_status(force=True)
        await render(actor, status_text(status))

    @registry.command("id")
    async def cmd_id(actor, ctx: AppContext, args: RouteArgs) -> None:
        await render(actor, f"{Emoji.TARGET} <b>Ваш ID:</b> {ctx.user_id}")

    @registry.command("ping")
    async def cmd_ping(actor, ctx: AppContext, args: RouteArgs) -> None:
        t0 = time.monotonic()
        await ctx.service.get_status()
        elapsed = (time.monotonic() - t0) * 1000
        await render(actor, f"{Emoji.PING} <b>Pong!</b> {elapsed:.0f} мс")
