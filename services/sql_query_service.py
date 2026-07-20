import sqlite3
import logging
from typing import Optional, List, Dict, Any
from pathlib import Path
from app_config import APP_BASE_DIR, PROFILE_ROOT_DIR

logger = logging.getLogger(__name__)

class AccountDB:
    def __init__(self, db_name: None):
        if db_name is None:
            base_dir = APP_BASE_DIR
            db_path = base_dir / "database" / "accounts.db"
        else:
            db_path = Path(db_name)
            base_dir = db_path.resolve().parent.parent

        # Ensure the database folder exists.
        db_path.parent.mkdir(parents=True, exist_ok=True)

        self.base_dir = base_dir.resolve()
        self.profile_root = PROFILE_ROOT_DIR if db_name is None else (self.base_dir / "Profile-Chrome").resolve()
        self.db_name = str(db_path)

    def _connect(self):
        conn = sqlite3.connect(self.db_name, timeout=30)
        conn.execute("PRAGMA busy_timeout = 30000")
        conn.execute("PRAGMA journal_mode = WAL")
        return conn

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

    def _normalize_account_row(self, row: sqlite3.Row | None) -> Optional[Dict[str, Any]]:
        if row is None:
            return None

        row_dict = dict(row)
        original_path = row_dict.get("Path_Chrome") or ""
        normalized_path = self._normalize_profile_path_value(original_path)

        if normalized_path and normalized_path != original_path:
            self._rewrite_profile_path(original_path, normalized_path)
            row_dict["Path_Chrome"] = normalized_path

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
            Mail_Password TEXT DEFAULT '',
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
            self._ensure_column(conn, "accounts", "Mail_Password", "TEXT DEFAULT ''")
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
        mail_password: str = "",
    ):
        query = """
        INSERT INTO accounts (
            Account_Name,
            Path_Chrome,
            Proxy,
            Email,
            Password,
            Twofa,
            Mail_Password,
            Cookie,
            Token,
            Status,
            Post_Count
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """
        normalized_path = self._normalize_profile_path_value(path_chrome)
        with self._connect() as conn:
            cursor = conn.execute(
                query,
                (
                    account_name,
                    normalized_path,
                    proxy,
                    email,
                    password,
                    twofa,
                    mail_password,
                    cookie,
                    token,
                    status,
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

    def save_imported_cookie_account(
        self,
        uid: str,
        password: str,
        cookie: str,
        token: str,
        email: str,
        mail_password: str,
        path_chrome: str,
        twofa: str = "",
        proxy: str = "",
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
                Twofa = ?,
                Mail_Password = ?,
                Cookie = ?,
                Token = ?,
                Status = ?
            WHERE id = ?
            """
            with self._connect() as conn:
                conn.execute(
                    query,
                    (
                        uid,
                        normalized_path,
                        proxy,
                        email,
                        password,
                        twofa,
                        mail_password,
                        cookie,
                        token,
                        "Đã nhập cookie",
                        existing_account["id"],
                    ),
                )
                conn.commit()
            return "updated"

        self.create_account(
            account_name=uid,
            path_chrome=normalized_path,
            proxy=proxy,
            email=email,
            password=password,
            twofa=twofa,
            mail_password=mail_password,
            cookie=cookie,
            token=token,
            status="Đã nhập cookie",
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
            logger.debug("find_id_from_path_chrome matched=%s", bool(row))
            return row[0]
        
    def find_full_path_from_path_chrome(self, name_path: str) -> str:
        query = "SELECT * FROM accounts WHERE Path_Chrome LIKE ?"
        with self._connect() as conn:
            conn.row_factory = sqlite3.Row
            row = conn.execute(query, (f"%\\{name_path}",)).fetchone()
            row_dict = self._normalize_account_row(row)
            return row_dict["Path_Chrome"]

    def find_account_from_path_chrome(self, name_path: str) -> Optional[Dict[str, Any]]:
        query = "SELECT * FROM accounts WHERE Path_Chrome LIKE ?"
        with self._connect() as conn:
            conn.row_factory = sqlite3.Row
            row = conn.execute(query, (f"%\\{name_path}",)).fetchone()
            return self._normalize_account_row(row)
        
    
    def find_info_account_from_path_chrome(self, name_path: str) -> str:
        query = "SELECT * FROM accounts WHERE Path_Chrome LIKE ?"
        with self._connect() as conn:
            conn.row_factory = sqlite3.Row
            row = conn.execute(query, (f"%\\{name_path}",)).fetchone()
            row_dict = self._normalize_account_row(row)
            third_value = row_dict.get("Mail_Password") or row_dict.get("Twofa") or ""
            return row_dict["Email"]+"|"+row_dict["Password"]+"|"+third_value
        
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
        
    def update_cookie_token_by_path(self, path_profile: str, cookie: str, token: str) -> bool:
        query = """ UPDATE accounts SET Cookie = ?, Token = ? WHERE Path_Chrome = ? """
        normalized_path = self._normalize_profile_path_value(path_profile)
        try:
            with self._connect() as conn:
                cursor = conn.execute(query,(cookie,token,normalized_path),)
                conn.commit()
                return cursor.rowcount > 0
        except Exception as e:
            logger.exception("Error updating cookie/token")
            return False
        

    def update_status_by_path(self, path_profile: str, status: str) -> bool:
        query = """ UPDATE accounts SET Status = ? WHERE Path_Chrome = ? """
        normalized_path = self._normalize_profile_path_value(path_profile)
        try:
            with self._connect() as conn:
                cursor = conn.execute(query, (status, normalized_path))
                conn.commit()
                return cursor.rowcount > 0
        except Exception as e:
            logger.exception("Error updating account status")
            return False

    def update_proxy_by_path(self, path_profile: str, proxy: str) -> bool:
        query = """ UPDATE accounts SET Proxy = ? WHERE Path_Chrome = ? """
        normalized_path = self._normalize_profile_path_value(path_profile)
        try:
            with self._connect() as conn:
                cursor = conn.execute(query, (proxy or "", normalized_path))
                conn.commit()
                return cursor.rowcount > 0
        except Exception:
            logger.exception("Error updating account proxy")
            return False

    def update_account_name_by_path(self, path_profile: str, account_name: str) -> bool:
        query = """ UPDATE accounts SET Account_Name = ? WHERE Path_Chrome = ? """
        normalized_path = self._normalize_profile_path_value(path_profile)
        normalized_name = str(account_name or "").strip()
        if not normalized_path or not normalized_name:
            return False

        try:
            with self._connect() as conn:
                cursor = conn.execute(query, (normalized_name, normalized_path))
                conn.commit()
                return cursor.rowcount > 0
        except Exception:
            logger.exception("Error updating account name")
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
            logger.exception("Error updating page count")
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
            logger.exception("Error updating page info")
            return False

    def delete_account(self, account_id: int) -> bool:
        query = "DELETE FROM accounts WHERE id = ?"
        with self._connect() as conn:
            cursor = conn.execute(query, (account_id,))
            conn.commit()
            return cursor.rowcount > 0
