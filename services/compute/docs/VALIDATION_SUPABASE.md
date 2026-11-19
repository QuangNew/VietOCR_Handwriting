# Kiểm chứng server-only / Supabase — 03/11/2026

Kiểm tra trên Windows, RTX4050 Laptop6GB, RAM16GB. Model ML_s44 giữ checkpoint SHA-256 `644f2613046e4974c3aea5878e61d119b9100debe05cb55756b85b8241254cb2`, runtime FP32/V2c64px. Không tải model/CUDA/SDK/browser mới.

| Phần | Kết quả thực |
| --- | --- |
| Backend | Release build0warning/0error; **21tests** qua, gồm hard quota caps, validation tài nguyên, fair queue và mật khẩu/hash |
| Desktop | **168tests** của suite client qua; sau đó thêm **3tests PKCE** qua: HTTP callback thật trên loopback, exchange, DPAPI, phục hồi phiên, huỷ/đóng listener |
| Android | **87tests unit/widget** qua; analyzer không có vấn đề; Release arm64 build thành công |
| Web | Production Next.js build và TypeScript qua; **4Playwrighttests** qua trên browser có sẵn: login/CSRF, responsive, edit key, lưu cấu hình và reload, audit |
| Supabase thật | **70admissions đồng thời → 60accepted,10minute_quota**; idempotency chỉ trừ1lượt; daily limit và timezone; khoá tài khoản; anonymous bị chặn |
| RLS | Transaction fixture rồi rollback: authenticated accountA chỉ đọc kết quả/identityA, không đọc hash, không sửa quota, không execute backend RPC |
| API thật | **11checks** qua với database Supabase: xác thực, CSRF, idempotency/conflict, ownership, cancel, dọn ảnh, metrics và revoke |
| Model thật | Worker GPU xử lý ảnh qua C#; `succeeded`, width2048/height230; inference537,8ms, total1948,6ms ở lần đo này (gồm database/cloud latency, không phải benchmark throughput) |
| Production transports | Desktop adapter và Dart SDK gửi multipart/poll qua C# + worker thật, cùng văn bản tiếng Việt (lưu hash, không ghi nội dung). Desktop không importtorch hoặc spawnmodel |
| Google config | ProviderGoogle bật, anonymouslogin tắt; Supabase chọn đúng cả hai callback desktop/Android sau khi người dùng bổ sung Android redirect |
| APK | **3.0.0+17**, **21.357.162byte ≈20,37MiB**, từ144.153.014byte ≈137,48MiB: **giảm85,18%**; không có ONNX/PTH/tensor/modelassets/ONNXruntime/`:ocr`; signaturev2 và ELF/ZIP16KiB alignment đạt |

APK: `Mobile/dist/VietOCR-arm64.apk`, SHA-256 `3f87c918ccd25061a33f9541b5fe64ab9f4577393e98fac13b1248d048bb803e`. Desktop launcher `VietHandOCR_API_Release/dist/VietOCR.exe`847.364byte; dùng source/Python cùng thư mục, không phải gói portable độc lập.

Reports:

- [`../validation/server-only-builds.json`](../validation/server-only-builds.json)
- [`../validation/supabase-policy-checks.json`](../validation/supabase-policy-checks.json)
- [`../validation/rls-account-isolation.sql`](../validation/rls-account-isolation.sql)
- [`../validation/supabase-api-checks.json`](../validation/supabase-api-checks.json)
- [`../validation/supabase-model-checks.json`](../validation/supabase-model-checks.json)
- [`../validation/supabase-app-transports.json`](../validation/supabase-app-transports.json)
- [`../validation/google-callback-checks.json`](../validation/google-callback-checks.json)
- [`../../Mobile/validation.json`](../../Mobile/validation.json)
- Screenshots: `validation/ui/supabase-api-edit.png`, `supabase-settings-desktop.png`, `supabase-settings-mobile.png`.

Giới hạn: **chưa cài APK mới lên điện thoại thật, chưa hoàn tất đăng nhập tài khoản Google tương tác thật**. PKCE desktop được kiểm thử với callback/token endpoint giả lập; cấu hình redirect/provider được kiểm tra trực tiếp Supabase. Role RLS dùng fixture SQL trong transaction rollback, không coi đó là Google login thật. Chưa benchmark nhiều worker/cloud load dài hạn; tính17worker theo dung lượng file không phải số worker đã thử. Ảnh/draft trên thiết bị chưa đồng bộ Supabase Storage; chỉ job/kết quả/history/identity/quota là dữ liệu cloud chính.

Fixture quota/API mới đã dọn; giữ nguyên14identity/hash cũ đã migrate, tài khoảnadmin và cấu hình vận hành. DatabaseXAMPP gốc không xoá. Các tiến trình API/web/model và Gradle do phiên này tạo đã dừng sau kiểm tra để trả RAM; không dừng daemonFlutter/IDE của người dùng.
