"""Форматирование текстов сообщений бота (HTML + премиум-эмодзи)."""
from __future__ import annotations

import html
import time
from datetime import datetime, timezone

from bot.keyboards.emoji import Emoji
from bot.services.tplink import ClientDevice, RouterStatus

_CLIENT_ICONS = ["🖥️", "📱", "📺", "🖨️", "🎮", "📦", "💻", "🔊"]


def esc(value: object) -> str:
    return html.escape(str(value), quote=False)


def _fmt_time(ts: float) -> str:
    return datetime.fromtimestamp(ts, tz=timezone.utc).strftime("%H:%M:%S UTC")


def _bar(value: float, vmax: float, width: int = 10) -> str:
    if vmax <= 0:
        filled = 0
    else:
        filled = min(width, int(round(width * value / vmax)))
    return "█" * filled + "░" * (width - filled)


# ---------- Главное меню ----------

def home_text(status: RouterStatus) -> str:
    state = f"{Emoji.CHECK} Онлайн" if status.online else f"{Emoji.CROSS} Офлайн"
    mode = "☁️ Cloud" if status.mode == "cloud" else "🎭 Демо-режим"
    lines = [
        f"{Emoji.SHINE} <b>Управление роутером</b>",
        f"{Emoji.NET} <b>{esc(status.alias)}</b> — {Emoji.DIAMOND} {esc(status.model)}",
        f"{state} · {mode} · {status.total_clients} {Emoji.CLIENTS}",
    ]
    if status.mode == "mock":
        lines.append(
            f"{Emoji.TARGET} Для реального роутера: в .env настройте "
            f"TPLINK_MODE=cloud, TPLINK_USER, TPLINK_PASSWORD"
        )
    return "\n".join(lines)


# ---------- Статус роутера ----------

def status_text(s: RouterStatus) -> str:
    online = f"{Emoji.CHECK} Онлайн" if s.online else f"{Emoji.CROSS} Офлайн"
    lines = [
        f"{Emoji.NET} <b>{esc(s.alias)}</b>",
        f"{Emoji.ROBOT} {esc(s.model)} · {online}",
        "",
        f"{Emoji.CLIENTS} <b>Устройств:</b> {s.total_clients}",
        f"{Emoji.SECURITY} <b>MAC:</b> {esc(s.mac) or '—'}",
        f"{Emoji.SHIELD} <b>Прошивка:</b> {esc(s.firmware)}",
        f"{Emoji.CLOCK} <b>Uptime:</b> {esc(s.uptime)}",
        f"{Emoji.STATS} <b>Загрузка:</b> CPU {esc(s.cpu)} · Память {esc(s.memory)}",
        f"{Emoji.HOME} <b>WAN IP:</b> {esc(s.wan_ip)}",
        "",
        f"{Emoji.WIFI} <b>Сети:</b>",
    ]
    for net in s.networks:
        mark = Emoji.CHECK if net.enabled else Emoji.CROSS
        lines.append(f"{mark} {esc(net.label)} — {esc(net.ssid)} ({net.clients} {Emoji.CLIENTS})")
    lines.append("")
    lines.append(f"{Emoji.CLOCK} Обновлено: {_fmt_time(s.refreshed_at)}")
    return "\n".join(lines)


# ---------- Скорость ----------

def speed_text(s: RouterStatus) -> str:
    lines = [
        f"{Emoji.SPEED} <b>Скорость сети</b>",
        "",
        f"{Emoji.DOWN} <b>Загрузка:</b> {s.download_mbps:.1f} Мбит/с",
        f"{_bar(s.download_mbps, max(s.download_mbps * 1.5, 100))}",
        "",
        f"{Emoji.UP} <b>Отдача:</b> {s.upload_mbps:.1f} Мбит/с",
        f"{_bar(s.upload_mbps, max(s.upload_mbps * 1.5, 50))}",
        "",
        f"{Emoji.CLIENTS} Клиентов: {s.total_clients}",
        f"{Emoji.CLOCK} Обновлено: {_fmt_time(s.refreshed_at)}",
    ]
    return "\n".join(lines)


# ---------- Устройства ----------

def clients_text(clients: list[ClientDevice]) -> str:
    if not clients:
        return f"{Emoji.CLIENTS} Подключённых устройств не найдено"
    lines = [f"{Emoji.DEVICES} <b>Подключённые устройства</b> ({len(clients)})", ""]
    for i, c in enumerate(clients):
        icon = _CLIENT_ICONS[i % len(_CLIENT_ICONS)]
        lines.append(
            f"{icon} {esc(c.name)}\n"
            f"   IP: {esc(c.ip)} · MAC: {esc(c.mac)}\n"
            f"   ↓ {c.download_mbps:.1f} · ↑ {c.upload_mbps:.1f} Мбит/с · {esc(c.band)}"
        )
    return "\n".join(lines)


# ---------- Помощь ----------

HELP_TEXT = (
    f"{Emoji.SHINE} <b>Как работает бот</b>\n\n"
    f"{Emoji.MENU} <b>Главное</b> — краткая сводка роутера\n"
    f"{Emoji.NET} <b>Роутер</b> — полное управление Archer C80:\n"
    f"   📊 Статус, 📡 Устройства, ⚡ Скорость\n"
    f"   🔄 Перезагрузка, 🌐 Радио-сети, ⚙️ SSID/пароль\n"
    f"{Emoji.HELP} <b>Команды:</b> /start /menu /status /id /ping\n\n"
    f"{Emoji.TARGET} Управление изменён состоянием роутера\n"
    f"требует прав администратора (ADMIN_IDS в .env)."
)
