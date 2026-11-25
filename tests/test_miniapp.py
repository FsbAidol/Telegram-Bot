"""Контракт-тест мини-приложения «Эмодзи-студия»:
каталог, SVG-эмодзи, HTML-ссылки и алгоритм валидации Telegram initData.

Запуск: python -m unittest discover tests -v
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import sys
import unittest
import xml.etree.ElementTree as ET
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
WEB = ROOT / "mini-app" / "web"
sys.path.insert(0, str(ROOT / "mini-app"))

from dev_server import validate_init_data  # noqa: E402


def make_init_data(bot_token: str, extra: dict | None = None, tamper: bool = False) -> str:
    """Генерирует корректный initData по официальной схеме (для теста)."""
    data = {
        "query_id": "AAEbWlQAAAAAEBA1aN",
        "user": json.dumps({"id": 42, "first_name": "Тест", "is_premium": True}),
        "auth_date": "1700000000",
    }
    if extra:
        data.update(extra)
    data_check = "\n".join(f"{k}={data[k]}" for k in sorted(data))
    secret = hmac.new(b"-WebAppData", bot_token.encode(), hashlib.sha256).digest()
    signature = base64.urlsafe_b64encode(
        hmac.new(secret, data_check.encode(), hashlib.sha256).digest()
    ).decode().rstrip("=")
    data["hash"] = hashlib.sha256(data_check.encode()).hexdigest()
    data["signature"] = signature
    if tamper:
        data["user"] = json.dumps({"id": 999, "first_name": "Взлом"})
    return "&".join(f"{k}={v}" for k, v in data.items())


class TestEmojiCatalog(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.catalog_path = WEB / "data" / "emoji.json"
        cls.catalog = json.loads(cls.catalog_path.read_text(encoding="utf-8"))

    def test_catalog_fields(self) -> None:
        self.assertGreaterEqual(len(self.catalog), 10)
        for entry in self.catalog:
            for field in ("id", "name", "unicode", "tags", "svg", "anim"):
                self.assertIn(field, entry, entry)
            self.assertIsInstance(entry["tags"], list)

    def test_svg_files_exist_and_valid_xml(self) -> None:
        for entry in self.catalog:
            svg_path = WEB / entry["svg"]
            self.assertTrue(svg_path.is_file(), f"пропущен файл {entry['svg']}")
            tree = ET.parse(svg_path)  # поднимает ParseError при невалидном XML
            root = tree.getroot()
            self.assertEqual(root.tag, "{http://www.w3.org/2000/svg}svg")
            self.assertEqual(root.get("viewBox"), "0 0 100 100")

    def test_every_svg_has_animation(self) -> None:
        for entry in self.catalog:
            text = (WEB / entry["svg"]).read_text(encoding="utf-8")
            self.assertIn("animate", text, entry["svg"])
            self.assertIn("repeatCount=\"indefinite\"", text, entry["svg"])

    def test_html_references(self) -> None:
        html = (WEB / "index.html").read_text(encoding="utf-8")
        for ref in ("styles.css", "js/emoji-script.js", "js/app.js"):
            self.assertIn(ref, html)

    def test_java_sources_present(self) -> None:
        server_dir = ROOT / "mini-app" / "server"
        for name in ("EmojiAppServer.java", "TelegramInitDataValidator.java"):
            self.assertTrue((server_dir / name).is_file(), name)


class TestInitDataValidator(unittest.TestCase):
    BOT_TOKEN = "123456789:TEST_TOKEN_FOR_VALIDATOR"

    def test_valid_init_data(self) -> None:
        result = validate_init_data(make_init_data(self.BOT_TOKEN), self.BOT_TOKEN)
        self.assertIsNotNone(result)
        self.assertEqual(json.loads(result["user"])["id"], 42)

    def test_tampered_init_data_rejected(self) -> None:
        self.assertIsNone(validate_init_data(make_init_data(self.BOT_TOKEN, tamper=True), self.BOT_TOKEN))

    def test_wrong_token_rejected(self) -> None:
        init_data = make_init_data(self.BOT_TOKEN)
        self.assertIsNone(validate_init_data(init_data, "other:token"))

    def test_empty_inputs(self) -> None:
        self.assertIsNone(validate_init_data("", self.BOT_TOKEN))
        self.assertIsNone(validate_init_data("query_id=x&hash=y&signature=z", self.BOT_TOKEN))


if __name__ == "__main__":
    unittest.main()
