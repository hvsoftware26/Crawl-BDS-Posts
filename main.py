# Main GUI
import sys, os, json, shutil, logging
from logging import getLogger
from pathlib import Path
from typing import List
from PyQt5.QtCore import Qt, QTimer
from PyQt5.QtWidgets import (
    QApplication, QMainWindow, QTableWidgetItem, QMessageBox, QFileDialog,
    QMenu, QHBoxLayout, QVBoxLayout, QWidget, QCheckBox, QDialog,
    QLabel, QLineEdit, QPushButton,
)
from playwright.sync_api import sync_playwright
from services.sql_query_service import AccountDB
from controllers.scan_controller import reset_posts_json
from resources.ui.gui import MultiProfileDialog, Ui_MainWindow, create_application
from services.ai_service import OpenAIService
from models.account import Info_data
from workers.account_import_worker import AccountImportWorker
from workers.process_worker import Worker_Handle
from integrations.facebook_client import get_managed_page_names
from utils.facebook_cookies import (
    build_facebook_playwright_cookies,
    parse_cookie_header,
)
from utils.group_distribution import split_groups_for_accounts
from utils.proxy_utils import (
    build_playwright_proxy,
    build_requests_proxies,
    mask_proxy,
    parse_proxy,
    verify_browser_proxy_ip,
)
from utils.security import mask_secret
from app_config import (
    APP_BASE_DIR,
    CHROME_PATH,
    OPENAI_MODEL_NAME,
)
OPENAI_API_KEY_ENV = "OPENAI_API_KEY"
UID_CHECK_DEFAULT_THREADS = 8
MANUAL_FACEBOOK_LOGIN_URLS = (
    "https://m.facebook.com/login/?locale=vi_VN",
    "https://www.facebook.com/login/?locale=vi_VN",
    "https://www.facebook.com/login.php?locale=vi_VN",
)

logger = getLogger(__name__)

VIEW_CHROME_URL = "https://www.facebook.com/?locale=vi_VN"

# Flag mạng cho cửa sổ Chrome xem tay: chặn QUIC/UDP để proxy đi TCP, tránh treo
# request; ẩn navigator.webdriver để Facebook không bóp feed động.
VIEW_CHROME_NETWORK_ARGS = [
    "--disable-quic",
    "--disable-features=UseDnsHttpsSvcb,UseDnsHttpsSvcbAlpn,EncryptedClientHello",
    "--dns-prefetch-disable",
    "--disable-background-networking",
    "--force-webrtc-ip-handling-policy=disable_non_proxied_udp",
    "--webrtc-ip-handling-policy=disable_non_proxied_udp",
    "--disable-blink-features=AutomationControlled",
]


def reset_runtime_logs():
    reset_file_handler = False
    for handler in logging.getLogger().handlers:
        if not isinstance(handler, logging.FileHandler):
            continue

        try:
            handler.acquire()
            if handler.stream:
                handler.flush()
                handler.stream.seek(0)
                handler.stream.truncate()
            reset_file_handler = True
        except Exception:
            logger.exception("Could not reset runtime log handler")
        finally:
            try:
                handler.release()
            except Exception:
                pass

    if reset_file_handler:
        return

    try:
        (APP_BASE_DIR / "main.log").write_text("", encoding="utf-8")
    except Exception:
        logger.exception("Could not reset runtime log file")


def ensure_profile_directory(path_chrome: str) -> str:
    profile_path = Path(path_chrome).resolve()
    profile_path.mkdir(parents=True, exist_ok=True)
    return str(profile_path)


class ProxyUpdateDialog(QDialog):
    def __init__(self, current_proxy: str = "", parent=None):
        super().__init__(parent)
        self.setWindowTitle("Cập nhật proxy")
        self.setModal(True)
        self.setMinimumWidth(420)

        layout = QVBoxLayout(self)

        label = QLabel("Proxy mới")
        self.proxy_input = QLineEdit()
        self.proxy_input.setPlaceholderText("ip:port:user:pass hoặc ip:port")
        self.proxy_input.setText(str(current_proxy or ""))
        self.proxy_input.selectAll()

        layout.addWidget(label)
        layout.addWidget(self.proxy_input)

        button_row = QHBoxLayout()
        self.cancel_btn = QPushButton("Hủy")
        self.cancel_btn.setStyleSheet(
            "QPushButton { background:#16a34a; color:white; font-weight:600; padding:7px 16px; border-radius:6px; }"
            "QPushButton:hover { background:#15803d; }"
        )
        self.confirm_btn = QPushButton("Xác nhận")
        self.confirm_btn.setStyleSheet(
            "QPushButton { background:#dc2626; color:white; font-weight:600; padding:7px 16px; border-radius:6px; }"
            "QPushButton:hover { background:#b91c1c; }"
        )
        self.cancel_btn.clicked.connect(self.reject)
        self.confirm_btn.clicked.connect(self.accept)
        button_row.addWidget(self.cancel_btn)
        button_row.addWidget(self.confirm_btn)
        layout.addLayout(button_row)

    def proxy_value(self) -> str:
        return self.proxy_input.text().strip()


class CookieTokenUpdateDialog(QDialog):
    def __init__(self, current_token: str = "", current_cookie: str = "", parent=None):
        super().__init__(parent)
        self.setWindowTitle("Cập nhật token/cookie")
        self.setModal(True)
        self.setMinimumWidth(480)

        layout = QVBoxLayout(self)

        token_label = QLabel("Token mới")
        self.token_input = QLineEdit()
        self.token_input.setPlaceholderText("EAAG...")
        self.token_input.setText(str(current_token or ""))

        cookie_label = QLabel("Cookie mới")
        self.cookie_input = QLineEdit()
        self.cookie_input.setPlaceholderText("c_user=...; xs=...; ...")
        self.cookie_input.setText(str(current_cookie or ""))

        layout.addWidget(token_label)
        layout.addWidget(self.token_input)
        layout.addWidget(cookie_label)
        layout.addWidget(self.cookie_input)

        button_row = QHBoxLayout()
        self.cancel_btn = QPushButton("Hủy")
        self.cancel_btn.setStyleSheet(
            "QPushButton { background:#16a34a; color:white; font-weight:600; padding:7px 16px; border-radius:6px; }"
            "QPushButton:hover { background:#15803d; }"
        )
        self.confirm_btn = QPushButton("Xác nhận")
        self.confirm_btn.setStyleSheet(
            "QPushButton { background:#dc2626; color:white; font-weight:600; padding:7px 16px; border-radius:6px; }"
            "QPushButton:hover { background:#b91c1c; }"
        )
        self.cancel_btn.clicked.connect(self.reject)
        self.confirm_btn.clicked.connect(self.accept)
        button_row.addWidget(self.cancel_btn)
        button_row.addWidget(self.confirm_btn)
        layout.addLayout(button_row)

    def token_value(self) -> str:
        return self.token_input.text().strip()

    def cookie_value(self) -> str:
        return self.cookie_input.text().strip()


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.uic = Ui_MainWindow()
        self.uic.setupUi(self)
        reset_runtime_logs()
        self.uic.console.clear()

        self.group_count = 0
        self.profile_lines: List[str] = []
        self.api_key = None
        self.group_file_path = None
        self.prompt_file_path = None
        self.prompt_cmt_file_path = None
        self.tele_file_path = None
        self.id_chat = None
        self.token_tele = None
        self.cycle_total = self.uic.spn_cycle_hours.value()
        self.delay_get_post_gr = None
        self.keywords_list = None
        self.workers = []
        self.pending_tasks = []
        self.pending_action_mode = "crawl"
        self.max_threads = self.uic.spn_threads.value()
        self.stop_requested = False
        self.view_chrome_playwright = None
        self.view_chrome_context = None
        self.view_chrome_page = None
        self.view_chrome_timer = None
        self.view_chrome_row = None
        self.view_chrome_path = None
        self._view_chrome_closed_flag = False
        self.account_import_worker = None
        self.is_running = False

        self._connect_signals()
        AccountDB(None)._create_table()
        self.load_table()
        self.update_delay_between_cycles()

    def _connect_signals(self):
        self.uic.profile_btn.clicked.connect(self.open_profile_dialog)
        self.uic.table.setContextMenuPolicy(Qt.CustomContextMenu)
        self.uic.table.customContextMenuRequested.connect(self.show_menu)
        self.uic.btn_import_group.clicked.connect(self.import_group_file)
        self.uic.btn_import_prompt.clicked.connect(self.import_prompt_file)
        self.uic.btn_import_prompt_cmt.clicked.connect(self.import_prompt_cmt_file)
        self.uic.btn_select_tele.clicked.connect(self.import_tele_file)
        self.uic.btn_check_api.clicked.connect(self.check_api_key)
        self.uic.btn_clear_log.clicked.connect(self.clear_log)
        self.uic.btn_select_all.clicked.connect(self.toggle_all_rows)
        self.uic.btn_delete_row.clicked.connect(self.delete_selected_rows)
        self.uic.btn_start.clicked.connect(self.start_tool)
        self.uic.btn_stop.clicked.connect(self.stop_tool)
        self.uic.spn_cycle_hours.valueChanged.connect(self.update_delay_between_cycles)
        self.uic.table.horizontalHeader().sectionClicked.connect(self.on_table_header_clicked)

    def append_log(self, text: str):
        self.uic.console.append(str(text or ""))

    def clear_log(self):
        self.uic.console.clear()
        self.append_log("Đã xóa log hiển thị.")

    def on_table_header_clicked(self, section: int):
        if section == 0:
            self.toggle_all_rows()

    def _create_center_checkbox(self) -> QWidget:
        holder = QWidget()
        holder.setStyleSheet("background: transparent;")
        layout = QHBoxLayout(holder)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        layout.setAlignment(Qt.AlignCenter)

        checkbox = QCheckBox()
        checkbox.setText("")
        checkbox.setTristate(False)
        checkbox.setFocusPolicy(Qt.NoFocus)
        checkbox.setFixedSize(18, 18)
        checkbox.setStyleSheet(
            "QCheckBox { margin: 0px; padding: 0px; spacing: 0px; }"
            "QCheckBox::indicator { margin: 0px; width: 18px; height: 18px; }"
        )
        layout.addWidget(checkbox)
        return holder

    def _row_checkbox(self, row: int):
        holder = self.uic.table.cellWidget(row, 0)
        if holder is None:
            return None
        return holder.findChild(QCheckBox)

    def _is_row_checked(self, row: int) -> bool:
        checkbox = self._row_checkbox(row)
        if checkbox is not None:
            return checkbox.isChecked()

        item = self.uic.table.item(row, 0)
        return bool(item and item.checkState() == Qt.Checked)

    def _is_valid_table_row(self, row: int) -> bool:
        return isinstance(row, int) and 0 <= row < self.uic.table.rowCount()

    def _set_row_checked(self, row: int, checked: bool):
        checkbox = self._row_checkbox(row)
        if checkbox is not None:
            checkbox.setChecked(checked)
            return

        item = self.uic.table.item(row, 0)
        if item:
            item.setCheckState(Qt.Checked if checked else Qt.Unchecked)

    @staticmethod
    def _normalize_path(path_value: str) -> str:
        return os.path.normcase(os.path.abspath(str(path_value or "").strip()))

    def _same_profile_path(self, left: str, right: str) -> bool:
        return bool(left and right and self._normalize_path(left) == self._normalize_path(right))

    def _sync_view_chrome_state(self):
        # Chrome chạy trên main thread, giữ sống bằng QTimer bơm pipe CDP.
        # Khi user bấm X, context "close" -> _view_chrome_closed_flag = True;
        # ở đây dọn state (đóng playwright, tắt timer) nếu đã đánh dấu đóng.
        if self.view_chrome_path and self._view_chrome_closed_flag:
            self._teardown_view_chrome()

    def _is_view_chrome_running(self) -> bool:
        self._sync_view_chrome_state()
        return bool(self.view_chrome_path)

    def _is_profile_running_in_worker(self, path_chrome: str) -> bool:
        normalized_path = self._normalize_path(path_chrome)
        for worker in self.workers:
            try:
                if worker.isRunning() and self._normalize_path(getattr(worker.task, "path_chrome", "")) == normalized_path:
                    return True
            except Exception:
                continue
        return False

    def _collect_checked_profiles(self):
        checked_profiles = []
        db = AccountDB(None)

        for row in range(self.uic.table.rowCount()):
            if not self._is_row_checked(row):
                continue

            profile_item = self.uic.table.item(row, 2)
            if profile_item is None:
                continue

            profile_name = profile_item.text().strip()
            if not profile_name:
                continue

            full_path = db.find_full_path_from_path_chrome(profile_name)
            checked_profiles.append(
                {
                    "row": row,
                    "profile_name": profile_name,
                    "full_path": full_path,
                }
            )

        return checked_profiles

    def _require_checked_profiles(self, allow_multiple: bool = False):
        checked_profiles = self._collect_checked_profiles()
        if not checked_profiles:
            QMessageBox.warning(self, "Thông báo", "Vui lòng tích chọn tài khoản trước.")
            return []

        if not allow_multiple and len(checked_profiles) != 1:
            QMessageBox.warning(self, "Thông báo", "Chức năng này chỉ dùng cho 1 tài khoản được tích.")
            return []

        return checked_profiles

    def _build_account_task_from_profile(self, profile: dict) -> Info_data:
        db = AccountDB(None)
        profile_name = profile["profile_name"]

        account = db.find_account_from_path_chrome(profile_name) or {}

        return Info_data(
            row=profile["row"],
            account_name=account.get("Account_Name") or "",
            path_chrome=account.get("Path_Chrome") or "",
            proxy=account.get("Proxy") or "",
            email=account.get("Email") or "",
            password=account.get("Password") or "",
            twofa=account.get("Twofa") or "",
            cookie=account.get("Cookie") or "",
            token=account.get("Token") or "",
            post_count=str(account.get("Post_Count") or ""),
            api_key=self.api_key or "",
            groups_list=[],
            prompt="",
            id_chat="",
            token_tele="",
            cycle_total=0,
            delay_get_post_gr=0,
            keywords_list=[],
            prompt_cmt="",
            prompt_cmt_mode="text",
        )

    def update_interact_group(self, row: int, text: str):
        if not self._is_valid_table_row(row):
            return
        item = QTableWidgetItem(text)
        item.setTextAlignment(Qt.AlignCenter)
        self.uic.table.setItem(row, 5, item)

    def on_row_signal(self, row: int, text: str):
        if not self._is_valid_table_row(row):
            return
        item = QTableWidgetItem(str(text or ""))
        item.setTextAlignment(Qt.AlignCenter)
        self.uic.table.setItem(row, 6, item)

    def on_task_finished(self, row: int, text: str):
        if not self._is_valid_table_row(row):
            return
        item = QTableWidgetItem(str(text or ""))
        item.setTextAlignment(Qt.AlignCenter)
        self.uic.table.setItem(row, 6, item)

    def _format_page_cell_text(self, page_count: int | str, page_names: str = "") -> str:
        try:
            count_value = int(page_count or 0)
        except (TypeError, ValueError):
            count_value = 0

        return str(count_value)

    def on_page_signal(self, row: int, page_count: int):
        if not self._is_valid_table_row(row):
            return
        existing_item = self.uic.table.item(row, 4)
        page_names = existing_item.toolTip() if existing_item else ""
        item = QTableWidgetItem(self._format_page_cell_text(page_count, page_names))
        item.setTextAlignment(Qt.AlignCenter)
        item.setData(Qt.UserRole, int(page_count or 0))
        if page_names:
            item.setToolTip(page_names)
        self.uic.table.setItem(row, 4, item)

    def on_page_names_signal(self, row: int, page_names: str):
        if not self._is_valid_table_row(row):
            return
        item = self.uic.table.item(row, 4)
        if item is not None:
            item.setToolTip(page_names or "")
            page_count = item.data(Qt.UserRole)
            if page_count is None:
                page_count = str(item.text()).split("|", 1)[0].strip()
            item.setText(self._format_page_cell_text(page_count, page_names))

    def _create_worker(self, task: Info_data, action_mode: str = "crawl") -> Worker_Handle:
        worker = Worker_Handle(task.row, task, action_mode=action_mode)
        worker.row_signal.connect(self.on_row_signal)
        worker.interaction_signal.connect(self.update_interact_group)
        worker.page_signal.connect(self.on_page_signal)
        worker.page_names_signal.connect(self.on_page_names_signal)
        worker.post_signal.connect(self.on_post_signal)
        worker.finished_signal.connect(self.on_task_finished)
        worker.console_signal.connect(self.append_log)
        worker.finished.connect(self._cleanup_finished_workers)
        return worker

    def _start_pending_workers(self):
        while (
            self.is_running
            and not self.stop_requested
            and self.pending_tasks
            and len(self.workers) < self.max_threads
        ):
            task = self.pending_tasks.pop(0)
            worker = self._create_worker(task, action_mode=self.pending_action_mode)
            self.workers.append(worker)
            self.on_row_signal(task.row, "Đang khởi động")
            worker.start()
            self.append_log(
                f"Đã start worker dòng={task.row + 1} "
                f"({len(self.workers)}/{self.max_threads} luồng đang chạy, "
                f"còn {len(self.pending_tasks)} task chờ)"
            )

    def _cleanup_finished_workers(self):
        self.workers = [w for w in self.workers if w.isRunning()]
        if self.is_running and not self.stop_requested:
            self._start_pending_workers()

        if not self.workers and not self.pending_tasks:
            should_log = self.is_running or self.stop_requested
            was_stopping = self.stop_requested
            self.is_running = False
            self.stop_requested = False
            self.uic.spn_threads.setEnabled(True)
            if should_log:
                if was_stopping:
                    self.append_log("Đã dừng tất cả worker.")
                else:
                    self.append_log("Tất cả worker đã kết thúc.")

    def on_post_signal(self, row: int, status: int):
        if not self._is_valid_table_row(row):
            return
        item = QTableWidgetItem(str(status))
        item.setTextAlignment(Qt.AlignCenter)
        self.uic.table.setItem(row, 7, item)

    def start_tool(self):
        if self.is_running:
            QMessageBox.information(self, "Thông báo", "Tool đang chạy. Vui lòng dừng trước khi chạy lại.")
            return

        self.keywords_list = self.uic.edit_banned_keywords.text().strip()
        self.cycle_total = self.uic.spn_cycle_hours.value()

        required_fields = {
            "API Key": self.api_key,
            "File Group": self.group_file_path,
            "File Prompt": self.prompt_file_path,
            "File Tele": self.tele_file_path,
            "ID Chat": self.id_chat,
            "Token Tele": self.token_tele,
            "Chu kỳ tổng": self.cycle_total,
            "Delay lấy post group": self.delay_get_post_gr,
        }

        def is_missing(value):
            if value is None:
                return True
            if isinstance(value, str):
                return value.strip() == ""
            return False

        missing_fields = [name for name, value in required_fields.items() if is_missing(value)]

        if missing_fields:
            QMessageBox.warning(
                self,
                "Thiếu dữ liệu",
                "Vui lòng nhập đầy đủ dữ liệu:\n\n- " + "\n- ".join(missing_fields)
            )
            return

        tasks = self.build_data(max_active_accounts=None)
        if not tasks:
            return

        if self._is_view_chrome_running():
            conflict_task = next(
                (task for task in tasks if self._same_profile_path(task.path_chrome, self.view_chrome_path)),
                None,
            )
            if conflict_task is not None:
                profile_name = os.path.basename(conflict_task.path_chrome or "")
                QMessageBox.warning(
                    self,
                    "Thông báo",
                    f"Profile {profile_name} đang mở Chrome. Hãy đóng Chrome của profile này trước khi chạy tool.",
                )
                return

        reset_runtime_logs()
        self.uic.console.clear()

        # Crawl worker chạy vòng lặp vô hạn (không tự kết thúc), nên account bị
        # xếp hàng chờ luồng sẽ không bao giờ được crawl. Vì vậy chạy tất cả
        # account đã chọn cùng lúc; "Số luồng" không giới hạn crawl flow nữa.
        self.max_threads = len(tasks)
        self.pending_tasks = list(tasks)
        self.pending_action_mode = "crawl"
        self.workers.clear()
        self.stop_requested = False
        self.is_running = True
        reset_posts_json()
        # Crawl chạy tất cả account cùng lúc nên "Số luồng" không còn tác dụng ở
        # đây; khóa lại khi đang crawl để tránh nhầm là nó giới hạn luồng.
        self.uic.spn_threads.setEnabled(False)
        self.append_log(
            f"Bắt đầu chạy tool với {self.max_threads} luồng / {len(tasks)} task."
        )

        for task in self.pending_tasks:
            self.on_row_signal(task.row, "Đang chờ luồng")

        self._start_pending_workers()

    def stop_tool(self):
        if not self.workers and not self.pending_tasks:
            self.append_log("Không có worker nào đang chạy.")
            self.is_running = False
            return

        self.stop_requested = True
        queued_count = len(self.pending_tasks)
        self.pending_tasks.clear()
        if queued_count:
            self.append_log(f"Đã hủy {queued_count} task đang chờ luồng.")

        self.append_log("Đang gửi tín hiệu dừng tới tất cả worker...")

        alive_workers = []
        for worker in self.workers:
            try:
                if worker.isRunning():
                    worker.stop()
                    alive_workers.append(worker)
            except Exception as e:
                self.append_log(f"Lỗi khi stop worker: {e}")

        for worker in alive_workers:
            try:
                if not worker.wait(5000):
                    self.append_log(f"Worker chưa dừng kịp: row={getattr(worker, 'row', 'unknown')}")
            except Exception as e:
                self.append_log(f"Lỗi khi wait worker: {e}")

        self.workers = [w for w in self.workers if w.isRunning()]
        self.is_running = len(self.workers) > 0

        if self.is_running:
            self.append_log("Một số worker vẫn chưa dừng hẳn.")
        else:
            self.stop_requested = False
            self.uic.spn_threads.setEnabled(True)
            self.append_log("Đã dừng tất cả worker.")

    def load_table(self):
        try:
            self.uic.table.setUpdatesEnabled(False)
            self.uic.table.setRowCount(0)

            for data in AccountDB(None).get_all_accounts():
                self.insert_row(
                    data.get('Account_Name', ''),
                    os.path.basename(data.get('Path_Chrome', '')).split("\\")[-1],
                    data.get('Proxy', ''),
                    data.get('Page_Count', 0),
                    data.get('Page_Names', ''),
                    "",
                    data.get('Status', ''),
                    data.get('Post_Count', ''),
                )
        except Exception:
            pass
        finally:
            self.uic.table.setUpdatesEnabled(True)

    
    def open_profile_dialog(self):
        if self._is_account_import_running():
            QMessageBox.information(self, "Thông báo", "Đang import tài khoản. Vui lòng đợi tiến trình hiện tại kết thúc.")
            return

        dialog = MultiProfileDialog(self)
        if dialog.exec_() != QDialog.Accepted:
            return

        raw_lines = [line.strip() for line in dialog.editor.toPlainText().splitlines() if line.strip()]
        if not raw_lines:
            QMessageBox.warning(self, "Cảnh báo", "Chưa có dữ liệu tài khoản.")
            return

        self._start_account_import_worker(raw_lines)

    def _is_account_import_running(self) -> bool:
        return bool(self.account_import_worker and self.account_import_worker.isRunning())

    def _start_account_import_worker(self, raw_lines: list[str]):
        worker = AccountImportWorker(raw_lines)
        self.account_import_worker = worker
        self.uic.profile_btn.setEnabled(False)
        self.uic.profile_info.setText(f"Đang import {len(raw_lines)} tài khoản...")
        self.append_log(f"Bắt đầu import {len(raw_lines)} tài khoản trong luồng nền.")

        worker.log_signal.connect(self.append_log)
        worker.progress_signal.connect(self.uic.profile_info.setText)
        worker.error_signal.connect(self._on_account_import_error)
        worker.finished_signal.connect(self._on_account_import_finished)
        worker.finished.connect(self._on_account_import_thread_finished)
        worker.finished.connect(worker.deleteLater)
        worker.start()

    def _on_account_import_error(self, message: str):
        QMessageBox.warning(self, "Cảnh báo", str(message or "Không import được tài khoản."))

    def _on_account_import_finished(self, summary: dict):
        self.load_table()
        summary_text = str((summary or {}).get("summary_text") or "Đã kết thúc import tài khoản.")
        self.uic.profile_info.setText(summary_text)
        self.append_log(summary_text)

    def _on_account_import_thread_finished(self):
        self.uic.profile_btn.setEnabled(True)
        self.account_import_worker = None

    def import_group_file(self):
        path, _ = QFileDialog.getOpenFileName(
            self,
            "Chọn file danh sách group",
            "",
            "Text/CSV/JSON (*.txt *.csv *.json);;All Files (*)",
        )
        if not path:
            return

        self.group_file_path = path
        self.group_count = self.count_non_empty_lines(path)
        self.uic.group_path.setText(f"{path} | Số lượng group: {self.group_count}")
        self.update_delay_between_cycles()
        self.append_log(f"Đã import danh sách group: {self.group_count} group")

    def import_prompt_file(self):
        path, _ = QFileDialog.getOpenFileName(
            self,
            "Chọn file prompt",
            "",
            "Text Files (*.txt *.md *.json);;All Files (*)",
        )
        if not path:
            return

        self.prompt_file_path = path
        self.uic.prompt_path.setText(path)
        self.append_log("Đã import prompt GPT")

    def import_prompt_cmt_file(self):
        path, _ = QFileDialog.getOpenFileName(
            self,
            "Chọn file prompt cmt",
            "",
            "Text Files (*.txt *.md *.json);;All Files (*)",
        )
        if not path:
            return

        self.prompt_cmt_file_path = path
        self.uic.prompt_cmt_path.setText(path)
        self.append_log("Đã import prompt cmt")

    def import_tele_file(self):
        path, _ = QFileDialog.getOpenFileName(
            self,
            "Chọn file cấu hình bot tele",
            "",
            "JSON Files (*.json);;All Files (*)",
        )
        if not path:
            return

        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)

            id_chat = data.get("id_chat", "").strip()
            token_tele = data.get("token_tele", "").strip()

            if not id_chat or not token_tele:
                QMessageBox.warning(self, "Lỗi", "File JSON thiếu id_chat hoặc token_tele.")
                return

            self.tele_file_path = path
            self.id_chat = id_chat
            self.token_tele = token_tele
            self.uic.tele_path.setText(path)

            self.append_log("Đã import TELE:")
            self.append_log(f" - Chat ID: {id_chat}")
            self.append_log(f" - Token: {mask_secret(token_tele)}")

        except Exception as e:
            QMessageBox.critical(self, "Lỗi", f"Không đọc được file JSON:\n{e}")

    def check_api_key(self):
        raw_api_key = self.uic.api_edit.text().strip()
        api_key_source = "ô nhập"
        if raw_api_key.casefold() == "demo":
            raw_api_key = ""
            self.append_log("Kiểm tra key: đã tắt key demo, thử dùng OPENAI_API_KEY.")

        api_key = raw_api_key or os.environ.get(OPENAI_API_KEY_ENV, "").strip()
        if not raw_api_key and api_key:
            api_key_source = f"biến môi trường {OPENAI_API_KEY_ENV}"

        if not api_key:
            QMessageBox.warning(
                self,
                "Thiếu API key",
                f"Nhập API key hoặc đặt biến môi trường {OPENAI_API_KEY_ENV}.",
            )
            return

        prefix_ok = api_key.startswith('sk-')
        length_ok = len(api_key) >= 20
        if not prefix_ok or not length_ok:
            QMessageBox.warning(self, "Kiểm tra key", "Định dạng API key không hợp lệ.")
            self.append_log(f"Kiểm tra key: định dạng API key không hợp lệ ({mask_secret(api_key)}).")
            return

        try:
            model_name = OPENAI_MODEL_NAME
            service = OpenAIService(api_key=api_key, model=model_name, timeout=20)
            result = service.check_api_key()

            if not result.get('valid'):
                msg = f"API key không hợp lệ.\n\nKey: {result.get('masked_key', '')}\nLý do: {result.get('message', 'Không rõ')}"
                QMessageBox.warning(self, "Kiểm tra key", msg)
                self.append_log(f"Kiểm tra key thất bại: {result.get('message', '')}")
                return

            sample_models = result.get('sample_models', [])
            sample_models_text = '\n'.join(sample_models[:10]) if sample_models else 'Không có'
            info_text = (
                f"API key hợp lệ\n\n"
                f"Key: {result.get('masked_key', '')}\n"
                f"Model mặc định: {result.get('default_model', '')}\n"
                f"Model mặc định khả dụng: {'Có' if result.get('default_model_ok') else 'Không'}\n"
                f"Số model thấy được: {result.get('models_count', 0)}\n\n"
                f"Một số model khả dụng:\n{sample_models_text}\n"
            )
            QMessageBox.information(self, "Kiểm tra key", info_text)
            self.append_log(f"Kiểm tra key: API key hợp lệ, đã lấy thông tin model từ {api_key_source}.")
            self.api_key = api_key

        except Exception as e:
            QMessageBox.critical(self, "Kiểm tra key", f"Lỗi khi kiểm tra API key:\n{e}")
            self.append_log(f"Kiểm tra key lỗi: {e}")

    @staticmethod
    def count_non_empty_lines(path: str) -> int:
        try:
            with open(path, "r", encoding="utf-8") as file:
                return sum(1 for line in file if line.strip())
        except Exception:
            return 0

    @staticmethod
    def read_text_file(path: str) -> str:
        if not path:
            return ""

        try:
            with open(path, "r", encoding="utf-8") as file:
                return file.read().strip()
        except Exception:
            return ""

    @staticmethod
    def format_minutes_value(value: float) -> str:
        rounded = round(value, 1)
        if abs(rounded - int(rounded)) < 1e-9:
            return f"{int(rounded)} phút"
        return f"{rounded:.1f}".replace(".", ",") + " phút"

    def update_delay_between_cycles(self):
        if self.group_count <= 0:
            self.uic.lb_delay_between_cycles.setText("Delay giữa các chu kỳ: 0 phút")
            self.delay_get_post_gr = "0"
            return

        minutes_per_cycle = (self.uic.spn_cycle_hours.value() * 60.0) / self.group_count
        self.uic.lb_delay_between_cycles.setText(f"Delay giữa các chu kỳ: {self.format_minutes_value(minutes_per_cycle)}")
        rounded = round(minutes_per_cycle, 1)
        self.delay_get_post_gr = str(int(rounded)) if abs(rounded - int(rounded)) < 1e-9 else str(rounded).replace(".", ",")

    def toggle_all_rows(self):
        target = not self.are_all_checked()
        state = Qt.Checked if target else Qt.Unchecked

        for row in range(self.uic.table.rowCount()):
            self._set_row_checked(row, state == Qt.Checked)

    def are_all_checked(self) -> bool:
        total = self.uic.table.rowCount()
        if total == 0:
            return False

        for row in range(total):
            if not self._is_row_checked(row):
                return False

        return True

    def delete_selected_rows(self):
        selected_accounts = []
        db = AccountDB(None)
        self._sync_view_chrome_state()

        for profile in self._collect_checked_profiles():
            account_id = db.find_id_from_path_chrome(profile["profile_name"])
            selected_accounts.append((account_id, profile["full_path"]))

        if not selected_accounts:
            QMessageBox.warning(self, "Thông báo", "Chưa có profile nào được chọn!")
            return

        for _, full_path in selected_accounts:
            if self._same_profile_path(full_path, self.view_chrome_path):
                QMessageBox.warning(
                    self,
                    "Thông báo",
                    "Không thể xóa profile đang mở trong Chrome. Hãy đóng Chrome trước.",
                )
                return

            if self._is_profile_running_in_worker(full_path):
                QMessageBox.warning(
                    self,
                    "Thông báo",
                    "Không thể xóa profile đang được worker sử dụng.",
                )
                return

        delete_accept = QMessageBox.question(
            self,
            'Xác nhận',
            f'Xác nhận xóa {len(selected_accounts)} profiles?',
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No
        )

        if delete_accept == QMessageBox.Yes:
            for account_id, full_path in reversed(selected_accounts):
                AccountDB(None).delete_account(account_id)
                try:
                    shutil.rmtree(full_path)
                except FileNotFoundError:
                    pass
            self.append_log(f"Đã xóa {len(selected_accounts)} profiles.")

        self.load_table()

    def _set_item(self, row, col, value, align):
        item = QTableWidgetItem(str(value or ""))
        item.setTextAlignment(int(align))
        self.uic.table.setItem(row, col, item)
        return item

    def insert_row(self, account_name, path_chrome, proxy, page_count, page_names, interact, status, post_count):
        self.uic.table.setColumnCount(8)
        row = self.uic.table.rowCount()
        self.uic.table.insertRow(row)

        self.uic.table.setCellWidget(row, 0, self._create_center_checkbox())

        self._set_item(row, 1, account_name, Qt.AlignHCenter | Qt.AlignVCenter)
        self._set_item(row, 2, path_chrome, Qt.AlignHCenter | Qt.AlignVCenter)
        self._set_item(row, 3, proxy, Qt.AlignHCenter | Qt.AlignVCenter)
        page_item = self._set_item(
            row,
            4,
            self._format_page_cell_text(page_count, page_names),
            Qt.AlignHCenter | Qt.AlignVCenter,
        )
        try:
            page_item.setData(Qt.UserRole, int(page_count or 0))
        except (TypeError, ValueError):
            page_item.setData(Qt.UserRole, 0)
        if page_names:
            page_item.setToolTip(page_names)
        self._set_item(row, 5, interact, Qt.AlignHCenter | Qt.AlignVCenter)
        self._set_item(row, 6, status, Qt.AlignHCenter | Qt.AlignVCenter)
        self._set_item(row, 7, post_count, Qt.AlignHCenter | Qt.AlignVCenter)

    def show_menu(self, pos):
        if self.uic.table.rowAt(pos.y()) < 0:
            return

        menu = QMenu(self)
        copy_path_ = menu.addAction("📋 Copy đường dẫn profile")
        copy_proxy = menu.addAction("🌍 Copy proxy (tài nguyên)")
        copy_info_account = menu.addAction("📧 Copy mail|pass|pass_mail")
        copy_token = menu.addAction("🔑 Copy token (tài nguyên)")
        copy_cookie = menu.addAction("🍪 Copy cookie (tài nguyên)")
        update_proxy = menu.addAction("♻️ Cập nhật proxy")
        update_cookie_token = menu.addAction("🔑 Cập nhật token/cookie")
        view_chrome = menu.addAction("🌐 Xem Chrome")
        login_chrome = menu.addAction("🔓 Đăng nhập (gắn cookie)")
        menu.addSeparator()
        refresh_pages = menu.addAction("👥 Cập nhật page mới")
        update_page_count = menu.addAction("🔢 Cập nhật số page (me/accounts)")
        check_uid_status = menu.addAction("✅ Kiểm tra UID sống/chết")

        selected_action = menu.exec(self.uic.table.viewport().mapToGlobal(pos))
        if selected_action is None:
            return

        if selected_action == refresh_pages:
            if self._require_checked_profiles(allow_multiple=True):
                self.refresh_pages_selected_accounts()
            return

        if selected_action == update_page_count:
            profiles = self._require_checked_profiles(allow_multiple=True)
            if profiles:
                self.update_page_count_selected_accounts(profiles)
            return

        if selected_action == check_uid_status:
            if self._require_checked_profiles(allow_multiple=True):
                self.check_uid_status_selected_accounts()
            return

        if selected_action == update_proxy:
            profiles = self._require_checked_profiles(allow_multiple=True)
            if profiles:
                self.update_proxy_selected_accounts(profiles)
            return

        if not self._require_checked_profiles(allow_multiple=False):
            return

        if selected_action == copy_path_:
            self.copy_path()
        elif selected_action == update_cookie_token:
            self.update_cookie_token_selected_account()
        elif selected_action == copy_proxy:
            self.copy_proxy()
        elif selected_action == copy_info_account:
            self.copy_info_account()
        elif selected_action == copy_token:
            self.copy_token()
        elif selected_action == copy_cookie:
            self.copy_cookie()
        elif selected_action == view_chrome:
            self.view_chrome_profile()
        elif selected_action == login_chrome:
            self.login_chrome_profile()

    def _start_account_action(self, profiles: list[dict], action_mode: str, label: str, max_threads: int):
        if self.is_running:
            QMessageBox.information(self, "Thông báo", "Đang có tiến trình chạy. Vui lòng dừng trước khi chạy chức năng khác.")
            return

        if action_mode not in ("check_uid_status", "refresh_page_data") and self._is_view_chrome_running():
            conflict_profile = next(
                (profile for profile in profiles if self._same_profile_path(profile["full_path"], self.view_chrome_path)),
                None,
            )
            if conflict_profile is not None:
                QMessageBox.warning(
                    self,
                    "Thông báo",
                    f"Profile {conflict_profile['profile_name']} đang mở Chrome. Hãy đóng Chrome trước.",
                )
                return

        tasks = [self._build_account_task_from_profile(profile) for profile in profiles]
        if not tasks:
            return

        self.max_threads = min(max(1, max_threads), len(tasks))
        self.pending_tasks = tasks
        self.pending_action_mode = action_mode
        self.workers.clear()
        self.stop_requested = False
        self.is_running = True

        self.append_log(f"Bắt đầu {label}: {len(tasks)} tài khoản, {self.max_threads} luồng.")
        for task in self.pending_tasks:
            self.on_row_signal(task.row, "Đang chờ luồng")

        self._start_pending_workers()

    def check_uid_status_selected_accounts(self):
        profiles = self._require_checked_profiles(allow_multiple=True)
        if not profiles:
            return

        configured_threads = max(1, int(self.uic.spn_threads.value()))
        default_threads = min(len(profiles), UID_CHECK_DEFAULT_THREADS)
        self._start_account_action(
            profiles=profiles,
            action_mode="check_uid_status",
            label="kiểm tra UID sống/chết",
            max_threads=max(configured_threads, default_threads),
        )

    def refresh_pages_selected_accounts(self):
        profiles = self._require_checked_profiles(allow_multiple=True)
        if not profiles:
            return

        configured_threads = max(1, int(self.uic.spn_threads.value()))
        self._start_account_action(
            profiles=profiles,
            action_mode="refresh_page_data",
            label="cập nhật page mới",
            max_threads=configured_threads,
        )

    def update_page_count_selected_accounts(self, profiles: list[dict]):
        # Bản đồng bộ chạy ngay trên main thread (không qua worker): với mỗi
        # profile, gọi /me/accounts bằng token+cookie của nick (qua proxy nếu
        # có) để đếm số page, rồi ghi DB + cập nhật cell. Nick chính đã bị loại
        # khỏi danh sách page trong get_managed_page_names.
        if not profiles:
            return

        db = AccountDB(None)
        updated_count = 0
        failed_profiles = []

        for profile in profiles:
            profile_name = profile["profile_name"]
            account = db.find_account_from_path_chrome(profile_name) or {}
            token = account.get("Token") or ""
            cookie = account.get("Cookie") or ""
            proxy = account.get("Proxy") or ""
            account_name = account.get("Account_Name") or ""

            if not token:
                failed_profiles.append(f"{profile_name} (thiếu token)")
                continue

            try:
                page_names = get_managed_page_names(
                    token,
                    account_cookies=cookie,
                    account_name=account_name,
                    proxies=build_requests_proxies(proxy),
                )
            except Exception as exc:
                failed_profiles.append(f"{profile_name} ({exc})")
                self.append_log(f"Không lấy được page cho {profile_name}: {exc}")
                continue

            page_count = len(page_names)
            db.update_page_info_by_path(
                profile["full_path"],
                page_count,
                "\n".join(page_names),
            )
            self.on_page_signal(profile["row"], page_count)
            self.on_page_names_signal(profile["row"], "\n".join(page_names))
            updated_count += 1
            self.append_log(f"Đã cập nhật {page_count} page cho {profile_name}.")

        if failed_profiles:
            QMessageBox.warning(
                self,
                "Thông báo",
                "Không cập nhật được số page cho:\n" + "\n".join(failed_profiles),
            )

        self.append_log(f"Đã cập nhật số page cho {updated_count}/{len(profiles)} tài khoản.")

    def update_proxy_selected_accounts(self, profiles: list[dict]):
        if not profiles:
            return

        current_values = []
        for profile in profiles:
            item = self.uic.table.item(profile["row"], 3)
            current_values.append(item.text().strip() if item else "")
        current_proxy = current_values[0] if len(set(current_values)) == 1 else ""

        dialog = ProxyUpdateDialog(current_proxy=current_proxy, parent=self)
        if dialog.exec_() != QDialog.Accepted:
            return

        new_proxy = dialog.proxy_value()
        # if not new_proxy:
        #     QMessageBox.warning(self, "Thông báo", "Proxy mới không được để trống.")
        #     return

        try:
            parse_proxy(new_proxy)
        except Exception as exc:
            QMessageBox.warning(self, "Thông báo", f"Proxy không hợp lệ:\n{exc}")
            return

        db = AccountDB(None)
        updated_count = 0
        failed_profiles = []
        for profile in profiles:
            if db.update_proxy_by_path(profile["full_path"], new_proxy):
                updated_count += 1
                self._set_item(
                    profile["row"],
                    3,
                    new_proxy,
                    Qt.AlignHCenter | Qt.AlignVCenter,
                )
            else:
                failed_profiles.append(profile["profile_name"])

        if failed_profiles:
            QMessageBox.warning(
                self,
                "Thông báo",
                "Không cập nhật được proxy cho:\n" + "\n".join(failed_profiles),
            )

        self.append_log(f"Đã cập nhật proxy cho {updated_count} tài khoản.")

    def update_cookie_token_selected_account(self):
        profiles = self._require_checked_profiles(allow_multiple=False)
        if not profiles:
            return

        profile = profiles[0]
        db = AccountDB(None)
        current_token = db.find_token_from_path_chrome(profile["profile_name"])
        current_cookie = db.find_cookie_from_path_chrome(profile["profile_name"])

        dialog = CookieTokenUpdateDialog(
            current_token=current_token,
            current_cookie=current_cookie,
            parent=self,
        )
        if dialog.exec_() != QDialog.Accepted:
            return

        new_token = dialog.token_value()
        new_cookie = dialog.cookie_value()

        if not new_token:
            QMessageBox.warning(self, "Thông báo", "Token mới không được để trống.")
            return
        if not new_cookie:
            QMessageBox.warning(self, "Thông báo", "Cookie mới không được để trống.")
            return

        cookie_map = parse_cookie_header(new_cookie)
        if not (cookie_map.get("c_user") and cookie_map.get("xs")):
            QMessageBox.warning(self, "Thông báo", "Cookie phải có c_user và xs.")
            return

        if db.update_cookie_token_by_path(profile["full_path"], new_cookie, new_token):
            self.append_log(f"Đã cập nhật token/cookie cho {profile['profile_name']}.")
        else:
            QMessageBox.warning(
                self,
                "Thông báo",
                f"Không cập nhật được token/cookie cho {profile['profile_name']}.",
            )

    def copy_path(self):
        checked_paths = []
        for row in range(self.uic.table.rowCount()):
            if self._is_row_checked(row):
                profile_name = self.uic.table.item(row, 2).text()
                checked_paths.append(AccountDB(None).find_full_path_from_path_chrome(profile_name))
        if not checked_paths:
            QMessageBox.warning(self, 'Lỗi', 'Vui lòng tích chọn ít nhất 1 tài khoản để copy đường dẫn profile.')
            return
        QApplication.clipboard().setText('\n'.join(checked_paths))
        QMessageBox.information(self, 'Đã copy', f'Đã copy {len(checked_paths)} đường dẫn profile.')

    def copy_proxy(self):
        checked_paths = []
        for row in range(self.uic.table.rowCount()):
            if self._is_row_checked(row):
                profile_name = self.uic.table.item(row, 2).text()
                checked_paths.append(AccountDB(None).find_proxy_from_path_chrome(profile_name))
        if not checked_paths:
            QMessageBox.warning(self, 'Lỗi', 'Vui lòng tích chọn ít nhất 1 tài khoản để copy proxy.')
            return
        QApplication.clipboard().setText('\n'.join(checked_paths))
        QMessageBox.information(self, 'Đã copy', f'Đã copy {len(checked_paths)} proxy.')

    def copy_info_account(self):
        checked_paths = []
        for row in range(self.uic.table.rowCount()):
            if self._is_row_checked(row):
                profile_name = self.uic.table.item(row, 2).text()
                checked_paths.append(AccountDB(None).find_info_account_from_path_chrome(profile_name))
        if not checked_paths:
            QMessageBox.warning(self, 'Lỗi', 'Vui lòng tích chọn ít nhất 1 tài khoản để copy mail|pass|pass_mail.')
            return
        QApplication.clipboard().setText('\n'.join(checked_paths))
        QMessageBox.information(self, 'Đã copy', f'Đã copy {len(checked_paths)} mail|pass|pass_mail.')

    def copy_token(self):
        checked_paths = []
        for row in range(self.uic.table.rowCount()):
            if self._is_row_checked(row):
                profile_name = self.uic.table.item(row, 2).text()
                checked_paths.append(AccountDB(None).find_token_from_path_chrome(profile_name))
        if not checked_paths:
            QMessageBox.warning(self, 'Lỗi', 'Vui lòng tích chọn ít nhất 1 tài khoản để copy token.')
            return
        QApplication.clipboard().setText('\n'.join(checked_paths))
        QMessageBox.information(self, 'Đã copy', f'Đã copy {len(checked_paths)} token.')

    def copy_cookie(self):
        checked_paths = []
        for row in range(self.uic.table.rowCount()):
            if self._is_row_checked(row):
                profile_name = self.uic.table.item(row, 2).text()
                checked_paths.append(AccountDB(None).find_cookie_from_path_chrome(profile_name))
        if not checked_paths:
            QMessageBox.warning(self, 'Lỗi', 'Vui lòng tích chọn ít nhất 1 tài khoản để copy cookie.')
            return
        QApplication.clipboard().setText('\n'.join(checked_paths))
        QMessageBox.information(self, 'Đã copy', f'Đã copy {len(checked_paths)} cookie.')

    def view_chrome_profile(self):
        # Xem Chrome: mở profile nhưng KHÔNG đụng cookie (giữ nguyên session sẵn có).
        self._open_chrome(add_cookie=False)

    def login_chrome_profile(self):
        # Đăng nhập: mở profile và LUÔN gắn cookie tài khoản vào trình duyệt.
        self._open_chrome(add_cookie=True)

    def _open_chrome(self, add_cookie: bool):
        checked_profiles = self._collect_checked_profiles()
        if not checked_profiles:
            QMessageBox.warning(self, "Lỗi", "Vui lòng tích chọn ít nhất 1 tài khoản để mở Chrome.")
            return

        if len(checked_profiles) > 1:
            QMessageBox.information(self, "Thông báo", "Chỉ nên chọn 1 profile khi mở Chrome.")
            return

        selected_profile = checked_profiles[0]
        profile_path = ensure_profile_directory(selected_profile["full_path"])
        profile_name = selected_profile["profile_name"]
        db = AccountDB(None)
        profile_proxy = db.find_proxy_from_path_chrome(profile_name)
        profile_cookie = db.find_cookie_from_path_chrome(profile_name)

        if self._is_profile_running_in_worker(profile_path):
            QMessageBox.warning(
                self,
                "Thông báo",
                f"Profile {profile_name} đang được worker sử dụng. Hãy dừng worker trước khi mở Chrome tay.",
            )
            return

        if self._is_view_chrome_running():
            if self._same_profile_path(profile_path, self.view_chrome_path):
                QMessageBox.information(self, "Thông báo", f"Profile {profile_name} đang mở Chrome.")
            else:
                current_profile = os.path.basename(self.view_chrome_path or "")
                QMessageBox.information(
                    self,
                    "Thông báo",
                    f"Một profile Chrome khác đang mở ({current_profile}). Hãy đóng cửa sổ đó trước.",
                )
            return

        self._launch_view_chrome(
            selected_profile["row"],
            profile_path,
            profile_proxy,
            profile_cookie,
            profile_name,
            add_cookie=add_cookie,
        )

    def _launch_view_chrome(self, row, profile_path, proxy, cookie, profile_name, add_cookie: bool = False):
        # Chạy Chrome trên main thread (giống test.py chạy mượt), KHÔNG dùng
        # QThread. Giữ cửa sổ sống bằng QTimer bơm pipe CDP mỗi 300ms thay vì
        # vòng msleep: mỗi tick gọi 1 hàm Playwright nên pipe luôn được đọc ->
        # thao tác (scroll/click) không nghẽn. QTimer không block Qt event loop
        # nên GUI tool vẫn phản hồi.
        try:
            proxy_settings = build_playwright_proxy(proxy or "")
        except Exception as exc:
            QMessageBox.warning(self, "Lỗi", f"Proxy không hợp lệ: {exc}")
            return

        args = list(VIEW_CHROME_NETWORK_ARGS)
        launch_options = {
            "user_data_dir": profile_path,
            "executable_path": CHROME_PATH,
            "headless": False,
            # Bỏ --enable-automation: xóa banner "Chrome is being controlled".
            "ignore_default_args": ["--enable-automation"],
            "args": args,
        }
        if proxy_settings:
            launch_options["proxy"] = proxy_settings

        try:
            playwright = sync_playwright().start()
            context = playwright.chromium.launch_persistent_context(**launch_options)
        except Exception as exc:
            error_message = str(exc)
            try:
                playwright.stop()
            except Exception:
                pass
            if "user data directory is already in use" in error_message.lower():
                QMessageBox.warning(
                    self,
                    "Thông báo",
                    "Profile Chrome đang mở ở nơi khác. Hãy đóng Chrome của profile này trước.",
                )
            else:
                QMessageBox.warning(self, "Lỗi", f"Lỗi mở Chrome: {error_message}")
            return

        self.view_chrome_playwright = playwright
        self.view_chrome_context = context
        self.view_chrome_row = row
        self.view_chrome_path = profile_path
        self._view_chrome_closed_flag = False

        # Bấm X đóng cửa sổ -> context "close" -> đánh dấu để teardown ở tick sau.
        context.on("close", lambda _: setattr(self, "_view_chrome_closed_flag", True))

        pages = [
            page
            for page in context.pages
            if not (page.url or "").startswith("chrome-extension://")
        ]
        page = pages[0] if pages else context.new_page()
        page.set_default_timeout(30000)
        page.set_default_navigation_timeout(60000)
        self.view_chrome_page = page

        if proxy_settings:
            self.on_row_signal(row, f"Đang mở Chrome (proxy: {mask_proxy(proxy)})")

        try:
            page.goto(VIEW_CHROME_URL, wait_until="domcontentloaded", timeout=60000)
        except Exception as exc:
            logger.warning("Không mở được Facebook trong Chrome: %s", exc)

        if add_cookie:
            self._sync_view_chrome_cookie(page, context, cookie)

        try:
            page.bring_to_front()
        except Exception:
            pass

        self.view_chrome_timer = QTimer(self)
        self.view_chrome_timer.setInterval(300)
        self.view_chrome_timer.timeout.connect(self._pump_view_chrome)
        self.view_chrome_timer.start()

        self.on_row_signal(row, "Đang mở Chrome")
        self.append_log(f"Đang mở Chrome cho profile: {profile_name}")

    def _pump_view_chrome(self):
        # Tick QTimer: gọi 1 hàm Playwright để drain pipe CDP. Nếu cửa sổ đã đóng
        # (X hoặc context chết) thì teardown.
        if self._view_chrome_closed_flag or not self.view_chrome_context:
            self._teardown_view_chrome()
            return
        try:
            if not self.view_chrome_context.pages:
                self._teardown_view_chrome()
                return
            self.view_chrome_page.wait_for_timeout(50)
        except Exception:
            self._teardown_view_chrome()

    def _sync_view_chrome_cookie(self, page, context, cookie):
        # Chỉ add cookie khi profile chưa đăng nhập đúng nick: so c_user/xs của
        # cookie trình duyệt với cookie tài khoản; trùng thì bỏ qua, lệch thì add.
        account_cookie = parse_cookie_header(cookie or "")
        account_login = {
            name: account_cookie[name]
            for name in ("c_user", "xs")
            if account_cookie.get(name)
        }
        if not account_login:
            return

        try:
            browser_cookies = context.cookies(["https://www.facebook.com"])
        except Exception:
            browser_cookies = []
        browser_login = {
            str(c.get("name")): str(c.get("value"))
            for c in browser_cookies
            if c.get("name") in ("c_user", "xs")
        }
        if browser_login == account_login:
            logger.info("Cookie trình duyệt đã trùng cookie tài khoản, bỏ qua add")
            return

        cookies = build_facebook_playwright_cookies(cookie)
        if not cookies:
            return
        try:
            context.add_cookies(cookies)
            page.goto(VIEW_CHROME_URL, wait_until="domcontentloaded", timeout=60000)
        except Exception as exc:
            logger.warning("Không nạp được cookie: %s", exc)

    def _teardown_view_chrome(self):
        row = self.view_chrome_row

        if self.view_chrome_timer is not None:
            try:
                self.view_chrome_timer.stop()
            except Exception:
                pass
        self.view_chrome_timer = None

        if self.view_chrome_context is not None:
            try:
                self.view_chrome_context.close()
            except Exception:
                pass
        self.view_chrome_context = None

        if self.view_chrome_playwright is not None:
            try:
                self.view_chrome_playwright.stop()
            except Exception:
                pass
        self.view_chrome_playwright = None

        self.view_chrome_page = None
        self.view_chrome_row = None
        self.view_chrome_path = None
        self._view_chrome_closed_flag = False

        if row is not None:
            self.on_row_signal(row, "Đã đóng Chrome")

    def build_data(self, max_active_accounts: int | None = None):
        tasks = []

        keywords_raw = self.uic.edit_banned_keywords.text().strip()
        keywords_list = [keyword.strip() for keyword in keywords_raw.split(",") if keyword.strip()] if keywords_raw else [""]

        groups_list = None
        if self.group_file_path:
            try:
                with open(self.group_file_path, "r", encoding="utf-8") as file:
                    groups_list = [line.strip() for line in file if line.strip()]
            except Exception:
                groups_list = None

        prompt = self.read_text_file(self.prompt_file_path)
        prompt_cmt = self.read_text_file(self.prompt_cmt_file_path)
        prompt_cmt_mode = "ai" if self.uic.radio_prompt_cmt_ai.isChecked() else "text"
        if not prompt_cmt:
            default_comment_filename = "comment_AI.txt" if prompt_cmt_mode == "ai" else "comment.txt"
            default_comment_path = APP_BASE_DIR / default_comment_filename
            if default_comment_path.exists():
                prompt_cmt = self.read_text_file(str(default_comment_path))

        if not groups_list:
            QMessageBox.warning(self, "Lỗi", "Không đọc được danh sách group hoặc file group đang rỗng.")
            return []

        selected_profiles = []
        for row in range(self.uic.table.rowCount()):
            if not self._is_row_checked(row):
                continue

            profile_item = self.uic.table.item(row, 2)
            if profile_item is None:
                continue

            selected_profiles.append((row, profile_item.text()))

        if not selected_profiles:
            QMessageBox.warning(self, 'Lỗi', 'Vui lòng tích chọn ít nhất 1 tài khoản để chạy tool.')
            return []

        if max_active_accounts is not None:
            active_limit = max(1, int(max_active_accounts))
            if len(selected_profiles) > active_limit:
                skipped_count = len(selected_profiles) - active_limit
                self.append_log(
                    f"Chỉ sử dụng {active_limit} nick đầu tiên theo số lượng luồng crawl; bỏ qua {skipped_count} nick đang chọn."
                )
                selected_profiles = selected_profiles[:active_limit]

        group_chunks = split_groups_for_accounts(groups_list, len(selected_profiles))
        db = AccountDB(None)

        for profile_index, ((row, profile_name), assigned_groups) in enumerate(zip(selected_profiles, group_chunks), start=1):
            if not assigned_groups:
                self.append_log(f"Dòng {row + 1}: không có group được chia, bỏ qua nick này.")
                continue

            self.append_log(
                f"Chia group: nick {profile_index}/{len(selected_profiles)} dong {row + 1} nhan {len(assigned_groups)} group."
            )

            account = db.find_account_from_path_chrome(profile_name) or {}

            cycle_total_hours = float(self.cycle_total) if self.cycle_total is not None else 0.0
            if cycle_total_hours > 0 and assigned_groups:
                delay_get_post_gr = (cycle_total_hours * 60.0) / len(assigned_groups)
            else:
                delay_get_post_gr = (
                    float(str(self.delay_get_post_gr).replace(",", "."))
                    if self.delay_get_post_gr not in (None, "")
                    else 0.0
                )

            tasks.append(
                Info_data(
                    row=row,
                    account_name=account.get("Account_Name") or "",
                    path_chrome=account.get("Path_Chrome") or "",
                    proxy=account.get("Proxy") or "",
                    email=account.get("Email") or "",
                    password=account.get("Password") or "",
                    twofa=account.get("Twofa") or "",
                    cookie=account.get("Cookie") or "",
                    token=account.get("Token") or "",
                    post_count=str(account.get("Post_Count") or ""),
                    api_key=self.api_key or "",
                    groups_list=assigned_groups,
                    prompt=prompt,
                    id_chat=self.id_chat or "",
                    token_tele=self.token_tele or "",
                    cycle_total=cycle_total_hours,
                    delay_get_post_gr=delay_get_post_gr,
                    keywords_list=keywords_list,
                    prompt_cmt=prompt_cmt,
                    prompt_cmt_mode=prompt_cmt_mode,
                )
            )

        if not tasks:
            QMessageBox.warning(self, 'Lỗi', 'Vui lòng tích chọn ít nhất 1 tài khoản để chạy tool.')
            return []

        return tasks


def main():
    app = create_application()
    window = MainWindow()
    window.show()
    sys.exit(app.exec_())


if __name__ == "__main__":
    main()
