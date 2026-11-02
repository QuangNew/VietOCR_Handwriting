# VietOCR Assistant: điện thoại và giao thức BLE

**02/11/2026, OV5640 AF:** UUID/BLE, cấu hình Wi-Fi và lệnh chụp giữ như cũ;
JPEG ảnh chụp nay đủ **2592×1944**. Preview mặc định **640×480**, trần gửi 30 FPS;
mục tiêu ít nhất 15 FPS phụ thuộc LAN và cảnh chụp.
`CAM FOCUS` yêu cầu lấy nét trong task camera; `CAM AF STATUS` đọc trạng thái,
không đọc I²C trong callback. `CAM CONFIG` trả schema 2 / sensor OV5640;
`CAM SET <key> <integer>` áp dụng RAM, `CAM SAVE` ghi profile OV5640 vào NVS.
Xem [OV5640.md](OV5640.md). Chưa cập nhật app trong lượt làm IoT này.
Preview nhanh: POST HTTP :80 `/stream/udp` với token BLE và cổng nhận UDP;
bo gửi các fragment `VOJ1` từ UDP :82, mỗi JPEG có CRC32. Không gửi JPEG qua
BLE và không dùng UDP cho ảnh chụp OCR. Chi tiết header/lease trong OV5640.md.

Từ 27/10/2026: BLE còn dùng cho cấu hình Wi-Fi và điều khiển camera. Xem trước
và ảnh chụp gốc 2048×1536 đi qua HTTP LAN; TFT chỉ hiển thị trợ lý. Danh sách
lệnh `WIFI ...`, token phiên và endpoint ở [CAMERA.md](CAMERA.md#wi-fi-cấu-hình-qua-ble).

Từ **2.3.1-blewifi**, ESP32 tự nhớ mạng đã kết nối thành công trong flash/NVS và
tìm/kết nối ngay mỗi lần BLE kết nối, đồng thời thử lại khi bật nguồn/mất mạng.
`WIFI SAVED` đọc trạng thái mạng nhớ;
`WIFI FORGET` xóa. Luồng NUS/UUID cũ giữ nguyên, app Android 1.6.1 dùng được.
Wi-Fi/NVS/HTTP dùng task riêng; trả lệnh NUS từ vòng BLE chính, bỏ reply
thuộc phiên đã ngắt. Không gửi SSID/password qua HTTP hoặc ghi password vào log.

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
| Image (mở rộng VietOCR) | `6e400004-b5a3-f393-e0a9-e50e24dcca9e` | Read + Write: chọn ID/offset rồi đọc chunk JPEG |

Giao thức camera `CAM OPEN/SHOT/META/RELEASE`, CRC32, MTU và cấu hình dây mới
được mô tả trong [CAMERA.md](CAMERA.md). `RECEIVED` chấp nhận số ảnh
**1..2147483647**, không còn giới hạn 10 ảnh. RX/TX cho các lệnh trạng thái giữ
nguyên để app còn làm việc với firmware cũ; các lệnh camera chưa hỗ trợ trả ERR.

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

BLE truyền trạng thái và cấu hình Wi-Fi; stream/ảnh JPEG dùng Wi-Fi LAN.
Từ **2.6.0-config**, bảng **Cấu hình camera** của desktop/Android dùng
`GET/POST /camera/config` trên HTTP :80 với token lấy từ phiên BLE. Các giá
trị được kiểm tra trước khi đổi, áp dụng trong task camera và có tùy chọn
lưu NVS qua mất điện. `revision` / `applied_revision` / `saved` phân biệt đã
nhận yêu cầu, đã áp dụng và đã lưu flash. Xem [API và giới hạn](CAMERA.md#cấu-hình-camera-trong-app).
Từ 2.5.0: `CAM ORIENT <mirror:0/1> <flip:0/1>` chọn lật ngang/dọc cho cả
preview và ảnh chụp; `CAM ORIENT` đọc lựa chọn hiện tại. Thay đổi cảm biến và
ghi NVS thuộc task camera, không chạy trong callback BLE. `OK CAM ORIENT`
xác nhận yêu cầu đã được nhận; chỉ frame mới sau khi áp dụng được phát ra.
Preview VGA 640×480/QS16 giữ cửa sổ 4:3; ảnh chụp QXGA 2048×1536/QS4.
Không giới hạn stream ở 10 FPS nữa; tốc độ thực xem trên desktop hoặc log
`CAMERA CAPTURE fps=...` / `WIFI MJPEG fps=...`.
Model chạy offline trên điện thoại/máy tính. Các lệnh `CAM OPEN`, `CAM STATUS`,
`CAM CLOSE`, `CAM SHOT`, `CAM META`, `CAM RELEASE` và characteristic ảnh được
mô tả trong [CAMERA.md](CAMERA.md). `CAM STATUS READY` xác nhận camera đã có
JPEG preview; app chỉ báo sẵn sàng xem khi thực sự nhận/hiển thị được khung.
Firmware 2.2.0 stream qua HTTP :81, ảnh chụp qua :80; TFT vẫn hiển thị trợ lý.

Firmware đề nghị MTU 517, interval 15–30 ms; central quyết định thông số thực.
Công cụ BLE ảnh cũ hỗ trợ long read 480 byte/lượt với fallback theo MTU.
Giao diện desktop/Android hiện tại yêu cầu Wi-Fi cho ảnh; không âm thầm chuyển
sang BLE chậm khi Wi-Fi lỗi. Chỉ một app giữ kết nối BLE tại một thời điểm.

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
