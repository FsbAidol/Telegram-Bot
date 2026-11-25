"""Управление роутером TP-Link Archer C80 через TP-Link Cloud API.

Протокол: https://a1.tplinkcloud.com — тот же облачный API, который использует
приложение TP-Link Tether для управления роутерами Archer C80.

Примерный цикл запросов:
    1. login          — авторизация (пароль отдаётся как MD5), получаем dp_id, uid
                       и cookie TP_SESSIONID (aiohttp CookieJar сохраняет её сам).
    2. tplinkcloud    — все последующие методы идут в одном пакете:
                       {"method": "tplinkcloud",
                        "params": {"dp_id": ..., "uid": ...,
                                   "requestData": {"<method>": {...}}}}

Методы (иммена по протоколу Tether/Cloud для роутеров):
    getDeviceList          — список устройств аккаунта
    getDeviceBasicFmt      — статус роутера (сети, загрузка, uptime, WAN IP)
    setDeviceWifi          — смена SSID/пароля диапазона (index: 0=2.4G, 1=5G, 2=Guest)
    reboot                 — перезагрузка
    getDeviceClientList    — список подключённых клиентов (с источником ошибки — альтернативы)

Если аккаунт TP-Link не задан или TPLINK_MODE=mock — работает MockRouter:
полноценная виртуальная модель роутера для демонстрации и тестов.
"""
from __future__ import annotations

import asyncio
import hashlib
import logging
import time
from dataclasses import dataclass, field
from typing import Any

import aiohttp

from bot.config import Settings

logger = logging.getLogger(__name__)

CLOUD_ENDPOINT = "https://a1.tplinkcloud.com"

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
    """Ошибка при работе с TP-Link Cloud."""


class TpLinkAuthFailed(TpLinkError):
    """Неверные данные аккаунта TP-Link."""


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
# Клиент TP-Link Cloud API
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
        """Выбор роутера: по алиасу, иначе первый устройство аккаунта."""
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
# Сервис: cloud-клиент или mock, с кэшем статуса
# ---------------------------------------------------------------------------

class RouterService:
    """Единая точка доступа к роутеру для обработчиков."""

    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._client: TpLinkCloudClient | None = None
        self._device_id: str = ""
        self._mock = MockRouter()
        self._cache: RouterStatus | None = None
        self._cache_ts: float = 0.0
        self._lock = asyncio.Lock()

    @property
    def mode(self) -> str:
        """cloud — только если включен режим и заданы данные аккаунта."""
        return "cloud" if (
            self._settings.tplink_mode == "cloud" and self._settings.tplink_user
            and self._settings.tplink_password
        ) else "mock"

    async def _get_client(self) -> TpLinkCloudClient:
        async with self._lock:
            if self._client is None:
                client = TpLinkCloudClient(self._settings.tplink_user, self._settings.tplink_password)
                await client.login()
                self._device_id = await client.select_device(self._settings.tplink_alias)
                self._client = client
            return self._client

    async def get_status(self, force: bool = False) -> RouterStatus:
        if self.mode == "mock":
            return await self._mock.get_status(force)

        ttl = max(10, self._settings.stats_interval)
        if not force and self._cache is not None and (time.monotonic() - self._cache_ts) < ttl:
            return self._cache

        try:
            client = await self._get_client()
            info = await client.device_info(self._device_id)
            status = parse_device_info(info, mode="cloud")
        except TpLinkAuthFailed:
            await self._reset_client()
            raise
        except TpLinkError as exc:
            await self._reset_client()
            raise RouterUnavailable(str(exc)) from exc

        self._cache = status
        self._cache_ts = time.monotonic()
        return status

    async def get_clients(self) -> list[ClientDevice]:
        if self.mode == "mock":
            return await self._mock.get_clients()

        try:
            client = await self._get_client()
            raw = await client.get_clients(self._device_id)
            return parse_clients(raw)
        except TpLinkAuthFailed:
            await self._reset_client()
            raise
        except TpLinkError as exc:
            await self._reset_client()
            raise RouterUnavailable(str(exc)) from exc

    async def reboot(self) -> None:
        if self.mode == "mock":
            await self._mock.reboot()
            return
        try:
            client = await self._get_client()
            await client.reboot(self._device_id)
        except TpLinkAuthFailed:
            await self._reset_client()
            raise
        except TpLinkError as exc:
            await self._reset_client()
            raise RouterUnavailable(str(exc)) from exc

    async def set_wifi_enabled(self, band: str, enabled: bool) -> None:
        if self.mode == "mock":
            await self._mock.set_wifi_enabled(band, enabled)
            return
        if band not in BAND_INDEX:
            raise RouterUnavailable(f"Неизвестный диапазон: {band}")
        try:
            client = await self._get_client()
            status = await self.get_status(force=True)
            net = status.network(band)
            ssid = net.ssid if net else ""
            await client.set_wifi(self._device_id, BAND_INDEX[band], ssid=ssid, enable=enabled)
        except TpLinkAuthFailed:
            await self._reset_client()
            raise
        except TpLinkError as exc:
            await self._reset_client()
            raise RouterUnavailable(str(exc)) from exc

    async def set_wifi_credentials(self, band: str, ssid: str, password: str) -> None:
        if self.mode == "mock":
            await self._mock.set_wifi_credentials(band, ssid, password)
            return
        if band not in BAND_INDEX:
            raise RouterUnavailable(f"Неизвестный диапазон: {band}")
        try:
            client = await self._get_client()
            await client.set_wifi(self._device_id, BAND_INDEX[band], ssid=ssid, password=password)
        except TpLinkAuthFailed:
            await self._reset_client()
            raise
        except TpLinkError as exc:
            await self._reset_client()
            raise RouterUnavailable(str(exc)) from exc

    async def _reset_client(self) -> None:
        """Сбрасываем сессию — спросим логин при следующем запросе."""
        async with self._lock:
            if self._client is not None:
                await self._client._close()
                self._client = None
            self._device_id = ""
            self._cache = None
            self._cache_ts = 0.0
