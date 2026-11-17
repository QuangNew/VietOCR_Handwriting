# VietOCR Control — server nhận diện

**ASP.NET Core 10 + Next.js + Supabase PostgreSQL/Auth**, model **ML_s44** chạy trên máy host bằng Python/PyTorch. Desktop và Android chỉ dùng server; không nạp model cục bộ. XAMPP không còn là dependency vận hành.

Trên nhánh `refactor`, server giữ C#/Python/Next.js và nhận OCR qua Raspberry. Xem [tiến độ](../docs/REFACTOR_PROGRESS.md), [API v2](docs/API.md) và [rollout database](../docs/REFACTOR_DB_ROLLOUT.md). Migrations500/30 đã áp dụng; tên miền/tunnel còn cần xác minh trước khi dùng qua Internet.

## Chạy trên máy này

```powershell
Server/Run-Server.cmd
# Chỉ dành cho phát triển trong LAN tin cậy:
Server/Run-Server.cmd -Lan
```

Dashboard: `http://127.0.0.1:3000`; compute nội bộ: `http://127.0.0.1:5080`. Client cấu hình HTTPS của Pi, không kết nối trực tiếp cổng5080 để gửi ảnh. API v1 mặc định trả410. Webcam nằm trên Pi; firmware và client BLE/ESP32 đã gỡ.

Tài khoản quản trị hiện có đã chuyển sang Supabase. Thông tin đăng nhập trên máy nằm trong `runtime/admin-first-login.txt` (private, không commit). Tạo admin khác bằng `tools/New-Admin.ps1`; không có đăng ký admin công khai. Chạy `tools/Build-Server.ps1` sau khi sửa mã.

## Điều hành

- **Tài khoản & API**: chỉnh tên, quota, khoá/mở; tạo/cấp lại API key tích hợp. Tài khoản Google tự xuất hiện sau đăng nhập client lần đầu.
- **Cấu hình server**: bật/tắt nhận việc, pause queue, timeout, retention, giới hạn upload/queue và RAM/VRAM dự phòng; lưu trên Supabase.
- **WorkerSpace**: chọn Tự động, GPU rời, GPU tích hợp DirectML hoặc CPU cho từng worker; đo RAM/VRAM thực. Tự động ưu tiên GPU rời → GPU tích hợp → CPU; mọi lần thêm đều kiểm tra tài nguyên.
- **Hàng đợi / Nhật ký**: xem lỗi gốc, trạng thái/kết quả, huỷ job, tra thay đổi quản trị.

Mỗi tài khoản có mã OCR cố định; request dùng phiên Google có thời hạn. Giới hạn **500 ảnh/ngày, 30 request OCR trong 60 giây**, dùng chung mọi thiết bị. Tăng bộ đếm và ghi job là một transaction PostgreSQL; không thể vượt bằng request đồng thời hoặc restart server. Chi tiết OAuth, callbacks, schema, quota và quyền admin tại [SUPABASE.md](docs/SUPABASE.md).

## Model và tài nguyên

Model lưu tại `models/ML_s44/ml_s44_fp16.pth` (72,9 MiB), runtime FP32/V2c 64px, worker persistent. Không tải trọng số từ Internet. Server dùng Python CUDA tại `.venv/Scripts/python.exe` (interpreter riêng trong `.python/`); đây là môi trường **server**, không phải yêu cầu cài PyTorch cho client mới.

Dự toán `(6144−1024)/300≈17` chỉ là tính ban đầu. Phép đo trước đây: một worker khoảng 266 MiB CUDA reserved và khoảng 1,1 GiB RAM cả cây process; phải cộng CUDA context, activation, warm-up và phần dự phòng. Không tự nạp 17 worker. Nếu web báo thiếu RAM, giải phóng RAM rồi thêm worker. App vẫn giữ ảnh khi server chưa sẵn sàng.

Queue round-robin theo tài khoản, FIFO bên trong từng tài khoản. Worker lỗi native được thay process và retry có giới hạn; input trên ổ đĩa, trạng thái/kết quả trên Supabase. Giữ ít nhất 1 GiB RAM/VRAM theo mặc định. Ảnh tạm xoá sau kết thúc; kết quả giữ 24 giờ mặc định. Host chết có thể thực hiện lại inference: at least once, không cam kết exactly once. Một coordinator/lease cho một project.

Các worker rảnh cũng được chọn luân phiên, kể cả khi request đến từng cái. Worker đang bận hoặc đang dừng được bỏ qua; worker nhanh nhận việc tiếp mà không phải chờ worker chậm. Client gửi có giới hạn đồng thời và theo cơ chế cấp lượt của Pi; ảnh đã nhận nằm trên compute, không giữ hàng nghìn file trong RAM Pi. Một ảnh chạy trên một worker. Bản JPEG/PNG gốc luôn được giữ; bản tối ưu ảnh là tuỳ chọn riêng.

Xem [đo độ trễ và chia tải](docs/PERFORMANCE.md). `Run-Server.cmd` build lại web production trước khi chạy để tránh dùng UI cũ; cần đóng phiên server trước khi mở lại. Bản Android hiện tại không cần đổi để nhận lợi ích của bộ điều phối phía server.

## Dev và kiểm tra

```powershell
# Backend
 dotnet test Server/backend/VietOcr.Server.Tests/VietOcr.Server.Tests.csproj -c Release
# Frontend
 cd Server/web
 npm run dev
 npm run check
 npm run build
 npm run test:e2e
```

Agentation chỉ render trong dev để đánh dấu/chỉnh UI. Không có trong production. Giao diện tự triển khai, responsive sáng/tối và biểu đồ SVG; [giấy phép thư viện](docs/THIRD_PARTY.md).

Kiểm thử Supabase thật: `tools/check_supabase.py`, `validation/rls-account-isolation.sql`; API thật: `tools/check_api.py`. Dùng đúng Python môi trường server và CLI đã link. Reports [validation](validation/), [ghi nhận mới](docs/VALIDATION_SUPABASE.md), [cài đặt](docs/INSTALL_REPORT.md). OAuth trên thiết bị thật cần người dùng đăng nhập Google; không coi cấu hình provider thành kiểm chứng đăng nhập.
