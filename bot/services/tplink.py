"""Управление роутером TP-Link Archer C80.

Два реального режима:

1. ``lan`` — локальный HTTP-API роутера (прошивка SG/CE_RED, как в Tether/веб-UI).
   Это современный и рабочий способ управления Archer C80. Клиент копирует
   handshake веб-интерфейса роутера:

      1. ``login?form=keys``   — публичный ключ RSA для шифрования пароля.
      2. ``login?form=auth``   — ключ RSA для подписи + последовательный номер seq.
      3. ``login?form=login``  — AES-CBC + RSA-OAEP подпись, получаем stok и
                                 cookie sysauth.
      4. Все последующие запросы — AES-CBC + HMAC-SHA256 подпись через
         ``/cgi-bin/luci/;stok=<stok>/<path>?form=<form>``.

   Требует, чтобы бот был в той же сети, что и роутер (или роутер был доступен
   удалённо через шлюз/VPN). Настройки: TPLINK_HOST (IP роутера),
   TPLINK_ADMIN (пользователь, обычно admin), TPLINK_PASSWORD (пароль роутера).

2. ``cloud`` — прежний TP-Link Cloud API для роутеров (a1.tplinkcloud.com).
   Облачный API роутеров от TP-Link отключён (хост более не существует),
   поэтому по умолчанию для реального роутера используется режим ``lan``.
   Эндпоинт можно задать через TPLINK_CLOUD_URL, если есть рабочий gateway.

Если данные роутера не заданы или TPLINK_MODE=mock — работает MockRouter:
полноценная виртуальная модель роутера для демонстрации и тестов.
"""
from __future__ import annotations

import asyncio
import hashlib
import hmac
import logging
import time
from base64 import b64encode, b64decode
from binascii import hexlify
from dataclasses import dataclass, field
from random import randint
from typing import Any
from urllib.parse import urlencode

import aiohttp
from Crypto.Cipher import AES, PKCS1_OAEP, PKCS1_v1_5
from Crypto.PublicKey.RSA import construct
from Crypto.Util.Padding import pad, unpad

from bot.config import Settings

logger = logging.getLogger(__name__)

# --- Режим cloud (устаревший, но оставлен для совместимости) ---
CLOUD_ENDPOINT = "https://a1.tplinkcloud.com"

# --- Режим LAN: протокол веб-UI роутера (SG/CE_RED) ---
SIGNATURE_OFFSET = 53
AES_KEY_LEN = 16

# Индекс диапазона в протоколе TP-Link Cloud (как в Tether).
BAND_INDEX: dict[str, int] = {"24": 0, "5": 1, "guest": 2}
BAND_LABEL: dict[int, str] = {0: "Wi-Fi 2.4 ГГц", 1: "Wi-Fi 5 ГГц", 2: "Guest Wi-Fi"}
BAND_KEY: dict[int, str] = {0: "24", 1: "5", 2: "guest"}

# Метод получения списка клиентов: пробуем известные варианты по порядку.
CLIENT_LIST_METHODS = (
    "getDeviceClientList",
    "getDeviceConnectedClientList",
    "getDeviceWifiClientList",
)


class TpLinkError(Exception):
    """Ошибка при работе с TP-Link."""


class TpLinkAuthFailed(TpLinkError):
    """Неверные данные роутера/аккаунта TP-Link."""


class RouterUnavailable(TpLinkError):
    """Роутер недоступен (офлайн, сеть, нет ответа)."""


# ---------------------------------------------------------------------------
# Данные
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class WifiNetwork:
    key: str          # "24" | "5" | "guest"
    label: str
    enabled: bool
    ssid: str = ""
    clients: int = 0


@dataclass
class RouterStatus:
    mode: str = "mock"
    online: bool = False
    alias: str = "Router"
    model: str = "TP-Link Archer C80"
    mac: str = ""
    firmware: str = "—"
    uptime: str = "—"
    cpu: str = "—"
    memory: str = "—"
    wan_ip: str = "—"
    download_mbps: float = 0.0
    upload_mbps: float = 0.0
    networks: list[WifiNetwork] = field(default_factory=list)
    total_clients: int = 0
    refreshed_at: float = field(default_factory=time.time)

    def network(self, key: str) -> WifiNetwork | None:
        for net in self.networks:
            if net.key == key:
                return net
        return None


@dataclass
class ClientDevice:
    name: str
    mac: str = ""
    ip: str = ""
    download_mbps: float = 0.0
    upload_mbps: float = 0.0
    band: str = ""


# ---------------------------------------------------------------------------
# Клиент TP-Link Cloud API (устаревший; оставлен для совместимости)
# ---------------------------------------------------------------------------

class TpLinkCloudClient:
    """Асинхронный клиент TP-Link Cloud API (для роутеров, включая Archer C80)."""

    def __init__(self, username: str, password: str, endpoint: str = CLOUD_ENDPOINT,
                 timeout: int = 15) -> None:
        self._username = username
        self._password = password
        self._endpoint = endpoint
        self._timeout = aiohttp.ClientTimeout(total=timeout)
        self._session: aiohttp.ClientSession | None = None
        self._dp_id: str = ""
        self._uid: str = ""

    async def __aenter__(self) -> "TpLinkCloudClient":
        await self._open()
        return self

    async def __aexit__(self, *exc: Any) -> None:
        await self._close()

    async def _open(self) -> None:
        if self._session is None:
            # unsafe=True — нужен, чтобы сохранять cookie TP_SESSIONID по IP-адресу.
            self._session = aiohttp.ClientSession(
                cookie_jar=aiohttp.CookieJar(unsafe=True), timeout=self._timeout
            )

    async def _close(self) -> None:
        if self._session is not None:
            await self._session.close()
            self._session = None

    async def _post(self, payload: dict[str, Any]) -> dict[str, Any]:
        await self._open()
        try:
            async with self._session.post(self._endpoint, json=payload) as resp:
                data = await resp.json(content_type=None)
        except aiohttp.ClientError as exc:
            raise RouterUnavailable(f"Нет связи с TP-Link Cloud: {exc}") from exc
        except Exception as exc:
            raise RouterUnavailable(f"Некорректный ответ TP-Link Cloud: {exc}") from exc

        code = data.get("error_code", data.get("errorCode", 0))
        if code not in (0, "0", None):
            msg = data.get("msg", data.get("message", "Неизвестная ошибка API"))
            if "session" in msg.lower() or code in (-10103, -10104, -10003):
                raise TpLinkAuthFailed(f"Сессия TP-Link Cloud неактивна: {msg}")
            raise TpLinkError(f"TP-Link Cloud вернул ошибку {code}: {msg}")
        return data

    async def login(self) -> None:
        """Авторизация: пароль отправляется как MD5 (по протоколу)."""
        payload = {
            "method": "login",
            "params": {
                "username": self._username,
                "password": hashlib.md5(self._password.encode("utf-8")).hexdigest(),
            },
        }
        data = await self._post(payload)
        result = data.get("result", {})
        self._dp_id = str(result.get("dp_id", ""))
        self._uid = str(result.get("uid", ""))
        if not self._dp_id:
            raise TpLinkAuthFailed("TP-Link Cloud не вернул идентификатор устройства")
        logger.info("Авторизация в TP-Link Cloud успешна (dp_id=%s)", self._dp_id)

    async def call(self, method: str, params: dict[str, Any] | None = None) -> Any:
        """Вызов метода через контейнер tplinkcloud."""
        payload = {
            "method": "tplinkcloud",
            "params": {
                "dp_id": self._dp_id,
                "uid": self._uid,
                "requestData": {method: params or {}},
            },
        }
        data = await self._post(payload)
        result = data.get("result", {})
        # В ответе данные могут лежать в result.data или непосредственно в result.
        return result.get("data", result) if isinstance(result, dict) else result

    async def get_devices(self) -> list[dict[str, Any]]:
        result = await self.call("getDeviceList")
        if isinstance(result, list):
            return result
        if isinstance(result, dict):
            devices = result.get("deviceList", [])
            return devices if isinstance(devices, list) else []
        return []

    async def select_device(self, alias: str = "") -> str:
        """Выбор роутера: по алиасу, иначе первое устройство аккаунта."""
        devices = await self.get_devices()
        if not devices:
            raise RouterUnavailable("В аккаунте TP-Link нет устройств")
        if alias:
            for dev in devices:
                if str(dev.get("alias", "")) == alias:
                    return str(dev.get("dp_id") or dev.get("deviceId") or dev.get("id"))
        for dev in devices:
            dtype = str(dev.get("deviceType", ""))
            if "WIRELESS" in dtype.upper() or dtype == "IOT.WIRELESS":
                return str(dev.get("dp_id") or dev.get("deviceId") or dev.get("id"))
        return str(devices[0].get("dp_id") or devices[0].get("deviceId") or devices[0].get("id"))

    async def device_info(self, dp_id: str) -> dict[str, Any]:
        result = await self.call("getDeviceBasicFmt", {"dp_id": dp_id})
        return result if isinstance(result, dict) else {}

    async def reboot(self, dp_id: str) -> None:
        await self.call("reboot", {"dp_id": dp_id})

    async def set_wifi(self, dp_id: str, index: int, ssid: str = "",
                       password: str = "", enable: bool | None = None) -> None:
        params: dict[str, Any] = {"dp_id": dp_id, "index": index}
        if ssid:
            params["ssid"] = ssid
        if password:
            params["password"] = password
        if enable is not None:
            params["enable"] = 1 if enable else 0
        await self.call("setDeviceWifi", params)

    async def get_clients(self, dp_id: str) -> list[dict[str, Any]]:
        last_error: Exception | None = None
        for method in CLIENT_LIST_METHODS:
            try:
                result = await self.call(method, {"dp_id": dp_id})
            except TpLinkError as exc:
                last_error = exc
                continue
            if isinstance(result, list):
                return result
            if isinstance(result, dict):
                for key in ("clientList", "clients", "deviceList"):
                    items = result.get(key)
                    if isinstance(items, list):
                        return items
        if last_error is not None:
            raise RouterUnavailable(f"Не удалось получить список клиентов: {last_error}")
        return []


# ---------------------------------------------------------------------------
# Клиент локального HTTP-API роутера (прошивка SG/CE_RED)
# ---------------------------------------------------------------------------

def _to_bool(val: Any) -> bool:
    if isinstance(val, bool):
        return val
    if isinstance(val, str):
        return val.lower() in ("on", "true", "yes", "1")
    return bool(val)


class TpLinkLanClient:
    """Клиент локального HTTP-API TP-Link Archer C80 (прошивка SG/CE_RED).

    Повторяет handshake веб-интерфейса роутера: RSA-шифрование пароля,
    AES-CBC для данных и HMAC-SHA256 для подписи запросов.
    """

    def __init__(self, host: str, username: str = "admin", password: str = "",
                 timeout: int = 15) -> None:
        host_clean = host.rstrip("/")
        if not host_clean.startswith(("http://", "https://")):
            self.base_url = f"http://{host_clean}"
        else:
            self.base_url = host_clean
        self._username = username
        self._password = password
        self._timeout = aiohttp.ClientTimeout(total=timeout)
        self._session: aiohttp.ClientSession | None = None
        self._stok: str = ""
        self._sysauth: str = ""

        # Состояние handshake
        self._aes_key: str = ""
        self._aes_iv: str = ""
        self._hash: str = ""
        self._seq: int = 0
        self._nn: str = ""
        self._ee: str = ""
        self._pwd_nn: str = ""
        self._pwd_ee: str = ""

    async def __aenter__(self) -> "TpLinkLanClient":
        await self._open()
        return self

    async def __aexit__(self, *exc: Any) -> None:
        await self._close()

    async def _open(self) -> None:
        if self._session is None:
            self._session = aiohttp.ClientSession(
                cookie_jar=aiohttp.CookieJar(unsafe=True), timeout=self._timeout
            )

    async def _close(self) -> None:
        if self._session is not None:
            await self._session.close()
            self._session = None

    # -- криптографические примитивы (как в веб-UI роутера) --

    def _generate_aes_key(self) -> None:
        self._aes_key = "".join(str(randint(0, 9)) for _ in range(AES_KEY_LEN))
        self._aes_iv = "".join(str(randint(0, 9)) for _ in range(AES_KEY_LEN))

    def _aes_encrypt(self, data: str) -> str:
        cipher = AES.new(self._aes_key.encode(), AES.MODE_CBC, self._aes_iv.encode())
        return b64encode(cipher.encrypt(pad(data.encode(), AES.block_size))).decode()

    def _aes_decrypt(self, data: str) -> str:
        cipher = AES.new(self._aes_key.encode(), AES.MODE_CBC, self._aes_iv.encode())
        return unpad(cipher.decrypt(b64decode(data)), AES.block_size).decode()

    @staticmethod
    def _rsa_v15_encrypt(data: str, n_hex: str, e_hex: str) -> str:
        key = construct((int(n_hex, 16), int(e_hex, 16)))
        cipher = PKCS1_v1_5.new(key)
        result = hexlify(cipher.encrypt(data.encode())).decode()
        key_len = len(n_hex)
        return result.zfill(key_len) if len(result) < key_len else result

    @staticmethod
    def _rsa_oaep_encrypt(data: str, n_hex: str, e_hex: str) -> str:
        key = construct((int(n_hex, 16), int(e_hex, 16)))
        cipher = PKCS1_OAEP.new(key)
        result = hexlify(cipher.encrypt(data.encode())).decode()
        key_len = len(n_hex)
        return result.zfill(key_len) if len(result) < key_len else result

    def _get_aes_formatted_key(self) -> str:
        return f"k={self._aes_key}&i={self._aes_iv}"

    def _build_login_signature(self, data_len: int) -> str:
        sign_str = f"{self._get_aes_formatted_key()}&h={self._hash}&s={self._seq + data_len}"
        rsa_byte_len = len(self._nn) // 2
        oaep_step = min(SIGNATURE_OFFSET, rsa_byte_len - 2 * 20 - 2)
        sign = ""
        for i in range(0, len(sign_str), oaep_step):
            chunk = sign_str[i:i + oaep_step]
            sign += self._rsa_oaep_encrypt(chunk, self._nn, self._ee)
        return sign

    def _build_request_signature(self, data_len: int) -> str:
        sign_str = f"h={self._hash}&s={self._seq + data_len}"
        aes_key = self._get_aes_formatted_key()
        sign = ""
        for i in range(0, len(sign_str), SIGNATURE_OFFSET):
            chunk = sign_str[i:i + SIGNATURE_OFFSET]
            h = hmac.new(aes_key.encode(), chunk.encode(), hashlib.sha256)
            sign += h.hexdigest()
        return sign

    # -- HTTP-примитив --

    async def _post(self, path: str, data: dict[str, Any], use_login_stok: bool = False) -> dict[str, Any]:
        await self._open()
        clean_path = path.lstrip("/")
        if self._stok == "" or use_login_stok:
            _, separator, query = clean_path.partition("?")
            if separator:
                url = f"/cgi-bin/luci/;stok=/login?{query}"
            else:
                url = "/cgi-bin/luci/;stok=/login"
        else:
            url = f"/cgi-bin/luci/;stok={self._stok}/{clean_path}"

        headers = {
            "Content-Type": "application/x-www-form-urlencoded",
            "Referer": f"{self.base_url}/webpages/index.html#/login",
        }
        try:
            async with self._session.post(url, data=data, headers=headers) as resp:
                if resp.status in (401, 403):
                    raise TpLinkAuthFailed(f"Роутер отказал в доступе (HTTP {resp.status})")
                res_json = await resp.json(content_type=None)
        except aiohttp.ClientError as exc:
            raise RouterUnavailable(f"Нет связи с роутером {self.base_url}: {exc}") from exc
        except TpLinkAuthFailed:
            raise
        except Exception as exc:
            raise RouterUnavailable(f"Некорректный ответ роутера: {exc}") from exc

        # Сохраняем cookie sysauth
        sysauth = self._session.cookie_jar.filter_cookies(self.base_url).get("sysauth")
        if sysauth:
            self._sysauth = sysauth.value
        return res_json

    async def _request_pwd_keys(self) -> None:
        response = await self._post("login?form=keys", {"operation": "read"}, use_login_stok=True)
        try:
            self._pwd_nn = response["data"]["password"][0]
            self._pwd_ee = response["data"]["password"][1]
        except (KeyError, IndexError, TypeError) as e:
            raise TpLinkAuthFailed(f"Не удалось получить ключ RSA для пароля: {e}") from e

    async def _request_auth_keys(self) -> None:
        response = await self._post("login?form=auth", {"operation": "read"}, use_login_stok=True)
        try:
            self._seq = response["data"]["seq"]
            self._nn = response["data"]["key"][0]
            self._ee = response["data"]["key"][1]
        except (KeyError, IndexError, TypeError) as e:
            raise TpLinkAuthFailed(f"Не удалось получить ключ подписи: {e}") from e

    async def login(self) -> None:
        """Выполняет handshake и сохраняет stok/cookie."""
        await self._request_pwd_keys()
        await self._request_auth_keys()

        self._hash = hashlib.sha256(
            (self._username + self._password).encode("utf-8")
        ).hexdigest()
        self._generate_aes_key()

        encrypted_pwd = self._rsa_v15_encrypt(self._password, self._pwd_nn, self._pwd_ee)
        login_data = f"operation=login&password={encrypted_pwd}&confirm=true"
        encrypted_data = self._aes_encrypt(login_data)
        sign = self._build_login_signature(len(encrypted_data))

        response = await self._post(
            "login?form=login",
            {"sign": sign, "data": encrypted_data},
            use_login_stok=True,
        )
        try:
            decrypted = json_loads_safe(self._aes_decrypt(response["data"]))
        except Exception as e:
            raise TpLinkAuthFailed(f"Не удалось расшифровать ответ логина: {e}") from e

        if not decrypted.get("success"):
            errorcode = decrypted.get("data", {}).get("errorcode", "unknown")
            raise TpLinkAuthFailed(f"Логин на роутер не выполнен: {errorcode}")

        self._stok = decrypted["data"]["stok"]
        logger.info("Авторизация на роутер %s успешна", self.base_url)

    async def _request(self, path: str, data: dict[str, Any]) -> dict[str, Any]:
        encrypted_data = self._aes_encrypt(urlencode(data))
        self._hash = hashlib.sha256(encrypted_data.encode()).hexdigest()
        sign = self._build_request_signature(len(encrypted_data))
        response = await self._post(path, {"sign": sign, "data": encrypted_data})
        try:
            return json_loads_safe(self._aes_decrypt(response["data"]))
        except Exception as e:
            raise RouterUnavailable(f"Не удалось расшифровать ответ {path}: {e}") from e

    async def read(self, module: str, form: str, **kwargs: Any) -> dict[str, Any]:
        data = {"operation": "read", **kwargs}
        return await self._request(f"{module}?form={form}", data)

    async def write(self, module: str, form: str, **kwargs: Any) -> dict[str, Any]:
        data = {"operation": "write", **kwargs}
        return await self._request(f"{module}?form={form}", data)

    # -- высший уровень --

    async def get_status_raw(self) -> dict[str, Any]:
        resp = await self.read("admin/status", "all")
        return resp.get("data", {}) if isinstance(resp, dict) else {}

    async def reboot(self) -> None:
        await self.write("admin/system", "reboot")

    async def get_wireless(self, band: str) -> dict[str, Any]:
        """Читает конфигурацию диапазона: wireless_2g / wireless_5g / guest_2g / guest_5g."""
        form_map = {"24": "wireless_2g", "5": "wireless_5g",
                    "guest": "guest_2g", "guest_5g": "guest_5g"}
        form = form_map.get(band, band)
        resp = await self.read("admin/wireless", form)
        return resp.get("data", {}) if isinstance(resp, dict) else {}

    async def set_wireless(self, band: str, enable: bool | None = None,
                           ssid: str | None = None, password: str | None = None) -> None:
        """Запись конфигурации Wi-Fi диапазона с отражением текущих значений."""
        if band == "24":
            form = "wireless_2g"
        elif band == "5":
            form = "wireless_5g"
        elif band == "guest":
            form = "guest_2g"
        else:
            raise RouterUnavailable(f"Неизвестный диапазон: {band}")

        current = await self.get_wireless(band)
        payload: dict[str, Any] = {
            "ssid": ssid if ssid is not None else current.get("ssid", ""),
            "psk_key": password if password is not None else (current.get("psk_key") or ""),
            "enable": ("on" if enable else "off") if enable is not None
                      else ("on" if _to_bool(current.get("enable")) else "off"),
            "encryption": current.get("encryption") or "psk",
            "psk_cipher": current.get("psk_cipher") or "aes",
            "channel": current.get("channel") or "auto",
            "htmode": current.get("htmode") or "auto",
        }
        await self.write("admin/wireless", form, **payload)
        # Guest: параллельно пишем 5-GHz guest-диапазон, если он есть.
        if band == "guest":
            try:
                await self.write("admin/wireless", "guest_5g", **{
                    k: v for k, v in payload.items() if k in
                    ("ssid", "psk_key", "enable", "encryption", "psk_cipher")
                })
            except RouterUnavailable:
                pass  # guest_5g может отсутствовать на некоторых прошивках.


def json_loads_safe(text: str) -> dict[str, Any]:
    import json
    return json.loads(text)


# ---------------------------------------------------------------------------
# Разбор ответов API в наши DTO
# ---------------------------------------------------------------------------

def parse_device_info(info: dict[str, Any], mode: str = "cloud") -> RouterStatus:
    """Толерантный разбор getDeviceBasicFmt — структура может отличаться по прошивкам."""
    data = info.get("data", info) if isinstance(info, dict) else {}
    if not isinstance(data, dict):
        data = {}

    networks: list[WifiNetwork] = []
    for wlan in data.get("wlans") or []:
        if not isinstance(wlan, dict):
            continue
        try:
            idx = int(wlan.get("index", -1))
        except (TypeError, ValueError):
            continue
        key = BAND_KEY.get(idx, str(idx))
        enabled = str(wlan.get("wifi_enable", 1)) not in ("0", "False", "false")
        networks.append(
            WifiNetwork(
                key=key,
                label=BAND_LABEL.get(idx, f"Сеть {idx}"),
                enabled=enabled,
                ssid=str(wlan.get("ssid", "")),
                clients=int(wlan.get("client_num", 0) or 0),
            )
        )

    # Заполняем пропущенные диапазоны пустыми сетями — кнопки всегда на месте.
    present = {net.key for net in networks}
    for idx, key in BAND_KEY.items():
        if key not in present:
            networks.append(WifiNetwork(key=key, label=BAND_LABEL[idx], enabled=False))

    def _s(key: str, default: str = "") -> str:
        val = data.get(key, "")
        return str(val) if val not in (None, "") else default

    status = RouterStatus(
        mode=mode,
        online=str(data.get("device_online", data.get("online", "1"))) not in ("0", "false", "False"),
        alias=_s("alias", _s("device_alias", "Router")),
        model=_s("model", _s("device_model", "TP-Link Archer C80")),
        mac=_s("mac", _s("device_mac")),
        firmware=_s("firmware", _s("fw_version", "—")),
        uptime=_s("uptime", "—"),
        cpu=f"{data.get('cpu_usage', '—')}%",
        memory=f"{data.get('mem_usage', '—')}%",
        wan_ip=_s("wan_ip_addr", _s("ip", "—")),
        download_mbps=float(data.get("download_speed", 0) or 0),
        upload_mbps=float(data.get("upload_speed", 0) or 0),
        networks=networks,
        total_clients=sum(net.clients for net in networks),
    )
    return status


def parse_clients(raw: list[dict[str, Any]]) -> list[ClientDevice]:
    clients: list[ClientDevice] = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        clients.append(
            ClientDevice(
                name=str(item.get("alias", item.get("name", item.get("host", "Неизвестное устройство")))),
                mac=str(item.get("mac", item.get("device_mac", ""))),
                ip=str(item.get("ip", item.get("ip_addr", ""))),
                download_mbps=float(item.get("download_speed", item.get("dl_speed", 0)) or 0),
                upload_mbps=float(item.get("upload_speed", item.get("ul_speed", 0)) or 0),
                band=str(item.get("band", item.get("band_name", ""))),
            )
        )
    return clients


def parse_lan_status(data: dict[str, Any], mode: str = "lan") -> RouterStatus:
    """Разбор ответа admin/status?form=all локального API в RouterStatus."""
    if not isinstance(data, dict):
        data = {}

    def _s(key: str, default: str = "") -> str:
        val = data.get(key, "")
        return str(val) if val not in (None, "") else default

    def _uptime(seconds: Any) -> str:
        try:
            sec = int(float(seconds))
        except (TypeError, ValueError):
            return "—"
        if sec <= 0:
            return "—"
        days, rem = divmod(sec, 86400)
        hours, rem = divmod(rem, 3600)
        minutes = rem // 60
        if days:
            return f"{days} дн {hours} ч"
        if hours:
            return f"{hours} ч {minutes} мин"
        return f"{minutes} мин"

    def _band(prefix: str, label: str, key: str) -> WifiNetwork:
        enabled = _to_bool(data.get(f"{prefix}_enable", False))
        return WifiNetwork(
            key=key,
            label=label,
            enabled=enabled,
            ssid=_s(f"{prefix}_ssid"),
            clients=0,  # считаем устройства отдельно
        )

    networks = [
        _band("wireless_2g", "Wi-Fi 2.4 ГГц", "24"),
        _band("wireless_5g", "Wi-Fi 5 ГГц", "5"),
        _band("guest_2g", "Guest Wi-Fi", "guest"),
    ]

    # Считаем устройства по проводным и беспроводным спискам.
    wired = data.get("access_devices_wired") or []
    wireless = data.get("access_devices_wireless_host") or []
    counts = {"24": 0, "5": 0, "guest": 0}
    for dev in wireless:
        if not isinstance(dev, dict):
            continue
        wt = str(dev.get("wire_type", ""))
        if "2.4" in wt or wt == "2G":
            counts["24"] += 1
        elif "5" in wt:
            counts["5"] += 1
        else:
            counts["guest"] += 1
    # проводные устройства не относятся к Wi-Fi-диапазонам.

    networks = [
        WifiNetwork(net.key, net.label, net.enabled, net.ssid, counts.get(net.key, 0))
        for net in networks
    ]

    total_clients = len(wired) + len(wireless)

    return RouterStatus(
        mode=mode,
        online=True,
        alias="TP-Link Archer C80",
        model="TP-Link Archer C80",
        mac=_s("lan_macaddr") or _s("wan_macaddr"),
        firmware=_s("firmware_ver", _s("fw_version", "—")),
        uptime=_uptime(data.get("wan_ipv4_uptime")),
        cpu=f"{data.get('cpu_usage', '—')}%",
        memory=f"{data.get('mem_usage', '—')}%",
        wan_ip=_s("wan_ipv4_ipaddr", "—"),
        networks=networks,
        total_clients=total_clients,
    )


def parse_lan_clients(data: dict[str, Any]) -> list[ClientDevice]:
    """Разбор списка устройств из admin/status?form=all."""
    clients: list[ClientDevice] = []
    for dev in (data.get("access_devices_wired") or []):
        if isinstance(dev, dict):
            clients.append(ClientDevice(
                name=str(dev.get("hostname", "")) or "проводное устройство",
                mac=str(dev.get("macaddr", "")),
                ip=str(dev.get("ipaddr", "")),
                band="провод",
            ))
    for dev in (data.get("access_devices_wireless_host") or []):
        if not isinstance(dev, dict):
            continue
        wt = str(dev.get("wire_type", ""))
        band = "2.4 ГГц" if ("2.4" in wt or wt == "2G") else "5 ГГц"
        clients.append(ClientDevice(
            name=str(dev.get("hostname", "")) or "беспроводное устройство",
            mac=str(dev.get("macaddr", "")),
            ip=str(dev.get("ipaddr", "")),
            band=band,
        ))
    return clients


# ---------------------------------------------------------------------------
# Демо-роутер (mock mode)
# ---------------------------------------------------------------------------

class MockRouter:
    """Виртуальная модель Archer C80 с изменяемым состоянием — для теста без оборудования."""

    mode = "mock"

    def __init__(self) -> None:
        self.networks: dict[str, WifiNetwork] = {
            "24": WifiNetwork("24", "Wi-Fi 2.4 ГГц", True, "HomeWiFi-2G", 3),
            "5": WifiNetwork("5", "Wi-Fi 5 ГГц", True, "HomeWiFi-5G", 2),
            "guest": WifiNetwork("guest", "Guest Wi-Fi", False, "GuestWiFi", 0),
        }
        self.clients: list[ClientDevice] = [
            ClientDevice("Alex iPhone", "A8:3B:C2:11:22:01", "192.168.1.10", 87.4, 21.3, "5 ГГц"),
            ClientDevice("Maria MacBook", "A8:3B:C2:11:22:02", "192.168.1.11", 240.8, 55.6, "5 ГГц"),
            ClientDevice("Living-room TV", "A8:3B:C2:11:22:03", "192.168.1.12", 45.2, 3.1, "2.4 ГГц"),
            ClientDevice("Smart TV box", "A8:3B:C2:11:22:04", "192.168.1.13", 18.9, 4.7, "2.4 ГГц"),
            ClientDevice("Printer HP", "A8:3B:C2:11:22:05", "192.168.1.14", 1.2, 0.8, "2.4 ГГц"),
        ]
        self._reboots = 0

    async def _latency(self) -> None:
        await asyncio.sleep(0.5)

    async def get_status(self, force: bool = False) -> RouterStatus:
        await self._latency()
        total = sum(net.clients for net in self.networks.values())
        return RouterStatus(
            mode="mock",
            online=True,
            alias="Архив-C80",
            model="TP-Link Archer C80",
            mac="50:3E:AA:AB:CD:EF",
            firmware="1.0.9 Build 240311 Rel.20118n",
            uptime="12 дней 4 часа",
            cpu="17%",
            memory="34%",
            wan_ip="185.124.221.45",
            download_mbps=round(120.5 + (self._reboots % 3) * 12.3, 1),
            upload_mbps=round(45.2 + (self._reboots % 2) * 6.8, 1),
            networks=[self.networks[key] for key in ("24", "5", "guest")],
            total_clients=total,
        )

    async def get_clients(self) -> list[ClientDevice]:
        await asyncio.sleep(0.4)
        return [
            ClientDevice(c.name, c.mac, c.ip,
                         round(c.download_mbps * (0.9 + 0.2 * (i % 3)), 1),
                         round(c.upload_mbps * (0.9 + 0.2 * (i % 2)), 1), c.band)
            for i, c in enumerate(self.clients)
        ]

    async def reboot(self) -> None:
        await asyncio.sleep(1.2)
        self._reboots += 1
        logger.info("MockRouter: перезагрузка выполнена (#%d)", self._reboots)

    async def set_wifi_enabled(self, key: str, enabled: bool) -> WifiNetwork:
        await self._latency()
        if key not in self.networks:
            raise RouterUnavailable(f"Неизвестный диапазон: {key}")
        net = self.networks[key]
        self.networks[key] = WifiNetwork(net.key, net.label, enabled, net.ssid, net.clients)
        return self.networks[key]

    async def set_wifi_credentials(self, key: str, ssid: str, password: str) -> WifiNetwork:
        await self._latency()
        if key not in self.networks:
            raise RouterUnavailable(f"Неизвестный диапазон: {key}")
        net = self.networks[key]
        self.networks[key] = WifiNetwork(net.key, net.label, net.enabled, ssid, net.clients)
        logger.info("MockRouter: сеть %s обновлена (SSID=%s)", key, ssid)
        return self.networks[key]


# ---------------------------------------------------------------------------
# Сервис: cloud-клиент, lan-клиент или mock, с кэшем статуса
# ---------------------------------------------------------------------------

class RouterService:
    """Единая точка доступа к роутеру для обработчиков."""

    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._cloud: TpLinkCloudClient | None = None
        self._lan: TpLinkLanClient | None = None
        self._device_id: str = ""
        self._mock = MockRouter()
        self._cache: RouterStatus | None = None
        self._cache_ts: float = 0.0
        self._lock = asyncio.Lock()

    @property
    def mode(self) -> str:
        """cloud | lan | mock.

        lan — при TPLINK_MODE=lan и заданных TPLINK_HOST + TPLINK_PASSWORD.
        cloud — при TPLINK_MODE=cloud и заданных TPLINK_USER + TPLINK_PASSWORD.
        Иначе mock.
        """
        if self._settings.tplink_mode == "lan" and self._settings.tplink_host and self._settings.tplink_password:
            return "lan"
        if self._settings.tplink_mode == "cloud" and self._settings.tplink_user and self._settings.tplink_password:
            return "cloud"
        return "mock"

    def mode_reason(self) -> str:
        """Диагностика: почему выбран текущий режим роутера (для логов)."""
        if self._settings.tplink_mode == "lan":
            if not self._settings.tplink_host:
                return "TPLINK_HOST не задан (IP роутера, например 192.168.0.1)"
            if not self._settings.tplink_password:
                return "TPLINK_PASSWORD не задан (пароль роутера)"
            return "lan — реальный роутер через локальный HTTP-API"
        if self._settings.tplink_mode == "cloud":
            if not self._settings.tplink_user:
                return "TPLINK_USER не задан"
            if not self._settings.tplink_password:
                return "TPLINK_PASSWORD не задан"
            return "cloud — реальный роутер через TP-Link Cloud (устаревший API)"
        return "TPLINK_MODE != lan/cloud (в .env нужно TPLINK_MODE=lan или cloud)"

    async def _get_cloud(self) -> TpLinkCloudClient:
        async with self._lock:
            if self._cloud is None:
                client = TpLinkCloudClient(
                    self._settings.tplink_user, self._settings.tplink_password,
                    endpoint=self._settings.tplink_cloud_url or CLOUD_ENDPOINT,
                )
                await client.login()
                self._device_id = await client.select_device(self._settings.tplink_alias)
                self._cloud = client
            return self._cloud

    async def _get_lan(self) -> TpLinkLanClient:
        async with self._lock:
            if self._lan is None:
                client = TpLinkLanClient(
                    self._settings.tplink_host,
                    username=self._settings.tplink_admin or "admin",
                    password=self._settings.tplink_password,
                )
                await client.login()
                self._lan = client
            return self._lan

    async def get_status(self, force: bool = False) -> RouterStatus:
        mode = self.mode
        if mode == "mock":
            return await self._mock.get_status(force)

        ttl = max(10, self._settings.stats_interval)
        if not force and self._cache is not None and (time.monotonic() - self._cache_ts) < ttl:
            return self._cache

        try:
            if mode == "lan":
                client = await self._get_lan()
                data = await client.get_status_raw()
                status = parse_lan_status(data, mode="lan")
            else:
                client = await self._get_cloud()
                info = await client.device_info(self._device_id)
                status = parse_device_info(info, mode="cloud")
        except TpLinkAuthFailed:
            await self._reset_clients()
            raise
        except TpLinkError as exc:
            await self._reset_clients()
            raise RouterUnavailable(str(exc)) from exc

        self._cache = status
        self._cache_ts = time.monotonic()
        return status

    async def get_clients(self) -> list[ClientDevice]:
        mode = self.mode
        if mode == "mock":
            return await self._mock.get_clients()

        try:
            if mode == "lan":
                client = await self._get_lan()
                data = await client.get_status_raw()
                return parse_lan_clients(data)
            client = await self._get_cloud()
            raw = await client.get_clients(self._device_id)
            return parse_clients(raw)
        except TpLinkAuthFailed:
            await self._reset_clients()
            raise
        except TpLinkError as exc:
            await self._reset_clients()
            raise RouterUnavailable(str(exc)) from exc

    async def reboot(self) -> None:
        mode = self.mode
        if mode == "mock":
            await self._mock.reboot()
            return
        try:
            if mode == "lan":
                client = await self._get_lan()
                await client.reboot()
            else:
                client = await self._get_cloud()
                await client.reboot(self._device_id)
        except TpLinkAuthFailed:
            await self._reset_clients()
            raise
        except TpLinkError as exc:
            await self._reset_clients()
            raise RouterUnavailable(str(exc)) from exc

    async def set_wifi_enabled(self, band: str, enabled: bool) -> None:
        mode = self.mode
        if mode == "mock":
            await self._mock.set_wifi_enabled(band, enabled)
            return
        if mode == "lan":
            try:
                client = await self._get_lan()
                await client.set_wireless(band, enable=enabled)
            except TpLinkAuthFailed:
                await self._reset_clients()
                raise
            except TpLinkError as exc:
                await self._reset_clients()
                raise RouterUnavailable(str(exc)) from exc
            return
        if band not in BAND_INDEX:
            raise RouterUnavailable(f"Неизвестный диапазон: {band}")
        try:
            client = await self._get_cloud()
            status = await self.get_status(force=True)
            net = status.network(band)
            ssid = net.ssid if net else ""
            await client.set_wifi(self._device_id, BAND_INDEX[band], ssid=ssid, enable=enabled)
        except TpLinkAuthFailed:
            await self._reset_clients()
            raise
        except TpLinkError as exc:
            await self._reset_clients()
            raise RouterUnavailable(str(exc)) from exc

    async def set_wifi_credentials(self, band: str, ssid: str, password: str) -> None:
        mode = self.mode
        if mode == "mock":
            await self._mock.set_wifi_credentials(band, ssid, password)
            return
        if mode == "lan":
            try:
                client = await self._get_lan()
                await client.set_wireless(band, ssid=ssid, password=password)
            except TpLinkAuthFailed:
                await self._reset_clients()
                raise
            except TpLinkError as exc:
                await self._reset_clients()
                raise RouterUnavailable(str(exc)) from exc
            return
        if band not in BAND_INDEX:
            raise RouterUnavailable(f"Неизвестный диапазон: {band}")
        try:
            client = await self._get_cloud()
            await client.set_wifi(self._device_id, BAND_INDEX[band], ssid=ssid, password=password)
        except TpLinkAuthFailed:
            await self._reset_clients()
            raise
        except TpLinkError as exc:
            await self._reset_clients()
            raise RouterUnavailable(str(exc)) from exc

    async def _reset_clients(self) -> None:
        """Сбрасываем сессии — спросим логин при следующем запросе."""
        async with self._lock:
            if self._cloud is not None:
                await self._cloud._close()
                self._cloud = None
            if self._lan is not None:
                await self._lan._close()
                self._lan = None
            self._device_id = ""
            self._cache = None
            self._cache_ts = 0.0
