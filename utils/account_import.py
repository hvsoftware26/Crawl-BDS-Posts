from __future__ import annotations

from utils.facebook_cookies import has_facebook_login_cookie, parse_cookie_header
from utils.proxy_utils import is_no_proxy, parse_proxy


SUPPORTED_ACCOUNT_IMPORT_FORMATS = (
    "uid|pass|2FA|cookie|token|mail|pass mail",
    "uid|pass|2FA|cookie|token|mail|pass mail|Proxy",
    "uid|pass|cookie|token|mail|pass mail",
    "uid|pass|cookie|token|mail|pass mail|Proxy",
)


def supported_account_import_formats_text() -> str:
    return "\n".join(SUPPORTED_ACCOUNT_IMPORT_FORMATS)


def parse_account_import_line(line: str) -> dict[str, str]:
    parts = [part.strip() for part in str(line or "").split("|")]

    if len(parts) == 8:
        uid, password, twofa, cookie, token, email, mail_password, proxy = parts
    elif len(parts) == 7:
        if _looks_like_cookie(parts[2]):
            uid, password, cookie, token, email, mail_password, proxy = parts
            twofa = ""
        else:
            uid, password, twofa, cookie, token, email, mail_password = parts
            proxy = ""
    elif len(parts) == 6:
        uid, password, cookie, token, email, mail_password = parts
        twofa = ""
        proxy = ""
    else:
        raise ValueError(
            "Dinh dang dung:\n"
            f"{supported_account_import_formats_text()}"
        )

    proxy = proxy or ""
    _validate_imported_account(
        uid=uid,
        cookie=cookie,
        token=token,
        email=email,
        proxy=proxy,
    )

    return {
        "uid": uid,
        "account_name": uid,
        "proxy": proxy.strip(),
        "email": email.strip(),
        "password": password.strip(),
        "twofa": twofa.strip(),
        "cookie": cookie.strip(),
        "token": token.strip(),
        "mail_password": mail_password.strip(),
    }


def _looks_like_cookie(value: str) -> bool:
    parsed = parse_cookie_header(value)
    return bool(parsed) and (
        "c_user" in parsed
        or "xs" in parsed
        or ";" in str(value or "")
    )


def _validate_imported_account(
    *,
    uid: str,
    cookie: str,
    token: str,
    email: str,
    proxy: str,
) -> None:
    if not uid:
        raise ValueError("Thieu UID")
    if not uid.isdigit():
        raise ValueError("UID phai la so")
    if not cookie:
        raise ValueError("Thieu cookie")
    if not has_facebook_login_cookie(cookie):
        raise ValueError("Cookie phai co c_user va xs")

    cookie_uid = parse_cookie_header(cookie).get("c_user", "").strip()
    if cookie_uid and cookie_uid != uid:
        raise ValueError("UID khong khop c_user trong cookie")

    if not token:
        raise ValueError("Thieu token")
    if not email:
        raise ValueError("Thieu mail")

    if not is_no_proxy(proxy):
        parse_proxy(proxy)
