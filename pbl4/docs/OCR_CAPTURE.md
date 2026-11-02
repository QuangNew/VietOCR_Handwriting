# OV5640: lấy ảnh phục vụ OCR — 02/11/2026

Firmware `3.1.0-ocr`, bo N16R8 qua COM8. Không thay chân, camera driver, PSRAM/DMA hay tải toolchain mới.

## Nguồn đã đối chiếu

- [Espressif esp32-camera](https://github.com/espressif/esp32-camera): JPEG + PSRAM, hai framebuffer cho continuous capture; hỗ trợ AF phụ thuộc module có motor/VCM. Giữ driver hiện có vì upstream mới yêu cầu IDF mới hơn môi trường Arduino 2.0.14 của dự án.
- [OV5640 AF commands](https://github.com/espressif/esp32-camera/blob/master/sensors/ov5640_af.c) và [AF wait helper](https://github.com/espressif/esp32-camera/blob/master/driver/esp_camera_af.c): gửi trigger và đợi trạng thái focus là hai bước riêng. ACK không đủ để khẳng định lens đã khóa. Áp dụng trình tự reset/release/trigger và đợi status `0x10`, báo không khóa khi idle/lỗi/timeout.
- [OV5640 register definitions](https://github.com/espressif/esp32-camera/blob/master/sensors/private_include/ov5640_regs.h): đọc AEC thực ở `0x3500..3502`, gain `0x350a..350b`. Không dùng giá trị cache của API tự động.
- [CameraWebServer controls](https://github.com/easytarget/esp32-cam-webserver): tham khảo cấu hình sensor theo điều kiện sáng, hướng ảnh, JPEG/AF. Bảng điều khiển LAN đã có trong dự án được mở rộng bằng preset OCR.
- [Tesseract ImproveQuality](https://tesseract-ocr.github.io/tessdoc/ImproveQuality.html): ánh sáng, skew và vùng chữ ảnh hưởng OCR. Đây là hướng dẫn Tesseract, không phải bằng chứng VietOCR nên nhận ảnh nhị phân. Không tự threshold/sharpen cực mạnh hay tăng DPI metadata rồi coi là thêm chi tiết.
- [OpenCV homography](https://docs.opencv.org/4.x/d9/dab/tutorial_homography.html): chỉnh phối cảnh cần đúng bốn góc của mặt phẳng tài liệu. Lượt này không tự đoán góc/cắt giấy vì ảnh còn có bàn, hình vẽ và mép trang ngoài khung; người dùng có thể crop bằng trình xem ảnh desktop.
- [Báo cáo OV5640 QS rất thấp](https://github.com/espressif/esp32-camera/issues/684): một cấu hình phần cứng gặp artifact khi QS thấp hơn 4. Không coi đó là lỗi mọi module; giữ khoảng hợp lệ QS>=4, preset OCR dùng 6 thay vì ép 0.

## Quy trình đã triển khai

1. Preview 640×480, QS18, trần 30 FPS, continuous AF. FPS thực phụ thuộc ánh sáng và LAN.
2. Đợi AEC/AGC ở preview ổn định, cấu hình điểm AF theo tọa độ 0–100% (bấm vào chữ trong app). Dùng lệnh 0x80/0x81 của firmware AF đang đóng gói; tọa độ bù lại hmirror/vflip.
3. Trigger single AF ở preview, đợi status `0x10` rồi pause/giữ lens và chuyển sang native **2592×1944**, cùng góc nhìn 4:3. Quét nét có timeout 4 giây và tối đa một lần thử lại. Thất bại trả `CAMERA_FOCUS`. Thử thật trên bo cho thấy cấu hình vùng nét sau chuyển sang native có thể treo ACK; đường chụp hiện tránh trình tự đó. Lệnh pause `0x06` không chờ ACK vì blob đang dùng không xóa ACK cho lệnh này.
4. Bỏ ảnh còn đọng từ preview và ảnh trước khi lens khóa; đọc AEC/AGC qua các khung mới. Chấp nhận khi có ba lần đọc liên tiếp lệch không quá 8%. Đây là ngưỡng thực nghiệm của dự án, không phải thông số bắt buộc từ Espressif. Nếu chưa hội tụ trả `CAMERA_EXPOSURE` trong thời gian hữu hạn.
5. Kiểm tra JPEG đủ chiều, đúng độ phân giải, truyền HTTP và xác minh CRC32. Giữ JPEG nguyên gốc; không upsample VGA làm ảnh chụp.
6. Preset **Tài liệu OCR**: QS6 cho still, neutral brightness/contrast/saturation/sharpness, denoise0, AWB/AE/AGC/AF bật, hiệu chỉnh ống kính bật. Không ghi đè hmirror/vflip. Mục tiêu giữ nét mảnh/dấu tiếng Việt, tránh vùng giấy sáng bị cắt mất chi tiết; không hứa tối ưu mọi nguồn sáng.

## Kiểm tra thật và giới hạn

- `validation/ocr-camera.json`: stream, chụp liên tiếp, CRC, kích thước, thời gian và xác nhận ngủ sâu.
- `validation/ocr-paper.json`: so sánh cùng trang giấy với cấu hình đã lưu trước đó và preset OCR. JPEG giảm 692593 → 439004 bytes. Lượt đầu có khởi tạo camera lạnh nên không so trực tiếp thời gian hai lượt như benchmark tốc độ.
- Single AF báo khóa khoảng 1,3 giây; tạo native JPEG sau chuyển chế độ khoảng 2 giây ở cảnh thử. AF khóa không bảo đảm mọi vị trí trên trang nghiêng đều sắc nét.
- Quan sát ảnh thật: nét còn mềm, giấy nghiêng, bóng và hình vẽ. Sau khi pull đúng bộ nạp ML_s44 64 px/V2c ngày 02/11, hai trong bốn crop chữ do người dùng cung cấp được pipeline DIP đọc đúng “Chúc giáng sinh vui vẻ”. Đây là thử trên bốn ảnh, chưa phải đánh giá độ chính xác chung; xem [báo cáo tích hợp](../../VietHandOCR_API_Release/docs/REVIEW_2026-11-02.md).
- Thử riêng chuẩn hóa nền bằng morphology rồi deskew giúp một biến thể gần đúng hơn, nhưng không ổn định giữa hai ảnh. Chưa đưa bước đó vào pipeline mặc định để tránh làm mất dấu hoặc thay đổi các ảnh mẫu đang hoạt động.
- Để chụp tài liệu: đặt sensor song song trang, cho vùng chữ gần giữa khung và chiếm phần lớn ảnh, giữ đứng yên, chiếu sáng đều hai bên tránh bóng camera. Cắt vùng chữ trước OCR khi trong ảnh có hình vẽ/bàn; preset không thay được điều kiện quang học.

## Cho bo nghỉ

Sau **10 giây không preview/chụp**, camera giải phóng driver/DMA, dừng XCLK và đưa sensor vào software standby. Ảnh JPEG đang chờ tải không giữ sensor chạy. Khoảng đợi vẫn cho phép xem lại ảnh 3 giây và chụp tiếp mà không khởi tạo lạnh mỗi lần. Lần mở lạnh phải nạp lại AF (~5 giây trên bo này).

Firmware **3.2.0-focus-power** thêm các chính sách sau:

- Preview có lease 65 giây; UDP client gia hạn mỗi 20 giây. Client chết không để camera chạy mãi. MJPEG/HTTP preview đang xem cũng gia hạn lease.
- Giới hạn FPS ngay tại tác vụ lấy/copy JPEG, cùng trần mà bộ gửi mạng sử dụng.
- CPU chạy 240 MHz khi camera hoạt động, 80 MHz khi sensor/DMA đã dừng; APB của S3 giữ 80 MHz.
- BLE dùng yêu cầu interval 30–50 ms, slave latency 4 và TX 0 dBm vì ảnh truyền qua Wi-Fi. Thiết bị trung tâm quyết định thông số thực tế.
- Wi-Fi luôn có modem sleep để tương thích BLE; chọn MIN_MODEM lúc nghỉ, MAX_MODEM/listen_interval=1 lúc camera chạy. TX giảm theo RSSI mạnh và tăng lại khi xa AP.
- TFT ở trạng thái Idle/Done vẽ 10 FPS; ngủ vẽ 1 FPS. Chuyển trạng thái vẫn vẽ ngay.
- Cảm biến nhiệt trong chip được đọc mỗi 5 giây, có thời gian chờ ADC ổn định và loại số ngoài dải đã cấu hình. Serial `POWER STATUS` và HTTP `/health` cho số đo. Từ 75°C giảm trần preview còn 10 FPS; từ 85°C dừng camera đến khi xuống 75°C. Đây là bảo vệ theo cảm biến trong chip, không đo nhiệt độ regulator/camera hay nhiệt độ ngoài vỏ.

Kiểm tra ngắn trên COM8 xác nhận standby/CPU 80 MHz, JPEG 5 MP CRC đúng và ngủ sâu cuối lượt. Chưa có phép đo 30 phút hoặc đo công suất/đối chiếu nhiệt kế ngoài; không coi cảm giác chạm tay là số đo 50/70/90°C đã được xác nhận. Log ở `validation/review-idle-2026-11-02.json`.

Serial `POWER SLEEP` là nghỉ sâu chủ động: dừng camera, HTTP/UDP, Wi-Fi và BLE trước `esp_deep_sleep_start()`. Chỉ nhận qua Serial; app không vô tình làm mất kết nối vĩnh viễn. Không cấu hình timer tự thức. Nhấn EN/RESET hoặc reset qua USB-UART để chạy lại; Wi-Fi/camera settings vẫn trong NVS. Đèn nền TFT nối trực tiếp 3V3 vẫn có điện, muốn tắt hoàn toàn cần ngắt nguồn.

```powershell
..\VietHandOCR_API_Release\.venv\Scripts\python.exe -X utf8 tools/camera_check.py --udp --seconds 15 --cycles 2 --wake --sleep-after
```

Lượt này đã nạp/test COM8, cuối lượt xác nhận `POWER DEEP_SLEEP`. Không cài thêm package/SDK và không build Android.
