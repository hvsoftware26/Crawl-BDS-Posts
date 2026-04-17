# app/services/

## Mô tả
Chứa logic kinh doanh (business logic) của ứng dụng. 
Các service xử lý các công việc phức tạp và tương tác giữa nhiều thành phần.

## Các file

- **auth_service.py** - Xác thực người dùng
  - Đăng nhập với Facebook
  - Quản lý token
  - Kiểm tra trạng thái token

- **group_service.py** - Quản lý nhóm
  - Lấy danh sách nhóm
  - Cập nhật thông tin nhóm
  - Bật/tắt theo dõi nhóm

- **post_service.py** - Xử lý bài viết
  - Lấy bài viết từ nhóm
  - Lọc bài viết theo từ khóa
  - Cập nhật trạng thái bài viết

- **keyword_service.py** - Quản lý từ khóa
  - Thêm/xóa từ khóa
  - Kiểm tra từ khóa trong bài viết

- **ai_service.py** - Xử lý AI
  - Kiểm tra bài viết bằng AI
  - Tạo câu trả lời tự động

- **notify_service.py** - Gửi thông báo
  - Gửi thông báo Telegram
  - Gửi cảnh báo

- **scheduler_service.py** - Lập lịch công việc
  - Lịch quét nhóm định kỳ
  - Lịch kiểm tra token
  - Lịch khác

## Kiến trúc
Các service được gọi từ controllers hoặc workers,
không trực tiếp từ UI layer.
