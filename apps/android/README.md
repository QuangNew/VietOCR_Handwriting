# VietOCR Android

App Flutter dùng webcam Raspberry và OCR trên máy chủ. Đăng nhập Google để mở tài liệu.

1. Bấm **Chụp tài liệu** để mở webcam hoặc **Chọn ảnh** để lấy ảnh từ thư viện.
2. Bấm một tài liệu để xem ảnh, **Cắt và chỉnh ảnh**, hoặc chọn **Một dòng** khi ảnh chỉ có một dòng chữ.
3. Bấm **Gửi ảnh này** cho tài liệu đang mở. Đánh dấu những ảnh cần gửi và bấm **Gửi N ảnh** để xử lý nhiều ảnh.
4. Kết quả hiện ngay bên dưới ảnh. Bạn có thể sửa, sao chép hoặc xuất `.txt`. Bộ lọc **Đã đọc** gom các tài liệu đã có văn bản.

**Cài đặt** chứa tài khoản, hạn mức, địa chỉ Raspberry, giao diện tối, lịch sử máy chủ và nhật ký. Địa chỉ triển khai mặc định là `https://api.quangnew.tech`. Khi mất kết nối, ảnh nháp của tài khoản đã được xác minh được giữ trên máy.

**Tạm dừng** ngắt lượt gửi đang thực hiện trên Android. Máy chủ tiếp tục xử lý ảnh đã nhận đủ. Khi mở lại app, kết quả đã nhận được khôi phục theo mã lượt gửi. App chuẩn bị ảnh truyền tự động khi bấm Gửi. Ảnh lưu trong thư viện tài liệu vẫn giữ bản gốc.

## Kiểm tra và build

Từ thư mục gốc của repo:

```powershell
cd apps/android
$env:JAVA_HOME=(Resolve-Path ../../.toolchain/java/jdk-21.0.12.1+1).Path
$env:PATH=$env:JAVA_HOME+'\bin;'+$env:PATH
flutter pub get --offline
flutter analyze --no-pub
flutter test --no-pub --concurrency=1
flutter build apk --release --target-platform android-arm64 --no-pub
```

Bản **4.1.0+21** dùng gói `dist/VietOCR-4.1.0-refactor-arm64.apk`. SDK Android, Flutter và JDK có thể đặt ở thư mục riêng của từng máy. Đọc mục Android trong [DevTodo.md](../../DevTodo.md) để cài APK và thiết lập kết nối.
