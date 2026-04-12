# app/utils/

## Mô tả
Chứa các hàm tiện ích (utility functions) và helper được sử dụng 
trên toàn bộ ứng dụng.

## Các file

- **file_utils.py** - Tiện ích xử lý file
  - Đọc/ghi file
  - Quản lý đường dẫn
  - Xóa file/thư mục

- **logger.py** - Cấu hình logging
  - Tạo logger
  - Quản lý log level
  - Ghi log vào file

- **time_utils.py** - Tiện ích xử lý thời gian
  - Chuyển đổi format thời gian
  - Tính khoảng thời gian
  - Lập lịch

- **validators.py** - Xác thực dữ liệu
  - Xác thực email
  - Xác thực URL
  - Xác thực format dữ liệu khác

## Sử dụng
Các hàm tiện ích này được import từ bất kỳ file nào trong project
để tránh viết lại code trùng lặp (DRY principle).
