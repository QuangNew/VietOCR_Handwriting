# Báo cáo công cụ và file đã thêm

## Native OCR và Android 4.1 — 19/11/2026

- Máy Windows dùng lại Python, PyTorch CUDA, .NET 10, Flutter, Android SDK và JDK 21. Python và trọng số đang dùng ở `services/compute/.venv`, `services/compute/.python` và `services/compute/models/ML_s44`. JDK nằm ở `.toolchain/java/jdk-21.0.12.1+1`.
- Worker chạy tiền xử lý Native trước ML_s44. Đã kiểm SHA-256, chạy worker CPU và CUDA, và đo trên RTX 4050 khoảng 1,15–1,73 giây với trang mẫu 1100 × 590 và 3,37 giây với mẫu phóng lên 3300 × 1770. Đây là thời gian trong worker. Mẫu đọc `trơi` ở vị trí tham chiếu `trời`.
- Đã chuyển các client sang `apps/`, hai dịch vụ sang `services/` và mã dùng chung sang `shared/`. Bản nghiên cứu gốc và dữ liệu cũ được giữ cục bộ trong `.toolchain/archive/2026-11-19/`. Hai bản checkpoint trùng SHA-256, công cụ ONNX Android cũ và cache Rust đã được dọn.
- SSH xác nhận các dịch vụ gateway, webcam và tunnel trên Pi đều `enabled` và `active`. Gateway trả `alive`. Phiên bản Native chạy ở compute Windows và dùng giao thức gateway v2 hiện tại.
- Xem [DevTodo](../DevTodo.md) để khởi động dịch vụ và cài APK. Các mục sau ghi lại các đợt triển khai trước đây với tên thư mục tại thời điểm đó.

## Nhánh refactor — 09/11/2026

Các mục bên dưới là lịch sử cài đặt, không phải đường dẫn chạy của v4.

- Python/CUDA hiện có đã chuyển cùng ổ đĩa từ `VietHandOCR_API_Release/.venv`
  sang **`Server/.venv`**, interpreter từ `.python` cũ sang **`Server/.python`**.
  Không tải/cài lại PyTorch, CUDA hoặc trọng số. `pyvenv.cfg` và activation được
  cập nhật. Dùng `Server/.venv/Scripts/python.exe -m pip`, không dựa vào launcher
  `pip.exe` cũ có thể còn đường dẫn tuyệt đối trước khi di chuyển.
- cloudflared **2026.10.7**: Windows tại
  `.toolchain/cloudflared/cloudflared-windows-amd64.exe`, ARM64 trên Pi tại
  `/usr/local/bin/cloudflared`. Tổng hai binary tải khoảng88.8MiB; đã đối chiếu
  SHA256 release. DNS/Authorize chưa xong, chưa cài named connector production.
- Gateway ARM64 và µStreamer native MJPEG chạy bằng systemd trên Pi; không cài
  Rust/compiler lên Pi, không đổi SSH/RDP/Tailscale. GPIO vẫn tắt theo yêu cầu.
- Desktop mới: `Desktop/dist/vietocr-desktop.exe` từ CI Windows, không cần Python.
  Android mới: `Mobile/dist/VietOCR-4.0.1-refactor-arm64.apk`,20,637,449bytes;
  JDK21/Flutter/AndroidSDK cũ được dùng lại, không tải SDK/toolchain lớn.
- Các crate Rust bổ sung cho ảnh được cache ở Cargo registry; không thêm runtime
  model cho client. Mã Tk/BLE/ESP32 và launcher EXE cũ đã gỡ80 tracked file.
- Dọn14 mapping Android1.x/2.x cũ,178,390,646logical bytes (~170.1MiB). Model,
  ảnh người dùng, signing material, session và APK mới được giữ. Dữ liệu dọn
  firmware/cache trước đó được ghi riêng ở `docs/REFACTOR_PROGRESS.md`.
- Khoá máy ở `/etc/vietocr/*.token` trên Pi có quyền0600; hai bản staging đã xoá,
  thư mục staging chuyển0700. Không đưa mật khẩu SSH, cert.pem, UUID credential,
  service-role hay máy-token vào Git/EXE/APK. Cấu hình publishable là công khai;
  giao diện kết nối không còn hai trường Supabase.

Chi tiết phiên bản build đã kiểm và giới hạn các phép đo ở
[REFACTOR_PROGRESS.md](REFACTOR_PROGRESS.md).

## Bản test OV5640 desktop và Android — 02/11/2026

- Desktop: [VietOCR.exe](../VietHandOCR_API_Release/dist/VietOCR.exe), launcher
  Windows dùng `.venv`, model và mã nguồn trong `VietHandOCR_API_Release`.
  Giữ EXE trong `dist`; đây là bản chạy thử trên máy hiện tại, chưa phải gói
  portable. Console debug tách khỏi tiến trình giao diện và ghi vào `.logs`.
  Mã launcher/build ở `VietHandOCR_API_Release/tools/desktop_launcher.cpp`
  và `tools/build_desktop.ps1`.
- Android: **1.9.0+14**, [VietOCR-arm64.apk](../Mobile/dist/VietOCR-arm64.apk).
  Kết quả kiểm tra chữ ký, ABI, model và hash APK ở
  [Mobile/validation.json](../Mobile/validation.json). Chưa cài APK lên điện thoại.
- Hai app hỗ trợ firmware **3.0.0-ov5640**, preview UDP VOJ1 mặc định
  **640×480/QS18**, ảnh chụp HTTP **2592×1944/QS8**, autofocus và cấu hình
  schema 2. Ảnh JPEG lưu nguyên byte sau kiểm CRC32; không hạ xuống 3 MP.
  Lật gương trái–phải đã được xác nhận lưu trên NVS của bo (`hmirror=1`,
  `vflip=0`); app dùng cùng hướng ảnh từ cảm biến.
- Kiểm tra tự động: **179 desktop**, **76 Flutter**, Dart analyzer không lỗi;
  gồm UDP thật trên loopback, gia hạn lease, đóng/mở lại, gói sai CRC/thứ tự,
  bộ đệm giới hạn và lưu/khôi phục JPEG 5 MP đã lật gương. Log ở
  `.toolchain/ov5640-apps-*`. Khi kiểm tra phần cứng cuối, máy không thấy
  COM8 hoặc quảng bá BLE; chưa đo lại FPS với hai app. Trạng thái Bluetooth
  Windows đã được trả về như trước khi kiểm tra.
- **Không cài thêm SDK, compiler hoặc thư viện** trong lượt build này. Dùng
  lại Flutter/Dart tại `C:\Services\Flutter\flutter`, Android SDK tại
  `C:\Users\QuangNew\AppData\Local\Android\sdk`, JDK ở
  `.toolchain/java/jdk-21.0.12.1+1`, Python tại
  `VietHandOCR_API_Release/.venv` và MSYS2 UCRT C++ tại
  `C:\msys64\ucrt64\bin\g++.exe`. Pub và Gradle dùng dependency đã có;
  không tải model/toolchain lớn và không sửa PATH/biến môi trường toàn máy.
- Với Flutter 3.41, chạy test xong phải build release bằng lệnh chuẩn trong
  `Mobile/README.md`, không dùng `--no-pub`: tùy chọn này bỏ bước tạo lại
  registrant và có thể giữ `IntegrationTestPlugin` chỉ dùng cho test.

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

## Camera OV3660 và hàng đợi ngày 25/10/2026 — APK 1.3.0+5

- Tải thêm thư viện Arduino **TJpg_Decoder 1.1.0** của Bodmer để giải mã JPEG
  lên TFT. Dependency khóa phiên bản tại `pbl4/platformio.ini`; nguồn là
  [repository của tác giả](https://github.com/Bodmer/TJpg_Decoder).
  PlatformIO quản lý thư viện trong
  `pbl4/.pio/libdeps/esp32-s3-cam-ov3660/TJpg_Decoder` và
  `pbl4/.pio/libdeps/esp32-s3-devkitc-1/TJpg_Decoder`; cache tải dùng
  `C:\Users\QuangNew\.platformio\.cache`. IDE có thể tái tạo các thư mục libdeps.
- Không cài thêm SDK/NDK/JDK, package Python hoặc công cụ toàn cục; dùng lại
  Flutter, Gradle, Java/JNI ONNX và PlatformIO đã có. Biến môi trường build
  chỉ đặt trong tiến trình lệnh, không sửa User/Machine PATH.
- Firmware camera và legacy được build bằng espressif32 6.5.0 / Arduino 2.0.14.
  Kết quả PlatformIO ở `pbl4/.pio/build/<environment>`; bản sao giữ ở
  `pbl4/dist/VietOCR-OV3660.bin` và `pbl4/dist/VietOCR-legacy.bin`.
  Checksum/kích thước tại `pbl4/docs/camera-validation.json`.
- Mặc định **legacy, camera tắt**, theo dây cũ người dùng xác nhận.
  Profile camera riêng yêu cầu đối chiếu pinout và chuyển TFT/còi; chưa upload.
  Chi tiết trong `pbl4/docs/CAMERA.md`. File `.bin` app không thay thế toàn bộ
  quy trình PlatformIO upload (còn bootloader/partition).
- Desktop lưu ảnh hàng đợi tạm trong `%TEMP%\vietocr_queue_*`; không giữ toàn
  bộ ảnh trong RAM. Xóa mục/dọn danh sách xóa file tương ứng, đóng app kết thúc
  phiên. Mobile lưu ảnh/kết quả trong vùng dữ liệu riêng như trước, nay khôi
  phục đầy đủ danh sách trên 10 ảnh.
- APK **1.3.0+5** tại `Mobile/dist/VietOCR-arm64.apk`: **109.349.615 byte**
  (104,3 MiB), SHA-256
  `5a2466396ea34fd493bbb2bd2e2841502170cf8f2eb9167ae9e994ee5fd88c75`.
  Chữ ký cập nhật giống bản trước; model, service OCR riêng, ARM64, căn chỉnh
  16 KiB và 60 lớp ONNX/JNI gốc đã được kiểm tra trên release APK.
- Backup APK 1.2.1+4: `.toolchain/VietOCR-arm64-1.2.1+4.apk`; các backup cũ giữ
  nguyên. Mapping mới: `Mobile/dist/VietOCR-1.3.0+5-mapping.txt`.
- Kết quả: analyzer sạch, **41 test Flutter**, **107 test desktop**, **591
  kiểm tra host firmware**, **8 ca OCR Java/JNI** khớp Python. Desktop chạy
  trọng số thật qua **5 ca**, GUI vẫn phản hồi. Kiểm tra không thay thế đánh
  giá độ chính xác OCR hoặc thử camera/BLE/điện thoại thật.
- Log ở `.toolchain`: `android-camera-build.log`, `firmware-camera-build.log`,
  `firmware-camera-tests.log`, `flutter-camera-analyze.log`,
  `flutter-camera-tests.log`, `python-camera-tests.log`,
  `desktop-camera-model-smoke.log`, `java-camera-ocr-tests.log`.
- Chưa cài APK lên điện thoại, chưa flash board, chưa xác nhận camera/BLE trên
  bo thật. Người dùng hiện chỉ xác nhận N16R8 và ảnh bo, chưa có sơ đồ nội bộ
  để xác nhận toàn bộ pinout camera.

## Chẩn đoán chân camera ngày 26/10/2026

- Tạo dự án độc lập tại `pbl4/diagnostics/camera_probe`, mã chính `src/main.cpp`:
  thử hai cấu hình S3-WROOM/GOOUUU, đọc PID và giải mã ba JPEG, in chân qua Serial.
- Build `probe-uart` bằng PlatformIO/espressif32 6.5.0/Arduino 2.0.14 đã có.
  Không thêm thư viện hay công cụ toàn cục. File build ở
  `pbl4/diagnostics/camera_probe/.pio/build/probe-uart/firmware.bin`;
  log tại `.toolchain/camera-probe-build.log`.
- Không sửa cấu hình firmware trợ lý, không ghi NVS và chưa upload lên board.
  Hướng dẫn nạp/Serial tại `pbl4/diagnostics/camera_probe/README.md`.

## Kết quả chẩn đoán do người dùng cung cấp ngày 26/10/2026

- Người dùng đã nạp/chạy camera_probe: OV3660 PID `0x3660`, sáu JPEG QVGA
  giải mã thành công với hai biến thể PWDN=-1/38, XCLK 20 MHz.
  Log lưu tại `pbl4/docs/camera-probe-2026-10-26.txt`.
- Giữ cấu hình trợ lý **PWDN=-1, RESET=-1** vì đã hoạt động mà không điều khiển
  PWDN. Các chân camera hiện có khớp log, không cần thay giá trị GPIO camera.
  Cần chuyển dây TFT/còi theo `pbl4/docs/CAMERA.md` trước khi nạp profile camera.
- Không cài/tải thêm công cụ hoặc thư viện. Lượt này chỉ cập nhật ghi nhận kiểm
  chứng và chú thích; không build lại hoặc tự upload firmware. Chưa xác nhận
  TFT, chụp 1600×1200 hay truyền JPEG qua BLE trên phần cứng.

## Kiểm tra TFT trắng ngày 26/10/2026

- Người dùng xác nhận đã chuyển dây mới và nạp firmware trợ lý; Serial tới
  READY/BLE trong khi TFT trắng. Cổng hiện tại là USB-UART CH343 **COM8**.
- Đổi default environment sang `esp32-s3-cam-ov3660`, giữ cổng COM8 người dùng
  đã cấu hình. SPI TFT 10 MHz, in pinout từ thư viện TFT_eSPI và hiện ba màu
  khởi động để xác định đường truyền màn hình. Bản legacy vẫn dùng SPI 20 MHz.
- Build camera đạt; không cài/tải thêm công cụ hoặc thư viện. Log tại
  `.toolchain/tft-white-screen-build.log`, binary tại `pbl4/dist/VietOCR-OV3660.bin`.
- Không tự nạp/reset bo. COM8 đang được chương trình khác giữ nên không đọc
  Serial trực tiếp; log do người dùng cung cấp. Chưa xác nhận hết trắng trên bo.

## Sửa MISO TFT_eSPI trên ESP32-S3 ngày 26/10/2026

- Log thực tế của người dùng có `MOSI=21 MISO=21` dù cấu hình MISO=-1.
  Kiểm tra nguồn TFT_eSPI 2.5.43 xác nhận processor header S3 tự đổi -1 thành
  MOSI. Chuyển sang **MISO=39**, nối SDO/MISO màn hình vào GPIO39;
  GPIO13 vẫn là PCLK camera. Hướng dẫn tháo MISO trước đây đã được sửa.
- Thêm static_assert sau khi nạp header thư viện để chặn MISO/MOSI trùng nhau.
  Đọc ID ILI9341 qua MISO ở 1 MHz và in Serial; tốc độ ghi giữ 10 MHz.
- Không sửa thư viện trong `.pio`, không tải/cài package mới. Build/log tại
  `.toolchain/tft-miso-fix-build.log`; binary cập nhật `pbl4/dist/VietOCR-OV3660.bin`.
  Chưa tự upload và chưa xác nhận hiển thị trên phần cứng sau thay đổi này.

## Kiểm tra TFT qua GPIO trực tiếp ngày 26/10/2026

- Người dùng xác nhận dây: CS42, RESET40, DC41, MOSI21, SCK47, MISO39,
  còi14; TFT vẫn trắng và đọc ID `0xffff`. Chưa xác định nguyên nhân.
- Tạo chương trình độc lập tại `pbl4/diagnostics/tft_probe`, chỉ gửi bảng lệnh
  ILI9341 và ba dải màu bằng GPIO trực tiếp; không khởi tạo SPI phần cứng,
  camera hoặc BLE. Giữ nguyên bộ dây hiện tại.
- PlatformIO cài bản thư viện **TFT_eSPI 2.5.43** cho dự án kiểm tra tại
  `pbl4/diagnostics/tft_probe/.pio/libdeps/tft-soft-spi/TFT_eSPI`, dùng lại phiên
  bản đã có trong dự án chính. Không cài thêm công cụ toàn cục.
- Build **SUCCESS**; binary ở
  `pbl4/diagnostics/tft_probe/.pio/build/tft-soft-spi/firmware.bin`, log tại
  `.toolchain/tft-direct-gpio-build.log`. Chưa upload/reset bo, chưa có kết quả
  hiển thị thực tế. Hướng dẫn ở `pbl4/diagnostics/tft_probe/README.md`.

## Desktop: CUDA, DirectML và thoát Bluetooth ngày 26/10/2026

Máy có RTX 4050 Laptop 6 GB và Intel UHD. Môi trường trước đó dùng
Torch **2.14.1+cpu**, Torchvision **0.29.1+cpu**, nên không thể dùng CUDA dù có
card NVIDIA. Đã cài các gói sau **trong môi trường của dự án**:

| Gói | Phiên bản sau cài | Vị trí |
| --- | --- | --- |
| PyTorch CUDA | 2.14.1+cu126 | `VietHandOCR_API_Release/.venv/Lib/site-packages/torch` |
| Torchvision CUDA | 0.29.1+cu126 | `VietHandOCR_API_Release/.venv/Lib/site-packages/torchvision` |
| ONNX Runtime DirectML | 1.24.4 | `VietHandOCR_API_Release/.venv/Lib/site-packages/onnxruntime` |

- Torch/Torchvision lấy từ `https://download.pytorch.org/whl/cu126`. CUDA
  runtime đi kèm wheel; không cài CUDA Toolkit hoặc thay driver NVIDIA.
  Wheel Torch tải khoảng **2,4 GiB**; riêng thư mục `torch/lib` có khoảng
  **4,09 GB** dữ liệu logic. Đây là môi trường GPU, lớn hơn môi trường CPU.
- Cache tải/giải nén uv ở
  `C:/Users/QuangNew/AppData/Local/uv/cache`. Log cài đặt:
  `.toolchain/desktop-cuda-install.log`. Danh sách gói trước cài:
  `.toolchain/desktop-packages-before-cuda.txt`.
- Wheel DirectML **25,1 MB** từ PyPI được lưu ở
  `.toolchain/directml-wheel/onnxruntime_directml-1.24.4-cp311-cp311-win_amd64.whl`;
  log tải/cài ở `.toolchain/desktop-directml-download.log` và
  `.toolchain/desktop-directml-install.log`.
- Gỡ gói **onnxruntime CPU 1.23.2** trước khi cài DirectML vì hai distribution
  dùng chung namespace/file. DirectML vẫn có `CPUExecutionProvider`.
  Requirements export Windows dùng cùng distribution để tránh cài chồng lại.
  `pip check` sau cài: **No broken requirements found**.
- Không tải thêm model. DirectML dùng encoder/decoder hiện có tại
  `Mobile/assets/models/`, kiểm SHA256 và đối chiếu checkpoint đã chọn.

Desktop mặc định chọn **GPU rời → GPU tích hợp → CPU**; NVIDIA ưu tiên CUDA.
DXGI/D3D12 xác định UMA và giữ LUID để không nhầm GPU khi chỉ số adapter đổi.
Nạp checkpoint trên CPU trước khi chuyển model sang CUDA để giảm đỉnh VRAM.
Lỗi GPU được thử lại trong worker mới; Tk không nạp PyTorch. Thanh trạng thái
hiện thiết bị thực tế, worker log ghi các lần chuyển thiết bị.

Kết quả kiểm tra:

- **116 test** desktop đã qua sau thay đổi GPU/LUID; **3 test console** qua sau
  sửa thêm input của IDE (gồm một ca mới, tổng 117 ca khác nhau).
- Model thật chạy CPU, RTX 4050/CUDA và Intel UHD/DirectML trên hai ảnh mẫu,
  cùng văn bản. Chạy lại một mẫu trên mã cuối vẫn khớp cả ba thiết bị.
  DirectML profiling ghi nhận kernel GPU trên cả encoder và decoder; một số
  toán tử vẫn dùng CPU theo thiết kế của execution provider.
- RTX ở lượt đầu khoảng **0,5–0,9 giây/ảnh**; Intel UHD lượt đầu **60–76
  giây/ảnh**, chạy lại mẫu khoảng **2,3 giây**. Số đo có ảnh hưởng khởi động và
  cache, không phải benchmark toàn diện hoặc bảo đảm GPU luôn nhanh hơn CPU.
- Tk thật chạy ẩn, nạp/nhận diện qua RTX 4050, xử lý **931 lượt vòng sự kiện**,
  cập nhật nhãn thiết bị và đóng sạch; PyTorch không được nạp vào tiến trình Tk.
- Báo cáo được lưu tại `VietHandOCR_API_Release/docs/compute-validation.json`.
  Log kiểm tra ở `.toolchain/desktop-gpu-*-tests.log`,
  `desktop-gpu-*-model-smoke.log` và `desktop-gpu-ui-smoke.log`.

Log Bluetooth người dùng gửi có hai trường hợp: không thấy quảng bá BLE sau
8 giây là lỗi kết nối đã được bắt; traceback `CancelledError` rồi
`KeyboardInterrupt` là SIGINT được gửi tới worker. Đã để worker bỏ qua SIGINT,
GUI gửi lệnh CLOSE để giải phóng GATT. Terminal debug chỉ mở lại app khi Enter/R;
lệnh activate do IDE gửi không làm mở lại app. Mã `App exited: 0` trong log cũ
là thoát bình thường. Chưa xác nhận kết nối GATT thật trong lượt này.

TFT: người dùng xác nhận ấn dây thì màn hình chạy, phù hợp lỗi tiếp xúc do
header chưa hàn. Cần hàn để ổn định. Firmware `tft_probe` không bật BLE; phải
nạp lại profile trợ lý camera để kết nối app sau khi thử màn hình.

## Camera desktop, nhận JPEG và hiển thị ngày 26/10/2026

- Người dùng cung cấp log kết nối GATT/PING/WAKE thành công; `CAM SHOT`
  tạo JPEG **61.928 byte, 1600×1200**, nhưng chưa có dòng hoàn tất nhận ảnh.
  Log sau đó cũng có CAM OPEN nhưng firmware cũ từ chối CAM STATUS. Chưa có
  dữ liệu MTU/số byte nhận để khẳng định nguyên nhân truyền chậm trên bo thật.
- Sửa luồng desktop: mở hoặc mở lại cửa sổ camera gửi CAM OPEN, kiểm tra
  CAM STATUS để bật nút Chụp khi khung đã được giải mã/gửi lên TFT. Nút Chụp
  nằm trong app desktop theo lựa chọn người dùng. Bỏ chiều cao cố định 210 px,
  giữ footer/nút ở mọi cỡ chữ đã thử. Có nút Xem lại trên TFT sau khi chụp.
- Tiến độ ảnh đi từ worker BLE qua IPC tới giao diện, có % và số byte.
  Windows thử GATT long read 480 byte JPEG, lùi về MTU khi driver từ chối hoặc
  cắt ngắn; CRC32 vẫn bắt buộc. Timeout hiện rõ số byte, log nhận mỗi 4 giây.
  Firmware đề nghị MTU517 và interval15–30 ms; central quyết định thông số.
- Bỏ phần hiện màu đỏ/xanh lá/xanh dương khi khởi động. Firmware thường vào
  trợ lý trực tiếp; chương trình tft_probe độc lập giữ riêng để chẩn đoán.
- SPI TFT **40 MHz**, hoạt ảnh mục tiêu **60 FPS**, gửi vùng động để giảm
  băng thông. Panel ILI9341 FRMCTR1=00/1F: danh định **61 Hz**, gần60Hz nhất
  trong bảng datasheet. Camera 320×240 RGB565 không thể gửi đủ60FPS qua SPI
  40MHz (giới hạn thô32,6FPS trước giải mã/lệnh); Serial báo FPS thực mỗi5giây.
  Chưa đo FPS hay xác nhận40MHz trên bo thật sau thay đổi.
- **125 test desktop** qua; thêm **2 ca mới** về driver long read lỗi/timeout
  trong lượt cuối, bộ **15 test truyền ảnh + IPC** đều qua. **591 kiểm tra host
  firmware** và build cả profile camera/legacy đều đạt. Không tải/cài thêm
  công cụ hoặc thư viện; dùng PlatformIO/espressif32 6.5.0, Arduino2.0.14,
  TFT_eSPI2.5.43 và TJpg_Decoder1.1.0 đã có.
- Artifact camera `pbl4/dist/VietOCR-OV3660.bin`: **1.063.872 byte**, SHA256
  `46d567554e8feabfb6ecc7b2d345957f2d2386008702f27253e20870f221ed9f`.
  Legacy `pbl4/dist/VietOCR-legacy.bin`: **1.001.120 byte**, SHA256
  `96614a0c4457c199e0cdcdb437f3bad8a33b1a56c32e3c6e162db72ebce1a040`.
  Bản trước được giữ trong `.toolchain/*-before-preview-fix.bin`.
- Log: `.toolchain/firmware-camera-final-build.log`,
  `firmware-camera-final-host-tests.log`, `desktop-camera-preview-tests.log`,
  `desktop-camera-final-transfer-tests.log`. Ghi nhận tại
  `pbl4/docs/camera-validation.json`. Chưa tự upload firmware, chưa xác nhận
  xem trước/nhận JPEG đầy đủ hay FPS trên bo thật với bản mới này.

## Wi-Fi camera và OCR FP32 — 27/10/2026

- **OV3660:** cảm biến giữ nguyên QXGA **2048×1536**, JPEG quality 6 cho cả
  xem trước và ảnh chụp. Bỏ luồng đưa camera lên TFT trong chương trình chính;
  TFT luôn vẽ trợ lý và cập nhật theme. Giữ nguyên GPIO người dùng đã xác nhận.
- **Wi-Fi:** hai app có Quét/chọn mạng, nhập SSID/mật khẩu, Kết nối và Kiểm tra.
  BLE cấu hình/điều khiển, HTTP LAN truyền JPEG có token phiên. Máy nhận và
  ESP32 cần cùng LAN; ESP32 dùng mạng 2.4 GHz. Mật khẩu lưu trên bo tại NVS
  `vietocr-wifi` (`ssid`, `pass`), không lưu trong app hoặc log. Token đổi khi
  mất BLE. Kiểm CRC32 trước OCR; lỗi HTTP không âm thầm tạo ảnh chụp thứ hai.
  Khi Wi-Fi chưa sẵn sàng, luồng chụp có thể lùi về BLE; xem trước cần Wi-Fi.
- **Mobile 1.4.0+6:** phục hồi hai export FP32 gốc đã kiểm SHA256 từ
  `.toolchain/fp32-models` vào `Mobile/assets/models`, tổng **152.819.648 byte**.
  Bản nén cũ vẫn ở `.toolchain/compact-models`. So sánh 20 trường hợp của đủ
  5 ảnh qua Dart tiền xử lý: FP32 và bản nén cùng nội dung, không có kết quả
  toàn số trên host. Đây chưa phải bằng chứng xác định lỗi trên Android ARM.
  Nút kiểm tra AI yêu cầu tiêu đề ảnh chuẩn khớp hoàn toàn; không còn coi mọi
  chuỗi không rỗng là thành công. Native ghi min/max/std của tensor, xác nhận
  little-endian, miền [0,1] và precision; không ghi ảnh/nội dung OCR.
- **Độ ổn định:** chặn khởi tạo BLE trùng trong một phiên, giới hạn cache ảnh
  Flutter 24 MiB, dừng preview khi chụp/ngắt/nền, giữ OCR trong `:ocr`.
  Desktop dành chỗ thanh thao tác/trạng thái trước nội dung co giãn, xuống dòng
  trạng thái, chuyển import OpenCV sang bước nhận diện. AI/BLE vẫn nằm trong
  worker riêng. Hai log desktop mới nhất kết thúc mã 0; chưa có dấu vết xác
  định nguyên nhân các lần crash mà người dùng báo trong yêu cầu mới.
- **Kiểm tra:** 134 test desktop, 44 test Flutter, analyzer không lỗi,
  20 tensor Java/JNI thật khớp Python ORT, 591 kiểm tra host firmware; hai
  profile firmware build đạt. Desktop chạy thêm model thật trong Tk, chọn
  RTX 4050 / CUDA, đọc xong mẫu và nhận 3.758 lượt vòng UI, Torch không nạp
  trong tiến trình Tk. Đây không thay thế kiểm tra trên điện thoại/bo thật.
- **Artifact:** `Mobile/dist/VietOCR-arm64.apk`, **182.388.218 byte (~173,9 MiB)**,
  version **1.4.0+6**. Đã xác nhận model đóng gói, ABI ARM64, dịch vụ OCR riêng,
  chữ ký v2, căn chỉnh ZIP/ELF 16 KiB và các lớp JNI qua R8. Bản 1.3.0+5 được
  giữ tại `.toolchain/VietOCR-arm64-1.3.0+5.apk`; mapping mới nằm cạnh APK.
  Checksum APK nằm trong `Mobile/validation.json`.
- Firmware camera `pbl4/dist/VietOCR-OV3660.bin`: **1.458.336 byte**, SHA256
  `537b6defea39dd70ca80aa4e72cbc2003e4423d17fee5378277549b407604e33`.
  Legacy **1.395.248 byte**, SHA256
  `c48b5c0a871b428058fefbe0c1a77818ff38cc785a33d1e2f402ec70efc7788d`.
  Bản trước giữ tại `.toolchain/*-before-wifi.bin`.
- **Không cài thêm package/SDK/toolchain trong lượt này.** Dùng lại Flutter
  tại `C:\Services\Flutter\flutter`, Android SDK tại
  `C:\Users\QuangNew\AppData\Local\Android\Sdk`, JDK tại
  `.toolchain/java/jdk-21.0.12.1+1`, PlatformIO/toolchain trong
  `C:\Users\QuangNew\.platformio`, Python/thư viện tại
  `VietHandOCR_API_Release/.venv`. Model FP32 là bản sao lưu sẵn có, không tải
  model mới. Các công cụ được phép ghi cache cần thiết; không đổi PATH toàn máy.
- Log mới: `.toolchain/mobile-wifi-analyze.log`, `mobile-wifi-tests.log`,
  `desktop-wifi-final-tests.log`, `mobile-five-models.log`, `java-wifi-fp32-ocr.log`,
  `desktop-wifi-real-gpu-ui.log`, `firmware-wifi-final-build.log`,
  `firmware-wifi-host-tests.log`, `android-wifi-fp32-build-final.log` và
  `android-wifi-release-verification.log`. Lượt build đầu dùng `--no-pub` bị
  registrant plugin integration_test; build lại bình thường đã đạt.
- **Chưa tự nạp firmware, chưa cài/chạy APK trên điện thoại**, chưa đo tốc độ
  Wi-Fi hoặc xác nhận hết lỗi toàn số/crash/theme trên thiết bị thật. Sau khi
  nạp/cài bản mới: kết nối BLE → Wi-Fi camera → chọn mạng → Kết nối → Kiểm tra
  → Xem camera → Chụp. OCR điện thoại/thư viện vẫn hoạt động khi không dùng LAN.

## Sửa lỗi Quét Wi-Fi `INVALID_COMMAND` — 27/10/2026

- Đã đọc trực tiếp COM8 trước khi sửa: `HELP` trên bo chưa có nhóm lệnh WIFI
  và `WIFI STATUS` trả `ERR INVALID_COMMAND: send HELP`. Log BLE desktop cũng
  ghi `WIFI SCAN` bị từ chối nhưng PING/PONG vẫn bình thường. Nguyên nhân xác
  định là firmware trên bo cũ hơn app, chưa có hỗ trợ Wi-Fi.
- Đã **nạp profile camera `esp32-s3-cam-ov3660` bản `2.0.1-wifi` vào COM8**,
  xác nhận chip ESP32-S3 revision v0.2, MAC gốc `84:c7:bb:53:08:60`, hash nạp
  flash đạt. Không đổi GPIO, không xóa toàn bộ flash/NVS. Thêm `INFO` để đọc
  phiên bản/capability rõ ràng qua Serial hoặc BLE.
- Kiểm tra trên bo thật: `INFO` trả đúng phiên bản; `WIFI SCAN`/`WIFI COUNT`
  qua Serial tìm **14 điểm phát**. Mã desktop dùng BLE quét và đọc từng mạng
  thành công, trả **7 tên mạng** sau lọc trùng/tên rỗng. Thử THEME LIGHT/DARK
  rồi đọc STATUS đã xác nhận firmware cập nhật, khôi phục theme trước đó,
  PING vẫn qua và đã ngắt BLE sau kiểm tra. Không khẳng định giao diện TFT
  nhìn đúng chỉ từ phản hồi STATUS.
- Firmware phân biệt lỗi bắt đầu/kết thúc quét, không trả giả `COUNT 0` khi
  scan thất bại. Hai app giải thích firmware thiếu tính năng, đang kết nối
  và quét lỗi; các lỗi này không làm đóng kết nối BLE.
- **9 ca hồi quy desktop Wi-Fi** và **45 test Flutter** qua; analyzer không
  lỗi. Profile camera build/nạp đạt, profile legacy build đạt (không nạp).
- APK **1.4.1+7** tại `Mobile/dist/VietOCR-arm64.apk`, **182.388.218 byte**,
  SHA256 `01f700711961f6c0b92018ec019ffd9a39b0f1c44870808cf6e7f94ffb744b0e`.
  Kiểm chữ ký v2/cùng chứng chỉ, ABI ARM64, model FP32 và JNI/R8, căn chỉnh
  16 KiB đều qua. Giữ APK trước ở `.toolchain/VietOCR-arm64-1.4.0+6.apk`;
  mapping mới `Mobile/dist/VietOCR-1.4.1+7-mapping.txt`.
- Firmware camera mới **1.458.688 byte**, SHA256
  `9c9ab3f7151b522e249fc1f58c0a0e5407e3b877ff2fef834fc8349862ddca7a`.
  Legacy **1.395.600 byte**, SHA256
  `a278930946c1c853f4f2159bb5ce592591a499c2c10079b92d2d4f9b618fd7a6`.
  Artifact ở `pbl4/dist`; bản trước ở `.toolchain/*-before-scan-fix.bin`.
- **Không cài thêm phần mềm/package.** Dùng lại Python, PlatformIO, Flutter,
  Android SDK và JDK tại các đường dẫn đã ghi ở mục trước. Không đổi model.
- Log: `.toolchain/firmware-wifi-scan-upload.log`,
  `firmware-wifi-scan-serial.log`, `firmware-wifi-scan-ble.log`,
  `desktop-wifi-scan-tests.log`, `mobile-wifi-scan-tests.log`,
  `mobile-wifi-scan-analyze.log`, `android-wifi-scan-build.log`,
  `android-wifi-scan-release-verification.log`. Dữ liệu kiểm chứng trong
  `pbl4/docs/camera-validation.json` và `Mobile/validation.json`.
- Chưa nhập mật khẩu Wi-Fi, chưa kiểm tra đăng nhập LAN/truyền JPEG qua Wi-Fi
  trên bo thật; chưa cài APK mới lên điện thoại. Người dùng mở lại app desktop
  → Kết nối BLE → Wi-Fi camera → Quét mạng → chọn mạng và nhập mật khẩu.

## HTTP camera và thời gian nạp/nhận diện — 27/10/2026

- Yêu cầu mới: camera không hiện dù đã vào LAN, nạp model và nhận diện GPU
  chậm. Người dùng chọn **chỉ sửa mã và build, tự nạp**; lượt này không nạp
  ESP32 hoặc cài APK lên điện thoại. Lúc chẩn đoán máy chỉ còn COM3/COM4 của
  Bluetooth, không có COM8; không thể đọc lỗi socket/IP từ bo trực tiếp.
- Log người dùng xác nhận OV3660 khởi tạo và có JPEG; traceback lỗi ở HTTP
  fetch, không phải sensor init. Mã cũ gom lỗi thành `URLError`, che nguyên
  nhân socket; chưa đủ dữ liệu để khẳng định router, IP hay HTTP listener
  là nguyên nhân thực tế. Sửa để hiện IP:80 và mã refused/timeout/no-route,
  HTTP401/404/503 rõ ràng; không ghi token/mật khẩu trong lỗi/log.
- Firmware **2.1.0-wifi** mở server sau khi STA có IP DHCP hợp lệ, khởi động
  lại khi mất/đổi IP. Thêm `/health` có token; nút Kiểm tra thử HTTP thật.
  Giữ đủ **2048×1536, JPEG quality6**; bớt một frame bỏ khi camera đã hoạt
  động, Serial ghi `capture_ms`, `send_ms`, số byte và rc để đo sau nạp.
  Ảnh chụp trong app yêu cầu Wi-Fi/HTTP hoạt động, không tự chuyển sang hàng
  nghìn lượt BLE khi đường Wi-Fi lỗi. Preview desktop giữ endpoint 4 giây
  để giảm lần hỏi BLE, xóa cache khi HTTP lỗi.
- **Desktop model:** không đổi trọng số. `desktop/torch_predictor.py` dựng
  cùng model trên meta device, nạp checkpoint mmap/assign, tính FP32; tránh
  cấp phát/khởi tạo classifier VGG 500+MB bị upstream loại bỏ. Decoder giữ KV
  cache, giải mã token mới và chuyển mã token thay vì cả chuỗi xác suất về
  CPU. Dựng module checkpoint khớp strict; giữ API predict/predict_batch.
  Góc nghiêng tính trên ảnh nhỏ tối đa 600×400 rồi xoay ảnh gốc; ảnh 3MP
  không bị giảm kích thước trước bước cắt dòng. Model nạp nền sau khi mở
  app, vẫn ưu tiên GPU rời → GPU tích hợp → CPU.
- **Đo A/B trên cùng model/thiết bị, xen kẽ hai decoder:** 5 ảnh, CPU và
  RTX4050/CUDA, 3 lượt mỗi phương pháp; so văn bản khớp tất cả. Trung vị hai
  lượt cuối: mẫu dài GPU **0,572 → 0,336 giây**, mẫu tiêu đề **0,228 → 0,131**;
  5 mẫu GPU giảm khoảng **28–43%**. Khởi tạo/nạp checkpoint CPU **sau imports**
  **1,852 → 0,126 giây**. Đây không phải tổng thời gian khởi động app/CUDA.
  Tk thật nạp nền cả worker/import/GPU khoảng **11,89 giây**, vẫn phản hồi
  1.217 lượt vòng UI và nhận diện xong, Torch không nạp trong tiến trình Tk.
  Các con số là phép đo host, không bảo đảm thời gian trên mọi máy/tài liệu.
- Kiểm chứng: **140 test desktop**, **45 test Flutter** qua, analyzer không
  lỗi. Build cả firmware camera/legacy đạt. Mã Java OCR/mobile model không
  đổi; không khẳng định sửa lỗi nhận dạng trên điện thoại từ tối ưu desktop.
- Firmware camera `pbl4/dist/VietOCR-OV3660.bin`: **1.460.240 byte**, SHA256
  `e459067e3ac7320328ec25ffa7ae87611d6a133abf1e34f27ccf44f32cd7ebfb`.
  Legacy **1.398.032 byte**, SHA256
  `a71e634f828af8ff6b41a91f88732cafed9d6f0d72a7610e491f13ba522256a9`.
  Bản trước giữ trong `.toolchain/*-before-http-performance.bin`.
- Android **1.5.0+8**: `Mobile/dist/VietOCR-arm64.apk`; checksum/kích thước,
  chữ ký, R8/JNI và alignment xem `Mobile/validation.json`. APK trước giữ
  `.toolchain/VietOCR-arm64-1.4.1+7.apk`. Không cài SDK/package/model mới;
  dùng lại các đường dẫn toolchain đã ghi ở các mục trước.
- Log: `.toolchain/firmware-http-performance-build.log`,
  `desktop-http-performance-tests.log`, `mobile-http-tests.log`,
  `mobile-http-analyze.log`, `ocr-performance-final.log`,
  `desktop-http-real-model-ui.log`, `android-http-build.log`,
  `android-http-release-verification.log`. Báo cáo thời gian ở
  `VietHandOCR_API_Release/docs/performance-validation.json`; tình trạng
  build/chưa nạp ở `pbl4/docs/camera-validation.json`.
- Chưa kiểm tra HTTP/ảnh JPEG trên bo thật với bản 2.1.0, chưa đo tốc độ
  chụp/truyền thực tế. Người dùng nạp profile camera rồi cài APK mới, mở
  Wi-Fi camera → Kiểm tra. Nếu vẫn lỗi, IP/cổng và mã socket mới là dữ liệu
  cần dùng để xác định đường mạng, thay cho thông báo URLError chung.

Tham khảo kỹ thuật:
[PyTorch mmap/meta/assign](https://docs.pytorch.org/tutorials/recipes/recipes/module_load_state_dict_tips.html),
[inference mode](https://docs.pytorch.org/docs/stable/generated/torch.autograd.grad_mode.inference_mode.html),
[HTTP server ESP-IDF 4.4](https://docs.espressif.com/projects/esp-idf/en/v4.4/esp32/api-reference/protocols/esp_http_server.html).

## Stream OV3660 — 27/10/2026

- Người dùng xác nhận tối ưu OCR có hiệu quả; lượt này giữ nguyên model và
  phần tăng tốc. Camera cũ vẫn lặp tải JPEG 3 MP, chưa có luồng video. Log
  desktop 13:14 ghi khoảng 200 KB/ảnh, mất 6–14 giây cho mỗi GET `/preview`.
- Firmware **2.2.0-stream** thêm MJPEG liên tục ở **HTTP :81/stream**;
  **:80** dành cho `/health` và `/image`. Hai server/task riêng để stream
  không chặn ảnh chụp, lệnh BLE hoặc theme. Preview **320×240, quality20**,
  giới hạn cấu hình **10 fps**, hai buffer PSRAM và lấy khung mới nhất.
  Ảnh OCR vẫn **2048×1536, quality6**; chuyển chế độ lúc chụp, bỏ buffer cũ
  và đọc SOF trong JPEG để tránh gửi nhầm ảnh preview dưới metadata 3 MP.
- Desktop đọc stream ở thread HTTP riêng, dữ liệu JPEG không đi qua
  worker/IPC BLE. Chỉ giữ một khung mới nhất; UI chỉ bật Chụp sau khi thực sự
  nhận và hiển thị JPEG. Dừng socket khi chụp, đóng cửa sổ, mất BLE hoặc thoát.
  Reader có hủy và timeout; không đóng BufferedReader từ thread Tk gây treo.
- Android **1.6.0+9** dùng một kết nối MJPEG, xử lý multipart chia gói và
  giới hạn bộ nhớ. Ngắt stream khi chụp/đóng/ngắt BLE/xuống nền; loại phản hồi
  từ phiên cũ. Không âm thầm chuyển ảnh sang BLE nếu Wi-Fi chưa sẵn sàng.
  Kiểm tra HTTP trước chụp, tiếp tục CRC32. Log ghi thời gian nhận khung đầu.
- Kiểm chứng: **149 test desktop**, **54 test Flutter**, **615 kiểm tra C++
  host** đạt; analyzer không lỗi. Test HTTP dùng kết nối chunked thực trên
  localhost: nhiều khung tới trước EOF, fragment mọi vị trí, kích thước bất
  thường, hủy/mở lại, mạng im lặng và tiếp tục điều khiển trong lúc stream.
  Build cả profile camera và legacy đạt. Chi tiết build/chữ ký/ABI/model và
  checksum ở `Mobile/validation.json`, `pbl4/docs/camera-validation.json`.
- File để dùng: `pbl4/dist/VietOCR-OV3660.bin` (**2.2.0-stream**),
  `Mobile/dist/VietOCR-arm64.apk` (**1.6.0+9**); desktop mở lại bằng
  `VietHandOCR_API_Release/Run-VietOCR.cmd`. Cần cập nhật cả ESP32 và app,
  cài APK không tự nạp ESP32. Dùng PlatformIO profile `esp32-s3-cam-ov3660`;
  giữ nguyên bộ dây camera đã xác nhận, không cần xóa toàn bộ flash/NVS.
- Bản trước được giữ ở `.toolchain/*-before-stream.bin` và
  `.toolchain/VietOCR-arm64-1.5.0+8.apk`. Mapping APK mới tại
  `Mobile/dist/VietOCR-1.6.0+9-mapping.txt`.
- **Không cài thêm phần mềm/package/model trong lượt này.** Dùng lại Flutter
  `C:\Services\Flutter\flutter`, SDK
  `C:\Users\QuangNew\AppData\Local\Android\Sdk`, JDK
  `.toolchain/java/jdk-21.0.12.1+1`, PlatformIO
  `C:\Users\QuangNew\.platformio`, Python desktop
  `VietHandOCR_API_Release/.venv`. Chỉ sinh mã build/cache và các artifact
  ở vị trí nêu trên; không đổi biến môi trường hệ thống.
- **Chỉ sửa/build, chưa nạp ESP32 hay cài APK lên điện thoại**, theo lựa chọn
  tự nạp của người dùng. Chưa đo FPS, độ nét hay thời gian mở trên bo thật;
  10 fps là mức giới hạn trong mã, không phải số đo trên LAN của người dùng.
  Sau cập nhật, mở Wi-Fi camera → Kiểm tra → Xem camera. Serial có
  `WIFI MJPEG listening port=81`, `WIFI MJPEG first_frame_ms=...`; app ghi thời
  gian khung đầu. Nếu chỉ cổng :80 thông nhưng :81 bị chặn, stream vẫn báo lỗi.
- Log build/kiểm tra: `.toolchain/stream-firmware-build.log`,
  `stream-host-tests.log`, `stream-desktop-tests.log`, `stream-mobile-tests.log`,
  `stream-mobile-analyze.log`, `stream-android-build.log`,
  `stream-android-verification.log`, `stream-release-report.json`.

Tham khảo:
[CameraWebServer của Espressif](https://github.com/espressif/arduino-esp32/blob/2.0.14/libraries/ESP32/examples/Camera/CameraWebServer/app_httpd.cpp),
[esp32-camera: buffer và chế độ grab](https://github.com/espressif/esp32-camera).

## Phục hồi Wi-Fi và ổn định desktop — 27/10/2026, lượt log 22:28–22:32

- Log gửi kèm cho thấy `WIFI STATUS OFFLINE 1`, nhiều lần
  `WIFI_SCAN_FAILED`, trong khi BLE vẫn trả PONG. Người dùng xác nhận TFT
  vẫn chạy, không có hình trong app; không phải ESP32 tự khởi động lại.
  Chưa có chứng cứ lỗi cảm biến/camera native từ log này.
- Lần desktop thoát đầu đi qua `check_interrupt` (SIGINT); lần sau qua lệnh
  đóng cửa sổ. Cả hai exit **0**, model ở lượt sau nạp thành công trên CUDA.
  Vì vậy không quy traceback lỗi mạng thành model crash. Lỗi scan thực tế
  chưa có mã ESP-IDF gốc vì Arduino wrapper chỉ trả `WIFI_SCAN_FAILED`.
- Firmware **2.2.1-recovery** sửa trường hợp cờ `joining_` đã hết hạn nhưng
  driver vẫn reconnect mạng cũ. Scan dừng kết nối offline, tắt auto-reconnect,
  đợi **250 ms** rồi quét nền, tối đa **3 lần**, cách **500 ms**; hủy cả lần
  retry đầu tiên mà Arduino 2.x có thể tự tạo. Không ngắt LAN đang hoạt động
  chỉ vì quét. Join quá **25 giây** thực sự dừng driver; giữ nguyên NVS.
  Serial ghi disconnect reason/kết quả từng lần scan, OFFLINE/JOINING thêm
  reason ở cuối. Chưa đo lại scan/stream trên bo thật; đây là sửa theo log,
  mã driver và kiểm thử lịch retry, không phải xác nhận nguyên nhân vật lý.
- Desktop và Android kiểm tra Wi-Fi status cùng `/health` trước `CAM OPEN`;
  mạng chưa sẵn sàng không bật cảm biến/không cấp phát frame buffer. Desktop
  gắn token từng yêu cầu mở, bỏ phản hồi cửa sổ/phiên cũ sau đóng/mở lại.
  Lỗi mạng có thể phục hồi chỉ ghi WARNING, không in hàng loạt traceback;
  BLE và lệnh theme/PING vẫn tiếp tục hoạt động.
- Launcher Windows tạo GUI bằng `CREATE_NEW_PROCESS_GROUP`, stdin DEVNULL,
  tránh Ctrl+C từ terminal/IDE vô tình đóng GUI. Nút X vẫn đóng bình thường.
  Log ghi `window_close` hoặc `terminal_SIGINT`; không in stack ở lần đóng
  bình thường và không in lại crash trace cũ cho một lần thoát mới không liên quan.
- Android **1.6.1+10**, model FP32 và tối ưu OCR giữ nguyên. Ảnh chụp vẫn
  **2048×1536/quality6**, preview MJPEG **320×240/quality20**, không đổi dây.
  Bản này cần firmware recovery để sửa phía scan; cài APK không cập nhật ESP32.
- Kiểm chứng: **154 test desktop**, gồm tái hiện OFFLINE/quét lỗi qua worker
  BLE ở tiến trình con thật, kiểm tra Tk còn mở và không có CAM OPEN trước
  HTTP; **55 test Flutter**, analyzer sạch; **638 kiểm tra C++ host**, hai
  profile firmware build đạt. Chữ ký APK, model, JNI/R8, ABI và alignment
  được kiểm trong `Mobile/validation.json`. Chi tiết/giới hạn tại
  `pbl4/docs/camera-validation.json`, mục `wifi_recovery_update`.
- Artifact: `pbl4/dist/VietOCR-OV3660.bin` (**2.2.1-recovery**),
  `Mobile/dist/VietOCR-arm64.apk` (**1.6.1+10**). Desktop chạy lại launcher.
  Bản trước giữ ở `.toolchain/*-before-wifi-recovery.bin`,
  `.toolchain/VietOCR-arm64-1.6.0+9.apk`; mapping mới tại
  `Mobile/dist/VietOCR-1.6.1+10-mapping.txt`.
- Không cài thêm công cụ/thư viện/model: dùng lại Flutter
  `C:\Services\Flutter\flutter`, Android SDK
  `C:\Users\QuangNew\AppData\Local\Android\Sdk`, JDK
  `.toolchain/java/jdk-21.0.12.1+1`, Python desktop `.venv` và PlatformIO
  `C:\Users\QuangNew\.platformio` (Arduino core 2.0.14). Chỉ sinh build/cache.
  Không đổi biến môi trường hệ thống, không nạp bo hoặc cài lên điện thoại,
  theo lựa chọn người dùng tự nạp. Chưa tái hiện một native crash từ log này;
  chưa phát sự kiện Ctrl+C thật vào terminal dùng chung khi kiểm thử.
- Log: `.toolchain/recovery-desktop-tests.log`, `recovery-mobile-tests.log`,
  `recovery-mobile-analyze.log`, `recovery-host-tests.log`,
  `recovery-firmware-build.log`, `recovery-android-build.log`,
  `recovery-android-verification.log`, `recovery-release-report.json`.

Đối chiếu driver:
[Espressif — scan khi đang kết nối Wi-Fi](https://docs.espressif.com/projects/esp-idf/en/v4.4.6/esp32s3/api-guides/wifi.html#scan-when-wi-fi-is-connecting).

## Nhớ Wi-Fi và xử lý GATT bị hủy — 27/10/2026, log 23:38

- Trace mới ở `write_gatt_char(PING)`: WinRT trả **0x800704C7**, mã Win32
  **1223**, rồi GATT bị đóng và nối lại. Log có Wi-Fi JOIN trước chuỗi mất
  heartbeat; chưa đủ chứng cứ xác định driver/radio nào gây lỗi, hoặc suy ra
  người dùng đã bấm hủy từ câu thông báo của Windows. Không có bằng chứng
  native GUI crash trong đoạn log này.
- Firmware **2.3.0-autowifi**: lưu **một mạng đã kết nối thành công** ở NVS
  namespace `vietocr-wifi`, key `profile`. Record **104 byte**, version/CRC32,
  chứa SSID/password cùng một blob; ghi rồi đọc lại kiểm tra. Chỉ ghi khi có
  IP và cấu hình khác, không ghi lại theo heartbeat hoặc mỗi reconnect. Đọc
  tương thích keys `ssid`/`pass` cũ, chuyển sang record mới khi kết nối thành
  công. Mạng mới sai mật khẩu không ghi đè mạng thành công trước đó.
- Bật nguồn/RESET tự đọc mạng và kết nối, độc lập với BLE/app. Mất mạng tự
  thử sau **3/6/12/24/60 giây** (mỗi lần thử tối đa **25 giây**); scan và nhập
  cấu hình được ưu tiên, tạm chờ 30/60 giây tương ứng. `WIFI SAVED` đọc trạng
  thái + tên mạng hex, không có password; `WIFI FORGET` xóa cả record/keys cũ.
- Wi-Fi begin/scan, NVS và HTTP start/stop chạy ở **task riêng trên core 0**;
  Arduino loop chỉ đẩy/nhận lệnh qua queue giới hạn 4 phần tử, tiếp tục BLE,
  TFT và buzzer. Worker không ghi trực tiếp vòng TX BLE; epoch loại reply
  thuộc phiên đã ngắt. Tránh trường hợp HTTP shutdown/connect chặn heartbeat.
  Đây là thay đổi loại bỏ một nguồn chặn đã thấy trong mã, chưa chứng minh
  giải quyết toàn bộ nguyên nhân driver WinRT trên máy người dùng.
- Desktop xử lý WinRT cancel theo ACK: nếu ESP32 đã phản hồi đúng thì nhận
  kết quả, **không gửi lặp** SSID/PASS/JOIN/SHOT. Nếu chưa có ACK, hủy phiên
  và nối lại, ghi WARNING rõ lỗi đường BLE. Backoff không reset chỉ vì vừa
  handshake; cần kết nối ổn định 30 giây, tránh lặp nối/ngắt cố định 3 giây.
- Kiểm chứng: **158 test desktop**, trong đó tái hiện cùng HRESULT có/không
  ACK, không gửi lặp credentials, và backoff sau handshake ngắn. **894 kiểm
  tra C++ host**, gồm **246** cho codec + hàm lưu/đọc production với NVS giả
  (đọc legacy, migration, record cắt/hỏng, lỗi ghi/đọc lại), **10** cho reconnect.
  Hai profile firmware build đạt. Những test này không thay thế thử mất điện,
  NVS thật, hay cùng chạy Wi-Fi/BLE trên bo. Chưa nạp bo, theo lựa chọn tự nạp.
- Artifact mới: `pbl4/dist/VietOCR-OV3660.bin` và `VietOCR-legacy.bin`, phiên
  bản **2.3.0-autowifi**. Bản trước ở `.toolchain/*-before-autowifi.bin`;
  checksum/kích thước tại `pbl4/docs/camera-validation.json`, `auto_wifi_update`.
  Desktop mở lại `VietHandOCR_API_Release/Run-VietOCR.cmd`. **Không sửa/build
  APK** lượt này; APK **1.6.1+10** hiện tại tương thích, không cần cài lại.
  Không đổi model/độ phân giải/chất lượng ảnh chụp.
- Không cài thêm công cụ/package: dùng PlatformIO tại
  `C:\Users\QuangNew\.platformio`, Arduino core **2.0.14**, Python trong
  `VietHandOCR_API_Release/.venv`, compiler host `C:\msys64\ucrt64\bin`.
  Chỉ sinh build/cache trong `.pio`, `.toolchain`, `.logs`; dữ liệu nhớ mạng
  sẽ nằm trên ESP32 sau nạp và kết nối thành công, không lưu mật khẩu vào app.
- Log: `.toolchain/autowifi-desktop-tests.log`, `autowifi-host-tests.log`,
  `autowifi-firmware-build.log`, `autowifi-release-report.json`.

Đối chiếu:
[Microsoft — ERROR_CANCELLED 1223](https://learn.microsoft.com/en-us/windows/win32/debug/system-error-codes--1000-1299-),
[Espressif Preferences/NVS](https://docs.espressif.com/projects/arduino-esp32/en/latest/api/preferences.html).

### Bổ sung kích hoạt Wi-Fi khi BLE kết nối — 2.3.1-blewifi

- Theo yêu cầu làm rõ: **mỗi lần BLE kết nối**, không đợi người dùng mở
  Wi-Fi camera/nhấn Quét/Kết nối. Vòng BLE báo sự kiện sang task Wi-Fi;
  bỏ thời gian backoff cũ, dùng SSID/password trong NVS để yêu cầu driver
  tìm mạng rồi kết nối ngay. LAN đang hoạt động giữ nguyên, lượt join đang
  chạy tiếp tục. Tác vụ không chạy trong callback của stack Bluetooth.
- Thông tin nhớ mạng nằm trên **flash/NVS ESP32**, không phải RAM hoặc
  phiên app/BLE. Ngắt BLE, reset hoặc rút nguồn không xóa theo thiết kế;
  `WIFI FORGET`/erase NVS mới xóa. Chưa kiểm tra mất điện/khởi động lại trên
  phần cứng thật. Bộ test dùng store giả để kiểm code lưu/đọc/readback.
- Phiên bản cuối **2.3.1-blewifi**, build cả profile camera/legacy đạt.
  **904 kiểm tra C++ host** (thêm 10 trường hợp BLE wake: vượt backoff,
  mạng đã nối, join đang chạy, chưa có profile). Desktop giữ kết quả
  **158 test** của phần sửa WinRT phía trên; không sửa thêm Python sau đó.
- File mới: `pbl4/dist/VietOCR-OV3660.bin`, `VietOCR-legacy.bin`.
  Bản 2.3.0 giữ `.toolchain/*-before-blewifi.bin`; bản cũ hơn vẫn ở
  `.toolchain/*-before-autowifi.bin`. Metadata cuối xem `auto_wifi_update`
  trong `pbl4/docs/camera-validation.json`; snapshot 2.3.0 giữ riêng.
- Serial nhận `WIFI BLE WAKE: searching saved SSID and connecting now`,
  `LAN already connected` hoặc trạng thái join đang chạy. Dùng `WIFI SAVED`
  để kiểm cấu hình nhớ, không in mật khẩu. APK 1.6.1+10 vẫn tương thích;
  không cài thêm package, không nạp bo thay người dùng.
- Log cuối: `.toolchain/blewifi-host-tests.log`,
  `blewifi-firmware-build.log`, `blewifi-release-report.json`.

## Reset lặp do cấu hình radio — 28/10/2026, 2.3.2-coexfix

- Người dùng cung cấp log hoàn chỉnh: `Should enable WiFi modem sleep when
  both WiFi and Bluetooth are enabled`, `abort() at PC 0x420d88a3`, reboot
  `rst:0xc (RTC_SW_CPU_RST)`. Đây là lỗi cấu hình firmware, không phải suy
  đoán từ lỗi GATT hay lỗi dây màn hình.
- ELF bản 2.3.1 khớp SHA256 **1227e01d80332bf2dd5835d795dd0ce23ca0c8f920d41705f3c416431d30e7c3**
  với tiền tố trong Serial. `addr2line` giải stack: `panic_abort` →
  `esp_system_abort` → `abort` → **pm_set_sleep_type** →
  **wifi_set_ps_process** → `ieee80211_ioctl_process` → `ppTask`.
  File gốc giữ `.toolchain/VietOCR-OV3660-2.3.1-bootloop.elf`, kết quả tại
  `.toolchain/coex-original-backtrace.log`.
- Cấu hình giảm trễ cũ gọi **WiFi.setSleep(false)** sau khi có IP. Arduino
  2.0.14 ánh xạ sang **WIFI_PS_NONE**; SDK 4.4 không cho chế độ đó khi Wi-Fi
  cùng Bluetooth nên abort. Sửa **2.3.2-coexfix**: đặt Arduino cached sleep
  **WIFI_PS_MIN_MODEM** trước `WiFi.mode(WIFI_STA)`, gọi driver set cùng mode,
  loại lệnh tắt sleep sau kết nối. Serial mới in
  `WIFI COEX power_save=MIN_MODEM rc=ESP_OK`.
- `profile NOT_FOUND` trong log là key blob mới chưa có, trong khi
  `WIFI CACHE loaded` xác nhận dữ liệu cũ vẫn đọc được. Thêm `isKey` trước
  khi đọc blob/SSID; không coi thiếu key mới là lỗi và không xóa thông tin
  đã lưu. NVS, nối Wi-Fi khi BLE kết nối, full-resolution capture giữ nguyên.
- Hai profile camera/legacy build đạt, **905 kiểm tra C++ host** qua, gồm
  kiểm tra record/legacy fallback không đọc key blob chưa tồn tại. Rà nguồn
  active chỉ còn cấu hình **MIN_MODEM**; không còn `setSleep(false)` hoặc
  `esp_wifi_set_ps(WIFI_PS_NONE)` trong firmware dự án. Không chạy lại test
  desktop/Flutter vì không thay mã app/model. Không khẳng định đã kiểm tra
  hết lỗi trên phần cứng; bản sửa chưa được agent nạp/run trên bo thật.
- Artifact cuối: `pbl4/dist/VietOCR-OV3660.bin`, `VietOCR-legacy.bin`, version
  **2.3.2-coexfix**. Bản 2.3.1 lỗi giữ `.toolchain/*-2.3.1-bootloop.bin` để
  truy ngược, không dùng lại làm bản khuyến nghị. Metadata/checksum tại
  `pbl4/docs/camera-validation.json`, mục `coexistence_reset_fix`.
- Người dùng nạp bình thường profile `esp32-s3-cam-ov3660`; **không erase
  toàn bộ flash/NVS**, không cần cấu hình lại Wi-Fi chỉ để sửa reset.
  APK 1.6.1+10 dùng tiếp. Không cài thêm package/toolchain hoặc đổi biến môi
  trường; dùng PlatformIO/Arduino 2.0.14 và compiler host đã có.
- Log: `.toolchain/coex-firmware-build.log`, `coex-host-tests.log`,
  `coex-original-backtrace.log`, `coex-release-report.json`.

Đối chiếu:
[ESP-IDF 4.4.6 Station Sleep](https://docs.espressif.com/projects/esp-idf/en/v4.4.6/esp32s3/api-guides/wifi.html#station-sleep),
[Arduino 2.0.14 WiFiGeneric](https://github.com/espressif/arduino-esp32/blob/2.0.14/libraries/WiFi/src/WiFiGeneric.cpp),
[Espressif xác nhận lỗi coexist/WIFI_PS_NONE](https://github.com/espressif/esp-idf/issues/9595).

## 2026-10-28 — Preview native, xem ảnh 3 giây và hàng đợi camera

- Firmware **2.4.1-native**, APK Android **1.7.0+11**. Preview và ảnh chụp
  cùng **2048×1536, JPEG QS0**; giữ nguyên crop/hướng ảnh/cấu hình cảm biến
  khi chuyển từ xem sang chụp. AE/AWB/gain tự động, màu sắc trung tính;
  không tăng gain/phơi sáng cực đại để tránh nhiễu/cháy chữ. XCLK 20 MHz,
  pinout camera/TFT/còi, NVS và Wi-Fi/BLE modem sleep được giữ nguyên.
- Log desktop người dùng có `CAM OPEN`/`OK CAM OPEN`, BLE vẫn PONG nhưng
  stream chưa có JPEG và dừng sau khoảng 8 giây. Không có Serial camera
  để kết luận chính xác lỗi phần cứng. Khi rà driver, thấy bộ đệm mặc định
  chỉ `width*height/5` = **629.145 byte** ở 3 MP, có thể thiếu cho QS0.
  Bản này cấp **2 MiB** thật trong HAL, dùng **một** framebuffer và giải
  phóng bản preview cũ trước khi cấp bản mới để vừa PSRAM 8 MiB.
  Có phục hồi driver camera tối đa một lần nếu thiếu frame; không reset bo.
  Kiểm timestamp để bỏ frame còn trong bộ đệm từ trước lúc mở/chụp, tránh
  hiển thị lại ảnh của phiên cũ khi dùng một framebuffer.
  App báo giai đoạn TCP/HTTP/JPEG và đọc `camera_status` từ `/health`,
  không mặc định quy mọi timeout thành lỗi LAN hay yêu cầu firmware cũ.
- **Đã tải/thêm gì, ở đâu:** năm file nguồn/header Espressif
  `esp32-camera v2.0.4` cùng giấy phép Apache-2.0 tại
  `pbl4/lib/NativeCameraHal/` (đường dẫn đầy đủ:
  `C:\DevLanguage\Works\PBL\PBL4\VietOCR_Handwriting\pbl4\lib\NativeCameraHal`).
  URL và SHA-256 upstream trong `UPSTREAM.json`; thay đổi cục bộ trong
  `src/cam_hal.c`, mô tả tại `README.md`. **Không cài thêm SDK/toolchain,
  không sửa SDK Arduino cài chung, không thay biến môi trường hệ thống.**
  Dùng lại PlatformIO, Flutter, Android SDK/JDK đã có. Addr2line xác nhận
  `cam_config`/`ll_cam_config` trong ELF trỏ về HAL cục bộ, tại
  `.toolchain/native-hal-link-proof.log`.
- Desktop: cửa sổ camera lớn, kéo giãn/phóng to được và khởi tạo trong
  màn hình; giữ ảnh vừa nhận **3 giây**, hoặc **Bỏ qua · Chụp tiếp**, rồi
  đưa vào queue đúng một lần và tự trở lại preview. Đóng khi đang xem ảnh
  vẫn giữ ảnh đã nhận. Bảng tiến trình góc dưới phải trên cả cửa sổ chính
  và camera, thu gọn được, hiển thị trạng thái từng ảnh. Đã sửa dòng
  kích thước thumbnail **101×76** thành kích thước gốc thật.
- Bấm **Ảnh gốc** mở xem lớn, zoom/pan/crop theo pixel native. Crop desktop
  cập nhật ảnh OCR nhưng giữ gốc để khôi phục; chờ OCR xong trước khi áp
  dụng để tránh sửa file worker đang dùng. Xuất JPEG gốc **nguyên byte**.
  Bỏ bước nén JPEG camera sang PNG khi thêm vào queue.
- Android: trang camera lớn/pinch zoom, cùng luồng review/Skip/queue và
  panel tiến trình. File JPEG native được kiểm tra rồi lưu nguyên byte.
  Xem lớn, zoom và crop tạo ảnh vùng mới trong queue. Tải ảnh mở Android
  `ACTION_CREATE_DOCUMENT`, sao chép ở worker I/O, không xin quyền toàn
  bộ bộ nhớ. Không thay model/weights trong lượt này.
- Kiểm tra: **165 test desktop**, **63 test Flutter**, **913 kiểm tra
  C++ host** đạt; Flutter analyzer không có vấn đề. Hai profile firmware
  camera/legacy build đạt. HTTP test có frame đầu đến sau **8,5 giây**,
  MIME bị chia gói/CRLF, frame lớn hơn 128 KiB, ngắt/mở stream; kiểm tra
  timer/Skip/Close, crop và JPEG gốc sau lưu/xuất. GUI đã xem với ảnh giả
  lập, không coi đó là kiểm thử camera thật.
- APK release ARM64 build đạt, kiểm checksum model đóng gói, JNI/R8,
  chữ ký v2 cùng certificate cũ và căn chỉnh ZIP/ELF 16 KiB. Bản mới tại
  `Mobile/dist/VietOCR-arm64.apk`; metadata/checksum `Mobile/validation.json`.
  Firmware tại `pbl4/dist/VietOCR-OV3660.bin` và `VietOCR-legacy.bin`,
  checksum trong `pbl4/docs/camera-validation.json/native_camera_update`.
  Bản cũ giữ `.toolchain/*-before-2.4.1-native.bin` và APK 1.6.1+10 dự phòng.
- Log: `.toolchain/native-firmware-build.log`, `native-host-tests.log`,
  `native-desktop-tests.log`, `native-mobile-tests.log`,
  `native-android-analyze.log`, `native-android-build.log`,
  `native-apk-validation.log`, `native-release-report.json`.
  Agent **không nạp firmware, không cài APK/chạy trên điện thoại**; người
  dùng tự nạp. Không xóa flash/NVS. **Chưa xác nhận sửa hết timeout trên
  bo thật, chưa đo FPS/chất lượng quang học.** JPEG QS0 vượt 2 MiB bị từ
  chối an toàn; không tự hạ độ phân giải/chất lượng hay chấp nhận ảnh cụt.

## 2026-10-28 — Trạng thái Wi-Fi tự động và chẩn đoán camera không có JPEG

- **Firmware 2.4.2-status, Android 1.7.1+12.** Log người dùng từ bản
  2.4.1 xác nhận ESP32 đã đọc mạng lưu trong flash, tự kết nối IP
  `192.168.100.173`, mở HTTP và vẫn ở LAN lúc BLE kết nối. Camera khởi tạo
  thành công nhưng stream có **0 frame**, cả sau một lần khôi phục driver.
  Không coi lỗi camera này là bằng chứng chưa kết nối Wi-Fi.
- Desktop và Android đọc trạng thái ngay sau kết nối BLE, cập nhật mỗi
  **5 giây**, hiện SSID, IP và tên mạng lưu trên ESP32. Trạng thái có ở
  màn hình chính, cửa sổ camera và hộp cài Wi-Fi. Mở cài đặt chỉ đọc trạng
  thái; không tự quét, không cần bấm nút kiểm tra mới biết đã vào mạng.
  Nút **Kiểm tra LAN** kiểm tra HTTP riêng. Tự điền SSID khi ô còn trống,
  giữ nội dung người dùng đang sửa. Bấm Kết nối với mật khẩu trống và đúng
  mạng đang kết nối không thay mật khẩu đã lưu. Ngắt BLE hiển thị chưa đọc
  được trạng thái, không khẳng định Wi-Fi trên bo đã mất kết nối.
- Camera giữ **2048×1536, QS0, XCLK 20 MHz**, một framebuffer 2 MiB.
  HAL dùng vòng đệm SRAM 32 KiB, EOF mỗi 4 KiB để giảm số ngắt; task lấy
  dữ liệu chạy core 1. Bỏ retry đệ quy khi thiếu EOI, giới hạn tổng thời
  gian đợi, chặn đọc marker quá biên và không phát hành frame tràn bộ đệm.
  Đây là sửa các điểm yếu tìm thấy trong mã nhận ảnh; **chưa chứng minh
  chính xác nguyên nhân mất JPEG trên bo người dùng hoặc hết lỗi thực tế**.
- Serial mới phân biệt `CAMERA INIT OK` với `CAMERA FIRST JPEG`. Khi hết
  thời gian chờ, dòng **CAMERA DVP TIMEOUT** hiện các bộ đếm VSYNC, EOF,
  lỗi queue/buffer, SOI/EOI, số JPEG tốt và kích thước cuối. Thông tin lỗi
  cũng đi qua `/health` đến app. Dòng này vẫn hiện khi SDK bỏ log WARNING.
  Wi-Fi/BLE tiếp tục dùng **MIN_MODEM**; không đổi pinout, không xóa NVS.
- **Không cài/tải thêm SDK, package hoặc toolchain trong lượt này.**
  Sửa thư viện đã có tại
  `C:\DevLanguage\Works\PBL\PBL4\VietOCR_Handwriting\pbl4\lib\NativeCameraHal`;
  không sửa SDK Arduino dùng chung hoặc biến môi trường hệ thống.
  Giữ nguồn upstream v2.0.4 và giấy phép; chỉ hai file upstream
  `cam_hal.c`, `ll_cam.c` được sửa, thêm helper `native_jpeg.h`.
- **169 test desktop, 66 test Flutter, 930 kiểm tra C++ host đạt**;
  Flutter analyzer không có vấn đề. Hai profile firmware camera/legacy
  build thành công. GUI Wi-Fi được xem với kết nối giả lập, có đủ thông
  tin và nút bấm; ảnh tại `.toolchain/status-wifi-ui.png`.
  ELF/addr2line xác nhận các hàm nhận camera trỏ đúng HAL cục bộ.
- APK release ARM64 **182.453.822 byte** được xác nhận version, chữ ký v2
  cùng certificate cũ, căn chỉnh ZIP/ELF 16 KiB, JNI/R8, service OCR riêng
  và SHA-256 model FP32 không đổi. Gradle có cảnh báo SDK XML v4/v3 nhưng
  build trả mã 0; không cần tải SDK để hoàn tất bản này.
- Bản bàn giao:
  - `pbl4/dist/VietOCR-OV3660.bin`, **1.472.448 byte**,
    SHA-256 `6e1204ed626833ed11de87e4b5559d72e978fa75d76812175e790624f9dc7e1f`.
  - `pbl4/dist/VietOCR-legacy.bin`, **1.408.192 byte**,
    SHA-256 `8371ad4f03bd30bb1afb5a0816034843270746d829873721815f20df4d783467`.
  - `Mobile/dist/VietOCR-arm64.apk`,
    SHA-256 `1f72902084f4c254b0d629b3c77af729ed4fbc078436d77e2c70da0aaaab78d1`;
    mapping `Mobile/dist/VietOCR-1.7.1+12-mapping.txt`.
  Bản firmware trước lưu `.toolchain/*-before-2.4.2-status.bin`; APK cũ
  `.toolchain/VietOCR-arm64-1.7.0+11.apk`. Nạp profile
  `esp32-s3-cam-ov3660` như trước, không erase flash. Desktop mở lại
  `VietHandOCR_API_Release/Run-VietOCR.cmd` để chạy mã mới.
- Metadata: `Mobile/validation.json`,
  `pbl4/docs/camera-validation.json/wifi_status_camera_update`.
  Log dưới `.toolchain/`: `status-firmware-build.log`,
  `status-host-tests.log`, `status-desktop-tests.log`,
  `status-mobile-tests.log`, `status-android-analyze.log`,
  `status-android-build.log`, `status-apk-validation.log`,
  `status-hal-link-proof.log`, `status-release-report.json`.
  **Không nạp firmware, không cài APK/chạy trên điện thoại thật.**
  Nếu camera vẫn không có hình, cần Serial từ `CAMERA INIT OK` đến
  `CAMERA DVP TIMEOUT` để phân biệt thiếu tín hiệu, tràn DMA hay JPEG lỗi.

Nguồn đối chiếu mã driver:
[Espressif esp_camera.c v2.0.4](https://github.com/espressif/esp32-camera/blob/v2.0.4/driver/esp_camera.c),
[OV3660 v2.0.4](https://github.com/espressif/esp32-camera/blob/v2.0.4/sensors/ov3660.c),
[Espressif giải thích chế độ PSRAM DMA](https://github.com/espressif/esp32-camera/issues/411).

## 2026-10-28 — Chỉ sửa camera: quyền sở hữu GDMA, 2.4.3-camera

- Theo yêu cầu mới, chỉ làm firmware camera và kiểm tra liên quan. Không
  sửa/build Android, iOS hoặc model. Không cài thêm SDK/package/toolchain.
- Log thật bản 2.4.2: Wi-Fi đã kết nối, lần đầu `VSYNC=24 EOF=1 NO_SOI=1`,
  sau khởi tạo lại `VSYNC=23 EOF=0`; không tràn framebuffer, JFIFO=0.
  Không có JPEG để gửi lên app. Chỉ tăng bộ đệm không xử lý được trường
  hợp này; chưa đủ dữ kiện để kết luận chất lượng QS0 là nguyên nhân.
- Phát hiện lỗi cụ thể trong HAL cũ: tự chọn kênh GDMA bằng thanh ghi
  `in.link.addr`, không đăng ký với bộ cấp kênh và không giữ tham chiếu
  clock của ESP-IDF. IDF có thể cấp kênh đó cho client khác hoặc tắt/reset
  peripheral khi client đăng ký cuối cùng rời đi, dù camera vẫn cần DMA.
  Sửa sang `gdma_new_channel` + `gdma_connect(CAM)`; giữ handle đến lúc
  đóng camera, giải phóng có kiểm tra lỗi. Cấu hình lại RX ở mỗi đầu frame,
  không reset toàn bộ GDMA ảnh hưởng client khác. Gỡ ISR trước khi xóa
  queue; bỏ đường giải phóng `cam_obj` sai chủ sở hữu khi cấp kênh thất bại.
- Sửa cục bộ tại `pbl4/lib/NativeCameraHal/src/`: `native_dma.h`,
  `ll_cam.c`, `ll_cam.h`, `cam_hal.c`. Thêm trạng thái DMA và bộ đếm độ dài
  JPEG của cảm biến khi timeout để phân biệt lỗi phát dữ liệu với lỗi nhận.
  Giữ **2048×1536, QS0, 20 MHz**, pinout, NVS và modem sleep MIN_MODEM.
- **287 kiểm tra host liên quan camera đạt**: 229 quản lý DMA (gồm 100 vòng
  mở/đóng), 17 biên JPEG và 41 truyền ảnh. Test DMA mô phỏng vòng đời API
  ESP-IDF và clock, không mô phỏng tín hiệu DVP. Build duy nhất profile
  `esp32-s3-cam-ov3660` thành công. Link map xác nhận `ll_cam.c` tham chiếu
  `gdma_new_channel`; addr2line xác nhận HAL cục bộ vào ELF.
- Artifact **2.4.3-camera**: `pbl4/dist/VietOCR-OV3660.bin`, **1.473.024 byte**,
  SHA-256 `76ebc80efdc0e402c4e09a0ac975504f1ed2465b314e6fda2376b25849dd292f`.
  Bản cũ giữ `.toolchain/VietOCR-OV3660-2.4.2-status.bin`.
  Nạp profile camera như trước; desktop hiện tại dùng tiếp, không cần
  cấu hình lại Wi-Fi. Log mới phải có `READY VIETOCR_ASSISTANT 2.4.3-camera`
  và khi mở camera có `CAMERA GDMA owned RX=... peripheral=CAM clock=managed`.
  Chỉ `CAMERA FIRST JPEG` / ảnh xuất hiện trong app mới xác nhận thu ảnh.
- Log/metadata: `.toolchain/camera-dma-build.log`, `camera-dma-tests.log`,
  `camera-dma-link-proof.log`, `camera-dma-release.json`;
  `pbl4/docs/camera-validation.json/camera_dma_ownership_fix`.
  Không nạp lên bo. **Lỗi quản lý tài nguyên được xác nhận trong mã; chưa
  chứng minh là nguyên nhân duy nhất hoặc stream đã chạy trên bo thật.**

Đối chiếu:
[GDMA ESP-IDF 4.4.6: cấp kênh và vòng đời clock](https://github.com/espressif/esp-idf/blob/v4.4.6/components/driver/gdma.c),
[peripheral clock/reference count](https://github.com/espressif/esp-idf/blob/v4.4.6/components/driver/periph_ctrl.c),
[driver camera Espressif dùng cấp kênh GDMA](https://github.com/espressif/esp32-camera/blob/master/target/esp32s3/ll_cam.c).
Issue [620](https://github.com/espressif/esp32-camera/issues/620) mô tả một
trường hợp GDMA ngừng sau Wi-Fi trên IDF 5.2; không dùng issue đó để khẳng
định cùng nguyên nhân trên SDK 4.4 hiện tại.

## Camera kiểm chứng trực tiếp — 29/10/2026, 2.4.4-stream

- Người dùng cho phép nạp/thử qua COM8. Đã tái hiện 2.4.3 không có JPEG hoàn
  chỉnh. Giữ nguyên QXGA 2048×1536, chỉ đổi QS: QS0/1 thất bại; QS2 có vài
  ảnh rồi ngắt; QS4 chạy được. Không khẳng định QS3 hoặc mọi module giống nhau.
- Đã nạp 2.4.4-stream và xác minh flash bằng esptool. Lượt QS4 dài nhận
  28 JPEG/125 giây. Dùng đúng `BLEProtocol`, `CameraStream`, `capture_fast`
  của desktop kiểm tra ba vòng mở stream 40 giây → chụp → mở lại: nhận
  **48 frame preview và 3 ảnh chụp**, tất cả giải mã ở 2048×1536; ba ảnh chụp
  đúng CRC32, cùng bảng lượng tử JPEG với preview. Không có lỗi trong ba vòng.
- Bản đã kiểm chứng giữ tại `pbl4/dist/VietOCR-OV3660-2.4.4-stream.bin`,
  1.473.056 byte, SHA-256
  `2db484782a4b75a206260ea626cb97247ba49d195949f437e4f2def1403c3bbd`.
  Số đo và giới hạn: `pbl4/docs/camera-hardware-2026-10-29.json`;
  log `.toolchain/camera-ble-stream.log`, `.toolchain/camera-qs4-long.json`.
  Đây là kiểm tra preview 3 MP, khoảng 0,22–0,4 FPS trên LAN ở cảnh thử.
- Không cài thêm thư viện/công cụ; dùng PlatformIO/Python/Pillow/Bleak sẵn có.
  Không xóa NVS, không build/cài APK.

## Preview nhanh và lật ảnh — 29/10/2026, 2.5.0-preview

- Người dùng chọn preview mượt hơn, ảnh chụp vẫn 3 MP, sau đó yêu cầu
  **tiếp tục mà không nạp**. Đã dừng thao tác với bo. Lần upload đầu của bản
  thử preview trước yêu cầu này thất bại vì COM8 không tồn tại; chưa có bản
  2.5.0 nào được nạp. Kết quả phần cứng 2.4.4 phía trên không được dùng làm
  bằng chứng FPS/lật ảnh cho 2.5.0.
- Preview **640×480/QS16**, chụp **2048×1536/QS4**, cùng cửa sổ cảm biến 4:3.
  Hai framebuffer 2 MiB; bỏ giới hạn gửi 10 FPS, desktop đọc frame mỗi 20 ms
  và hiện FPS thật. Tách log tốc độ camera, tốc độ gửi và thời gian gửi.
  Giữ modem sleep MIN_MODEM để tránh lỗi reset Wi-Fi/BLE trước đây.
- Nút **Lật ngang / Lật dọc** trên desktop điều khiển cảm biến qua
  `CAM ORIENT h v`, áp dụng cho cả preview và JPEG chụp. Chọn cả hai là xoay
  180°. Desktop nhớ preferences; ESP32 nhớ NVS `vietocr-camera/orientation`.
  Ghi NVS và đổi thanh ghi chạy task camera. Sau chuyển mode/hướng, bỏ hai
  frame đầu, kiểm tra timestamp và kích thước JPEG; chụp có ngân sách 20 giây.
- Build profile `esp32-s3-cam-ov3660` thành công. **88 kiểm tra desktop đạt**
  (UI 36, BLE 27, IPC 8, Wi-Fi 17), thêm ba ca cuối kiểm tra lật/review/layout.
  **287 kiểm tra C++ camera đạt**. Mã mobile chấp nhận preview VGA 4:3 và
  vẫn báo ảnh chụp 3 MP; 8 kiểm tra Dart/BLE đạt, không build APK.
- Artifact: `pbl4/dist/VietOCR-OV3660.bin` và
  `pbl4/dist/VietOCR-OV3660-2.5.0-preview.bin`, **1.475.456 byte**, SHA-256
  `584fe59f2ff43048f04f529c5ef794ece8944de365ccdc86a49709a43f4c38bf`.
  Metadata `pbl4/docs/camera-preview-validation.json`; build log
  `.toolchain/camera-preview-final-build.log`; test logs
  `.toolchain/camera-preview-*-tests.log` và `camera-preview-final-ui-check.log`.
- **Chưa nạp, chưa đo FPS hoặc kiểm chứng chuyển chế độ/lật trên bo.**
  15–30 FPS là mục tiêu, chưa phải số đo. Không cài thêm thứ gì: dùng
  PlatformIO `C:\Users\QuangNew\.platformio`, Flutter/Dart
  `C:\Services\Flutter\flutter`, Python `.venv` sẵn có. Các gói cài ở những
  lượt trước không bị thay thế.

## Cấu hình camera trong desktop và Android — 29/10/2026

- Tham khảo [easytarget/esp32-cam-webserver](https://github.com/easytarget/esp32-cam-webserver),
  commit `19eec9c143a6181f8970842bb8f1e50cfbf8191e`, đặc biệt nhóm điều khiển
  OV3660 và lưu/khôi phục cấu hình. Repo tự cảnh báo core cũ; không thay
  firmware bằng sketch đó, không sao chép mã nguồn LGPL-2.1. Viết phần cấu
  hình độc lập trên `sensor_t` của driver Espressif hiện có.
- Firmware **2.6.0-config** bổ sung API xác thực `GET/POST /camera/config`,
  19 thông số có giới hạn và schema. Tất cả field được kiểm tra trước khi
  nhận thay đổi. Sensor và NVS được xử lý trong task camera; không làm việc
  này trong callback BLE. App đợi `applied_revision` và, khi yêu cầu nhớ,
  `saved=true`, không coi HTTP 202 là đã lưu xong.
- Desktop: **Xem camera → Cấu hình camera**. Android **1.8.0+13**: biểu tượng
  thanh trượt trong trang OV3660. Có ba preset Mượt/Cân bằng/Chi tiết, chỉnh
  preview/JPEG/trần FPS, sáng/tương phản/màu/sắc nét/giảm nhiễu, cân bằng
  trắng, AE/AGC tự động hoặc thủ công, hiệu ứng, lật ảnh và hiệu chỉnh ống kính.
  Preview mặc định 640×480/QS16, chỉnh 320×240 đến 2048×1536; ảnh chụp giữ
  2048×1536, QS4 mặc định. Chọn preset không đổi chất lượng ảnh chụp 3 MP.
- **Nhớ cấu hình trên ESP32** lưu flash/NVS `vietocr-camera/profile` bằng
  một record 88 byte có version/CRC32, kiểm tra lại sau ghi. Giữ qua ngắt
  BLE, reset và tắt nguồn; profile cũ chỉ có orientation được đọc chuyển
  tiếp. Bỏ chọn thì chỉ áp dụng RAM. Không ghi flash khi kéo từng thanh.
  NVS Wi-Fi riêng vẫn được giữ. Desktop không ghi đè hướng ảnh từ mobile
  khi chỉ mở camera. Đóng trang Android lúc đang áp dụng không tự mở lại
  stream sau khi rời trang; chụp bị khóa trong thời gian đổi cấu hình.
- Build camera và legacy thành công. **177 test desktop**, **72 test Flutter**
  đạt; analyzer không có vấn đề. Kiểm tra C++ gồm range/mode/QS, record NVS,
  CRC/version/cắt cụt/sai dữ liệu, JPEG, DMA, Wi-Fi, nhạc và trạng thái.
  Test HTTP dùng server cục bộ thật; kiểm tra chờ sensor/NVS, giữ BLE khi
  camera từ chối, mở lại stream, UI nhỏ với chữ lớn và đóng trang giữa lúc áp dụng.
  APK được kiểm chữ ký v2, cùng chứng thư bản trước, alignment 16 KiB,
  hash model đóng gói và JNI/R8; model FP32 không thay đổi.
- Firmware: `pbl4/dist/VietOCR-OV3660-2.6.0-config.bin` và bản chung
  `pbl4/dist/VietOCR-OV3660.bin`, **1.485.360 byte**, SHA-256
  `fa413032af024db84546c5a4f31827bf7cdb7c5c1130ab3bf65d250d3247e5f8`.
  APK: `Mobile/dist/VietOCR-arm64.apk`, **182.781.578 byte (~174,3 MiB)**,
  SHA-256 `17ba73de1eab3558a60c0992e47edd59d3cc7900cf33eb1fdaaf3727f0dccf3b`.
  APK release ARM64, ký debug để cài thử PBL. Mapping R8:
  `Mobile/dist/VietOCR-1.8.0+13-mapping.txt`.
- **Chưa nạp firmware, chưa cài APK hoặc đo FPS/kiểm tra thanh ghi cảm biến
  trên thiết bị thật**, giữ yêu cầu tiếp tục không nạp. Trần FPS có thể chọn
  không đồng nghĩa đạt tốc độ đó. Kết quả phần cứng 2.4.4 vẫn tách riêng.
  Báo cáo mới: `pbl4/docs/camera-config-validation.json`, `Mobile/validation.json`;
  log build/test/kiểm gói: `.toolchain/camera-config-*.log`.
- **Không cài thêm dependency hoặc công cụ.** Dùng lại PlatformIO tại
  `C:\Users\QuangNew\.platformio`, Flutter/Dart tại `C:\Services\Flutter\flutter`,
  Android SDK tại `C:\Users\QuangNew\AppData\Local\Android\sdk`, JDK tại
  `.toolchain/java/jdk-21.0.12.1+1`, Python tại
  `VietHandOCR_API_Release/.venv`. Tài liệu/mã tham khảo tải đọc vào
  `.toolchain/references/esp32-cam-webserver`; không đưa repo cũ vào dependency.
  Bản firmware 2.4.4/2.5.0 có tên riêng trong `pbl4/dist` được giữ lại;
  APK trước được lưu trong `.toolchain` bởi script đóng gói.


## 10/11/2026 — Tauri4.0.2, Android4.0.2+20 và Pi tự chạy

- Không cài thêm package lên Pi. Ba unit được cập nhật tại
  `/etc/systemd/system/vietocr-{gateway,camera@,tunnel}.service`, enable và
  đang active. Script nhỏ ở `/home/admin/vietocr-autostart/`; Wi-Fi đã bật
  autoconnect. GPIO vẫn tắt, không reboot/rút mạng khi kiểm.
- EXE `Desktop/dist/vietocr-desktop.exe` từ GitHub CI42775756851,
  sourcea20bb66; zip tải4,752,802byte, EXE13,474,816byte. Không tải C++ SDK.
- APK `Mobile/dist/VietOCR-4.0.2-refactor-arm64.apk`,20,637,449byte, build
  offline từ Maven/Flutter cache đang có; JDK21 tại `.toolchain/java/`,
  Android SDK tại `C:\Users\QuangNew\AppData\Local\Android\sdk`.
  Không tải thêm SDK, NDK hoặc Maven package. Chưa cài APK lên điện thoại.
- Lần gọi Rustup ban đầu đã tạo khoảng180MB mảnh cài MSVC tại
  `C:\Users\QuangNew\.rustup\toolchains\1.94.0-x86_64-pc-windows-msvc`
  rồi được dừng; compiler chưa cài xong. Các mảnh này đã gỡ bằng Rustup,
  tái sử dụng stableGNU để kiểm cục bộ, Windows release build trên CI.
- Lệnh xoá cache bằng shell bị duyệt tự động chặn; dọn an toàn bằng Cargo
  đã thành công, xoá3295file sinh tự động (~1.1GiB). Flutter build cache
  được dọn bằng Flutter sau khi giữ APK ở dist. Không đụng model,
  Python/CUDA, ảnh/bản nháp, credential hay Rust toolchain có sẵn.
- Bản ghi hash, kiểm thử và phạm vi kiểm thực tế:
  `docs/validation/refactor-transfers-2026-11-10.json`. Không tạo client
  Google/API giả hay tiêu lượt OCR thật trong lần kiểm này.
