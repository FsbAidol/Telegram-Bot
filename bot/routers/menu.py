"""Раздел «Меню»: главное меню и помощь."""
from __future__ import annotations

from bot.keyboards.menus import MAIN_MENU, main_menu
from bot.registry import AppContext, RouteArgs, RouterRegistry
from bot.render import HELP_TEXT, home_text
from bot.routers._common import render


def register(registry: RouterRegistry) -> None:
    @registry.route("menu", "home")
    async def menu_home(actor, ctx: AppContext, args: RouteArgs) -> None:
        status = await ctx.service.get_status()
        await render(actor, home_text(status), main_menu(ctx.settings.mini_app_url))

    @registry.route("menu", "help")
    async def menu_help(actor, ctx: AppContext, args: RouteArgs) -> None:
        await render(actor, HELP_TEXT, MAIN_MENU)

    @registry.command("menu")
    async def cmd_menu(actor, ctx: AppContext, args: RouteArgs) -> None:
        await menu_home(actor, ctx, args)

    @registry.command("help")
    async def cmd_help(actor, ctx: AppContext, args: RouteArgs) -> None:
        await menu_help(actor, ctx, args)
