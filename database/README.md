# 📘 README - accounts.db

## 📌 Giới thiệu

`accounts.db` là một cơ sở dữ liệu SQLite3 được thiết kế để quản lý thông tin tài khoản phục vụ cho các hệ thống tự động (automation), bao gồm thông tin đăng nhập, proxy, cookie, token và trạng thái hoạt động.

---

## 🗂️ Thông tin chung

- **Tên database:** `accounts.db`
- **Hệ quản trị:** SQLite3
- **Bảng chính:** `accounts`

---

## 🧱 Cấu trúc bảng `accounts`

| STT | Tên cột        | Kiểu dữ liệu | Mô tả |
|-----|----------------|-------------|------|
| 0   | `id`           | INTEGER     | Khóa chính, tự động tăng |
| 1   | `Account_Name` | TEXT        | Tên tài khoản |
| 2   | `Path_Chrome`  | TEXT        | Đường dẫn profile Chrome |
| 3   | `Proxy`        | TEXT        | Proxy |
| 4   | `Email`        | TEXT        | Email |
| 5   | `Password`     | TEXT        | Mật khẩu |
| 6   | `Twofa`        | TEXT        | Mã 2FA |
| 7   | `Cookie`       | TEXT        | Mặc định "" |
| 8   | `Token`        | TEXT        | Mặc định "" |
| 9   | `Status`       | TEXT        | Mặc định "Chưa rõ" |
| 10  | `Post_Count`   | INTEGER     | Mặc định 0 |
| 11  | `Page_Count`   | INTEGER     | Tổng số page Facebook account quản lý, mặc định 0 |
| 12  | `Page_Names`   | TEXT        | Danh sách tên page, mỗi dòng một page |

---

## 🛠️ Câu lệnh tạo bảng

```sql
CREATE TABLE IF NOT EXISTS accounts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    Account_Name TEXT,
    Path_Chrome TEXT,
    Proxy TEXT,
    Email TEXT,
    Password TEXT,
    Twofa TEXT,
    Cookie TEXT DEFAULT "",
    Token TEXT DEFAULT "",
    Status TEXT DEFAULT "Chưa rõ",
    Post_Count INTEGER DEFAULT 0,
    Page_Count INTEGER DEFAULT 0,
    Page_Names TEXT DEFAULT ''
);
```

---

## ⚙️ Giá trị mặc định

- Cookie: ""
- Token: ""
- Status: "Chưa rõ"
- Post_Count: 0
- Page_Count: 0
- Page_Names: ""

---

## 🔄 Workflow

1. Thêm tài khoản
2. Chạy script login
3. Lấy Cookie / Token
4. Cập nhật Status
5. Cập nhật Page_Count và Page_Names sau khi đăng nhập thủ công hoặc kiểm tra đăng nhập
6. Tăng Post_Count

---

## ⚠️ Bảo mật

Không chia sẻ database vì chứa thông tin nhạy cảm.

---
