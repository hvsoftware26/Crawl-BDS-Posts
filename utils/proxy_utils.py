from __future__ import annotations

import ipaddress
import json
import time
from dataclasses import dataclass
from urllib.parse import quote, urlparse

import requests


NO_PROXY_VALUES = {
    "",
    "none",
    "no",
    "false",
    "0",
}


@dataclass(frozen=True)
class ProxyConfig:
    scheme: str
    host: str
    port: int
    username: str = ""
    password: str = ""

    @property
    def host_for_url(self) -> str:
        try:
            if isinstance(ipaddress.ip_address(self.host), ipaddress.IPv6Address):
                return f"[{self.host}]"
        except ValueError:
            pass
        return self.host

    @property
    def server(self) -> str:
        return f"{self.scheme}://{self.host_for_url}:{self.port}"

    @property
    def has_auth(self) -> bool:
        return bool(self.username or self.password)

    @property
    def requests_url(self) -> str:
        if not self.has_auth:
            return self.server

        username = quote(self.username, safe="")
        password = quote(self.password, safe="")
        return f"{self.scheme}://{username}:{password}@{self.host_for_url}:{self.port}"


def is_no_proxy(proxy_value: str | None) -> bool:
    normalized = str(proxy_value or "").strip().casefold()
    return normalized in NO_PROXY_VALUES


def parse_proxy(proxy_value: str | None) -> ProxyConfig | None:
    raw_proxy = str(proxy_value or "").strip()
    if is_no_proxy(raw_proxy):
        return None

    scheme = "http"
    host = ""
    port = ""
    username = ""
    password = ""

    if "://" in raw_proxy:
        parsed = urlparse(raw_proxy)
        scheme = parsed.scheme or scheme
        host = parsed.hostname or ""
        port = str(parsed.port or "")
        username = parsed.username or ""
        password = parsed.password or ""
    else:
        parts = raw_proxy.split(":")
        if len(parts) < 2:
            raise ValueError("Proxy phải có dạng ip:port hoặc ip:port:user:pass")

        host = parts[0].strip()
        port = parts[1].strip()
        if len(parts) >= 4:
            username = parts[2].strip()
            password = ":".join(parts[3:]).strip()

    if not host or not port:
        raise ValueError("Proxy thiếu host hoặc port")

    try:
        port_number = int(port)
    except ValueError as exc:
        raise ValueError("Proxy port không hợp lệ") from exc

    if port_number <= 0 or port_number > 65535:
        raise ValueError("Proxy port không hợp lệ")

    return ProxyConfig(
        scheme=scheme,
        host=host,
        port=port_number,
        username=username,
        password=password,
    )


def mask_proxy(proxy_value: str | None) -> str:
    config = parse_proxy(proxy_value)
    if not config:
        return ""

    if config.has_auth:
        return f"{config.host}:{config.port}:***:***"

    return f"{config.host}:{config.port}"


def build_playwright_proxy(proxy_value: str | None) -> dict | None:
    config = parse_proxy(proxy_value)
    if not config:
        return None

    proxy = {"server": config.server}
    if config.username:
        proxy["username"] = config.username
    if config.password:
        proxy["password"] = config.password
    return proxy


def build_chrome_proxy_server(proxy_value: str | None) -> str:
    config = parse_proxy(proxy_value)
    if not config:
        return ""

    return config.server


def build_requests_proxies(proxy_value: str | None) -> dict | None:
    config = parse_proxy(proxy_value)
    if not config:
        return None

    proxy_url = config.requests_url
    return {
        "http": proxy_url,
        "https": proxy_url,
    }


def _safe_proxy_error(error: Exception, config: ProxyConfig) -> str:
    error_text = str(error)
    for secret in (config.username, config.password):
        if secret:
            error_text = error_text.replace(secret, "***")
    return error_text


PUBLIC_IP_CHECK_URL = "https://api.ip2location.io/"


def _extract_ip_from_body(raw_body: str) -> str:
    try:
        payload = json.loads(str(raw_body or "").strip())
    except (json.JSONDecodeError, ValueError):
        return ""

    ip_value = str(payload.get("ip") or "").strip() if isinstance(payload, dict) else ""
    try:
        return str(ipaddress.ip_address(ip_value))
    except ValueError:
        return ""


def _fetch_public_ip(proxies: dict | None, timeout: int, session=None) -> str:
    http = session or requests.Session()
    try:
        response = http.get(
            PUBLIC_IP_CHECK_URL,
            headers={"accept": "*/*", "user-agent": "Mozilla/5.0"},
            proxies=proxies,
            timeout=timeout,
        )
    except requests.RequestException:
        return ""
    if response.status_code >= 400:
        return ""
    return _extract_ip_from_body(response.text)


def check_proxy_status(
    proxy_value: str | None,
    timeout: int = 12,
    session=None,
) -> dict:
    """
    Kiểm tra proxy theo LUỒNG 1 Bước 1:
    - Lấy IP public của máy hiện tại và IP public khi đi qua proxy.
    - Coi proxy hết hạn/lỗi nếu: không kết nối được, timeout, lỗi xác thực,
      không lấy được IP qua proxy, hoặc IP qua proxy trùng IP máy hiện tại.

    Trả về dict: {ok, message, machine_ip, proxy_ip}.
    IPv4 và IPv6 đều được hỗ trợ nhờ ProxyConfig.host_for_url.
    """
    config = parse_proxy(proxy_value)
    if not config:
        return {
            "ok": True,
            "message": "Không dùng proxy",
            "machine_ip": "",
            "proxy_ip": "",
        }

    http = session or requests.Session()
    machine_ip = _fetch_public_ip(None, timeout=timeout, session=http)

    try:
        proxies = build_requests_proxies(proxy_value)
    except Exception as exc:
        return {
            "ok": False,
            "message": f"Proxy không hợp lệ: {_safe_proxy_error(exc, config)}",
            "machine_ip": machine_ip,
            "proxy_ip": "",
        }

    proxy_ip = ""
    try:
        response = http.get(
            PUBLIC_IP_CHECK_URL,
            headers={"accept": "*/*", "user-agent": "Mozilla/5.0"},
            proxies=proxies,
            timeout=timeout,
        )
    except requests.exceptions.ProxyError as exc:
        return {
            "ok": False,
            "message": f"Proxy lỗi hoặc bị reset: {_safe_proxy_error(exc, config)}",
            "machine_ip": machine_ip,
            "proxy_ip": "",
        }
    except requests.exceptions.Timeout as exc:
        return {
            "ok": False,
            "message": f"Proxy timeout sau {timeout}s: {_safe_proxy_error(exc, config)}",
            "machine_ip": machine_ip,
            "proxy_ip": "",
        }
    except requests.exceptions.RequestException as exc:
        return {
            "ok": False,
            "message": f"Không kết nối được qua proxy: {_safe_proxy_error(exc, config)}",
            "machine_ip": machine_ip,
            "proxy_ip": "",
        }

    if response.status_code == 407:
        return {
            "ok": False,
            "message": "Proxy yêu cầu xác thực hoặc sai user/pass.",
            "machine_ip": machine_ip,
            "proxy_ip": "",
        }
    if response.status_code >= 400:
        return {
            "ok": False,
            "message": f"Proxy trả về HTTP {response.status_code}.",
            "machine_ip": machine_ip,
            "proxy_ip": "",
        }

    proxy_ip = _extract_ip_from_body(response.text)
    if not proxy_ip:
        return {
            "ok": False,
            "message": "Không lấy được IP public qua proxy.",
            "machine_ip": machine_ip,
            "proxy_ip": "",
        }

    if machine_ip and proxy_ip == machine_ip:
        return {
            "ok": False,
            "message": f"IP qua proxy trùng IP máy hiện tại ({proxy_ip}), proxy không hoạt động.",
            "machine_ip": machine_ip,
            "proxy_ip": proxy_ip,
        }

    return {
        "ok": True,
        "message": f"Proxy hoạt động, IP: {proxy_ip}",
        "machine_ip": machine_ip,
        "proxy_ip": proxy_ip,
    }


def _add_cache_buster(url: str) -> str:
    separator = "&" if "?" in url else "?"
    return f"{url}{separator}_={int(time.time() * 1000)}"


def _proxy_origin_matches(expected_host: str, origin: str) -> bool | None:
    """
    True  = IP trong browser khớp host proxy.
    False = không khớp.
    None  = không kiểm tra được (proxy là domain, không phải IP số).
    """
    if not expected_host or not origin:
        return False
    try:
        expected_ip = ipaddress.ip_address(expected_host)
    except ValueError:
        return None
    try:
        return ipaddress.ip_address(origin) == expected_ip
    except ValueError:
        return False


def verify_browser_proxy_ip(
    page,
    proxy_value: str | None,
    timeout_ms: int = 12000,
    attempts: int = 2,
    delay_seconds: float = 0.5,
) -> dict:
    """
    Verify IP NGAY TRONG browser Playwright (điều hướng page tới link check IP,
    đọc IP trả về). Khác check_proxy_status (dùng requests) ở chỗ nó xác nhận
    chính trình duyệt đang đi qua proxy trước khi crawl.

    Trả về dict: {ok, origin, matches_expected, source_url, status, error}.
    """
    config = parse_proxy(proxy_value)
    total_attempts = max(1, int(attempts or 1))
    last_result = None

    for attempt_index in range(total_attempts):
        source_url = _add_cache_buster(PUBLIC_IP_CHECK_URL)
        try:
            response = page.goto(source_url, wait_until="domcontentloaded", timeout=timeout_ms)
            status = response.status if response else 0
            raw_body = (page.text_content("body", timeout=timeout_ms) or "").strip()
            origin = _extract_ip_from_body(raw_body)
            matches_expected = _proxy_origin_matches(config.host, origin) if config else True

            if status >= 400:
                last_result = {
                    "ok": False,
                    "origin": origin,
                    "matches_expected": matches_expected,
                    "source_url": PUBLIC_IP_CHECK_URL,
                    "status": status,
                    "error": f"HTTP {status}",
                }
            else:
                last_result = {
                    "ok": bool(origin) and matches_expected is not False,
                    "origin": origin,
                    "matches_expected": matches_expected,
                    "source_url": PUBLIC_IP_CHECK_URL,
                    "status": status,
                    "error": "" if origin else "no_ip_in_response",
                }
        except Exception as exc:
            last_result = {
                "ok": False,
                "origin": "",
                "matches_expected": False,
                "source_url": PUBLIC_IP_CHECK_URL,
                "status": 0,
                "error": str(exc),
            }

        if last_result.get("ok"):
            return last_result
        if attempt_index < total_attempts - 1:
            time.sleep(max(0.0, delay_seconds))

    return last_result or {
        "ok": False,
        "origin": "",
        "matches_expected": False,
        "source_url": PUBLIC_IP_CHECK_URL,
        "status": 0,
        "error": "no_result",
    }


def test_proxy_connectivity(
    proxy_value: str | None,
    test_url: str = "https://www.facebook.com/",
    timeout: int = 8,
    attempts: int = 1,
    session=None,
) -> dict:
    config = parse_proxy(proxy_value)
    if not config:
        return {
            "ok": True,
            "message": "Không dùng proxy",
            "status_code": None,
        }

    http = session or requests.Session()
    total_attempts = max(1, int(attempts or 1))
    last_result = None

    for attempt_number in range(1, total_attempts + 1):
        try:
            response = http.get(
                test_url,
                headers={
                    "accept": "*/*",
                    "user-agent": "Mozilla/5.0",
                },
                proxies=build_requests_proxies(proxy_value),
                timeout=timeout,
                allow_redirects=False,
            )
        except requests.exceptions.ProxyError as exc:
            last_result = {
                "ok": False,
                "message": f"Proxy lỗi hoặc bị reset: {_safe_proxy_error(exc, config)}",
                "status_code": None,
                "attempts": attempt_number,
            }
            continue
        except requests.exceptions.Timeout as exc:
            last_result = {
                "ok": False,
                "message": f"Proxy timeout sau {timeout}s: {_safe_proxy_error(exc, config)}",
                "status_code": None,
                "attempts": attempt_number,
            }
            continue
        except requests.exceptions.RequestException as exc:
            last_result = {
                "ok": False,
                "message": f"Không kết nối được qua proxy: {_safe_proxy_error(exc, config)}",
                "status_code": None,
                "attempts": attempt_number,
            }
            continue

        if response.status_code == 407:
            return {
                "ok": False,
                "message": "Proxy yêu cầu xác thực hoặc sai user/pass.",
                "status_code": response.status_code,
                "attempts": attempt_number,
            }

        if response.status_code >= 400:
            last_result = {
                "ok": False,
                "message": f"Proxy trả về HTTP {response.status_code}.",
                "status_code": response.status_code,
                "attempts": attempt_number,
            }
            continue

        return {
            "ok": True,
            "message": f"Proxy kết nối được, HTTP {response.status_code}.",
            "status_code": response.status_code,
            "attempts": attempt_number,
        }

    return last_result or {
        "ok": False,
        "message": "Không kết nối được qua proxy.",
        "status_code": None,
        "attempts": total_attempts,
    }
