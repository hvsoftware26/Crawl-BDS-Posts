import sys

from PyQt5.QtCore import Qt
from PyQt5.QtGui import QFont
from PyQt5.QtWidgets import (
    QApplication,
    QAbstractItemView,
    QButtonGroup,
    QCheckBox,
    QDialog,
    QDoubleSpinBox,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMainWindow,
    QPushButton,
    QPlainTextEdit,
    QRadioButton,
    QSizePolicy,
    QSpinBox,
    QTableWidget,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)


APP_STYLE = """
QMainWindow, QWidget {
    background: #F4F7FB;
    color: #16243b;
    font-family: 'Segoe UI';
    font-size: 13px;
}
QGroupBox {
    border: 1px solid #d7e1ef;
    border-radius: 18px;
    margin-top: 12px;
    background: #f4f7fb;
    font-weight: 600;
}
QGroupBox::title {
    subcontrol-origin: margin;
    left: 16px;
    padding: 0 8px;
    color: #172b4d;
}
QLabel#pageTitle {
    color: #2160ff;
    font-size: 22px;
    font-weight: 800;
    padding: 4px 0 8px 0;
}
QLabel#sectionLabel {
    background: #e8eef6;
    border: 1px solid #d5deea;
    border-radius: 12px;
    padding: 10px 14px;
    min-height: 20px;
    font-weight: 700;
    color: #23395d;
}
QLabel#statsLabel {
    background: #e8eef6;
    border: 1px solid #d5deea;
    border-radius: 12px;
    padding: 0 14px;
    min-height: 34px;
    max-height: 34px;
    font-weight: 700;
    color: #1f3152;
}
QLineEdit, QSpinBox, QDoubleSpinBox, QTextEdit, QPlainTextEdit {
    background: #ffffff;
    border: 1px solid #ccd8e7;
    border-radius: 12px;
    padding: 8px 12px;
    selection-background-color: #cfe0ff;
}
QLineEdit:focus, QSpinBox:focus, QDoubleSpinBox:focus, QTextEdit:focus, QPlainTextEdit:focus {
    border: 1px solid #3d73ff;
}
QDoubleSpinBox {
    background: #ffffff;
    border: 1px solid #ccd8e7;
    border-radius: 12px;
    padding: 8px 12px;
}
QPushButton {
    background: #edf3ff;
    border: 1px solid #cddaf4;
    border-radius: 12px;
    padding: 10px 16px;
    font-weight: 700;
    color: #2160ff;
}
QPushButton:hover {
    background: #e2edff;
}
QPushButton:pressed {
    background: #d7e6ff;
}
QPushButton#primaryBtn {
    background: #3367e7;
    color: white;
    border: none;
}
QPushButton#primaryBtn:hover {
    background: #2e5fd5;
}
QPushButton#dangerBtn {
    background: #ef4444;
    color: white;
    border: none;
}
QPushButton#dangerBtn:hover {
    background: #dc3e3e;
}
QPushButton#softBtn {
    min-width: 120px;
}
QTableWidget {
    background: white;
    border: 1px solid #d7e1ef;
    border-radius: 14px;
    gridline-color: #edf2f9;
    alternate-background-color: #f9fbff;
}

QTableWidget::item {
    text-align: center;
}

QTableWidget::item:selected {
    background-color: #F4F7FB;
    color: black;
}

QTableWidgetItem::item {
    text-align: center;
}

QHeaderView::section {
    background: #f1f5fb;
    color: #1a3154;
    border: none;
    border-bottom: 1px solid #dbe4f0;
    padding: 10px;
    font-weight: 700;
}
QTableCornerButton::section {
    background: #f1f5fb;
    border: none;
    border-bottom: 1px solid #dbe4f0;
}
QTextEdit#consoleBox {
    background: #031a57;
    color: #d9e6ff;
    border: 1px solid #0a256f;
    border-radius: 16px;
    padding: 14px;
    font-family: Consolas;
}
QDialog {
    background: #F4F7FB;
}
QRadioButton {
    spacing: 10px;
    font-weight: 700;
}
QRadioButton::indicator, QCheckBox::indicator {
    width: 18px;
    height: 18px;
}
QScrollBar:vertical {
    background: transparent;
    width: 10px;
    margin: 6px 2px 6px 2px;
}
QScrollBar::handle:vertical {
    background: #c5d3e6;
    border-radius: 5px;
    min-height: 30px;
}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {
    height: 0;
}
QMenu {
    background: #f8fbff;
    border: 1px solid #d7e1ef;
    padding: 2px;
}

QMenu::item {
    padding: 9px 18px;
    border-radius: 8px;
    margin: 2px 4px;
    color: #16243b;
}

QMenu::item:selected {
    background: #2160ff;
    color: white;
}
"""


class LabelBox(QLabel):
    def __init__(self, text: str, object_name: str = "sectionLabel"):
        super().__init__(text)
        self.setObjectName(object_name)
        self.setAlignment(Qt.AlignVCenter | Qt.AlignLeft)
        self.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Fixed)


class PlaceholderPathEdit(QLineEdit):
    def __init__(self, placeholder: str):
        super().__init__()
        self.setPlaceholderText(placeholder)
        self.setMinimumHeight(42)


class NumberBox(QSpinBox):
    def __init__(self, minimum=0, maximum=999999, value=0, suffix=""):
        super().__init__()
        self.setRange(minimum, maximum)
        self.setValue(value)
        self.setSuffix(suffix)
        self.setButtonSymbols(QSpinBox.NoButtons)
        self.setMinimumHeight(42)


class DecimalBox(QDoubleSpinBox):
    def __init__(self, minimum=0.0, maximum=999999.0, value=0.0, suffix="", decimals=1):
        super().__init__()
        self.setRange(minimum, maximum)
        self.setDecimals(decimals)
        self.setValue(value)
        self.setSuffix(suffix)
        self.setButtonSymbols(QDoubleSpinBox.NoButtons)
        self.setMinimumHeight(42)


class MultiProfileDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Thêm tài khoản")
        self.resize(760, 470)
        self.setModal(True)
        self.build_ui()

    def build_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(18, 18, 18, 18)
        root.setSpacing(14)

        title = QLabel("Thêm tài khoản")
        title.setObjectName("pageTitle")
        root.addWidget(title)

        top_box = QGroupBox()
        top_layout = QVBoxLayout(top_box)
        top_layout.setContentsMargins(14, 14, 14, 14)
        top_layout.setSpacing(12)

        mode_row = QHBoxLayout()
        mode_row.setSpacing(12)
        mode_row.addWidget(LabelBox("Định dạng dữ liệu"))

        self.radio_proxy = QRadioButton("Profile Chrome - Proxy")
        self.radio_normal = QRadioButton("Profile Chrome")
        self.radio_proxy.setChecked(True)

        group = QButtonGroup(self)
        group.addButton(self.radio_proxy)
        group.addButton(self.radio_normal)

        mode_row.addWidget(self.radio_proxy)
        mode_row.addWidget(self.radio_normal)
        mode_row.addStretch()
        top_layout.addLayout(mode_row)

        self.help_box = QLabel()
        self.help_box.setWordWrap(True)
        self.help_box.setObjectName("sectionLabel")
        top_layout.addWidget(self.help_box)

        self.editor = QPlainTextEdit()
        self.editor.setPlaceholderText(
            "Dán danh sách tài khoản tại đây...\n"
            "Dùng proxy chọn chế độ Profile Chrome-Proxy:\n"
            "Tên tài khoản|proxy|email|password|2FA\n"
            "Không dùng proxy chọn chế độ Profile Chrome:\n"
            "Tên tài khoản|email|password|2FA"
        )
        self.editor.setMinimumHeight(180)
        top_layout.addWidget(self.editor)
        root.addWidget(top_box)

        button_row = QHBoxLayout()
        button_row.addStretch()
        self.cancel_btn = QPushButton("Hủy bỏ")
        self.cancel_btn.setObjectName("dangerBtn")
        self.ok_btn = QPushButton("Xác nhận")
        self.ok_btn.setObjectName("primaryBtn")
        self.cancel_btn.clicked.connect(self.reject)
        self.ok_btn.clicked.connect(self.accept)
        button_row.addWidget(self.cancel_btn)
        button_row.addWidget(self.ok_btn)
        root.addLayout(button_row)

        self.radio_proxy.toggled.connect(self.update_help_text)
        self.update_help_text()

    def update_help_text(self):
        if self.radio_proxy.isChecked():
            text = (
                "Dán nhiều dòng tài khoản vào đây. Mỗi dòng là 1 tài khoản.\n"
                "Ví dụ:\n"
                "Tên tài khoản|127.0.0.1:8000:user:pass|example@gmail.com|Nohope1111@@|2FA"
            )
        else:
            text = (
                "Dán nhiều dòng tài khoản vào đây. Mỗi dòng là 1 tài khoản.\n"
                "Ví dụ:\n"
                "Tên tài khoản|example@gmail.com|Nohope1111@@|2FA"
            )
        self.help_box.setText(text)


class Ui_MainWindow(object):
    def setupUi(self, MainWindow):
        MainWindow.setWindowTitle("Facebook BĐS - Crawl Bài Viết")
        MainWindow.resize(1540, 930)
        MainWindow.setMinimumSize(1180, 720)

        self.central = QWidget()
        MainWindow.setCentralWidget(self.central)
        self.outer = QVBoxLayout(self.central)
        self.outer.setContentsMargins(16, 14, 16, 14)
        self.outer.setSpacing(12)

        self.title = QLabel("Facebook BĐS - Crawl dữ liệu bài viết")
        self.title.setObjectName("pageTitle")
        self.outer.addWidget(self.title)

        self.top_group = QGroupBox()
        self.top_layout = QVBoxLayout(self.top_group)
        self.top_layout.setContentsMargins(14, 14, 14, 14)
        self.top_layout.setSpacing(12)

        self.grid = QGridLayout()
        self.grid.setHorizontalSpacing(10)
        self.grid.setVerticalSpacing(10)

        self.api_label = LabelBox("API key ChatGPT")
        self.api_edit = PlaceholderPathEdit("Nhập API key ChatGPT...")
        self.btn_check_api = QPushButton("Check key")

        self.group_label = LabelBox("Danh sách group")
        self.group_path = PlaceholderPathEdit("Chưa chọn file danh sách group...")
        self.group_path.setReadOnly(True)
        self.btn_import_group = QPushButton("Import file")

        self.prompt_label = LabelBox("AI lọc bài viết")
        self.prompt_path = PlaceholderPathEdit("Chưa import file prompt...")
        self.prompt_path.setReadOnly(True)
        self.btn_import_prompt = QPushButton("Thêm prompt")

        self.prompt_cmt_label = LabelBox("Bình luận")
        self.prompt_cmt_path = PlaceholderPathEdit("Chưa import file prompt cmt...")
        self.prompt_cmt_path.setReadOnly(True)
        self.btn_import_prompt_cmt = QPushButton("Thêm file /prompt")
        self.radio_prompt_cmt_text = QRadioButton("Cmt sẵn")
        self.radio_prompt_cmt_ai = QRadioButton("Dùng AI")
        self.radio_prompt_cmt_text.setChecked(True)
        self.prompt_cmt_mode_group = QButtonGroup(MainWindow)
        self.prompt_cmt_mode_group.addButton(self.radio_prompt_cmt_text)
        self.prompt_cmt_mode_group.addButton(self.radio_prompt_cmt_ai)

        self.prompt_cmt_row = QHBoxLayout()
        self.prompt_cmt_row.setContentsMargins(0, 0, 0, 0)
        self.prompt_cmt_row.setSpacing(8)
        self.prompt_cmt_mode_layout = QVBoxLayout()
        self.prompt_cmt_mode_layout.setContentsMargins(0, 0, 0, 0)
        self.prompt_cmt_mode_layout.setSpacing(0)
        self.prompt_cmt_mode_layout.addWidget(self.radio_prompt_cmt_text)
        self.prompt_cmt_mode_layout.addWidget(self.radio_prompt_cmt_ai)
        self.prompt_cmt_row.addWidget(self.prompt_cmt_label)
        self.prompt_cmt_row.addLayout(self.prompt_cmt_mode_layout)
        self.prompt_cmt_row.addWidget(self.prompt_cmt_path, 1)
        self.prompt_cmt_row.addWidget(self.btn_import_prompt_cmt)

        self.profile_btn = QPushButton("Thêm tài khoản")
        self.profile_info = PlaceholderPathEdit("Chưa thêm tài khoản...")
        self.profile_info.setReadOnly(True)

        self.tele_label = LabelBox("Cấu hình bot tele")
        self.tele_path = PlaceholderPathEdit("Chưa chọn file json cấu hình tele...")
        self.tele_path.setReadOnly(True)
        self.btn_select_tele = QPushButton("Chọn file")

        widgets = [
            (self.api_label, 0, 0, 1, 1),
            (self.api_edit, 0, 1, 1, 3),
            (self.btn_check_api, 0, 4, 1, 1),
            (self.prompt_label, 0, 5, 1, 1),
            (self.prompt_path, 0, 6, 1, 2),
            (self.btn_import_prompt, 0, 8, 1, 1),
            (self.group_label, 0, 9, 1, 1),
            (self.group_path, 0, 10, 1, 2),
            (self.btn_import_group, 0, 12, 1, 1),
            (self.profile_btn, 1, 0, 1, 1),
            (self.profile_info, 1, 1, 1, 3),
            (self.tele_label, 1, 4, 1, 1),
            (self.tele_path, 1, 5, 1, 3),
            (self.btn_select_tele, 1, 8, 1, 1),
        ]
        for widget, r, c, rs, cs in widgets:
            self.grid.addWidget(widget, r, c, rs, cs)
        self.grid.addLayout(self.prompt_cmt_row, 1, 9, 1, 4)

        for col, stretch in {
            0: 2, 1: 3, 2: 2, 3: 2, 4: 2, 5: 2, 6: 2,
            7: 3, 8: 2, 9: 2, 10: 3, 11: 2, 12: 2
        }.items():
            self.grid.setColumnStretch(col, stretch)

        self.top_layout.addLayout(self.grid)

        self.controls = QGridLayout()
        self.controls.setHorizontalSpacing(10)
        self.controls.setVerticalSpacing(10)

        self.lbl_threads = LabelBox("Số luồng")
        self.spn_threads = NumberBox(1, 50, 1)

        self.lbl_cycle_hours = LabelBox("Chu kỳ")
        self.spn_cycle_hours = DecimalBox(0.1, 999999.0, 4.0, " tiếng", 1)

        self.lb_delay_between_cycles = LabelBox("Delay giữa các chu kỳ: 0 phút", "statsLabel")
        self.lb_delay_between_cycles.setAlignment(Qt.AlignVCenter | Qt.AlignLeft)

        self.lbl_banned_keywords = LabelBox("Keywords Cấm")
        self.edit_banned_keywords = PlaceholderPathEdit("Nhập keyword cấm...")

        control_items = [
            self.lbl_threads, self.spn_threads,
            self.lbl_cycle_hours, self.spn_cycle_hours,
            self.lbl_banned_keywords, self.edit_banned_keywords,
        ]
        for i, widget in enumerate(control_items):
            self.controls.addWidget(widget, 0, i)
            self.controls.setColumnStretch(i, 1)

        self.top_layout.addLayout(self.controls)

        self.stats_row = QHBoxLayout()
        self.stats_row.setSpacing(10)
        self.stats_row.setContentsMargins(0, 0, 0, 0)

        self.lb_success = LabelBox("Acc chạy thành công: 0", "statsLabel")
        self.lb_error = LabelBox("Số bài viết lỗi: 0", "statsLabel")
        self.lb_done = LabelBox("Số bài viết thành công: 0", "statsLabel")
        self.lb_delay_between_cycles.setObjectName("statsLabel")
        self.lb_delay_between_cycles.setAlignment(Qt.AlignVCenter | Qt.AlignLeft)

        stats_height = 34
        for widget in (
            self.lb_success,
            self.lb_error,
            self.lb_done,
            self.lb_delay_between_cycles,
        ):
            widget.setFixedHeight(stats_height)

        self.btn_start = QPushButton("Start")
        self.btn_start.setObjectName("primaryBtn")
        self.btn_stop = QPushButton("Stop")
        self.btn_stop.setObjectName("dangerBtn")
        self.btn_start.setMinimumHeight(40)
        self.btn_stop.setMinimumHeight(40)

        self.stats_row.addWidget(self.lb_success, 2)
        self.stats_row.addWidget(self.lb_error, 2)
        self.stats_row.addWidget(self.lb_done, 2)
        self.stats_row.addWidget(self.lb_delay_between_cycles, 2)
        self.stats_row.addWidget(self.btn_start, 1)
        self.stats_row.addWidget(self.btn_stop, 1)
        self.top_layout.addLayout(self.stats_row)

        self.outer.addWidget(self.top_group)

        self.body_layout = QHBoxLayout()
        self.body_layout.setSpacing(12)

        self.left_box = QGroupBox("Danh sách tài khoản / tiến trình")
        self.left_layout = QVBoxLayout(self.left_box)
        self.left_layout.setContentsMargins(12, 12, 12, 12)
        self.left_layout.setSpacing(10)

        self.table = QTableWidget(0, 8)
        self.table.setHorizontalHeaderLabels([
            "✅", "Tên tài khoản", "Path chrome", "Proxy",
            "Tổng số page", "Tương tác group", "Status", "Số bài viết đã cmt"
        ])
        self.table.setAlternatingRowColors(True)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.verticalHeader().setVisible(False)
        self.table.setShowGrid(False)
        self.table.setWordWrap(False)
        self.table.setMinimumHeight(420)

        header = self.table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(1, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(2, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(3, QHeaderView.Stretch)
        header.setSectionResizeMode(4, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(5, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(6, QHeaderView.Stretch)
        header.setSectionResizeMode(7, QHeaderView.ResizeToContents)
        self.left_layout.addWidget(self.table)

        self.bottom_buttons = QHBoxLayout()
        self.btn_delete_row = QPushButton("Xóa dòng")
        self.btn_select_all = QPushButton("Chọn tất cả")
        self.btn_clear_log = QPushButton("Xóa log")
        self.bottom_buttons.addWidget(self.btn_delete_row)
        self.bottom_buttons.addWidget(self.btn_select_all)
        self.bottom_buttons.addStretch()
        self.bottom_buttons.addWidget(self.btn_clear_log)
        self.left_layout.addLayout(self.bottom_buttons)

        self.right_box = QGroupBox("Console / Log chạy tool")
        self.right_layout = QVBoxLayout(self.right_box)
        self.right_layout.setContentsMargins(12, 12, 12, 12)
        self.console = QTextEdit()
        self.console.setObjectName("consoleBox")
        self.console.setReadOnly(True)
        self.console.setPlaceholderText("Log hoạt động sẽ hiển thị tại đây...")
        self.right_layout.addWidget(self.console)

        self.body_layout.addWidget(self.left_box, 3)
        self.body_layout.addWidget(self.right_box, 1)
        self.outer.addLayout(self.body_layout, 1)

        self.table.setColumnWidth(0, 42)
        self.table.setColumnWidth(7, 140)


def create_application():
    app = QApplication(sys.argv)
    app.setStyleSheet(APP_STYLE)
    app.setFont(QFont("Segoe UI", 10))
    return app
