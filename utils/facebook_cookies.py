from __future__ import annotations

import time

FACEBOOK_COOKIE_DOMAINS = (".facebook.com", "facebook.com", ".m.facebook.com", "m.facebook.com")
PERSISTENT_COOKIE_SECONDS = 60 * 60 * 24 * 365


def parse_cookie_header(cookie_header: str) -> dict[str, str]:
    cookies = {}
    for part in str(cookie_header or "").split(";"):
        name, separator, value = part.strip().partition("=")
        if not separator:
            continue
        name = name.strip()
        if not name:
            continue
        cookies[name] = value.strip()
    return cookies


def build_facebook_playwright_cookies(cookie_header: str) -> list[dict]:
    parsed = parse_cookie_header(cookie_header)
    playwright_cookies = []
    expires_at = int(time.time()) + PERSISTENT_COOKIE_SECONDS
    for domain in FACEBOOK_COOKIE_DOMAINS:
        for name, value in parsed.items():
            playwright_cookies.append(
                {
                    "name": name,
                    "value": value,
                    "domain": domain,
                    "path": "/",
                    "secure": True,
                    "httpOnly": name in {"xs", "fr", "datr", "sb"},
                    "sameSite": "Lax",
                    "expires": expires_at,
                }
            )
    return playwright_cookies


def has_facebook_login_cookie(cookie_header: str) -> bool:
    parsed = parse_cookie_header(cookie_header)
    return bool(parsed.get("c_user") and parsed.get("xs"))
