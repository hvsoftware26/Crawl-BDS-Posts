from __future__ import annotations


def mask_secret(value: str | None, prefix: int = 6, suffix: int = 4) -> str:
    secret = str(value or "").strip()
    if not secret:
        return ""

    if len(secret) <= prefix + suffix:
        return "*" * len(secret)

    return f"{secret[:prefix]}...{secret[-suffix:]}"


def mask_cookie(cookie_value: str | None) -> str:
    parts = []
    for raw_part in str(cookie_value or "").split(";"):
        key, separator, value = raw_part.strip().partition("=")
        if not key:
            continue

        if not separator:
            parts.append(key)
            continue

        parts.append(f"{key}={mask_secret(value, prefix=2, suffix=2)}")

    return "; ".join(parts)
