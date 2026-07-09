from __future__ import annotations

import base64
import hashlib
import hmac
import logging
import re
import struct
import time
from urllib.parse import parse_qs, urlparse


logger = logging.getLogger(__name__)
DEFAULT_PERIOD_SECONDS = 30
DEFAULT_DIGITS = 6
DEFAULT_MIN_SECONDS_REMAINING = 8


def _extract_secret(twofa: str) -> str:
    value = str(twofa or "").strip()
    if not value:
        raise ValueError("Missing 2FA secret")

    if value.lower().startswith("otpauth://"):
        parsed = urlparse(value)
        value = parse_qs(parsed.query).get("secret", [""])[0]

    value = re.sub(r"[\s-]+", "", value).rstrip("=")
    if not value:
        raise ValueError("Missing 2FA secret")

    return value.upper()


def _decode_base32_secret(secret: str) -> bytes:
    normalized_secret = _extract_secret(secret)
    padding = "=" * ((8 - len(normalized_secret) % 8) % 8)
    return base64.b32decode(normalized_secret + padding, casefold=True)


def seconds_remaining(period: int = DEFAULT_PERIOD_SECONDS, now: float | None = None) -> float:
    current_time = time.time() if now is None else float(now)
    remaining = period - (current_time % period)
    return period if remaining <= 0 else remaining


def generate_totp(
    twofa: str,
    for_time: float | None = None,
    period: int = DEFAULT_PERIOD_SECONDS,
    digits: int = DEFAULT_DIGITS,
) -> str:
    key = _decode_base32_secret(twofa)
    current_time = time.time() if for_time is None else float(for_time)
    counter = int(current_time // period)
    msg = struct.pack(">Q", counter)
    digest = hmac.new(key, msg, hashlib.sha1).digest()
    offset = digest[-1] & 0x0F
    code_int = struct.unpack(">I", digest[offset : offset + 4])[0] & 0x7FFFFFFF
    return str(code_int % (10**digits)).zfill(digits)


def Get_Towfa(
    twofa: str,
    min_seconds_remaining: int = DEFAULT_MIN_SECONDS_REMAINING,
    period: int = DEFAULT_PERIOD_SECONDS,
):
    """
    Backward-compatible name used by the old code.
    Generates the TOTP locally instead of depending on 2fa.live.
    """
    try:
        remaining = seconds_remaining(period)
        if 0 < remaining < min_seconds_remaining:
            time.sleep(remaining + 0.25)

        return generate_totp(twofa, period=period)
    except Exception as e:
        logger.warning("Could not generate 2FA code: %s", e)
        return False
