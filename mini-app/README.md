# 🎨 Эмодзи-студия — Telegram-мини-приложение

Мини-приложение для бота: gallery премиум-эмодзи с **плавными SVG-анимациями**
(SMIL + JS-скрипты анимации), премиальный тёмный интерфейс и Java-бэкенд.

## 🧩 Состав

```
mini-app/
├── run.sh                    # продакшен-запуск на Java (чистый JDK 11+, без зависимостей)
├── dev_server.py             # dev-сервер на stdlib Python (тот же API-контракт)
├── server/                   # Java-бэкенд (com.sun.net.httpserver)
│   ├── EmojiAppServer.java       # статика + /api/emoji + /api/session, CORS
│   └── TelegramInitDataValidator.java  # валидация initData WebApp (HMAC-SHA256)
└── web/                      # фронтендер (HTML/CSS/JS, без сборки)
    ├── index.html
    ├── styles.css            # тёмная премиум-тема, анимированная аурора, glassmorphism
    ├── js/
    │   ├── emoji-script.js   # движок «скриптов» анимации эмодзи (rAF, easing, таймлайны)
    │   └── app.js            # галерея, поиск, модалка, копипаст, частицы
    ├── data/emoji.json       # каталог эмодзи (API)
    └── emoji/*.svg           # 12 анимированных SVG-эмодзи (SMIL-циклы)
```

## 🚀 Запуск

**Java (продакшен):**
```bash
cd mini-app
./run.sh                      # javac + java, прослушивает 0.0.0.0:8080
```

**Python (быстрый dev, тот же API):**
```bash
cd mini-app
python3 dev_server.py         # прослушивает 0.0.0.0:8080
```

Переменные окружения: `MINI_APP_PORT` (8080), `MINI_APP_WEB` (web),
`BOT_TOKEN` (для валидации initData в `/api/session`).

## 🔌 API

| Эндпоинт | Описание |
|---|---|
| `GET /` | Статика (index.html, css, js, svg) |
| `GET /api/emoji` | Каталог эмодзи: `id, name, unicode, tags, svg, anim` |
| `GET /api/session` | Валидация `x-telegram-init-data` → `{ok, user}` (401 при невалидных данных) |

CORS включён для запросов из WebView Telegram.

## 🎯 Подключение к боту

1. Запусти мини-приложение (Java или Python) и получи доступ по HTTPS
   (логируй туннелем вида `https://<host>.trycloudflare.com`, либо домен
   в @BotFather → «Домен Mini App»).
2. В `.env` бота укажи `MINI_APP_URL=https://your-domain.example`.
3. В главном меню бота появится кнопка **🎨 Эмодзи-студия** — открытие
   мини-приложения через `WebAppInfo`.

## ✨ Анимации

- **SVG-эмодзи**: 12 векторных иконок с SMIL-циклами (мерцание огня, парящая
  ракета, вращающиеся звезды, конфетти и т.д.).
- **JS-скрипты анимации** (`emoji-script.js`): движок таймлайнов на
  `requestAnimationFrame` с easing (elastic, bounce, easeOut) — `pop`, `float`,
  `pulse`, `twinkle`, `spin`, `glow`, `wave`, `confetti`, `flicker`, `shimmer`.
- **Интерфейс**: анимированная аурора-фон, летящие частицы, staggered-появление
  карточек, блики при наведении, модалка с плавающим превью, тосты.
- **Telegram WebApp**: тема, разложение на весь экран, датасет темы.

## 🧪 Тесты

```bash
python -m unittest discover tests -v   # каталог, SVG, HTML, валидация initData
```
