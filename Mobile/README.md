# VietOCR Android — 3.0.0+17

Nhánh `refactor`: đây là client cũ đang giữ đối chiếu; luồng Flutter mới sẽ dùng webcam trên Raspberry và chỉ OCR sau khi bấm Gửi. Firmware ESP32 đã được gỡ. Xem [kế hoạch](../docs/REFACTOR_PLAN_2026-11-08.md) và [tiến độ](../docs/REFACTOR_PROGRESS.md); chưa có bản APK refactor được phát hành trong checkpoint đầu.

Ứng dụng Flutter Android **chỉ nhận diện qua OCR Server**. Đã bỏ ONNX runtime, service `:ocr`, trọng số và công tắc OCR offline khỏi client. Model chạy trên máy host C#, không phải Supabase. Supabase là database chính và dịch vụ đăng nhập Google.

## Sử dụng

1. Trên máy host chạy [Server/Run-Server.cmd](../Server/Run-Server.cmd) với `-Lan`.
2. Trong app, mở biểu tượng **Tài khoản & OCR Server**, nhập `http://<IP-máy-tính>:5080`. Bật HTTP trong LAN tin cậy nếu dùng mạng riêng. `localhost` trên điện thoại không phải máy tính.
3. **Đăng nhập Google** qua trình duyệt. Mỗi tài khoản có định danh OCR cố định; policy mới là **500 ảnh/ngày, 30 request trong 60 giây** sau khi database migrate. Phiên đăng nhập được mã hoá Android Keystore, tự refresh token; không nhập API key thủ công.
4. Thêm ảnh từ thư viện, camera điện thoại hoặc ESP32 OV5640. Không giới hạn tổng 10 ảnh; app gửi tuần tự. Hết quota hoặc mất server thì giữ phần ảnh còn lại để thử tiếp.

Mục tài khoản cho xem hạn mức và lịch sử/kết quả trên Supabase. Ảnh/crop đang soạn là cache riêng theo tài khoản trên thiết bị; đăng xuất không hiển thị dữ liệu tài khoản khác. Google login cần Internet; camera ESP32 dùng LAN/BLE độc lập. [Cấu hình Google/callback](../Server/docs/SUPABASE.md).

## Camera và ảnh

- BLE kết nối trợ lý, gửi theme/trạng thái và cấu hình Wi-Fi; ESP32 giữ mạng trong NVS.
- OV5640 preview UDP 640×480, ảnh chụp gốc 2592×1944. Lật ngang/dọc đồng nhất preview và ảnh chụp theo cấu hình cảm biến.
- JPEG được kiểm CRC32, tải HTTP có tiếp tục byte range; lưu ảnh giữ dữ liệu gốc.
- Xem lại 3 giây hoặc Bỏ qua, đưa ảnh vào queue; tab chụp mở tới khi tự đóng.
- Zoom/pan, crop chữ nhật/ellipse/tự vẽ và xoay vùng chọn, tạo PNG trắng đen OCR riêng.
- Theme sáng/tối, log lỗi, chia sẻ/sao chép và tải ảnh Android ACTION_CREATE_DOCUMENT.

## Build

```powershell
cd Mobile
flutter pub get
flutter analyze
flutter test
flutter build apk --release --target-platform android-arm64
```

APK dùng thử: [dist/VietOCR-arm64.apk](dist/VietOCR-arm64.apk). Android 8/API26 trở lên, arm64. Giữ signing certificate hiện tại để cài cập nhật; bản sideload chưa dùng Play signing production.

SDK `C:/Users/QuangNew/AppData/Local/Android/sdk`, Flutter `C:/Services/Flutter/flutter`, JDK21 trong `.toolchain/java`. Máy ít RAM nên dùng một Gradle worker và JVM khoảng 1536 MiB. Không chạy Flutter tests song song với build release.

```powershell
# Tại thư mục gốc, sau build:
VietHandOCR_API_Release/.venv/Scripts/python.exe Mobile/tools/package_release.py --validation-prefix server-only
```

Verifier kiểm chữ ký, alignment16KiB, deep link, không có model/ORT hoặc `:ocr` trong APK. [validation.json](validation.json) ghi số test và hash thật. Chưa cài/run APK mới trên điện thoại thật.

## Cấu hình cloud

`assets/config/supabase.json` chứa project URL và **publishable key công khai**. Không được thêm service-role hoặc Google Client Secret vào file này. Sinh lại bằng `Server/tools/configure_supabase.py` khi đổi project. Deep link Android: `vn.pbl4.vietocr://auth/callback`, flow PKCE qua system browser.

Mã native local OCR cũ được lưu ngoài client tại `Server/archive/local-clients/` trên máy (Git bỏ qua), không đóng gói. Các công cụ export model cũ không dùng để build app mới; server giữ checkpoint PyTorch và pipeline nhóm AI.
