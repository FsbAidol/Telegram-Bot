"""Центральная таблица маршрутов бота.

Все обработчики регистрируются через декораторы:
    @registry.route("router", "status")   — inline-кнопка
    @registry.command("start")            — команда /start

aiogram ставит в Dispatcher только две входные точки (entry-хендлеры):
    message_entry   — командные сообщения и ввод FSM
    callback_entry  — inline-кнопки

entry-хендлер разбирает входные данные и вызывает нужный маршрут из таблицы.
Это даёт единую точку входа, единую обработку ошибок и простую расширяемость:
новый раздел — это новый файл с декораторами и регистрация в build_registry().
"""
from __future__ import annotations

import functools
import logging
from collections.abc import Callable, Coroutine
from dataclasses import dataclass
from typing import Any

logger = logging.getLogger(__name__)

RouteHandler = Callable[[Any, "AppContext", "RouteArgs"], Coroutine[Any, Any, Any]]

# Маршруты, требующие прав администратора (изменение состояния роутера).
SENSITIVE_ROUTES: frozenset[tuple[str, str]] = frozenset(
    {
        ("router", "reboot"),
        ("router", "reboot_confirm"),
        ("router", "wifi"),
        ("router", "net"),
        ("router", "net_band"),
        ("router", "net_cancel"),
    }
)


@dataclass(frozen=True)
class RouteArgs:
    """Параметры маршрута: area:action:arg1:arg2..."""

    area: str
    action: str
    args: tuple[str, ...]


@dataclass
class App:
    """Граф приложения — раздаётся хендлерам через Dispatcher(app=...)."""

    settings: Any
    registry: "RouterRegistry"
    service: Any


@dataclass
class AppContext:
    """Контекст, который получает каждый маршрут-обработчик."""

    bot: Any
    state: Any
    settings: Any
    registry: "RouterRegistry"
    service: Any
    user_id: int

    @property
    def is_admin(self) -> bool:
        return self.settings.is_admin(self.user_id)


def handled(fn: RouteHandler) -> RouteHandler:
    """Обёртка обработчика: единая точка записи ошибок в лог + уведомление пользователя."""

    @functools.wraps(fn)
    async def wrapper(actor: Any, ctx: AppContext, args: RouteArgs) -> Any:
        try:
            return await fn(actor, ctx, args)
        except Exception:
            route = f"{args.area}:{args.action}" if args else "unknown"
            logger.exception("Ошибка в маршруте %s (user=%s)", route, ctx.user_id)
            await _notify_error(actor)
            return None

    return wrapper


async def _notify_error(actor: Any) -> None:
    try:
        text = "⚠️ Внутренняя ошибка. Попробуйте позже."
        if hasattr(actor, "message") and actor.message is not None:
            await actor.message.answer(text)
        else:
            await actor.answer(text)
    except Exception:
        logger.debug("Не удалось уведомить пользователя об ошибке", exc_info=True)


class RouterRegistry:
    """Таблица маршрутов: area+action -> обработчик и команда -> обработчик."""

    def __init__(self) -> None:
        self._routes: dict[tuple[str, str], RouteHandler] = {}
        self._commands: dict[str, RouteHandler] = {}

    def route(self, area: str, action: str) -> Callable[[RouteHandler], RouteHandler]:
        def decorator(fn: RouteHandler) -> RouteHandler:
            key = (area, action)
            if key in self._routes:
                raise ValueError(f"Дубликат маршрута {area}:{action}")
            self._routes[key] = handled(fn)
            return fn

        return decorator

    def command(self, name: str) -> Callable[[RouteHandler], RouteHandler]:
        def decorator(fn: RouteHandler) -> RouteHandler:
            name_clean = name.lstrip("/")
            if name_clean in self._commands:
                raise ValueError(f"Дубликат команды /{name_clean}")
            self._commands[name_clean] = handled(fn)
            return fn

        return decorator

    def match(self, area: str, action: str) -> RouteHandler | None:
        return self._routes.get((area, action))

    def match_command(self, name: str) -> RouteHandler | None:
        return self._commands.get(name.lstrip("/"))

    @property
    def routes(self) -> int:
        return len(self._routes) + len(self._commands)

    @staticmethod
    def parse_callback(data: str) -> tuple[str, str, tuple[str, ...]] | None:
        """Разбор callback_data по шаблону: c:<area>:<action>[:arg:arg...]"""
        if not data or not data.startswith("c:"):
            return None
        parts = data.split(":")
        if len(parts) < 3:
            return None
        return parts[1], parts[2], tuple(parts[3:])
