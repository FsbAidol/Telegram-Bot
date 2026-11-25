"""Общие утилиты для обработчиков маршрутов."""
from __future__ import annotations

from typing import Any

from aiogram.exceptions import TelegramAPIError
from aiogram.types import InlineKeyboardMarkup, ReplyKeyboardMarkup

MAX_MESSAGE_LINES = 35


async def render(actor: Any, text: str,
                 markup: InlineKeyboardMarkup | ReplyKeyboardMarkup | None = None) -> None:
    """Единая отправка: для callback-кнопки — редактируем исходное сообщение,
     если редактирование невозможно (удалённое сообщение и т.п.) — отвечаем заново.
     Определение типа по duck-typing (CallbackQuery имеет атрибут .message)."""
    if hasattr(actor, "message") and actor.message is not None:
        try:
            await actor.message.edit_text(text, reply_markup=markup)
            return
        except TelegramAPIError:
            pass
        await actor.message.answer(text, reply_markup=markup)
        return
    await actor.answer(text, reply_markup=markup)


def split_messages(text: str, max_lines: int = MAX_MESSAGE_LINES) -> list[str]:
    """Разбивает длинный текст на части по max_lines строк."""
    lines = text.split("\n")
    if len(lines) <= max_lines:
        return [text]
    chunks: list[str] = []
    for i in range(0, len(lines), max_lines):
        chunks.append("\n".join(lines[i:i + max_lines]))
    return chunks
