> Báo cáo này thuộc milestone MySQL/optional-local trước đó. Trạng thái hiện tại: [VALIDATION_SUPABASE.md](VALIDATION_SUPABASE.md).

# Kiểm tra ngày 03/11/2026

Máy Windows, RTX 4050 Laptop 6 GB, RAM 16 GB, Python 3.11 / PyTorch 2.14.1+cu126, .NET SDK 10.0.114, Node 22.21.1, XAMPP MariaDB 10.4.32. Model ML_s44 FP32 / ảnh cao 64 / V2c, SHA checkpoint `644f2613046e4974c3aea5878e61d119b9100debe05cb55756b85b8241254cb2`.

| Kiểm tra | Kết quả |
|---|---|
| Backend .NET tests | 18 qua: fair queue, nhiều producer, huỷ, dedup, bộ nhớ dự phòng, GPU stale/missing, percentile, mật khẩu/hash. |
| Desktop | 220 qua; thêm kiểm tra server routing không spawn/nạp model cục bộ, DPAPI round trip, không lộ key trong repr. |
| Mobile | 88 unit/widget tests qua; thêm HTTP multipart/poll thật với local test server, cancellation, không tự fallback offline. |
| Dart analyzer | Không có vấn đề; kiểm tra toàn mobile và các file server mới. |
| Web | Next.js production build thành công; 3 Playwright tests qua ở desktop 1440 px và mobile 390 px, theme/navigation/back button, không tràn trang, auth/CSRF. |
| C# + MySQL + GPU API | 11 kiểm tra qua trên server thật: auth, CSRF, key riêng, idempotency, isolation, key revoke, inference, xoá ảnh, metrics. |
| Client app → C# thật | Desktop OCRProcessService và Dart transport trả văn bản Việt giống nhau; desktop không import torch/không tạo local AI process. |
| Restart / backpressure | MySQL + image spool giữ nguyên sau restart; queue đầy trả 429/Retry-After; huỷ công việc đã khôi phục và xoá file. |
| Native model chết giữa request | Chủ động tắt đúng tiến trình Python đang chạy: API sống, cùng job được xử lý lại bởi worker mới, attempts=2, khoảng 7 giây. |
| API bị kill | Windows Job Object/parent watcher thu hồi cây Python, không còn model process sau khi host dừng. |
| Agentation | Toolbar thực sự hiện trong dev; production chunks không có toolbar/runtime Agentation. |
| Android build | 2.1.0+16 arm64 release, 137,48 MiB; chữ ký v2, cùng cert bản trước, 16 KB ZIP/ELF alignment và R8 JNI callbacks đã xác minh. Chưa cài/chạy trên điện thoại thật. |
| Desktop build | Launcher EXE đã build và `--check` qua; dùng source + Python environment trong repo, không phải portable EXE chứa tất cả. |

Ảnh UI: [desktop](../validation/ui/overview-desktop.png), [mobile](../validation/ui/overview-mobile.png), [WorkerSpace](../validation/ui/workers-desktop.png), [Agentation dev](../validation/ui/agentation-dev.png).

Số đo model thật: [api-checks.json](../validation/api-checks.json), [app-transports.json](../validation/app-transports.json), [load-test.json](../validation/load-test.json), [persistence-checks.json](../validation/persistence-checks.json), [worker-recovery.json](../validation/worker-recovery.json). Không lưu văn bản/ảnh trong các report đo tải; ảnh tạm đã được dọn.

Thử tải 8 ảnh một dòng từ hai client, một worker nóng: 4,09 giây, 1,95 ảnh/giây. Worker khoảng 154 MiB tensor / 266 MiB CUDA reserved / 1,1 GiB RAM cây tiến trình. Lần đo này không đủ RAM dự phòng để thêm worker thứ hai, nên không suy diễn throughput hai worker hoặc 17 worker. 17 là công thức dự toán ban đầu. Chưa thử tải dài ngày, Internet, điện thoại thật, multi-host hoặc cấp SLA.

P50/P95 dùng tối đa 20.000 công việc gần nhất trong cửa sổ 15 phút và có nhãn khi lấy mẫu. Tổng thành công/thất bại, success rate, throughput và trung bình lấy từ aggregate MySQL trên toàn cửa sổ, không bị cắt theo số mẫu percentile. Độ trễ job không bao gồm upload mạng.

Lệnh chạy lại, từ repo:

```powershell
dotnet test Server/backend/VietOcr.Server.Tests/VietOcr.Server.Tests.csproj -c Release
# Sau khi bật server, có admin local:
VietHandOCR_API_Release/.venv/Scripts/python.exe Server/tools/check_api.py --inference
VietHandOCR_API_Release/.venv/Scripts/python.exe Server/tools/check_app_transports.py
# Lệnh tiếp theo chủ động dừng worker đang chạy; chỉ dùng trong phiên kiểm tra:
VietHandOCR_API_Release/.venv/Scripts/python.exe Server/tools/check_worker_recovery.py
# Tắt API chính trước khi kiểm tra restart/queue trên cổng 5081:
VietHandOCR_API_Release/.venv/Scripts/python.exe Server/tools/check_persistence.py
```

APK: `Mobile/dist/VietOCR-arm64.apk`, SHA-256 `ed7c326c3c7f503fcec5269df48c57a125a87d2dce00954a6c31de8739e3abf3`. Bản cũ được giữ ở `.toolchain/VietOCR-arm64-2.0.0+15.apk`. Model offline vẫn đóng gói để người dùng chọn; đây chưa phải APK server-only.

Các API/web/worker do phiên kiểm tra mở đã tắt để trả lại RAM; MySQL/XAMPP do người dùng bật vẫn để nguyên. Không nạp firmware hoặc đánh thức ESP32 trong nhiệm vụ server này. Không commit/push thay đổi hoặc cấu hình cloud/public hosting.
