import sqlite3, os
from typing import Optional, List, Dict, Any
from pathlib import Path

class AccountDB:
    def __init__(self, db_name: None):
        if db_name is None:
            base_dir = Path(__file__).resolve().parent.parent
            db_path = base_dir / "database" / "accounts.db"
        else:
            db_path = Path(db_name)

        # ✅ Tạo folder nếu chưa tồn tại
        db_path.parent.mkdir(parents=True, exist_ok=True)

        self.db_name = str(db_path)

    def _connect(self):
        return sqlite3.connect(self.db_name)

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
            Post_Count INTEGER DEFAULT 0
        )
        """
        with self._connect() as conn:
            conn.execute(query)
            conn.commit()

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
        with self._connect() as conn:
            cursor = conn.execute(
                query,
                (
                    account_name,
                    path_chrome,
                    proxy,
                    email,
                    password,
                    twofa,
                    cookie,
                    token,
                    status,
                    post_count,
                ),
            )
            conn.commit()
            return cursor.lastrowid

    def get_all_accounts(self) -> List[Dict[str, Any]]:
        query = "SELECT * FROM accounts"
        with self._connect() as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(query).fetchall()
            return [dict(row) for row in rows]

    def find_id_from_path_chrome(self, name_path: str) -> int:
        query = "SELECT * FROM accounts WHERE Path_Chrome LIKE ?"
        with self._connect() as conn:
            conn.row_factory = sqlite3.Row
            row = conn.execute(query, (f"%\\{name_path}",)).fetchone()
            return row["id"]
        
    def find_account_name_from_path_chrome(self, name_path: str) -> int:
        query = "SELECT * FROM accounts WHERE Path_Chrome LIKE ?"
        with self._connect() as conn:
            conn.row_factory = sqlite3.Row
            row = conn.execute(query, (f"%\\{name_path}",)).fetchone()
            return row["Account_Name"]
        
    def find_full_path_from_path_chrome(self, name_path: str) -> str:
        query = "SELECT * FROM accounts WHERE Path_Chrome LIKE ?"
        with self._connect() as conn:
            conn.row_factory = sqlite3.Row
            row = conn.execute(query, (f"%\\{name_path}",)).fetchone()
            return row["Path_Chrome"]
        
    
    def find_info_account_from_path_chrome(self, name_path: str) -> str:
        query = "SELECT * FROM accounts WHERE Path_Chrome LIKE ?"
        with self._connect() as conn:
            conn.row_factory = sqlite3.Row
            row = conn.execute(query, (f"%\\{name_path}",)).fetchone()
            return row["Email"]+"|"+row["Password"]+"|"+row["Twofa"]
        
    def find_proxy_from_path_chrome(self, name_path: str) -> str:
        query = "SELECT * FROM accounts WHERE Path_Chrome LIKE ?"
        with self._connect() as conn:
            conn.row_factory = sqlite3.Row
            row = conn.execute(query, (f"%\\{name_path}",)).fetchone()
            return row["Proxy"]
        
    def find_token_from_path_chrome(self, name_path: str) -> str:
        query = "SELECT * FROM accounts WHERE Path_Chrome LIKE ?"
        with self._connect() as conn:
            conn.row_factory = sqlite3.Row
            row = conn.execute(query, (f"%\\{name_path}",)).fetchone()
            return row["Token"]

    def find_cookie_from_path_chrome(self, name_path: str) -> str:
        query = "SELECT * FROM accounts WHERE Path_Chrome LIKE ?"
        with self._connect() as conn:
            conn.row_factory = sqlite3.Row
            row = conn.execute(query, (f"%\\{name_path}",)).fetchone()
            return row["Cookie"]
        
    def find_post_count_from_path_chrome(self, name_path: str) -> str:
        query = "SELECT * FROM accounts WHERE Path_Chrome LIKE ?"
        with self._connect() as conn:
            conn.row_factory = sqlite3.Row
            row = conn.execute(query, (f"%\\{name_path}",)).fetchone()
            return row["Post_Count"]

    def get_account_by_id(self, path_chrome: str) -> Optional[Dict[str, Any]]:
        query = "SELECT * FROM accounts WHERE id = ?"
        with self._connect() as conn:
            conn.row_factory = sqlite3.Row
            row = conn.execute(query,(f"%{path_chrome}",)).fetchone()
            return dict(row) if row else None
        
    def update_cookie_token_by_path(self, path_profile: str, cookie: str, token: str) -> bool:
        query = """ UPDATE accounts SET Cookie = ?, Token = ? WHERE Path_Chrome = ? """
        try:
            with self._connect() as conn:
                cursor = conn.execute(query,(cookie,token,path_profile),)
                conn.commit()
                return cursor.rowcount > 0
        except Exception as e:
            print(f"Lỗi update cookie/token: {e}")
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
                    proxy,
                    email,
                    password,
                    status,
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