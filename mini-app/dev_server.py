#!/usr/bin/env python3
"""dev_server.py — dev-сервер Эмодзи-студии на чистом stdlib Python.

Тот же API-контракт, что у Java-сервера (server/EmojiAppServer.java):
  GET /            — статика из web/
  GET /api/emoji   — каталог web/data/emoji.json
  GET /api/session — валидация x-telegram-init-data (та же схема, что в Java)

Запуск: python3 dev_server.py  (порт MINI_APP_PORT, default 8080)
Для продакшена используй Java: ./run.sh
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import unquote, urlparse

ROOT = Path(__file__).parent / "web"
PORT = int(os.getenv("MINI_APP_PORT", "8080"))
BOT_TOKEN = os.getenv("BOT_TOKEN", "")
WEBAPP_KEY = "-WebAppData"

CONTENT_TYPES = {
    ".html": "text/html; charset=utf-8",
    ".css": "text/css; charset=utf-8",
    ".js": "application/javascript; charset=utf-8",
    ".json": "application/json; charset=utf-8",
    ".svg": "image/svg+xml",
    ".png": "image/png",
    ".ico": "image/x-icon",
}


def validate_init_data(init_data: str, bot_token: str) -> dict | None:
    """Валидация по официальной схеме Telegram WebApp (та же, что в Java)."""
    if not init_data or not bot_token:
        return None

    fields: dict[str, str] = {}
    for pair in init_data.split("&"):
        idx = pair.find("=")
        if idx <= 0:
            continue
        fields[pair[:idx]] = unquote(pair[idx + 1:])

    signature = fields.pop("signature", None)
    hash_value = fields.pop("hash", None)
    if not signature or not hash_value or not fields:
        return None

    data_check = "\n".join(f"{k}={fields[k]}" for k in sorted(fields))

    # 1) hash: sha256 hex
    if hashlib.sha256(data_check.encode()).hexdigest() != hash_value:
        return None

    # 2) signature: base64url(HMAC-SHA256(secret_key, data_check_string))
    secret = hmac.new(WEBAPP_KEY.encode(), bot_token.encode(), hashlib.sha256).digest()
    expected = hmac.new(secret, data_check.encode(), hashlib.sha256).digest()
    try:
        actual = base64.urlsafe_b64decode(signature + "=" * (-len(signature) % 4))
    except Exception:
        return None
    if not hmac.compare_digest(expected, actual):
        return None

    result = dict(fields)
    result["signature"] = signature
    return result


class Handler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):  # компактный лог
        sys.stderr.write("→ %s\n" % (fmt % args))

    def _cors(self) -> None:
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type, x-telegram-init-data")

    def _send(self, code: int, body: bytes, content_type: str) -> None:
        self.send_response(code)
        self._cors()
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        if body:
            self.wfile.write(body)

    def _json(self, code: int, payload: str) -> None:
        self._send(code, payload.encode("utf-8"), "application/json; charset=utf-8")

    def _options(self) -> None:
        self.send_response(204)
        self._cors()
        self.end_headers()

    def do_OPTIONS(self):
        self._options()

    def do_GET(self):
        path = urlparse(self.path).path
        if path == "/api/emoji":
            file = ROOT / "data" / "emoji.json"
            if not file.is_file():
                self._json(500, '{"error":"emoji.json не найден"}')
                return
            self._send(200, file.read_bytes(), "application/json; charset=utf-8")
            return

        if path == "/api/session":
            init_data = self.headers.get("x-telegram-init-data", "")
            if not init_data:
                self._json(401, '{"ok":false,"error":"отсутствует x-telegram-init-data"}')
                return
            data = validate_init_data(init_data, BOT_TOKEN)
            if data is None:
                self._json(401, '{"ok":false,"error":"невалидный initData"}')
                return
            user_json = json.dumps(json.loads(data.get("user", "{}")), ensure_ascii=False)
            self._json(200, '{"ok":true,"user":%s}' % user_json)
            return

        if path == "/":
            path = "/index.html"

        if ".." in path:
            self._json(403, '{"error":"forbidden"}')
            return

        file = (ROOT / path.lstrip("/")).resolve()
        if not str(file).startswith(str(ROOT.resolve())) or not file.is_file():
            self._json(404, '{"error":"not found"}')
            return

        ctype = CONTENT_TYPES.get(file.suffix.lower(), "application/octet-stream")
        cache = "no-cache" if file.suffix.lower() == ".html" else "public, max-age=300"
        body = file.read_bytes()
        self.send_response(200)
        self._cors()
        self.send_header("Content-Type", ctype)
        self.send_header("Cache-Control", cache)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


if __name__ == "__main__":
    if not (ROOT / "index.html").is_file():
        print("web/ не найден", file=sys.stderr)
        sys.exit(1)
    server = ThreadingHTTPServer(("0.0.0.0", PORT), Handler)
    print(f"🎨 dev-сервер Эмодзи-студии: http://0.0.0.0:{PORT}")
    server.serve_forever()
