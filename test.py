"""
Mở Chrome headful y hệt cách agent đã mở (native proxy dict, không extension),
cho profile 61577297542268. Dùng để so trực tiếp với nút "mở Chrome" trong tool.

Điểm mấu chốt: giữ cửa sổ sống bằng vòng lặp CÓ bơm Playwright
(page.wait_for_timeout) thay vì time.sleep/msleep thuần. Vòng msleep của
ViewChromeWorker KHÔNG gọi hàm Playwright nào -> pipe CDP không được đọc ->
khi thao tác thật (scroll/click) Chrome bắn nhiều event CDP -> pipe nghẽn -> lag.

Chạy:  python test.py
Đóng:  bấm X trên cửa sổ Chrome, hoặc Ctrl+C ở terminal.
"""

import time

from playwright.sync_api import sync_playwright

from app_config import CHROME_PATH
from utils.proxy_utils import build_playwright_proxy, mask_proxy

PROFILE = r"C:\Users\My Aspire\OneDrive\Máy tính\Crawl-BDS-Posts\Profile-Chrome\61577297542268"
PROXY = "apollo.proxyngon.com:37241:vietnopro:nohope1111"
FACEBOOK_URL = "https://www.facebook.com/?locale=vi_VN"

# Bộ flag mạng y hệt ViewChromeWorker.NETWORK_ARGS: chặn QUIC/UDP để proxy đi TCP.
NETWORK_ARGS = [
    "--disable-quic",
    "--disable-features=UseDnsHttpsSvcb,UseDnsHttpsSvcbAlpn,EncryptedClientHello",
    "--dns-prefetch-disable",
    "--disable-background-networking",
    "--force-webrtc-ip-handling-policy=disable_non_proxied_udp",
    "--webrtc-ip-handling-policy=disable_non_proxied_udp",
    "--disable-blink-features=AutomationControlled",
]


def main():
    proxy_settings = build_playwright_proxy(PROXY)

    launch_options = {
        "user_data_dir": PROFILE,
        "executable_path": CHROME_PATH,
        "headless": False,
        "ignore_default_args": ["--enable-automation"],
        "args": list(NETWORK_ARGS),
    }
    if proxy_settings:
        launch_options["proxy"] = proxy_settings
        print(f"[test] proxy: {mask_proxy(PROXY)}")

    with sync_playwright() as p:
        context = p.chromium.launch_persistent_context(**launch_options)
        context.on("close", lambda _: print("[test] context closed"))

        pages = [
            page
            for page in context.pages
            if not (page.url or "").startswith("chrome-extension://")
        ]
        page = pages[0] if pages else context.new_page()
        page.set_default_timeout(30000)
        page.set_default_navigation_timeout(60000)

        started = time.monotonic()
        try:
            page.goto(FACEBOOK_URL, wait_until="domcontentloaded", timeout=60000)
            print(f"[test] goto done in {time.monotonic() - started:.1f}s")
        except Exception as exc:
            print(f"[test] goto error: {exc}")

        page.bring_to_front()
        print("[test] Cửa sổ đang mở. Thao tác thử (scroll/click). Bấm X để đóng.")

        # Giữ cửa sổ sống bằng wait_for_timeout: MỖI vòng gọi 1 hàm Playwright nên
        # pipe CDP luôn được đọc -> không nghẽn khi thao tác. Đây là điểm khác
        # với self.msleep(400) của ViewChromeWorker.
        try:
            while context.pages:
                page.wait_for_timeout(400)
        except Exception:
            pass

        print("[test] Đã đóng.")


if __name__ == "__main__":
    main()
