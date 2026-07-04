# Main GUI
import sys, os, requests, json, shutil, subprocess, ctypes
from ctypes import wintypes
from pathlib import Path
from typing import List
from PyQt5.QtCore import Qt, QEvent, QTimer
from PyQt5.QtWidgets import (
    QApplication, QMainWindow, QTableWidgetItem, QMessageBox, QFileDialog,
    QMenu, QHBoxLayout, QWidget, QCheckBox, QDialog, QLabel, QPushButton,
    QVBoxLayout,
)
from services.sql_query_service import AccountDB, format_proxy_text, format_status_text
from resources.ui.gui import MultiProfileDialog, Ui_MainWindow, create_application
from services.ai_service import OpenAIService
from models.account import Info_data
from workers.process_worker import Worker_Handle
from utils.group_distribution import split_groups_for_accounts
from app_config import (
    APP_BASE_DIR,
    CHROME_PATH,
    FACEBOOK_LOGIN_URL,
    build_profile_path_from_email,
)

MAX_PATH = 260
TH32CS_SNAPPROCESS = 0x00000002
GWL_STYLE = -16
GWL_EXSTYLE = -20
WS_CHILD = 0x40000000
WS_VISIBLE = 0x10000000
WS_CAPTION = 0x00C00000
WS_THICKFRAME = 0x00040000
WS_POPUP = 0x80000000
WS_EX_APPWINDOW = 0x00040000
SW_SHOW = 5
SWP_NOSIZE = 0x0001
SWP_NOMOVE = 0x0002
SWP_NOZORDER = 0x0004
SWP_FRAMECHANGED = 0x0020
WM_CLOSE = 0x0010


class PROCESSENTRY32W(ctypes.Structure):
    _fields_ = [
        ("dwSize", wintypes.DWORD),
        ("cntUsage", wintypes.DWORD),
        ("th32ProcessID", wintypes.DWORD),
        ("th32DefaultHeapID", ctypes.c_void_p),
        ("th32ModuleID", wintypes.DWORD),
        ("cntThreads", wintypes.DWORD),
        ("th32ParentProcessID", wintypes.DWORD),
        ("pcPriClassBase", wintypes.LONG),
        ("dwFlags", wintypes.DWORD),
        ("szExeFile", wintypes.WCHAR * MAX_PATH),
    ]


def _collect_process_tree_pids(root_pid: int) -> set[int]:
    if os.name != "nt" or not root_pid:
        return {root_pid}

    kernel32 = ctypes.windll.kernel32
    kernel32.CreateToolhelp32Snapshot.restype = wintypes.HANDLE
    kernel32.CreateToolhelp32Snapshot.argtypes = [wintypes.DWORD, wintypes.DWORD]
    kernel32.Process32FirstW.argtypes = [wintypes.HANDLE, ctypes.POINTER(PROCESSENTRY32W)]
    kernel32.Process32NextW.argtypes = [wintypes.HANDLE, ctypes.POINTER(PROCESSENTRY32W)]
    kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
    snapshot = kernel32.CreateToolhelp32Snapshot(TH32CS_SNAPPROCESS, 0)
    if snapshot in (0, ctypes.c_void_p(-1).value):
        return {root_pid}

    processes = []
    entry = PROCESSENTRY32W()
    entry.dwSize = ctypes.sizeof(PROCESSENTRY32W)

    try:
        if kernel32.Process32FirstW(snapshot, ctypes.byref(entry)):
            while True:
                processes.append((int(entry.th32ProcessID), int(entry.th32ParentProcessID)))
                if not kernel32.Process32NextW(snapshot, ctypes.byref(entry)):
                    break
    finally:
        kernel32.CloseHandle(snapshot)

    pids = {int(root_pid)}
    changed = True
    while changed:
        changed = False
        for pid, parent_pid in processes:
            if parent_pid in pids and pid not in pids:
                pids.add(pid)
                changed = True

    return pids


def _find_chrome_window(root_pid: int):
    if os.name != "nt" or not root_pid:
        return None

    user32 = ctypes.windll.user32
    pids = _collect_process_tree_pids(root_pid)
    matched_windows = []

    @ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    def enum_windows(hwnd, _):
        if not user32.IsWindowVisible(hwnd) or user32.GetParent(hwnd):
            return True

        pid = wintypes.DWORD()
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        if int(pid.value) not in pids:
            return True

        class_name = ctypes.create_unicode_buffer(256)
        user32.GetClassNameW(hwnd, class_name, 256)
        if class_name.value.startswith("Chrome_WidgetWin"):
            matched_windows.append(hwnd)
            return False

        return True

    user32.EnumWindows(enum_windows, 0)
    return matched_windows[0] if matched_windows else None


def _get_window_long(hwnd, index: int):
    user32 = ctypes.windll.user32
    if ctypes.sizeof(ctypes.c_void_p) == 8:
        user32.GetWindowLongPtrW.restype = ctypes.c_longlong
        user32.GetWindowLongPtrW.argtypes = [wintypes.HWND, ctypes.c_int]
        return user32.GetWindowLongPtrW(wintypes.HWND(hwnd), index)

    user32.GetWindowLongW.restype = ctypes.c_long
    user32.GetWindowLongW.argtypes = [wintypes.HWND, ctypes.c_int]
    return user32.GetWindowLongW(wintypes.HWND(hwnd), index)


def _set_window_long(hwnd, index: int, value: int):
    user32 = ctypes.windll.user32
    if ctypes.sizeof(ctypes.c_void_p) == 8:
        user32.SetWindowLongPtrW.restype = ctypes.c_longlong
        user32.SetWindowLongPtrW.argtypes = [wintypes.HWND, ctypes.c_int, ctypes.c_longlong]
        return user32.SetWindowLongPtrW(wintypes.HWND(hwnd), index, ctypes.c_longlong(value))

    user32.SetWindowLongW.restype = ctypes.c_long
    user32.SetWindowLongW.argtypes = [wintypes.HWND, ctypes.c_int, ctypes.c_long]
    return user32.SetWindowLongW(wintypes.HWND(hwnd), index, ctypes.c_long(value))


def _embed_chrome_window(hwnd, parent_hwnd: int):
    user32 = ctypes.windll.user32
    user32.SetParent.argtypes = [wintypes.HWND, wintypes.HWND]
    user32.SetParent(wintypes.HWND(hwnd), wintypes.HWND(parent_hwnd))

    style = int(_get_window_long(hwnd, GWL_STYLE))
    style = (style & ~(WS_CAPTION | WS_THICKFRAME | WS_POPUP)) | WS_CHILD | WS_VISIBLE
    _set_window_long(hwnd, GWL_STYLE, style)

    ex_style = int(_get_window_long(hwnd, GWL_EXSTYLE))
    ex_style = ex_style & ~WS_EX_APPWINDOW
    _set_window_long(hwnd, GWL_EXSTYLE, ex_style)

    user32.SetWindowPos(
        wintypes.HWND(hwnd),
        None,
        0,
        0,
        0,
        0,
        SWP_NOMOVE | SWP_NOSIZE | SWP_NOZORDER | SWP_FRAMECHANGED,
    )
    user32.ShowWindow(wintypes.HWND(hwnd), SW_SHOW)


def _move_chrome_window(hwnd, width: int, height: int):
    if os.name == "nt" and hwnd:
        ctypes.windll.user32.MoveWindow(wintypes.HWND(hwnd), 0, 0, max(1, width), max(1, height), True)


def _focus_chrome_window(hwnd):
    if os.name != "nt" or not hwnd:
        return

    user32 = ctypes.windll.user32
    kernel32 = ctypes.windll.kernel32
    current_thread_id = kernel32.GetCurrentThreadId()
    target_process_id = wintypes.DWORD()
    target_thread_id = user32.GetWindowThreadProcessId(wintypes.HWND(hwnd), ctypes.byref(target_process_id))

    try:
        if target_thread_id and target_thread_id != current_thread_id:
            user32.AttachThreadInput(current_thread_id, target_thread_id, True)

        user32.SetFocus(wintypes.HWND(hwnd))
        user32.SetActiveWindow(wintypes.HWND(hwnd))
        user32.SetForegroundWindow(wintypes.HWND(hwnd))
    finally:
        if target_thread_id and target_thread_id != current_thread_id:
            user32.AttachThreadInput(current_thread_id, target_thread_id, False)


def ensure_profile_directory(path_chrome: str) -> str:
    profile_path = Path(path_chrome).resolve()
    profile_path.mkdir(parents=True, exist_ok=True)
    return str(profile_path)


class ManualLoginChromeDialog(QDialog):
    def __init__(self, profile_name: str, profile_path: str, parent=None):
        super().__init__(parent)
        self.profile_name = profile_name
        self.profile_path = profile_path
        self.chrome_process = None
        self.chrome_hwnd = None
        self._started = False
        self._chrome_closed = False
        self._attach_attempts = 0

        self.setWindowTitle("Mở Chrome / Đăng nhập")
        self.setMinimumSize(1100, 760)
        self.resize(1200, 820)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 14, 14, 14)
        layout.setSpacing(10)

        title = QLabel(f"Đăng nhập profile: {profile_name}")
        title.setStyleSheet("font-size: 16px; font-weight: 700; color: #16243b;")
        layout.addWidget(title)

        hint = QLabel(
            "Đăng nhập trong khung Chrome bên dưới. Sau khi hoàn tất, tích "
            "\"Đã đăng nhập\" rồi bấm Lưu để cập nhật profile vào database."
        )
        hint.setWordWrap(True)
        layout.addWidget(hint)

        self.status_label = QLabel("Đang mở Chrome...")
        self.status_label.setStyleSheet("color: #31507a; font-weight: 600;")
        layout.addWidget(self.status_label)

        self.chrome_container = QWidget()
        self.chrome_container.setMinimumSize(1000, 600)
        self.chrome_container.setStyleSheet("background: #111827;")
        layout.addWidget(self.chrome_container, 1)

        action_row = QHBoxLayout()
        self.logged_in_checkbox = QCheckBox("Đã đăng nhập")
        action_row.addWidget(self.logged_in_checkbox)
        action_row.addStretch(1)

        self.save_button = QPushButton("Lưu")
        self.cancel_button = QPushButton("Hủy")
        self.save_button.setObjectName("primaryBtn")
        self.cancel_button.setObjectName("dangerBtn")
        self.save_button.clicked.connect(self._save_clicked)
        self.cancel_button.clicked.connect(self.reject)
        action_row.addWidget(self.save_button)
        action_row.addWidget(self.cancel_button)
        layout.addLayout(action_row)

        self.attach_timer = QTimer(self)
        self.attach_timer.setInterval(300)
        self.attach_timer.timeout.connect(self._attach_chrome_window)

        self.resize_timer = QTimer(self)
        self.resize_timer.setSingleShot(True)
        self.resize_timer.setInterval(40)
        self.resize_timer.timeout.connect(self._resize_embedded_chrome)

        self.chrome_container.setAttribute(Qt.WA_NativeWindow, True)
        self.chrome_container.setAttribute(Qt.WA_DontCreateNativeAncestors, True)
        self.chrome_container.setFocusPolicy(Qt.StrongFocus)
        self.chrome_container.installEventFilter(self)
        self.chrome_container.winId()

    def eventFilter(self, watched, event):
        if watched is self.chrome_container and self.chrome_hwnd:
            if event.type() in (QEvent.MouseButtonPress, QEvent.FocusIn, QEvent.Enter, QEvent.KeyPress):
                _focus_chrome_window(self.chrome_hwnd)

        return super().eventFilter(watched, event)

    def showEvent(self, event):
        super().showEvent(event)
        if not self._started:
            self._started = True
            QTimer.singleShot(100, self._start_chrome)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._schedule_resize_embedded_chrome()

    def closeEvent(self, event):
        self._close_chrome()
        super().closeEvent(event)

    def done(self, result):
        self._close_chrome()
        super().done(result)

    def _start_chrome(self):
        if os.name != "nt":
            QMessageBox.critical(self, "Lỗi", "Chức năng nhúng Chrome chỉ hỗ trợ trên Windows.")
            self.reject()
            return

        chrome_args = [
            CHROME_PATH,
            f"--user-data-dir={self.profile_path}",
            "--new-window",
            "--no-first-run",
            "--no-default-browser-check",
            "--window-position=-32000,-32000",
            "--window-size=1100,720",
            "--disable-features=CalculateNativeWinOcclusion,Translate,AutofillServerCommunication,MediaRouter",
            "--disable-background-timer-throttling",
            "--disable-backgrounding-occluded-windows",
            "--disable-renderer-backgrounding",
            "--disable-renderer-accessibility",
            "--disable-spell-checking",
            "--disable-gpu",
            FACEBOOK_LOGIN_URL,
        ]

        try:
            self.chrome_container.winId()
            self.chrome_process = subprocess.Popen(chrome_args)
        except Exception as exc:
            QMessageBox.critical(self, "Lỗi", f"Không mở được Chrome:\n{exc}")
            self.reject()
            return

        self.attach_timer.start()

    def _schedule_resize_embedded_chrome(self):
        if self.chrome_hwnd and not self.resize_timer.isActive():
            self.resize_timer.start()

    def _attach_chrome_window(self):
        if not self.chrome_process:
            return

        if self.chrome_process.poll() is not None:
            self.attach_timer.stop()
            self.status_label.setText("Chrome đã đóng.")
            return

        hwnd = _find_chrome_window(self.chrome_process.pid)
        if not hwnd:
            self._attach_attempts += 1
            if self._attach_attempts >= 80:
                self.status_label.setText("Chưa nhúng được Chrome, bạn có thể đóng form và thử lại.")
            return

        self.chrome_hwnd = hwnd
        self.attach_timer.stop()
        _embed_chrome_window(self.chrome_hwnd, int(self.chrome_container.winId()))
        self._resize_embedded_chrome()
        _focus_chrome_window(self.chrome_hwnd)
        self.status_label.setText("Chrome đã sẵn sàng trong form.")

    def _resize_embedded_chrome(self):
        if self.chrome_hwnd:
            _move_chrome_window(
                self.chrome_hwnd,
                self.chrome_container.width(),
                self.chrome_container.height(),
            )

    def _save_clicked(self):
        if not self.logged_in_checkbox.isChecked():
            QMessageBox.information(
                self,
                "Thông báo",
                "Bạn chưa tích \"Đã đăng nhập\" nên profile chưa được cập nhật.",
            )
            return

        self.accept()

    def _close_chrome(self):
        if self._chrome_closed:
            return

        self._chrome_closed = True
        self.attach_timer.stop()
        self.resize_timer.stop()
        chrome_process = self.chrome_process
        chrome_hwnd = self.chrome_hwnd
        self.chrome_process = None
        self.chrome_hwnd = None

        if chrome_hwnd and os.name == "nt":
            try:
                ctypes.windll.user32.PostMessageW(chrome_hwnd, WM_CLOSE, 0, 0)
            except Exception:
                pass

        if chrome_process and chrome_process.poll() is None:
            QTimer.singleShot(
                3000,
                lambda proc=chrome_process: ManualLoginChromeDialog._terminate_chrome_if_needed(proc),
            )

    @staticmethod
    def _terminate_chrome_if_needed(chrome_process):
        if chrome_process.poll() is not None:
            return

        try:
            chrome_process.terminate()
        except Exception:
            pass

        QTimer.singleShot(1500, lambda proc=chrome_process: ManualLoginChromeDialog._kill_chrome_if_needed(proc))

    @staticmethod
    def _kill_chrome_if_needed(chrome_process):
        if chrome_process.poll() is not None:
            return

        try:
            chrome_process.kill()
        except Exception:
            pass

        try:
            chrome_process.wait(timeout=0)
        except Exception:
            pass


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.uic = Ui_MainWindow()
        self.uic.setupUi(self)

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
        self.view_chrome = None
        self.view_chrome_path = None
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
        self.uic.console.append(text)

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
        if self.view_chrome and self.view_chrome.poll() is not None:
            closed_profile_name = os.path.basename(self.view_chrome_path or "")
            self.view_chrome = None
            self.view_chrome_path = None
            if closed_profile_name:
                self.append_log(f"Đã đóng Chrome profile: {closed_profile_name}")

    def _is_view_chrome_running(self) -> bool:
        self._sync_view_chrome_state()
        return self.view_chrome is not None and self.view_chrome.poll() is None

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

        account_name = db.find_account_name_from_path_chrome(profile_name)
        path_profile = db.find_full_path_from_path_chrome(profile_name)
        proxy = db.find_proxy_from_path_chrome(profile_name)
        info_account = db.find_info_account_from_path_chrome(profile_name)
        cookie = db.find_cookie_from_path_chrome(profile_name)
        token = db.find_token_from_path_chrome(profile_name)
        post_count = db.find_post_count_from_path_chrome(profile_name)

        email, password, twofa = "", "", ""
        if info_account:
            info_parts = info_account.split("|", 2)
            if len(info_parts) == 3:
                email, password, twofa = info_parts
            elif len(info_parts) == 2:
                email, password = info_parts
            elif len(info_parts) == 1:
                email = info_parts[0]

        return Info_data(
            row=profile["row"],
            account_name=account_name or "",
            path_chrome=path_profile or "",
            proxy=proxy or "",
            email=email or "",
            password=password or "",
            twofa=twofa or "",
            cookie=cookie or "",
            token=token or "",
            post_count=str(post_count or ""),
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
        item = QTableWidgetItem(text)
        item.setTextAlignment(Qt.AlignCenter)
        self.uic.table.setItem(row, 5, item)

    def on_row_signal(self, row: int, text: str):
        item = QTableWidgetItem(format_status_text(text))
        item.setTextAlignment(Qt.AlignCenter)
        self.uic.table.setItem(row, 6, item)

    def on_task_finished(self, row: int, text: str):
        item = QTableWidgetItem(format_status_text(text))
        item.setTextAlignment(Qt.AlignCenter)
        self.uic.table.setItem(row, 6, item)

    def on_page_signal(self, row: int, page_count: int):
        item = QTableWidgetItem(str(page_count))
        item.setTextAlignment(Qt.AlignCenter)
        existing_item = self.uic.table.item(row, 4)
        if existing_item and existing_item.toolTip():
            item.setToolTip(existing_item.toolTip())
        self.uic.table.setItem(row, 4, item)

    def on_page_names_signal(self, row: int, page_names: str):
        item = self.uic.table.item(row, 4)
        if item is not None:
            item.setToolTip(page_names or "")

    def _create_worker(self, task: Info_data, action_mode: str = "crawl") -> Worker_Handle:
        worker = Worker_Handle(task.row, task, action_mode=action_mode)
        worker.row_signal.connect(self.on_row_signal)
        worker.interaction_signal.connect(self.update_interact_group)
        worker.page_signal.connect(self.on_page_signal)
        worker.page_names_signal.connect(self.on_page_names_signal)
        worker.post_signal.connect(self.on_post_signal)
        worker.finished_signal.connect(self.on_task_finished)
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
            if should_log:
                if was_stopping:
                    self.append_log("Đã dừng tất cả worker.")
                else:
                    self.append_log("Tất cả worker đã kết thúc.")

    def on_post_signal(self, row: int, status: int):
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

        configured_threads = max(1, int(self.uic.spn_threads.value()))
        tasks = self.build_data(max_active_accounts=configured_threads)
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

        self.max_threads = min(configured_threads, len(tasks))
        self.pending_tasks = list(tasks)
        self.pending_action_mode = "crawl"
        self.workers.clear()
        self.stop_requested = False
        self.is_running = True
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
            self.append_log("Đã dừng tất cả worker.")

    def load_table(self):
        try:
            self.uic.table.setUpdatesEnabled(False)
            self.uic.table.setRowCount(0)

            for data in AccountDB(None).get_all_accounts():
                self.insert_row(
                    data.get('Account_Name', ''),
                    os.path.basename(data.get('Path_Chrome', '')).split("\\")[-1],
                    format_proxy_text(data.get('Proxy', '')),
                    data.get('Page_Count', 0),
                    data.get('Page_Names', ''),
                    "",
                    format_status_text(data.get('Status', '')),
                    data.get('Post_Count', ''),
                )

            self.uic.table.setUpdatesEnabled(True)
        except Exception:
            pass

    
    def _parse_profile_line(self, line: str, normal_mode: bool):
        parts = [part.strip() for part in line.split('|')]

        if normal_mode:
            if len(parts) != 4:
                raise ValueError("Định dạng đúng: tên tài khoản|email|password|2FA")
            account_name, email, password, twofa = parts
            proxy = "Không"
        else:
            if len(parts) != 5:
                raise ValueError("Định dạng đúng: tên tài khoản|proxy|email|password|2FA")
            account_name, proxy, email, password, twofa = parts

        if not account_name:
            raise ValueError("Thiếu tên tài khoản")

        path_chrome = ensure_profile_directory(build_profile_path_from_email(email))

        return {
            "account_name": account_name,
            "proxy": format_proxy_text(proxy),
            "email": email.strip(),
            "password": password.strip(),
            "twofa": twofa.strip(),
            "path_chrome": path_chrome,
        }

    def open_profile_dialog(self):
        dialog = MultiProfileDialog(self)
        if dialog.exec_() != QDialog.Accepted:
            return

        raw_lines = [line.strip() for line in dialog.editor.toPlainText().splitlines() if line.strip()]
        if not raw_lines:
            QMessageBox.warning(self, 'Cảnh báo', 'Chưa có dữ liệu tài khoản.')
            return

        normal_mode = dialog.radio_normal.isChecked()
        mode_label = "Profile Chrome" if normal_mode else "Profile Chrome - Proxy"
        db = AccountDB(None)
        created_count = 0
        updated_count = 0

        for line_number, line in enumerate(raw_lines, start=1):
            try:
                parsed_profile = self._parse_profile_line(line, normal_mode)
                action = db.save_account_profile(**parsed_profile)
            except Exception as exc:
                QMessageBox.warning(
                    self,
                    'Cảnh báo',
                    f'Dòng {line_number} không hợp lệ:\n{exc}',
                )
                return

            if action == "created":
                created_count += 1
            else:
                updated_count += 1

        self.load_table()

        summary_text = (
            f"Đã lưu {len(raw_lines)} tài khoản | Chế độ: {mode_label}"
            f" | Tạo mới: {created_count} | Cập nhật: {updated_count}"
        )
        self.uic.profile_info.setText(summary_text)
        self.append_log(summary_text)

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
                QMessageBox.warning(self, "Lỗi", "File JSON thiếu id_chat hoặc token_tele!")
                return

            self.tele_file_path = path
            self.id_chat = id_chat
            self.token_tele = token_tele
            self.uic.tele_path.setText(path)

            self.append_log("Đã import TELE:")
            self.append_log(f" - Chat ID: {id_chat}")
            self.append_log(f" - Token: {token_tele[:10]}********")

        except Exception as e:
            QMessageBox.critical(self, "Lỗi", f"Không đọc được file JSON:\n{e}")

    def check_api_key(self):
        api_key = self.uic.api_edit.text().strip()
        if api_key == "demo":
            api_key = "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"
        if not api_key:
            QMessageBox.warning(self, "Thiếu dữ liệu", "Vui lòng nhập API key trước khi kiểm tra.")
            return

        prefix_ok = api_key.startswith('sk-')
        length_ok = len(api_key) >= 20
        if not prefix_ok or not length_ok:
            QMessageBox.warning(self, 'Kiểm tra key', 'API key có vẻ không đúng định dạng cơ bản.')
            self.append_log('Check key: key không đúng định dạng cơ bản.')
            return

        try:
            model_name = 'gpt-5.4-nano'
            service = OpenAIService(api_key=api_key, model=model_name, timeout=20)
            result = service.check_api_key()

            if not result.get('valid'):
                msg = f"API key không hợp lệ.\n\nKey: {result.get('masked_key', '')}\nLý do: {result.get('message', 'Không xác định')}"
                QMessageBox.warning(self, 'Kiểm tra key', msg)
                self.append_log(f"Check key fail: {result.get('message', '')}")
                return

            sample_models = result.get('sample_models', [])
            sample_models_text = '\n'.join(sample_models[:10]) if sample_models else 'Không có'
            info_text = (
                f"API key hợp lệ\n\n"
                f"Key: {result.get('masked_key', '')}\n"
                f"Model mặc định: {result.get('default_model', '')}\n"
                f"Dùng được model mặc định: {'Có' if result.get('default_model_ok') else 'Không'}\n"
                f"Tổng model thấy được: {result.get('models_count', 0)}\n\n"
                f"Một số model khả dụng:\n{sample_models_text}\n"
            )
            QMessageBox.information(self, 'Kiểm tra key', info_text)
            self.append_log('Check key: API key hợp lệ, đã lấy thông tin model.')
            self.api_key = api_key

        except Exception as e:
            QMessageBox.critical(self, 'Kiểm tra key', f'Lỗi khi kiểm tra API key:\n{e}')
            self.append_log(f'Check key exception: {e}')

    @staticmethod
    def count_non_empty_lines(path: str) -> int:
        try:
            with open(path, "r", encoding="utf-8") as file:
                return sum(1 for line in file if line.strip())
        except UnicodeDecodeError:
            with open(path, "r", encoding="utf-8-sig", errors="ignore") as file:
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
        except UnicodeDecodeError:
            with open(path, "r", encoding="utf-8-sig", errors="ignore") as file:
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
            QMessageBox.warning(self, "Thông báo", "Chưa có profiles nào được chọn!")
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
            f'Xác nhận xóa {len(selected_accounts)} profiles ?',
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
        item = QTableWidgetItem(str(value))
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
        self._set_item(row, 3, format_proxy_text(proxy), Qt.AlignHCenter | Qt.AlignVCenter)
        page_item = self._set_item(row, 4, page_count, Qt.AlignHCenter | Qt.AlignVCenter)
        if page_names:
            page_item.setToolTip(page_names)
        self._set_item(row, 5, interact, Qt.AlignHCenter | Qt.AlignVCenter)
        self._set_item(row, 6, format_status_text(status), Qt.AlignHCenter | Qt.AlignVCenter)
        self._set_item(row, 7, post_count, Qt.AlignHCenter | Qt.AlignVCenter)

    def show_menu(self, pos):
        if self.uic.table.rowAt(pos.y()) < 0:
            return

        menu = QMenu(self)
        copy_path_ = menu.addAction("📋 Copy đường dẫn Chrome")
        copy_proxy = menu.addAction("🌍 Copy proxy (tài nguyên)")
        copy_info_account = menu.addAction("📧 Copy mail|pass|2FA")
        copy_token = menu.addAction("🔑 Copy token (tài nguyên)")
        copy_cookie = menu.addAction("🍪 Copy cookie (tài nguyên)")
        update_page_names = menu.addAction("📄 Cập nhật tên page")
        open_chrome = menu.addAction("🌐 Mở Chrome / Đăng nhập")
        menu.addSeparator()
        check_login = menu.addAction("✅ Kiểm tra đăng nhập")

        selected_action = menu.exec(self.uic.table.viewport().mapToGlobal(pos))
        if selected_action is None:
            return

        if selected_action == check_login:
            if self._require_checked_profiles(allow_multiple=True):
                self.check_login_selected_accounts()
            return

        if selected_action == update_page_names:
            if self._require_checked_profiles(allow_multiple=True):
                self.update_page_names_selected_accounts()
            return

        if not self._require_checked_profiles(allow_multiple=False):
            return

        if selected_action == copy_path_:
            self.copy_path()
        elif selected_action == copy_proxy:
            self.copy_proxy()
        elif selected_action == copy_info_account:
            self.copy_info_account()
        elif selected_action == copy_token:
            self.copy_token()
        elif selected_action == copy_cookie:
            self.copy_cookie()
        elif selected_action == open_chrome:
            self.open_chrome()

    def _start_account_action(self, profiles: list[dict], action_mode: str, label: str, max_threads: int):
        if self.is_running:
            QMessageBox.information(self, "Thông báo", "Đang có tiến trình chạy. Vui lòng dừng trước khi chạy chức năng khác.")
            return

        if self._is_view_chrome_running():
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

    def check_login_selected_accounts(self):
        profiles = self._require_checked_profiles(allow_multiple=True)
        if not profiles:
            return

        configured_threads = max(1, int(self.uic.spn_threads.value()))
        self._start_account_action(
            profiles=profiles,
            action_mode="check_login",
            label="kiểm tra đăng nhập",
            max_threads=configured_threads,
        )

    def update_page_names_selected_accounts(self):
        profiles = self._require_checked_profiles(allow_multiple=True)
        if not profiles:
            return

        configured_threads = max(1, int(self.uic.spn_threads.value()))
        self._start_account_action(
            profiles=profiles,
            action_mode="refresh_page_names",
            label="cập nhật tên page",
            max_threads=configured_threads,
        )

    def _start_manual_login_refresh(self, selected_profile: dict, saved_path: str, profile_name: str):
        refresh_profile = dict(selected_profile)
        refresh_profile["profile_name"] = os.path.basename(saved_path)
        refresh_profile["full_path"] = saved_path

        def start_refresh():
            if self.is_running:
                self.append_log(
                    f"Chưa cập nhật số page cho profile {profile_name} vì tool đang chạy."
                )
                return

            self._start_account_action(
                profiles=[refresh_profile],
                action_mode="refresh_login_data",
                label="cập nhật số page sau đăng nhập thủ công",
                max_threads=1,
            )

        self.append_log(f"Sẽ cập nhật cookie/token và số page cho profile: {profile_name}")
        QTimer.singleShot(3500, start_refresh)

    def copy_path(self):
        checked_paths = []
        for row in range(self.uic.table.rowCount()):
            if self._is_row_checked(row):
                profile_name = self.uic.table.item(row, 2).text()
                checked_paths.append(AccountDB(None).find_full_path_from_path_chrome(profile_name))
        if not checked_paths:
            QMessageBox.warning(self, 'Error', 'Vui lòng tích chọn ít nhất 1 tài khoản để copy đường dẫn Chrome.')
            return
        QApplication.clipboard().setText('\n'.join(checked_paths))
        QMessageBox.information(self, 'Copied', f'Đã copy {len(checked_paths)} đường dẫn Chrome.')

    def copy_proxy(self):
        checked_paths = []
        for row in range(self.uic.table.rowCount()):
            if self._is_row_checked(row):
                profile_name = self.uic.table.item(row, 2).text()
                checked_paths.append(AccountDB(None).find_proxy_from_path_chrome(profile_name))
        if not checked_paths:
            QMessageBox.warning(self, 'Error', 'Vui lòng tích chọn ít nhất 1 tài khoản để copy proxy.')
            return
        QApplication.clipboard().setText('\n'.join(checked_paths))
        QMessageBox.information(self, 'Copied', f'Đã copy {len(checked_paths)} proxy.')

    def copy_info_account(self):
        checked_paths = []
        for row in range(self.uic.table.rowCount()):
            if self._is_row_checked(row):
                profile_name = self.uic.table.item(row, 2).text()
                checked_paths.append(AccountDB(None).find_info_account_from_path_chrome(profile_name))
        if not checked_paths:
            QMessageBox.warning(self, 'Error', 'Vui lòng tích chọn ít nhất 1 tài khoản để copy mail|pass|2FA.')
            return
        QApplication.clipboard().setText('\n'.join(checked_paths))
        QMessageBox.information(self, 'Copied', f'Đã copy {len(checked_paths)} mail|pass|2FA.')

    def copy_token(self):
        checked_paths = []
        for row in range(self.uic.table.rowCount()):
            if self._is_row_checked(row):
                profile_name = self.uic.table.item(row, 2).text()
                checked_paths.append(AccountDB(None).find_token_from_path_chrome(profile_name))
        if not checked_paths:
            QMessageBox.warning(self, 'Error', 'Vui lòng tích chọn ít nhất 1 tài khoản để copy token.')
            return
        QApplication.clipboard().setText('\n'.join(checked_paths))
        QMessageBox.information(self, 'Copied', f'Đã copy {len(checked_paths)} token.')

    def copy_cookie(self):
        checked_paths = []
        for row in range(self.uic.table.rowCount()):
            if self._is_row_checked(row):
                profile_name = self.uic.table.item(row, 2).text()
                checked_paths.append(AccountDB(None).find_cookie_from_path_chrome(profile_name))
        if not checked_paths:
            QMessageBox.warning(self, 'Error', 'Vui lòng tích chọn ít nhất 1 tài khoản để copy cookie.')
            return
        QApplication.clipboard().setText('\n'.join(checked_paths))
        QMessageBox.information(self, 'Copied', f'Đã copy {len(checked_paths)} cookie.')

    def open_chrome(self):
        checked_profiles = self._collect_checked_profiles()
        if not checked_profiles:
            QMessageBox.warning(self, 'Error', 'Vui lòng tích chọn ít nhất 1 tài khoản để mở Chrome.')
            return

        if len(checked_profiles) > 1:
            QMessageBox.information(self, 'Thông báo', 'Chỉ nên chọn 1 profile khi mở Chrome.')
            return

        selected_profile = checked_profiles[0]
        profile_path = ensure_profile_directory(selected_profile["full_path"])
        profile_name = selected_profile["profile_name"]

        if self._is_profile_running_in_worker(profile_path):
            QMessageBox.warning(
                self,
                'Thông báo',
                f'Profile {profile_name} đang được worker sử dụng. Hãy dừng worker trước khi mở Chrome tay.',
            )
            return

        if self._is_view_chrome_running():
            if self._same_profile_path(profile_path, self.view_chrome_path):
                QMessageBox.information(self, 'Thông báo', f'Profile {profile_name} đang mở Chrome.')
            else:
                current_profile = os.path.basename(self.view_chrome_path or "")
                QMessageBox.information(
                    self,
                    'Thông báo',
                    f'Một profile Chrome khác đang mở ({current_profile}). Hãy đóng cửa sổ đó trước.',
                )
            return

        dialog = ManualLoginChromeDialog(profile_name, profile_path, self)
        self.view_chrome_path = profile_path
        self.append_log(f"Đã mở Chrome đăng nhập cho profile: {profile_name}")

        if dialog.exec_() != QDialog.Accepted:
            self.view_chrome = None
            self.view_chrome_path = None
            self.append_log(f"Chưa xác nhận đăng nhập profile: {profile_name}")
            return

        self.view_chrome = None
        self.view_chrome_path = None
        saved_path = ensure_profile_directory(profile_path)
        if AccountDB(None).mark_profile_logged_in(saved_path):
            self.on_row_signal(selected_profile["row"], "Đã đăng nhập")
            self.append_log(f"Đã lưu trạng thái đăng nhập cho profile: {profile_name}")
            self._start_manual_login_refresh(selected_profile, saved_path, profile_name)
            QMessageBox.information(
                self,
                "Thành công",
                "Đã lưu profile đăng nhập vào database. Tool sẽ tự cập nhật số page ở nền.",
            )
            return

        QMessageBox.warning(
            self,
            "Thông báo",
            "Không tìm thấy profile trong database để cập nhật.",
        )

    def build_data(self, max_active_accounts: int | None = None):
        tasks = []

        keywords_raw = self.uic.edit_banned_keywords.text().strip()
        keywords_list = [keyword.strip() for keyword in keywords_raw.split(",") if keyword.strip()] if keywords_raw else [""]

        groups_list = None
        if self.group_file_path:
            try:
                with open(self.group_file_path, "r", encoding="utf-8") as file:
                    groups_list = [line.strip() for line in file if line.strip()]
            except UnicodeDecodeError:
                with open(self.group_file_path, "r", encoding="utf-8-sig", errors="ignore") as file:
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
            QMessageBox.warning(self, "Error", "Khong doc duoc danh sach group hoac file group dang rong.")
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
            QMessageBox.warning(self, 'Error', 'Vui lòng tích chọn ít nhất 1 tài khoản để chạy tool.')
            return []

        if max_active_accounts is not None:
            active_limit = max(1, int(max_active_accounts))
            if len(selected_profiles) > active_limit:
                skipped_count = len(selected_profiles) - active_limit
                self.append_log(
                    f"Chi su dung {active_limit} nick dau tien theo so luong luong crawl; bo qua {skipped_count} nick dang chon."
                )
                selected_profiles = selected_profiles[:active_limit]

        group_chunks = split_groups_for_accounts(groups_list, len(selected_profiles))
        db = AccountDB(None)

        for profile_index, ((row, profile_name), assigned_groups) in enumerate(zip(selected_profiles, group_chunks), start=1):
            if not assigned_groups:
                self.append_log(f"Dong {row + 1}: khong co group duoc chia, bo qua nick nay.")
                continue

            self.append_log(
                f"Chia group: nick {profile_index}/{len(selected_profiles)} dong {row + 1} nhan {len(assigned_groups)} group."
            )

            account_name = db.find_account_name_from_path_chrome(profile_name)
            path_profile = db.find_full_path_from_path_chrome(profile_name)
            proxy = db.find_proxy_from_path_chrome(profile_name)
            info_account = db.find_info_account_from_path_chrome(profile_name)
            cookie = db.find_cookie_from_path_chrome(profile_name)
            token = db.find_token_from_path_chrome(profile_name)
            post_count = db.find_post_count_from_path_chrome(profile_name)

            email, password, twofa = "", "", ""
            if info_account:
                info_parts = info_account.split("|", 2)
                if len(info_parts) == 3:
                    email, password, twofa = info_parts
                elif len(info_parts) == 2:
                    email, password = info_parts
                elif len(info_parts) == 1:
                    email = info_parts[0]

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
                    account_name=account_name or "",
                    path_chrome=path_profile or "",
                    proxy=proxy or "",
                    email=email or "",
                    password=password or "",
                    twofa=twofa or "",
                    cookie=cookie or "",
                    token=token or "",
                    post_count=str(post_count or ""),
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
            QMessageBox.warning(self, 'Error', 'Vui lòng tích chọn ít nhất 1 tài khoản để chạy tool.')
            return []

        return tasks


def main():
    app = create_application()
    window = MainWindow()
    window.show()
    sys.exit(app.exec_())


if __name__ == "__main__":
    main()
