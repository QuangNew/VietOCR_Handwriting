# Đọc thử chân camera ESP32-S3 N16R8

**Tắt nguồn, tháo dây TFT/còi và thẻ microSD**, chỉ giữ camera trên bo và USB.
Cắm cổng **USB-UART** (cổng có đèn TX/RX).

Từ thư mục gốc repository, dùng PowerShell:

```powershell
# Thay COM7 bằng cổng của bạn (xem cổng bằng lệnh device list):
& "$env:USERPROFILE/.platformio/penv/Scripts/pio.exe" device list
& "$env:USERPROFILE/.platformio/penv/Scripts/pio.exe" run -d pbl4/diagnostics/camera_probe -e probe-uart -t upload --upload-port COM7
& "$env:USERPROFILE/.platformio/penv/Scripts/pio.exe" device monitor --port COM7 --baud 115200 --dtr 0 --rts 0
```

Mở monitor rồi nhấn **RESET**. Code tự thử PWDN=-1 và PWDN=38. Mỗi cấu hình
phải đọc được mã cảm biến và chụp/giải mã **3 JPEG** mới in
`=== WORKS: CAMERA PINOUT ===` cùng các chân. Gửi lại đoạn log đó.
Gõ `R` để thử lại.

Nếu dùng cổng **USB Native/OTG**, thay `probe-uart` bằng `probe-native-usb`
trong lệnh upload. Cổng COM có thể đổi sau nạp.

Code thử hai pinout GOOUUU/S3-WROOM trong
[ví dụ Espressif](https://github.com/espressif/esp32-camera/blob/master/examples/camera_example/main/camera_pinout.h),
không đọc sơ đồ mạch từ chip. Nếu cả hai chạy, PWDN=-1 cho biết không cần điều
khiển chân đó, chưa xác định dây PWDN vật lý. Không tìm thấy chưa chứng minh
camera hỏng.

Bản chẩn đoán tạm thay firmware trợ lý khi upload; lấy log xong nạp lại trợ lý.
Không ghi NVS, không dùng Wi-Fi/Bluetooth/TFT/còi. Cấu hình dự án trợ lý không đổi.
