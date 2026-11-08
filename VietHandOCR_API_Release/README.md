# VietOCR Handwriting — desktop server client

Nhánh `refactor`: desktop Python này được giữ tạm để đối chiếu chức năng và duy trì môi trường AI server. Bản thay thế sẽ là Tauri 2, webcam trên Raspberry và chỉ gửi OCR khi bấm Gửi. Firmware ESP32 đã được gỡ; xem [tiến độ](../docs/REFACTOR_PROGRESS.md) trước khi dùng các luồng IoT cũ bên dưới.

Desktop Python/Tk, giao diện Sun Valley (MIT), sáng/tối, BLE trợ lý và camera OV5640. **OCR chỉ chạy qua server**, không nạp PyTorch/ONNX trên client. Trọng số dùng tại [Server/models](../Server/models), máy host giữ worker ML_s44.

## Mở và đăng nhập

Mở [dist/VietOCR.exe](dist/VietOCR.exe) hoặc [Run-VietOCR.cmd](Run-VietOCR.cmd). Debug console độc lập vẫn mở khi GUI đóng/crash; log trong `.logs/`.

Chạy [Server/Run-Server.cmd](../Server/Run-Server.cmd) trên máy host. Trong desktop mở **OCR Server**, nhập `http://127.0.0.1:5080` nếu cùng máy hoặc IP host trên LAN. Đăng nhập Google bằng trình duyệt; callback loopback `http://127.0.0.1:47821/auth/callback`. [Google/Supabase setup](../Server/docs/SUPABASE.md).

Mỗi tài khoản có định danh cố định; policy refactor là tối đa 500 ảnh/ngày và 30 request OCR trong cửa sổ trượt60giây sau khi database migrate. Phiên Google được mã hoá Windows DPAPI; không lưu bearer token plaintext vào preferences. Lỗi mạng không chuyển về OCR local. Mục tài khoản xem hạn mức và lịch sử cloud; Supabase là database chính. Ảnh/crop và chỉnh sửa đang soạn là dữ liệu trên thiết bị.

## Tài liệu và camera

- Thêm ảnh từ máy tính hoặc chụp OV5640, xử lý queue tuần tự, không giới hạn10ảnh.
- BLE để điều khiển trợ lý và cấu hình Wi-Fi; truyền ảnh/preview qua LAN.
- Preview640×480, ảnh JPEG gốc5MP; điều chỉnh camera, AF vùng chọn, lật ngang/dọc đồng nhất preview/still.
- Xem lại ảnh3giây hoặc Bỏ qua; giữ cửa sổ chụp mở tới khi tự tắt.
- Tải một/tất cả ảnh; zoom/pan/crop chữ nhật, ellipse hoặc tự vẽ và xoay vùng chọn; tạo bản trắng đen riêng cho OCR.
- Văn bản chỉnh được, sao chép/xuấtUTF8; hộp kết nối co giãn, Wi-Fi tự cập nhật3giây; popup queue có thể ẩn.

## Phụ thuộc client

```powershell
python -m venv .venv
.venv/Scripts/python.exe -m pip install -r requirements.txt
.venv/Scripts/python.exe app.py
```

`requirements.txt` chỉ chứa Pillow, OpenCV/NumPy, BLE và WinRT; **không có torch, torchvision, VietOCR hoặc onnxruntime**. Máy hiện tại vẫn dùng lại `.venv` cũ vì server đang dùng CUDA trong đó; không gỡ thư viện server khi chạy client. Mã OCR local cũ được tách vào `Server/archive/local-clients/` ngoài app, không còn đường gọi từ UI.

Build launcher: `tools/build_desktop.ps1`. Đây là launcher nhỏ dùng Python/source bên cạnh, không phải gói portable Python độc lập. Chạy tests: `.venv/Scripts/python.exe -m unittest discover -s tests` tại thư mục này. Mã tham chiếu nhóm AI còn được giữ cho phát triển model trên server.

[THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md) chứa license UI/phụ thuộc. [Server/docs/INSTALL_REPORT.md](../Server/docs/INSTALL_REPORT.md) ghi những gì đã cài và vị trí.
