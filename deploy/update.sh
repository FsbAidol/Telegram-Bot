#!/usr/bin/env bash
# update.sh — обновление бота и мини-приложения на сервере.
set -euo pipefail

INSTALL_DIR="${1:-/opt/telegram-bot}"
RUN_USER="${2:-telegram}"

log() { printf '\033[1;36m==>\033[0m %s\n' "$*"; }

log "Обновление репозитория в $INSTALL_DIR"
sudo -u "$RUN_USER" git -C "$INSTALL_DIR" pull --ff-only

log "Обновление Python-зависимостей"
sudo -u "$RUN_USER" "$INSTALL_DIR/.venv/bin/pip" install -q -r "$INSTALL_DIR/requirements.txt"

log "Перезапуск сервисов"
sudo systemctl restart telegram-bot
sudo systemctl restart emoji-studio

log "Обновление завершено ✅"
