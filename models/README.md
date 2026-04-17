# Account Configuration Model — `Info_data`

## Overview

`Info_data` là **data model** dùng để lưu cấu hình cho từng account trong hệ thống automation.

Model này được thiết kế bằng `@dataclass` để:

* Quản lý nhiều account dễ dàng
* Truyền dữ liệu giữa GUI, Model và Worker Thread
* Hỗ trợ queue và multi-thread
* Dễ serialize (lưu file / export / import)

---

## Import

```python
from dataclasses import dataclass
from typing import Optional, List
```

---

## Model Definition

```python
@dataclass
class Info_data:
    row: int
    account_name: str
    path_chrome: str
    proxy: str
    emjuail: str
    password: str
    twofa: str
    cookie: str
    token: str
    post_count: str
    api_key: str
    groups_list: Optional[List[str]]
    prompt: str
    id_chat: str
    token_tele: str
    cycle_total: int
    delay_get_cookie_token: float
    delay_get_post_gr: float
    keywords_list: Optional[List[str]]
```

---

# Field Description

## Basic Account Info

| Field          | Type  | Description                        |
| -------------- | ----- | ---------------------------------- |
| `row`          | `int` | Dòng của account trong table/model |
| `account_name` | `str` | Tên account                        |
| `path_chrome`  | `str` | Đường dẫn profile Chrome           |
| `proxy`        | `str` | Proxy dạng `ip:port:user:pass`     |
| `emjuail`      | `str` | Email đăng nhập                    |
| `password`     | `str` | Mật khẩu account                   |
| `twofa`        | `str` | Secret key 2FA                     |

---

## Session Data

| Field     | Type  | Description    |
| --------- | ----- | -------------- |
| `cookie`  | `str` | Cookie session |
| `token`   | `str` | Access token   |
| `api_key` | `str` | API key nếu có |

---

## Posting Configuration

| Field           | Type                  | Description              |
| --------------- | --------------------- | ------------------------ |
| `post_count`    | `str`                 | Số bài viết cần lấy      |
| `groups_list`   | `Optional[List[str]]` | Danh sách group ID       |
| `prompt`        | `str`                 | Prompt dùng tạo nội dung |
| `keywords_list` | `Optional[List[str]]` | Danh sách keyword        |

---

## Telegram Configuration

| Field        | Type  | Description        |
| ------------ | ----- | ------------------ |
| `id_chat`    | `str` | Telegram Chat ID   |
| `token_tele` | `str` | Telegram Bot Token |

---

## Cycle Configuration

| Field                    | Type    | Unit    | Description                |
| ------------------------ | ------- | ------- | -------------------------- |
| `cycle_total`            | `int`   | Hours   | Tổng thời gian chạy chu kì |
| `delay_get_cookie_token` | `float` | Minutes | Delay lấy cookie/token     |
| `delay_get_post_gr`      | `float` | Minutes | Delay lấy bài viết         |

---

# Example Usage

## Create Account Object

```python
account = Info_data(
    row=1,
    account_name="Account_1",
    path_chrome="profiles/profile_1",
    proxy="1.1.1.1:8080:user:pass",
    emjuail="example@gmail.com",
    password="123456",
    twofa="ABCDEF123456",
    cookie="",
    token="",
    post_count="10",
    api_key="API_KEY_HERE",
    groups_list=["group1", "group2"],
    prompt="Write a short post",
    id_chat="123456789",
    token_tele="BOT_TOKEN",
    cycle_total=24,
    delay_get_cookie_token=1.5,
    delay_get_post_gr=2.0,
    keywords_list=["python", "automation"]
)
```

---

# Example With Queue (Multi-thread)

```python
from queue import Queue

task_queue = Queue()

task_queue.put(account)
```

Worker:

```python
task = task_queue.get()

print(task.account_name)
```

---

# Example With Qt Model

```python
accounts: list[Info_data] = []

accounts.append(account)
```

Trong `QAbstractTableModel`:

```python
def data(self, index, role):

    if role == Qt.DisplayRole:

        acc = self.accounts[index.row()]

        if index.column() == 0:
            return acc.account_name
```

---

# Default Optional Fields

Các field sau có thể `None`:

```python
groups_list
keywords_list
```

Ví dụ:

```python
groups_list=None
keywords_list=None
```

---

# Data Flow Architecture

```
GUI Table
    ↓
Account Model
    ↓
Queue
    ↓
Worker Thread
    ↓
Automation Task
```

---

# Recommended Best Practices

## 1. Không sửa trực tiếp từ Worker Thread

Sai:

```python
account.cookie = new_cookie
```

Đúng:

```python
signal.emit(row, new_cookie)
```

Main Thread:

```python
accounts[row].cookie = new_cookie
```

---

## 2. Validate Proxy Format

Format khuyến nghị:

```
ip:port:user:pass
```

Ví dụ:

```
1.52.195.88:11868:user:password
```

---

## 3. Delay Units

| Field                    | Unit    |
| ------------------------ | ------- |
| `delay_get_cookie_token` | Minutes |
| `delay_get_post_gr`      | Minutes |
| `cycle_total`            | Hours   |

---

# Suggested Improvements (Optional)

Bạn có thể thêm default value:

```python
groups_list: Optional[List[str]] = None
keywords_list: Optional[List[str]] = None
```

Hoặc:

```python
cookie: str = ""
token: str = ""
```

Giúp tránh lỗi:

```
TypeError: missing required argument
```

---

# Typical Workflow

```
Load accounts
      ↓
Create Info_data objects
      ↓
Add to Model
      ↓
Push to Queue
      ↓
Worker process
      ↓
Update GUI
```

---

# Serialization (Optional)

## Convert to dict

```python
from dataclasses import asdict

data_dict = asdict(account)
```

---

## Convert from dict

```python
account = Info_data(**data_dict)
```

---

# Common Use Cases

Model này phù hợp cho:

* Multi-account automation
* Social media bot
* Group scraping
* Auto posting
* Telegram notification
* Token/Cookie management

---

# Author Notes

Model này được thiết kế cho:

* Qt GUI Application
* Multi-thread Worker
* Queue-based Task Processing
* Large-scale Account Management

Khuyến nghị sử dụng cùng:

* `QThread`
* `Queue`
* `QAbstractTableModel`

để đạt hiệu suất tốt nhất.
