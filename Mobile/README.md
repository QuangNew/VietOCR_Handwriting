# VietOCR Android v4

Flutter Android client cho luồng **Google → Raspberry → inference server**. Không có model local, Bluetooth/ESP32 hoặc camera điện thoại. Webcam USB nằm trên Pi; import dùng Android Photo Picker.

1. Mở **Google & Raspberry**, cấu hình HTTPS của Pi (`https://api.quangnew.tech` sau khi DNS/tunnel sẵn sàng).
2. Đăng nhập Google bằng system browser. Workspace chỉ mở sau khi Pi xác minh; tài khoản đã xác minh có thể mở bản nháp riêng khi mất mạng.
3. Chụp trên tab Camera Raspberry hoặc tải file. Xem lại 3 giây/Skip chỉ lưu bản nháp; không gửi OCR.
4. Nhấn **Gửi** để upload từng khối tối đa 1 MiB qua Pi. Server nhận đủ/kiểm ảnh/commit rồi mới trừ lượt. Kết quả đọc trực tiếp từ compute.
5. Ảnh đã nhận tiếp tục xử lý khi app đóng. Khi mở lại, client chỉ đọc lại những job đã biết; không tự upload các bản nháp mới.

Giữ zoom, crop hình/vẽ tự do/xoay vùng chọn, đen trắng OCR, sửa/xuất text, lưu/chia sẻ ảnh, log và lịch sử tài khoản. JPEG/PNG gốc được giữ byte-for-byte; ảnh xoay phục vụ upload được lưu cùng thư mục riêng của tài khoản để tiếp tục đúng job sau gián đoạn.

Mỗi tài khoản tối đa 500 ảnh/ngày và 30 ảnh được nhận trong 60 giây; admin có thể hạ. Preview, snapshot và upload chưa đủ không tính lượt. Credential phiên mã hoá Android Keystore, không dùng API key cố định để gọi OCR.

## Build trên máy hiện tại

```powershell
cd Mobile
$env:JAVA_HOME=(Resolve-Path ../.toolchain/java/jdk-21.0.12.1+1).Path
$env:PATH=$env:JAVA_HOME+'\bin;'+$env:PATH
flutter pub get --offline
flutter analyze --no-pub
flutter test --no-pub --concurrency=1
flutter build apk --release --target-platform android-arm64 --no-pub
```

Dùng JDK **21**, không dùng Oracle JDK25 mặc định cho Gradle hiện tại. SDK hiện tại: `C:/Users/QuangNew/AppData/Local/Android/sdk`; Flutter: `C:/Services/Flutter/flutter`. Gradle giới hạn heap2GB và2worker để tránh chiếm hết RAM. Chạy kiểm tra/build lần lượt khi máy đang nhiều ứng dụng.

Bản hiện tại: **4.0.1+19**, đầu ra `dist/VietOCR-4.0.1-refactor-arm64.apk` sau khi kiểm tra build. Bản4.0.0 giữ để rollback. Kiểm [báo cáo tiến độ](../docs/REFACTOR_PROGRESS.md) để đối chiếu artifact/mã nguồn. Chưa xác nhận chạy APK v4 trên điện thoại thật; sideload vẫn dùng signing baseline, không coi là bản Play Store.

`assets/config/supabase.json` chỉ chứa project URL/publishable key công khai. Callback Google: `vn.pbl4.vietocr://auth/callback`. Không đặt service-role, Google Client Secret hoặc machine token vào app.

Chọn ảnh cần gửi bằng checkbox. Crop/đen trắng/lật gương tạo bản nháp mới và giữ
nguyên bản gốc, bỏ chọn bản nguồn để tránh gửi trùng. Tối ưu truyền ảnh là tuỳ chọn
PNG/JPEG95 không đổi kích thước; mặc định gửi bản gốc. Log che token/key trước khi
lưu hoặc xuất. Đổi tài khoản đóng camera/trình sửa và chặn cả token refresh đang
dở, không chuyển tác vụ ảnh cũ sang tài khoản mới.
