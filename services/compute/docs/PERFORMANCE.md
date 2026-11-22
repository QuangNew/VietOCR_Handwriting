# Độ trễ, thiết bị và phân chia worker — 03/11/2026

Đã đo qua API C# thật, Supabase thật và model ML_s44 trên máy RTX4050/16GB RAM. Đây là phép đo nhỏ bằng ảnh mẫu, không phải cam kết thời gian cho mọi ảnh.

| Phép đo | Trước | Sau |
| --- | --- | --- |
| Thời gian client trung bình, 4 lượt trên 2 ảnh dòng chữ | 2.311ms | 1.615ms |
| SDK đợi kết quả | Ngủ 1s rồi GET | Long poll tối đa 2s, trả ngay khi hoàn tất |
| Chọn worker rảnh | Worker đầu tiên trong danh sách | Luân phiên tất cả worker đủ điều kiện |
| 4 request thử chia tải | — | 2 worker, mỗi worker nhận 2 ảnh |

Giảm khoảng30% thời gian client trong bộ mẫu. Chữ nhận diện có cùng SHA-256 trước/sau. Báo cáo gốc: [`latency-before.json`](../validation/latency-before.json), [`latency-after.json`](../validation/latency-after.json), [`dispatch-after.json`](../validation/dispatch-after.json). Cả hai lượt SDK đều gửi JPEG gốc. Chúng dùng service key kiểm thử; **không bao gồm HTTP xác thực Google**, và không đồng nhất với độ trễ 4s/ảnh người dùng đo trước đó.

Đo bổ sung trên adapter desktop thật: 4 ảnh lần lượt so với tối đa2 request đồng thời, giữ nguyên kết quả. [`desktop-dispatch.json`](../validation/desktop-dispatch.json) ghi thời gian toàn lô và số request. Đây cũng là service key kiểm thử, không phải phiên Google trên thiết bị. Không quy toàn bộ mức cải thiện thành tốc độ tính toán GPU; upload, auth/DB và chờ kết quả đều có thể chồng thời gian khi chạy đồng thời.

## Các thay đổi

- Bỏ một lượt đọc Supabase dư trước admission; transaction PostgreSQL vẫn kiểm tra idempotency, quota, queue/spool và ghi job nguyên tử.
- HTTP chờ tín hiệu hoàn tất; tín hiệu chỉ giữ ID của job đang chờ. Kết quả vẫn đọc từ database sau khi kiểm tra chủ sở hữu. Hết thời gian HTTP không huỷ model hoặc người đang đợi khác.
- Queue luân phiên tài khoản, FIFO trong từng tài khoản; bộ điều phối luân phiên worker đang rảnh, bỏ qua worker đang bận hoặc draining. Worker nhanh tiếp tục nhận việc khi worker chậm còn chạy. Một ảnh dùng một worker.
- Desktop giới hạn số ảnh đồng thời bằng `min(4, readyWorkers)`, không gửi cả thư viện cùng lúc. Mỗi request có transport riêng, dùng chung phiên đăng nhập có khoá refresh. Dừng sẽ ngừng gửi ảnh mới và huỷ các job đang gửi/chờ. Kết quả gắn vào đúng ID ảnh; thanh tiến độ tính tổng phần hoàn tất nên không chạy lùi khi kết quả đến khác thứ tự.
- Desktop gửi file nguồn trực tiếp thay vì decode rồi nén lại PNG. Ảnh chỉnh sửa/đen trắng vẫn được gửi từ file làm việc tương ứng. Giữ nguyên xử lý EXIF trên server.
- UI admin dành chỗ cho tài khoản/logout; phần điều hướng có thể cuộn khi browser zoom/cửa sổ thấp. Canvas trống và chú thích dưới “Ảnh gốc” mở hộp chọn ảnh; ảnh đã có vẫn mở xem chi tiết.

## CPU, GPU và giới hạn thực

WorkerSpace cho phép chọn riêng `auto`, `cpu`, hoặc ID thiết bị thật từ `/api/admin/devices`. Tự động thử GPU rời CUDA, GPU tích hợp DirectML, rồi CPU. Chọn thiết bị cụ thể sẽ không âm thầm chạy sang thiết bị khác. CPU không cần NVIDIA/VRAM nhưng vẫn cần RAM dự phòng.

Đã nhận diện cùng ảnh mẫu trên CPU (~826ms), Intel UHD qua DirectML (~1.055ms) và CUDA; kết quả khớp baseline. CPU/iGPU không nhất thiết nhanh hơn CUDA cho một ảnh. DirectML dùng bản xuất **FP32**, cùng hash checkpoint và V2c64px với model server. Thăm dò DXGI chạy riêng, không tạo các D3D12 device không liên quan trong process model. Đã kiểm tra lại riêng việc khởi tạo DirectML: ready sau5,45s, RAM khoảng805MiB.

Các lần kiểm tra sau đó máy giảm RAM trống; việc thêm nhiều worker bị giới hạn tài nguyên và một lượt khởi tạo iGPU thất bại. Không hạ dự phòng để ép tạo worker. Lỗi khởi tạo được ghi rõ trong log và trả lỗi có kiểm soát. Báo cáo chia tải thành công chứng minh thuật toán trong lúc đủ RAM, không có nghĩa máy luôn tạo thêm được worker. Dung lượng checkpoint75MB không phải lượng RAM/VRAM thực của một worker.

Khi xác nhận lease Supabase tạm thất bại, host dừng admission/dispatch, thử lại trong cửa sổ lease còn hợp lệ. Phiên được thu hồi sau30s chưa xác nhận, trước TTL45s; host khởi tạo lại và khôi phục worker/job. Không chạy vô thời hạn khi mất quyền điều phối. Đã kiểm tra logic/build và vận hành với Supabase thật; chưa cố tình cắt Internet dài hạn để đo phục hồi.

## Kiểm tra và bản build

- Backend: 31 unit tests; 12 kiểm tra API thật gồm quyền sở hữu với long poll, idempotency chỉ trừ một credit, kết quả model và thu hồi key.
- Desktop: 178 kiểm tra toàn bộ; nhóm UI38 kiểm tra đã chạy lại riêng sau khi sửa tiến độ.
- Web: TypeScript sạch, Next production build thành công, 4 Playwright tests qua; kiểm tra account/footer ở viewport1235×643 và1024×500. Playwright dùng trực tiếp HTML/JS/CSS đã build với API thật5081, không thay web đang mở trên3000.
- Desktop launcher đã build lại: `VietHandOCR_API_Release/dist/VietOCR.exe`. Launcher dùng source và môi trường hiện có, không phải gói portable.
- Backend validation Release: `.toolchain/latency-final/bin/VietOcr.Server/release`. Web validation: `Server/web/.next-latency`. Android không thay mã/giao thức nên không build APK trong lượt này.

Các key kiểm thử được thu hồi theo đúng ID đã tạo. Không cài runtime/package mới và không tải model/SDK lớn. Bộ ONNX hiện có được hard-link vào thư mục model của **server**, không đưa trở lại client.

Đóng cửa sổ server cũ rồi chạy `Server/Run-Server.cmd -Lan` để áp dụng backend/web mới; script tự build trước khi chạy. Mở lại desktop để nạp source mới. Các listener5080/3000 đang mở của người dùng được giữ nguyên; API kiểm thử5081 được dừng sau khi kiểm tra. Chi tiết vị trí ở [INSTALL_REPORT.md](INSTALL_REPORT.md).
