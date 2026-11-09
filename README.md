# VietOCR v4

Nhánh triển khai: **[refactor](https://github.com/QuangNew/VietOCR_Handwriting/tree/refactor)**.

Client Windows Tauri 2 / Android Flutter → Raspberry Pi Rust gateway → server Windows C#/Python. Supabase quản lý Google Auth, tài khoản, quota và lịch sử; Next.js giữ phần quản trị.

| Thành phần | Mã nguồn | Tình trạng |
|---|---|---|
| Gateway, webcam chung, telemetry/TFT/còi | [Gateway](Gateway/README.md) | Đã chạy bằng systemd trên Pi; GPIO tắt đến khi xác minh dây |
| Client Windows, không Python/model/BLE | [Desktop](Desktop/README.md) | Đã build EXE; đang hoàn thiện kiểm thử triển khai |
| Client Android, không model/BLE/camera local | [Mobile](Mobile/README.md) | Đã build APK v4; đang kiểm thử luồng mới |
| API inference, queue, GPU/CPU workers | [Server](Server/README.md) | Đã kiểm luồng Google → Pi → model → nhận kết quả trực tiếp |
| Contract và database | [Contracts](Contracts/openapi-v2.json), `supabase/` | Migrations v2 đã áp dụng lên project hiện tại |

Webcam cắm **Pi**, dùng chung cho các tài khoản hợp lệ. Ảnh chụp, import và chỉnh sửa là bản nháp riêng; **Gửi** mới upload và tạo OCR. Pi chuyển tiếp từng khối, server ghi ảnh bền vững rồi mới tính một lượt. Client đọc kết quả trực tiếp từ compute bằng vé ngắn hạn. Trần **500 ảnh/ngày, 30 ảnh được nhận/phút**, dùng chung mọi thiết bị; admin có thể hạ giới hạn.

Tiến độ và bằng chứng: [REFACTOR_PROGRESS.md](docs/REFACTOR_PROGRESS.md). Phạm vi đã duyệt: [REFACTOR_PLAN_2026-11-08.md](docs/REFACTOR_PLAN_2026-11-08.md). Tên miền dự kiến `api.quangnew.tech` cho Pi và `ocr.quangnew.tech` cho compute; **chưa công bố Internet sẵn sàng khi Cloudflare/DNS còn cấu hình**.

`pbl4/` và cache ESP32 cũ đã gỡ. Server hiện còn dùng Python/CUDA tại `VietHandOCR_API_Release/.venv`; không xoá môi trường này. Launcher Python cũ đã chuyển sang mở client Tauri. Firmware có thể lấy lại từ Git history; không cần giữ PlatformIO trên nhánh mới.

## Kiểm tra mã

```sh
cargo test --workspace --locked
cargo clippy --workspace --all-targets --locked -- -D warnings
dotnet test Server/backend/VietOcr.Server.Tests
node --test Desktop/tests/*.test.mjs
cd Mobile
flutter analyze --no-pub
flutter test --no-pub --concurrency=1
```

SQL tests nằm trong `Contracts/tests`; native PostgreSQL suite chỉ chạy trên database disposable tên `*_test`. Không tạo hàng nghìn tài khoản hoặc đốt quota project thật để giả lập tải. Hướng dẫn DevTodo sẽ được chốt sau khi các cổng triển khai còn thiếu đã kiểm chứng.
