"""Конфигурация бота — всё из переменных окружения (.env)."""
from __future__ import annotations

import os
from dataclasses import dataclass

from dotenv import load_dotenv

load_dotenv()


@dataclass(frozen=True)
class Settings:
    """Сборка настроек из окружения с защитой от пустых значений."""

    bot_token: str
    tplink_mode: str = "mock"            # cloud | mock
    tplink_user: str = ""
    tplink_password: str = ""
    tplink_alias: str = ""              # алиас роутера в аккаунте TP-Link (необязательно)
    admin_ids: frozenset[int] = frozenset()
    stats_interval: int = 60            # секунды, через которые кэш статуса роутера обновляется

    @classmethod
    def from_env(cls) -> "Settings":
        token = os.getenv("BOT_TOKEN", "").strip()
        if not token:
            raise RuntimeError(
                "BOT_TOKEN не задан. Скопируй .env.example в .env и укажи токен бота."
            )

        admins_raw = os.getenv("ADMIN_IDS", "").replace(";", ",")
        admins = frozenset(
            int(part.strip())
            for part in admins_raw.split(",")
            if part.strip().isdigit()
        )

        mode = os.getenv("TPLINK_MODE", "mock").strip().lower()
        if mode not in {"cloud", "mock"}:
            mode = "mock"

        try:
            interval = max(10, int(os.getenv("STATS_INTERVAL", "60") or 60))
        except ValueError:
            interval = 60

        return cls(
            bot_token=token,
            tplink_mode=mode,
            tplink_user=os.getenv("TPLINK_USER", "").strip(),
            tplink_password=os.getenv("TPLINK_PASSWORD", "").strip(),
            tplink_alias=os.getenv("TPLINK_ALIAS", "").strip(),
            admin_ids=admins,
            stats_interval=interval,
        )

    def is_admin(self, user_id: int) -> bool:
        """Если ADMIN_IDS не задан — все пользователи получают права администратора."""
        return not self.admin_ids or user_id in self.admin_ids
