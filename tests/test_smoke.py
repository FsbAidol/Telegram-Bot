"""Смоук-тест: роутинг, клавиатуры и цикл управления роутером (без сети и Telegram API).

Запуск: python -m unittest discover tests -v
"""
from __future__ import annotations

import asyncio
import unittest

from aiogram.types import InlineKeyboardMarkup

from bot.config import Settings
from bot.keyboards.menus import MAIN_MENU, build_router_menu, main_menu
from bot.registry import AppContext, RouteArgs, RouterRegistry
from bot.routers import commands, menu, router_control
from bot.services.tplink import MockRouter, RouterService


def make_settings(**overrides) -> Settings:
    base = dict(bot_token="000:test")
    base.update(overrides)
    return Settings(**base)


class FakeMessage:
    """Замена aiogram.Message для тестов (с редактированием)."""

    def __init__(self) -> None:
        self.sent: list[tuple[str, object]] = []
        self.edited: list[tuple[str, object]] = []

    async def answer(self, text: str, reply_markup=None) -> None:
        self.sent.append((text, reply_markup))

    async def edit_text(self, text: str, reply_markup=None) -> None:
        self.edited.append((text, reply_markup))


class FakeCallback:
    """Замена aiogram.CallbackQuery для тестов."""

    def __init__(self) -> None:
        self.message = FakeMessage()
        self.answered: list[str] = []

    async def answer(self, text: str = "", show_alert: bool = False) -> None:
        self.answered.append(text)


class FakeState:
    def __init__(self) -> None:
        self._state = None
        self._data: dict = {}

    async def get_state(self):
        return self._state

    async def set_state(self, state) -> None:
        self._state = state

    async def update_data(self, **data) -> None:
        self._data.update(data)

    async def get_data(self) -> dict:
        return dict(self._data)

    async def clear_state(self) -> None:
        self._state = None
        self._data = {}


def make_context(service: RouterService, registry: RouterRegistry) -> AppContext:
    return AppContext(
        bot=None,
        state=FakeState(),
        settings=make_settings(admin_ids=frozenset({1})),
        registry=registry,
        service=service,
        user_id=1,
    )


def build_registry() -> RouterRegistry:
    registry = RouterRegistry()
    menu.register(registry)
    router_control.register(registry)
    commands.register(registry)
    return registry


class TestRegistry(unittest.IsolatedAsyncioTestCase):
    def test_routes_registered(self) -> None:
        registry = build_registry()
        for area, action in [
            ("menu", "home"), ("menu", "help"),
            ("router", "home"), ("router", "status"), ("router", "clients"),
            ("router", "speed"), ("router", "wifi"), ("router", "reboot"),
            ("router", "reboot_confirm"), ("router", "net"), ("router", "net_band"),
            ("router", "net_cancel"),
        ]:
            self.assertIsNotNone(registry.match(area, action), f"{area}:{action}")
        for cmd in ["start", "menu", "help", "status", "id", "ping"]:
            self.assertIsNotNone(registry.match_command(cmd), f"/{cmd}")

    def test_duplicate_route_rejected(self) -> None:
        registry = RouterRegistry()

        @registry.route("x", "y")
        async def h1(actor, ctx, args):
            pass

        with self.assertRaises(ValueError):
            @registry.route("x", "y")
            async def h2(actor, ctx, args):
                pass

    def test_parse_callback(self) -> None:
        self.assertEqual(
            RouterRegistry.parse_callback("c:router:wifi:24:toggle"),
            ("router", "wifi", ("24", "toggle")),
        )
        self.assertIsNone(RouterRegistry.parse_callback("bad"))
        self.assertIsNone(RouterRegistry.parse_callback("c:only"))


class TestKeyboards(unittest.IsolatedAsyncioTestCase):
    def test_main_menu_buttons(self) -> None:
        markup: InlineKeyboardMarkup = MAIN_MENU
        datas = [btn.callback_data for row in markup.inline_keyboard for btn in row]
        self.assertIn("c:menu:home", datas)
        self.assertIn("c:router:home", datas)
        self.assertTrue(all(btn.text.startswith(("🎮", "📶", "📊", "❓"))
                            for row in markup.inline_keyboard for btn in row))

    def test_main_menu_with_web_app(self) -> None:
        from aiogram.types import WebAppInfo
        markup = main_menu("https://example.org/mini-app")
        webapp_buttons = [
            btn for row in markup.inline_keyboard for btn in row
            if btn.web_app is not None
        ]
        self.assertEqual(len(webapp_buttons), 1)
        self.assertEqual(webapp_buttons[0].web_app.url, "https://example.org/mini-app")
        self.assertIn("🎨", webapp_buttons[0].text)

    def test_main_menu_http_url_hides_web_app(self) -> None:
        # Telegram не принимает http:// WebApp-URL — кнопка не должна рендериться
        for url in ("", "http://localhost:8080"):
            markup = main_menu(url)
            webapp_buttons = [
                btn for row in markup.inline_keyboard for btn in row
                if btn.web_app is not None
            ]
            self.assertEqual(webapp_buttons, [], url)

    def test_router_menu_dynamic(self) -> None:
        mock = MockRouter()

        async def status():
            return await mock.get_status()

        status = asyncio.get_event_loop().run_until_complete(status())
        markup = build_router_menu(status)
        texts = [btn.text for row in markup.inline_keyboard for btn in row]
        # сетям соответствуют ✅/❌ в зависимости от состояния
        guest_btn = [t for t in texts if "Guest" in t][0]
        self.assertTrue(guest_btn.startswith("❌"), guest_btn)
        self.assertIn("✅ Wi-Fi 2.4 ГГц", texts)


class TestRouterServiceMock(unittest.IsolatedAsyncioTestCase):
    def test_full_cycle(self) -> None:
        async def scenario() -> None:
            service = RouterService(make_settings(tplink_mode="mock"))
            self.assertEqual(service.mode, "mock")

            status = await service.get_status()
            self.assertTrue(status.online)
            self.assertEqual(status.total_clients, 5)
            self.assertTrue(status.network("24").enabled)

            # Переключаем Guest Wi-Fi
            await service.set_wifi_enabled("guest", True)
            status2 = await service.get_status(force=True)
            self.assertTrue(status2.network("guest").enabled)

            # Смена SSID
            await service.set_wifi_credentials("5", "New-5G", "secret123")
            status3 = await service.get_status(force=True)
            self.assertEqual(status3.network("5").ssid, "New-5G")

            # Клиенты
            clients = await service.get_clients()
            self.assertEqual(len(clients), 5)
            self.assertTrue(all(c.name for c in clients))

            # Перезагрузка
            await service.reboot()

        asyncio.get_event_loop().run_until_complete(scenario())

    def test_cloud_falls_back_to_mock(self) -> None:
        service = RouterService(make_settings(tplink_mode="cloud"))
        self.assertEqual(service.mode, "mock")  # без данных аккаунта — mock


class TestHandlers(unittest.IsolatedAsyncioTestCase):
    def test_callback_flow(self) -> None:
        async def scenario() -> None:
            registry = build_registry()
            service = RouterService(make_settings(tplink_mode="mock"))
            ctx = make_context(service, registry)
            cb = FakeCallback()

            # Открываем меню роутера
            handler = registry.match("router", "home")
            await handler(cb, ctx, RouteArgs("router", "home", ()))
            text, markup = cb.message.edited[-1]
            self.assertIn("Архив-C80", text)
            self.assertIsNotNone(markup)

            # Переключаем Guest Wi-Fi через маршрут wifi — кнопка перерисовывается с ✅
            handler = registry.match("router", "wifi")
            await handler(cb, ctx, RouteArgs("router", "wifi", ("guest", "toggle")))
            text, markup = cb.message.edited[-1]
            btn_texts = [btn.text for row in markup.inline_keyboard for btn in row]
            self.assertIn("✅ Guest Wi-Fi", btn_texts)

            # Перезагрузка с подтверждением
            handler = registry.match("router", "reboot_confirm")
            await handler(cb, ctx, RouteArgs("router", "reboot_confirm", ()))
            self.assertIn("Готово", cb.message.edited[-1][0])

        asyncio.get_event_loop().run_until_complete(scenario())

    def test_command_flow(self) -> None:
        async def scenario() -> None:
            registry = build_registry()
            service = RouterService(make_settings(tplink_mode="mock"))
            ctx = make_context(service, registry)
            msg = FakeMessage()

            handler = registry.match_command("start")
            await handler(msg, ctx, RouteArgs("cmd", "start", ()))
            self.assertIn("Добро пожаловать", msg.sent[0][0])

            handler = registry.match_command("ping")
            await handler(msg, ctx, RouteArgs("cmd", "ping", ()))
            self.assertIn("Pong", msg.sent[-1][0])

        asyncio.get_event_loop().run_until_complete(scenario())

    def test_error_handling(self) -> None:
        async def scenario() -> None:
            registry = RouterRegistry()

            @registry.route("bad", "boom")
            async def boom(actor, ctx, args):
                raise RuntimeError("kaboom")

            service = RouterService(make_settings(tplink_mode="mock"))
            ctx = make_context(service, registry)
            cb = FakeCallback()
            await registry.match("bad", "boom")(cb, ctx, RouteArgs("bad", "boom", ()))
            # ошибка не упала, пользователь уведомлен
            self.assertIn("Внутренняя ошибка", cb.message.sent[-1][0])

        asyncio.get_event_loop().run_until_complete(scenario())


if __name__ == "__main__":
    unittest.main()
