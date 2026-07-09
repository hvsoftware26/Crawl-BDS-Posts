import re
from datetime import datetime
from pathlib import Path

from openpyxl import Workbook
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side

from utils.time_utils import parse_created_time

BASE_DIR = Path(__file__).resolve().parents[2]
EXPORTS_DIR = BASE_DIR / "data" / "exports"
DEFAULT_FONT_NAME = "Calibri"
DEFAULT_FONT_SIZE = 11
EXCEL_CREATED_TIME_FORMAT = "%d/%m/%Y %H:%M:%S"


def safe_filename(text: str) -> str:
    """
    Remove all invalid characters for Windows filename
    """
    return re.sub(r'[\\/*?:"<>|]', "_", str(text))


def extract_group_name(group_input: str) -> str:
    """
    Extract meaningful group name or id from input
    """
    if not group_input:
        return "unknown"

    group_input = str(group_input)

    # lấy id hoặc slug sau /groups/
    match = re.search(r"/groups/([^/?]+)", group_input)
    if match:
        return match.group(1)

    return group_input


def sanitize_excel_message(message: str) -> str:
    normalized_message = str(message or "")
    normalized_message = normalized_message.replace("\\N", "\n").replace("\\n", "\n")
    normalized_message = normalized_message.replace("\r\n", "\n").replace("\r", "\n")
    normalized_message = re.sub(r"\n+", ". ", normalized_message)
    normalized_message = re.sub(r"\s{2,}", " ", normalized_message)
    return normalized_message.strip(" .")


def format_excel_created_time(created_time: str) -> str:
    parsed_time = parse_created_time(created_time)
    if parsed_time:
        return parsed_time.strftime(EXCEL_CREATED_TIME_FORMAT)

    return str(created_time or "")


def build_group_posts_excel(
    group_id: str,
    posts: list[dict],
    include_group_column: bool = False,
) -> Path:
    export_dir = EXPORTS_DIR / "telegram"
    export_dir.mkdir(parents=True, exist_ok=True)

    workbook = Workbook()
    worksheet = workbook.active
    worksheet.title = "Posts"
    worksheet.freeze_panes = "A2"

    headers = ["Link bài", "Time created", "Message"]
    if include_group_column:
        headers = ["Nhóm"] + headers
    header_fill = PatternFill(fill_type="solid", fgColor="D9EAF7")
    thin_side = Side(style="thin", color="C9D2DB")
    border = Border(left=thin_side, right=thin_side, top=thin_side, bottom=thin_side)
    body_font = Font(name=DEFAULT_FONT_NAME, size=DEFAULT_FONT_SIZE)
    header_font = Font(name=DEFAULT_FONT_NAME, size=DEFAULT_FONT_SIZE, bold=True)
    wrap_alignment = Alignment(vertical="top", horizontal="left", wrap_text=True)

    worksheet.append(headers)
    for cell in worksheet[1]:
        cell.font = header_font
        cell.fill = header_fill
        cell.alignment = wrap_alignment
        cell.border = border

    for post in posts:
        row = [
            f"https://www.facebook.com/{post.get('id')}",
            format_excel_created_time(post.get("created_time")),
            sanitize_excel_message(post.get("message")),
        ]
        if include_group_column:
            row = [str(post.get("group_id") or "")] + row
        worksheet.append(row)

    for row in worksheet.iter_rows(min_row=2, max_row=worksheet.max_row):
        for cell in row:
            cell.font = body_font
            cell.alignment = wrap_alignment
            cell.border = border

    if include_group_column:
        worksheet.column_dimensions["A"].width = 45
        worksheet.column_dimensions["B"].width = 40
        worksheet.column_dimensions["C"].width = 22
        worksheet.column_dimensions["D"].width = 120
    else:
        worksheet.column_dimensions["A"].width = 40
        worksheet.column_dimensions["B"].width = 22
        worksheet.column_dimensions["C"].width = 120

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")

    # Main row parser.
    group_name = extract_group_name(group_id)
    group_name = safe_filename(group_name)

    file_path = export_dir / f"group_{group_name}_{timestamp}.xlsx"

    workbook.save(file_path)
    return file_path
