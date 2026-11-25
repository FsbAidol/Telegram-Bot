#!/usr/bin/env bash
# Запуск Эмодзи-студии (Java, чистый JDK, без зависимостей).
# Требуется: JDK 11+.
set -euo pipefail
cd "$(dirname "$0")"

rm -rf out
mkdir -p out
javac -encoding UTF-8 -d out server/*.java

export MINI_APP_PORT="${MINI_APP_PORT:-8080}"
export MINI_APP_WEB="${MINI_APP_WEB:-web}"
export BOT_TOKEN="${BOT_TOKEN:-}"

echo "→ Компиляция завершена, запускаю на 0.0.0.0:${MINI_APP_PORT}"
exec java -Dfile.encoding=UTF-8 -cp out EmojiAppServer
