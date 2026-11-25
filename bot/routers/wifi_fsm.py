"""FSM-состояния для пошагового ввода SSID и пароля сети."""
from __future__ import annotations

from aiogram.fsm.state import State, StatesGroup
from aiogram.types import Message

from bot.keyboards.emoji import Emoji
from bot.keyboards.menus import CANCEL_REPLY, CANCEL_TEXT, REMOVE_REPLY
from bot.registry import AppContext
from bot.routers._common import render
from bot.services.tplink import RouterUnavailable


class WifiConfigFSM(StatesGroup):
    band = State()     # "24" | "5" | "guest"
    ssid = State()     # ожидание имени сети
    password = State()  # ожидание пароля


async def wifi_fsm_input(message: Message, ctx: AppContext) -> None:
    """Обрабатывает ввод пользователя в середине FSM (из message_entry)."""
    state = ctx.state

    # Отмена с ответной клавиатуры.
    if (message.text or "").strip() == CANCEL_TEXT:
        await state.clear_state()
        await message.answer(f"{Emoji.CLOSE} Настройка сети отменена", reply_markup=REMOVE_REPLY)
        return

    current = await state.get_state()

    if current == WifiConfigFSM.ssid.state:
        ssid = (message.text or "").strip()
        if not ssid:
            await message.answer(f"{Emoji.CLOSE} Имя сети пустое. Введите SSID:")
            return
        await state.update_data(ssid=ssid)
        await state.set_state(WifiConfigFSM.password.state)
        await message.answer(
            f"{Emoji.SAVE} Введите новый <b>пароль</b> Wi-Fi.\n"
            f"{Emoji.CLOSE} Нажмите «Отмена», чтобы выйти.",
            reply_markup=CANCEL_REPLY,
        )
        return

    if current == WifiConfigFSM.password.state:
        password = message.text or ""
        data = await state.get_data()
        band = str(data.get("band", "24"))
        await state.clear_state()

        try:
            await ctx.service.set_wifi_credentials(band, str(data.get("ssid", "")), password)
        except RouterUnavailable as exc:
            await message.answer(f"{Emoji.CROSS} <b>Не удалось:</b> {exc}", reply_markup=REMOVE_REPLY)
            return

        await render(
            message,
            f"{Emoji.CHECK} <b>Сеть обновлена!</b>\n"
            f"Диапазон {band}: SSID <b>{data.get('ssid')}</b>",
            reply_markup=REMOVE_REPLY,
        )
