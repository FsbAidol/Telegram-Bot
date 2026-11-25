#!/usr/bin/env bash
# install.sh — полная установка Telegram-бота + мини-приложения на сервер.
#
# Делает: проверка системы → пакеты → пользователь → клонирование → venv →
# .env → systemd-сервисы → nginx → HTTPS (certbot) → firewall → запуск.
#
# Пример:
#   sudo bash deploy/install.sh \
#     --repo https://github.com/FsbAidol/Telegram-Bot.git \
#     --domain your-domain.example.com \
#     --email you@example.com
set -euo pipefail

# ---------- Параметры по умолчанию ----------
REPO_URL="https://github.com/FsbAidol/Telegram-Bot.git"
DOMAIN=""
EMAIL=""
INSTALL_DIR="/opt/telegram-bot"
RUN_USER="telegram"

usage() {
  sed -n '2,9p' "$0" | sed 's/^# \{0,1\}//'
  echo
  echo "Параметры:"
  echo "  --repo URL         Git-репозиторий (default: $REPO_URL)"
  echo "  --domain DOMAIN    Домен для HTTPS мини-приложения"
  echo "  --email EMAIL      Почта для Let's Encrypt"
  echo "  --install-dir DIR  Каталог установки (default: $INSTALL_DIR)"
  echo "  --user NAME        Пользователь сервисов (default: $RUN_USER)"
  exit 1
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --repo)        REPO_URL="$2"; shift 2 ;;
    --domain)      DOMAIN="$2"; shift 2 ;;
    --email)       EMAIL="$2"; shift 2 ;;
    --install-dir) INSTALL_DIR="$2"; shift 2 ;;
    --user)        RUN_USER="$2"; shift 2 ;;
    -h|--help)     usage ;;
    *) echo "Неизвестный параметр: $1" >&2; usage ;;
  esac
done

log()  { printf '\033[1;36m==>\033[0m %s\n' "$*"; }
ok()   { printf '\033[1;32m✓\033[0m %s\n' "$*"; }
warn() { printf '\033[1;33m!\033[0m %s\n' "$*"; }
die()  { printf '\033[1;31m✗ %s\033[0m\n' "$*" >&2; exit 1; }

# ---------- Проверка привилегий и среды ----------
[[ $EUID -eq 0 ]] || die "Запустите как root: sudo bash deploy/install.sh"
command -v apt-get >/dev/null || die "Поддерживается только Debian/Ubuntu (apt)"

log "Обновление списка пакетов"
apt-get update -qq

log "Установка системных пакетов"
apt-get install -y -qq git curl ca-certificates \
  python3 python3-venv python3-pip \
  openjdk-17-jdk-headless \
  nginx certbot python3-certbot-nginx ufw
ok "Пакеты установлены"

# ---------- Пользователь ----------
if ! id "$RUN_USER" >/dev/null 2>&1; then
  log "Создание пользователя $RUN_USER"
  useradd -m -s /bin/bash "$RUN_USER"
fi

# ---------- Клонирование / обновление ----------
log "Подготовка каталога $INSTALL_DIR"
mkdir -p "$INSTALL_DIR"
if [[ -d "$INSTALL_DIR/.git" ]]; then
  warn "Репозиторий уже существует — выполняем обновление"
  sudo -u "$RUN_USER" git -C "$INSTALL_DIR" pull --ff-only
else
  rm -rf "$INSTALL_DIR"
  sudo -u "$RUN_USER" git clone "$REPO_URL" "$INSTALL_DIR"
fi
ok "Репозиторий готов"

# ---------- Python-окружение ----------
log "Создание виртуального окружения и установка зависимостей"
sudo -u "$RUN_USER" bash -c "
  cd '$INSTALL_DIR'
  [[ -d .venv ]] || python3 -m venv .venv
  .venv/bin/pip install --upgrade -q pip
  .venv/bin/pip install -q -r requirements.txt
"
ok "Python-окружение готово"

# ---------- .env ----------
log "Настройка .env"
ENV_FILE="$INSTALL_DIR/.env"
if [[ ! -f "$ENV_FILE" ]]; then
  sudo -u "$RUN_USER" cp "$INSTALL_DIR/.env.example" "$ENV_FILE"
fi

ask() {
  local var_name="$1" prompt="$2" cur
  cur=$(sudo -u "$RUN_USER" grep -E "^${var_name}=" "$ENV_FILE" 2>/dev/null | head -1 | cut -d= -f2- || true)
  if [[ -n "$cur" ]]; then
    ok "$var_name уже задан ($cur) — оставляю"
  else
    read -r -p "$prompt: " cur
    if [[ -n "$cur" ]]; then
      sudo -u "$RUN_USER" sed -i "s|^${var_name}=.*|${var_name}=${cur}|" "$ENV_FILE" 2>/dev/null \
        || sudo -u "$RUN_USER" bash -c "echo '${var_name}=${cur}' >> '$ENV_FILE'"
      ok "$var_name сохранён"
    fi
  fi
}

# BOT_TOKEN — скрытый ввод, если ещё не задан
if sudo -u "$RUN_USER" grep -qE "^BOT_TOKEN=.+" "$ENV_FILE" 2>/dev/null; then
  ok "BOT_TOKEN уже задан — оставляю"
else
  read -r -s -p "Токен бота от @BotFather (ввод скрыт): " tok
  echo
  if [[ -n "$tok" ]]; then
    sudo -u "$RUN_USER" sed -i "s|^BOT_TOKEN=.*|BOT_TOKEN=${tok}|" "$ENV_FILE"
    ok "BOT_TOKEN сохранён"
  else
    warn "BOT_TOKEN не введён — заполните $ENV_FILE вручную"
  fi
fi
ask ADMIN_IDS "ID администратора (через запятую)"

if [[ -n "$DOMAIN" ]]; then
  sudo -u "$RUN_USER" sed -i "s|^MINI_APP_URL=.*|MINI_APP_URL=https://$DOMAIN|" "$ENV_FILE"
  ok "MINI_APP_URL = https://$DOMAIN"
fi

# ---------- Systemd-сервисы ----------
log "Установка systemd-сервисов"
for unit in telegram-bot emoji-studio; do
  sudo cp "$INSTALL_DIR/deploy/${unit}.service" "/etc/systemd/system/${unit}.service"
done
# Унифицируем пути, если install-dir/user отличаются от стандартных
sudo sed -i "s|/opt/telegram-bot|$INSTALL_DIR|g; s|User=telegram|User=$RUN_USER|g" \
  /etc/systemd/system/telegram-bot.service /etc/systemd/system/emoji-studio.service
sudo systemctl daemon-reload
ok "Сервисы установлены"

# ---------- nginx + HTTPS ----------
if [[ -n "$DOMAIN" ]]; then
  log "Настройка nginx для $DOMAIN"
  sudo sed "s/your-domain.example.com/$DOMAIN/g" \
    "$INSTALL_DIR/deploy/nginx-emoji-studio.conf" > /etc/nginx/sites-available/emoji-studio
  sudo ln -sf /etc/nginx/sites-available/emoji-studio /etc/nginx/sites-enabled/emoji-studio
  sudo nginx -t

  log "Выдача SSL-сертификата Let's Encrypt"
  if sudo certbot --nginx -d "$DOMAIN" --non-interactive --agree-tos \
        --register-unsafely-without-email --redirect \
        -m "$EMAIL" 2>/dev/null; then
    ok "Сертификат выдан, HTTPS активен"
  else
    warn "certbot не удалось выполнить автоматически — запустите вручную:"
    warn "  sudo certbot --nginx -d $DOMAIN"
  fi
else
  warn "--domain не задан: мини-приложение останется на http://<ip>:8080"
  warn "Для Telegram Mini App нужен HTTPS — добавьте домен и перезапустите скрипт"
fi

# ---------- Firewall ----------
if command -v ufw >/dev/null 2>&1; then
  log "Настройка ufw"
  sudo ufw allow 22/tcp >/dev/null 2>&1 || true
  sudo ufw allow 80,443/tcp >/dev/null 2>&1 || true
  sudo ufw --force enable >/dev/null 2>&1 || true
  ok "ufw настроен (22, 80, 443)"
fi

# ---------- Запуск ----------
log "Запуск сервисов"
sudo systemctl enable --now telegram-bot
sudo systemctl enable --now emoji-studio
sleep 2

echo
ok "Готово! Состояние сервисов:"
systemctl --no-pager --full status telegram-bot emoji-studio | head -30
echo
echo "Ссылки:"
[[ -n "$DOMAIN" ]] && echo "  Мини-приложение: https://$DOMAIN"
echo "  Лог бота:  journalctl -u telegram-bot -f"
echo "  Лог приложения: journalctl -u emoji-studio -f"
