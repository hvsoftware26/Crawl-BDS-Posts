# Global configuration
import re
from datetime import datetime, timedelta, timezone
#setting for Chromium Path
import winreg

def get_chrome_path_from_registry():
    reg_paths = [
        r"SOFTWARE\Microsoft\Windows\CurrentVersion\App Paths\chrome.exe",
        r"SOFTWARE\WOW6432Node\Microsoft\Windows\CurrentVersion\App Paths\chrome.exe"
    ]

    for reg_path in reg_paths:
        try:
            key = winreg.OpenKey(
                winreg.HKEY_LOCAL_MACHINE,
                reg_path
            )

            value, _ = winreg.QueryValueEx(key, "")
            return value

        except FileNotFoundError:
            continue

    return None


chrome_path = get_chrome_path_from_registry()

CHROME_PATH = chrome_path if chrome_path else r"C:\Program Files\Google\Chrome\Application\chrome.exe"

#seting for API Facebook
DEFAULT_HEADERS = {
    'accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8,application/signed-exchange;v=b3;q=0.7',
    'accept-language': 'vi-VN,vi;q=0.9,fr-FR;q=0.8,fr;q=0.7,en-US;q=0.6,en;q=0.5',
    'cache-control': 'max-age=0',
    'dpr': '1.5',
    'priority': 'u=0, i',
    'referer': 'https://www.facebook.com/two_factor/remember_browser/?encrypted_context=ARG2JvsCe6-CppbtspoDt6Di6iFyjHA-C_-LL9l5HwLX83ZG-4ZX0_sEbd8aYswBvoChUPid8wqkV2TR9OWkGIp_b0cv_JntLGyjvhvnTXOFkCMJVeIR9klW4ym7B1uQhSlaWGSW6MBeonSGSXgh6jjT6EZydmQShtQXJgZSQlGDd5FkL7Nsx2_lN7ZCMqVVNXbot7AmNS__S6MxBIyuQ5bGCDRFMCANoFVCzxM5xIsl0Clx0d4cHr1P4Tir5ID23Gwt1u4d8dgCECIGBpH_xSYVh4mMl_eY2ws6avsbtKch1gpi_FfiwVL5b4HydrdFB82iUMHBw43-eSWA3HK-mn6Hn8BK_ihwSzIjLfU7PNyRgw4PiF_rfCnV762YePSbm-kGYf5-s-cCPzxEbVW2mEq_Qtxlj7DWi3hwlQWjvD1q6A01Enn9n1UFA9psu74HmogTS5VHnOS1VoyhO--bD5I5teEpDmVL4A&next=https%3A%2F%2Fwww.facebook.com%2Fcheckpoint%2F828281030927956%2F%3Fnext%3Dhttps%253A%252F%252Fwww.facebook.com%252F%253Flocale%253Dvi_VN',
    'sec-ch-prefers-color-scheme': 'light',
    'sec-ch-ua': '"Not)A;Brand";v="8", "Chromium";v="138", "Google Chrome";v="138"',
    'sec-ch-ua-full-version-list': '"Not)A;Brand";v="8.0.0.0", "Chromium";v="138.0.7204.169", "Google Chrome";v="138.0.7204.169"',
    'sec-ch-ua-mobile': '?0',
    'sec-ch-ua-model': '""',
    'sec-ch-ua-platform': '"Windows"',
    'sec-ch-ua-platform-version': '"19.0.0"',
    'sec-fetch-dest': 'document',
    'sec-fetch-mode': 'navigate',
    'sec-fetch-site': 'same-origin',
    'sec-fetch-user': '?1',
    'upgrade-insecure-requests': '1',
    'user-agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/138.0.0.0 Safari/537.36',
    'viewport-width': '725',
}
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
PROXIES = None
PARAMS = {'fields': 'feed{name, created_time, message}'}
def build_params(token = None):
    if token:
        params = PARAMS.copy()
        params['access_token'] = token
        return params
    raise ValueError("Token is required to build params")
def build_headers(cookie = None):
    if cookie:
        headers = DEFAULT_HEADERS.copy()
        headers['cookie'] = cookie
        return headers
    raise ValueError("Cookie is required to build headers")
