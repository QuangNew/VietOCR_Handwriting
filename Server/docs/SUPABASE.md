# Supabase, Google login và quản trị

Project hiện tại: `https://rrdxhztiikizgogxtlhu.supabase.co`.

Nhánh `refactor` triển khai Client → Pi → Server theo [kế hoạch đã duyệt](../../docs/REFACTOR_PLAN_2026-11-08.md). Các luồng app/API v1 bên dưới được giữ để đối chiếu trong chuyển đổi. Áp dụng các migration mới theo [runbook rollout](../../docs/REFACTOR_DB_ROLLOUT.md); build C# mới chỉ sẵn sàng nhận OCR sau khi database đã có policy 500/30. Không reset database/usage.

Database chính là **Supabase PostgreSQL**. Model ML_s44 vẫn chạy trên máy host bằng Python/PyTorch; Supabase không chạy model. Desktop và Android chỉ gọi API C#. Không có lựa chọn model offline hoặc fallback cục bộ.

## Google OAuth

Trong Google Cloud tạo OAuth client loại **Web application**. Authorized redirect URI:

```text
https://rrdxhztiikizgogxtlhu.supabase.co/auth/v1/callback
```

Nếu consent screen còn ở Testing, thêm Gmail dùng thử vào Test users. Trong Supabase → Authentication → Sign In / Providers → Google, bật Google và nhập Client ID/Secret. Không đưa Client Secret vào app hoặc Git.

Trong Supabase → Authentication → URL Configuration → Redirect URLs, thêm chính xác:

```text
http://127.0.0.1:47821/auth/callback
vn.pbl4.vietocr://auth/callback
```

Desktop dùng system browser + PKCE, listener chỉ bind `127.0.0.1:47821`, thời gian chờ 180 giây. Android dùng `supabase_flutter` + PKCE + deep link, trình duyệt ngoài. **Chỉ đăng nhập tài khoản Google của chính người dùng mới hoàn tất kiểm thử tương tác**; kiểm tra provider/HTTP redirect không chứng minh đã đăng nhập thành công trên thiết bị.

Phiên được mã hoá DPAPI trên Windows, Android Keystore AES256-GCM trên Android. Apps tự refresh access token. Không giữ API key dùng chung trong APK, không lưu Supabase service-role key trong web/app.

## Định danh cố định và hạn mức

Tài khoản Google gắn `auth.users.id` với một `ocr_id = ocr_<UUID bỏ dấu gạch>`. Định danh giữ nguyên khi đăng xuất, đăng nhập trên thiết bị khác, sửa tên hoặc sửa hạn mức. Đây là định danh công khai; access token có thời hạn mới chứng minh quyền sử dụng.

- Mặc định và mức tối đa trên nhánh refactor: **500 ảnh được nhận/ngày**, **30 request OCR được nhận trong cửa sổ trượt 60 giây**; admin có thể hạ từng tài khoản. Cần forward migration để áp dụng lên database hiện có.
- Ngày theo **Asia/Ho_Chi_Minh**, đặt lại lúc **00:00 giờ Việt Nam**.
- Cùng tài khoản dùng chung bộ đếm trên mọi thiết bị. Admin có thể hạ hạn mức riêng hoặc mặc định tài khoản mới.
- Postgres khoá hàng tài khoản, kiểm tra quota, ghi job và tăng bộ đếm trong **một transaction**.
- `Idempotency-Key` gửi lại cùng ảnh/layout trả job cũ, không trừ thêm lượt. Cùng key nhưng khác ảnh/layout trả `409`.
- Ảnh đã được nhận vào queue vẫn tính một lượt khi thất bại, huỷ hoặc timeout. Upload bị từ chối trước admission không tính. Polling, xem lịch sử và trạng thái không trừ lượt OCR.
- Dọn lịch sử không đặt lại bộ đếm trong ngày. Đổi tên, khoá/mở và rotate API key dịch vụ cũng không đặt lại quota.
- Hết quota trả `429` và `Retry-After`. App giữ các ảnh còn lại để người dùng thử tiếp; không tự chạy model local.

API key `voc_…` cũ vẫn dành cho tích hợp dịch vụ do admin cấp. Hash cũ đã được chuyển sang Supabase; không thể xem lại plaintext key. Admin có thể sửa tên/quota/khoá/mở hoặc cấp lại secret; việc cấp lại không đổi ID dịch vụ.

## Quyền quản trị trên web

| Mục | Điều chỉnh được |
| --- | --- |
| Tài khoản & API | Tìm/lọc Gmail hoặc dịch vụ; sửa tên, quota phút/ngày; khoá/mở; tạo/rotate API key dịch vụ |
| Cấu hình server | Bật/tắt nhận request; tạm dừng phân phối queue; tổng queue và queue/tài khoản; timeout; thời gian lưu kết quả |
| Tài nguyên | RAM/VRAM dự phòng; dự toán worker; số worker khi khởi động; dung lượng upload, pixel, spool |
| WorkerSpace | Thêm worker có kiểm tra phần cứng, dừng sau công việc đang chạy |
| Hàng đợi | Xem lỗi/kết quả từng job, huỷ riêng hoặc huỷ toàn bộ job chưa chạy |
| Nhật ký quản trị | 200 thay đổi gần nhất; lưu 90 ngày; không chứa secret |

Cấu hình lưu Supabase và có hiệu lực ngay trừ **initialWorkers** áp dụng khi khởi động lại, **maxPixels** cần thay worker đang nạp. Tăng dự toán tài nguyên không bỏ qua phép đo RAM/VRAM. Đường dẫn executable và secret không cho sửa qua browser.

Admin web vẫn đăng nhập bằng tài khoản quản trị riêng. Đăng nhập Google trong client **không cấp quyền admin**. Cookie HttpOnly và CSRF bảo vệ endpoint admin; JWT/API key client không truy cập được chúng.

## Schema và dữ liệu

Migration: [`../../supabase/migrations/202611030001_ocr_control.sql`](../../supabase/migrations/202611030001_ocr_control.sql).

Các migration bổ sung `202611090001`–`003` giữ dữ liệu cũ, thêm xác minh Google OAuth AMR/session, quota reservation/lease và quyền riêng gateway/compute. Mã nguồn migration mới đã được kiểm thử trên database tạm; không suy ra đã được áp dụng production. Xem [tiến độ](../../docs/REFACTOR_PROGRESS.md).

Các bảng `ocr_*` lưu admin, tài khoản, key hash, jobs/kết quả, quota, cấu hình, lease coordinator và audit. RLS bật trên tất cả bảng. Tài khoản authenticated chỉ đọc kết quả/usage và các cột identity được phép của chính mình. Không được sửa quota/job, đọc key hash hoặc gọi RPC backend. Secret service-role chỉ dùng trong API C#.

Ảnh gốc tạm nằm trên máy host, xoá sau xử lý/huỷ. Kết quả và metadata nằm trên Supabase; retention mặc định 24 giờ, chỉnh trên web. Lịch sử cloud xem trong mục Tài khoản & OCR Server ở cả hai app. Ảnh đang soạn/crop và phần sửa văn bản chưa xuất là cache trên thiết bị; chưa upload cả thư viện ảnh hoặc đồng bộ các chỉnh sửa bản nháp. Android tách cache theo tài khoản; desktop xoá danh sách khi rời tài khoản đã đăng nhập.

Một coordinator giữ lease PostgreSQL với heartbeat riêng, kể cả khi đang nạp nhiều model. Mất lease thì dừng xử lý để tránh hai máy cùng chạy lại queue. Đây là mô hình **một host xử lý**, không phải cluster lưu ảnh dùng chung.

## Khởi tạo trên máy khác

Đăng nhập/link Supabase CLI trước. Script không in secret:

```powershell
supabase login
supabase link --project-ref rrdxhztiikizgogxtlhu
Server/tools/Setup-Server.ps1 -SkipInstall
```

Chỉ với database mới, chạy migration một lần qua SQL Editor hoặc CLI:

```powershell
supabase db query --linked --file supabase/migrations/202611030001_ocr_control.sql
```

`server.local.json` bị Git bỏ qua và giới hạn quyền Windows. Public/publishable config cho hai app được sinh tại `desktop/cloud_config.json` và `Mobile/assets/config/supabase.json`. Đổi project cần sinh lại config rồi build APK.

Máy này đã chuyển **1 admin và 14 client cũ** từ XAMPP; database XAMPP gốc không xoá. Công việc/lịch sử thử nghiệm cũ vẫn nằm trong XAMPP, không chuyển ảnh/queue thử nghiệm cũ sang hệ thống mới.

## Nguồn chính thức

- [Google OAuth](https://supabase.com/docs/guides/auth/social-login/auth-google)
- [Redirect URLs](https://supabase.com/docs/guides/auth/redirect-urls)
- [PKCE](https://supabase.com/docs/guides/auth/sessions/pkce-flow)
- [JWT validation](https://supabase.com/docs/guides/auth/jwts)
- [Flutter OAuth](https://supabase.com/docs/reference/dart/auth-signinwithoauth)
