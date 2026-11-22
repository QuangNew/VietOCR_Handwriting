# VietOCR

VietOCR chuyển chữ viết tay tiếng Việt thành văn bản. Android và desktop gửi ảnh qua Raspberry Pi. Worker Python trên máy chủ chạy tiền xử lý Native và model ML_s44. Supabase quản lý đăng nhập Google, hạn mức và lịch sử.

| Bạn muốn làm gì | Mở ở đâu |
|---|---|
| Dùng hoặc phát triển app Android | [apps/android](apps/android/README.md) |
| Mở app Windows | [apps/desktop](apps/desktop/README.md) |
| Chạy server, model và web admin | [services/compute](services/compute/README.md) |
| Làm việc với webcam và gateway Pi | [services/gateway](services/gateway/README.md) |
| Xem giao thức, dữ liệu kiểm thử và Rust dùng chung | [shared/contracts](shared/contracts/openapi-v2.json), `shared/client-core` |
| Cài dịch vụ Pi và tunnel | [infra/raspberry](infra/raspberry/README.md), `infra/tunnel` |
| Quản lý schema và chính sách Supabase | `supabase/migrations` |

Trên Windows, chạy `services/compute/Run-Server.cmd` và vào `http://127.0.0.1:3000` để quản trị. [DevTodo.md](DevTodo.md) chỉ từng bước để mở laptop, Pi, dịch vụ và tunnel. Đọc [hướng dẫn worker Native](services/compute/worker/native/README.md) để kiểm bản bàn giao của nhóm.

## Kiểm tra từ thư mục gốc

```powershell
cargo test --workspace --locked
dotnet test services/compute/backend/VietOcr.Server.Tests -c Release
node --test apps/desktop/tests/*.test.mjs
services/compute/.venv/Scripts/python.exe -X utf8 services/compute/tools/check_native_worker.py --device cpu
```

Android dùng `flutter analyze --no-pub` và `flutter test --no-pub` trong `apps/android` sau khi đã chạy `flutter pub get`. Kiểm thử cơ sở dữ liệu chạy tại `shared/contracts/tests` với dữ liệu riêng cho test.

Cấu trúc trước khi chuyển có thể xem ở commit `f6dab00`. Nhánh triển khai là [refactor](https://github.com/QuangNew/VietOCR_Handwriting/tree/refactor).
