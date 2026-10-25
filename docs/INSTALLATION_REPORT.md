# Báo cáo công cụ và file đã thêm

Ngày thực hiện: **19/10/2026**. Các đường dẫn dưới đây là trên máy Windows hiện
tại; SDK/toolchain không nằm trong gói ứng dụng cài trên điện thoại.

## Android SDK đã tải bằng Android CLI

SDK đang dùng: `C:\Users\QuangNew\AppData\Local\Android\Sdk`.
Danh sách đã đối chiếu bằng `android --no-metrics sdk list`.

| Thành phần | Phiên bản | Vị trí |
| --- | --- | --- |
| Platform Tools, gồm ADB | 37.0.1 | `C:\Users\QuangNew\AppData\Local\Android\Sdk\platform-tools` |
| Android SDK Platform 36 | Android API 36, revision 2 | `C:\Users\QuangNew\AppData\Local\Android\Sdk\platforms\android-36` |
| Android SDK Platform 35, Gradle tải thêm cho thư viện | Android API 35, revision 2 | `C:\Users\QuangNew\AppData\Local\Android\Sdk\platforms\android-35` |
| Android SDK Build-Tools | 35.0.0 | `C:\Users\QuangNew\AppData\Local\Android\Sdk\build-tools\35.0.0` |
| NDK side by side | 28.2.13676358, r28c | `C:\Users\QuangNew\AppData\Local\Android\Sdk\ndk\28.2.13676358` |
| CMake, Gradle tải thêm cho bước build native | 3.22.1 | `C:\Users\QuangNew\AppData\Local\Android\Sdk\cmake\3.22.1` |

Android CLI còn tạo metadata trong SDK, gồm `licenses` và `.sdk`. NDK là phần
lớn nhất, khoảng 2 GiB sau giải nén; đây là công cụ build, không đóng gói nguyên
bộ vào APK. Không cài thêm Android Studio, emulator hoặc system image.

## Công cụ đã có sẵn và được sử dụng lại

| Công cụ | Vị trí |
| --- | --- |
| Android CLI | `C:\Users\QuangNew\AppData\AndroidCLI\android.exe` |
| ADB bạn đã đặt trong PATH | `C:\Users\QuangNew\Downloads\Setup\platform-tools\adb.exe` |
| Command-line tools cũ | `C:\Services\Android_SDK\cmdline-tools\latest` |
| Flutter 3.41.4 / Dart 3.11.1 | `C:\Services\Flutter\flutter` |
| JDK 21 dùng cho build | `.toolchain\java\jdk-21.0.12.1+1` trong repository |
| Python 3.11 và thư viện export/OCR | `VietHandOCR_API_Release\.venv` |
| PlatformIO | `C:\Users\QuangNew\.platformio\penv` |

Chạy Android CLI lần đầu trong phiên này có bước tự giải nén phần cài nhúng
của CLI. Các lệnh CLI tiếp theo dùng `--no-metrics`. ADB mới trong SDK và bản
ADB đã có trong Downloads cùng phiên bản 37.0.1; chưa xóa hay thay bản của bạn.

Biến `JAVA_HOME`, `ANDROID_HOME`, `ANDROID_SDK_ROOT` và PATH được đặt **trong
tiến trình chạy lệnh build**. Không sửa PATH/biến môi trường User hoặc Machine.
SDK ở `C:\Services\Android_SDK` chỉ là vị trí command-line tools cũ, không phải
SDK platform vừa được cài để build dự án này.

## Thư viện và dữ liệu của dự án

- Dependency Android mới: `com.microsoft.onnxruntime:onnxruntime-android:1.23.2`
  trong `Mobile/android/app/build.gradle.kts`. Gradle quản lý cache tại
  `C:\Users\QuangNew\.gradle\caches`; thư viện này chỉ được nạp vào tiến trình
  OCR. Thư viện Dart `flutter_onnxruntime` đã được bỏ khỏi `pubspec.yaml`.
- AAR ONNX đã tải ở
  `C:\Users\QuangNew\.gradle\caches\modules-2\files-2.1\com.microsoft.onnxruntime\onnxruntime-android\1.23.2`
  (bên trong có thư mục con theo hash do Gradle quản lý).
- Pub dùng các phiên bản trong `Mobile/pubspec.lock`; dependency dự án được
  liên kết qua `Mobile/.dart_tool`, cache dùng chung nằm ở
  `C:\Users\QuangNew\AppData\Local\Pub\Cache`. Không cài gói Python mới trong
  lần sửa này.
- Hai model mobile gọn: `Mobile/assets/models/vietocr_encoder.onnx` và
  `vietocr_decoder.onnx`, tổng **77.925.797 byte**. Bản FP32 trước khi nén giữ ở
  `.toolchain/fp32-models`; model ứng viên và log nằm trong `.toolchain`.
- Model desktop gọn: `VietHandOCR_API_Release/vgg_transformer_compact.pth`,
  **76.771.587 byte**; bản `vgg_transformer_final.pth` được giữ nguyên.
- Cache build của dự án: `Mobile/build`, `Mobile/android/.gradle`, `.dart_tool`
  và `pbl4/.pio`. Các thư mục này không phải dữ liệu huấn luyện/model gốc.

Model `.onnx` và `.pth` được bỏ qua bởi Git. Trên máy mới, cần cung cấp model
hoặc chạy công cụ export/nén theo README. Không xóa `.toolchain/fp32-models`
nếu vẫn cần đối chiếu/phục hồi bản trước khi nén.

APK phát hành và kết quả kiểm tra được ghi tại `Mobile/validation.json` và
`Mobile/dist`. Chi tiết giới hạn kiểm chứng nằm trong `Mobile/README.md`.

## Kết quả build ngày 19/10/2026

- APK mới: `Mobile/dist/VietOCR-arm64.apk`, phiên bản **1.1.0+2**, kích thước
  **109.119.035 byte (104,1 MiB)**. Bản trước 182,3 MiB; mức giảm khoảng 43%.
- Bản APK trước được giữ tại `.toolchain/previous-VietOCR-arm64.apk`.
- SHA-256 APK mới:
  `5dae8c52775883e8e8094e6f0f8401ad0b58509bf5465009976d70b6507f1468`.
- Release đã biên dịch và kiểm tra chữ ký, ARM64, checksum model, tiến trình
  OCR riêng và căn chỉnh native 16 KiB. Giữ cùng chứng chỉ ký với bản trước.
- Không cài APK hay chạy kiểm thử trên điện thoại theo yêu cầu của bạn.

## Bổ sung IoT ngày 20/10/2026

- Tạo thư viện nội bộ **VietMusic 1.0.0** tại `pbl4/lib/VietMusic`: bảng nốt Hz,
  score/BPM, bộ phát không chặn và adapter GPIO/LEDC active/passive.
- Không cài thêm công cụ hoặc package toàn cục trong lần bổ sung này.
  Dùng lại g++ tại `C:\msys64\ucrt64\bin\g++.exe` và PlatformIO đã có.
- Firmware build dùng platform `espressif32@6.5.0` và Arduino ESP32 **2.0.14**
  từ `C:\Users\QuangNew\.platformio\packages\framework-arduinoespressif32@3.20014.231204`.
- Kết quả build tại `pbl4/.pio/build/esp32-s3-devkitc-1`; các chương trình kiểm
  tra host tại `pbl4/.pio/host-tests`. Chưa upload firmware lên board.

## Bổ sung ngày 21/10/2026

- Tải **ONNX Runtime Java/JNI 1.23.2**, chỉ để đối chiếu lõi OCR Android trên
  Windows. File tại `.toolchain/onnx-java/onnxruntime-1.23.2.jar`,
  **75.255.976 byte**. Nguồn: [Microsoft trên Maven Central](https://repo.maven.apache.org/maven2/com/microsoft/onnxruntime/onnxruntime/1.23.2/onnxruntime-1.23.2.jar).
- Đã đối chiếu SHA-1 với file checksum Maven công bố. SHA-256 của JAR:
  `e0ab4a1af57d2da09097202f2dfd691e390c82e81183314788ccde4cf7c3cc38`.
  Metadata ở `.toolchain/onnx-java/download.json`; DLL Windows do Java trích ra
  nằm trong `.toolchain/onnx-java/native`. JAR/DLL đối chiếu không đóng gói vào APK.
- Không cài package Python, không cài thêm SDK/NDK/JDK/PlatformIO hoặc sửa biến
  môi trường User/Machine trong lần sửa này. Dùng lại các công cụ đã liệt kê.
- Dữ liệu test mới: tensor/expected text và class Java ở
  `Mobile/build/verification`; báo cáo không chứa văn bản nằm ở
  `Mobile/assets/models/java_runtime_verification.json`. 8 ca khớp với Python.
- Log kiểm tra/build ở `.toolchain`: `flutter-tests.log`, `python-tests.log`,
  `java-ocr-tests.log`, `mobile-pipeline.log`, `desktop-smoke.log`,
  `bluetooth-native-scan.log`, `android-build.log`, `firmware-music-build.log`.
- Desktop thêm log runtime tại `VietHandOCR_API_Release/.logs`: console từng
  phiên, `vietocr.log`, `bluetooth.log` và crash trace riêng từng tiến trình.
- Firmware arcade build đạt, **977.184 byte**, SHA-256
  `46f7a2e59247cb83bd6b9b58cce4f6600be6bc022791e6f16be456e6593fa0ef`.
  Vị trí và trạng thái chưa upload trong `pbl4/docs/music-validation.json`.
- APK mới **1.2.0+3** tại `Mobile/dist/VietOCR-arm64.apk`, **109.250.983 byte
  (104,2 MiB)**, SHA-256
  `f6ffd011e63486a13006f799da61502c9b09230a23dfd2c8fa45437f80181d57`.
  Đã kiểm chữ ký cập nhật, ARM64, model, service `:ocr` và căn chỉnh ZIP/ELF
  16 KiB. Bản trước 1.1.0+2 giữ ở `.toolchain/VietOCR-arm64-1.1.0+2.apk`;
  backup 1.0.0+1 cũ không bị ghi đè.
- Mapping R8 để đọc stack trace release: `Mobile/dist/VietOCR-1.2.0+3-mapping.txt`.
  Không cài APK lên điện thoại hoặc upload firmware lên ESP32 trong lần này.

## Sửa theo log native và BLE ngày 21/10/2026 — APK 1.2.1+4

- Không tải hoặc cài thêm SDK, JDK, thư viện Python hay công cụ toàn cục trong
  lượt sửa này. Dùng lại Flutter, SDK, Gradle cache và JAR ONNX đã nêu ở trên;
  không sửa biến môi trường User/Machine.
- Phát hiện lỗi đóng gói trong APK 1.2.0+3: R8 loại `TensorInfo`, đổi tên các
  lớp được JNI ONNX gọi bằng tên gốc. Thêm quy tắc giữ lớp tại
  `Mobile/android/app/proguard-rules.pro`; kiểm tra APK release bằng
  `Mobile/tools/check_jni_keeps.py`. Bản cũ bị kiểm tra này từ chối; bản mới
  giữ 60 lớp ONNX gốc, đủ callback JNI và constructor `TensorInfo`.
- APK hiện tại **1.2.1+4**: `Mobile/dist/VietOCR-arm64.apk`, **109.283.751 byte**
  (104,2 MiB). SHA-256:
  `14d200b09fcb3da63db117ed1ad2af26632d12c8a21ece329092e67aa21a5137`.
  Giữ chứng chỉ ký cũ, ARM64, service riêng, model checksum và căn chỉnh 16 KiB.
- Backup 1.2.0+3 tại `.toolchain/VietOCR-arm64-1.2.0+3.apk`; không ghi đè các
  backup cũ hơn. Mapping mới: `Mobile/dist/VietOCR-1.2.1+4-mapping.txt`.
  Kết quả kiểm tra chi tiết và hash mapping nằm trong `Mobile/validation.json`.
- Kiểm tra đạt: analyzer Flutter, **34 unit/widget**, **102 Python desktop**,
  **8 ca lõi Java/JNI** đối chiếu Python. Kiểm tra JNI/R8 chạy trên chính APK
  release mới; kết quả Java ghi hash mã nguồn trong
  `Mobile/assets/models/java_runtime_verification.json`.
- Desktop thêm `desktop/bluetooth_coordinator.py` và
  `tools/diagnose_bluetooth.py`; điều phối quét/kết nối/dọn worker, tránh client
  chồng nhau khi mở hộp thoại hoặc bấm kết nối lặp. Log quét máy thật tại
  `.toolchain/desktop-ble-probe.log`: 53 thiết bị, chưa thấy địa chỉ ESP32.
- Chưa cài/chạy APK mới trên điện thoại, chưa kết nối GATT thành công hoặc
  nạp firmware lên ESP32. Firmware không đổi trong lượt sửa này; kết quả 575
  kiểm tra host và firmware build ở phần trước vẫn là kết quả của bản đó.
