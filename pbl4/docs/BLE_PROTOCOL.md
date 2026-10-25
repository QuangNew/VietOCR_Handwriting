# VietOCR Assistant: điện thoại và giao thức BLE

Firmware ESP32-S3 đã hỗ trợ BLE. App Python hiện là bản desktop, có quét và kết
nối BLE bằng Bleak. Bản [Flutter mobile](../../Mobile/README.md) chạy OCR offline trên
Android và dùng cùng giao thức. Có thể thử riêng phần cứng bằng
[nRF Connect for Mobile của Nordic](https://www.nordicsemi.com/Products/Development-tools/nRF-Connect-for-mobile),
công cụ quét, kết nối, ghi characteristic và đọc notification.

## Thử bằng điện thoại

1. Nạp firmware mới từ `pbl4`, cấp nguồn ESP32. TFT hiện `BLE` / `Cho ket noi`.
   Ngắt kết nối app desktop nếu đang dùng.
2. Cài **nRF Connect for Mobile** trên điện thoại, bật Bluetooth và cho phép app
   truy cập Bluetooth/Thiết bị ở gần khi được hỏi. Với Android cũ, cấp quyền vị trí
   cho thao tác quét nếu app yêu cầu.
3. Mở nRF Connect → **Scan** → tìm **VietOCR-Assistant** → **Connect**.
   Kết nối trong app; firmware hiện không yêu cầu ghép đôi/PIN trong cài đặt máy.
4. Mở dịch vụ **Nordic UART Service** có UUID `6e400001-...`.
   Bật **Notify** trên TX `6e400003-...` để nhận phản hồi.
5. Chọn **Write** trên RX `6e400002-...`. Chọn định dạng **HEX**, nhập
   **`44454D4F0A`** rồi gửi: đây là `DEMO` kèm byte xuống dòng `0A`.
   ESP32 trả `OK DEMO` và chạy một vòng thức → nhận 3 ảnh → xử lý → hoàn tất → ngủ
   khoảng 14,7 giây.
6. Thử các lệnh trong bảng. Mỗi lệnh phải kết thúc bằng byte `0A` (LF).
   Nếu nhập ở chế độ text, phải bật tùy chọn thêm LF nếu công cụ có hỗ trợ;
   gõ hai ký tự `\` và `n` không thay cho byte xuống dòng. Dùng HEX để tránh nhầm.
7. Gửi `SLEEP` rồi **Disconnect** khi xong. Nếu không gửi lệnh trong 60 giây,
   ESP32 tự ngắt kết nối và ngủ; kết nối lại để tiếp tục.

| Mục đích | Lệnh | Dữ liệu HEX trên RX |
| --- | --- | --- |
| Chạy toàn bộ biểu cảm | `DEMO` | `44454D4F0A` |
| Thức dậy | `WAKE` | `57414B450A` |
| Thử còi | `BEEP` | `424545500A` |
| Giữ kết nối | `PING` | `50494E470A` |
| Ngủ | `SLEEP` | `534C4545500A` |

BLE kết nối thành công mới chỉ mở đường truyền; lệnh `WAKE` hoặc `DEMO` làm trợ lý
thức dậy. App desktop tự gửi `WAKE` sau khi kết nối.

## Dịch vụ GATT

Các UUID theo [Nordic UART Service](https://nrfconnectdocs.nordicsemi.com/ncs/latest/zephyr/doxygen/html/nus_8h.html).
Chiều RX/TX được đặt theo ESP32 (peripheral), điện thoại/máy tính là central.

| Thành phần | UUID | Thuộc tính / chiều |
| --- | --- | --- |
| Service | `6e400001-b5a3-f393-e0a9-e50e24dcca9e` | NUS |
| RX | `6e400002-b5a3-f393-e0a9-e50e24dcca9e` | Write, Write Without Response: app → ESP32 |
| TX | `6e400003-b5a3-f393-e0a9-e50e24dcca9e` | Notify: ESP32 → app |

Tên quảng bá mặc định là `VietOCR-Assistant`, đổi tại
`include/assistant_config.h`. Tên nằm trong scan response, UUID dịch vụ nằm trong
advertisement. Client nên quét theo service UUID, hiển thị tên thiết bị để người
dùng chọn, lưu định danh thiết bị được hệ điều hành trả về.

## Quy tắc truyền

- Bật Notify TX trước khi gửi lệnh. Không có dòng chào BLE tự động.
- Gửi một lệnh ASCII kết thúc LF hoặc CRLF vào RX, tối đa 79 ký tự trước LF.
  Một dòng có thể chia qua nhiều lần Write; một Write có thể chứa nhiều dòng.
- Client nên dùng **Write with response**, chia dữ liệu thành gói tối đa **20 byte**
  để hoạt động cả khi ATT MTU mặc định là 23. Firmware trả notification tối đa
  20 byte mỗi gói, cách nhau ít nhất 10ms; một dòng có thể nằm trong nhiều gói.
- Ghép các byte TX thành buffer và tách theo LF; bỏ CR ngay trước LF.
  Một notification không tương đương một phản hồi hoàn chỉnh.
- Gửi tuần tự và chờ phản hồi từng lệnh. `PING` → `PONG`; lệnh điều khiển →
  `OK ...`; lỗi → `ERR ...`. Đóng/kết nối lại nếu timeout hoặc sai giao thức để
  tránh dùng phản hồi cũ cho lệnh tiếp theo. `HELP` trả bốn dòng; `STATUS` trả một
  dòng `STATUS {json}`. Xem đầy đủ lệnh trong [README](../README.md#lệnh-điều-khiển).
- Với firmware cũ, lỗi `ERR INVALID_COMMAND: send HELP` có mã `INVALID_COMMAND`;
  phần sau dấu `:` là mô tả. App mới giữ kết nối nếu chỉ THEME chưa được hỗ trợ.
  Các lỗi khác và timeout vẫn được ghi log và phục hồi kết nối.
- Gửi `PING` khoảng **4 giây/lần**, kể cả lúc chưa có ảnh hay khi đang OCR.
  Timeout phiên BLE là **60 giây** kể từ lúc kết nối/lệnh hoàn chỉnh gần nhất.
- Ngắt BLE, timeout hoặc tràn hàng đợi → ESP32 dừng xử lý/âm báo, về ngủ và
  quảng bá lại. Tràn hàng đợi không được xử lý như lệnh bị cắt ngắn.
- Một app điều khiển tại một thời điểm. Firmware hiện là bản mẫu kết nối mở,
  chưa bật xác thực/ghép đôi BLE.

Ví dụ phiên app (mỗi dòng dưới đây phải gửi kèm LF và chờ phản hồi):

```text
PING          -> PONG
WAKE          -> OK WAKE
THEME DARK    -> OK THEME DARK
RECEIVED 3    -> OK RECEIVED 3
PROCESS       -> OK PROCESS
PROGRESS 40   -> OK PROGRESS 40
PROGRESS 100  -> OK PROGRESS 100
DONE          -> OK DONE
SLEEP         -> OK SLEEP
```

## Luồng tích hợp app mobile

1. Quét BLE theo service UUID, chọn trợ lý, kết nối GATT và đăng ký Notify TX.
2. Kiểm tra `PING`/`PONG`, gửi `WAKE`, rồi `THEME DARK` hoặc `THEME LIGHT` theo
   lựa chọn app; duy trì heartbeat trên luồng không bị OCR chặn.
3. App nhận ảnh → `RECEIVED n`; bắt đầu OCR → `PROCESS`; tiến độ → `PROGRESS n`;
   thành công → `DONE`; lỗi → `ERROR`.
4. Rời phiên app → gửi `SLEEP`, ngắt BLE. Hệ điều hành có thể đóng app đột ngột;
   khi đó timeout/ngắt kết nối trên ESP32 đưa trợ lý về ngủ.
5. Khi kết nối lại, gửi trạng thái hiện tại, không phát lại mọi sự kiện cũ.
   Nếu đang OCR: `WAKE`, `THEME ...`, `RECEIVED n`, `PROCESS`, `PROGRESS n` nếu có.

`THEME DARK` / `THEME LIGHT` chỉ đổi bảng màu TFT, không đặt lại trạng thái,
tiến độ, demo hoặc âm báo. App gửi lại khi người dùng đổi nền, kể cả đang xử lý.
`STATUS` bổ sung trường `"theme":"dark"` hoặc `"theme":"light"`. Firmware cũ trả
`ERR INVALID_COMMAND`: app bỏ qua tính năng theme trong kết nối đó và nhắc nạp
firmware mới; vẫn giữ kết nối cho các lệnh còn lại. Một phản hồi ERR đầy đủ không
phải timeout và không cần hủy đường truyền chỉ vì lệnh THEME chưa được hỗ trợ.

Android 12+ cần khai báo và xin quyền runtime `BLUETOOTH_SCAN` /
`BLUETOOTH_CONNECT`; quyền quét ở Android cũ khác nhau theo phiên bản.
Tham khảo [quyền Bluetooth Android](https://developer.android.com/develop/connectivity/bluetooth/bt-permissions).
App Flutter Android dùng cùng luồng trạng thái và UUID với bản desktop.

BLE ở đây truyền trạng thái, không chuyển ảnh/model sang ESP32. Flutter mobile
chạy encoder/decoder ONNX trực tiếp trên điện thoại; bản desktop chạy `AI.py`
và PyTorch trên máy tính. Không cần Wi-Fi cho kết nối trợ lý hoặc OCR mobile.

## Nhạc và âm báo

`MUSIC LIST` trả một dòng danh sách tên bài. `MUSIC <tên>` trả ngay
`OK MUSIC <TÊN>` rồi phát nền; `MUSIC STOP` trả `OK MUSIC STOP` và chỉ tắt nhạc.
Các tên có sẵn: WAKE, RECEIVED, PROCESS, DONE, ERROR, SLEEP, TEST, SCALE, TWINKLE.
Lệnh `BEEP` vẫn trả `OK BEEP`, nay phát cue TEST để app cũ tiếp tục dùng được.

PROGRESS, THEME và PING không phát lại/đặt lại bài. Lệnh đổi trạng thái thay bài
đang chạy bằng cue mới. MUTE ON, STOP và ngắt BLE dừng nhạc ngay; MUTE OFF không
phát lại nhạc đã dừng. Khi đang DEMO, trạng thái demo kế tiếp có thể phát cue
mới sau MUSIC STOP; dùng MUTE ON nếu muốn tắt toàn bộ âm.

`STATUS` thêm `"audio":"active"` hoặc `"passive"`, `"music":true/false`, và
`"note_hz":n`. `note_hz` là tần số nốt player yêu cầu, bằng 0 trong khoảng nghỉ;
TMB12A05 active vẫn có cao độ cố định. Để nghe đúng nốt, dùng còi passive và
cấu hình chế độ PWM theo [hướng dẫn VietMusic](../lib/VietMusic/README.md).
