# TFT trắng trên bo camera: đối chiếu ngày 26/10/2026

## Kết quả mới nhất

Người dùng xác nhận **hai hàng chân ESP32-S3-CAM chỉ cắm xuyên lỗ, chưa hàn**;
khe microSD không có thẻ. Đây là lỗi lắp ráp đã xác nhận: thanh chân thông
thường chưa tạo kết nối điện ổn định với pad trên PCB. Chưa đo thông mạch từng
chân, nhưng lỗi này phù hợp với cả hai thử nghiệm TFT trắng và ID toàn `ff`.
Chưa xác nhận màn hình hoạt động sau khi hàn.

Người dùng sau đó xác nhận **ấn/đè các dây thì màn hình hoạt động**. Kết quả
này củng cố lỗi tiếp xúc ở hàng chân ngoài; chưa thay thế mối hàn ổn định.

USB-UART và camera dùng đường nối trên PCB/cáp camera nên có thể hoạt động
ngay cả khi hai hàng chân ngoài chưa được hàn. Đèn nền TFT có thể sáng khi
các chân nguồn tiếp xúc, trong khi CS, RESET, DC, MOSI hoặc SCK không tiếp xúc.
Vì vậy log boot/camera thành công và đèn nền trắng không chứng minh đường
tín hiệu từ ESP32 tới TFT đã thông.

## Đối chiếu phần mềm và tài liệu

| Hạng mục | Bản cũ | Bản camera |
| --- | --- | --- |
| Chip/board trong PlatformIO | esp32-s3-devkitc-1 | Giống bản cũ |
| Framework | espressif32 6.5.0 / Arduino 2.0.14 | Giống bản cũ |
| Flash / PSRAM | QIO / OPI, 16 MB / 8 MB | Giống bản cũ |
| Driver TFT | ILI9341, TFT_eSPI 2.5.43 | Giống bản cũ |
| CS / RESET / DC | 10 / 8 / 9 | 42 / 40 / 41 |
| MOSI / SCK / MISO | 11 / 12 / 13 | 21 / 47 / 39 |
| Tốc độ ghi SPI | 20 MHz | 10 MHz |

- GPIO cũ 8–13 trùng các đường dữ liệu/PCLK camera đã được người dùng kiểm
  chứng, nên việc chuyển dây là cần thiết khi sử dụng camera.
- ESP32-S3 cho phép đưa tín hiệu ngoại vi qua GPIO Matrix. GPIO21, 39–42 và
  47 không thuộc nhóm 35–37 dành cho Octal PSRAM. GPIO47 không mặc định là
  chân 1,8 V trên module WROOM-1-N16R8; cảnh báo điện áp đó áp dụng các biến
  thể chip/module khác. Không có căn cứ kết luận GPIO47 sai chỉ vì số chân lớn.
- Mã TFT_eSPI cài tại dự án có xử lý CS/DC từ GPIO32 trở lên qua `GPIO.out1`.
  Arduino 2.0.14 định tuyến SPI theo các chân được truyền vào `spi.begin()`;
  không bắt buộc dùng bộ chân mặc định 11/12/13.
- Màn hình được khởi tạo trước camera. Test riêng dùng `digitalWrite`, không
  khởi tạo camera/BLE/SPI phần cứng, vẫn trắng. Do đó hiện tượng không cần
  tác vụ camera/BLE đang chạy để xuất hiện; không thể chỉ quy cho tranh chấp
  tài nguyên trong chương trình trợ lý.
- MISO=-1 bị thư viện đổi thành MOSI là hành vi có thật, nhưng đổi MISO39
  không khắc phục trắng. Chẩn đoán trước đó coi MISO là nguyên nhân chưa có
  đủ bằng chứng. `ff ff ff ff` từ test có pull-up không xác nhận TFT đã phản hồi.

Nguồn chính thức đã đối chiếu:

- [GPIO ESP32-S3, ESP-IDF 4.4.7](https://docs.espressif.com/projects/esp-idf/en/v4.4.7/esp32s3/api-reference/peripherals/gpio.html).
- [Datasheet WROOM-1/WROOM-1U, bảng module và chú thích GPIO47/48](https://www.espressif.com/sites/default/files/documentation/esp32-s3-wroom-1_wroom-1u_datasheet_en.pdf).
- [Arduino 2.0.14: GPIO](https://github.com/espressif/arduino-esp32/blob/2.0.14/cores/esp32/esp32-hal-gpio.c),
  [SPI](https://github.com/espressif/arduino-esp32/blob/2.0.14/cores/esp32/esp32-hal-spi.c).
- [TFT_eSPI: xử lý ESP32-S3](https://github.com/Bodmer/TFT_eSPI/blob/master/Processors/TFT_eSPI_ESP32_S3.h),
  đối chiếu trực tiếp bản 2.5.43 đang cài trong `.pio/libdeps`.
- [Adafruit hỗ trợ: thanh chân chưa hàn không tạo kết nối ổn định](https://forums.adafruit.com/viewtopic.php?t=69875).

## Bước xử lý

Ngắt nguồn USB, hàn hai hàng chân vào pad PCB; mỗi mối hàn phải nối cả chân
kim loại và pad, không nối tắt các chân cạnh nhau. Nếu chưa có dụng cụ/kinh
nghiệm, nhờ shop hàn giúp. Giữ bộ dây hiện tại, chạy lại bản `tft_probe` đã
nạp bằng nút RESET, không cần đổi cấu hình hay nạp thêm một bản test mới.

Khi ba dải màu xuất hiện, nạp lại firmware trợ lý camera theo `CAMERA.md`.
Nếu vẫn trắng sau khi mối hàn đã được kiểm tra, tiếp tục đo thông mạch và
VCC/RESET tại TFT; không ghi nhận lỗi đã sửa chỉ dựa vào log gửi lệnh.

Lượt điều tra này không cài công cụ/thư viện, không đổi firmware hay GPIO.
