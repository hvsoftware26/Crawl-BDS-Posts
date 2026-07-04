import sqlite3
from typing import Optional, List, Dict, Any
from pathlib import Path
from app_config import APP_BASE_DIR, PROFILE_ROOT_DIR

STATUS_TEXT_MAP = {
    "Chua ro": "Chưa rõ",
    "Dang cho luong": "Đang chờ luồng",
    "Dang khoi dong": "Đang khởi động",
    "Dang kiem tra dang nhap": "Đang kiểm tra đăng nhập",
    "Da dung": "Đã dừng",
    "Da dang nhap": "Đã đăng nhập",
    "Da dang xuat": "Đã đăng xuất",
    "Khong vao duoc Facebook": "Không vào được Facebook",
    "Khong lay duoc cookie/token": "Không lấy được cookie/token",
    "Xu ly bai viet that bai": "Xử lý bài viết thất bại",
}

PROXY_TEXT_MAP = {
    "Khong": "Không",
}


def format_status_text(status: str) -> str:
    status_value = str(status or "").strip()
    status_key = status_value.casefold()
    for source_text, formatted_text in STATUS_TEXT_MAP.items():
        if source_text.casefold() == status_key:
            return formatted_text
    return status_value


def format_proxy_text(proxy: str) -> str:
    proxy_value = str(proxy or "").strip()
    proxy_key = proxy_value.casefold()
    for source_text, formatted_text in PROXY_TEXT_MAP.items():
        if source_text.casefold() == proxy_key:
            return formatted_text
    return proxy_value


class AccountDB:
    def __init__(self, db_name: None):
        if db_name is None:
            base_dir = APP_BASE_DIR
            db_path = base_dir / "database" / "accounts.db"
        else:
            db_path = Path(db_name)
            base_dir = db_path.resolve().parent.parent

        # ✅ Tạo folder nếu chưa tồn tại
        db_path.parent.mkdir(parents=True, exist_ok=True)

        self.base_dir = base_dir.resolve()
        self.profile_root = PROFILE_ROOT_DIR if db_name is None else (self.base_dir / "Profile-Chrome").resolve()
        self.db_name = str(db_path)

    def _connect(self):
        return sqlite3.connect(self.db_name)

    def _normalize_profile_path_value(self, path_chrome: str) -> str:
        normalized_input = str(path_chrome or "").strip().strip('"')
        if not normalized_input:
            return ""

        candidate = Path(normalized_input)
        profile_name = candidate.name.strip()
        if not profile_name:
            return normalized_input

        if candidate.exists():
            return str(candidate.resolve())

        resolved_local = (self.profile_root / profile_name).resolve()
        return str(resolved_local)

    def _rewrite_profile_path(self, old_path: str, new_path: str):
        if not old_path or not new_path or old_path == new_path:
            return

        query = "UPDATE accounts SET Path_Chrome = ? WHERE Path_Chrome = ?"
        with self._connect() as conn:
            conn.execute(query, (new_path, old_path))
            conn.commit()

    def _rewrite_text_field(self, account_id: int, column_name: str, new_value: str):
        if column_name not in {"Proxy", "Status"}:
            return

        query = f"UPDATE accounts SET {column_name} = ? WHERE id = ?"
        with self._connect() as conn:
            conn.execute(query, (new_value, account_id))
            conn.commit()

    def _normalize_account_row(self, row: sqlite3.Row | None) -> Optional[Dict[str, Any]]:
        if row is None:
            return None

        row_dict = dict(row)
        original_path = row_dict.get("Path_Chrome") or ""
        normalized_path = self._normalize_profile_path_value(original_path)

        if normalized_path and normalized_path != original_path:
            self._rewrite_profile_path(original_path, normalized_path)
            row_dict["Path_Chrome"] = normalized_path

        original_proxy = row_dict.get("Proxy") or ""
        normalized_proxy = format_proxy_text(original_proxy)
        if normalized_proxy != original_proxy:
            self._rewrite_text_field(row_dict["id"], "Proxy", normalized_proxy)
            row_dict["Proxy"] = normalized_proxy

        original_status = row_dict.get("Status") or ""
        normalized_status = format_status_text(original_status)
        if normalized_status != original_status:
            self._rewrite_text_field(row_dict["id"], "Status", normalized_status)
            row_dict["Status"] = normalized_status

        return row_dict

    def _create_table(self):
        query = """
        CREATE TABLE IF NOT EXISTS accounts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            Account_Name TEXT,
            Path_Chrome TEXT,
            Proxy TEXT,
            Email TEXT,
            Password TEXT,
            Twofa TEXT,
            Cookie TEXT,
            Token TEXT,
            Status TEXT,
            Post_Count INTEGER DEFAULT 0,
            Page_Count INTEGER DEFAULT 0,
            Page_Names TEXT DEFAULT ''
        )
        """
        with self._connect() as conn:
            conn.execute(query)
            self._ensure_column(conn, "accounts", "Page_Count", "INTEGER DEFAULT 0")
            self._ensure_column(conn, "accounts", "Page_Names", "TEXT DEFAULT ''")
            conn.commit()

    def _ensure_column(self, conn, table_name: str, column_name: str, column_definition: str):
        columns = {
            row[1]
            for row in conn.execute(f"PRAGMA table_info({table_name})").fetchall()
        }
        if column_name not in columns:
            conn.execute(f"ALTER TABLE {table_name} ADD COLUMN {column_name} {column_definition}")

    def create_account(
        self,
        account_name: str,
        path_chrome: str,
        proxy: str,
        email: str,
        password: str,
        twofa: str,
        cookie: str,
        token: str,
        status: str,
        post_count: int,
    ):
        query = """
        INSERT INTO accounts (
            Account_Name,
            Path_Chrome,
            Proxy,
            Email,
            Password,
            Twofa,
            Cookie,
            Token,
            Status,
            Post_Count
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """
        normalized_path = self._normalize_profile_path_value(path_chrome)
        with self._connect() as conn:
            cursor = conn.execute(
                query,
                (
                    account_name,
                    normalized_path,
                    format_proxy_text(proxy),
                    email,
                    password,
                    twofa,
                    cookie,
                    token,
                    format_status_text(status),
                    post_count,
                ),
            )
            conn.commit()
            return cursor.lastrowid

    def find_account_by_exact_path(self, path_chrome: str) -> Optional[Dict[str, Any]]:
        normalized_path = self._normalize_profile_path_value(path_chrome)
        if not normalized_path:
            return None

        query = "SELECT * FROM accounts WHERE Path_Chrome = ?"
        with self._connect() as conn:
            conn.row_factory = sqlite3.Row
            row = conn.execute(query, (normalized_path,)).fetchone()
            return self._normalize_account_row(row)

    def save_account_profile(
        self,
        account_name: str,
        path_chrome: str,
        proxy: str,
        email: str,
        password: str,
        twofa: str,
    ) -> str:
        normalized_path = self._normalize_profile_path_value(path_chrome)
        existing_account = self.find_account_by_exact_path(normalized_path)

        if existing_account:
            query = """
            UPDATE accounts
            SET
                Account_Name = ?,
                Path_Chrome = ?,
                Proxy = ?,
                Email = ?,
                Password = ?,
                Twofa = ?
            WHERE id = ?
            """
            with self._connect() as conn:
                conn.execute(
                    query,
                    (
                        account_name,
                        normalized_path,
                        format_proxy_text(proxy),
                        email,
                        password,
                        twofa,
                        existing_account["id"],
                    ),
                )
                conn.commit()
            return "updated"

        self.create_account(
            account_name=account_name,
            path_chrome=normalized_path,
            proxy=proxy,
            email=email,
            password=password,
            twofa=twofa,
            cookie="",
            token="",
            status="Chưa rõ",
            post_count=0,
        )
        return "created"

    def get_all_accounts(self) -> List[Dict[str, Any]]:
        query = "SELECT * FROM accounts"
        with self._connect() as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(query).fetchall()
            normalized_rows = []
            for row in rows:
                row_dict = self._normalize_account_row(row)
                if row_dict is not None:
                    normalized_rows.append(row_dict)
            return normalized_rows

    def find_id_from_path_chrome(self, name_path: str) -> int:
        query = "SELECT * FROM accounts WHERE Path_Chrome LIKE ?"
        with self._connect() as conn:
            conn.row_factory = sqlite3.Row
            row = conn.execute(query, (f"%\\{name_path}%",)).fetchone()
            print(row)
            return row[0]
        
    def find_account_name_from_path_chrome(self, name_path: str) -> int:
        query = "SELECT * FROM accounts WHERE Path_Chrome LIKE ?"
        with self._connect() as conn:
            conn.row_factory = sqlite3.Row
            row = conn.execute(query, (f"%\\{name_path}",)).fetchone()
            row_dict = self._normalize_account_row(row)
            return row_dict["Account_Name"]
        
    def find_full_path_from_path_chrome(self, name_path: str) -> str:
        query = "SELECT * FROM accounts WHERE Path_Chrome LIKE ?"
        with self._connect() as conn:
            conn.row_factory = sqlite3.Row
            row = conn.execute(query, (f"%\\{name_path}",)).fetchone()
            row_dict = self._normalize_account_row(row)
            return row_dict["Path_Chrome"]
        
    
    def find_info_account_from_path_chrome(self, name_path: str) -> str:
        query = "SELECT * FROM accounts WHERE Path_Chrome LIKE ?"
        with self._connect() as conn:
            conn.row_factory = sqlite3.Row
            row = conn.execute(query, (f"%\\{name_path}",)).fetchone()
            row_dict = self._normalize_account_row(row)
            return row_dict["Email"]+"|"+row_dict["Password"]+"|"+row_dict["Twofa"]
        
    def find_proxy_from_path_chrome(self, name_path: str) -> str:
        query = "SELECT * FROM accounts WHERE Path_Chrome LIKE ?"
        with self._connect() as conn:
            conn.row_factory = sqlite3.Row
            row = conn.execute(query, (f"%\\{name_path}",)).fetchone()
            row_dict = self._normalize_account_row(row)
            return row_dict["Proxy"]
        
    def find_token_from_path_chrome(self, name_path: str) -> str:
        query = "SELECT * FROM accounts WHERE Path_Chrome LIKE ?"
        with self._connect() as conn:
            conn.row_factory = sqlite3.Row
            row = conn.execute(query, (f"%\\{name_path}",)).fetchone()
            row_dict = self._normalize_account_row(row)
            return row_dict["Token"]

    def find_cookie_from_path_chrome(self, name_path: str) -> str:
        query = "SELECT * FROM accounts WHERE Path_Chrome LIKE ?"
        with self._connect() as conn:
            conn.row_factory = sqlite3.Row
            row = conn.execute(query, (f"%\\{name_path}",)).fetchone()
            row_dict = self._normalize_account_row(row)
            return row_dict["Cookie"]
        
    def find_post_count_from_path_chrome(self, name_path: str) -> str:
        query = "SELECT * FROM accounts WHERE Path_Chrome LIKE ?"
        with self._connect() as conn:
            conn.row_factory = sqlite3.Row
            row = conn.execute(query, (f"%\\{name_path}",)).fetchone()
            row_dict = self._normalize_account_row(row)
            return row_dict["Post_Count"]

    def find_page_count_from_path_chrome(self, name_path: str) -> int:
        query = "SELECT * FROM accounts WHERE Path_Chrome LIKE ?"
        with self._connect() as conn:
            conn.row_factory = sqlite3.Row
            row = conn.execute(query, (f"%\\{name_path}",)).fetchone()
            row_dict = self._normalize_account_row(row)
            return int(row_dict.get("Page_Count") or 0)

    def find_page_names_from_path_chrome(self, name_path: str) -> str:
        query = "SELECT * FROM accounts WHERE Path_Chrome LIKE ?"
        with self._connect() as conn:
            conn.row_factory = sqlite3.Row
            row = conn.execute(query, (f"%\\{name_path}",)).fetchone()
            row_dict = self._normalize_account_row(row)
            return row_dict.get("Page_Names") or ""

    def get_account_by_id(self, path_chrome: str) -> Optional[Dict[str, Any]]:
        query = "SELECT * FROM accounts WHERE id = ?"
        with self._connect() as conn:
            conn.row_factory = sqlite3.Row
            row = conn.execute(query,(f"%{path_chrome}",)).fetchone()
            return self._normalize_account_row(row)
        
    def update_cookie_token_by_path(self, path_profile: str, cookie: str, token: str) -> bool:
        query = """ UPDATE accounts SET Cookie = ?, Token = ? WHERE Path_Chrome = ? """
        normalized_path = self._normalize_profile_path_value(path_profile)
        try:
            with self._connect() as conn:
                cursor = conn.execute(query,(cookie,token,normalized_path),)
                conn.commit()
                return cursor.rowcount > 0
        except Exception as e:
            print(f"Lỗi update cookie/token: {e}")
            return False
        

    def update_status_by_path(self, path_profile: str, status: str) -> bool:
        query = """ UPDATE accounts SET Status = ? WHERE Path_Chrome = ? """
        normalized_path = self._normalize_profile_path_value(path_profile)
        normalized_status = format_status_text(status)
        try:
            with self._connect() as conn:
                cursor = conn.execute(query, (normalized_status, normalized_path))
                conn.commit()
                return cursor.rowcount > 0
        except Exception as e:
            print(f"Lỗi update status: {e}")
            return False

    def mark_profile_logged_in(self, path_profile: str) -> bool:
        normalized_path = self._normalize_profile_path_value(path_profile)
        if not normalized_path:
            return False

        profile_name = Path(normalized_path).name

        try:
            with self._connect() as conn:
                cursor = conn.execute(
                    """
                    UPDATE accounts
                    SET Path_Chrome = ?, Status = ?
                    WHERE Path_Chrome = ?
                    """,
                    (normalized_path, "Đã đăng nhập", normalized_path),
                )

                if cursor.rowcount == 0 and profile_name:
                    cursor = conn.execute(
                        """
                        UPDATE accounts
                        SET Path_Chrome = ?, Status = ?
                        WHERE Path_Chrome LIKE ?
                        """,
                        (normalized_path, "Đã đăng nhập", f"%\\{profile_name}"),
                    )

                conn.commit()
                return cursor.rowcount > 0
        except Exception as e:
            print(f"Lỗi mark profile logged in: {e}")
            return False

    def update_page_count_by_path(self, path_profile: str, page_count: int) -> bool:
        query = """ UPDATE accounts SET Page_Count = ? WHERE Path_Chrome = ? """
        normalized_path = self._normalize_profile_path_value(path_profile)
        try:
            with self._connect() as conn:
                cursor = conn.execute(query, (int(page_count or 0), normalized_path))
                conn.commit()
                return cursor.rowcount > 0
        except Exception as e:
            print(f"Lỗi update page count: {e}")
            return False

    def update_page_names_by_path(self, path_profile: str, page_names: str) -> bool:
        query = """ UPDATE accounts SET Page_Names = ? WHERE Path_Chrome = ? """
        normalized_path = self._normalize_profile_path_value(path_profile)
        try:
            with self._connect() as conn:
                cursor = conn.execute(query, (page_names or "", normalized_path))
                conn.commit()
                return cursor.rowcount > 0
        except Exception as e:
            print(f"Lỗi update page names: {e}")
            return False

    def update_page_info_by_path(self, path_profile: str, page_count: int, page_names: str) -> bool:
        query = """ UPDATE accounts SET Page_Count = ?, Page_Names = ? WHERE Path_Chrome = ? """
        normalized_path = self._normalize_profile_path_value(path_profile)
        try:
            with self._connect() as conn:
                cursor = conn.execute(
                    query,
                    (int(page_count or 0), page_names or "", normalized_path),
                )
                conn.commit()
                return cursor.rowcount > 0
        except Exception as e:
            print(f"Lỗi update page info: {e}")
            return False

    def update_account(
        self,
        account_id: int,
        account_name: str,
        path_chrome: str,
        proxy: str,
        email: str,
        password: str,
        status: str,
        post_count: int,
    ) -> bool:
        query = """
        UPDATE accounts
        SET
            Account_Name = ?,
            Path_Chrome = ?,
            Proxy = ?,
            Email = ?,
            Password = ?,
            Status = ?,
            Post_Count = ?
        WHERE id = ?
        """
        with self._connect() as conn:
            cursor = conn.execute(
                query,
                (
                    account_name,
                    path_chrome,
                    format_proxy_text(proxy),
                    email,
                    password,
                    format_status_text(status),
                    post_count,
                    account_id,
                ),
            )
            conn.commit()
            return cursor.rowcount > 0

    def delete_account(self, account_id: int) -> bool:
        query = "DELETE FROM accounts WHERE id = ?"
        with self._connect() as conn:
            cursor = conn.execute(query, (account_id,))
            conn.commit()
            return cursor.rowcount > 0

# if __name__ == "__main__":
#     db = AccountDB()

#     # CREATE
#     new_id = db.create_account(
#         account_name="acc_01",
#         path_chrome=r"C:\ChromeProfile\acc_01",
#         proxy="127.0.0.1:8080",
#         email="test@gmail.com",
#         password="123456",
#         status="active",
#         post_count=5,
#     )
#     print(f"Đã thêm account, id = {new_id}")

#     # READ ALL
#     print("Danh sách accounts:")
#     print(db.get_all_accounts())

#     # READ ONE
#     print("Lấy account theo id:")
#     print(db.get_account_by_id(new_id))

#     # UPDATE
#     updated = db.update_account(
#         account_id=new_id,
#         account_name="acc_01_updated",
#         path_chrome=r"C:\ChromeProfile\acc_01_new",
#         proxy="127.0.0.1:9999",
#         email="newmail@gmail.com",
#         password="abcdef",
#         status="running",
#         post_count=10,
#     )
#     print("Update thành công:", updated)

#     # DELETE
#     deleted = db.delete_account(new_id)
#     print("Delete thành công:", deleted)
