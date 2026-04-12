# \# 📌 Scan Controller

# 

# \## 🧩 Giới thiệu

# 

# `ScanController` là một module trung tâm dùng để điều phối quá trình quét (scan) các nhóm, xử lý bài viết theo từ khóa, và lưu kết quả vào file JSON.

# 

# Module này kết hợp với:

# 

# \* `ScheduleService` để tính toán lịch quét

# \* `ScanGroups` worker để thực hiện việc quét dữ liệu

# 

# \---

# 

# \## 🚀 Chức năng chính

# 

# \* Quét danh sách group theo chu kỳ

# \* Lọc bài viết theo từ khóa

# \* Gửi callback tiến trình, trạng thái, và dữ liệu bài viết

# \* Lưu kết quả vào file `posts.json`

# 

# \---

# 

# \## 📂 Cấu trúc liên quan

# 

# ```

# scan\_controller.py

# services/

# &#x20;└── scheduler\_service.py

# workers/

# &#x20;└── scan\_groups\_worker.py

# data/

# &#x20;└── posts.json

# ```

# 

# \---

# 

# \## ⚙️ Khởi tạo

# 

# ```python

# ScanController(

# &#x20;   groups\_list,

# &#x20;   delay,

# &#x20;   keywords,

# &#x20;   account\_token=None,

# &#x20;   account\_cookies=None,

# &#x20;   proxies=None,

# &#x20;   API\_KEY=None,

# &#x20;   token\_tele=None,

# &#x20;   idchat=None,

# &#x20;   prompt=None,

# &#x20;   max\_length\_text=500,

# &#x20;   progress\_callback=None,

# &#x20;   status\_callback=None,

# &#x20;   post\_callback=None

# )

# ```

# 

# \### 🔑 Tham số

# 

# | Tên                 | Kiểu      | Mô tả                           |

# | ------------------- | --------- | ------------------------------- |

# | `groups\_list`       | list      | Danh sách group cần quét        |

# | `delay`             | int/float | Chu kỳ quét (giờ)               |

# | `keywords`          | list      | Từ khóa lọc bài viết            |

# | `account\_token`     | str       | Token đăng nhập                 |

# | `account\_cookies`   | dict      | Cookie tài khoản                |

# | `proxies`           | dict/list | Proxy sử dụng                   |

# | `API\_KEY`           | str       | API key (AI / external service) |

# | `token\_tele`        | str       | Token Telegram                  |

# | `idchat`            | str/int   | Chat ID Telegram                |

# | `prompt`            | str       | Prompt dùng cho xử lý nội dung  |

# | `max\_length\_text`   | int       | Giới hạn độ dài text            |

# | `progress\_callback` | func      | Callback tiến trình             |

# | `status\_callback`   | func      | Callback trạng thái             |

# | `post\_callback`     | func      | Callback khi có bài viết        |

# 

# \---

# 

# \## ▶️ Cách sử dụng

# 

# ```python

# controller = ScanController(

# &#x20;   groups\_list=\["group1", "group2"],

# &#x20;   delay=2,

# &#x20;   keywords=\["sale", "discount"]

# )

# 

# result = controller.start\_scan()

# print(result)

# ```

# 

# \---

# 

# \## 🔄 Luồng hoạt động

# 

# 1\. Khởi tạo `ScanController`

# 2\. Gọi `start\_scan()`

# 3\. Tạo lịch quét từ `ScheduleService`

# 4\. Khởi tạo `ScanGroups` worker

# 5\. Worker thực hiện quét group

# 6\. Trả về danh sách bài viết (`posts\_status`)

# 7\. Ghi dữ liệu vào `data/posts.json`

# 

# \---

# 

# \## 💾 Output

# 

# Kết quả được lưu tại:

# 

# ```

# data/posts.json

# ```

# 

# \### Ví dụ:

# 

# ```json

# \[

# &#x20;   {

# &#x20;       "group": "group1",

# &#x20;       "content": "Big sale today!",

# &#x20;       "status": 1

# &#x20;   }

# ]

# ```

# 

# \* `status = 1`: hợp lệ (match keyword)

# \* `status = 0`: không hợp lệ

# 

# \---

# 

# \## 🧠 Logging

# 

# Module sử dụng `logging` để ghi log:

# 

# \* Debug khi khởi tạo

# \* Info khi bắt đầu scan

# \* Info khi ghi file JSON

# 

# \---

# 

# \## 🧪 Callbacks

# 

# Bạn có thể truyền callback để xử lý realtime:

# 

# ```python

# def on\_progress(data):

# &#x20;   print("Progress:", data)

# 

# def on\_status(status):

# &#x20;   print("Status:", status)

# 

# def on\_post(post):

# &#x20;   print("New post:", post)

# ```

# 

# \---

# 

# \## ⚠️ Lưu ý

# 

# \* Đảm bảo file `posts.json` có quyền ghi

# \* Các service phụ (`ScheduleService`, `ScanGroups`) phải được implement đầy đủ

# \* Token / cookies cần hợp lệ nếu scan từ platform yêu cầu đăng nhập

# 

# \---

# 

# \## 📎 Tham chiếu

# 

# Code nguồn: 

# 

# \---

# 

# \## 👨‍💻 Tác giả

# 

# Developed for automated group scanning \& keyword-based filtering.



