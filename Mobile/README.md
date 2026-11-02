# VietOCR Mobile — Flutter / Dart

**Bản hiện tại: 1.9.0+14, firmware camera: 3.0.0-ov5640.**
Cài APK tại [dist/VietOCR-arm64.apk](dist/VietOCR-arm64.apk), dành cho Android
8 trở lên, ARM64. Có thể cài đè bản trước vì giữ cùng chữ ký thử nghiệm.
Kết nối BLE, đợi Wi-Fi hiện **Đã kết nối**, rồi mở **Camera OV5640**.
Preview dùng UDP để theo kịp firmware mới; ảnh chụp dùng HTTP có kiểm CRC32.
Model OCR offline và trọng số FP32 giữ nguyên trong lượt này.

Trong trang **Camera OV5640**, bấm biểu tượng **Cấu hình camera** (thanh trượt)
ở góc trên. Chọn preset **Mượt / Cân bằng / Chi tiết**, hoặc tự chỉnh độ phân
giải preview, JPEG, giới hạn FPS, màu sắc, cân bằng trắng, phơi sáng/gain,
hiệu ứng, lật ngang/dọc và autofocus. Bấm **Áp dụng** để gửi tới camera; preview mở lại
sau khi ESP32 xác nhận. **Mặc định** chỉ đổi các ô đang chỉnh, cần Áp dụng.
Bật **Nhớ cấu hình trên ESP32** để lưu flash/NVS, giữ qua ngắt BLE và mất điện.
App chờ xác nhận áp dụng và đọc lại NVS trước khi báo đã lưu.
Tham khảo cách tổ chức điều khiển từ
[esp32-cam-webserver](https://github.com/easytarget/esp32-cam-webserver);
[API camera của dự án](../pbl4/docs/CAMERA.md#cấu-hình-camera-trong-app).

Wi-Fi hiện tên mạng/IP ngay sau khi kết nối BLE và tự cập nhật mỗi 5 giây.
Hộp Wi-Fi hiện mạng đã lưu trên ESP32, không tự quét hoặc yêu cầu nhập lại
mật khẩu. **Kiểm tra LAN** chỉ kiểm tra đường HTTP; trạng thái cảm biến
hiện riêng trong trang camera. Mất BLE thì app báo chưa biết trạng thái Wi-Fi,
không giữ nhãn đã kết nối của phiên cũ.

Preview mặc định **640×480/QS18**, chỉnh được từ **320×240** tới **2592×1944**,
giữ góc nhìn 4:3; ảnh chụp **2592×1944/QS8**, đủ 5 MP. Mở trang camera lớn để
chụm tay zoom; sau chụp, ảnh hiện **3 giây** hoặc đến khi bấm **Bỏ qua · Chụp
tiếp**, rồi tự vào hàng đợi và camera mở lại preview. Bảng tiến trình nằm ở
góc dưới bên phải, có thể thu gọn. Trang chụp giữ mở đến khi người dùng đóng.
Bấm ảnh gốc để xem lớn/zoom/crop; nút tải xuống mở trình chọn nơi lưu Android.
JPEG native được giữ nguyên byte. Crop tạo ảnh vùng mới cho OCR, không sửa
ảnh gốc. Không thêm quyền toàn bộ bộ nhớ và không đổi model trong lượt này.
Lật gương trái–phải được đặt trên cảm biến, lưu NVS; preview, JPEG lưu và ảnh
đưa vào OCR cùng hướng. App đọc hướng đang lưu, không tự lật lần nữa hoặc ghi
đè cấu hình của desktop. Có thể đổi lại trong **Cấu hình camera → Hướng ảnh**.
Preview 5 MP cần nhiều băng thông hơn; giữ 640×480 để ưu tiên mượt. Giới hạn
FPS là mức trần, không bảo đảm FPS thực. Giao thức UDP dùng tối đa hai ảnh đang
ghép, kiểm CRC32 từng ảnh, tự gia hạn mỗi 20 giây; đóng trang sẽ đóng socket.
Bản 1.9.0 đã build và kiểm tra tự động, chưa cài/chạy trên điện thoại. Lần
kiểm tra phần cứng cuối không thấy COM8/quảng bá BLE nên chưa đo FPS của app.

**Nếu ESP32 reset lặp ở firmware 2.3.1:** nạp **2.3.2-coexfix** để sửa
cấu hình Wi-Fi modem sleep khi chạy chung BLE; không cần cài lại APK,
không cần xóa Wi-Fi trên bo. Chi tiết ở [CAMERA.md](../pbl4/docs/CAMERA.md).

**Wi-Fi nhớ mạng trên bo:** với firmware **2.3.1-blewifi**, cấu hình/kết nối
Wi-Fi thành công một lần, ESP32 sẽ nhớ qua reset/tắt nguồn và tự kết nối lại
khi mất mạng. APK **1.6.1+10** hiện có dùng được, không cần cài lại. Scan và
nhập mạng mới tạm ưu tiên hơn reconnect. Ảnh vẫn đi qua Wi-Fi, BLE điều khiển.
Mỗi khi app kết nối BLE, ESP32 tự tìm/kết nối mạng đã lưu ngay, không cần mở
Wi-Fi camera hay nhấn Quét/Kết nối. Dữ liệu nằm trên flash/NVS của bo, vẫn
còn khi ngắt BLE, reset hoặc tắt nguồn.

**1.6.1+10:** kiểm tra HTTP trước `CAM OPEN`, không bật cảm biến khi LAN chưa
sẵn sàng; báo rõ không tìm thấy mạng/mật khẩu thay vì lỗi camera chung.
Firmware **2.2.1-recovery** sửa quét Wi-Fi lúc bo đang thử kết nối mạng cũ:
dừng lần kết nối offline, đợi driver rồi quét nền với tối đa ba lần thử.
Không xóa Wi-Fi đã lưu, không thay model hay chất lượng ảnh chụp. Bản này
chỉ sửa/build; chưa chạy thử trên ESP32 hoặc điện thoại thật.

**1.6.0+9:** xem camera bằng **MJPEG liên tục** trên Wi-Fi cổng **81**,
thay cho tải từng JPEG 3 MP. Cần nạp firmware **2.2.0-stream** vào ESP32.
Xem trước **2048×1536**, cùng cấu hình ảnh chụp; tốc độ thực phụ thuộc LAN.
Ảnh chụp OCR vẫn **2048×1536, quality6**, kiểm CRC32. Đóng stream trước khi
chụp/đóng camera/ngắt BLE/đưa app xuống nền. Log ghi thời gian khung hình đầu
tiên và lỗi stream; không tự chuyển ảnh sang BLE chậm. Model FP32 giữ nguyên.
Bản này chỉ build; người dùng tự nạp firmware và cài APK.

**1.5.0+8:** cần firmware camera **2.1.0-wifi**. Nút Kiểm tra thử endpoint
HTTP `/health` thật; lỗi mạng có IP/cổng và nguyên nhân socket. Chụp OV3660
yêu cầu Wi-Fi/HTTP hoạt động, báo lỗi trước khi chụp nếu không tới được bo.
Ảnh vẫn đủ 2048×1536, CRC32 bắt buộc; BLE giữ điều khiển/theme/cấu hình Wi-Fi.
Không thay model FP32. Bản này chỉ sửa/build, chưa nạp/cài thiết bị thật.

**1.4.1+7:** giải thích rõ khi ESP32 thiếu firmware Wi-Fi thay vì chỉ hiện
`ERR INVALID_COMMAND`, phân biệt đang kết nối/quét lỗi. Bo trên COM8 đã nạp
`2.0.1-wifi` và quét được mạng qua BLE ngày 27/10. Nếu dùng bo khác, cần nạp
đúng profile camera; cài APK không tự cập nhật ESP32. Phần OCR/model giữ FP32
như 1.4.0. APK hiện tại và checksum xem `validation.json`.

Ứng dụng **Android** nhận diện chữ Việt **offline trên điện thoại**, dùng trọng số hiện có trong `VietHandOCR_API_Release/AI.py` đã chuyển thành ONNX. Không cần Python/server/Internet cho OCR; model nằm trong gói cài. BLE điều khiển trợ lý và cấu hình Wi-Fi; Wi-Fi LAN dùng để xem/nhận ảnh OV5640.

**Bản 1.4.0+6 (27/10/2026):** dùng model **FP32 gốc**, tổng 152.819.648 byte,
thay cho bản lưu trọng số FP16 để đối chiếu lỗi trên điện thoại. So sánh trên
máy tính: cả hai model trả cùng kết quả ở 20 trường hợp của 5 ảnh mẫu, vì vậy
chưa có bằng chứng việc nén là nguyên nhân lỗi toàn số trên Android. Nút kiểm tra
AI giờ yêu cầu nội dung ảnh chuẩn khớp hoàn toàn; văn bản không rỗng vẫn có thể
bị đánh giá sai. Lõi Java/JNI đã qua 20 tensor thật; chưa chạy APK mới trên máy thật.

- Hai nguồn ảnh: camera/thư viện điện thoại, hoặc **OV3660 trên trợ lý**. Không còn giới hạn 10 ảnh; ảnh được lưu file và xử lý tuần tự.
- Trong thẻ OV3660, mở **Wi-Fi camera → Quét mạng → chọn/nhập SSID và mật khẩu → Kết nối → Kiểm tra**. Dùng mạng 2.4 GHz cho ESP32; điện thoại cần cùng LAN, không dùng mạng khách cách ly thiết bị. Mật khẩu lưu trong NVS `vietocr-wifi` trên ESP32, không lưu trong app/log.
- Nhấn **Xem camera** để stream theo cấu hình đang lưu trên ESP32 (mặc định **640×480/QS18**). Nhấn **Chụp OV5640** sẽ dừng stream, lấy nét và nhận JPEG gốc **2592×1944** qua Wi-Fi, kiểm CRC32 rồi xem lại 3 giây. Bỏ qua hoặc hết 3 giây sẽ đưa vào OCR và mở lại preview. TFT luôn hiển thị trợ lý. HTTP :80 dành cho cấu hình/ảnh chụp/kiểm tra, UDP :82 dành cho preview. Có thể nhận thêm khi OCR đang chạy; ảnh xong không bị đọc lại.
- Nút **Kiểm tra AI trên máy này** chạy ảnh mẫu đóng gói qua model thật và ghi kết quả/lỗi vào Log, không thêm ảnh mẫu vào danh sách.
- Theme tối mặc định, nút đổi sáng/tối và lưu lựa chọn; đồng bộ nền TFT qua BLE.
- Xem/phóng to/xoay/xóa ảnh, chọn chế độ một dòng hoặc tự tách nhiều dòng.
- Đọc tuần tự, tiến trình theo ảnh/dòng, hủy ở giữa các bước; lỗi một ảnh vẫn tiếp tục ảnh khác.
- Sửa, sao chép từng ảnh/tất cả và xuất TXT UTF-8 qua trình chia sẻ Android.
- Lưu ảnh/kết quả trong vùng riêng của app, khôi phục khi mở lại; khôi phục ảnh từ image picker nếu Android hủy Activity khi chụp.
- Quét/chọn trợ lý BLE, thử còi, bật/tắt tiếng, heartbeat và nối lại thiết bị đã chọn. Có nút bật Bluetooth bằng hộp thoại hệ thống Android.
- Tab **Log** ghi bước OCR, lỗi Dart/Java gốc, phiên bản app, RAM và BLE TX/RX; xem chi tiết, lọc lỗi, sao chép hoặc xuất TXT. Log lưu cục bộ và được giới hạn dung lượng.
- Đưa app xuống nền sẽ hủy OCR, lưu phiên và gửi SLEEP/ngắt BLE. Mở camera/thư viện bằng app được xử lý riêng. Nếu hệ điều hành dừng app đột ngột, firmware tự ngủ khi mất kết nối/heartbeat.

Phần OV3660 cần firmware camera và chuyển dây TFT/còi vì trùng GPIO với camera
tích hợp. Xem [bảng dây và luồng camera](../pbl4/docs/CAMERA.md). Sau khi người
dùng xác nhận chuyển dây ngày 26/10, firmware mặc định chuyển sang profile camera.

## Chạy và build

Đã chọn dependency tương thích **Flutter 3.41.4 / Dart 3.11.1**, Android Gradle Plugin 8.13.2, Gradle 8.14, Java 17 hoặc 21. `permission_handler` được khóa ở 12.0.1 để tránh implementation mới yêu cầu AGP 9. Dùng `pubspec.lock` đã kèm theo.

Yêu cầu Android 8.0+ (API 26). Bản 1.4.0 dùng hai model FP32 gốc khoảng **145,7 MiB**; bản nén cũ giữ trong `.toolchain/compact-models` để đối chiếu. Đây là dung lượng model, chưa phải dung lượng APK hoặc RAM thực tế. App cần thêm dung lượng khi trích model lần đầu. CPU chạy hai thread; session được tái sử dụng khi app ở trước và giải phóng khi xuống nền. Cache ảnh giao diện giới hạn 24 MiB để chừa RAM cho OCR.

OCR dùng ONNX Runtime Java 1.23.2 trong tiến trình Android riêng `:ocr`. Model được chép từ APK bằng buffer nhỏ, kiểm tra SHA-256 rồi nạp từ file. Flutter gửi tensor từng dòng qua file tạm; dịch vụ Kotlin/Java quản lý tensor và sinh token. Khi tiến trình AI dừng hoặc không phản hồi, app báo lỗi, giữ kết quả đã có và cho phép thử lại. Cơ chế này giảm ảnh hưởng của lỗi native; vẫn cần kiểm tra trên máy thật để xác nhận lỗi người dùng gặp.

Service Kotlin quản lý tiến trình/file; lõi `OnnxRecognizer.java` giữ session,
tensor và vòng sinh token. Lõi này được chạy trực tiếp qua Java/JNI trên Windows
để đối chiếu với Python, gồm cả ảnh sau bước nhập/chuẩn hóa PNG. Một dòng rỗng
không làm mất các dòng còn lại; nếu toàn bộ ảnh không có kết quả, app báo lỗi
và hướng dẫn xem Log. Lỗi thư viện native, nạp model và hết bộ nhớ được phân biệt.

**Sửa crash release 1.2.1+4:** ảnh log của Xiaomi 23106RN0DA / Android 35 ghi
`ocr_exit_reason=5` tại encoder. Android định nghĩa mã 5 là
[lỗi native](https://developer.android.com/reference/android/app/ApplicationExitInfo#REASON_CRASH_NATIVE),
không phải bằng chứng ảnh quá nhỏ hay thiếu RAM. Kiểm tra APK 1.2.0+3 cho thấy
R8 đã loại `TensorInfo` và đổi tên `OnnxJavaType`/`OrtException`, trong khi JNI
ONNX gọi các lớp bằng tên gốc. Bản mới thêm `proguard-rules.pro` theo
[quy tắc ONNX Runtime chính thức](https://onnxruntime.ai/docs/build/android.html#note-proguard-rules-for-r8-minimization-android-app-builds-to-work),
giữ các lớp/constructor đó và kiểm tra trực tiếp APK cùng mapping sau build.
Đây là lỗi đóng gói đã xác nhận; vẫn cần chạy bản mới trên điện thoại để xác
nhận hết lỗi native người dùng gặp. Kiểm tra Java trên máy tính không thay
thế bước kiểm tra R8 của Android release.

Khi gặp lỗi: mở **Log → Chỉ lỗi → mở dòng lỗi → Xuất log**. Có thể xem thêm các
dòng INFO/DEBUG để biết lỗi xảy ra ở tách dòng, nạp model, encoder hay decoder.
Log native còn sau khi tiến trình OCR bị Android dừng; mở app lại vẫn đọc được.
Không ghi ảnh hoặc nội dung văn bản OCR vào log. Nút **Xóa log** xóa lịch sử Dart
và native. Bản mới ghi cả version/build ở dòng khởi động để phân biệt APK cũ.

Từ thư mục `Mobile`:

```powershell
flutter pub get
flutter analyze
flutter test
flutter run
flutter build apk --release --target-platform android-arm64
```

APK hiện được giữ riêng ở **`dist/VietOCR-arm64.apk`**. Những lần build tiếp theo tạo `build/app/outputs/flutter-apk/app-release.apk`. Bản ARM64 dành cho điện thoại Android 64-bit. Release hiện ký bằng debug key để cài thử PBL; cần signing riêng trước khi đưa lên Play Store. Bản 1.4.0 khai báo quyền Internet cho HTTP camera trên LAN; OCR không gửi ảnh lên Internet, không tải model hoặc gọi server AI.

Bản trước **1.3.0+5**: APK **109.349.615 byte (104,3 MiB)**, giảm từ
191.124.940 byte (182,3 MiB), khoảng **43%**. Chữ ký giống bản trước nên có thể
cài cập nhật bằng `adb install -r` mà không cần gỡ app. APK đã kiểm tra chữ ký,
ABI ARM64, checksum model, cấu hình dịch vụ OCR riêng và căn chỉnh 16 KiB của
ZIP/ELF. Dung lượng sau cài đặt còn gồm cache model và ảnh của bạn.
Giữ bản trước 1.2.1+4 tại `.toolchain/VietOCR-arm64-1.2.1+4.apk`, bản 1.2.0+3
tại `.toolchain/VietOCR-arm64-1.2.0+3.apk`, bản 1.1.0+2
tại `.toolchain/VietOCR-arm64-1.1.0+2.apk`; bản 1.0.0+1
vẫn ở `.toolchain/previous-VietOCR-arm64.apk`. Mapping R8 của bản mới lưu cạnh
APK tại `dist/VietOCR-1.6.1+10-mapping.txt` để giải tên class/method trong log release. Xem `validation.json` để biết checksum/dung lượng bản hiện tại, không dùng số dung lượng của bản nén cũ.

Sau mỗi build release, kiểm tra JNI ngay trên APK đã rút gọn (từ `Mobile`):

```powershell
../VietHandOCR_API_Release/.venv/Scripts/python.exe tools/check_jni_keeps.py build/app/outputs/flutter-apk/app-release.apk build/app/outputs/mapping/release/mapping.txt
```

Kiểm tra này từ chối APK 1.2.0+3 cũ và xác nhận 60 lớp ONNX gốc giữ tên trong
bản mới, gồm các lớp callback JNI và constructor `TensorInfo` cần sau encoder.

Dùng Android CLI để cài các thành phần build nếu máy chỉ mới có ADB:

```powershell
android --no-metrics info
android --no-metrics sdk install platform-tools
android --no-metrics sdk install 'platforms;android-36'
android --no-metrics sdk install 'build-tools;35.0.0'
android --no-metrics sdk install 'ndk;28.2.13676358'
# Khi muốn cài bản APK lên điện thoại đã cấp quyền USB debugging:
adb devices -l
adb install -r build/app/outputs/flutter-apk/app-release.apk
```

ADB dùng để giao tiếp thiết bị; build còn cần SDK platform, build-tools và NDK. Nếu SDK đặt ngoài đường dẫn mặc định, cấu hình `ANDROID_HOME` / `ANDROID_SDK_ROOT` và `android/local.properties` trỏ cùng thư mục mà `android info` báo.

Trên máy Windows hiện tại có JDK 21 riêng trong `.toolchain/java/` ở gốc repository; nếu Java mặc định là 25, chọn JDK 21 trước khi build:

```powershell
$env:JAVA_HOME = (Get-ChildItem ../.toolchain/java -Directory | Select-Object -First 1).FullName
$env:PATH = "$env:JAVA_HOME/bin;$env:PATH"
flutter build apk --release --target-platform android-arm64
```

Chỉ giữ platform Android trong dự án. Cấu hình build nâng `compileSdk` của thư viện BLE 5.5 lên 36 để tương thích AndroidX từ Flutter; không sửa trực tiếp package trong Pub cache. Cache Flutter/Gradle có thể dọn bằng script bên dưới; model, ảnh mẫu, mã nguồn và APK riêng trong `dist` được giữ lại. JDK 21 trong `.toolchain/java` và SDK Android được giữ để dùng lại.

Để dọn cache dự án những lần sau, đóng tác vụ Flutter/Gradle rồi chạy `powershell -ExecutionPolicy Bypass -File tools/clean_cache.ps1` từ `Mobile`. Script chép APK release vào `dist` trước khi xóa cache; không xóa model hoặc cache SDK/Pub dùng chung.

## Model và kiểm chứng

Hai file `assets/models/vietocr_encoder.onnx` và `vietocr_decoder.onnx` đã được tạo trong workspace. **Không commit file ONNX vào Git**; khi clone mới phải chuyển đổi lại hoặc tự chép từ máy này. Manifest chứa từ vựng, kích thước, SHA-256 và thông số chuẩn hóa. App kiểm tra SHA-256 khi trích/nạp bản cache, tránh dùng model hỏng hoặc phiên bản cũ.

Chuyển đổi từ thư mục gốc repository, dùng Python 3.11 của desktop:

```powershell
.\VietHandOCR_API_Release\.venv\Scripts\python.exe -m pip install -r Mobile/tools/requirements-export.txt
.\VietHandOCR_API_Release\.venv\Scripts\python.exe -X utf8 Mobile/tools/export_onnx.py
# Chỉ kiểm chứng lại bản FP32 chưa nén:
.\VietHandOCR_API_Release\.venv\Scripts\python.exe -X utf8 Mobile/tools/export_onnx.py --verify-only
# Tạo và kiểm chứng bản nhỏ, giữ bản FP32 trong .toolchain/fp32-models:
.\VietHandOCR_API_Release\.venv\Scripts\python.exe -X utf8 Mobile/tools/compact_models.py --install
```

Script export giữ nguyên trọng số/từ vựng của `vgg_transformer_final.pth`, tách encoder và autoregressive decoder, xuất opset 17 với chiều rộng ảnh/số token động. Attention biểu diễn bằng các phép toán ONNX cơ bản. `compact_models.py` chuyển trọng số Conv/MatMul sang lưu FP16, thêm Cast về FP32 trước phép tính để chạy CPU. Chỉ thay assets sau khi các ca so sánh văn bản đạt; bản FP32 gốc được giữ để phục hồi. `--verify-only` từ chối model đã nén vì ngưỡng sai số của kiểm chứng FP32 không áp dụng cho FP16.

`assets/models/compression_verification.json` là báo cáo **lịch sử của bản nén**, ghi mức **152.819.648 → 77.925.797 byte**. Bản 1.4.0 dùng lại FP32, không áp dụng nén trọng số. Đối chiếu mới nằm ở `five_sample_verification.json`: đủ 5 ảnh, raw/import và một/nhiều dòng (20 trường hợp). Trùng kết quả trên host chưa chứng minh chất lượng trên điện thoại. Các lỗi chính tả của model gốc vẫn có thể xuất hiện. `tools/restore_fp32.py` phục hồi assets từ bản FP32 đã lưu, kiểm checksum trước khi chép.

`assets/models/verification.json` ghi kết quả so sánh PyTorch/ONNX ở chiều rộng 32, 90, 256, 510, 1024 và prefix token 1, 2, 8, 17; bốn ảnh kiểm chứng trả cùng văn bản. Điều này kiểm chứng phép chuyển đổi, không phải đánh giá độ chính xác OCR trên mọi nét chữ.

Tiền xử lý mobile viết bằng Dart chạy trong isolate: EXIF, xoay, giới hạn kích thước, nền trắng cho ảnh trong suốt, grayscale, deskew, CLAHE khi tương phản thấp, tách dòng, Lanczos và tensor RGB CHW cao 32px. Bilinear deskew/Dart CLAHE khác đôi chút OpenCV; ảnh thực tế có thể cho kết quả khác desktop. Có script kiểm tra dữ liệu đầu vào thật từ Dart với cả PyTorch/ONNX:

```powershell
# Trong Mobile:
dart run tools/prepare_fixtures.dart
../VietHandOCR_API_Release/.venv/Scripts/python.exe -X utf8 tools/verify_mobile_pipeline.py
```

`assets/models/mobile_preprocessing_verification.json` ghi kết quả so sánh trên ảnh mẫu ở cả hai chế độ.

Ngày 21/10 đã kiểm tra **8 ca**: hai ảnh mẫu, một dòng/tự tách dòng, trước/sau
nhập PNG. PyTorch, ONNX Python và lõi Java/JNI cùng trả văn bản giống nhau.
`assets/models/java_runtime_verification.json` ghi kết quả và hash mã Java đã
chạy. Lệnh đối chiếu Java (JAR chính thức và JDK trong `.toolchain`, xem báo cáo
cài đặt):

```powershell
../VietHandOCR_API_Release/.venv/Scripts/python.exe -X utf8 tools/verify_java_pipeline.py
```

Kiểm tra Android thật khi có thiết bị:

```sh
flutter test integration_test/offline_ocr_test.dart -d <device-id>
```

Integration test nạp model đóng gói, so văn bản từ tensor tham chiếu với PyTorch và chạy lại OCR từ ảnh qua Dart + dịch vụ Kotlin. Chưa chạy kiểm thử trên điện thoại thật trong lần sửa này. Unit/widget test kiểm tra hàng đợi trên 10 ảnh, nhận thêm khi OCR chạy, CRC32/MTU/offset camera, nút kiểm tra AI, lưu/khôi phục, lỗi/hủy/thử lại, dừng batch khi AI chết, từ vựng/EOS, BLE/ACK, firmware cũ và vị trí chữ khi đổi theme.

Xem `validation.json` để đối chiếu phiên bản, kết quả kiểm tra và checksum/kích thước APK giữ trong `dist`. Việc build thành công và các kiểm tra tự động không thay thế thử OCR/BLE/camera trên điện thoại bị lỗi.

Lần kiểm tra ngày **25/10/2026**: analyzer sạch, **41 unit/widget test đạt**.
Desktop có **107 kiểm tra đạt**, gồm worker Bluetooth crash lần quét đầu, mở
lại hộp thoại, chờ dọn kết nối trước khi quét/nối tiếp, terminal còn sống sau GUI
crash và đổi theme khi cửa sổ hiển thị. Lần quét Windows ngày 21/10 thấy 53 thiết
bị quảng bá nhưng không thấy địa chỉ ESP32 đã lưu; chưa thử GATT trên board.
Firmware build camera và legacy thành công; **591 kiểm tra host đạt**, chưa nạp lên board.
Tránh chạy `flutter test` đồng
thời với `flutter build`: cả hai có thể ghi file đăng ký plugin được sinh tự động.
Với Flutter 3.41, build release bằng lệnh chuẩn có bước pub/plugin generation
như ví dụ trên. `--no-pub` sau khi chạy test có thể giữ registrant chứa
`IntegrationTestPlugin` trong khi Gradle release bỏ plugin dev này, gây lỗi
`package dev.flutter.plugins.integration_test does not exist`. Không sửa tay
`GeneratedPluginRegistrant.java`; chạy lại `flutter build apk --release`.

## BLE với ESP32-S3

Nạp firmware trong [pbl4](../pbl4/README.md), ngắt kết nối desktop/nRF Connect trước khi dùng mobile. Mở tab **Trợ lý → Bật Bluetooth → Tìm trợ lý → VietOCR-Assistant**. Cấp quyền Thiết bị ở gần; Android 8–11 cần quyền và dịch vụ vị trí để quét BLE. Không cần ghép đôi trong danh sách Bluetooth của hệ điều hành.

App dùng NUS service `6e400001-b5a3-f393-e0a9-e50e24dcca9e`, RX `...0002`, TX Notify `...0003`. App chờ radio sẵn sàng, quét trước khi kết nối và đăng ký notification trước `PING`/`WAKE`. Gửi một lệnh ASCII mỗi dòng và chờ ACK, ghép notification bị chia nhỏ, `PING` mỗi 4 giây. Timeout sẽ hủy kết nối trước khi thử lại để tránh ACK cũ bị nhận nhầm. Gửi `PROCESS` trước `PROGRESS`; tiến độ chưa xác định không gửi phần trăm giả.

Sau khi nối lại hoặc đổi giao diện, app gửi `THEME DARK` / `THEME LIGHT`. Lệnh chỉ đổi màu TFT, giữ trạng thái/tiến độ và không phát còi. **Cần nạp firmware mới trong `pbl4`** để dùng tính năng này. Firmware cũ từ chối THEME sẽ hiện lời nhắc cập nhật và vẫn nhận các lệnh OCR, tránh lặp ngắt/kết nối. Xem [giao thức đầy đủ](../pbl4/docs/BLE_PROTOCOL.md).

Giao diện dùng cùng kích thước/độ đậm chữ ở hai theme và tắt nội suy theme. Animation trợ lý chỉ vẽ lại vùng mặt; tiến trình OCR/BLE không dựng lại `MaterialApp`. Đọc ảnh, căn nghiêng và tạo tensor chạy trong isolate; bước tìm góc nghiêng giới hạn cả chiều rộng và chiều cao để tránh chậm với ảnh dọc.

Nếu cần điều tra lỗi sau này, **Trợ lý → Xuất chẩn đoán lỗi** tạo JSON gồm loại máy, RAM còn trống, bước AI gần nhất và lý do tiến trình AI kết thúc nếu Android cung cấp. File không chứa ảnh hoặc văn bản OCR; chỉ chia sẻ khi bạn chọn.

OCR trên điện thoại thật, BLE thật, camera và thời lượng pin chưa được kiểm chứng trên phần cứng trong môi trường Windows này. TMB12A05 phát beep báo trạng thái; không phát giọng nói.

## Giới hạn OCR

Model nhận diện từng dòng, hỗ trợ tốt nhất trang giấy sáng, một cột. Chưa có phát hiện chữ trong cảnh vật, bảng/nhiều cột hoặc sửa phối cảnh. Tài liệu tối đa 150 dòng/ảnh; ảnh gốc quá 40 megapixel hoặc file chọn vượt 40 MB được từ chối. Dòng vượt giới hạn sinh token báo lỗi để người dùng cắt ảnh nhỏ hơn. Nên kiểm tra và sửa dấu sau nhận diện.

Ảnh và kết quả được lưu trong vùng riêng của ứng dụng, không tự gửi ra ngoài. Nút chia sẻ chỉ xuất văn bản khi người dùng chọn. Gỡ app/xóa dữ liệu sẽ xóa phiên đã lưu; hãy xuất TXT nếu cần giữ lâu dài.

Các hướng phát triển tiếp theo và phương án giảm dung lượng sâu hơn nằm trong [lộ trình](../docs/ROADMAP.md).
Danh sách công cụ, phiên bản và thư mục đã cài trên máy hiện tại nằm trong [báo cáo cài đặt](../docs/INSTALLATION_REPORT.md).
