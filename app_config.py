# Global configuration
import re
import sys
from pathlib import Path
try:
    import winreg
except ImportError:
    winreg = None


def get_chrome_path_from_registry():
    if winreg is None:
        return None

    reg_paths = [
        r"SOFTWARE\Microsoft\Windows\CurrentVersion\App Paths\chrome.exe",
        r"SOFTWARE\WOW6432Node\Microsoft\Windows\CurrentVersion\App Paths\chrome.exe",
    ]

    for reg_path in reg_paths:
        try:
            key = winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, reg_path)
            value, _ = winreg.QueryValueEx(key, "")
            return value
        except FileNotFoundError:
            continue

    return None


chrome_path = get_chrome_path_from_registry()
CHROME_PATH = chrome_path if chrome_path else r"C:\Program Files\Google\Chrome\Application\chrome.exe"
FACEBOOK_LOGIN_URL = "https://www.facebook.com/?locale=vi_VN"
OPENAI_MODEL_NAME = "gpt-5.6-sol"


def get_app_base_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent

    return Path(__file__).resolve().parent


APP_BASE_DIR = get_app_base_dir()
PROFILE_ROOT_DIR = (APP_BASE_DIR / "Profile-Chrome").resolve()


def sanitize_profile_name(value: str) -> str:
    normalized = re.sub(r"\s+", "", str(value or "").strip())
    safe_name = re.sub(r"[^A-Za-z0-9._-]+", "_", normalized).strip("._-")

    if not safe_name:
        raise ValueError("Tên profile không hợp lệ")

    return safe_name


def build_local_profile_path(profile_name: str) -> Path:
    return (PROFILE_ROOT_DIR / sanitize_profile_name(profile_name)).resolve()


HEADERS_FOR_GET_UID = {
    'accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8,application/signed-exchange;v=b3;q=0.7',
    'accept-language': 'en-US,en;q=0.9',
    'priority': 'u=0, i',
    'sec-ch-ua': '"Chromium";v="146", "Not-A.Brand";v="24", "Google Chrome";v="146"',
    'sec-ch-ua-mobile': '?0',
    'sec-ch-ua-platform': '"Windows"',
    'sec-fetch-dest': 'document',
    'sec-fetch-mode': 'navigate',
    'sec-fetch-site': 'none',
    'sec-fetch-user': '?1',
    'upgrade-insecure-requests': '1',
    'user-agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/146.0.0.0 Safari/537.36',
}

# Facebook Group GraphQL crawler settings.
GRAPHQL_GROUP_POST_LIMIT = 30
GRAPHQL_GROUP_MAX_SCROLLS = 80
GRAPHQL_GROUP_IDLE_TIMEOUT_SECONDS = 15
GRAPHQL_GROUP_SCROLL_DELAY_SECONDS = 2
GRAPHQL_GROUP_SCROLL_DELAY_MIN_SECONDS = 1.2
GRAPHQL_GROUP_SCROLL_DELAY_MAX_SECONDS = 4.2
GRAPHQL_GROUP_NO_HEIGHT_CHANGE_LIMIT = 5
GRAPHQL_GROUP_MAX_RELOADS = 2
GRAPHQL_GROUP_STALE_SCROLLS_BEFORE_RELOAD = 4
GRAPHQL_GROUP_MAX_OOM_RELOADS = 3
BROWSER_RESTART_EVERY_GROUPS = 5

# Facebook browser comment settings.
FACEBOOK_COMMENT_TYPING_DELAY_MIN_SECONDS = 0.06
FACEBOOK_COMMENT_TYPING_DELAY_MAX_SECONDS = 0.22
FACEBOOK_COMMENT_ACTION_DELAY_MIN_SECONDS = 0.8
FACEBOOK_COMMENT_ACTION_DELAY_MAX_SECONDS = 2.4
