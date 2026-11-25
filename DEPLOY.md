# 📦 Полная установка на сервер

Пошаговое развёртывание **Telegram-бота** (Python/aiogram) и **мини-приложения
«Эмодзи-студия»** (Java) на сервер с Ubuntu/Debian, systemd, nginx и HTTPS
(HTTPS обязателен для Telegram Mini App).

## 0. Требования

| Компонент | Что нужно |
|---|---|
| ОС | Ubuntu 22.04+ / Debian 12+ (amd64 или arm64) |
| Telegram-бот | Python 3.11+, pip |
| Мини-приложение | JDK 17+ (`openjdk-17-jdk-headless` — нужен для `javac`) |
| HTTPS | nginx + certbot (Let's Encrypt) |
| Доступ | Суперпользователь (sudo), порт 22 (SSH) |

Порты: `22` (SSH), `80`/`443` (HTTP/HTTPS). Боту достаточно выхода в интернет
(polling), вебхуки не используются.

---

## Вариант A: Автоматическая установка (рекомендуется)

Один файл делает всё: проверку системы, пакеты, клонирование, venv, systemd,
nginx, HTTPS-сертификат и запуск сервисов.

```bash
sudo bash deploy/install.sh \
  --repo https://github.com/FsbAidol/Telegram-Bot.git \
  --domain your-domain.example.com \
  --email you@example.com
```

Параметры:

| Параметр | Назначение |
|---|---|
| `--repo URL` | Ссылка на Git-репозиторий (по умолчанию этот репозиторий) |
| `--domain` | Домен для мини-приложения (HTTPS); без него HTTPS настраивать не будет |
| `--email` | Почта для уведомлений Let's Encrypt |
| `--install-dir` | Каталог установки (по умолчанию `/opt/telegram-bot`) |
| `--user` | Системный пользователь под сервисы (по умолчанию `telegram`) |

Скрипт спросит **BOT_TOKEN** (от @BotFather) и **ADMIN_IDS**. После завершения:

```bash
systemctl status telegram-bot emoji-studio
journalctl -u telegram-bot -f
```

---

## Вариант B: Ручная установка

### 1. Системные пакеты

```bash
sudo apt update
sudo apt install -y git curl ca-certificates \
  python3 python3-venv python3-pip \
  openjdk-17-jdk-headless \
  nginx certbot python3-certbot-nginx ufw
```

### 2. Создание пользователя и клонирование

```bash
sudo useradd -m -s /bin/bash telegram
sudo mkdir -p /opt/telegram-bot && sudo chown telegram:telegram /opt/telegram-bot
sudo -u telegram git clone https://github.com/FsbAidol/Telegram-Bot.git /opt/telegram-bot
```

### 3. Python-окружение для бота

```bash
sudo -u telegram bash -c '
  cd /opt/telegram-bot
  python3 -m venv .venv
  .venv/bin/pip install --upgrade pip
  .venv/bin/pip install -r requirements.txt
'
```

### 4. Настройка `.env`

```bash
sudo -u telegram cp /opt/telegram-bot/.env.example /opt/telegram-bot/.env
sudo nano /opt/telegram-bot/.env
```

Заполнить:

```ini
BOT_TOKEN=6012345678:AAHdqTcvCH1vGWJxfSeofSAs0K5PALDsaw
ADMIN_IDS=123456789,987654321
TPLINK_MODE=cloud
TPLINK_USER=you@tplinkcloud.com
TPLINK_PASSWORD=пароль_аккаунта_Tether
TPLINK_ALIAS=Archer-C80
STATS_INTERVAL=60
# пока без HTTPS — сюда вернёмся на шаге 8
MINI_APP_URL=
```

### 5. Сервисы systemd

```bash
sudo cp deploy/telegram-bot.service deploy/emoji-studio.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now telegram-bot
sudo systemctl enable --now emoji-studio
```

Проверка:

```bash
systemctl status telegram-bot emoji-studio
journalctl -u telegram-bot -n 50
curl -s http://127.0.0.1:8080/api/emoji | head -c 120
```

### 6. nginx + HTTPS для мини-приложения

Telegram требует **HTTPS** для Mini App. Без домена можно получить https-ссылку
за минуту через туннель Cloudflare (бесплатно, без регистрации домена):

```bash
apt install -y cloudflared        # или скачать бинарник с cloudflare.com
cloudflared tunnel --url http://localhost:8080
# напечатается URL вида https://xxx.trycloudflare.com — это и есть MINI_APP_URL
```

С доменом — обычный путь (nginx + Let's Encrypt). Подменяем плейсхолдер домена:

```bash
sudo sed -i 's/your-domain.example.com/'"$YOUR_DOMAIN"'/g' deploy/nginx-emoji-studio.conf
sudo cp deploy/nginx-emoji-studio.conf /etc/nginx/sites-available/emoji-studio
sudo ln -sf /etc/nginx/sites-available/emoji-studio /etc/nginx/sites-enabled/
sudo nginx -t && sudo systemctl reload nginx
sudo certbot --nginx -d "$YOUR_DOMAIN" --non-interactive --agree-tos -m you@example.com
```

certbot автоматически вставит сертификаты в конфиг. Проверка:
`curl -sI https://$YOUR_DOMAIN/ | head -3` — должен быть `HTTP/2 200`.

### 7. Подключение мини-приложения к боту

1. В @BotFather → `/newapp` (или настройки бота) добавить домен
   `https://your-domain.example.com` в список доверенных для Mini App.
2. В `/opt/telegram-bot/.env` задать:

```ini
MINI_APP_URL=https://your-domain.example.com
```

3. Перезапустить бот: `sudo systemctl restart telegram-bot`.
4. В Telegram: кнопка **🎨 Эмодзи-студия** в меню бота открывает приложение.

### 8. Firewall (опционально, если используется ufw)

```bash
sudo ufw allow 22
sudo ufw allow 80,443/tcp
sudo ufw --force enable
```

---

## Обновление

```bash
sudo -u telegram bash deploy/update.sh
# либо вручную:
sudo -u telegram git -C /opt/telegram-bot pull --ff-only
sudo -u telegram /opt/telegram-bot/.venv/bin/pip install -r /opt/telegram-bot/requirements.txt
sudo systemctl restart telegram-bot emoji-studio
```

## Логи и отладка

| Что | Где |
|---|---|
| Лог бота | `journalctl -u telegram-bot -f` и `/opt/telegram-bot/logs/bot.log` |
| Лог мини-приложения | `journalctl -u emoji-studio -f` |
| nginx | `journalctl -u nginx -f`, `sudo nginx -t` |
| Обновление сертификата | `sudo certbot renew` (автоматическое, раз в 2 месяца) |

## Безопасность

- Не храните токен в публичных репозиториях — `.env` не коммитится (`.gitignore`).
- Старые логи содержат ID пользователей и команды — чистите `logs/bot.log`
  при необходимости.
- `ADMIN_IDS` — только ваш ID; иначе любой в Telegram сможет перезагружать роутер.
- Роутер управляется через аккаунт TP-Link Cloud — используйте строгий пароль.

## Частые проблемы

| Симптом | Решение |
|---|---|
| Mini App не открывается | Домен не закреплён в @BotFather; проверить `curl -I https://domain/` → 200 |
| `/api/session` 401 | `BOT_TOKEN` в `.env` должен быть **тым же**, что и у бота |
| Service не стартует | `journalctl -u <service> -n 100`; проверить `.env` и права пользователя `telegram` |
| Port 8080 занят | `MINI_APP_PORT=9090` в unit-файле и nginx-проксий на этот порт |
| Java не компилируется | Установлен только JRE — нужен `openjdk-17-jdk-headless` (javac) |
| `venv не создан ... ensurepip is not available` | На Ubuntu/Debian не установлен `python3-venv`: `apt install -y python3-venv` (или `python3.10-venv`), затем удалить старый `.venv` и создать новый |
| `requirements.txt` / `.env.example` не найдены | Команды выполнены не внутри каталога репозитория — `cd` в папку после `git clone` |
| `Web App URL 'http://...' is invalid: Only HTTPS links are allowed` | `MINI_APP_URL` должен начинаться с `https://` (туннель cloudflared или домен + certbot). Если HTTPS ещё нет — оставьте `MINI_APP_URL` пустым: кнопка скроется и бот будет работать |
