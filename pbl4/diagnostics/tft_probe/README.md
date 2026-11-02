# Kiểm tra TFT trắng, giữ nguyên bộ dây mới

CS42, RESET40, DC41, SDI/MOSI21, SCK47, SDO/MISO39, GND chung.
Nguồn VCC và LED giữ theo kết nối người dùng đang dùng; chưa tự đổi lên 5V khi
chưa xác định được mạch ổn áp của module. Các chân T_* là phần cảm ứng, để trống.

Bản này gửi SPI bằng `digitalWrite`, không gọi SPI phần cứng hoặc đối tượng
TFT_eSPI, không chạy camera/BLE. Chỉ dùng lại bảng lệnh khởi tạo ILI9341 từ
thư viện 2.5.43 đang có để giữ cùng cách khởi tạo đã dùng trong cấu hình cũ.

Đóng Serial Monitor, chạy từ gốc repository:

```powershell
& "$env:USERPROFILE/.platformio/penv/Scripts/pio.exe" run -d pbl4/diagnostics/tft_probe -t upload --upload-port COM8
& "$env:USERPROFILE/.platformio/penv/Scripts/pio.exe" device monitor --port COM8 --baud 115200 --dtr 0 --rts 0
```

Nhấn RESET, đợi khoảng 15 giây. Chương trình in `SOFT ID D3: ...` và gửi ba
dải đỏ/xanh lá/xanh dương. Gõ R để thử lại. Log `BARS SENT` chỉ xác nhận đã gửi,
không chứng minh màn hình đã hiện màu.

- Nếu có dải màu: xác nhận TFT nhận lệnh trên bộ dây này qua GPIO trực tiếp;
  tiếp tục kiểm tra driver SPI/phần firmware trợ lý.
- Nếu vẫn trắng: lỗi chưa được phân biệt giữa đường nối/nguồn/RESET/loại panel.
  Cần ảnh rõ mặt sau module và hai đầu dây, hoặc đo VCC-GND, điện áp sau ổn áp,
  RESET trên chính đầu TFT. Không tiếp tục đổi GPIO hay kết luận MISO là nguyên nhân.

Kiểm tra này thay tạm firmware trợ lý khi người dùng upload. Sau đó nạp lại
profile `esp32-s3-cam-ov3660` từ thư mục pbl4 để khôi phục app/assistant.

Kết quả người dùng ngày 26/10/2026: `SOFT ID D3: ff ff ff ff`, log `BARS SENT`
đã xuất hiện nhưng màn hình vẫn trắng. Chưa xác định nguyên nhân. Cần xem
mặt sau module và kiểm tra điện áp/đường nối thực tế trước khi đổi cấu hình.

Cập nhật cùng ngày: người dùng xác nhận hai hàng chân bo camera chỉ cắm,
chưa hàn; không có thẻ microSD. Ngắt nguồn và hàn chân vào pad PCB, giữ nguyên
bộ dây rồi nhấn RESET chạy lại bản test đã nạp. Chưa có kết quả sau hàn.
Xem [ghi nhận điều tra](../../docs/TFT_INVESTIGATION.md).
