# VietOCR v4 — hướng dẫn phát triển và triển khai

Cập nhật 09/11/2026 (Asia/Saigon). Nhánh triển khai: **`refactor`**.
Tài liệu này hướng dẫn luồng mới; bằng chứng build/kiểm thử và các bước còn thiếu
được cập nhật ở [docs/REFACTOR_PROGRESS.md](docs/REFACTOR_PROGRESS.md).

## 1. Thành phần

| Thành phần | Thư mục | Chạy ở đâu |
|---|---|---|
| Gateway Rust + camera broker + TFT/còi | `Gateway/` | Raspberry Pi 4B, OS 64-bit |
| Hợp đồng và parser MJPEG dùng chung | `Contracts/rust/` | Rust gateway/client |
| Logic native client | `ClientCore/` | Windows |
| Desktop Tauri 2 | `Desktop/` | Windows + WebView2 |
| Android Flutter | `Mobile/` | Android; không có model/BLE |
| Inference API, queue, worker manager | `Server/backend/` | Windows máy có GPU |
| Model worker Python và bộ xác minh ảnh | `Server/worker/` | Cùng máy inference |
| Quản trị Next.js | `Server/web/` | Máy server |
| Auth / quota / metadata / history | `supabase/migrations/` | Supabase project |

Client đăng nhập **Google duy nhất**, Pi xác minh phiên và tài khoản. Webcam USB
nằm trên Pi. Chụp/tải ảnh/crop/đen trắng chỉ tạo bản nháp riêng trên client.
**Gửi** mới tạo intent → xin lease → upload qua Pi → server kiểm file và commit.
Client đọc kết quả **trực tiếp từ compute** bằng vé ngắn hạn chỉ cho một job.

Pi không có service-role key. Compute giữ credential DB và cung cấp một adapter
machine-to-machine chỉ cho các thao tác cố định. Đây là ranh giới credential;
người dùng không được gọi adapter bằng Google JWT/API key cũ. API v1 tắt mặc định.

## 2. Công cụ cần có

- Máy server: .NET 10 SDK/runtime, Python 3.11 và môi trường PyTorch/CUDA hiện có.
  Model `Server/models/ML_s44/ml_s44_fp16.pth` giữ nguyên. Tạm thời server vẫn dùng
  Python trong `VietHandOCR_API_Release/.venv`; **chưa xoá môi trường đó**.
- Desktop: Rust MSVC 1.94+, Visual C++ Desktop Build Tools + Windows SDK, WebView2.
  Chỉ build client không cần Python, CUDA, Android SDK hoặc npm frontend.
- Gateway: Rust 1.94+ để build; có thể dùng artifact ARM64 CI, không cài compiler Pi.
- Android: Flutter/Dart đã cài, Java/Android SDK đang có; `flutter doctor -v` kiểm tra.
- Admin: Node.js 22+, `npm ci` trong `Server/web` khi thiếu dependency.
- Database: Supabase CLI đã đăng nhập hoặc SQL Editor của đúng project.

Không cập nhật/tải CUDA, model, SDK hay toolchain lớn nếu đã có bản dùng được.
Windows máy phát triển hiện chỉ có Rust GNU; build Tauri MSVC có thể dùng CI
`Refactor foundation` → artifact `vietocr-desktop-windows`, tránh tải C++ SDK cục bộ.

## 3. Cấu hình Supabase

Project hiện tại: `https://rrdxhztiikizgogxtlhu.supabase.co`.

1. Authentication → Providers → chỉ bật Google cho client v4. Google OAuth dùng
   callback Supabase hiển thị trong dashboard; Client Secret chỉ ở Supabase.
2. Authentication → URL Configuration → Redirect URLs:
   - `http://127.0.0.1:47821/auth/callback`
   - `vn.pbl4.vietocr://auth/callback`
3. JWT signing: ES256, giữ JWKS rotation do Supabase quản lý. Pi không nhận signing key.
4. Chỉ dùng `publishableKey` công khai trong app/Pi. `SupabaseServiceKey` chỉ trên compute.
5. Áp dụng migrations theo thứ tự. Nếu đã có bảng từ bản cũ nhưng chưa có lịch sử
   CLI, không chạy reset; kiểm tra schema rồi dùng SQL Editor/`db query --file` cho
   các migration còn thiếu. Mỗi migration cần transaction và ghi nhận phiên bản.

```powershell
supabase projects list
supabase migration list --linked
supabase db query --linked "select to_regclass('public.ocr_v2_intents');"
```

Thứ tự: `202611030001` baseline → `202611090001` 500/30 → `202611090002`
Google session → `202611090003` quota leases → `202611090004` luồng gateway.
Không chạy lại migration003 trên DB đã áp dụng vì có rename RPC.

Trần 500 ảnh/ngày, 30 **ảnh đã nhận đủ/phút**, múi giờ `Asia/Ho_Chi_Minh`.
Admin có thể hạ limit. Snapshot, preview, bản nháp và upload chưa đủ không tính ảnh.
Lease có thời hạn, retry cùng request/hash/layout không tính hai lần. Không sửa
counter quota bằng tay hoặc reset dữ liệu để né lỗi migration.

## 4. Ghép compute với Pi

Tạo hai random token độc lập, ít nhất 32 ký tự URL-safe:

- **Ingress token**: Pi dùng tạo intent, xin lease, truyền ảnh và yêu cầu scale.
- **Telemetry token**: Pi chỉ đọc stats CPU/RAM/worker cho TFT/còi.

Chạy `tools/Prepare-V2Pairing.ps1` để tạo file cục bộ đã ignore và hash; không commit,
không gửi token qua chat. Compute giữ SHA-256 của token, Pi giữ token gốc trong file
quyền0600. Vé đọc kết quả do ASP.NET Data Protection tạo; không dùng ingress token.

Trong `Server/server.local.json`, giữ cấu hình Supabase và thêm:

```json
{
  "AllowedHosts": "localhost;127.0.0.1;[::1];ocr.example.com;compute.example.com",
  "Server": {
    "GatewayIngressKeySha256": "SHA256_INGRESS_TOKEN",
    "GatewayTelemetryKeySha256": "SHA256_TELEMETRY_TOKEN",
    "PublicResultsOrigin": "https://ocr.example.com",
    "ServerId": "compute-1",
    "LegacyClientApiEnabled": false,
    "GatewayAutoScale": true
  }
}
```

Đây là **các trường bổ sung**, không ghi đè làm mất Supabase/Python settings.
Không expose `server.local.json`, `runtime/keys`, spool hay model qua web server.
Server luôn giữ quyền từ chối tăng worker khi thiếu RAM/VRAM dự phòng; số model
75MB không phải lượng VRAM thực của một Python/CUDA process.

```powershell
dotnet build Server/backend/VietOcr.Server -c Release
dotnet run --project Server/backend/VietOcr.Server --no-launch-profile --urls http://127.0.0.1:5080
# Admin, terminal riêng:
cd Server/web
npm run dev
```

Nếu đang có coordinator cũ, đóng bằng terminal đã mở trước khi chạy bản mới;
không chạy hai coordinator trên cùng DB. DB lease tự ngăn hai bộ dispatch.

## 5. Raspberry: camera và gateway

Máy đã kiểm tra: `admin@rasp4gb`, Raspberry Pi OS aarch64, µStreamer5.4 và v4l2-ctl.
Thông tin mật khẩu không ghi trong tài liệu/repo. Dùng SSH của bạn để triển khai.

```sh
uname -m                  # phải là aarch64
v4l2-ctl --list-devices
v4l2-ctl -d /dev/video0 --list-formats-ext
ustreamer --device=/dev/video0 --host=127.0.0.1 --port=8080 \
  --format=MJPEG --encoder=HW --resolution=1920x1080 --desired-fps=30 \
  --buffers=3 --workers=1 --slowdown
```

Chỉ chọn mode **MJPG** webcam công bố. Native JPEG không decode/encode lại trên Pi.
µStreamer chỉ bind loopback, không publish trực tiếp `/stream` ra Internet.
1920×1080@~30fps đã đo broker trên Pi; tốc độ Internet còn phụ thuộc uplink.
Camera chia sẻ nên mọi tài khoản hợp lệ đều thấy cùng khung cảnh.

Lấy ARM64 artifact CI hoặc build `cargo build --release -p vietocr-gateway` trên
máy ARM64. Chép binary và `Gateway/config.example.json` lên Pi, cấu hình:

```json
{
  "listen": "127.0.0.1:5082",
  "auth": {"supabaseUrl":"https://rrdxhztiikizgogxtlhu.supabase.co", "publishableKey":"PUBLIC_KEY", "databaseConcurrency":8},
  "cameras": [{"id":"desk", "name":"Webcam Raspberry", "upstream":"http://127.0.0.1:8080"}],
  "compute": {"origin":"https://compute.example.com", "publicResultsOrigin":"https://ocr.example.com", "tokenFile":"/etc/vietocr/ingress.token", "concurrentUploads":4},
  "telemetry": {"url":"https://compute.example.com/api/internal/v2/status", "tokenFile":"/etc/vietocr/telemetry.token"},
  "panel": {"enabled":false, "dcBcm":25, "resetBcm":24, "buzzerBcm":18, "spiHz":16000000}
}
```

Các trường còn lại lấy mặc định hữu hạn: 8 viewer, tối đa2/account, 4 snapshot,
32 request điều khiển đang chạy. 1000 OCR client không đồng nghĩa 1000 webcam viewer.
Khi vượt công suất, client nhận429/Retry-After, giữ ảnh và gửi tiếp; không giữ1000 ảnh RAM.

```sh
chmod 600 /etc/vietocr/*.token /etc/vietocr/config.json
/opt/vietocr/vietocr-gateway /etc/vietocr/config.json --check-config
curl http://127.0.0.1:5082/health/live
```

Mẫu systemd trong `infra/raspberry/`. Tạo user/group và sửa đường dẫn trước
`systemctl enable --now`. Giữ quyền video/spi/gpio hẹp; không chạy HTTP gateway root.

## 6. TFT và còi

Chưa bật GPIO trong config trước khi kiểm tra dây và enable SPI trên Pi.
GPIO dùng **BCM**, không lấy pin ESP32 cũ: CS8, MOSI10, SCK11, MISO9 (tuỳ chọn),
DC25, RESET24. ILI9341 VCC/LED theo module3.3V và GND chung.
TMB12A05 là còi active5V: dùng transistor/driver phù hợp từ GPIO18, không cấp5V
ngược vào GPIO Pi. Mặc định còi low, không beep boot/chụp/đăng nhập.

TFT lấy stats **máy compute**. CPU **hoặc** RAM **hoặc** busy/(idle+busy) >=85%
liên tục5s mới kêu180ms; tối thiểu60s giữa các đợt, chỉ rearm khi mọi chỉ số hợp lệ
<80%. Loading/draining không tính là worker rảnh. Stats quá10s → offline, không kêu.

## 7. Internet / HTTPS

Dùng hai connector named tunnel, một trên Pi, một trên Windows; mẫu trong
`infra/tunnel/`. Thay hostname thật và credential path, route hostname/path chính
xác, catch-all404. Không commit tunnel credentials, không dùng `noTLSVerify`.

- Pi domain → `http://127.0.0.1:5082`.
- Compute internal domain → `/api/internal/v2/*`, kiểm machine token.
- Result domain → chỉ `/api/v2/results/*` cho client.
- Admin domain (nếu cần) dùng chính sách bảo vệ riêng, không chung public result.

Không gửi bearer token trên query string. Proxy phải chuyển Authorization,
Content-Length, Upload-Offset và X-OCR-Generation; không cache camera/kết quả,
không buffer toàn bộ MJPEG. Giữ HTTP origin loopback sau connector.

## 8. Chạy client

**Desktop**: build Tauri trên Windows MSVC hoặc lấy artifact EXE; mở app, cấu hình
Pi HTTPS, đăng nhập Google bằng browser. Import/camera tạo nháp, clickẢnh gốc để
zoom/crop, vẽ tự do hoặc hình có góc quay. Đen trắng OCR là bản mới; có tải từng
ảnh/toàn bộ, sửa text/xuất.txt. Camera giữ mở, review3s hoặc Skip. NútGửi chuyển
ảnh theo khối1MiB; UI không chứa access/refresh/machine token.

**Android**:

```powershell
cd Mobile
flutter pub get
flutter analyze
flutter test
flutter build apk --release --target-platform android-arm64
adb install -r build/app/outputs/flutter-apk/app-release.apk
```

Mở Google & Raspberry → địa chỉPi. OAuth callback Android giữ applicationId,
scheme/signing hiện có. Không còn quyền Bluetooth/camera local hoặc model mobile.
Token phiên được mã hoá Android Keystore. Chụp/crop/import không tự gửi ảnh.

## 9. Kiểm tra trước khi dùng thật

```powershell
cargo test --workspace
cargo clippy --workspace --all-targets -- -D warnings
dotnet test Server/backend/VietOcr.Server.Tests
node --test Desktop/tests/*.test.mjs
cd Contracts/tests
npm ci --ignore-scripts
npm test
# Native race suite chỉ dùng PostgreSQL loopback DB tên *_test, không dùng production.
```

Kiểm lần lượt: health200 → camera khôngJWT401 → Google session200 → snapshot
giữ nguyênJPEG → intentkhôngtínhlượt → uploaddởkhôngtínhlượt → complete1lượt →
gửi lạicùngrequestkhôngtínhthêm → nhậntextdirectcompute → mởappkhôi phụckếtquả →
đổiGooglekhônglộnháptàikhoảntrước → clientkhôngtạojobtrựctiếpcompute.

Testmấtmạng,đầythưmụcspool,workerchết,quota,ban,tokenhếthạnvàcamrútUSB trước
đo tải. Chưa coi số đo broker30fps là kết quả1000clientInternet. Không chạy load
test1000JWTbằngtài khoảnthật hoặcđốtquotaSupabase;dùngstaging/fixturecógiớihạn.

## 10. Dọn dẹp và rollback

`pbl4/` firmware cũ đã xoá, khôi phục từ lịch sử Git khi cần. Flutter bỏ module/test
BLE/ESP32; không mang firmware vàoPi. Python desktop cũ chỉ được xoá sau khi đã
tách môi trường server và hoàn tất kiểm tra clientTauri. Không xoá model, CUDAenv,
signingkey,session/draftảnhngườidùng. Chỉ xoá buildcache sau khi có artifact.

Rollback: dừng gatewaybảnmới, quay binaryconfigtrước; acceptedjob trêncomputevẫn
chạy. SQL recovery xem `docs/REFACTOR_DB_ROLLOUT.md`; khôngresetdatabase/usage.

## Tình trạng triển khai

Mục này được điền sau kiểm thử thực tế ở cuối lượt triển khai. Các kiểm tra chưa
chạy (tên miền thật, Google tương tác, TFT/còi vật lý, tải1000 và release clients)
phải ghi đúng trạng thái, không đánh dấu đạt chỉ vì mã đã compile.
