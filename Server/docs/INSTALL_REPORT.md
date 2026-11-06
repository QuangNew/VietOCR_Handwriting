# Supabase / client server-only update — 03/11/2026

## Bổ sung tối ưu và worker CPU/iGPU

Không cài package/runtime mới trong lượt này, không tải model/CUDA/SDK/browser. Dùng lại .NET10, Node/npm, Chromium, Python và `onnxruntime-directml1.24.4` đã có trong `VietHandOCR_API_Release/.venv`. Tạo `Server/models/ML_s44/onnx/{vietocr_encoder.onnx,vietocr_decoder.onnx}` bằng hard link từ bộ FP32 đã xác minh trong archive (113.295.181 +39.524.467byte); không nhân đôi dữ liệu trọng số trên ổ đĩa. Manifest giữ cùng SHA checkpoint mới.

Build kiểm thử backend nằm tại `.toolchain/latency-final/bin/VietOcr.Server/release`; web tại `Server/web/.next-latency`; desktop launcher tại `VietHandOCR_API_Release/dist/VietOCR.exe`. API validation dùng riêng loopback5081, không thay listener5080/3000 người dùng đang mở. Web production assets được Playwright nạp trực tiếp và nối API thật; không coi đây là triển khai lên web đang chạy. `Run-Server.cmd` nay tự build web trước lúc khởi động. Không build Android trong lượt tối ưu này vì giao thức tương thích APK hiện tại. Số đo và giới hạn tại [PERFORMANCE.md](PERFORMANCE.md).

## Các thành phần của milestone Supabase

| Thành phần | Vị trí / thay đổi lần này |
| --- | --- |
| Supabase CLI 2.101.0 | Đã có tại npm user `%APPDATA%/npm`; dùng project đã link, không update/tải CLI mới. |
| PostgreSQL/Auth | Project `rrdxhztiikizgogxtlhu` trên Supabase; tạo các bảng/hàm `ocr_*`, RLS và quota. Không cài PostgreSQL/Docker lên máy. Google provider đã xác nhận bật. |
| Tài khoản/key cũ | Copy1admin và14API client/hash từ `vietocr_server` XAMPP. Bản MySQL gốc không xoá; lịch sử/job thử nghiệm cũ không chuyển. |
| C# runtime dependency | **Gỡ MySqlConnector** khỏi csproj; backend dùng HttpClient/.NET shared framework gọi Supabase RPC và Auth. |
| Flutter Supabase | Thêm `supabase_flutter2.18.3`, `supabase2.16.5`, `gotrue2.27.3`, các Dart libs/deep-link/url-launcher phụ thuộc. Cache tại `%LOCALAPPDATA%/Pub/Cache/hosted/pub.dev`; khoá phiên bản `Mobile/pubspec.lock`. |
| Android OCR | Gỡ ONNX dependency, private service `:ocr`, Java/Kotlin inference và model assets khỏi source/build client. Bản cũ lưu trong `Server/archive/local-clients/` (Git ignored), không đóng gói APK. |
| Desktop OCR | Gỡ local workers/device selection/predictors khỏi app; requirements chỉ ảnh/GUI/BLE. Giữ .venv CUDA cũ cho **server**; không tải torch/CUDA/model khác. |
| Credentials | Server secret trong `Server/server.local.json` có Windows ACL; Google session desktop DPAPI, Android Keystore. Public config chỉ URL + publishable key. |
| Build | .NET/Node/Flutter/JDK/Android SDK có sẵn; không cài SDK/NDK/browser mới. Gradle một worker, Xmx1536MiB; đã bổ sung các dependency Android nhỏ cho browser/Activity/Core/coroutines vào `%USERPROFILE%/.gradle/caches/modules-2/files-2.1` (khoảng5,24MiB file cache mới, không phải số liệu lưu lượng mạng đo trực tiếp). AGP8.13.2/Kotlin2.2.20 dùng bộ có sẵn. |
| Artifacts | `VietHandOCR_API_Release/dist/VietOCR.exe`, `Mobile/dist/VietOCR-arm64.apk`3.0.0+17, `Server/web/.next`, backend Release. |

Không mở firewall/router hoặc publish dịch vụ công khai. Phiên này sử dụng CLI Supabase sẵn có; không cài plugin Supabase mới. Các thay đổi/kiểm thử chỉ chạm schema `ocr_*` thuộc dự án. XAMPP tạm bật để đọc dữ liệu cũ, được tắt sau khi hoàn tất kiểm tra; không đổi cấu hình dịch vụ hệ thống.

## Báo cáo milestone trước (lịch sử)

# Đã dùng/cài gì và ở đâu

Thiết lập ngày 03/11/2026, host tự quản trên máy hiện tại.

| Thành phần | Vị trí / trạng thái |
|---|---|
| .NET SDK 10.0.114 | Có sẵn tại `C:\Program Files\dotnet`; dùng để build C#. Không tải SDK mới. Lần chạy CLI đầu tự tạo development HTTPS certificate; không cấu hình listener HTTPS hoặc trust công khai. |
| Node 22.21.1 / npm 11.12.1 | Có sẵn tại `C:\Program Files\nodejs`. |
| Next.js 16.4.4 / React 19.3.1 | Cài cục bộ trong `Server/web/node_modules`, khoá phiên bản bằng package-lock.json. |
| Agentation 3.1.2 | Dev dependency trong `Server/web/node_modules/agentation`; PolyForm Shield, không phải MIT. Không cài MCP hoặc sửa Codex config toàn cục. |
| TypeScript 5.9.3 / Playwright 1.64.1 | Dev dependencies cùng thư mục. Dùng Chromium đã có trong `%LOCALAPPDATA%/ms-playwright/chromium-1243`; không tải browser mới. Tổng node_modules trên đĩa khoảng 377 MiB, không đồng nghĩa lưu lượng tải mạng. |
| MySqlConnector 2.6.2 / test dependencies | NuGet cache tại `%USERPROFILE%\.nuget\packages`; project chỉ có một dependency runtime ngoài ASP.NET shared framework là MySqlConnector. Bản 2.5.0 thử ban đầu đã được thay trước khi bàn giao. |
| XAMPP / MariaDB 10.4.32 | Có sẵn tại `C:\Users\QuangNew\Downloads\Setup\xampp`, MySQL TCP 3306. Không cài lại hoặc thay cấu hình XAMPP toàn cục. |
| Database | Tạo `vietocr_server` trong XAMPP; bảng `admins`, `clients`, `jobs`. Tạo user `vietocr_app@127.0.0.1` chỉ cấp quyền trên DB này. Không sửa/xoá database khác. |
| DB config và admin đầu tiên | `Server/server.local.json`, `Server/runtime/admin-first-login.txt`; bỏ qua Git, ACL tài khoản Windows hiện tại. Không đưa mật khẩu vào README/log/command line. |
| Model / Python | Copy model cục bộ vào `Server/models/ML_s44`, kiểm SHA-256. Dùng `.venv` hiện có của desktop, PyTorch 2.14.1+cu126. Không tải lại model, CUDA hoặc torch. |
| Backend / web output | `Server/backend/VietOcr.Server/bin/Release/net10.0/`, `Server/web/.next/`. |
| Android / JDK / Flutter | Dùng toolchain đã có. Gradle chạy offline, một build worker, heap tối đa 1,5 GiB cho phiên build. Không tải Android SDK/NDK mới. Daemon mới do phiên build tạo đã tắt sau khi xong. |
| Bản build client | `VietHandOCR_API_Release/dist/VietOCR.exe`, `Mobile/dist/VietOCR-arm64.apk` (2.1.0+16). APK trước được backup. |

Không tự mở Windows Firewall, router port forwarding hoặc đưa dịch vụ lên Internet. Các endpoint chỉ được mở loopback để kiểm tra; dùng `Run-Server.cmd -Lan` khi muốn điện thoại cùng mạng kết nối. API/web/worker của phiên kiểm tra đã dừng, XAMPP vẫn do bạn quản lý.
