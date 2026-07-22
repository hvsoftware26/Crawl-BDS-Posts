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
    console_signal = pyqtSignal(str)

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
        self.account_page_names = []

    # =========================
    # Logging helpers
    # =========================
    def log_interaction(self, message: str):
        self.interaction_signal.emit(self.row, message)
        logger.info(f"[Row {self.row}] {message}")

    def log_row(self, message: str):
        self.row_signal.emit(self.row, message)
        logger.info(f"[Row {self.row}] {message}")

    def log_console(self, message: str):
        self.console_signal.emit(str(message or ""))
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
                "--window-position=30,30",
                "--window-size=500,700",
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
                "headless": False,
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

    def is_css_visible(self, selector: str, timeout: int = 3000) -> bool:
        if self._stop_requested:
            return False

        try:
            locator = self.page.locator(selector).first
            locator.wait_for(state="visible", timeout=timeout)
            return True
        except Exception:
            return False

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
        - Không hợp lệ -> mở Chrome, nếu còn session thì capture cookie/token
          mới rồi recheck Graph. Nếu nick đã đăng xuất thì KHÔNG tự đăng nhập
          lại: đặt Status "Cần đăng nhập tay" và trả (None, None) để dừng nick.
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
                    # Không tự đăng nhập lại nữa: đánh dấu trạng thái để user đăng
                    # nhập tay qua chức năng "Đăng nhập (gắn cookie)" rồi dừng nick.
                    self.persist_account_status("Cần đăng nhập tay")
                    self.log_row("Tài khoản bị đăng xuất, cần đăng nhập tay")
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

    def prepare_worker_browser_session(self) -> bool:
        if self._stop_requested:
            return False

        try:
            if not self.context or not self.page:
                self._start_browser()

            if self._stop_requested:
                return False

            self.log_row("Kiem tra phien Facebook bang Playwright")
            if not self.safe_goto("https://www.facebook.com/?locale=vi_VN", wait_until="domcontentloaded"):
                return False

            if not self.sleep_with_stop(random.uniform(2, 4)):
                return False

            if not self.is_logged_in():
                self.persist_account_status("Cần đăng nhập tay")
                self.log_row("Tai khoan bi dang xuat, can dang nhap tay")
                return False

            self.cookie_raw = self.get_cookie_raw()
            self.eaag_token = str(getattr(self.task, "token", "") or "").strip() or None
            self.log_row("Phien Facebook hop le, san sang quet Group bang GraphQL")
            return True
        except Exception as exc:
            logger.exception("[Row %s] Khong chuan bi duoc browser session: %s", self.row, exc)
            self.log_row(f"Khong chuan bi duoc browser session: {self._short_error(exc)}")
            self.close()
            return False

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

    def _load_account_page_info_from_db(self) -> tuple[int, list[str]]:
        account = AccountDB(None).find_account_by_exact_path(self.task.path_chrome) or {}
        try:
            page_count = int(account.get("Page_Count") or 0)
        except (TypeError, ValueError):
            page_count = 0

        page_names = self._dedupe_page_names(
            str(account.get("Page_Names") or "").splitlines()
        )
        return page_count, page_names

    def _ensure_account_has_pages_before_crawl(self) -> bool:
        page_count, page_names = self._load_account_page_info_from_db()
        self.account_page_names = page_names
        self.log_page_count(page_count)
        self.log_page_names(page_names)

        if page_count <= 0:
            self.log_row("Phải có trang mới cho chạy")
            return False

        if not page_names:
            self.log_row("Chưa có danh sách tên page trong DB, hãy cập nhật số page trước khi chạy")

        return True

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
            keywords=self.task.keywords_list,
            API_KEY=self.task.api_key,
            account_token=self.eaag_token,
            account_cookies=self.cookie_raw,
            account_name=self.task.account_name,
            account_page_names=self.account_page_names,
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
            console_callback=self.log_console,
            stop_callback=self.is_stop_requested,
            browser_context=self.context,
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

                if not self._ensure_account_has_pages_before_crawl():
                    final_status = "Phải có trang mới cho chạy"
                    break

                # =========================
                # LOGIN / CHECK ACCOUNT
                # Crawl posts now uses the logged-in Playwright session and GraphQL responses.
                # =========================
                browser_ready = self.prepare_worker_browser_session()

                if self._stop_requested:
                    final_status = "Đã dừng"
                    break

                if not browser_ready:
                    # Khong co browser session hop le de mo Facebook Group.
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
