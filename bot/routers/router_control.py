"""Раздел «Роутер»: управление TP-Link Archer C80 через inline-кнопки."""
from __future__ import annotations

from bot.keyboards.menus import (
    BAND_CHOICE,
    CANCEL_REPLY,
    REBOOT_CONFIRM,
    build_router_menu,
)
from bot.keyboards.emoji import Emoji
from bot.registry import AppContext, RouteArgs, RouterRegistry
from bot.routers.wifi_fsm import WifiConfigFSM
from bot.render import (
    clients_text,
    esc,
    home_text,
    speed_text,
    status_text,
)
from bot.routers._common import render, split_messages
from bot.services.tplink import RouterUnavailable


def register(registry: RouterRegistry) -> None:
    @registry.route("router", "home")
    async def router_home(actor, ctx: AppContext, args: RouteArgs) -> None:
        status = await ctx.service.get_status()
        await render(actor, home_text(status), build_router_menu(status))

    @registry.route("router", "status")
    async def router_status(actor, ctx: AppContext, args: RouteArgs) -> None:
        status = await ctx.service.get_status(force=True)
        await render(actor, status_text(status))

    @registry.route("router", "clients")
    async def router_clients(actor, ctx: AppContext, args: RouteArgs) -> None:
        await ctx.service.get_status()
        clients = await ctx.service.get_clients()
        chunks = split_messages(clients_text(clients))
        await render(actor, chunks[0])
        target = actor.message if hasattr(actor, "message") else actor
        for chunk in chunks[1:]:
            await target.answer(chunk)

    @registry.route("router", "speed")
    async def router_speed(actor, ctx: AppContext, args: RouteArgs) -> None:
        status = await ctx.service.get_status(force=True)
        await render(actor, speed_text(status))

    @registry.route("router", "wifi")
    async def router_wifi_toggle(actor, ctx: AppContext, route: RouteArgs) -> None:
        """Смена радио-диапазона: route.args = (band, "toggle"), band: 24 | 5 | guest."""
        band = route.args[0] if route.args else "24"
        status = await ctx.service.get_status()
        net = status.network(band)
        enable = not (net.enabled if net else False)

        await ctx.service.set_wifi_enabled(band, enable)
        new_status = await ctx.service.get_status(force=True)
        await render(actor, home_text(new_status), build_router_menu(new_status))

    @registry.route("router", "reboot")
    async def router_reboot(actor, ctx: AppContext, args: RouteArgs) -> None:
        await render(actor, f"{Emoji.REBOOT} <b>Перезагрузить роутер?</b>\n"
                            "Сеть ненадолго отключится.", REBOOT_CONFIRM)

    @registry.route("router", "reboot_confirm")
    async def router_reboot_confirm(actor, ctx: AppContext, args: RouteArgs) -> None:
        await render(actor, f"{Emoji.LAUNCH} Запускаю перезагрузку…")
        try:
            await ctx.service.reboot()
            message = (
                f"{Emoji.CHECK} <b>Готово!</b> Роутер перезагружается — "
                "соединитесь через пару минут."
            )
        except RouterUnavailable as exc:
            message = f"{Emoji.CROSS} <b>Не удалось:</b> {exc}"
        await render(actor, message)

    @registry.route("router", "net")
    async def router_net_config(actor, ctx: AppContext, args: RouteArgs) -> None:
        """Запуск FSM смены SSID/пароля: выбираем диапазон."""
        await ctx.state.set_state(WifiConfigFSM.band.state)
        await render(
            actor,
            f"{Emoji.SETTINGS} <b>Смена сети Wi-Fi</b>\n"
            f"Выберите диапазон:",
            BAND_CHOICE,
        )

    @registry.route("router", "net_band")
    async def router_net_band(actor, ctx: AppContext, route: RouteArgs) -> None:
        """Шаг FSM: диапазон выбран — просим SSID."""
        band = route.args[0] if route.args else "24"
        await ctx.state.update_data(band=band)
        await ctx.state.set_state(WifiConfigFSM.ssid.state)
        await render(
            actor,
            f"{Emoji.NET} <b>Диапазон:</b> {band}\n"
            f"Введите новое имя сети (SSID).\n"
            f"{Emoji.CLOSE} Нажмите «Отмена», чтобы выйти.",
            CANCEL_REPLY,
        )

    @registry.route("router", "net_cancel")
    async def router_net_cancel(actor, ctx: AppContext, args: RouteArgs) -> None:
        await ctx.state.clear_state()
        await render(actor, f"{Emoji.CLOSE} Настройка сети отменена")
