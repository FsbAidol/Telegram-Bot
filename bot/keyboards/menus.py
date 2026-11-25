"""Inline-клавиатуры бота: премиум-эмодзи в каждой кнопке."""
from __future__ import annotations

from aiogram.types import (
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    KeyboardButton,
    ReplyKeyboardMarkup,
    ReplyKeyboardRemove,
    WebAppInfo,
)
from aiogram.utils.keyboard import InlineKeyboardBuilder

from bot.keyboards.emoji import Emoji
from bot.services.tplink import RouterStatus

# ---------- Шорткат для сборки клавиатур ----------

def _kb(rows: list[list[InlineKeyboardButton | tuple[str, str]]]) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    for row in rows:
        cells: list[InlineKeyboardButton] = []
        for cell in row:
            if isinstance(cell, InlineKeyboardButton):
                cells.append(cell)
            else:
                text, data = cell
                cells.append(InlineKeyboardButton(text=text, callback_data=data))
        builder.row(*cells)
    return builder.as_markup()


# ---------- Главное меню ----------

def main_menu(mini_app_url: str = "") -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton | tuple[str, str]]] = [
        [(f"{Emoji.MENU} Главное", "c:menu:home")],
        [(f"{Emoji.NET} Роутер", "c:router:home")],
        [(f"{Emoji.STATS} Скорость", "c:router:speed")],
        [(f"{Emoji.HELP} Помощь", "c:menu:help")],
    ]
    # Telegram требует HTTPS для Web App: при http-URL (например localhost)
    # кнопку не рендерим — бот не должен падать на некорректной ссылке.
    if mini_app_url.startswith("https://"):
        rows.append([
            InlineKeyboardButton(
                text=f"{Emoji.SHINE} 🎨 Эмодзи-студия",
                web_app=WebAppInfo(url=mini_app_url),
            )
        ])
    return _kb(rows)


MAIN_MENU = main_menu()


# ---------- Меню роутера (динамическое: ✅/❌ по текущим сетям) ----------

def _net_button(key: str, label: str, enabled: bool) -> tuple[str, str]:
    mark = Emoji.CHECK if enabled else Emoji.CROSS
    return (f"{mark} {label}", f"c:router:wifi:{key}:toggle")


def build_router_menu(status: RouterStatus) -> InlineKeyboardMarkup:
    networks = {net.key: net for net in status.networks}
    n24 = networks.get("24")
    n5 = networks.get("5")
    ng = networks.get("guest")
    return _kb(
        [
            [
                (f"{Emoji.STATS} Статус", "c:router:status"),
                (f"{Emoji.DEVICES} Устройства", "c:router:clients"),
            ],
            [
                (f"{Emoji.SPEED} Скорость", "c:router:speed"),
                (f"{Emoji.REBOOT} Перезагрузка", "c:router:reboot"),
            ],
            [
                _net_button("24", "Wi-Fi 2.4 ГГц", n24.enabled if n24 else False),
                _net_button("5", "Wi-Fi 5 ГГц", n5.enabled if n5 else False),
            ],
            [
                _net_button("guest", "Guest Wi-Fi", ng.enabled if ng else False),
                (f"{Emoji.SETTINGS} Сеть (SSID/пароль)", "c:router:net"),
            ],
            [(f"{Emoji.BACK} Назад", "c:menu:home")],
        ]
    )


# ---------- Подтверждение перезагрузки ----------

REBOOT_CONFIRM = _kb(
    [
        [(f"{Emoji.CHECK} Подтвердить", "c:router:reboot_confirm")],
        [(f"{Emoji.CLOSE} Отмена", "c:menu:home")],
    ]
)


# ---------- Выбор диапазона сети при смене SSID/пароля ----------

BAND_CHOICE = _kb(
    [
        [(f"{Emoji.NET} 2.4 ГГц", "c:router:net_band:24")],
        [(f"{Emoji.BOLT} 5 ГГц", "c:router:net_band:5")],
        [(f"{Emoji.GUEST} Guest", "c:router:net_band:guest")],
        [(f"{Emoji.BACK} Назад", "c:router:home")],
    ]
)


# ---------- Ответная клавиатура (отмена ввода FSM) ----------

CANCEL_TEXT = "❌ Отмена"
CANCEL_REPLY = ReplyKeyboardMarkup(
    keyboard=[[KeyboardButton(text=CANCEL_TEXT)]],
    one_time_keyboard=True,
    resize_keyboard=True,
)
REMOVE_REPLY = ReplyKeyboardRemove()
