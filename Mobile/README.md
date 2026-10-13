# VietOCR Mobile — Flutter / Dart

Ứng dụng **Android** nhận diện chữ Việt **offline trên điện thoại**, dùng trọng số hiện có trong `VietHandOCR_API_Release/AI.py` đã chuyển thành ONNX. Không cần Python/server/Wi-Fi khi sử dụng; model nằm trong gói cài. BLE chỉ gửi trạng thái cho ESP32-S3.

- Chụp bằng camera hoặc chọn nhiều ảnh, tổng tối đa **10 ảnh/lượt**.
- Theme tối mặc định, nút đổi sáng/tối và lưu lựa chọn.
- Xem/phóng to/xoay/xóa ảnh, chọn chế độ một dòng hoặc tự tách nhiều dòng.
- Đọc tuần tự, tiến trình theo ảnh/dòng, hủy ở giữa các bước; lỗi một ảnh vẫn tiếp tục ảnh khác.
- Sửa, sao chép từng ảnh/tất cả và xuất TXT UTF-8 qua trình chia sẻ Android.
- Lưu ảnh/kết quả trong vùng riêng của app, khôi phục khi mở lại; khôi phục ảnh từ image picker nếu Android hủy Activity khi chụp.
- Quét/chọn trợ lý BLE, thử còi, bật/tắt tiếng, heartbeat và nối lại thiết bị đã chọn. Có nút bật Bluetooth bằng hộp thoại hệ thống Android.
- Đưa app xuống nền sẽ hủy OCR, lưu phiên và gửi SLEEP/ngắt BLE. Mở camera/thư viện bằng app được xử lý riêng. Nếu hệ điều hành dừng app đột ngột, firmware tự ngủ khi mất kết nối/heartbeat.

## Chạy và build

Đã chọn dependency tương thích **Flutter 3.41.4 / Dart 3.11.1**, Android Gradle Plugin 8.13.2, Gradle 8.14, Java 17 hoặc 21. `permission_handler` được khóa ở 12.0.1 để tránh implementation mới yêu cầu AGP 9. Dùng `pubspec.lock` đã kèm theo.

Yêu cầu Android 8.0+ (API 26). Model FP32 khoảng **146 MiB**, cần thêm dung lượng khi app trích model lần đầu. Nên thử trên điện thoại có ít nhất 4 GB RAM; chưa đo RAM/tốc độ trên điện thoại thật. CPU chạy hai thread, giữ session để tái sử dụng.

Từ thư mục `Mobile`:

```powershell
flutter pub get
flutter analyze
flutter test
flutter run
flutter build apk --release --target-platform android-arm64
```

APK đã giữ riêng ở **`dist/VietOCR-arm64.apk`** sau khi dọn cache. Những lần build tiếp theo tạo `build/app/outputs/flutter-apk/app-release.apk`. Bản ARM64 dành cho điện thoại Android 64-bit. Release hiện ký bằng debug key để cài thử PBL; cần signing riêng trước khi đưa lên Play Store. Gói release không khai báo quyền Internet. Lần đầu build cần Internet để tải thư viện; sau khi cài, OCR không tải model hay gọi dịch vụ mạng.

Trên máy Windows hiện tại có JDK 21 riêng trong `.toolchain/java/` ở gốc repository; nếu Java mặc định là 25, chọn JDK 21 trước khi build:

```powershell
$env:JAVA_HOME = (Get-ChildItem ../.toolchain/java -Directory | Select-Object -First 1).FullName
$env:PATH = "$env:JAVA_HOME/bin;$env:PATH"
flutter build apk --release --target-platform android-arm64
```

Chỉ giữ platform Android trong dự án. Cấu hình build nâng `compileSdk` của thư viện BLE 5.5 lên 36 để tương thích AndroidX từ Flutter; không sửa trực tiếp package trong Pub cache. Sau khi kiểm tra/build, cache Flutter/Gradle trong dự án và máy ảo thử nghiệm được xóa; model, ảnh mẫu, mã nguồn và APK riêng trong `dist` được giữ lại. JDK 21 trong `.toolchain/java` là công cụ build Android được giữ để dùng lại.

Để dọn cache dự án những lần sau, đóng tác vụ Flutter/Gradle rồi chạy `powershell -ExecutionPolicy Bypass -File tools/clean_cache.ps1` từ `Mobile`. Script chép APK release vào `dist` trước khi xóa cache; không xóa model hoặc cache SDK/Pub dùng chung.

## Model và kiểm chứng

Hai file `assets/models/vietocr_encoder.onnx` và `vietocr_decoder.onnx` đã được tạo trong workspace. **Không commit file ONNX vào Git**; khi clone mới phải chuyển đổi lại hoặc tự chép từ máy này. Manifest chứa từ vựng, kích thước, SHA-256 và thông số chuẩn hóa. App kiểm tra SHA-256 khi trích/nạp bản cache, tránh dùng model hỏng hoặc phiên bản cũ.

Chuyển đổi từ thư mục gốc repository, dùng Python 3.11 của desktop:

```powershell
.\VietHandOCR_API_Release\.venv\Scripts\python.exe -m pip install -r Mobile/tools/requirements-export.txt
.\VietHandOCR_API_Release\.venv\Scripts\python.exe -X utf8 Mobile/tools/export_onnx.py
# Chỉ kiểm chứng lại model đã xuất:
.\VietHandOCR_API_Release\.venv\Scripts\python.exe -X utf8 Mobile/tools/export_onnx.py --verify-only
```

Script giữ nguyên trọng số/từ vựng của `vgg_transformer_final.pth`, tách encoder và autoregressive decoder, xuất opset 17 với chiều rộng ảnh/số token động. Attention biểu diễn bằng các phép toán ONNX cơ bản. Không lượng tử hóa trong bản này.

`assets/models/verification.json` ghi kết quả so sánh PyTorch/ONNX ở chiều rộng 32, 90, 256, 510, 1024 và prefix token 1, 2, 8, 17; bốn ảnh kiểm chứng trả cùng văn bản. Điều này kiểm chứng phép chuyển đổi, không phải đánh giá độ chính xác OCR trên mọi nét chữ.

Tiền xử lý mobile viết bằng Dart chạy trong isolate: EXIF, xoay, giới hạn kích thước, nền trắng cho ảnh trong suốt, grayscale, deskew, CLAHE khi tương phản thấp, tách dòng, Lanczos và tensor RGB CHW cao 32px. Bilinear deskew/Dart CLAHE khác đôi chút OpenCV; ảnh thực tế có thể cho kết quả khác desktop. Có script kiểm tra dữ liệu đầu vào thật từ Dart với cả PyTorch/ONNX:

```powershell
# Trong Mobile:
dart run tools/prepare_fixtures.dart
../VietHandOCR_API_Release/.venv/Scripts/python.exe -X utf8 tools/verify_mobile_pipeline.py
```

`assets/models/mobile_preprocessing_verification.json` ghi kết quả so sánh trên ảnh mẫu ở cả hai chế độ. Kiểm tra native Android trên emulator hoặc thiết bị dành cho test:

```sh
flutter test integration_test/offline_ocr_test.dart -d <device-id>
```

Integration test nạp model đóng gói, so văn bản từ tensor tham chiếu với PyTorch và chạy lại OCR từ ảnh qua Dart + plugin native. **Chưa chạy xong kiểm tra native** trong môi trường này do ADB bị treo khi đọc thông tin emulator; máy ảo thử nghiệm đã được dọn. Unit/widget test kiểm tra giới hạn 10 ảnh, lưu/khôi phục, lỗi/hủy/thử lại, từ vựng/EOS, khung BLE/ACK và giao diện.

Kết quả hiện tại: analyzer sạch, **21 unit/widget test đạt**, APK ARM64 build và xác minh chữ ký thành công. Hai model trong APK đúng SHA-256 của bản ONNX đã kiểm chứng. Xem `validation.json` để đối chiếu checksum/kích thước APK giữ trong `dist`.

## BLE với ESP32-S3

Nạp firmware trong [pbl4](../pbl4/README.md), ngắt kết nối desktop/nRF Connect trước khi dùng mobile. Mở tab **Trợ lý → Bật Bluetooth → Tìm trợ lý → VietOCR-Assistant**. Cấp quyền Thiết bị ở gần; Android 8–11 cần quyền và dịch vụ vị trí để quét BLE. Không cần ghép đôi trong danh sách Bluetooth của hệ điều hành.

App dùng NUS service `6e400001-b5a3-f393-e0a9-e50e24dcca9e`, RX `...0002`, TX Notify `...0003`. Gửi một lệnh ASCII mỗi dòng và chờ ACK, ghép notification bị chia nhỏ, `PING` mỗi 4 giây. Timeout sẽ hủy kết nối trước khi thử lại để tránh ACK cũ bị nhận nhầm. Gửi `PROCESS` trước `PROGRESS`, không khởi động lại animation ở mỗi cập nhật. Xem [giao thức đầy đủ](../pbl4/docs/BLE_PROTOCOL.md).

OCR trên điện thoại thật, BLE thật, camera và thời lượng pin chưa được kiểm chứng trên phần cứng trong môi trường Windows này. TMB12A05 phát beep báo trạng thái; không phát giọng nói.

## Giới hạn OCR

Model nhận diện từng dòng, hỗ trợ tốt nhất trang giấy sáng, một cột. Chưa có phát hiện chữ trong cảnh vật, bảng/nhiều cột hoặc sửa phối cảnh. Tài liệu tối đa 150 dòng/ảnh; ảnh gốc quá 40 megapixel hoặc file chọn vượt 40 MB được từ chối. Dòng vượt giới hạn sinh token báo lỗi để người dùng cắt ảnh nhỏ hơn. Nên kiểm tra và sửa dấu sau nhận diện.

Ảnh và kết quả được lưu trong vùng riêng của ứng dụng, không tự gửi ra ngoài. Nút chia sẻ chỉ xuất văn bản khi người dùng chọn. Gỡ app/xóa dữ liệu sẽ xóa phiên đã lưu; hãy xuất TXT nếu cần giữ lâu dài.
