# Camera → Wi-Fi stream/ảnh chụp → OCR tuần tự

**Hiện tại: OV5640 AF, 3.0.0-ov5640 (02/11/2026).** Xem
[hướng dẫn OV5640 và kiểm tra thực tế](OV5640.md). Preview giảm độ phân giải,
ảnh chụp đầy đủ 2592×1944; schema camera mới là **2**, sensor **OV5640**.
Phần app desktop/Android được để lại cho lượt sau theo yêu cầu người dùng.
Build OV3660/legacy cũ đã dọn; các số đo và firmware được nói tới bên dưới
là lịch sử, không còn binary cũ trong `dist`.

## Lịch sử OV3660

**Firmware camera hiện tại: 2.6.0-config (29/10/2026). Android: 1.8.0+13.**
Người dùng chọn ưu tiên preview mượt và giữ ảnh chụp 3 MP. Preview mặc định
**640×480/QS16**; chụp **2048×1536/QS4**. Cả hai dùng cùng cửa sổ cảm biến
4:3, không cắt góc nhìn theo tỷ lệ màn hình. Sensor được chuyển mode trong
task camera, bỏ hai frame đầu và từ chối JPEG sai kích thước/timestamp.
Hai framebuffer giữ camera tiếp tục nhận khi đang sao chép frame; bỏ giới
hạn gửi 100 ms/khung (10 FPS). Desktop đọc frame mỗi 20 ms và hiện FPS đo được.
Serial tách `CAMERA CAPTURE fps=...` với `WIFI MJPEG fps=... avg_send_ms=...`
để phân biệt tốc độ cảm biến và đường LAN. Wi-Fi vẫn dùng MIN_MODEM cho BLE.

**Lật ngang / Lật dọc** trong cửa sổ camera đổi thanh ghi cảm biến nên cả
preview và JPEG lưu về có cùng hướng. Chọn cả hai tương đương xoay 180°.
Desktop đọc hướng ảnh từ bo khi mở camera. ESP32 lưu cùng cấu hình trong NVS
`vietocr-camera/profile`, đọc lại sau mất điện và nhận lại hướng từ key
`orientation` của bản cũ nếu chưa có profile. Không sửa ảnh đã chụp trước đó.

**Bản 2.6.0 chỉ sửa mã/build, chưa nạp theo yêu cầu người dùng khi COM8 không
còn thuận tiện. Chưa đo FPS thực hoặc kiểm chứng chuyển mode/lật trên bo;
không khẳng định đã đạt 15–30 FPS.** Đã build APK Android cho tính năng cấu
hình camera; chưa cài/chạy trên điện thoại. Kết quả phần cứng 2.4.4 bên dưới
không phải bằng chứng kiểm thử cảm biến với cấu hình mới.

## Cấu hình camera trong app

Kết nối BLE và Wi-Fi LAN như trước. Desktop mở **Xem camera → Cấu hình
camera**; Android mở trang OV3660 rồi bấm biểu tượng thanh trượt. Các ô được
đọc từ ESP32. Chỉnh xong bấm **Áp dụng**; app dừng stream, gửi toàn bộ cấu
hình, đợi xác nhận và mở lại preview. **Tải lại** đọc từ bo; **Mặc định** mới
chỉ chọn giá trị, cần bấm Áp dụng. Preset chỉ thay preview, không đổi chất
lượng ảnh chụp 3 MP hoặc hướng ảnh:

| Preset | Preview | JPEG QS | Trần FPS |
| --- | --- | --- | --- |
| Mượt | 320×240 | 24 | 30 |
| Cân bằng / mặc định | 640×480 | 16 | 30 |
| Chi tiết | 1024×768 | 10 | 15 |

Có thể tự chọn preview 800×600, 1600×1200 hoặc 2048×1536. Mọi mode giữ tỷ lệ
4:3; ảnh chụp vẫn 2048×1536, mặc định QS4. FPS là trần gửi, không phải tốc
độ bảo đảm. QS nhỏ hơn tăng chi tiết và dung lượng. Chặn QS0–3 vì QS0/1 không
có JPEG hoàn chỉnh và QS2 từng ngắt trên bo này; đây là giới hạn đã chọn cho
bản ứng dụng, không phải giới hạn chung của mọi OV3660.

Các nhóm chỉnh khác: sáng/tương phản/sắc nét −3..3, bão hòa −4..4, giảm nhiễu
0..8, WB Auto/Nắng/Mây/Đèn, hiệu ứng, AE tự động và bù −5..5 hoặc phơi sáng
thủ công 0..1536, AGC tự động hoặc gain 0..64, lật ngang/dọc, hiệu chỉnh ống
kính. Giá trị phơi sáng thực còn bị driver giới hạn theo thời gian khung của
mode đang chạy. Tắt tự động mới chỉnh được phơi sáng/gain thủ công.

**Nhớ cấu hình trên ESP32** mặc định bật: task camera lưu một record NVS
`vietocr-camera/profile` (88 byte, version + CRC32), đọc lại để xác nhận và
chỉ báo đã lưu khi đúng record. Ngắt BLE, reset hoặc tắt nguồn không mất
profile. Tắt tùy chọn này chỉ áp dụng RAM; lần bật nguồn tiếp theo dùng
profile đã lưu trước đó. Cấu hình Wi-Fi ở namespace riêng, không bị xóa.
Không ghi flash cho mỗi khung hình hoặc mỗi lần kéo thanh chỉnh.

API có xác thực bằng Bearer token lấy qua phiên BLE hiện tại:

* `GET http://<ip>/camera/config`: schema, sensor, firmware, settings, defaults,
  revision, applied_revision, saved và error.
* `POST /camera/config`, JSON `{"settings":{"brightness":1},"persist":true}`:
  chấp nhận patch hợp lệ, trả **202** cùng trạng thái; không có thay đổi nếu
  bất kỳ field nào sai. App gửi profile đầy đủ. **400** cho giá trị/field sai,
  **409** nếu ảnh trước chưa được release; giới hạn body 2 KiB.
* Đọc lại GET đến khi `applied_revision == revision`, `error` rỗng và, nếu
  yêu cầu lưu, `saved == true`. ACK HTTP chưa đồng nghĩa cảm biến/NVS đã xong.

Sensor chỉ đổi thanh ghi trong task camera; bỏ hai frame đầu, kiểm timestamp
và kích thước JPEG trước khi phát lại. NVS không nằm trong callback BLE.
Ảnh đã chụp và kết quả OCR không bị đổi khi chỉnh thông số. Model không đổi.

Tham khảo thiết kế nhóm điều khiển/API của
[easytarget/esp32-cam-webserver](https://github.com/easytarget/esp32-cam-webserver),
commit `19eec9c143a6181f8970842bb8f1e50cfbf8191e`, và
[API.md](https://github.com/easytarget/esp32-cam-webserver/blob/19eec9c143a6181f8970842bb8f1e50cfbf8191e/API.md).
Repo tham khảo dùng LGPL-2.1 và tự cảnh báo core cũ; không sao chép nguồn
repo đó, không thay firmware hiện tại bằng webserver cũ. Phần mới viết độc
lập bằng `sensor_t` của driver Espressif đang có trong dự án.

## Lịch sử kiểm chứng phần cứng

Lịch sử kiểm chứng 2.4.4 (chỉ áp dụng preview native 3 MP):
Đã nạp trực tiếp COM8, nhận và giải mã JPEG thật trên máy tính. Thử cùng
firmware/driver và giữ nguyên QXGA cho kết quả: QS0 và QS1 không có JPEG hoàn
chỉnh; QS2 chỉ có vài ảnh rồi dừng; QS4 stream liên tục 125 giây, nhận 28 JPEG
2048×1536, không lỗi giải mã hay phục hồi driver. Khung đầu khoảng 3,4 giây;
ảnh trong cảnh thử khoảng 279–385 KB, tốc độ LAN đo được khoảng 0,22 FPS.
Đã bỏ giả định “cứ đặt QS=0 là chất lượng tối đa dùng được”. Không giảm độ
phân giải, không ghép thêm marker để che ảnh hỏng. `/health` trả QS thực.
[Kết quả kiểm chứng](camera-validation.json). Chỉ sửa/nạp firmware camera;
không build Android/iOS, không cài dependency mới, giữ nguyên Wi-Fi trong NVS.

Lịch sử chẩn đoán 2.4.2–2.4.3 (chưa giải quyết hết lỗi):
Log 2.4.2 nhận VSYNC nhưng chỉ có 1 EOF rồi 0 EOF sau khởi tạo lại, không
tràn framebuffer. Đã sửa lỗi quản lý kênh DMA trong HAL cũ: dùng bộ cấp kênh
của ESP-IDF và giữ clock, thay cách đọc thanh ghi để tự chọn kênh. Cấu hình
RX được khôi phục ở mỗi đầu frame; ISR được gỡ trước khi giải phóng queue.
Serial mới có `CAMERA GDMA owned RX=...`; nếu còn timeout sẽ có trạng thái
thanh ghi GDMA và `CAMERA SENSOR ... JPEG_BYTES=...` để phân biệt phía cảm
biến với phía nhận dữ liệu. Build/test host đạt không thay cho kiểm tra ảnh
trên bo thật; chưa xác nhận nguyên nhân duy nhất hoặc hết lỗi trên phần cứng.

App tự hiện Wi-Fi đang kết nối / đã kết nối, SSID, IP và mạng đã lưu ngay sau
BLE rồi cập nhật mỗi 5 giây. Mở hộp Wi-Fi chỉ đọc trạng thái; quét mạng là
thao tác riêng. Không cần nhập lại mật khẩu khi ESP32 đã tự vào mạng. Kiểm tra
LAN kiểm tra HTTP độc lập với trạng thái kết nối Wi-Fi và cảm biến.

Log người dùng trên **2.4.1-native** đã xác nhận tự kết nối IP `192.168.100.173`,
HTTP :80 và MJPEG :81 mở, nhưng camera không có JPEG sau một lần khởi tạo lại.
Đó là lỗi lấy frame, không phải bằng chứng ESP32 chưa vào Wi-Fi. 2.4.2 tăng
SRAM ring DMA lên 32 KiB, gửi sự kiện EOF mỗi 4 KiB, chuyển task nhận frame
sang core 1; bỏ đệ quy có thể trừ âm timeout và không đưa frame tràn bộ đệm
vào queue. Serial và `/health` giữ bộ đếm lỗi để xác định phần chưa hoạt động.
`CAMERA INIT OK` không tuyên bố camera đã có ảnh; cần `CAMERA FIRST JPEG`.
Chưa kiểm chứng sửa driver 2.4.2 trên bo thật; không khẳng định đã hết lỗi camera.

Ảnh chụp dùng QXGA **2048×1536**, JPEG **QS=4**; preview VGA **640×480/QS16**
giữ góc nhìn 4:3 và hướng ảnh đã chọn, AE/AWB tự động.
3 MP là độ phân giải tối đa OV3660; QS thấp hơn cho JPEG chất lượng cao hơn
([driver Espressif](https://components.espressif.com/components/espressif/esp32-camera/versions/2.0.7)).
Độ sáng, tương phản, bão hòa giữ trung tính; phơi sáng/cân bằng trắng/gain tự
động. Đẩy gain hoặc phơi sáng lên cực đại sẽ làm nhiễu/cháy chữ, không tăng độ nét.

Arduino core cũ cấp JPEG `width*height/5`, tức **629.145 byte** ở 3 MP.
JPEG QS0 có thể vượt mức đó và bị driver loại bỏ trước khi app nhận được.
Thư viện [NativeCameraHal](../lib/NativeCameraHal/README.md) dùng nguồn Espressif
v2.0.4, cấp **2 MiB/buffer** và dùng hai frame buffer; không sửa SDK cài chung.
Các bản sao cũ được giải phóng trước khi tạo bản mới để giới hạn bộ nhớ.
Timestamp cảm biến được kiểm tra để bỏ frame từ trước lúc mở/chụp; mở lại
camera không hiển thị ảnh bị lưu trong buffer của phiên cũ.
Ảnh vượt 2 MiB bị từ chối, không nhận ảnh JPEG cắt cụt hoặc âm thầm giảm nét.
Camera có thể khởi tạo lại driver một lần khi thiếu khung sau reconnect Wi-Fi;
không reset bo. Timeout stream cũ 8 giây được thay bằng chờ có giới hạn,
và app desktop đọc `camera_status` từ `/health` khi lỗi.

Desktop: kéo cạnh hoặc phóng to cửa sổ camera; xem ảnh vừa chụp **3 giây** hoặc
**Bỏ qua · Chụp tiếp**. Chỉ sau bước này ảnh vào queue và preview tự mở lại.
Đóng cửa sổ khi đang xem ảnh vẫn đưa ảnh đã nhận vào queue. Bảng tiến trình
ở góc dưới bên phải có thể thu gọn và không ngắt cửa sổ chụp.
Bấm **Ảnh gốc** để mở trình xem zoom/pan/crop; **Lưu ảnh gốc** xuất đúng JPEG
đã nhận, không nén lại. Crop sửa ảnh dùng OCR, vẫn giữ ảnh gốc để khôi phục.
Android có trang camera lớn/pinch zoom, cùng quy trình 3 giây; tải ảnh bằng
trình chọn nơi lưu của Android, không xin quyền toàn bộ bộ nhớ. Crop trên
Android tạo một ảnh vùng mới trong hàng đợi và giữ nguyên ảnh gốc.

Log người dùng đã xác nhận bản 2.4.3 vẫn không có JPEG. Test host có luồng HTTP trả
khung đầu sau hơn 8 giây, JPEG lớn hơn 128 KiB, timer/Skip/Close và xuất/crop
ảnh native. Không cam kết 60 FPS hay 10 FPS cho stream 3 MP; xem số đo thực ở đầu trang.

Firmware stream MJPEG từ ESP32-S3 lên Android/desktop qua Wi-Fi, rồi chuyển
**ảnh chụp 3 MP** qua Wi-Fi vào OCR. TFT ILI9341 luôn hiển thị trợ lý; BLE dùng
để điều khiển/cấu hình mạng. Model vẫn chạy
offline trên thiết bị nhận. Desktop chỉ có nguồn OV3660; Android có thêm
camera điện thoại/thư viện ảnh. Hai app không còn giới hạn 10 ảnh.

## Board và dây nối

**N16R8 là thông số 16 MB Flash / 8 MB PSRAM, không xác định duy nhất pinout.**
Profile `esp32-s3-cam-ov3660` dùng pinout dưới đây, **đã được người dùng kiểm tra
trên bo thật ngày 26/10/2026**: PID `0x3660` (OV3660), ba JPEG 320×240 giải mã
đạt với `PWDN=-1`, và ba JPEG đạt khi thử `PWDN=38`.
Chốt dùng **PWDN=-1, RESET=-1, XCLK 20 MHz**. [Log kiểm tra](camera-probe-2026-10-26.txt).

| Camera | GPIO |
| --- | --- |
| D0 / D1 / D2 / D3 | 11 / 9 / 8 / 10 |
| D4 / D5 / D6 / D7 | 12 / 18 / 17 / 16 |
| XCLK / PCLK | 15 / 13 |
| VSYNC / HREF | 6 / 7 |
| SDA / SCL | 4 / 5 |
| PWDN / RESET | -1 / -1 |

Nguồn pinout: [ví dụ chính thức Espressif, BOARD_ESP32S3_GOOUUU và WROOM](https://github.com/espressif/esp32-camera/blob/master/examples/camera_example/main/camera_pinout.h).
Bản WROOM trong ví dụ dùng PWDN **38**, GOOUUU dùng **-1**. Cả hai chạy được
trên lượt chẩn đoán của người dùng; chọn -1 vì camera hoạt động mà không cần
driver điều khiển PWDN. Kết quả không chứng minh dây PWDN vật lý có nối GPIO38
hay không. Lượt chẩn đoán ban đầu chỉ kiểm tra camera ở 320×240; lượt ngày
29/10 đã kiểm tra firmware trợ lý và JPEG native 2048×1536 qua LAN.

Camera chiếm GPIO 5 và 8–13. **Không giữ dây TFT/còi cũ khi dùng profile camera.**
Chuyển dây ngoài như sau trước khi nạp:

| Thiết bị / chân | GPIO cũ | Cấu hình camera mới |
| --- | --- | --- |
| TFT VCC, LED | 3V3 | 3V3 |
| TFT GND | GND | GND |
| TFT CS | 10 | **42** |
| TFT RESET | 8 | **40** |
| TFT DC | 9 | **41** |
| TFT SDI / MOSI | 11 | **21** |
| TFT SCK | 12 | **47** |
| TFT SDO / MISO | 13 | **39** |
| Còi + / tín hiệu | 5 | **14** |
| Còi GND | GND | GND |

Người dùng xác nhận bộ dây mới đúng bảng trên. Các chân `T_CLK`, `T_CS`,
`T_DIN`, `T_DO`, `T_IRQ` thuộc cảm ứng, để trống khi chỉ hiển thị.

Profile camera không dùng thẻ SD. Không dùng GPIO 35–37 dành cho bộ nhớ N16R8,
19–20 dành cho USB, hoặc 43–44 của UART. Firmware kiểm tra xung đột chân camera
với TFT/còi khi biên dịch. Camera dùng LEDC timer 1/channel 2, tách với còi
timer 0/channel 0. TMB12A05 vẫn chỉ phát nhịp; camera không đổi khả năng của còi.

## Build và sử dụng

**Bản 2.3.2-coexfix — sửa reset lặp:** log người dùng ở 2.3.1 có thông báo
`Should enable WiFi modem sleep when both WiFi and Bluetooth are enabled`,
sau đó `abort`/`RTC_SW_CPU_RST`. ELF SHA256 đầu `1227e01d80332bf2` khớp bản
đã build; giải địa chỉ `0x420d88a3` ra `pm_set_sleep_type`, rồi
`wifi_set_ps_process`. Nguyên nhân là `WiFi.setSleep(false)` trong nhánh có IP,
tương đương `WIFI_PS_NONE` không được phép trong chế độ coexist của IDF 4.4.
Đã bỏ lệnh đó, đặt `WIFI_PS_MIN_MODEM` trước khi bật STA và cấu hình rõ ở
driver. Xem [quy định của Espressif](https://docs.espressif.com/projects/esp-idf/en/v4.4.6/esp32s3/api-guides/wifi.html#station-sleep).

`profile NOT_FOUND` chỉ là thiếu blob định dạng mới khi đọc keys cũ. Nay kiểm
tra key tồn tại trước khi đọc; vẫn chuyển đổi dữ liệu cũ sau khi kết nối
thành công. **Không cần erase NVS hoặc `WIFI FORGET` để sửa reset**.
Boot mới in `WIFI COEX power_save=MIN_MODEM rc=ESP_OK`. Cơ chế flash/NVS,
BLE tự tìm mạng, ảnh chụp và dây nối giữ nguyên. Chưa nạp thử lại trên bo;
xác nhận sửa thực tế cần log sau khi người dùng nạp bản mới.

**Bản 2.3.1-blewifi:** sự kiện **BLE APP CONNECTED** tự kích hoạt tìm/kết nối
mạng đã lưu ngay, vượt qua backoff 60 giây hoặc thời gian chờ sau scan. Không
cần nhấn Quét/Kết nối trong app mỗi phiên; `WiFi.begin` yêu cầu driver tìm
SSID đã cấu hình rồi xác thực. Nếu LAN đã kết nối thì giữ nguyên, nếu đang
join thì tiếp tục lượt đó. Task Wi-Fi nhận cờ từ vòng BLE, không thao tác
radio/NVS trong callback stack Bluetooth. Serial có `WIFI BLE WAKE: searching
saved SSID and connecting now` hoặc `LAN already connected`/`connection in progress`.
Thông tin lưu **flash/NVS**, không gắn với phiên BLE; ngắt BLE, reset và rút
nguồn không xóa. Chỉ `WIFI FORGET`/erase NVS mới xóa mạng đã nhớ.

**Bản 2.3.0-autowifi:** chỉ cấu hình mạng một lần trong app. Khi đã có IP,
ESP32 lưu SSID/password thành một blob 104 byte có version/CRC ở NVS
`vietocr-wifi`, key `profile`, đọc lại để kiểm tra ghi thành công. Reset/tắt
nguồn không mất cấu hình. Đọc tương thích `ssid`/`pass` của firmware cũ;
lần kết nối thành công đầu tiên chuyển sang blob mới. Không ghi flash lại
mỗi heartbeat hoặc mỗi lần nối lại cùng mạng. Mạng mới nhập sai không ghi
đè mạng đã kết nối thành công trước đó.

Mất mạng hoặc router chưa bật: tự thử lại sau **3, 6, 12, 24, rồi 60 giây**
(mỗi lần connect tối đa 25 giây). Scan được ưu tiên; sau scan chờ 30 giây
để chọn mạng, khi nhận SSID/password mới chờ 60 giây để nhập, không tranh
driver với reconnect. Sau khi có mạng, lịch thử lại đặt về đầu. Tự kết nối
Wi-Fi độc lập với BLE/app. Không cần cài lại APK để dùng cache trên bo.

Wi-Fi, HTTP start/stop và NVS chạy ở task riêng. Vòng Arduino chỉ đẩy lệnh
vào queue/nhận reply để BLE/TFT tiếp tục chạy; reply cũ bị bỏ khi BLE đổi
phiên. `WIFI SAVED` trả trạng thái + SSID hex, không trả mật khẩu.
`WIFI FORGET` xóa cả profile mới và keys cũ. Serial in `WIFI CACHE loaded`,
`WIFI CACHE saved and verified (NVS)` khi lưu thành công. Không erase flash
toàn bộ khi nâng firmware nếu muốn giữ mạng đã lưu.

Đây là bản chỉ build, chưa kiểm tra cold boot/mất điện thật trên bo.
NVS được thiết kế giữ dữ liệu qua reset/mất điện theo
[tài liệu Preferences Espressif](https://docs.espressif.com/projects/arduino-esp32/en/latest/api/preferences.html).

**Bản 2.2.1-recovery:** khi `WIFI STATUS OFFLINE 1` nhưng `WIFI SCAN` liên
tục bị từ chối, app chưa có đường Wi-Fi để xem camera. Driver có thể vẫn
thử kết nối mạng cũ sau khi cờ `joining_` hết hạn. Lệnh SCAN mới ưu tiên
người dùng: dừng lần kết nối offline, tắt auto-reconnect, đợi 250 ms rồi quét
nền; tối đa ba lần thử, cách nhau 500 ms. Không ngắt một LAN đang hoạt động.
Sau 25 giây kết nối không thành công, dừng driver thật. NVS giữ nguyên.
App kiểm tra cả BLE Wi-Fi status và HTTP trước khi gửi `CAM OPEN`; lỗi mạng
không khởi động cảm biến và không làm mất BLE. `OFFLINE/JOINING` thêm mã lý
do ở cuối, READY giữ định dạng cũ. Chi tiết giới hạn scan/connect:
[Espressif: scan khi đang kết nối](https://docs.espressif.com/projects/esp-idf/en/v4.4.6/esp32s3/api-guides/wifi.html#scan-when-wi-fi-is-connecting).
Đây là sửa lỗi từ đối chiếu log/mã; chưa đo lại scan trên bo thật.

**Bản 2.2.0-stream:** thay việc lặp GET `/preview` 3 MP bằng kết nối MJPEG
liên tục **`:81/stream`**. Preview **QVGA 320×240, quality20**, tối đa cấu hình
10 fps; lấy khung mới nhất, bỏ khung cũ khi client/mạng chậm. Camera dùng hai
frame buffer PSRAM với `CAMERA_GRAB_LATEST`. HTTP :80 và :81 chạy hai task
riêng, nên stream không chiếm luồng `/health`/`/image` hay worker BLE desktop.
Nút chụp đóng stream trước; camera chuyển sang **QXGA 2048×1536, quality6**,
bỏ buffer cũ và đọc kích thước trong JPEG SOF để không nhận nhầm ảnh preview
là ảnh gốc. Ảnh chụp kiểm CRC32 như trước. **Cần cập nhật cả firmware và app**;
APK Android là **1.6.0+9**. Không đổi dây, không xóa Wi-Fi đã lưu.

Log desktop trước sửa: mỗi JPEG xem trước khoảng 200 KB mất 6–14 giây tải,
không phải video stream. Thiết kế mới giảm dữ liệu xem trước và giữ một socket.
Test host đã kiểm tra multipart chia gói, bỏ khung tồn, dừng/mở lại và lỗi mạng.
Bản này chỉ build, người dùng tự nạp; **chưa đo FPS/thời gian mở trên bo thật**.

Cách tách server stream dựa trên
[CameraWebServer chính thức của Espressif](https://github.com/espressif/arduino-esp32/blob/2.0.14/libraries/ESP32/examples/Camera/CameraWebServer/app_httpd.cpp);
cấu hình nhiều buffer/khung mới nhất theo
[esp32-camera](https://github.com/espressif/esp32-camera).

**Bản 2.1.0-wifi:** listener HTTP được mở sau khi STA có IP DHCP hợp lệ,
khởi động lại nếu IP đổi/mất kết nối. Serial ghi `WIFI HTTP listening ip=...`
và mã lỗi gốc nếu không mở được server. `/health` cần cùng token như JPEG,
trả firmware/IP/RSSI; nút Kiểm tra trên app thực sự thử HTTP. Sau khi chụp,
Serial có `capture_ms`, `send_ms`, số byte và mã gửi để phân biệt thời gian
camera với thời gian truyền. Giữ 2048×1536/quality6; giảm một frame bỏ khi
camera đã chạy sẵn. Bản này **chỉ build, người dùng tự nạp**, chưa kiểm tra
HTTP/JPEG trên bo thật. Nếu vẫn timeout khi cùng LAN, cần dựa trên IP/subnet,
mã socket và cấu hình router/VPN để xác định; chưa thể khẳng định một nguyên
nhân mạng từ traceback `URLError` cũ đã che lỗi gốc.

**Nếu app báo `ERR INVALID_COMMAND` khi Quét mạng:** firmware trên bo chưa
có lệnh Wi-Fi. Cập nhật app không tự nạp firmware ESP32. Ngày 27/10 đã đọc
COM8, xác nhận firmware cũ từ chối `WIFI STATUS`, sau đó nạp trực tiếp bản
`2.0.1-wifi` và kiểm tra: Serial có 14 điểm phát; quét bằng mã desktop qua BLE
trả 7 tên mạng sau lọc trùng/tên rỗng. Lệnh `INFO` hiện phải trả
`INFO VIETOCR_ASSISTANT 2.0.1-wifi WIFI1 CAMERA_OV3660_2048x1536`.
App phân biệt firmware thiếu Wi-Fi, ESP32 đang kết nối và quét thất bại;
firmware không còn biến mã scan lỗi thành danh sách rỗng.

Lượt này chưa nhập mật khẩu/kết nối LAN hoặc kiểm chứng JPEG qua Wi-Fi trên
bo thật. Kiểm tra `THEME LIGHT/DARK` → `STATUS` qua BLE đã qua; chủ đề cũ đã
được khôi phục sau kiểm tra. Không cần đổi dây hoặc xóa toàn bộ flash.

Trong `pbl4`, mặc định là profile camera vì người dùng đã xác nhận chuyển dây
ngày 26/10/2026. Profile legacy chỉ dùng cho bộ dây cũ:

```powershell
pio run -e esp32-s3-cam-ov3660
# Sau khi chuyển dây TFT/còi theo bảng trên:
pio run -e esp32-s3-cam-ov3660 -t upload --upload-port COM8
pio device monitor --port COM8 --baud 115200
```

`COM8` là cổng USB-UART CH343 đang thấy trên máy; dùng cổng thực tế nếu thay đổi. File build
ở `.pio/build/esp32-s3-cam-ov3660/firmware.bin`. Profile cũ
`esp32-s3-devkitc-1` giữ dây cũ và tắt camera; `CAM ...` trả `CAMERA_DISABLED`.
Không cần upload filesystem.

### TFT trắng sau khi chuyển dây

**Cập nhật sau điều tra:** người dùng xác nhận hai hàng chân bo camera mới
chỉ cắm xuyên lỗ, **chưa hàn**, khe microSD không có thẻ. Cần hàn chân vào
pad PCB để có kết nối điện ổn định rồi chạy lại test hiện tại. Chưa kiểm
chứng màn hình sau hàn. [Đối chiếu cấu hình và nguồn tài liệu](TFT_INVESTIGATION.md).

Serial người dùng đã tới `READY VIETOCR_ASSISTANT 1` và `BLE READY`, nên
firmware vẫn chạy; chưa có bằng chứng chương trình treo ở khởi tạo TFT.
Bản ngày 26/10 đổi mặc định sang profile camera, giảm SPI TFT từ 20 xuống
10 MHz và in cấu hình **do chính thư viện TFT_eSPI sử dụng**. Log mới của
người dùng cho thấy `MOSI=21 MISO=21`: trong TFT_eSPI 2.5.43, file
`Processors/TFT_eSPI_ESP32_S3.h` tự đổi `TFT_MISO=-1` thành `TFT_MOSI` trên S3.
Vì vậy cấu hình hiện tại dùng **SPI 4 dây, MISO riêng GPIO39**; nối SDO/MISO
của TFT vào 39. Chỉ thay dây này so với bảng mới trước đó. Không nối lại GPIO13
vì đó là PCLK camera.

Thư viện và firmware có kiểm tra biên dịch không cho MISO trùng MOSI. Log sau
khi nạp đúng bản mới phải là:

```text
FIRMWARE esp32-s3-cam-ov3660 | TFT pins: CS42 RST40 DC41 MOSI21 SCK47
TFT CONFIG driver=0x9341 MOSI=21 MISO=39 SCK=47 CS=42 DC=41 RST=40 SPI=10000000 Hz
TFT READ ID=0x9341 ...
TFT COLOR RED
TFT COLOR GREEN
TFT COLOR BLUE
```

Đóng Serial Monitor trước khi nạp, rồi mở lại và nhấn RESET. TFT phải hiện lần
lượt ba màu rồi về trợ lý. `TFT INIT complete` chỉ xác nhận lệnh SPI đã được
gửi; log gửi màu chưa phải bằng chứng panel đã nhận và hiển thị dữ liệu.
Nếu vẫn trắng cả ba lần, gửi dòng `TFT CONFIG` thực tế để tiếp tục kiểm tra
RST/DC/CS/SCK/MOSI và nguồn màn hình. ID được đọc qua MISO ở 1 MHz;
`0x0000/0xffff` cần kiểm tra thêm SDO/MISO, không tự kết luận panel hỏng.

**Kết quả mới nhất:** người dùng đã nối MISO39 và cung cấp log đúng toàn bộ
GPIO, nhưng ID vẫn `0xffff` và cả ba màu vẫn trắng. Việc tách MISO chưa giải
quyết được lỗi hiển thị; chưa xác định nguyên nhân từ log này.
Đã tạo [bản kiểm tra GPIO trực tiếp](../diagnostics/tft_probe/README.md),
giữ nguyên bộ dây, không chạy camera/BLE/SPI phần cứng. Người dùng đã nạp và
chạy: `SOFT ID D3: ff ff ff ff`, có log `BARS SENT`, màn hình vẫn trắng.
Chương trình dùng cùng bảng khởi tạo ILI9341 và gửi ba dải màu bằng
`digitalWrite`. Kết quả chưa xác định nguyên nhân, chưa chứng minh panel hỏng.
Bước tiếp theo là kiểm tra mặt sau module, đường nối và điện áp VCC/RESET
tại đầu TFT; chưa có căn cứ đổi GPIO hoặc đổi VCC lên 5V.

Người dùng đã xác nhận ấn dây thì màn hình hoạt động, phù hợp lỗi tiếp xúc
header chưa hàn. Firmware hiện tại **bỏ phần màu kiểm tra khởi động**, vào
thẳng trợ lý. Chương trình `diagnostics/tft_probe` là bản thử riêng, không phải
firmware sử dụng thường ngày.

1. Chỉ kết nối một app với trợ lý qua BLE.
2. Mở **Wi-Fi camera** trên desktop hoặc trong thẻ OV3660 của mobile. Quét,
   chọn mạng **2.4 GHz**, nhập mật khẩu, Kết nối rồi Kiểm tra. Máy nhận và ESP32
   cần cùng LAN; Wi-Fi khách có cách ly thiết bị sẽ không dùng được. Có thể nhập
   SSID thủ công cho mạng ẩn. Cấu hình lưu trên NVS `vietocr-wifi` của ESP32.
3. Nhấn **Xem camera**: góc nhìn xuất hiện trong app desktop/điện thoại.
   App gửi `CAM ORIENT h v`, `CAM OPEN`, rồi mở MJPEG **640×480/QS16** qua
   **HTTP :81/stream**. Ảnh chụp vẫn **2048×1536/QS4**.
   TFT luôn hiển thị trợ lý, vì vậy đổi theme vẫn cập nhật ngay cả khi xem camera.
   Nhấn **Chụp OV3660** trong app, nhận ảnh gốc qua Wi-Fi và kiểm tra CRC32.
   Xem ảnh vừa chụp 3 giây hoặc Bỏ qua để ngắm và chụp tiếp. Không cần nối cảm ứng T_*.
4. Ảnh hợp lệ tự vào OCR sau bước xem ảnh; camera tự trở lại preview, không đóng tab.
   Có thể chụp tiếp kể cả khi OCR ảnh trước vẫn đang chạy.
5. Ảnh được nhận diện lần lượt; ảnh mới nối vào cuối hàng đợi, không đọc lại
   ảnh đã hoàn tất. Trợ lý báo xong khi hàng đợi đã hết. Xem/sửa/xuất văn bản
   trong app như trước.

Từ **2.4.1-native**, preview và ảnh chụp cùng **2048×1536/quality0**.
Không đưa camera lên TFT. Camera task riêng xử lý DVP; HTTP task gửi bản sao
khung mới nhất, không giữ mutex camera trong lúc chờ mạng. Độ phân giải cao
không sửa được sai tiêu cự, rung hoặc thiếu sáng. Chưa đo FPS/độ nét/tốc độ
Wi-Fi trên bo thật với firmware mới.

BLE dùng cho điều khiển và cấu hình; app cần Wi-Fi/HTTP hoạt động để chụp.
Nếu HTTP lỗi sau khi đã chụp, app báo lỗi và giải phóng ảnh; không âm thầm chụp
thêm ảnh thứ hai. Thời gian truyền BLE phụ thuộc MTU, sóng và máy nhận.
MTU mặc định 23 có thể khiến ảnh 60–70 KB mất nhiều phút nếu dùng hàng nghìn
lượt Write/Read nhỏ. Phần BLE transfer giữ riêng cho công cụ/firmware cũ; UI
chụp hiện tại chỉ đi qua Wi-Fi. Firmware đề nghị MTU **517** và connection interval
**15–30 ms**, máy nhận quyết định kết quả cuối. Serial in MTU thực tế.
Desktop Windows thử đọc **480 byte JPEG mỗi lượt** qua cơ chế GATT long read,
tự lùi về từng gói MTU nếu driver từ chối hoặc cắt ngắn. Log in MTU, kích thước
chunk, tiến độ mỗi 4 giây, tổng byte và CRC. Timeout có số byte đã nhận.
Các tối ưu này đã kiểm thử mô phỏng; tốc độ/kết quả nhận ảnh trên bo thật sau
bản sửa này chưa được xác nhận.

### Tốc độ hiển thị

SPI ghi TFT hiện **40 MHz**. Hoạt ảnh trợ lý đặt mục tiêu **60 FPS**, chỉ gửi
lại vùng động thay vì toàn mặt ở mỗi khung. ILI9341 FRMCTR1 được đặt
`DIVA=0, RTNA=0x1f`, tương ứng danh định **61 Hz** theo bảng của hãng, gần
60 Hz nhất trong các giá trị được liệt kê. Tần số quét panel và FPS camera là
hai thông số khác nhau.

Camera toàn màn hình 320×240 RGB565 cần 1.228.800 bit mỗi khung. Riêng SPI
40 MHz chỉ có giới hạn lý thuyết khoảng **32,6 khung/giây**, trước chi phí JPEG,
lệnh và vẽ, nên không thể cam kết camera toàn màn hình 60 FPS với cấu hình này.
Serial in `TFT FPS assistant=...` hoặc `TFT FPS camera=...` mỗi 5 giây để đo
thực tế. Khi ngủ vẫn giảm số lần vẽ để tiết kiệm xử lý.

Nguồn: [ILI9341 datasheet, FRMCTR1 mục 8.3.2](https://cdn-shop.adafruit.com/datasheets/ILI9341.pdf).

## Hợp đồng truyền JPEG

### Wi-Fi cấu hình qua BLE

Các lệnh vẫn nằm trong giới hạn dòng ASCII 80 byte. SSID/password mã hóa hex
UTF-8 để hỗ trợ khoảng trắng và tiếng Việt; mật khẩu chia khúc tối đa 24 byte.
Hex là mã hóa biểu diễn, không phải mã hóa bảo mật. App không ghi các giá trị
mật khẩu hoặc token vào log. NVS lưu mật khẩu trên bo để kết nối lại sau reset.

| Lệnh | Phản hồi |
| --- | --- |
| `WIFI SCAN` | `OK WIFI SCAN`, bắt đầu quét nền |
| `WIFI COUNT` | `WIFI COUNT BUSY` hoặc `WIFI COUNT <0..30>` |
| `WIFI NET <index>` | `WIFI NET <index> <rssi> <secured> <ssid_hex>` |
| `WIFI SSID <hex>` | `OK WIFI SSID`, bắt đầu cấu hình mới, xóa password tạm |
| `WIFI PASS <hex>` | `OK WIFI PASS`, nối thêm tối đa 24 byte |
| `WIFI JOIN` | `OK WIFI JOIN`, kết nối nền; lưu mạng mới sau khi có IP |
| `WIFI STATUS` | `WIFI STATUS JOINING/OFFLINE <status>` hoặc `WIFI STATUS READY <ip> <token> <ssid_hex>` |
| `WIFI SAVED` | `WIFI SAVED <0/1> <ssid_hex hoặc ->`, không lộ mật khẩu |
| `WIFI FORGET` | Xóa Wi-Fi đã lưu, ngắt Wi-Fi, thay token |

HTTP cổng **81**: `GET /stream` trả `multipart/x-mixed-replace`, boundary
`vietocr-frame`, mỗi part có `Content-Type: image/jpeg`, `Content-Length` và
`X-Sequence`. Kết nối giữ mở, không có Content-Length cho toàn stream.
HTTP cổng **80**: `GET /preview` lấy một JPEG nhỏ mới nhất (dành cho chẩn đoán);
`GET /image?id=<frame_id>` lấy ảnh gốc đã chụp; `/health` trả JSON, gồm firmware,
IP, RSSI, `stream_port:81`, `preview:[640,480]`, `still:[2048,1536]`,
`preview_jpeg_quality:16`, `jpeg_quality:4`, `mirror`, `flip`,
`jpeg_capacity:2097152` (mỗi framebuffer) và `camera_status`.
Các endpoint yêu cầu header `Authorization: Bearer <token>` lấy qua BLE,
không cache hoặc redirect. Token đổi/ngắt BLE sẽ kết thúc stream. Client chụp
qua `CAM SHOT`/`CAM META`, tải JPEG qua Wi-Fi rồi kiểm CRC32 và `CAM RELEASE`.
Đây là HTTP trên LAN, không dùng dịch vụ cloud và không thay đổi OCR offline.

### BLE dự phòng

Dùng NUS RX/TX cũ cho lệnh/ACK. Characteristic riêng
`6e400004-b5a3-f393-e0a9-e50e24dcca9e` có **Read + Write with response** cho ảnh.

| Lệnh NUS | Phản hồi |
| --- | --- |
| `CAM OPEN` / `CAM CLOSE` | `OK CAM OPEN` / `OK CAM CLOSE` |
| `CAM STATUS` | `CAM STATUS OPENING`, `READY`, `CLOSED` hoặc `ERROR <lỗi>` |
| `CAM ORIENT <h:0/1> <v:0/1>` | `OK CAM ORIENT h v`; áp dụng cho cả preview/ảnh chụp, nhớ NVS |
| `CAM ORIENT` | `CAM ORIENT h v`; đọc lựa chọn hướng hiện tại |
| `CAM SHOT <id>` | `OK CAM SHOT <id>`; bắt đầu chụp nền |
| `CAM META <id>` | `CAM <id> <bytes> <crc32_hex> <width> <height>` hoặc `ERR CAMERA_BUSY` |
| `CAM RELEASE <id>` | `OK CAM RELEASE <id>`; giải phóng ảnh |

ID là số uint32 dương do client tạo cho mỗi lần chụp. Client đợi metadata tối
đa 25 giây, từ chối ảnh trên 2 MiB hoặc kích thước bất hợp lý trước khi cấp RAM.
Đây là giới hạn **mỗi ảnh truyền**, không phải số ảnh trong hàng đợi.

Mỗi chunk được lấy bằng hai thao tác trên characteristic ảnh:

1. Write **12 byte little-endian**: `uint32 frame_id, offset, wanted_bytes`.
2. Read: **8 byte header** `uint32 frame_id, offset` rồi đến dữ liệu JPEG.

Android dùng `wanted_bytes <= min(480, MTU - 9)`, bao gồm header trong ATT Read
response `MTU - 1`. Desktop WinRT thử `wanted_bytes <= 480` với long read rồi
lùi về giới hạn MTU nếu cần. Firmware giữ nguyên nội dung chunk trong cả chuỗi
Read Blob, chỉ đổi khi selector tiếp theo được ghi; tổng giá trị tối đa 488 byte.
Chunk sai ID/offset/độ dài được đọc lại tối đa 3 lần. App kiểm CRC32 toàn ảnh
(đa thức IEEE `0xedb88320`, giống `zlib.crc32`) và JPEG SOI/EOI trước khi nhập.
Lỗi CRC không được đưa vào OCR. Đây là kiểm tra lỗi đường truyền, không phải
xác thực thiết bị.

Giữ `PING` mỗi 4 giây khi nhận ảnh; giới hạn toàn lượt nhận 4 phút. Chỉ một
snapshot tồn tại trên ESP32; nhận xong/lỗi đều gửi RELEASE. Mất kết nối hoặc
không đọc ảnh trong 120 giây sẽ giải phóng buffer. Không tự ghép ảnh dở dang
của phiên BLE cũ vào ảnh mới.

## OCR và kiểm chứng

Desktop lưu ảnh hàng đợi vào file tạm và chỉ giải mã ảnh đang xem/đọc; danh
sách hiển thị từng trang 50 mục. Nạp PyTorch/inference vẫn ở tiến trình riêng,
CPU tối đa 2 thread, OpenCV 1 thread. Lỗi worker có mã thoát số/hex, tên bước và
log; GUI/terminal không thoát theo worker. Dừng OCR/lỗi nạp model sẽ dừng tự
chạy hàng đợi, giữ ảnh và kết quả, chờ người dùng thử lại.

Android lưu ảnh hàng đợi trong vùng riêng của app, khôi phục đủ danh sách khi
mở lại; CRC chạy isolate và tiến độ BLE được giới hạn tần suất vẽ. Nút
**Kiểm tra AI trên máy này** chạy ảnh mẫu đóng gói qua đúng dịch vụ OCR,
không thêm ảnh mẫu vào hàng đợi. Nếu thất bại, xem **Log → AI CHECK / OCR** để
lấy lỗi gốc và version/build. Quy tắc giữ lớp JNI của ONNX vẫn được kiểm tra
trên APK release để tránh lặp lỗi R8 của bản 1.2.0.

Kết quả trước đó ngày 25/10/2026 được ghi trong `../../Mobile/validation.json` và
`camera-validation.json`: kiểm tra CRC/offset/MTU, hàng đợi trên 10 ảnh,
nhận thêm khi đang OCR và giữ giao diện khi worker chết. Desktop còn chạy
trọng số thật trên 4 mẫu và ảnh ghép 2 dòng. Các ca này xác nhận nạp/chạy có
kết quả và GUI còn phản hồi, không khẳng định độ chính xác mọi từ. Một số mẫu
vẫn nhận sai chữ theo chất lượng model hiện tại. Host Java/JNI đối chiếu 8 ca với
Python. Các kiểm tra này không thay thế đo camera/BLE hoặc chạy OCR trên điện
thoại thật; chưa flash board/cài APK lên thiết bị trong lượt này.
