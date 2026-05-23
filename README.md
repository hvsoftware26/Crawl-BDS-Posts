# Facebook BDS Lead Finder

Tool desktop dùng để quản lý nhiều profile Facebook, quét bài viết trong danh sách group, lọc bài theo keyword và prompt AI, sau đó xuất kết quả ra file Excel và gửi về Telegram.

Dự án được viết bằng Python, giao diện PyQt5, chạy trên Windows và sử dụng Google Chrome profile riêng cho từng tài khoản.

## Chức năng chính

- Thêm và quản lý nhiều profile Facebook.
- Hỗ trợ profile có proxy hoặc không có proxy.
- Tự động mở Chrome theo từng profile để đăng nhập, lấy cookie và token cần thiết.
- Quét danh sách group Facebook theo chu kỳ đã cấu hình.
- Lọc bài viết theo keyword.
- Lọc tiếp bằng OpenAI theo prompt tùy chỉnh.
- Tạo file Excel chứa các bài viết phù hợp.
- Gửi báo cáo từng group và báo cáo tổng hợp chu kỳ về Telegram.
- Lưu kết quả trung gian vào `data/posts.json`.
- Hiển thị trạng thái xử lý và log trực tiếp trên giao diện.

## Yêu cầu môi trường

- Windows.
- Python 3.10 trở lên.
- Google Chrome đã cài đặt trên máy.
- Tài khoản Facebook có quyền xem các group cần quét.
- OpenAI API key để dùng tính năng lọc bằng AI.
- Telegram bot token và chat ID để nhận file báo cáo.

## Cài đặt

Tạo môi trường ảo:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
```

Cài các thư viện cần thiết:

```powershell
pip install PyQt5 playwright requests fake-useragent openpyxl
```

Nếu môi trường Playwright yêu cầu cài driver bổ sung, chạy thêm:

```powershell
python -m playwright install
```

## Chạy tool

Tại thư mục gốc dự án, chạy:

```powershell
python main.py
```

Giao diện chính sẽ mở với tên `Facebook BĐS - Crawl Bài Viết`.

## Chuẩn bị dữ liệu đầu vào

### File danh sách group

File group có thể là `.txt`, `.csv` hoặc `.json`, nhưng tool hiện đang đọc theo từng dòng. Mỗi dòng nên là một link group Facebook hoặc ID group.

Ví dụ:

```text
https://www.facebook.com/groups/nhatrophongtrothuduc
https://www.facebook.com/groups/282513046904325
659144150945217
```

Với link group dạng slug, tool sẽ gọi API của `id.traodoisub.com` để convert sang ID trước khi lấy bài.

### File prompt

File prompt có thể là `.txt`, `.md` hoặc `.json`. Nội dung file dùng để hướng dẫn AI xác định bài viết nào phù hợp.

Ví dụ:

```text
Xác định bài viết có nhu cầu tìm phòng, thuê phòng hoặc cần chỗ ở.
Chỉ chọn bài viết người đăng đang có nhu cầu thuê, không chọn bài đăng cho thuê hoặc quảng cáo.
```

### File Telegram

File cấu hình Telegram là JSON, gồm `id_chat` và `token_tele`.

Ví dụ:

```json
{
    "id_chat": "123456789",
    "token_tele": "YOUR_TELEGRAM_BOT_TOKEN"
}
```

Không đưa token thật vào tài liệu công khai hoặc commit lên repository.

### Dữ liệu profile Facebook

Trong giao diện, bấm `Chọn nhiều profile`, sau đó dán danh sách profile vào ô nhập.

Nếu dùng proxy, chọn chế độ `Profile Chrome - Proxy` và nhập mỗi dòng theo định dạng:

```text
Tên tài khoản|proxy|email|password|2FA
```

Ví dụ:

```text
Tài khoản 1|127.0.0.1:8000:user:pass|example@gmail.com|password123|JBSWY3DPEHPK3PXP
```

Nếu không dùng proxy, chọn chế độ `Profile Chrome` và nhập mỗi dòng theo định dạng:

```text
Tên tài khoản|email|password|2FA
```

Ví dụ:

```text
Tài khoản 1|example@gmail.com|password123|JBSWY3DPEHPK3PXP
```

Sau khi xác nhận, tool sẽ tạo profile Chrome riêng trong thư mục `Profile-Chrome` và lưu thông tin vào `database/accounts.db`.

## Hướng dẫn sử dụng trên giao diện

1. Nhập OpenAI API key vào ô `API key ChatGPT`.
2. Bấm `Check key` để kiểm tra key.
3. Bấm `Import file` ở phần danh sách group và chọn file group.
4. Bấm `Import prompt` và chọn file prompt AI.
5. Bấm `Chọn nhiều profile` để thêm tài khoản Facebook.
6. Bấm `Chọn file` ở phần cấu hình bot tele và chọn file JSON Telegram.
7. Nhập `Chu kỳ`, tính bằng giờ. Tool sẽ tự tính delay giữa các group dựa trên số group trong file.
8. Nhập `Keywords Cấm`, cách nhau bằng dấu phẩy nếu có nhiều keyword.
9. Tích chọn các profile muốn chạy trong bảng tài khoản.
10. Bấm `Start` để bắt đầu quét.
11. Theo dõi cột `Tương tác group`, `Status`, `Số bài viết` và khung log bên phải.
12. Bấm `Stop` nếu cần dừng tiến trình đang chạy.

## Cách tool xử lý dữ liệu

1. Khởi động worker riêng cho mỗi profile được tích chọn.
2. Mở Chrome headless bằng thư mục profile tương ứng.
3. Kiểm tra trạng thái đăng nhập Facebook.
4. Nếu tài khoản bị đăng xuất, tool thử đăng nhập lại bằng email, password và mã 2FA.
5. Lấy cookie và token phục vụ gọi Facebook Graph API.
6. Đọc danh sách group từ file đã import.
7. Lấy bài viết mới trong từng group theo khoảng thời gian của chu kỳ.
8. Chuẩn hóa nội dung bài viết và bỏ bài quá dài.
9. Lọc bài theo keyword.
10. Nếu có OpenAI API key, gửi các bài còn lại lên AI để lọc theo prompt.
11. Tạo danh sách bài hợp lệ và không hợp lệ.
12. Ghi kết quả vào `data/posts.json`.
13. Xuất file Excel trong `data/exports/telegram`.
14. Gửi file Excel về Telegram nếu cấu hình hợp lệ.

## Kết quả đầu ra

Kết quả JSON:

```text
data/posts.json
```

File Excel gửi Telegram:

```text
data/exports/telegram
```

File log:

```text
main.log
```

Mỗi dòng bài viết trong Excel gồm link bài, thời gian tạo và nội dung bài. Báo cáo tổng hợp chu kỳ có thêm cột nhóm.

## Menu chuột phải trên bảng tài khoản

Trong bảng profile, có thể tích chọn một hoặc nhiều dòng, sau đó bấm chuột phải để:

- Copy đường dẫn Chrome profile.
- Copy proxy.
- Copy email, password và 2FA.
- Copy token.
- Copy cookie.
- Mở Chrome để xem hoặc đăng nhập profile thủ công.

Khi một profile đang được worker sử dụng, không nên mở Chrome thủ công cùng profile đó.

## Build file exe

Dự án có file `CONVERT.txt` chứa lệnh PyInstaller mẫu. Có thể cài PyInstaller:

```powershell
pip install pyinstaller
```

Sau đó điều chỉnh lại đường dẫn trong `CONVERT.txt` cho đúng với máy hiện tại và chạy lệnh build.

Lưu ý: trong lệnh mẫu có `splite3`, nếu build gặp lỗi hidden import thì cần sửa thành `sqlite3`.

## Cấu trúc thư mục

```text
controllers/        Điều phối luồng quét group
data/               Lưu kết quả JSON và file export
database/           Lưu database SQLite tài khoản
integrations/       Client Facebook, OpenAI, Telegram
models/             Dataclass dữ liệu task
resources/ui/       Giao diện PyQt5
services/           Xử lý nghiệp vụ
utils/              Hàm tiện ích
workers/            Worker chạy tiến trình quét
main.py             Điểm chạy chính của tool
app_config.py       Cấu hình Chrome, profile và API helper
```

## Lưu ý bảo mật và vận hành

- Không chia sẻ `tele.json`, OpenAI API key, cookie, token Facebook hoặc file database.
- Không commit `database/accounts.db`, `Profile-Chrome`, `main.log` và file export có dữ liệu thật.
- Sử dụng tài khoản, group và dữ liệu theo đúng quyền truy cập và điều khoản của nền tảng liên quan.
- Nếu Facebook yêu cầu checkpoint, hãy mở profile bằng menu chuột phải, xử lý thủ công rồi chạy lại.
- Nếu tool báo profile đang được sử dụng, đóng cửa sổ Chrome của profile đó trước khi bấm `Start`.

## Lỗi thường gặp

### Thiếu API key

Nhập API key vào ô `API key ChatGPT`, bấm `Check key`, sau đó mới bấm `Start`.

### File Telegram không đọc được

Kiểm tra file JSON có đúng hai trường `id_chat` và `token_tele`, đồng thời đảm bảo file được lưu bằng UTF-8.

### Không lấy được bài từ group

Kiểm tra group có tồn tại, tài khoản có quyền xem group, token Facebook còn hợp lệ và kết nối mạng ổn định.

### Profile Chrome đang mở

Đóng cửa sổ Chrome đang sử dụng profile đó, hoặc dừng worker đang chạy, sau đó thử lại.

### Không gửi được Telegram

Kiểm tra bot token, chat ID, quyền của bot trong group chat và kết nối mạng.
