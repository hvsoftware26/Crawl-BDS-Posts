from __future__ import annotations
import requests
import random
import logging
import time
import threading
from logging import getLogger
from controllers.scan_controller import ScanController
from PyQt5.QtCore import QThread, pyqtSignal
from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeoutError
from services.sql_query_service import AccountDB
from services.get_2fa import Get_Towfa
from models.account import Info_data
from config import CHROME_PATH

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
    post_signal = pyqtSignal(int, int)
    finished_signal = pyqtSignal(int, str)

    def __init__(self, row: int, task: Info_data):
        super().__init__()
        self.row = row
        self.task = task

        self.playwright = None
        self.context = None
        self.page = None
        self.scanner = None

        self.request_captured = False
        self.response_captured = False
        self.cookie_raw = None
        self.eaag_token = None

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
        self.playwright = sync_playwright().start()
        self.context = self.playwright.chromium.launch_persistent_context(
            user_data_dir=self.task.path_chrome,
            executable_path=CHROME_PATH,
            headless=True,
            args=[
                "--window-size=600,540",
                "--lang=vi-VN",
                "--accept-lang=vi-VN,vi",
                "--disable-blink-features=AutomationControlled",
                "--disable-infobars",
                "--no-first-run",
                "--no-default-browser-check",
                "--disable-dev-shm-usage",
                "--disable-features=IsolateOrigins,site-per-process",
                "--disable-background-networking",
                "--disable-background-timer-throttling",
                "--disable-renderer-backgrounding",
                "--disable-backgrounding-occluded-windows",
                "--disable-extensions",
                "--disable-sync",
                "--metrics-recording-only",
                "--mute-audio",
                "--force-webrtc-ip-handling-policy=disable_non_proxied_udp",
                "--webrtc-ip-handling-policy=disable_non_proxied_udp",
            ],
        )

        pages = self.context.pages
        self.page = pages[0] if pages else self.context.new_page()
        self.page.set_default_timeout(30000)
        self.page.set_default_navigation_timeout(20000)

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

            self.log_row(f"Mã 2FA: {twofa_code}")

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
            logger.info(f"[Row {self.row}] COOKIE: {self.cookie_raw}")

    def on_capture_response(self, response):
        if self.response_captured or self._stop_requested:
            return

        try:
            if "business_locations" in response.url:
                text = response.text()
                if '],["EAAGN' in text:
                    self.eaag_token = "EAAGN" + text.split('],["EAAGN')[1].split('","')[0]
                    self.response_captured = True
                    logger.info(f"[Row {self.row}] Bắt được EAAG token")
        except Exception as e:
            logger.error(f"[Row {self.row}] Lỗi bắt response token: {e}")

    def start_capture(self):
        self.request_captured = False
        self.response_captured = False
        self.page.on("request", self.on_capture_requests)
        self.page.on("response", self.on_capture_response)

    # =========================
    # Login flow
    # =========================
    def is_logged_in(self) -> bool:
        if self._stop_requested:
            return False

        try:
            current_url = (self.page.url or "").lower()
            has_session = self.has_active_facebook_session()

            if (
                has_session
                and "login" not in current_url
                and "checkpoint" not in current_url
                and "two_factor" not in current_url
                and "recover" not in current_url
            ):
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

            body = self.page.locator("body")
            body.wait_for(state="visible", timeout=5000)
            body_text = body.inner_text(timeout=5000).lower()

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
            return False

    def handle_login(self):
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
            keywords=self.task.keywords_list,
            API_KEY=self.task.api_key,
            account_token=self.eaag_token,
            account_cookies=self.cookie_raw,
            token_tele=self.task.token_tele,
            idchat=self.task.id_chat,
            prompt=self.task.prompt,
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
        final_status = "Đã dừng"
        cycle_index = 0

        try:
            while not self._stop_requested:
                cycle_index += 1
                total_groups = len(self.task.groups_list or [])

                self.log_row(f"Bắt đầu chu kỳ {cycle_index}")

                # =========================
                # LOGIN
                # =========================
                self.cookie_raw, self.eaag_token = self.handle_login()

                if self._stop_requested:
                    final_status = "Đã dừng"
                    break

                if not self.cookie_raw or not self.eaag_token:
                    final_status = "Không lấy được cookie/token"
                    break

                self.log_row(f"Chu kỳ {cycle_index}: bắt đầu scan {total_groups} group")

                # =========================
                # SCAN 1 CHU KỲ
                # =========================
                ok = self.process_posts_once()
                print("SCAN RESULT:", ok)

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
