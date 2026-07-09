from __future__ import annotations
import requests
import random
import logging
import time
import threading
from logging import getLogger
from controllers.scan_controller import ScanController
from integrations.facebook_client import (
    FacebookUidCheckNetworkError,
    check_facebook_uid_status,
    extract_facebook_uid_from_cookie,
    get_account_profile_info,
    get_managed_page_names,
    resolve_facebook_uid,
)
from PyQt5.QtCore import QThread, pyqtSignal
from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeoutError
from services.sql_query_service import AccountDB
from services.get_2fa import Get_Towfa
from models.account import Info_data
from app_config import CHROME_PATH
from utils.proxy_utils import (
    build_playwright_proxy,
    build_requests_proxies,
    mask_proxy,
)
from utils.facebook_cookies import has_facebook_login_cookie
from utils.proxy_utils import verify_browser_proxy_ip
from utils.security import mask_cookie, mask_secret

logging.basicConfig(
    filename="main.log",
    filemode="a",
    level=logging.DEBUG,
    format="%(asctime)s - %(name)s - %(levelname)s - %(lineno)d - %(message)s",
    encoding="utf-8"
)

logger = getLogger(__name__)


class Worker_Handle(QThread):
    interaction_signal = pyqtSignal(int, str)
    row_signal = pyqtSignal(int, str)
    page_signal = pyqtSignal(int, int)
    page_names_signal = pyqtSignal(int, str)
    post_signal = pyqtSignal(int, int)
    finished_signal = pyqtSignal(int, str)

    def __init__(self, row: int, task: Info_data, action_mode: str = "crawl"):
        super().__init__()
        self.row = row
        self.task = task
        self.action_mode = action_mode

        self.playwright = None
        self.context = None
        self.page = None
        self.scanner = None

        self.request_captured = False
        self.response_captured = False
        self.cookie_raw = None
        self.eaag_token = None
        self._capture_listening = False

        self._stop_requested = False
        self._playwright_thread_id = None

    # =========================
    # Logging helpers
    # =========================
    def log_interaction(self, message: str):
        self.interaction_signal.emit(self.row, message)
        logger.info(f"[Row {self.row}] {message}")

    def log_row(self, message: str):
        self.row_signal.emit(self.row, message)
        logger.info(f"[Row {self.row}] {message}")

    def log_post(self, value: int):
        self.post_signal.emit(self.row, value)
        logger.info(f"[Row {self.row}] Post count: {value}")

    def log_page_count(self, value: int):
        self.page_signal.emit(self.row, value)
        logger.info(f"[Row {self.row}] Page count: {value}")

    def log_page_names(self, page_names: list[str]):
        names_text = "\n".join(page_names or [])
        self.page_names_signal.emit(self.row, names_text)
        if page_names:
            logger.info(f"[Row {self.row}] Page names: {', '.join(page_names[:20])}")

    # =========================
    # Stop helpers
    # =========================
    def stop(self):
        if self._stop_requested:
            return

        self._stop_requested = True
        self.requestInterruption()
        self.log_row("Đang yêu cầu dừng...")

    def is_stop_requested(self) -> bool:
        return self._stop_requested

    def sleep_with_stop(self, seconds: float) -> bool:
        """
        Sleep nhưng vẫn phản hồi stop nhanh.
        Trả về False nếu có yêu cầu dừng.
        """
        ms_total = int(seconds * 1000)
        step = 100
        waited = 0

        while waited < ms_total:
            if self._stop_requested:
                return False
            self.msleep(step)
            waited += step

        return True

    def ensure_not_stopped(self):
        if self._stop_requested:
            raise InterruptedError("Worker đã được yêu cầu dừng")

    # =========================
    # Browser / Playwright
    # =========================
    def _start_browser(self):
        self.ensure_not_stopped()
        self.log_row("Đang khởi động trình duyệt")

        self._playwright_thread_id = threading.get_ident()
        try:
            self.playwright = sync_playwright().start()
            proxy_settings = build_playwright_proxy(getattr(self.task, "proxy", ""))
            browser_args = [
                "--headless=new",
                "--window-position=-32000,-32000",
                "--window-size=600,540",
                "--lang=vi-VN",
                "--accept-lang=vi-VN,vi",
                "--disable-blink-features=AutomationControlled",
                "--disable-infobars",
                "--no-first-run",
                "--no-default-browser-check",
                "--disable-gpu",
                "--disable-software-rasterizer",
                "--hide-scrollbars",
                "--disable-dev-shm-usage",
                "--disable-features=IsolateOrigins,site-per-process,CalculateNativeWinOcclusion,Translate,AutofillServerCommunication,MediaRouter,DisableLoadExtensionCommandLineSwitch,UseDnsHttpsSvcb,EncryptedClientHello",
                "--disable-background-networking",
                "--disable-background-timer-throttling",
                "--disable-renderer-backgrounding",
                "--disable-backgrounding-occluded-windows",
                "--disable-sync",
                "--metrics-recording-only",
                "--mute-audio",
                "--disable-quic",
                "--dns-prefetch-disable",
                "--force-webrtc-ip-handling-policy=disable_non_proxied_udp",
                "--webrtc-ip-handling-policy=disable_non_proxied_udp",
                "--disable-extensions",
            ]

            launch_options = {
                "user_data_dir": self.task.path_chrome,
                "executable_path": CHROME_PATH,
                "headless": True,
                "args": browser_args,
            }
            if proxy_settings:
                launch_options["proxy"] = proxy_settings
                self.log_row(f"Đang dùng proxy Playwright: {mask_proxy(getattr(self.task, 'proxy', ''))}")

            self.context = self.playwright.chromium.launch_persistent_context(**launch_options)
            # KHÔNG dùng context.route("**/*") ở đây. Với proxy có auth, mỗi request
            # bị interception phải đi lại challenge 407 -> trang treo/quay mãi
            # (đã xác nhận qua test.py). Bỏ resource-blocking để proxy auth hoạt động.
            if proxy_settings:
                self._verify_playwright_proxy(getattr(self.task, "proxy", ""))
        except Exception as e:
            error_message = str(e)

            try:
                if self.playwright:
                    self.playwright.stop()
            except Exception:
                pass

            self.playwright = None
            self.context = None
            self._playwright_thread_id = None

            if "user data directory is already in use" in error_message.lower():
                raise RuntimeError(
                    "Profile Chrome đang mở ở nơi khác. Hãy đóng Chrome của profile này trước khi chạy tool."
                ) from e

            raise

        pages = [
            page
            for page in self.context.pages
            if not (page.url or "").startswith("chrome-extension://")
        ]
        self.page = pages[0] if pages else self.context.new_page()
        self.page.set_default_timeout(30000)
        self.page.set_default_navigation_timeout(20000)

    def _verify_playwright_proxy(self, proxy_value: str):
        check_pages = [
            page
            for page in self.context.pages
            if not (page.url or "").startswith("chrome-extension://")
        ]
        check_page = check_pages[0] if check_pages else self.context.new_page()
        result = verify_browser_proxy_ip(
            check_page,
            proxy_value,
            timeout_ms=10000,
            attempts=2,
            delay_seconds=0.5,
        )
        origin = result.get("origin", "")
        if not result.get("ok"):
            source = result.get("source_url") or "unknown"
            error = result.get("error") or "không đọc được IP"
            if origin:
                raise RuntimeError(f"Proxy Playwright chưa đúng IP. IP nhận được: {origin} (nguồn: {source})")
            raise RuntimeError(f"Không kiểm tra được IP proxy Playwright: {error} (nguồn: {source})")

        self.log_row(f"Proxy Playwright OK: {origin}")

    def close(self):
        if (
            self._playwright_thread_id is not None
            and threading.get_ident() != self._playwright_thread_id
        ):
            logger.warning(
                "[Row %s] Bỏ qua cleanup Playwright từ thread khác: current=%s expected=%s",
                self.row,
                threading.get_ident(),
                self._playwright_thread_id,
            )
            return

        try:
            if self.context:
                self.context.close()
        except Exception as e:
            logger.error(f"[Row {self.row}] Lỗi khi đóng context: {e}")
        finally:
            self.context = None
            self.page = None

        try:
            if self.playwright:
                self.playwright.stop()
        except Exception as e:
            logger.error(f"[Row {self.row}] Lỗi khi stop playwright: {e}")
        finally:
            self.playwright = None
            self._playwright_thread_id = None

    def safe_goto(self, url: str, wait_until: str = "load", retry: int = 2) -> bool:
        last_error = None

        for attempt in range(1, retry + 1):
            if self._stop_requested:
                return False

            try:
                self.log_row(f"Truy cập: {url} (lần {attempt})")
                self.page.goto(url, wait_until=wait_until, timeout=30000)
                return True
            except Exception as e:
                last_error = e
                logger.warning(f"[Row {self.row}] Lỗi goto {url} lần {attempt}: {e}")

                if not self.sleep_with_stop(2):
                    return False

        logger.error(f"[Row {self.row}] Goto thất bại {url}: {last_error}")
        return False

    def get_locator(self, xpath: str):
        return self.page.locator(f"xpath={xpath}")

    def is_element_visible(self, xpath: str, timeout: int = 3000) -> bool:
        if self._stop_requested:
            return False

        try:
            locator = self.get_locator(xpath)
            locator.wait_for(state="visible", timeout=timeout)
            return True
        except Exception:
            return False

    def wait_and_fill(self, xpath: str, value: str, timeout: int = 15000) -> bool:
        if self._stop_requested:
            return False

        try:
            locator = self.get_locator(xpath)
            locator.wait_for(state="visible", timeout=timeout)
            locator.scroll_into_view_if_needed()
            locator.fill(str(value))
            return True
        except Exception as e:
            logger.error(f"[Row {self.row}] Lỗi fill xpath={xpath}: {e}")
            return False

    def wait_and_click(self, xpath: str, timeout: int = 15000) -> bool:
        if self._stop_requested:
            return False

        try:
            locator = self.get_locator(xpath)
            locator.wait_for(state="visible", timeout=timeout)
            locator.scroll_into_view_if_needed()
            locator.click(timeout=timeout)
            return True
        except Exception as e:
            logger.error(f"[Row {self.row}] Lỗi click xpath={xpath}: {e}")
            return False

    def get_cookie_raw(self) -> str:
        cookies = self.context.cookies()
        return "; ".join([f"{c['name']}={c['value']}" for c in cookies])

    def get_facebook_cookie_map(self) -> dict[str, str]:
        if not self.context:
            return {}

        try:
            cookies = self.context.cookies(["https://www.facebook.com"])
        except Exception as e:
            logger.warning(f"[Row {self.row}] Không đọc được cookie Facebook: {e}")
            return {}

        return {
            str(cookie.get("name")): str(cookie.get("value"))
            for cookie in cookies
            if cookie.get("name")
        }

    def has_active_facebook_session(self) -> bool:
        cookie_map = self.get_facebook_cookie_map()
        return bool(cookie_map.get("c_user") and cookie_map.get("xs"))

    def wait_and_fill_css(
        self,
        selector: str,
        value: str,
        timeout: int = 15000,
        log_errors: bool = False,
    ) -> bool:
        if self._stop_requested:
            return False

        try:
            locator = self.page.locator(selector).first
            locator.wait_for(state="visible", timeout=timeout)
            locator.scroll_into_view_if_needed()
            locator.fill(str(value))
            return True
        except Exception as e:
            if log_errors:
                logger.error(f"[Row {self.row}] Lỗi fill selector={selector}: {e}")
            return False

    def wait_and_click_css(
        self,
        selector: str,
        timeout: int = 15000,
        log_errors: bool = False,
    ) -> bool:
        if self._stop_requested:
            return False

        try:
            locator = self.page.locator(selector).first
            locator.wait_for(state="visible", timeout=timeout)
            locator.scroll_into_view_if_needed()
            locator.click(timeout=timeout)
            return True
        except Exception as e:
            if log_errors:
                logger.error(f"[Row {self.row}] Lỗi click selector={selector}: {e}")
            return False

    def is_css_visible(self, selector: str, timeout: int = 3000) -> bool:
        if self._stop_requested:
            return False

        try:
            locator = self.page.locator(selector).first
            locator.wait_for(state="visible", timeout=timeout)
            return True
        except Exception:
            return False

    def click_first_visible(self, selectors: list[str], timeout: int = 5000) -> bool:
        for selector in selectors:
            if self.wait_and_click_css(selector, timeout=timeout, log_errors=False):
                return True
        return False

    def find_first_visible_locator(self, selectors: list[str], timeout: int = 5000):
        if self._stop_requested:
            return None, None

        deadline = time.monotonic() + (timeout / 1000)
        while time.monotonic() < deadline:
            if self._stop_requested:
                return None, None

            for selector in selectors:
                remaining_ms = int((deadline - time.monotonic()) * 1000)
                if remaining_ms <= 0:
                    return None, None

                try:
                    locator = self.page.locator(selector).first
                    locator.wait_for(state="visible", timeout=min(250, remaining_ms))
                    return locator, selector
                except Exception:
                    continue

            if not self.sleep_with_stop(0.2):
                return None, None

        return None, None

    def page_text_contains_any(self, words: list[str], timeout: int = 1500) -> bool:
        try:
            body_text = self.page.locator("body").inner_text(timeout=timeout).lower()
        except Exception:
            return False

        return any(word.lower() in body_text for word in words)

    def page_looks_like_2fa_challenge(self) -> bool:
        current_url = (self.page.url or "").lower()
        if any(
            marker in current_url
            for marker in (
                "checkpoint",
                "two_factor",
                "two-factor",
                "two_step",
                "two-step",
                "login/approvals",
            )
        ):
            return True

        return self.page_text_contains_any(
            [
                "two-factor",
                "authentication code",
                "security code",
                "login code",
                "code generator",
                "enter the code",
                "nhập mã",
                "ma xac thuc",
                "mã xác thực",
                "mã bảo mật",
            ]
        )

    def find_2fa_input(self, timeout: int = 10000):
        specific_selectors = [
            'input[name="approvals_code"]',
            'input#approvals_code',
            'input[autocomplete="one-time-code"]',
            'input[inputmode="numeric"]',
            'input[type="tel"]',
            'input[aria-label*="code" i]',
            'input[placeholder*="code" i]',
            'input[aria-label*="mã" i]',
            'input[placeholder*="mã" i]',
            "xpath=/html/body/div[1]/div[1]/div/div[2]/div/div/div/div/div/div/div/div[2]/div[1]/div[4]/span/span/div/div[2]/div/div/div/div[1]/div[2]/div/div/input",
            "xpath=/html/body/div[1]/div[1]/div/div/div/div/div/div/div/div/div/div/div/div/div/div[2]/div[2]/div[3]/div/div/div[3]/div/div/div[1]/input",
        ]
        locator, selector = self.find_first_visible_locator(specific_selectors, timeout=timeout)
        if locator:
            return locator, selector

        if not self.page_looks_like_2fa_challenge():
            return None, None

        generic_selectors = [
            'input[type="text"][maxlength="6"]',
            'input[type="text"][maxlength="8"]',
            'input[type="text"]',
        ]
        return self.find_first_visible_locator(generic_selectors, timeout=2000)

    def has_2fa_challenge(self) -> bool:
        locator, _ = self.find_2fa_input(timeout=1200)
        return bool(locator)

    def fill_2fa_code(self, input_locator, code: str) -> bool:
        try:
            digit_inputs = self.page.locator(
                'input[maxlength="1"], input[aria-label*="digit" i], input[aria-label*="Digit" i]'
            )
            visible_digit_inputs = []
            for index in range(min(digit_inputs.count(), len(code))):
                item = digit_inputs.nth(index)
                try:
                    if item.is_visible():
                        visible_digit_inputs.append(item)
                except Exception:
                    continue

            if len(visible_digit_inputs) >= len(code):
                for digit, item in zip(code, visible_digit_inputs):
                    item.fill(digit)
                return True
        except Exception:
            pass

        try:
            input_locator.scroll_into_view_if_needed()
            input_locator.fill(str(code))
            return True
        except Exception:
            try:
                input_locator.click()
                input_locator.type(str(code), delay=40)
                return True
            except Exception as e:
                logger.error(f"[Row {self.row}] Loi nhap ma 2FA: {e}")
                return False

    def submit_2fa_code(self) -> bool:
        submit_selectors = [
            'button[type="submit"]',
            'div[role="button"]:has-text("Continue")',
            'button:has-text("Continue")',
            'text="Continue"',
            'div[role="button"]:has-text("Tiếp tục")',
            'button:has-text("Tiếp tục")',
            'text="Tiếp tục"',
            "xpath=/html/body/div[1]/div[1]/div/div[2]/div/div/div/div/div/div/div/div[3]/div[2]/div/div",
            "xpath=/html/body/div[1]/div[1]/div/div/div/div/div/div/div/div/div/div/div/div/div/div[3]/div/div/div/div/div/div[2]/div[2]/div/div",
        ]

        if self.click_first_visible(submit_selectors, timeout=5000):
            return True

        try:
            self.page.keyboard.press("Enter")
            return True
        except Exception as e:
            logger.error(f"[Row {self.row}] Khong submit duoc ma 2FA: {e}")
            return False

    def click_post_login_prompts(self):
        prompt_selectors = [
            'div[role="button"]:has-text("Continue")',
            'button:has-text("Continue")',
            'text="Continue"',
            'div[role="button"]:has-text("Tiếp tục")',
            'button:has-text("Tiếp tục")',
            'text="Tiếp tục"',
            'div[role="button"]:has-text("OK")',
            'button:has-text("OK")',
        ]

        for _ in range(3):
            if self.click_first_visible(prompt_selectors, timeout=1000):
                if not self.sleep_with_stop(0.6):
                    return
            else:
                return

    def handle_2fa_challenge(self) -> bool:
        if self._stop_requested:
            return False

        self.log_row("Kiem tra xac minh 2FA")
        input_locator, selector = self.find_2fa_input(timeout=15000)
        if not input_locator:
            self.log_row("Khong phat hien form 2FA")
            return True

        self.log_row(f"Phat hien form 2FA: {selector}")

        twofa_secret = getattr(self.task, "twofa", "")
        if not twofa_secret:
            self.log_row("Tai khoan chua co secret 2FA")
            return False

        twofa_code = Get_Towfa(twofa_secret, min_seconds_remaining=8)
        if not twofa_code:
            self.log_row("Khong lay duoc ma 2FA")
            return False

        self.log_row("Da lay ma 2FA")
        if not self.fill_2fa_code(input_locator, str(twofa_code)):
            self.log_row("Khong nhap duoc ma 2FA")
            return False

        if not self.sleep_with_stop(0.8):
            return False

        if not self.submit_2fa_code():
            self.log_row("Khong submit duoc ma 2FA")
            return False

        self.log_row("Da submit ma 2FA, dang cho Facebook xac nhan")

        for _ in range(15):
            if self._stop_requested:
                return False

            self.click_post_login_prompts()
            if self.is_logged_in():
                self.log_row("Xac minh 2FA thanh cong")
                return True

            if not self.has_2fa_challenge():
                return True

            if not self.sleep_with_stop(1):
                return False

        if self.has_2fa_challenge():
            self.log_row("Form 2FA van hien thi sau khi submit, co the ma da het han hoac bi tu choi")
            return False

        return True

    def fill_login_form(self) -> bool:
        filled_any = False

        if getattr(self.task, "email", None):
            if self.wait_and_fill_css(
                'input[name="email"]',
                self.task.email,
                timeout=5000,
                log_errors=False,
            ):
                self.log_row("Đã nhập email đăng nhập")
                filled_any = True

        if getattr(self.task, "password", None):
            if self.wait_and_fill_css(
                'input[name="pass"]',
                self.task.password,
                timeout=5000,
                log_errors=False,
            ):
                self.log_row("Đã nhập mật khẩu đăng nhập")
                filled_any = True

        return filled_any

    def submit_login_form(self) -> bool:
        login_selectors = [
            'button[name="login"]',
            'div[role="button"]:has-text("Đăng nhập")',
            'div[role="button"]:has-text("Log in")',
            'text="Đăng nhập"',
            'text="Log in"',
        ]

        if self.click_first_visible(login_selectors, timeout=5000):
            self.log_row("Đã gửi form đăng nhập")
            return True

        try:
            password_locator = self.page.locator('input[name="pass"]').first
            password_locator.wait_for(state="visible", timeout=3000)
            password_locator.press("Enter")
            self.log_row("Đã gửi form đăng nhập bằng Enter")
            return True
        except Exception as e:
            logger.error(f"[Row {self.row}] Không submit được form đăng nhập: {e}")
            return False

    def relogin_once(self, attempt_number: int) -> bool:
        self.log_row(f"Thử đăng nhập lại (lần {attempt_number})")

        if not self.safe_goto("https://www.facebook.com/?locale=vi_VN", wait_until="domcontentloaded"):
            if not self._stop_requested:
                self.log_row("Không vào được Facebook")
            return False

        if not self.sleep_with_stop(2):
            return False

        if self.is_logged_in():
            return True

        clicked_continue = self.click_first_visible(
            [
                'div[role="button"]:has-text("Tiếp tục")',
                'div[role="button"]:has-text("Continue")',
                'text="Tiếp tục"',
                'text="Continue"',
            ],
            timeout=3000,
        )
        if clicked_continue:
            self.log_row("Đã click nút tiếp tục phiên đăng nhập")
            if not self.sleep_with_stop(2):
                return False

        if self.has_2fa_challenge():
            self.log_row("Phat hien yeu cau 2FA trong luong dang nhap")
            if not self.handle_2fa_if_present():
                return False
            if not self.sleep_with_stop(2):
                return False
            return self.is_logged_in()

        filled_login_form = self.fill_login_form()

        if not filled_login_form and not clicked_continue:
            self.log_row("Không tìm thấy form đăng nhập hoặc nút tiếp tục")
            return False

        if filled_login_form and not self.submit_login_form():
            return False

        try:
            self.page.wait_for_load_state("domcontentloaded", timeout=10000)
        except Exception:
            pass

        if not self.sleep_with_stop(3):
            return False

        if not self.handle_2fa_if_present():
            if self._stop_requested:
                return False
            self.log_row("Xử lý 2FA chưa thành công")
            return False

        if not self.sleep_with_stop(2):
            return False

        return self.is_logged_in()

    # =========================
    # 2FA / capture
    # =========================
    def handle_2fa_if_present(self) -> bool:
        if self._stop_requested:
            return False

        return self.handle_2fa_challenge()

        twofa_layouts = [
            {
                "name": "layout_cu",
                "input": "/html/body/div[1]/div[1]/div/div[2]/div/div/div/div/div/div/div/div[2]/div[1]/div[4]/span/span/div/div[2]/div/div/div/div[1]/div[2]/div/div/input",
                "button": "/html/body/div[1]/div[1]/div/div[2]/div/div/div/div/div/div/div/div[3]/div[2]/div/div",
            },
            {
                "name": "layout_moi",
                "input": "/html/body/div[1]/div[1]/div/div/div/div/div/div/div/div/div/div/div/div/div/div[2]/div[2]/div[3]/div/div/div[3]/div/div/div[1]/input",
                "button": "/html/body/div[1]/div[1]/div/div/div/div/div/div/div/div/div/div/div/div/div/div[3]/div/div/div/div/div/div[2]/div[2]/div/div",
            },
        ]

        self.log_row("Kiểm tra xác minh 2FA")
        matched_layout = None

        for layout in twofa_layouts:
            if self._stop_requested:
                return False

            if self.is_element_visible(layout["input"], timeout=5000):
                matched_layout = layout
                self.log_row(f"Phát hiện form 2FA: {layout['name']}")
                break

        if not matched_layout:
            self.log_row("Không phát hiện form 2FA")
            return True

        try:
            twofa_code = None

            if hasattr(self.task, "twofa") and self.task.twofa:
                twofa_code = Get_Towfa(self.task.twofa)

            if not twofa_code:
                self.log_row("Không lấy được mã 2FA")
                return False

            self.log_row("Đã lấy mã 2FA")

        except Exception as e:
            logger.error(f"[Row {self.row}] Lỗi lấy mã 2FA: {e}")
            return False

        if not self.wait_and_fill(matched_layout["input"], twofa_code):
            self.log_row("Không nhập được mã 2FA")
            return False

        if not self.sleep_with_stop(1):
            return False

        if not self.wait_and_click(matched_layout["button"]):
            self.log_row("Không click được nút tiếp tục 2FA")
            return False

        self.log_row("Đã submit mã 2FA thành công")

        if not self.sleep_with_stop(3):
            return False

        return True

    def on_capture_requests(self, request):
        if self.request_captured or self._stop_requested:
            return

        if "business_locations" in request.url:
            self.request_captured = True
            self.cookie_raw = self.get_cookie_raw()
            logger.info(f"[Row {self.row}] Bắt được request business_locations")
            logger.info(f"[Row {self.row}] COOKIE: {mask_cookie(self.cookie_raw)}")

    def on_capture_response(self, response):
        if self.response_captured or self._stop_requested:
            return

        try:
            if "business_locations" in response.url:
                text = response.text()
                if '],["EAAGN' in text:
                    self.eaag_token = "EAAGN" + text.split('],["EAAGN')[1].split('","')[0]
                    self.response_captured = True
                    logger.info(f"[Row {self.row}] Bắt được EAAG token: {mask_secret(self.eaag_token)}")
        except Exception as e:
            logger.error(f"[Row {self.row}] Lỗi bắt response token: {e}")

    def start_capture(self):
        self.request_captured = False
        self.response_captured = False
        if self._capture_listening:
            return
        self.page.on("request", self.on_capture_requests)
        self.page.on("response", self.on_capture_response)
        self._capture_listening = True

    def stop_capture(self):
        # Gỡ listener sau khi lấy xong cookie/token. Nếu để nguyên, mọi
        # request/response của trang phải round-trip qua CDP về Python, làm
        # các trang nặng (link post) lag khi thao tác tay.
        if not self._capture_listening:
            return
        try:
            self.page.remove_listener("request", self.on_capture_requests)
            self.page.remove_listener("response", self.on_capture_response)
        except Exception as e:
            logger.warning(f"[Row {self.row}] Lỗi gỡ capture listener: {e}")
        finally:
            self._capture_listening = False

    # =========================
    # Login flow
    # =========================
    def is_logged_in(self) -> bool:
        if self._stop_requested:
            return False

        try:
            current_url = (self.page.url or "").lower()
            has_session = self.has_active_facebook_session()
            is_auth_challenge = any(
                marker in current_url
                for marker in (
                    "login",
                    "checkpoint",
                    "two_factor",
                    "two-factor",
                    "recover",
                )
            )

            if has_session and not is_auth_challenge:
                return True

            if self.is_css_visible('input[name="email"]', timeout=2000):
                logger.info(
                    f"[Row {self.row}] Phát hiện form email đăng nhập. url={current_url} has_session={has_session}"
                )
                return False

            if self.is_css_visible('input[name="pass"]', timeout=2000) and not has_session:
                logger.info(
                    f"[Row {self.row}] Phát hiện form mật khẩu đăng nhập. url={current_url} has_session={has_session}"
                )
                return False

            try:
                body_text = self.page.locator("body").inner_text(timeout=2500).lower()
            except Exception as body_error:
                logger.warning(
                    "[Row %s] Khong doc duoc body khi kiem tra login: url=%s has_session=%s error=%s",
                    self.row,
                    current_url,
                    has_session,
                    body_error,
                )
                return has_session and not is_auth_challenge

            if (
                "bạn đang nghĩ gì thế" in body_text
                or "what's on your mind" in body_text
                or "what’s on your mind" in body_text
                or "meta business suite" in body_text
                or "business locations" in body_text
            ):
                return True

            if (
                "đăng nhập vào facebook" in body_text
                or "log into facebook" in body_text
                or "quên mật khẩu" in body_text
                or "forgotten password" in body_text
            ):
                return False

            return has_session
        except Exception as e:
            logger.error(f"[Row {self.row}] Lỗi kiểm tra login: {e}")
            try:
                return self.has_active_facebook_session()
            except Exception:
                return False

    def try_reuse_saved_cookie_token(self):
        saved_cookie = str(getattr(self.task, "cookie", "") or "").strip()
        saved_token = str(getattr(self.task, "token", "") or "").strip()
        if not saved_cookie or not saved_token:
            return None

        if not has_facebook_login_cookie(saved_cookie):
            self.log_row("Cookie hiện tại thiếu c_user/xs, sẽ lấy lại cookie/token")
            return None

        try:
            profile_info = get_account_profile_info(
                saved_token,
                account_cookies=saved_cookie,
                proxies=build_requests_proxies(getattr(self.task, "proxy", "")),
            )
        except Exception as exc:
            logger.info("[Row %s] Saved token/cookie is not reusable: %s", self.row, exc)
            self.log_row(f"Token/cookie hiện tại không dùng được, sẽ lấy lại: {exc}")
            return None

        cookie_uid = extract_facebook_uid_from_cookie(saved_cookie)
        token_uid = str(profile_info.get("id") or "").strip()
        if cookie_uid and token_uid and cookie_uid != token_uid:
            self.log_row("Token/cookie hiện tại không cùng UID, sẽ lấy lại cookie/token")
            logger.info(
                "[Row %s] Saved credential UID mismatch: cookie_uid=%s token_uid=%s",
                self.row,
                cookie_uid,
                token_uid,
            )
            return None

        self.cookie_raw = saved_cookie
        self.eaag_token = saved_token
        account_name = profile_info.get("name") or token_uid or cookie_uid
        self.log_row(f"Token/cookie hiện tại còn dùng được: {account_name}")
        return self.cookie_raw, self.eaag_token

    def verify_account_active(self, cookie: str, token: str) -> bool:
        """Check account còn hoạt động bằng cookie + token qua Graph API."""
        if not cookie or not token:
            return False
        try:
            get_account_profile_info(
                token,
                account_cookies=cookie,
                proxies=build_requests_proxies(getattr(self.task, "proxy", "")),
            )
            return True
        except Exception as exc:
            logger.info("[Row %s] verify_account_active failed: %s", self.row, exc)
            return False

    def prepare_worker_account(self):
        """
        LUỒNG 2: kiểm tra tài khoản bằng cookie+token trước khi chạy worker.
        - Hợp lệ  -> trả (cookie, token) để chạy tool ngay.
        - Không hợp lệ -> refresh token (mở Chrome + Get_Towfa + capture),
          recheck Graph. Được thì chạy tiếp, thất bại thì trả (None, None)
          và caller sẽ đặt Status "Có thể nick bị đăng xuất".
        """
        reused = self.try_reuse_saved_cookie_token()
        if reused:
            return reused

        if self._stop_requested:
            return None, None

        self.log_row("Có thể token đã hết hạn")
        cookie, token = self.handle_login(skip_reuse=True)

        if self._stop_requested:
            return None, None

        if cookie and token and self.verify_account_active(cookie, token):
            self.log_row("Đã lấy token mới, tài khoản còn hoạt động")
            return cookie, token

        return None, None

    def handle_login(self, skip_reuse: bool = False):
        if not skip_reuse:
            saved_credentials = self.try_reuse_saved_cookie_token()
            if saved_credentials:
                return saved_credentials

        browser_retry = 3
        capture_retry = 5

        for browser_attempt in range(1, browser_retry + 1):
            if self._stop_requested:
                return None, None

            try:
                self.cookie_raw = None
                self.eaag_token = None

                self._start_browser()

                if self._stop_requested:
                    return None, None

                self.log_row(f"Truy cập Facebook (lần {browser_attempt})")
                if not self.safe_goto("https://www.facebook.com/?locale=vi_VN", wait_until="domcontentloaded"):
                    if self._stop_requested:
                        return None, None
                    raise Exception("Không vào được Facebook")

                if not self.sleep_with_stop(random.uniform(2, 4)):
                    return None, None

                self.log_row("Đang kiểm tra tài khoản")
                if not self.is_logged_in():
                    self.log_row("Tài khoản bị đăng xuất")
                    count = 0
                    relogin_success = False

                    while count < 5:
                        if self._stop_requested:
                            return None, None

                        count += 1
                        try:
                            relogin_success = self.relogin_once(count)
                        except Exception as e:
                            if self._stop_requested:
                                return None, None
                            logger.error(f"[Row {self.row}] Lỗi quá trình đăng nhập lại lần {count}: {e}")
                            relogin_success = False

                        if relogin_success:
                            self.log_row("Đăng nhập lại thành công")
                            break

                        self.log_row("Đăng nhập lại chưa thành công, sẽ thử lại")

                        if count < 5 and not self.sleep_with_stop(2):
                            return None, None

                    if not relogin_success:
                        self.log_row("Đăng nhập lại thất bại sau nhiều lần thử")
                        return None, None

                if self._stop_requested:
                    return None, None

                self.log_row("Tài khoản đã đăng nhập")
                self.log_row("Truy cập Business Location")

                if not self.safe_goto(
                    "https://business.facebook.com/business_locations/",
                    wait_until="domcontentloaded"
                ):
                    if self._stop_requested:
                        return None, None
                    raise Exception("Không vào được Business Location")

                if not self.sleep_with_stop(3):
                    return None, None

                if not self.handle_2fa_if_present():
                    if self._stop_requested:
                        return None, None
                    raise Exception("Xử lý 2FA thất bại")

                for capture_attempt in range(1, capture_retry + 1):
                    if self._stop_requested:
                        return None, None

                    try:
                        self.log_row(f"Thử lấy cookie/token lần {capture_attempt}/{capture_retry}")

                        self.cookie_raw = None
                        self.eaag_token = None
                        self.request_captured = False
                        self.response_captured = False

                        self.log_row("Bắt đầu bắt request/response")
                        self.start_capture()

                        if not self.sleep_with_stop(2):
                            return None, None

                        if not self.safe_goto(
                            "https://business.facebook.com/business_locations/",
                            wait_until="domcontentloaded"
                        ):
                            if self._stop_requested:
                                return None, None
                            raise Exception("Không tải lại được Business Location")

                        if not self.sleep_with_stop(5):
                            return None, None

                        self.log_row("Đang lấy cookie và token")

                        if not self.sleep_with_stop(2):
                            return None, None

                        if not self.cookie_raw:
                            self.cookie_raw = self.get_cookie_raw()

                        if self.cookie_raw and self.eaag_token:
                            AccountDB(None).update_cookie_token_by_path(
                                path_profile=self.task.path_chrome,
                                cookie=self.cookie_raw,
                                token=self.eaag_token,
                            )
                            self.log_row("Lấy cookie và token thành công")
                            self.stop_capture()
                            return self.cookie_raw, self.eaag_token

                        self.log_row("Chưa lấy đủ cookie/token, sẽ thử lại")

                        if capture_attempt < capture_retry:
                            if not self.sleep_with_stop(2):
                                return None, None
                            continue

                    except Exception as capture_error:
                        if self._stop_requested:
                            return None, None
                        logger.exception(
                            f"[Row {self.row}] Lỗi lấy cookie/token lần {capture_attempt}: {capture_error}"
                        )
                        self.log_row(f"Lỗi lấy cookie/token lần {capture_attempt}: {capture_error}")

                        if capture_attempt < capture_retry:
                            if not self.sleep_with_stop(2):
                                return None, None
                            continue

                raise Exception("Lấy cookie và token thất bại sau nhiều lần thử trong cùng phiên Chrome")

            except InterruptedError:
                return None, None

            except PlaywrightTimeoutError as e:
                if self._stop_requested:
                    return None, None
                logger.exception(f"[Row {self.row}] Timeout Playwright lần {browser_attempt}: {e}")
                self.log_row(f"Timeout lần {browser_attempt}: {e}")

            except Exception as e:
                if self._stop_requested:
                    return None, None
                logger.exception(f"[Row {self.row}] Lỗi lần {browser_attempt}: {e}")
                self.log_row(f"Lỗi lần {browser_attempt}: {e}")

            finally:
                self.close()

            if self._stop_requested:
                return None, None

            if browser_attempt < browser_retry:
                self.log_row("Thử mở lại trình duyệt và đăng nhập lại...")
                if not self.sleep_with_stop(3):
                    return None, None

        if self._stop_requested:
            return None, None

        self.log_row("Lấy cookie và token thất bại sau nhiều lần thử")
        return None, None

    @staticmethod
    def _normalize_page_name(name: str) -> str:
        return " ".join(str(name or "").split()).strip()

    def _dedupe_page_names(self, names: list[str]) -> list[str]:
        unique_names = []
        seen = set()

        for name in names or []:
            normalized_name = self._normalize_page_name(name)
            if not normalized_name:
                continue

            key = normalized_name.casefold()
            if key in seen:
                continue

            seen.add(key)
            unique_names.append(normalized_name)

        return unique_names

    def fetch_page_names_from_graph(self, token: str = None, cookie: str = None) -> list[str] | None:
        access_token = token or self.eaag_token or getattr(self.task, "token", "")
        cookie_value = cookie or self.cookie_raw or getattr(self.task, "cookie", "")
        if not access_token:
            logger.info("[Row %s] Skip page names from Graph because token is empty", self.row)
            return None

        try:
            return self._dedupe_page_names(
                get_managed_page_names(
                    access_token,
                    account_cookies=cookie_value,
                    account_name=getattr(self.task, "account_name", ""),
                    proxies=build_requests_proxies(getattr(self.task, "proxy", "")),
                )
            )
        except Exception as e:
            logger.warning("[Row %s] Không lấy được danh sách page từ Graph: %s", self.row, e)
            return None

    def fetch_page_names_from_graph_with_fallback(self, token: str = None, cookie: str = None) -> list[str] | None:
        access_token = token or self.eaag_token or getattr(self.task, "token", "")
        cookie_value = cookie or self.cookie_raw or getattr(self.task, "cookie", "")
        if not access_token:
            logger.info("[Row %s] Skip page names from Graph because token is empty", self.row)
            return None

        proxy_value = getattr(self.task, "proxy", "")
        attempts = []
        try:
            proxies = build_requests_proxies(proxy_value)
        except Exception as exc:
            logger.warning("[Row %s] Invalid Graph proxy, retry direct: %s", self.row, exc)
            proxies = None

        if proxies:
            attempts.append(("proxy", proxies))
        attempts.append(("direct", None))

        last_error = None
        for label, request_proxies in attempts:
            if self._stop_requested:
                return None

            try:
                page_names = get_managed_page_names(
                    access_token,
                    account_cookies=cookie_value,
                    account_name=getattr(self.task, "account_name", ""),
                    proxies=request_proxies,
                )
                if label == "direct" and proxies:
                    self.log_row("Proxy loi, da lay danh sach page bang ket noi direct")
                return self._dedupe_page_names(page_names)
            except Exception as exc:
                last_error = exc
                logger.warning(
                    "[Row %s] Khong lay duoc danh sach page tu Graph %s: %s",
                    self.row,
                    label,
                    exc,
                )
                if request_proxies is not None:
                    self.log_row(f"Proxy loi khi lay page, thu lai khong dung proxy: {self._short_error(exc)}")
                    continue

        if last_error:
            self.log_row(
                f"Khong lay duoc danh sach page tu Graph API, giu nguyen du lieu cu: {self._short_error(last_error)}"
            )
        return None

    def fetch_total_pages(self, token: str = None, cookie: str = None) -> int | None:
        page_names = self.fetch_page_names_from_graph(token, cookie)
        if page_names is None:
            return None

        return len(page_names)

    def _extract_page_names_from_current_dom(self) -> list[str]:
        if not self.page:
            return []

        try:
            names = self.page.evaluate(
                """
                () => {
                    const blockedTexts = new Set([
                        "facebook", "home", "trang chủ", "pages", "trang",
                        "friends", "bạn bè", "groups", "nhóm", "marketplace",
                        "watch", "video", "reels", "menu", "notifications",
                        "thông báo", "messenger", "search", "tìm kiếm",
                        "settings", "cài đặt", "see more", "xem thêm",
                        "create new page", "tạo trang mới", "create page",
                        "tạo trang", "manage", "quản lý", "switch", "chuyển",
                        "meta business suite", "feeds", "bảng feed"
                    ]);
                    const blockedPathStarts = new Set([
                        "pages", "groups", "friends", "marketplace", "watch",
                        "notifications", "messages", "help", "settings",
                        "privacy", "events", "gaming", "reel", "reels",
                        "stories", "search", "bookmarks", "business", "ads",
                        "me", "profile"
                    ]);

                    const cleanText = (value) => String(value || "")
                        .replace(/\\s+/g, " ")
                        .trim();

                    const hasPageContext = (node) => {
                        let current = node;
                        for (let depth = 0; current && depth < 8; depth += 1) {
                            const contextText = cleanText(current.innerText || current.textContent || "");
                            if (/followers?|người theo dõi|likes?|lượt thích|manage|quản lý|switch|chuyển|page|trang/i.test(contextText)) {
                                return true;
                            }
                            current = current.parentElement;
                        }
                        return false;
                    };

                    const isUsableName = (name) => {
                        const text = cleanText(name);
                        if (!text || text.length < 2 || text.length > 120) {
                            return false;
                        }
                        if (blockedTexts.has(text.toLowerCase())) {
                            return false;
                        }
                        if (/^(\\d+[.,]?\\d*\\s*)?(followers?|người theo dõi|likes?|lượt thích)$/i.test(text)) {
                            return false;
                        }
                        if (/^(manage|quản lý|switch|chuyển|view|xem|message|nhắn tin)$/i.test(text)) {
                            return false;
                        }
                        return true;
                    };

                    const isProbablyPageHref = (href, node) => {
                        if (!href) {
                            return false;
                        }

                        let url;
                        try {
                            url = new URL(href, location.href);
                        } catch (_) {
                            return false;
                        }

                        if (!/(^|\\.)facebook\\.com$/i.test(url.hostname)) {
                            return false;
                        }

                        const path = decodeURIComponent(url.pathname || "").replace(/\\/+$/, "");
                        if (path === "/profile.php") {
                            return url.searchParams.has("id") && hasPageContext(node);
                        }

                        const segments = path.split("/").filter(Boolean);
                        if (segments.length === 0) {
                            return false;
                        }

                        if (blockedPathStarts.has((segments[0] || "").toLowerCase())) {
                            return false;
                        }

                        return hasPageContext(node);
                    };

                    const result = [];
                    for (const anchor of Array.from(document.querySelectorAll('a[href]'))) {
                        if (!isProbablyPageHref(anchor.href, anchor)) {
                            continue;
                        }

                        const label = cleanText(anchor.getAttribute("aria-label"));
                        const rawText = cleanText(anchor.innerText || anchor.textContent);
                        const firstLine = cleanText((anchor.innerText || anchor.textContent || "").split("\\n")[0]);
                        const candidates = [firstLine, label, rawText];

                        for (const candidate of candidates) {
                            if (isUsableName(candidate)) {
                                result.push(candidate);
                                break;
                            }
                        }
                    }

                    return result;
                }
                """
            )
        except Exception as e:
            logger.warning("[Row %s] Không đọc được DOM page Facebook: %s", self.row, e)
            return []

        return self._dedupe_page_names(names or [])

    def fetch_page_names_from_html(self) -> list[str] | None:
        urls = [
            "https://www.facebook.com/pages/?category=your_pages&ref=bookmarks",
            "https://www.facebook.com/pages/?category=your_pages",
            "https://www.facebook.com/bookmarks/pages",
            "https://m.facebook.com/pages/?category=your_pages",
        ]
        page_names = []

        try:
            self._start_browser()
            if not self.safe_goto("https://www.facebook.com/?locale=vi_VN", wait_until="domcontentloaded", retry=1):
                return None

            if not self.sleep_with_stop(2):
                return None

            if not self.is_logged_in():
                self.log_row("Không thể đọc tên page bằng HTML vì profile chưa đăng nhập")
                return None

            for url in urls:
                if self._stop_requested:
                    return None

                self.log_row(f"Đọc danh sách page từ HTML: {url}")
                if not self.safe_goto(url, wait_until="domcontentloaded", retry=1):
                    continue

                if not self.sleep_with_stop(3):
                    return None

                for _ in range(6):
                    page_names.extend(self._extract_page_names_from_current_dom())
                    try:
                        self.page.mouse.wheel(0, 1400)
                    except Exception:
                        pass

                    if not self.sleep_with_stop(1):
                        return None

            page_names = self._dedupe_page_names(page_names)
            return page_names if page_names else None
        finally:
            self.close()

    def persist_account_status(
        self,
        status: str,
        page_count: int | None = None,
        page_names: list[str] | None = None,
    ):
        db = AccountDB(None)
        db.update_status_by_path(self.task.path_chrome, status)
        if page_names is not None:
            page_names = self._dedupe_page_names(page_names)
            resolved_page_count = len(page_names) if page_count is None else page_count
            db.update_page_info_by_path(
                self.task.path_chrome,
                resolved_page_count,
                "\n".join(page_names),
            )
            self.log_page_count(resolved_page_count)
            self.log_page_names(page_names)
        elif page_count is not None:
            db.update_page_count_by_path(self.task.path_chrome, page_count)
            self.log_page_count(page_count)

    def run_check_uid_status(self) -> str:
        self.log_row("Đang kiểm tra UID Facebook")
        uid = resolve_facebook_uid(
            account_name=getattr(self.task, "account_name", ""),
            path_chrome=getattr(self.task, "path_chrome", ""),
            email=getattr(self.task, "email", ""),
            cookie=getattr(self.task, "cookie", ""),
        )
        if not uid:
            status = "Không có UID Facebook"
            self.persist_account_status(status)
            self.log_row(status)
            return status

        if self._stop_requested:
            return "Đã dừng"

        if not self.sleep_with_stop(random.uniform(0.1, 0.7)):
            return "Đã dừng"

        self.log_row(f"Đang kiểm tra UID: {uid}")
        result = self._check_uid_status_with_retry(uid)
        if not result:
            status = "UID lỗi mạng"
            self.persist_account_status(status)
            self.log_row(f"{status}: {uid}")
            return status

        status = "UID sống" if result.get("alive") else "UID chết"
        self.persist_account_status(status)
        self.log_row(f"{status}: {uid}")
        return status

    @staticmethod
    def _short_error(error: Exception, limit: int = 120) -> str:
        message = " ".join(str(error or "").split())
        if len(message) <= limit:
            return message
        return message[: max(1, limit - 3)].rstrip() + "..."

    def _check_uid_status_with_retry(self, uid: str) -> dict | None:
        proxy_value = getattr(self.task, "proxy", "")
        proxy_attempted = False
        last_error = None

        try:
            proxies = build_requests_proxies(proxy_value)
        except Exception as exc:
            proxies = None
            last_error = exc
            self.log_row(f"Proxy kiểm tra UID không hợp lệ, bỏ qua proxy: {self._short_error(exc)}")

        for attempt in range(1, 3):
            if self._stop_requested:
                return None

            try:
                if proxies:
                    proxy_attempted = True
                    return check_facebook_uid_status(uid, proxies=proxies, timeout=15)
                return check_facebook_uid_status(uid, proxies=None, timeout=15)
            except FacebookUidCheckNetworkError as exc:
                last_error = exc
                self.log_row(f"Lỗi mạng khi kiểm tra UID lần {attempt}/2: {self._short_error(exc)}")
                if not self.sleep_with_stop(0.8 * attempt):
                    return None
            except Exception as exc:
                last_error = exc
                self.log_row(f"Không kiểm tra được UID: {self._short_error(exc)}")
                return None

        if proxy_attempted and not self._stop_requested:
            try:
                self.log_row("Proxy lỗi, thử kiểm tra UID không dùng proxy")
                return check_facebook_uid_status(uid, proxies=None, timeout=15)
            except Exception as exc:
                last_error = exc
                self.log_row(f"Không kiểm tra được UID sau fallback: {self._short_error(exc)}")

        if last_error:
            logger.warning("[Row %s] UID check failed for uid=%s: %s", self.row, uid, last_error)
        return None

    def run_refresh_login_data(self) -> str:
        self.log_row("Đang cập nhật cookie/token và số page")

        cookie, token = self.handle_login()

        if self._stop_requested:
            return "Đã dừng"

        page_names = None
        if cookie and token:
            page_names = self.fetch_page_names_from_graph(token, cookie)
        else:
            self.log_row("Chưa lấy được cookie/token, chuyển sang đọc tên page bằng HTML")

        if page_names is None:
            page_names = self.fetch_page_names_from_html()

        if page_names is None:
            page_names = []
            self.persist_account_status("Đã đăng nhập", 0, page_names)
            self.log_row("Không lấy được danh sách page, đã cập nhật page = 0")
        else:
            self.persist_account_status("Đã đăng nhập", len(page_names), page_names)
            self.log_row(f"Đã cập nhật {len(page_names)} page")

        return "Đã đăng nhập"

    def run_refresh_page_data(self) -> str:
        self.log_row("Đang cập nhật page mới qua Graph API")

        page_names = self.fetch_page_names_from_graph_with_fallback(
            getattr(self.task, "token", ""),
            getattr(self.task, "cookie", ""),
        )
        if page_names is None:
            db = AccountDB(None)
            old_account = db.find_account_by_exact_path(self.task.path_chrome) or {}
            old_page_count = int(old_account.get("Page_Count") or 0)
            old_page_names = old_account.get("Page_Names") or ""
            self.log_page_count(old_page_count)
            self.log_page_names(self._dedupe_page_names(old_page_names.splitlines()))
            self.log_row("Khong cap nhat duoc page moi, khong ghi de ve 0")
            return "Khong cap nhat duoc page"

        self.persist_account_status("Đã đăng nhập", len(page_names), page_names)
        if page_names:
            self.log_row(f"Đã cập nhật {len(page_names)} page: {', '.join(page_names[:5])}")
        else:
            self.log_row("Đã cập nhật page: tài khoản hiện có 0 page")
        return "Đã đăng nhập"

    # =========================
    # Scan flow
    # =========================
    def process_posts_once(self) -> bool:
        if self._stop_requested:
            return False

        total_groups = len(self.task.groups_list or [])
        self.log_row(f"Bắt đầu xử lý bài viết: {total_groups} group / 1 chu kỳ")

        self.scanner = ScanController(
            groups_list=self.task.groups_list,
            delay=float(self.task.delay_get_post_gr),
            recent_window_minutes=float(self.task.cycle_total or 0) * 60,
            keywords=self.task.keywords_list,
            API_KEY=self.task.api_key,
            account_token=self.eaag_token,
            account_cookies=self.cookie_raw,
            account_name=self.task.account_name,
            proxies=build_requests_proxies(getattr(self.task, "proxy", "")),
            token_tele=self.task.token_tele,
            idchat=self.task.id_chat,
            prompt=self.task.prompt,
            prompt_cmt=self.task.prompt_cmt,
            prompt_cmt_mode=self.task.prompt_cmt_mode,
            max_length_text=100000,
            progress_callback=self.log_interaction,
            status_callback=self.log_row,
            post_callback=self.log_post,
            stop_callback=self.is_stop_requested,
        )

        logger.info("Bắt đầu scan group=%s", total_groups)

        if self._stop_requested:
            return False

        results = self.scanner.start_scan()
        logger.info(f"[Row {self.row}] Kết quả scan: {results}")

        if self._stop_requested:
            return False

        self.log_row(f"Đã xử lý xong {total_groups} group trong chu kỳ này")
        return True

    # =========================
    # Main thread flow
    # =========================
    def run(self):
        if self.action_mode not in ("crawl", "check_uid_status", "refresh_login_data", "refresh_page_data"):
            final_status = "Chức năng này không còn được hỗ trợ"
            self.log_row(final_status)
            self.finished_signal.emit(self.row, final_status)
            return

        if self.action_mode in ("check_uid_status", "refresh_login_data", "refresh_page_data"):
            final_status = "Đã dừng"
            try:
                if self.action_mode == "check_uid_status":
                    final_status = self.run_check_uid_status()
                elif self.action_mode == "refresh_login_data":
                    final_status = self.run_refresh_login_data()
                elif self.action_mode == "refresh_page_data":
                    final_status = self.run_refresh_page_data()
            except Exception as e:
                logger.exception(f"[Row {self.row}] Lỗi cập nhật đăng nhập: {e}")
                final_status = f"Lỗi: {e}"
            finally:
                self.close()
                self.finished_signal.emit(self.row, final_status)
            return

        final_status = "Đã dừng"
        cycle_index = 0

        try:
            while not self._stop_requested:
                cycle_index += 1
                total_groups = len(self.task.groups_list or [])

                self.log_row(f"Bắt đầu chu kỳ {cycle_index}")

                # =========================
                # LOGIN / CHECK ACCOUNT (LUỒNG 2)
                # Check account bằng cookie+token -> hợp lệ chạy luôn;
                # không hợp lệ thì refresh token rồi recheck Graph.
                # =========================
                self.cookie_raw, self.eaag_token = self.prepare_worker_account()

                if self._stop_requested:
                    final_status = "Đã dừng"
                    break

                if not self.cookie_raw or not self.eaag_token:
                    # Sau N lần refresh vẫn không lấy được token hợp lệ.
                    final_status = "Có thể nick bị đăng xuất"
                    self.log_row(final_status)
                    break

                self.log_row(f"Chu kỳ {cycle_index}: bắt đầu scan {total_groups} group")

                # =========================
                # SCAN 1 CHU KỲ
                # =========================
                ok = self.process_posts_once()
                logger.info("[Row %s] Scan result: %s", self.row, ok)

                if self._stop_requested:
                    final_status = "Đã dừng"
                    break

                if not ok:
                    final_status = "Xử lý bài viết thất bại"
                    break

                # =========================
                # HOÀN THÀNH 1 CHU KỲ
                # =========================
                self.log_row(f"Hoàn thành chu kỳ {cycle_index}")

                # reset để vòng sau login lại
                self.cookie_raw = None
                self.eaag_token = None

                # delay giữa các chu kỳ
                if not self.sleep_with_stop(2):
                    final_status = "Đã dừng"
                    break

            # nếu bị stop
            if self._stop_requested:
                final_status = "Đã dừng"

        except Exception as e:
            logger.exception(f"[Row {self.row}] Lỗi run: {e}")
            final_status = f"Lỗi: {e}"

        finally:
            self.close()
            self.finished_signal.emit(self.row, final_status)
