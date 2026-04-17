# app/integrations/

## Mô tả
Chứa các client để kết nối với các dịch vụ API bên thứ ba.

## Các file

- **facebook_client.py** - Client kết nối với Facebook Graph API
  - Xác thực người dùng
  - Lấy thông tin nhóm
  - Quét bài viết, comment, reply
  
- **openai_client.py** - Client kết nối với OpenAI API
  - Kiểm tra bài viết bằng AI
  - Tạo câu trả lời tự động
  
- **telegram_client.py** - Client gửi thông báo qua Telegram
  - Gửi tin nhắn thông báo
  - Gửi cảnh báo

## Cách hoạt động
Mỗi client cung cấp các phương thức để tương tác với API tương ứng, xử lý lỗi, 
và quản lý token/key xác thực.
