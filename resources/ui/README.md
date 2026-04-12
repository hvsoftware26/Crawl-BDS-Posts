# README - Giao diện Facebook BĐS Crawl Bài Viết (PyQt5)

## 1. Mục đích của file `gui_fixed.py`

File `gui_fixed.py` là giao diện desktop viết bằng **PyQt5** cho tool crawl dữ liệu bài viết Facebook phục vụ mảng **Bất động sản**. Giao diện này tập trung vào các tác vụ chính:

- nhập và kiểm tra API key ChatGPT
- import danh sách group Facebook cần quét
- import prompt GPT
- import cấu hình bot Telegram
- nhập nhiều profile Chrome để chạy nhiều phiên làm việc
- cấu hình chu kỳ và delay vận hành
- quan sát danh sách tài khoản / tiến trình đang chạy
- theo dõi log ở khung console

Đây hiện là **file giao diện mô phỏng luồng làm việc**. Một số chức năng như `check API`, `start`, `stop`, `import file` mới đang ở mức giao diện hoặc xử lý mẫu, chưa phải logic crawl thật.

---

## 2. Cấu trúc tổng quan của file

File gồm 4 phần chính:

### 2.1. `APP_STYLE`
Khối stylesheet QSS để tạo giao diện hiện đại:
- màu nền
- bo góc
- màu nút
- màu bảng
- màu khung log
- chiều cao các label thống kê

### 2.2. Các class widget dùng lại
- `LabelBox`
- `PlaceholderPathEdit`
- `NumberBox`
- `DecimalBox`

Các class này giúp đồng bộ style, giảm lặp code và dễ bảo trì.

### 2.3. `MultiProfileDialog`
Popup dùng để dán nhiều profile Chrome.

### 2.4. `MainWindow`
Cửa sổ chính của tool, chứa toàn bộ layout, bảng dữ liệu, log và các hàm xử lý sự kiện.

---

## 3. Giải thích chi tiết từng class

## 3.1. Class `LabelBox(QLabel)`

### Mục đích
Tạo label dạng khối, dùng thống nhất cho các nhãn ở giao diện.

### Đặc điểm
- nhận vào nội dung text
- nhận thêm `object_name` để gán style QSS
- canh nội dung theo chiều dọc và trái
- đặt `QSizePolicy.Fixed` theo chiều cao để layout ổn định hơn

### Dùng ở đâu
- `API key ChatGPT`
- `Thêm danh sách group`
- `Dùng prompt GPT`
- `Cấu hình bot tele`
- `Số luồng`
- `Delay các luồng`
- `Chu kỳ`
- `Delay token - cookie`
- các ô thống kê như `Acc chạy thành công: 0`

---

## 3.2. Class `PlaceholderPathEdit(QLineEdit)`

### Mục đích
Tạo ô nhập liệu / hiển thị đường dẫn có chiều cao đồng bộ.

### Đặc điểm
- nhận placeholder
- chiều cao tối thiểu `42px`

### Dùng ở đâu
- ô nhập API key
- ô hiển thị file group
- ô hiển thị file prompt
- ô hiển thị thông tin profile
- ô hiển thị file cấu hình Telegram

---

## 3.3. Class `NumberBox(QSpinBox)`

### Mục đích
Tạo ô nhập số nguyên.

### Đặc điểm
- giới hạn min/max
- có giá trị mặc định
- hỗ trợ suffix như `phút`
- ẩn nút tăng giảm để giao diện gọn hơn
- chiều cao tối thiểu `42px`

### Dùng ở đâu
- `Số luồng`
- `Delay các luồng`
- `Delay token - cookie`

---

## 3.4. Class `DecimalBox(QDoubleSpinBox)`

### Mục đích
Tạo ô nhập số thực.

### Đặc điểm
- cho phép nhập số có phần thập phân
- hỗ trợ suffix như `tiếng`
- cấu hình số chữ số thập phân
- ẩn nút tăng giảm
- chiều cao tối thiểu `42px`

### Dùng ở đâu
- `Chu kỳ`

Ví dụ:
- `4.0 tiếng`
- `3.5 tiếng`

---

## 3.5. Class `MultiProfileDialog(QDialog)`

### Mục đích
Là popup để người dùng dán nhiều profile Chrome cùng lúc.

### Thành phần chính
- tiêu đề: `Chọn nhiều profile Chrome`
- nhãn `Định dạng dữ liệu`
- 2 radio button:
  - `Profile Chrome - Proxy`
  - `Profile Chrome`
- ô hướng dẫn `help_box`
- vùng nhập nhiều dòng `editor`
- nút `Hủy bỏ`
- nút `Xác nhận`

### Hai chế độ nhập

#### Chế độ 1: `Profile Chrome - Proxy`
Ví dụ định dạng:
```text
Tên Kênh 1-Tên Kênh 2|C:/Users/profile_1|127.0.0.1:8000:user:pass|example@gmail.com|Nohope1111@@
```

#### Chế độ 2: `Profile Chrome`
Ví dụ định dạng:
```text
Tên Kênh 1-Tên Kênh 2|C:/Users/profile_1|example@gmail.com|Nohope1111@@
```

### Hàm trong dialog

#### `build_ui(self)`
Dùng để dựng toàn bộ giao diện popup.

#### `update_help(self)`
Tự đổi nội dung hướng dẫn khi người dùng chuyển radio button.

---

## 4. Giải thích chi tiết giao diện chính `MainWindow`

## 4.1. Các thuộc tính khởi tạo

Trong `__init__`:

- `self.setWindowTitle("Facebook BĐS - Crawl Bài Viết")`
  - đặt tiêu đề cửa sổ
- `self.resize(1540, 930)`
  - kích thước mở ban đầu
- `self.setMinimumSize(1180, 720)`
  - giới hạn kích thước tối thiểu để tránh vỡ layout
- `self.profile_dialog = None`
  - biến dự phòng cho popup profile
- `self.group_count = 0`
  - lưu số lượng group sau khi import file
- `self.build_ui()`
  - dựng toàn bộ giao diện
- `self.populate_demo_table()`
  - nạp dữ liệu demo vào bảng

---

## 5. Toàn bộ label trên giao diện và ý nghĩa

## 5.1. Tiêu đề lớn

### `Facebook BĐS - Crawl dữ liệu bài viết`
Là tiêu đề chính của phần mềm.

---

## 5.2. Cụm label hàng trên cùng

### `API key ChatGPT`
Ô nhãn cho vùng nhập API key.

### `Thêm danh sách group`
Ô nhãn cho vùng import file danh sách group Facebook.

### `Dùng prompt GPT`
Ô nhãn cho vùng import file prompt GPT.

### `Cấu hình bot tele`
Ô nhãn cho vùng import file JSON cấu hình Telegram bot.

---

## 5.3. Cụm label cấu hình thông số

### `Số luồng`
Số lượng luồng chạy song song.

Hiện tại:
- là `read only`
- mặc định là `1`

### `Delay các luồng`
Khoảng nghỉ giữa các luồng.

### `Chu kỳ`
Thời gian của một chu kỳ quét, tính theo **tiếng**.

### `Delay token - cookie`
Khoảng thời gian delay cho token/cookie, tính theo **phút**.

---

## 5.4. Cụm label thống kê

### `Acc chạy thành công: 0`
Số tài khoản hoặc profile đã xử lý thành công.

### `Số bài viết lỗi: 0`
Số bài viết bị lỗi trong quá trình xử lý.

### `Số bài viết thành công: 0`
Số bài viết xử lý thành công.

### `Delay giữa các chu kì: 0 phút`
Thông số được tính tự động theo công thức:

```text
Delay giữa các chu kì = (Chu kỳ * 60) / Số lượng group
```

Ví dụ:
- Chu kỳ = `4.0 tiếng`
- Số lượng group = `67`
- Delay giữa các chu kì ≈ `3,6 phút`

---

## 5.5. Tiêu đề nhóm trái và phải

### `Danh sách tài khoản / tiến trình`
Tiêu đề khu vực bảng quản lý profile / tiến trình.

### `Console / Log chạy tool`
Tiêu đề khu vực hiển thị log.

---

## 6. Toàn bộ nút bấm và chức năng

## 6.1. `Check key`

### Mục đích
Kiểm tra API key ChatGPT đã nhập.

### Hàm gọi
`mock_check_api()`

### Hoạt động hiện tại
- nếu ô API key trống: báo cảnh báo
- nếu có dữ liệu: báo thành công giả lập

### Lưu ý
Đây mới là check giả lập ở giao diện, chưa gọi API thật.

---

## 6.2. `Import file`
Nút import danh sách group.

### Hàm gọi
`import_group_file()`

### Hoạt động hiện tại
- mở hộp chọn file
- hỗ trợ file: `.txt`, `.csv`, `.json`
- đếm số dòng không rỗng trong file
- lưu số lượng group vào `self.group_count`
- hiển thị đường dẫn và số lượng group
- tự cập nhật `Delay giữa các chu kì`
- ghi log import thành công

---

## 6.3. `Import prompt`

### Hàm gọi
`import_prompt_file()`

### Hoạt động hiện tại
- chọn file prompt
- hỗ trợ `.txt`, `.md`, `.json`
- hiển thị path vào ô prompt
- ghi log

---

## 6.4. `Chọn nhiều profile`

### Hàm gọi
`open_profile_dialog()`

### Hoạt động hiện tại
- mở popup `MultiProfileDialog`
- đọc dữ liệu nhiều dòng người dùng dán vào
- đếm số profile
- xác định chế độ đang chọn:
  - Profile Chrome - Proxy
  - Profile Chrome
- cập nhật ô thông tin profile
- ghi log

---

## 6.5. `Chọn file`

### Mục đích
Chọn file cấu hình Telegram bot.

### Hàm gọi
`import_tele_file()`

### Hoạt động hiện tại
- chỉ nhận file JSON
- hiển thị path file
- ghi log

### Ghi chú
Theo yêu cầu nghiệp vụ, file JSON này thường sẽ chứa:

```json
{
  "idchat": "...",
  "token": "..."
}
```

Tuy nhiên trong file hiện tại, chương trình mới chỉ chọn file và hiển thị path, chưa parse nội dung JSON.

---

## 6.6. `Start`

### Hàm gọi
Lambda:
```python
lambda: self.append_log("Bắt đầu chạy tool...")
```

### Hoạt động hiện tại
- chỉ ghi log `Bắt đầu chạy tool...`
- chưa có logic crawl thật

---

## 6.7. `Stop`

### Hàm gọi
Lambda:
```python
lambda: self.append_log("Đã dừng tool.")
```

### Hoạt động hiện tại
- chỉ ghi log `Đã dừng tool.`
- chưa có logic dừng worker thật

---

## 6.8. `Xóa dòng`

### Hàm gọi
`delete_selected_rows()`

### Hoạt động hiện tại
- duyệt từng dòng trong bảng
- tìm các dòng có checkbox được tick
- xóa các dòng đó khỏi bảng
- ghi log số dòng đã xóa

---

## 6.9. `Chọn tất cả`

### Hàm gọi
`toggle_all_rows()`

### Hoạt động hiện tại
- nếu chưa chọn hết: chọn tất cả
- nếu đã chọn hết: bỏ chọn tất cả

---

## 6.10. `Xóa log`

### Hàm gọi
`self.console.clear`

### Hoạt động hiện tại
- xóa toàn bộ nội dung trong khung log

---

## 6.11. Nút trong popup profile

### `Hủy bỏ`
- đóng popup
- không lưu dữ liệu

### `Xác nhận`
- đóng popup với trạng thái `Accepted`
- dữ liệu được đọc lại ở hàm `open_profile_dialog()`

---

## 7. Toàn bộ ô nhập liệu / ô hiển thị và chức năng

## 7.1. `self.api_edit`

### Loại
`QLineEdit`

### Chức năng
Cho người dùng nhập API key ChatGPT.

---

## 7.2. `self.group_path`

### Loại
`QLineEdit`

### Chức năng
Hiển thị:
- đường dẫn file group
- số lượng group sau khi import

### Ví dụ hiển thị
```text
D:/data/group.txt | Số lượng group: 67
```

---

## 7.3. `self.prompt_path`

### Loại
`QLineEdit`

### Chức năng
Hiển thị đường dẫn file prompt GPT đã chọn.

---

## 7.4. `self.profile_info`

### Loại
`QLineEdit`

### Chức năng
Hiển thị thông tin tổng hợp sau khi dán profile.

### Ví dụ hiển thị
```text
Đã thêm 8 profile | Chế độ: Profile Chrome - Proxy
```

---

## 7.5. `self.tele_path`

### Loại
`QLineEdit`

### Chức năng
Hiển thị đường dẫn file cấu hình bot Telegram.

---

## 7.6. `self.spn_threads`

### Loại
`QSpinBox`

### Chức năng
Hiển thị số luồng.

### Trạng thái
- `read only`
- `NoFocus`

---

## 7.7. `self.spn_delay_threads`

### Loại
`QSpinBox`

### Chức năng
Nhập delay giữa các luồng.

---

## 7.8. `self.spn_cycle_hours`

### Loại
`QDoubleSpinBox`

### Chức năng
Nhập số tiếng cho một chu kỳ quét.

### Ảnh hưởng
Khi thay đổi giá trị này, chương trình sẽ gọi lại:
- `update_delay_between_cycles()`

---

## 7.9. `self.spn_delay_cookie`

### Loại
`QSpinBox`

### Chức năng
Nhập delay token/cookie theo phút.

---

## 8. Bảng dữ liệu tài khoản / tiến trình

## 8.1. Tên widget
`self.table`

## 8.2. Số cột
7 cột

## 8.3. Tên từng cột

### Cột 1: `Quét`
- chứa checkbox để chọn dòng

### Cột 2: `Tên tài khoản`
- tên account hoặc profile đang chạy

### Cột 3: `Path chrome`
- tên hoặc đường dẫn profile Chrome

### Cột 4: `Proxy`
- thông tin proxy đang dùng
- có thể là `Không` nếu không dùng proxy

### Cột 5: `Tương tác group`
- nhóm Facebook mà account đang tương tác hoặc đang crawl

### Cột 6: `Status`
- trạng thái tiến trình
- ví dụ:
  - `Thành công - Đã gửi bài viết`
  - `Đang crawl dữ liệu`
  - `Thất bại - Không lấy được bài viết`
  - `Đang chờ trong queue`

### Cột 7: `Số bài viết`
- số lượng bài viết tương ứng với dòng đó

---

## 8.4. Cấu hình bảng hiện tại
- chỉ chọn theo hàng
- không cho sửa trực tiếp
- ẩn header dọc
- không hiển thị grid line
- không tự xuống dòng trong ô
- có dữ liệu mẫu khi khởi động

---

## 9. Khung log / console

## 9.1. Tên widget
`self.console`

## 9.2. Loại
`QTextEdit`

## 9.3. Chức năng
Hiển thị log hoạt động của tool.

## 9.4. Trạng thái
- chỉ đọc (`read only`)

## 9.5. Ví dụ log
- `Đã import danh sách group: 67 group`
- `Đã import prompt GPT`
- `Đã import cấu hình bot tele`
- `API key hợp lệ, kết nối kiểm tra thành công.`
- `Bắt đầu chạy tool...`
- `Đã dừng tool.`

---

## 10. Giải thích chi tiết từng hàm trong `MainWindow`

## 10.1. `build_ui(self)`

### Mục đích
Dựng toàn bộ giao diện chính.

### Công việc thực hiện
- tạo widget trung tâm
- dựng tiêu đề trang
- dựng nhóm điều khiển trên cùng
- dựng các ô nhập file, API, profile, tele
- dựng các control delay / chu kỳ
- dựng hàng thống kê
- dựng bảng tiến trình
- dựng khung console
- gắn signal cho các nút
- kết nối thay đổi chu kỳ với hàm tính delay tự động

Đây là hàm quan trọng nhất của giao diện.

---

## 10.2. `open_profile_dialog(self)`

### Mục đích
Mở popup nhập nhiều profile.

### Luồng xử lý
1. tạo dialog
2. hiển thị dialog
3. nếu người dùng bấm `Xác nhận`
4. lấy toàn bộ dòng đã nhập
5. loại bỏ dòng trống
6. đếm số profile
7. xác định mode đang chọn
8. cập nhật `self.profile_info`
9. ghi log

### Kết quả hiển thị ví dụ
```text
Đã thêm 5 profile | Chế độ: Profile Chrome
```

---

## 10.3. `import_group_file(self)`

### Mục đích
Import file group và tính lại delay giữa các chu kỳ.

### Luồng xử lý
1. mở hộp chọn file
2. nếu người dùng chọn file
3. gọi `count_non_empty_lines(path)` để đếm group
4. lưu vào `self.group_count`
5. cập nhật nội dung ô `group_path`
6. gọi `update_delay_between_cycles()`
7. ghi log

---

## 10.4. `import_prompt_file(self)`

### Mục đích
Import file prompt GPT.

### Luồng xử lý
1. mở hộp chọn file
2. nếu có path
3. hiển thị path vào `prompt_path`
4. ghi log

---

## 10.5. `import_tele_file(self)`

### Mục đích
Import file JSON cấu hình Telegram.

### Luồng xử lý
1. mở hộp chọn file `.json`
2. nếu có path
3. hiển thị path vào `tele_path`
4. ghi log

---

## 10.6. `mock_check_api(self)`

### Mục đích
Kiểm tra API key ở mức giả lập.

### Luồng xử lý
- nếu ô API rỗng:
  - hiện cảnh báo `Vui lòng nhập API key trước khi kiểm tra.`
- nếu có giá trị:
  - ghi log thành công
  - hiện message box thông báo thành công

### Lưu ý
Chưa gọi API OpenAI thật.

---

## 10.7. `count_non_empty_lines(self, path: str) -> int`

### Mục đích
Đếm số dòng có nội dung trong file.

### Dùng để làm gì
Hiện tại dùng để xác định số lượng group trong file group.

### Cách xử lý
- mở file bằng `utf-8`
- nếu lỗi mã hóa, thử lại bằng `utf-8-sig`
- bỏ qua dòng trống
- nếu có lỗi khác, trả về `0`

---

## 10.8. `format_minutes_value(self, value: float) -> str`

### Mục đích
Định dạng số phút hiển thị đẹp hơn.

### Quy tắc
- làm tròn 1 chữ số thập phân
- nếu là số nguyên, hiển thị như `5 phút`
- nếu là số thực, hiển thị như `5,4 phút`

### Ví dụ
- `5.0` -> `5 phút`
- `5.4` -> `5,4 phút`

---

## 10.9. `update_delay_between_cycles(self)`

### Mục đích
Tính và cập nhật nhãn `Delay giữa các chu kì`.

### Công thức
```text
Delay giữa các chu kì = (Chu kỳ * 60) / Số lượng group
```

### Luồng xử lý
- nếu chưa có group:
  - hiển thị `Delay giữa các chu kì: 0 phút`
- nếu đã có group:
  - tính số phút mỗi chu kỳ
  - gọi `format_minutes_value()`
  - cập nhật label

### Khi nào hàm này chạy
- sau khi import file group
- khi thay đổi giá trị `Chu kỳ`
- khi khởi tạo giao diện

---

## 10.10. `append_log(self, text: str)`

### Mục đích
Ghi thêm một dòng log vào console.

### Cách hoạt động
Dùng `self.console.append(text)`.

---

## 10.11. `toggle_all_rows(self)`

### Mục đích
Chọn tất cả hoặc bỏ chọn tất cả checkbox trong bảng.

### Cách hoạt động
- gọi `are_all_checked()` để biết trạng thái hiện tại
- nếu chưa chọn hết -> chọn tất cả
- nếu đã chọn hết -> bỏ tất cả

---

## 10.12. `are_all_checked(self) -> bool`

### Mục đích
Kiểm tra toàn bộ dòng trong bảng đã được tick hết chưa.

### Kết quả trả về
- `True` nếu tất cả checkbox đều được chọn
- `False` nếu còn ít nhất một dòng chưa chọn hoặc bảng rỗng

---

## 10.13. `delete_selected_rows(self)`

### Mục đích
Xóa các dòng được tick trong bảng.

### Luồng xử lý
1. duyệt tất cả dòng
2. gom index các dòng có checkbox được tick
3. xóa ngược từ dưới lên để tránh lệch index
4. ghi log số lượng dòng đã xóa

---

## 10.14. `populate_demo_table(self)`

### Mục đích
Nạp dữ liệu mẫu vào bảng khi mở giao diện.

### Dữ liệu mẫu gồm
- tài khoản
- profile chrome
- proxy
- group tương tác
- trạng thái
- số bài viết

### Ý nghĩa
Giúp xem trước bố cục bảng ngay khi mở phần mềm, kể cả khi chưa chạy logic thật.

---

## 11. Signal / sự kiện đã được kết nối

Trong `build_ui()` có các kết nối sau:

### `self.profile_btn.clicked.connect(self.open_profile_dialog)`
Bấm nút profile sẽ mở popup profile.

### `self.btn_import_group.clicked.connect(self.import_group_file)`
Bấm import file group.

### `self.btn_import_prompt.clicked.connect(self.import_prompt_file)`
Bấm import prompt.

### `self.btn_select_tele.clicked.connect(self.import_tele_file)`
Bấm chọn file Telegram.

### `self.btn_check_api.clicked.connect(self.mock_check_api)`
Bấm kiểm tra API.

### `self.btn_clear_log.clicked.connect(self.console.clear)`
Bấm xóa log.

### `self.btn_select_all.clicked.connect(self.toggle_all_rows)`
Bấm chọn tất cả dòng.

### `self.btn_delete_row.clicked.connect(self.delete_selected_rows)`
Bấm xóa dòng được tick.

### `self.btn_start.clicked.connect(lambda: self.append_log("Bắt đầu chạy tool..."))`
Bấm Start sẽ ghi log bắt đầu.

### `self.btn_stop.clicked.connect(lambda: self.append_log("Đã dừng tool."))`
Bấm Stop sẽ ghi log dừng.

### `self.spn_cycle_hours.valueChanged.connect(self.update_delay_between_cycles)`
Khi thay đổi `Chu kỳ`, delay giữa các chu kỳ sẽ được tính lại ngay.

---

## 12. Những gì file hiện tại đã làm được

- dựng giao diện desktop đẹp, bo góc, hiện đại
- layout khá ổn cho PC/laptop
- popup nhập nhiều profile
- import file group, prompt, tele
- đếm số lượng group từ file
- tự tính delay giữa các chu kỳ
- chọn / bỏ chọn tất cả các dòng
- xóa các dòng được tick
- ghi log ra console
- có bảng dữ liệu mẫu để test giao diện

---

## 13. Những gì file hiện tại CHƯA làm

Đây là phần rất quan trọng để tránh hiểu nhầm khi bàn giao.

### Chưa có crawl Facebook thật
Hiện file mới chỉ là giao diện.

### Chưa có worker / thread xử lý thật
`Số luồng`, `Delay các luồng`, `Start`, `Stop` mới đang là lớp UI.

### Chưa có check API thật
`mock_check_api()` chỉ kiểm tra có nhập key hay chưa.

### Chưa parse JSON Telegram
Hiện mới chỉ chọn file và hiển thị path.

### Chưa validate chi tiết dữ liệu profile
Popup profile hiện mới đếm số dòng, chưa tách và kiểm tra format từng profile.

### Chưa có cập nhật real-time thống kê
Các nhãn `Acc chạy thành công`, `Số bài viết lỗi`, `Số bài viết thành công` vẫn đang là giá trị mẫu.

---

## 14. Gợi ý nâng cấp tiếp theo

Nếu phát triển bản thương mại hoàn chỉnh, nên bổ sung:

### 14.1. Validate dữ liệu đầu vào
- API key rỗng / sai định dạng
- file Telegram thiếu `idchat` hoặc `token`
- profile sai số trường
- file group rỗng

### 14.2. Tách module
Nên tách thành:
- `gui.py`
- `workers.py`
- `services/facebook_service.py`
- `services/gpt_service.py`
- `services/telegram_service.py`
- `utils/file_utils.py`
- `models/task_models.py`

### 14.3. Thread / Queue thật
- dùng `QThread` hoặc `QRunnable`
- có signal update status từng dòng
- có signal update log
- có signal update các ô thống kê

### 14.4. Lưu cấu hình
- lưu API key
- lưu đường dẫn file gần nhất
- lưu chu kỳ, delay
- lưu kích thước cửa sổ

### 14.5. Parse file Telegram
Đọc nội dung JSON và kiểm tra đủ 2 trường:
- `idchat`
- `token`

### 14.6. Parse profile chi tiết
Tách từng trường:
- tên tài khoản
- path profile chrome
- proxy
- email
- password

### 14.7. Nạp dữ liệu thật vào bảng
Thay `populate_demo_table()` bằng dữ liệu runtime.

---

## 15. Cách chạy file

### Cài PyQt5
```bash
pip install PyQt5
```

### Chạy chương trình
```bash
python gui_fixed.py
```

---

## 16. Hàm `main()`

### Vai trò
Điểm vào của chương trình.

### Công việc
- tạo `QApplication`
- nạp stylesheet `APP_STYLE`
- đặt font `Segoe UI`
- tạo `MainWindow`
- hiển thị cửa sổ
- chạy event loop PyQt5

---

## 17. Tóm tắt ngắn

`gui.py` là file giao diện PyQt5 cho tool Facebook BĐS Crawl Bài Viết, đã có:
- giao diện chính
- popup profile
- import file
- bảng quản lý tiến trình
- log console
- tính toán delay giữa các chu kỳ

Nhưng chưa có phần xử lý nghiệp vụ crawl thật. File này phù hợp để làm nền giao diện trước khi nối với worker, service và logic sản phẩm thật.
