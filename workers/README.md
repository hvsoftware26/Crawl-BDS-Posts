# app/workers/

## Mô tả
Chứa các worker thread - các luồng xử lý nền để thực hiện các tác vụ dài ngày
mà không làm đứng cứng giao diện người dùng.

## Các file

- **login_worker.py** - Worker xử lý đăng nhập
  - Xác thực với Facebook
  - Lưu token xác thực
  - Gửi signal khi hoàn thành

- **scan_groups_worker.py** - Worker quét nhóm
  - Lấy danh sách nhóm
  - Quét bài viết từ mỗi nhóm
  - Cập nhật cơ sở dữ liệu

- **process_posts_worker.py** - Worker xử lý bài viết
  - Lọc bài viết theo từ khóa
  - Kiểm tra bằng AI
  - Tạo câu trả lời
  - Lưu kết quả

- **notify_worker.py** - Worker gửi thông báo
  - Gửi thông báo Telegram
  - Gửi alert

## Cách hoạt động
- Worker chạy trong luồng riêng (QThread)
- Không chặn the UI thread
- Sử dụng signal/slot để gửi dữ liệu về main thread
- Luôn cập nhật UI thông qua thread-safe signals

## Lợi ích
- UI không bị đứng cứng (không lag)
- Ứng dụng vẫn responsive trong khi xử lý
- Có thể hủy tác vụ dài nếu cần
