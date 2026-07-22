from __future__ import annotations

import re
from logging import getLogger
from pathlib import Path

from PyQt5.QtCore import QThread, pyqtSignal
from playwright.sync_api import sync_playwright

from app_config import CHROME_PATH, build_local_profile_path
from integrations.facebook_client import get_account_profile_info, get_managed_page_names
from services.sql_query_service import AccountDB
from utils.account_import import parse_account_import_line
from utils.facebook_cookies import build_facebook_playwright_cookies
from utils.proxy_utils import build_playwright_proxy, build_requests_proxies, check_proxy_status


logger = getLogger(__name__)


class AccountImportWorker(QThread):
    log_signal = pyqtSignal(str)
    progress_signal = pyqtSignal(str)
    error_signal = pyqtSignal(str)
    finished_signal = pyqtSignal(dict)

    def __init__(self, raw_lines: list[str], parent=None):
        super().__init__(parent)
        self.raw_lines = [str(line or "").strip() for line in raw_lines if str(line or "").strip()]
        self.mode_label = "Cookie/Token"

    def stop(self):
        self.requestInterruption()

    def run(self):
        summary = {
            "raw_count": len(self.raw_lines),
            "mode_label": self.mode_label,
            "created_count": 0,
            "updated_count": 0,
            "seeded_count": 0,
            "page_updated_count": 0,
            "stopped": False,
            "error": "",
            "summary_text": "",
        }

        try:
            db = AccountDB(None)

            for line_number, line in enumerate(self.raw_lines, start=1):
                if self.isInterruptionRequested():
                    summary["stopped"] = True
                    break

                self.progress_signal.emit(
                    f"Đang import tài khoản {line_number}/{summary['raw_count']}..."
                )

                try:
                    parsed_profile = self._parse_profile_line(line)
                    action = db.save_imported_cookie_account(
                        uid=parsed_profile["uid"],
                        password=parsed_profile["password"],
                        cookie=parsed_profile["cookie"],
                        token=parsed_profile["token"],
                        email=parsed_profile["email"],
                        mail_password=parsed_profile["mail_password"],
                        twofa=parsed_profile["twofa"],
                        path_chrome=parsed_profile["path_chrome"],
                        proxy=parsed_profile["proxy"],
                    )
                except Exception as exc:
                    summary["error"] = f"Dòng {line_number} không hợp lệ:\n{exc}"
                    self.error_signal.emit(summary["error"])
                    return

                if action == "created":
                    summary["created_count"] += 1
                else:
                    summary["updated_count"] += 1

                path_chrome = parsed_profile["path_chrome"]

                if parsed_profile.get("proxy"):
                    self.progress_signal.emit(
                        f"Dòng {line_number}: đang kiểm tra proxy..."
                    )
                    proxy_result = check_proxy_status(parsed_profile["proxy"])
                    if not proxy_result.get("ok"):
                        db.update_status_by_path(path_chrome, "Proxy hết hạn / lỗi")
                        self.log_signal.emit(
                            f"Dòng {line_number}: {proxy_result.get('message') or 'Proxy hết hạn / lỗi'}"
                        )
                        continue

                if self.isInterruptionRequested():
                    summary["stopped"] = True
                    break

                try:
                    self.progress_signal.emit(
                        f"Dòng {line_number}: đang cập nhật thông tin tài khoản..."
                    )
                    graph_info = self._update_imported_account_graph_info(parsed_profile)
                    summary["page_updated_count"] += 1
                    page_names_text = ", ".join(graph_info.get("page_names") or [])
                    if page_names_text:
                        page_names_text = f" | Page: {page_names_text}"
                    self.log_signal.emit(
                        f"Dòng {line_number}: đã cập nhật {graph_info.get('page_count') or 0} page "
                        f"cho {graph_info.get('account_name') or parsed_profile['uid']}"
                        f"{page_names_text}"
                    )
                except Exception as exc:
                    db.update_status_by_path(path_chrome, "Tài khoản không hoạt động")
                    self.log_signal.emit(f"Dòng {line_number}: tài khoản không hoạt động: {exc}")
                    continue

                if self.isInterruptionRequested():
                    summary["stopped"] = True
                    break

                try:
                    self.progress_signal.emit(
                        f"Dòng {line_number}: đang nạp cookie vào profile Chrome..."
                    )
                    if self._seed_profile_with_facebook_cookie(
                        line_number,
                        path_chrome,
                        parsed_profile["cookie"],
                        parsed_profile.get("proxy", ""),
                    ):
                        summary["seeded_count"] += 1
                        db.update_status_by_path(path_chrome, "Đã đăng nhập")
                    else:
                        db.update_status_by_path(path_chrome, "Đã nhập cookie")
                        self.log_signal.emit(
                            f"Dòng {line_number}: chưa xác nhận được session sau khi gắn cookie."
                        )
                except Exception as exc:
                    db.update_status_by_path(path_chrome, "Đã nhập cookie")
                    self.log_signal.emit(
                        f"Dòng {line_number}: chưa nạp được cookie vào profile Chrome: {exc}"
                    )
        except Exception as exc:
            logger.exception("Lỗi import tài khoản")
            summary["error"] = f"Lỗi import tài khoản: {exc}"
            self.error_signal.emit(summary["error"])
        finally:
            summary["summary_text"] = self._build_summary_text(summary)
            self.finished_signal.emit(summary)

    def _parse_profile_line(self, line: str) -> dict:
        parsed_profile = parse_account_import_line(line)
        parsed_profile["path_chrome"] = self._ensure_profile_directory(
            str(build_local_profile_path(parsed_profile["uid"]))
        )
        return parsed_profile

    @staticmethod
    def _ensure_profile_directory(path_chrome: str) -> str:
        profile_path = Path(path_chrome).resolve()
        profile_path.mkdir(parents=True, exist_ok=True)
        return str(profile_path)

    @staticmethod
    def _update_imported_account_graph_info(parsed_profile: dict) -> dict:
        proxies = build_requests_proxies(parsed_profile.get("proxy", ""))
        profile_info = get_account_profile_info(
            parsed_profile["token"],
            account_cookies=parsed_profile["cookie"],
            proxies=proxies,
        )
        account_name = profile_info.get("name") or parsed_profile["uid"]
        page_names = get_managed_page_names(
            parsed_profile["token"],
            account_cookies=parsed_profile["cookie"],
            account_name=account_name,
            proxies=proxies,
        )

        db = AccountDB(None)
        db.update_account_name_by_path(parsed_profile["path_chrome"], account_name)
        db.update_page_info_by_path(
            parsed_profile["path_chrome"],
            len(page_names),
            "\n".join(page_names),
        )
        return {
            "account_name": account_name,
            "page_count": len(page_names),
            "page_names": page_names,
        }

    def _seed_profile_with_facebook_cookie(
        self,
        line_number: int,
        profile_path: str,
        cookie: str,
        proxy: str = "",
    ) -> bool:
        cookies = build_facebook_playwright_cookies(cookie)
        if not cookies:
            return False

        proxy_settings = build_playwright_proxy(proxy)
        args = [
            "--no-first-run",
            "--no-default-browser-check",
            "--disable-extensions",
            "--disable-sync",
            "--window-position=-32000,-32000",
            "--window-size=1,1",
            "--disable-gpu",
            "--disable-software-rasterizer",
        ]
        launch_options = {
            "user_data_dir": profile_path,
            "executable_path": CHROME_PATH,
            "headless": True,
            "args": args,
        }
        if proxy_settings:
            launch_options["proxy"] = proxy_settings

        playwright = sync_playwright().start()
        context = None
        try:
            context = playwright.chromium.launch_persistent_context(**launch_options)
            context.clear_cookies(domain=re.compile(r"(^|\.)facebook\.com$"))
            context.add_cookies(cookies)

            stored_cookie_names = {
                item.get("name")
                for item in context.cookies(
                    [
                        "https://facebook.com",
                        "https://www.facebook.com",
                        "https://m.facebook.com",
                    ]
                )
            }
            if not {"c_user", "xs"}.issubset(stored_cookie_names):
                return False

            pages = [
                page
                for page in context.pages
                if not (page.url or "").startswith("chrome-extension://")
            ]
            page = pages[0] if pages else context.new_page()
            try:
                page.goto(
                    "https://www.facebook.com/?locale=vi_VN",
                    wait_until="domcontentloaded",
                    timeout=60000,
                )
            except Exception as exc:
                self.log_signal.emit(
                    f"Dòng {line_number}: đã gắn cookie nhưng chưa mở được Facebook qua proxy: {exc}"
                )
            return True
        finally:
            try:
                if context:
                    context.close()
            finally:
                playwright.stop()

    def _build_summary_text(self, summary: dict) -> str:
        saved_count = int(summary.get("created_count", 0) or 0) + int(summary.get("updated_count", 0) or 0)
        account_count = int(summary.get("raw_count", 0) or 0)
        prefix = "Đã lưu"
        if summary.get("stopped"):
            prefix = "Đã dừng import sau khi lưu"
            account_count = saved_count
        elif summary.get("error"):
            prefix = "Import tài khoản bị dừng sau khi lưu"
            account_count = saved_count

        return (
            f"{prefix} {account_count} tài khoản | Chế độ: {summary.get('mode_label') or self.mode_label}"
            f" | Tạo mới: {summary.get('created_count', 0)} | Cập nhật: {summary.get('updated_count', 0)}"
            f" | Nạp cookie profile: {summary.get('seeded_count', 0)}"
            f" | Cập nhật page: {summary.get('page_updated_count', 0)}"
        )
