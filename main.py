# Main GUI
import sys, os, requests, json
from typing import List
from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import (
    QApplication, QMainWindow, QTableWidgetItem, QMessageBox, QFileDialog,
    QMenu, QHBoxLayout, QWidget, QCheckBox, QDialog,
)

from services.sql_query_service import AccountDB
from resources.ui.gui import MultiProfileDialog, Ui_MainWindow, create_application
from services.ai_service import OpenAIService
from models.account import Info_data
from workers.process_worker import Worker_Handle


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
        self.tele_file_path = None
        self.id_chat = None
        self.token_tele = None
        self.cycle_total = self.uic.spn_cycle_hours.value()
        self.delay_get_post_gr = None
        self.keywords_list = None
        self.workers = []
        self.is_running = False

        self._connect_signals()
        self.load_table()
        AccountDB(None)._create_table()
        self.update_delay_between_cycles()

    def _connect_signals(self):
        self.uic.profile_btn.clicked.connect(self.open_profile_dialog)
        self.uic.table.setContextMenuPolicy(Qt.CustomContextMenu)
        self.uic.table.customContextMenuRequested.connect(self.show_menu)
        self.uic.btn_import_group.clicked.connect(self.import_group_file)
        self.uic.btn_import_prompt.clicked.connect(self.import_prompt_file)
        self.uic.btn_select_tele.clicked.connect(self.import_tele_file)
        self.uic.btn_check_api.clicked.connect(self.check_api_key)
        self.uic.btn_clear_log.clicked.connect(self.clear_log)
        self.uic.btn_select_all.clicked.connect(self.toggle_all_rows)
        self.uic.btn_delete_row.clicked.connect(self.delete_selected_rows)
        self.uic.btn_start.clicked.connect(self.start_tool)
        self.uic.btn_stop.clicked.connect(self.stop_tool)
        self.uic.spn_cycle_hours.valueChanged.connect(self.update_delay_between_cycles)

    def append_log(self, text: str):
        self.uic.console.append(text)

    def clear_log(self):
        self.uic.console.clear()
        self.append_log("Đã xóa log hiển thị.")

    def update_interact_group(self, row: int, text: str):
        item = QTableWidgetItem(text)
        item.setTextAlignment(Qt.AlignCenter)
        self.uic.table.setItem(row, 4, item)

    def on_row_signal(self, row: int, text: str):
        item = QTableWidgetItem(text)
        item.setTextAlignment(Qt.AlignCenter)
        self.uic.table.setItem(row, 5, item)

    def on_task_finished(self, row: int, text: str):
        item = QTableWidgetItem(text)
        item.setTextAlignment(Qt.AlignCenter)
        self.uic.table.setItem(row, 5, item)

    def _cleanup_finished_workers(self):
        self.workers = [w for w in self.workers if w.isRunning()]
        if not self.workers:
            self.is_running = False
            self.append_log("Tất cả worker đã kết thúc.")

    
    def on_post_signal(self, row: int, status: int):
        item = QTableWidgetItem(str(status))
        item.setTextAlignment(Qt.AlignCenter)
        self.uic.table.setItem(row, 6, item)

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

        tasks = self.build_data()
        if not tasks:
            return

        self.workers.clear()
        self.is_running = True
        self.append_log("Bắt đầu chạy tool...")

        for task in tasks:
            row = task.row
            worker = Worker_Handle(row, task)
            worker.row_signal.connect(self.on_row_signal)
            worker.interaction_signal.connect(self.update_interact_group)
            worker.post_signal.connect(self.on_post_signal)
            worker.finished_signal.connect(self.on_task_finished)
            worker.finished.connect(lambda: self._cleanup_finished_workers())
            worker.start()
            self.workers.append(worker)

    def stop_tool(self):
        if not self.workers:
            self.append_log("Không có worker nào đang chạy.")
            self.is_running = False
            return

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
                    "",
                    data.get('Status', ''),
                    data.get('Post_Count', ''),
                )

            self.uic.table.setUpdatesEnabled(True)
        except Exception:
            pass

    def open_profile_dialog(self):
        dialog = MultiProfileDialog(self)
        if dialog.exec_() != QDialog.Accepted:
            return

        for line in dialog.editor.toPlainText().splitlines():
            radio_check = dialog.radio_normal.isChecked()

            try:
                count_element = line.split('|')
                if radio_check:
                    if len(count_element) != 5:
                        QMessageBox.warning(self, 'Cảnh báo', 'Đã nhập sai định dạng!')
                        return
                    account_name, path_chrome, email, password, twofa = count_element
                    proxy = "Không"
                else:
                    if len(count_element) != 6:
                        QMessageBox.warning(self, 'Cảnh báo', 'Đã nhập sai định dạng!')
                        return
                    account_name, path_chrome, proxy, email, password, twofa = count_element
            except Exception:
                QMessageBox.warning(self, 'Cảnh báo', 'Đã nhập sai định dạng!')
                return

            AccountDB(None).create_account(
                account_name=account_name,
                path_chrome=path_chrome,
                proxy=proxy,
                email=email,
                password=password,
                twofa=twofa,
                cookie="",
                token="",
                status='Chưa rõ',
                post_count=0
            )
            self.load_table()

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
            item = self.uic.table.item(row, 0)
            if item:
                item.setCheckState(state)

    def are_all_checked(self) -> bool:
        total = self.uic.table.rowCount()
        if total == 0:
            return False

        for row in range(total):
            item = self.uic.table.item(row, 0)
            if not item or item.checkState() != Qt.Checked:
                return False

        return True

    def delete_selected_rows(self):
        path_chrome_list = []
        for row in range(self.uic.table.rowCount()):
            item = self.uic.table.item(row, 0)
            if item and item.checkState() == Qt.Checked:
                path_chrome = self.uic.table.item(row, 2).text()
                get_id = AccountDB(None).find_id_from_path_chrome(path_chrome)
                path_chrome_list.append(get_id)

        if not path_chrome_list:
            QMessageBox.warning(self, "Thông báo", "Chưa có profiles nào được chọn!")
            return

        delete_accept = QMessageBox.question(
            self,
            'Xác nhận',
            f'Xác nhận xóa {len(path_chrome_list)} profiles ?',
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No
        )

        if delete_accept == QMessageBox.Yes:
            for row in reversed(path_chrome_list):
                AccountDB(None).delete_account(row)
            self.append_log(f"Đã xóa {len(path_chrome_list)} profiles.")

        self.load_table()

    def _set_item(self, row, col, value, align):
        item = QTableWidgetItem(str(value))
        item.setTextAlignment(int(align))
        self.uic.table.setItem(row, col, item)

    def insert_row(self, account_name, path_chrome, proxy, interact, status, post_count):
        self.uic.table.setColumnCount(7)
        row = self.uic.table.rowCount()
        self.uic.table.insertRow(row)

        checkbox_item = QTableWidgetItem()
        checkbox_item.setFlags(Qt.ItemIsUserCheckable | Qt.ItemIsEnabled | Qt.ItemIsSelectable)
        checkbox_item.setCheckState(Qt.Unchecked)
        checkbox_item.setTextAlignment(int(Qt.AlignHCenter | Qt.AlignVCenter))
        self.uic.table.setItem(row, 0, checkbox_item)

        self._set_item(row, 1, account_name, Qt.AlignHCenter | Qt.AlignVCenter)
        self._set_item(row, 2, path_chrome, Qt.AlignHCenter | Qt.AlignVCenter)
        self._set_item(row, 3, proxy, Qt.AlignHCenter | Qt.AlignVCenter)
        self._set_item(row, 4, interact, Qt.AlignHCenter | Qt.AlignVCenter)
        self._set_item(row, 5, status, Qt.AlignHCenter | Qt.AlignVCenter)
        self._set_item(row, 6, post_count, Qt.AlignHCenter | Qt.AlignVCenter)

    def show_menu(self, pos):
        item = self.uic.table.itemAt(pos)
        if item is None:
            return

        menu = QMenu(self)
        copy_path_ = menu.addAction("📋 Copy path chrome")
        copy_proxy = menu.addAction("🌐 Copy proxy")
        copy_info_account = menu.addAction("📧 Copy mail|pass|2FA")
        copy_token = menu.addAction("🔑 Copy token")
        copy_cookie = menu.addAction("🍪 Copy cookie")
        check_live_die = menu.addAction("✅ Check Live / Die")

        selected_action = menu.exec(self.uic.table.viewport().mapToGlobal(pos))
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
        elif selected_action == check_live_die:
            self.check_live_die()

    def copy_path(self):
        checked_paths = []
        for row in range(self.uic.table.rowCount()):
            item = self.uic.table.item(row, 0)
            if item and item.checkState() == Qt.Checked:
                profile_name = self.uic.table.item(row, 2).text()
                checked_paths.append(AccountDB(None).find_full_path_from_path_chrome(profile_name))
        if not checked_paths:
            QMessageBox.warning(self, 'Error', 'Vui lòng tích chọn ít nhất 1 tài khoản để copy path chrome.')
            return
        QApplication.clipboard().setText('\n'.join(checked_paths))
        QMessageBox.information(self, 'Copied', f'Đã copy {len(checked_paths)} path chrome.')

    def copy_proxy(self):
        checked_paths = []
        for row in range(self.uic.table.rowCount()):
            item = self.uic.table.item(row, 0)
            if item and item.checkState() == Qt.Checked:
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
            item = self.uic.table.item(row, 0)
            if item and item.checkState() == Qt.Checked:
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
            item = self.uic.table.item(row, 0)
            if item and item.checkState() == Qt.Checked:
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
            item = self.uic.table.item(row, 0)
            if item and item.checkState() == Qt.Checked:
                profile_name = self.uic.table.item(row, 2).text()
                checked_paths.append(AccountDB(None).find_cookie_from_path_chrome(profile_name))
        if not checked_paths:
            QMessageBox.warning(self, 'Error', 'Vui lòng tích chọn ít nhất 1 tài khoản để copy cookie.')
            return
        QApplication.clipboard().setText('\n'.join(checked_paths))
        QMessageBox.information(self, 'Copied', f'Đã copy {len(checked_paths)} cookie.')

    def api_fb_check(self, cookie, token):
        if cookie == '' or token == '':
            return "Unk"
        try:
            headers = {'cookie': cookie}
            params = {'fields': 'id,name', 'access_token': token}
            requests.get('https://graph.facebook.com/v21.0/me', params=params, headers=headers).json()['name']
            return True
        except Exception:
            return False

    def check_live_die(self):
        checked_paths = []
        for row in range(self.uic.table.rowCount()):
            item = self.uic.table.item(row, 0)
            if item and item.checkState() == Qt.Checked:
                profile_name = self.uic.table.item(row, 2).text()
                check_live = self.api_fb_check(
                    AccountDB(None).find_cookie_from_path_chrome(profile_name),
                    AccountDB(None).find_token_from_path_chrome(profile_name)
                )
                checked_paths.append(check_live)

                if check_live is True:
                    item_status = QTableWidgetItem("Live")
                elif check_live == "Unk":
                    item_status = QTableWidgetItem("Thiếu cookie hoặc token")
                else:
                    item_status = QTableWidgetItem("Die")

                item_status.setTextAlignment(Qt.AlignCenter)
                self.uic.table.setItem(row, 5, item_status)

        if not checked_paths:
            QMessageBox.warning(self, 'Error', 'Vui lòng tích chọn ít nhất 1 tài khoản để check live die.')
            return

        QMessageBox.information(self, 'Thông báo', f'Đã check live die {len(checked_paths)} tài khoản.')

    def build_data(self):
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

        prompt = ""
        if self.prompt_file_path:
            try:
                with open(self.prompt_file_path, "r", encoding="utf-8") as file:
                    prompt = file.read().strip()
            except UnicodeDecodeError:
                with open(self.prompt_file_path, "r", encoding="utf-8-sig", errors="ignore") as file:
                    prompt = file.read().strip()
            except Exception:
                prompt = ""

        db = AccountDB(None)

        for row in range(self.uic.table.rowCount()):
            item = self.uic.table.item(row, 0)
            if not item or item.checkState() != Qt.Checked:
                continue

            profile_item = self.uic.table.item(row, 2)
            if profile_item is None:
                continue

            profile_name = profile_item.text()

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

            tasks.append(
                Info_data(
                    row=row,
                    account_name=account_name or "",
                    path_chrome=path_profile or "",
                    proxy=proxy or "",
                    emjuail=email or "",
                    password=password or "",
                    twofa=twofa or "",
                    cookie=cookie or "",
                    token=token or "",
                    post_count=str(post_count or ""),
                    api_key=self.api_key or "",
                    groups_list=groups_list,
                    prompt=prompt,
                    id_chat=self.id_chat or "",
                    token_tele=self.token_tele or "",
                    cycle_total=float(self.cycle_total) if self.cycle_total is not None else 0.0,
                    delay_get_post_gr=float(str(self.delay_get_post_gr).replace(",", ".")) if self.delay_get_post_gr not in (None, "") else 0.0,
                    keywords_list=keywords_list,
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
    key = requests.get("https://raw.githubusercontent.com/hvsoftware26/Crawl-BDS-Posts/refs/heads/main/key.txt?token=GHSAT0AAAAAADZR5VEM3L2A5F7M3SPGZDO22O3HA2A").text.strip()
    if key != "HVSOFTWARƯ":
        open("KEY KÍCH HOẠT.txt", "w", encoding="utf-8").write('VUI LÒNG NHẬP KEY KÍCH HOẠT')
    main()